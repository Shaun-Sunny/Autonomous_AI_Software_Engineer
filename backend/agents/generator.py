import json
import os
from pathlib import Path

import httpx

from .planner import APIPlan

GENERATOR_SYSTEM_PROMPT = (
    "You are an expert FastAPI developer. Given an API plan as JSON, generate complete, production-ready "
    "Python files. Output ONLY the raw file contents — no explanation, no markdown code blocks. The code "
    "must be immediately runnable. Use SQLAlchemy for ORM, Pydantic for schemas, and PostgreSQL for the "
    "database. Include proper error handling and HTTP status codes on every endpoint."
)


class CodeGeneratorAgent:
    def __init__(self, output_root: Path, model: str = "llama-3.3-70b-versatile") -> None:
        self.output_root = output_root
        self.model = model
        self.groq_api_key = os.getenv("GROQ_API_KEY")

    async def generate(self, plan: APIPlan) -> dict[str, str]:
        app_dir = self.output_root / plan.app_name
        app_dir.mkdir(parents=True, exist_ok=True)

        files = await self._generate_files(plan)
        for name, content in files.items():
            (app_dir / name).write_text(content, encoding="utf-8")
        return files

    async def _generate_files(self, plan: APIPlan) -> dict[str, str]:
        if not self.groq_api_key:
            return self._fallback_files(plan)

        user_prompt = (
            "Return a JSON object with keys exactly: main.py, models.py, database.py, schemas.py, "
            "requirements.txt, Dockerfile, .env.example. Values must be full file contents as strings.\n"
            f"Plan:\n{plan.model_dump_json(indent=2)}"
        )
        payload: dict[str, object] = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": GENERATOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {self.groq_api_key}"}
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"].strip()
            generated = json.loads(content)
            required = {
                "main.py",
                "models.py",
                "database.py",
                "schemas.py",
                "requirements.txt",
                "Dockerfile",
                ".env.example",
            }
            missing = required.difference(generated.keys())
            if missing:
                raise RuntimeError(f"Generator output missing files: {sorted(missing)}")
            return {k: str(v) for k, v in generated.items()}

    def _fallback_files(self, plan: APIPlan) -> dict[str, str]:
        entity = plan.entities[0]
        entity_table = f"{entity.lower()}s"
        return {
            "database.py": """import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv(\"DATABASE_URL\") or os.getenv(\"SUPABASE_URL\")
if not DATABASE_URL:
    raise RuntimeError(\"Set DATABASE_URL or SUPABASE_URL before running the generated app\")
if DATABASE_URL.startswith(\"postgresql://\"):
    DATABASE_URL = DATABASE_URL.replace(\"postgresql://\", \"postgresql+psycopg://\", 1)
elif DATABASE_URL.startswith(\"postgres://\"):
    DATABASE_URL = DATABASE_URL.replace(\"postgres://\", \"postgresql+psycopg://\", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
""",
            "models.py": f"""from sqlalchemy import Boolean, Column, Integer, String

from database import Base


class {entity}(Base):
    __tablename__ = \"{entity_table}\"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    status = Column(Boolean, default=False, nullable=False)
""",
            "schemas.py": f"""from pydantic import BaseModel


class {entity}Base(BaseModel):
    title: str
    status: bool = False


class {entity}Create({entity}Base):
    pass


class {entity}Update({entity}Base):
    pass


class {entity}Out({entity}Base):
    id: int

    class Config:
        from_attributes = True
""",
            "main.py": f"""from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import {entity}
from schemas import {entity}Create, {entity}Out, {entity}Update

Base.metadata.create_all(bind=engine)

app = FastAPI(title=\"{plan.app_name}\")


@app.post(\"/{entity_table}\", response_model={entity}Out, status_code=status.HTTP_201_CREATED)
def create_item(payload: {entity}Create, db: Session = Depends(get_db)):
    item = {entity}(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.get(\"/{entity_table}\", response_model=list[{entity}Out])
def list_items(db: Session = Depends(get_db)):
    return db.query({entity}).all()


@app.get(\"/{entity_table}/{{item_id}}\", response_model={entity}Out)
def get_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query({entity}).filter({entity}.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=\"Not found\")
    return item


@app.put(\"/{entity_table}/{{item_id}}\", response_model={entity}Out)
def update_item(item_id: int, payload: {entity}Update, db: Session = Depends(get_db)):
    item = db.query({entity}).filter({entity}.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=\"Not found\")
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@app.delete(\"/{entity_table}/{{item_id}}\", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query({entity}).filter({entity}.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=\"Not found\")
    db.delete(item)
    db.commit()
""",
            "requirements.txt": "fastapi\nuvicorn\nsqlalchemy\npsycopg[binary]\npydantic\n",
            "Dockerfile": "FROM python:3.12-slim\nWORKDIR /app\nCOPY requirements.txt .\nRUN pip install --no-cache-dir -r requirements.txt\nCOPY . .\nEXPOSE 8000\nCMD [\"uvicorn\", \"main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n",
            ".env.example": "DATABASE_URL=postgresql://postgres:password@db:5432/app\nSUPABASE_URL=\nSUPABASE_KEY=\n",
        }
