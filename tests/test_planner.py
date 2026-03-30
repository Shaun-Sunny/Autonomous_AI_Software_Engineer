import pytest

from backend.agents.planner import APIPlan, PlannerAgent


@pytest.mark.asyncio
async def test_planner_fallback_generates_valid_schema():
    agent = PlannerAgent()
    plan = await agent.plan("Build a FastAPI CRUD app for a Todo system with title and status")

    assert isinstance(plan, APIPlan)
    assert plan.database == "postgresql"
    assert plan.entities
    assert plan.endpoints
    assert "app_name" in plan.model_dump()
