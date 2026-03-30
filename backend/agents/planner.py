import json
import os
import re
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

PLANNER_SYSTEM_PROMPT = (
    "You are an API architect. Given a plain English description of an API, output ONLY a valid JSON "
    "object with this exact schema — no explanation, no markdown, no extra text:\n"
    "{\n"
    '  "app_name": string (snake_case, no spaces),\n'
    '  "entities": [string],\n'
    '  "fields": { entity_name: [field_name_string] },\n'
    '  "endpoints": [string],\n'
    '  "database": "postgresql"\n'
    "}"
)


class APIPlan(BaseModel):
    app_name: str = Field(min_length=1)
    entities: list[str]
    fields: dict[str, list[str]]
    endpoints: list[str]
    database: str


class PlannerAgent:
    def __init__(self, model: str = "llama-3.3-70b-versatile") -> None:
        self.model = model
        self.groq_api_key = os.getenv("GROQ_API_KEY")

    def _extract_json(self, content: str) -> dict[str, Any]:
        trimmed = content.strip()
        if trimmed.startswith("```"):
            trimmed = re.sub(r"^```[a-zA-Z]*", "", trimmed).strip()
            trimmed = trimmed.rstrip("`").strip()
        return json.loads(trimmed)

    async def _call_llm(self, prompt: str) -> dict[str, Any]:
        if not self.groq_api_key:
            return self._fallback_plan(prompt)

        payload: dict[str, object] = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {self.groq_api_key}"}

        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            return self._extract_json(content)

    def _fallback_plan(self, prompt: str) -> dict[str, Any]:
        entity = "Todo" if "todo" in prompt.lower() else "Item"
        app_name = re.sub(r"[^a-z0-9]+", "_", prompt.lower()).strip("_")
        app_name = (app_name or "generated_api")[:40]
        fields = ["id", "title", "status"] if entity == "Todo" else ["id", "name", "status"]
        plural = f"{entity.lower()}s"
        return {
            "app_name": app_name,
            "entities": [entity],
            "fields": {entity: fields},
            "endpoints": [
                f"POST /{plural}",
                f"GET /{plural}",
                f"GET /{plural}/{{id}}",
                f"PUT /{plural}/{{id}}",
                f"DELETE /{plural}/{{id}}",
            ],
            "database": "postgresql",
        }

    async def plan(self, prompt: str, max_retries: int = 3) -> APIPlan:
        last_error: Exception | None = None
        for _ in range(max_retries):
            try:
                data = await self._call_llm(prompt)
                plan = APIPlan.model_validate(data)
                if plan.database.lower() != "postgresql":
                    raise ValueError("Planner must return database='postgresql'")
                return plan
            except (json.JSONDecodeError, ValidationError, ValueError, httpx.HTTPError) as exc:
                last_error = exc
        raise RuntimeError(f"Planner failed after {max_retries} attempts: {last_error}")
