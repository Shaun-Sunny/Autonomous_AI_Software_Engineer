import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents import CodeGeneratorAgent, DebugAgent, DeploymentAgent, PlannerAgent
from backend.db import GeneratedFile, Log, LogLevel, Run, RunStatus, SessionLocal, init_db
from backend.executor import DockerRunner
from backend.observability.metrics import (
    active_runs,
    retries_total,
    run_duration_seconds,
    runs_total,
    update_deploy_success_rate,
)

BASE_DIR = Path(__file__).resolve().parents[1]
GENERATED_ROOT = BASE_DIR / "generated_apps"
FRONTEND_DIR = BASE_DIR / "frontend"

@asynccontextmanager
async def lifespan(_: FastAPI):
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(title="Autonomous API Engineer", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

planner_agent = PlannerAgent()
generator_agent = CodeGeneratorAgent(output_root=GENERATED_ROOT)
debug_agent = DebugAgent()
deployer_agent = DeploymentAgent()
docker_runner = DockerRunner(startup_timeout=30)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=3)


class GenerateResponse(BaseModel):
    run_id: uuid.UUID


def write_log(db: Session, run_id: uuid.UUID, agent: str, message: str, level: LogLevel = LogLevel.info) -> None:
    db.add(Log(run_id=run_id, agent=agent, message=message, level=level))
    db.commit()


def set_status(db: Session, run: Run, status: RunStatus) -> None:
    run.status = status
    db.commit()


async def process_run(run_id: uuid.UUID, prompt: str) -> None:
    start = time.perf_counter()
    active_runs.inc()
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        if not run:
            return

        set_status(db, run, RunStatus.planning)
        write_log(db, run_id, "planner", "Starting plan generation")
        plan = await planner_agent.plan(prompt)
        run.app_name = plan.app_name
        db.commit()
        write_log(db, run_id, "planner", f"Plan ready for app '{plan.app_name}'")

        set_status(db, run, RunStatus.generating)
        write_log(db, run_id, "generator", "Generating application files")
        generated_files = await generator_agent.generate(plan)
        for filename, content in generated_files.items():
            db.add(GeneratedFile(run_id=run_id, filename=filename, content=content, version=1))
        db.commit()
        write_log(db, run_id, "generator", f"Generated {len(generated_files)} files")

        app_path = GENERATED_ROOT / plan.app_name
        set_status(db, run, RunStatus.executing)
        write_log(db, run_id, "executor", "Building and running Docker container")
        result = docker_runner.build_and_run(app_path, image_tag=f"{plan.app_name}:{run_id}")

        attempts: list[str] = []
        while not result.success and result.retryable and run.retry_count < 4:
            run.retry_count += 1
            db.commit()
            retries_total.inc()

            set_status(db, run, RunStatus.debugging)
            write_log(
                db,
                run_id,
                "debugger",
                f"Debug attempt {run.retry_count}/4 started",
                LogLevel.warning,
            )

            file_to_fix = result.suspected_file or "main.py"
            target = app_path / file_to_fix
            if not target.exists():
                target = app_path / "main.py"

            corrected = await debug_agent.fix_file(target, result.logs, attempts[-3:])
            attempts.append(corrected[:1000])
            db.add(
                GeneratedFile(
                    run_id=run_id,
                    filename=target.name,
                    content=corrected,
                    version=run.retry_count + 1,
                )
            )
            db.commit()
            write_log(db, run_id, "debugger", f"Patched {target.name}; rerunning Docker")

            set_status(db, run, RunStatus.executing)
            result = docker_runner.build_and_run(app_path, image_tag=f"{plan.app_name}:{run_id}")

        if not result.success:
            set_status(db, run, RunStatus.failed)
            write_log(db, run_id, "executor", result.logs, LogLevel.error)
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            runs_total.labels(status="failed").inc()
            update_deploy_success_rate(False)
            return

        write_log(db, run_id, "executor", "Container health check passed")
        set_status(db, run, RunStatus.deploying)
        write_log(db, run_id, "deployer", "Deploying generated app")
        deployed_url = await deployer_agent.deploy(plan.app_name, app_path)
        run.deployed_url = deployed_url
        run.completed_at = datetime.now(timezone.utc)
        set_status(db, run, RunStatus.success)
        write_log(db, run_id, "deployer", f"Deployment complete: {deployed_url}")
        runs_total.labels(status="success").inc()
        update_deploy_success_rate(True)
    except Exception as exc:  # noqa: BLE001
        run = db.get(Run, run_id)
        if run:
            run.status = RunStatus.failed
            run.completed_at = datetime.now(timezone.utc)
            db.commit()
            write_log(db, run_id, "orchestrator", f"Unhandled error: {exc}", LogLevel.error)
        runs_total.labels(status="failed").inc()
        update_deploy_success_rate(False)
    finally:
        duration = time.perf_counter() - start
        run_duration_seconds.observe(duration)
        active_runs.dec()
        db.close()


@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest, background_tasks: BackgroundTasks) -> GenerateResponse:
    db = SessionLocal()
    try:
        run_id = uuid.uuid4()
        app_name = "pending_app"
        run = Run(id=run_id, prompt=request.prompt, app_name=app_name, status=RunStatus.pending)
        db.add(run)
        db.commit()
        write_log(db, run_id, "orchestrator", "Run accepted")
        background_tasks.add_task(process_run, run_id, request.prompt)
        return GenerateResponse(run_id=run_id)
    finally:
        db.close()


@app.get("/runs/{run_id}/status")
def run_status(run_id: uuid.UUID) -> JSONResponse:
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        return JSONResponse(
            {
                "status": run.status.value,
                "deployed_url": run.deployed_url,
                "retry_count": run.retry_count,
            }
        )
    finally:
        db.close()


@app.get("/runs")
def list_runs() -> JSONResponse:
    db = SessionLocal()
    try:
        rows = db.execute(select(Run).order_by(Run.created_at.desc())).scalars().all()
        return JSONResponse(
            [
                {
                    "id": str(r.id),
                    "prompt": r.prompt,
                    "app_name": r.app_name,
                    "status": r.status.value,
                    "retry_count": r.retry_count,
                    "deployed_url": r.deployed_url,
                    "created_at": r.created_at.isoformat(),
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                }
                for r in rows
            ]
        )
    finally:
        db.close()


@app.get("/runs/{run_id}/logs")
async def stream_logs(run_id: uuid.UUID) -> StreamingResponse:
    async def event_stream():
        sent_ids: set[str] = set()
        while True:
            db = SessionLocal()
            try:
                run = db.get(Run, run_id)
                if not run:
                    yield "event: error\ndata: {\"message\": \"Run not found\"}\n\n"
                    break
                logs = db.execute(select(Log).where(Log.run_id == run_id).order_by(Log.timestamp.asc())).scalars().all()
                for log in logs:
                    key = str(log.id)
                    if key in sent_ids:
                        continue
                    sent_ids.add(key)
                    data = {
                        "agent": log.agent,
                        "level": log.level.value,
                        "message": log.message,
                        "timestamp": log.timestamp.isoformat(),
                    }
                    yield f"data: {json.dumps(data)}\n\n"
                if run.status in (RunStatus.success, RunStatus.failed):
                    yield f"event: done\ndata: {{\"status\": \"{run.status.value}\"}}\n\n"
                    break
            finally:
                db.close()
            await asyncio.sleep(1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/metrics")
def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/app.js")
def frontend_js() -> FileResponse:
    path = FRONTEND_DIR / "app.js"
    if not path.exists():
        raise HTTPException(status_code=404, detail="app.js not found")
    return FileResponse(path)


@app.get("/")
def index() -> FileResponse:
    path = FRONTEND_DIR / "index.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return FileResponse(path)


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "env": os.getenv("ENVIRONMENT", "local")})
