# Autonomous API Engineer

Autonomous API Engineer is a FastAPI-based orchestrator that takes plain-English API requests and executes a full lifecycle pipeline:

1. Plan API architecture from natural language
2. Generate complete FastAPI app files
3. Build and run generated code in Docker
4. Retry debugging up to 4 times on failures
5. Push generated app code to GitHub
6. Trigger deployment on Railway
7. Stream live logs to a browser via SSE

## Architecture

```mermaid
flowchart LR
  A[Frontend: HTML + JS] -->|POST /generate| B[FastAPI Orchestrator]
  B --> C[Planner Agent]
  B --> D[Code Generator Agent]
  B --> E[Docker Executor]
  E -->|Failure Logs| F[Debug Agent]
  F --> E
  E -->|Success| G[Deployment Agent]
  G --> H[GitHub API]
  G --> I[Railway API]
  B --> J[(PostgreSQL/Supabase)]
  B --> K[/metrics]
  K --> L[Prometheus]
```

## Project Structure

- `backend/main.py`: Orchestration API, SSE logs, status endpoints
- `backend/agents/planner.py`: LLM planning + strict JSON validation
- `backend/agents/generator.py`: LLM code generation + deterministic fallback
- `backend/executor/docker_runner.py`: Docker build/run/health-check workflow
- `backend/agents/debugger.py`: File-level LLM debugging loop
- `backend/agents/deployer.py`: GitHub + Railway deployment flow
- `backend/db/models.py`: SQLAlchemy models for runs, logs, generated files
- `backend/observability/metrics.py`: Prometheus metrics
- `frontend/index.html`, `frontend/app.js`: Prompt UI + SSE terminal logs

## Setup

1. Create `.env` from `.env.example` and fill keys.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Start services:
   - `docker-compose up --build`
   - The orchestrator uses the host Docker engine via `/var/run/docker.sock` to build and run generated apps.
4. Open:
   - `http://localhost:8000`
   - `http://localhost:9090`

## API Endpoints

- `POST /generate`
- `GET /runs/{run_id}/status`
- `GET /runs/{run_id}/logs` (SSE)
- `GET /runs`
- `GET /metrics`

## Environment Variables

Defined in `.env.example`:

- `GROQ_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_KEY`
- `ORCHESTRATOR_DATABASE_URL`
- `GITHUB_TOKEN`
- `GITHUB_USERNAME`
- `RAILWAY_API_KEY`
- `RAILWAY_PROJECT_ID`
- `PROMETHEUS_PORT`

## CI/CD

GitHub Actions workflow in `.github/workflows/ci.yml`:

- Installs Python dependencies
- Runs pytest
- Builds Docker image
- Deploys to Railway on `main`

## Demo

Add demo GIF here:

`docs/demo.gif`
