import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class DockerRunResult:
    success: bool
    logs: str
    url: str | None = None
    suspected_file: str | None = None
    retryable: bool = True


class DockerRunner:
    def __init__(self, startup_timeout: int = 30) -> None:
        self.startup_timeout = startup_timeout

    def _run(self, command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False)

    def _extract_file_from_logs(self, logs: str) -> str | None:
        match = re.search(r'File "/app/([^"]+)"', logs)
        return match.group(1) if match else None

    def _docker_unavailable_result(self, details: str) -> DockerRunResult:
        message = (
            "Docker is not available for execution.\n"
            "How to fix:\n"
            "1. Install Docker Desktop (includes the docker CLI).\n"
            "2. Start Docker Desktop and wait until the engine is running.\n"
            "3. Re-run generation.\n\n"
            f"Details:\n{details}"
        )
        return DockerRunResult(success=False, logs=message, retryable=False)

    def build_and_run(self, app_path: Path, image_tag: str) -> DockerRunResult:
        if shutil.which("docker") is None:
            return self._docker_unavailable_result("'docker' was not found in PATH.")

        docker_info = self._run(["docker", "info"], cwd=app_path)
        if docker_info.returncode != 0:
            details = f"STDOUT:\n{docker_info.stdout}\nSTDERR:\n{docker_info.stderr}"
            return self._docker_unavailable_result(details)

        build = self._run(["docker", "build", "-t", image_tag, "."], cwd=app_path)
        if build.returncode != 0:
            logs = f"Docker build failed\nSTDOUT:\n{build.stdout}\nSTDERR:\n{build.stderr}"
            return DockerRunResult(success=False, logs=logs)

        port = random.randint(18000, 18999)
        run = self._run(["docker", "run", "-d", "-p", f"{port}:8000", image_tag], cwd=app_path)
        if run.returncode != 0:
            logs = f"Docker run failed\nSTDOUT:\n{run.stdout}\nSTDERR:\n{run.stderr}"
            return DockerRunResult(success=False, logs=logs)

        container_id = run.stdout.strip()
        url = f"http://127.0.0.1:{port}"

        start = time.time()
        healthy = False
        health_error = ""
        while time.time() - start < self.startup_timeout:
            try:
                resp = httpx.get(f"{url}/docs", timeout=3)
                if resp.status_code == 200:
                    healthy = True
                    break
            except Exception as exc:  # noqa: BLE001
                health_error = str(exc)
            time.sleep(1)

        if healthy:
            self._run(["docker", "rm", "-f", container_id], cwd=app_path)
            return DockerRunResult(success=True, logs="Container started successfully", url=url)

        logs_result = self._run(["docker", "logs", container_id], cwd=app_path)
        self._run(["docker", "rm", "-f", container_id], cwd=app_path)
        combined = (
            f"Container failed health check after {self.startup_timeout}s. Last health error: {health_error}\n"
            f"STDOUT:\n{logs_result.stdout}\nSTDERR:\n{logs_result.stderr}"
        )
        return DockerRunResult(
            success=False,
            logs=combined,
            suspected_file=self._extract_file_from_logs(combined),
        )
