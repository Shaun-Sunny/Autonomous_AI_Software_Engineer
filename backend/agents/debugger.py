import os
from pathlib import Path

import httpx

DEBUGGER_SYSTEM_PROMPT = (
    "You are a Python debugging expert. You will receive:\n"
    "1. An error log from a failed Docker container\n"
    "2. The contents of the file that caused the error\n"
    "3. A history of previous fix attempts (if any)\n\n"
    "Output ONLY the complete corrected file contents — no explanation, no markdown, no extra text. "
    "The fix must address the root cause, not just suppress the error."
)


class DebugAgent:
    def __init__(self, model: str = "llama-3.3-70b-versatile") -> None:
        self.model = model
        self.groq_api_key = os.getenv("GROQ_API_KEY")

    async def fix_file(
        self,
        file_path: Path,
        error_logs: str,
        previous_attempts: list[str],
    ) -> str:
        original = file_path.read_text(encoding="utf-8")
        if not self.groq_api_key:
            return original

        user_prompt = (
            "Error logs:\n"
            f"{error_logs}\n\n"
            "Current file content:\n"
            f"{original}\n\n"
            "Previous fix attempts:\n"
            f"{chr(10).join(previous_attempts) if previous_attempts else 'None'}"
        )
        payload: dict[str, object] = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": DEBUGGER_SYSTEM_PROMPT},
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
            corrected = response.json()["choices"][0]["message"]["content"].strip()
        file_path.write_text(corrected, encoding="utf-8")
        return corrected
