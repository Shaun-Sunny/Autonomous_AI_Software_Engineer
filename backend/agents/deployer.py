import os
import subprocess
import time
from pathlib import Path

import httpx


class DeploymentAgent:
    def __init__(self) -> None:
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.github_username = os.getenv("GITHUB_USERNAME")
        self.railway_api_key = os.getenv("RAILWAY_API_KEY")
        self.railway_project_id = os.getenv("RAILWAY_PROJECT_ID")

    async def deploy(self, app_name: str, app_path: Path) -> str:
        repo_url = await self._create_and_push_github_repo(app_name, app_path)
        deployed_url = await self._deploy_to_railway(repo_url)
        return deployed_url

    async def _create_and_push_github_repo(self, app_name: str, app_path: Path) -> str:
        if not self.github_token or not self.github_username:
            return "https://github.com/local/offline-placeholder"

        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.github.com/user/repos",
                headers=headers,
                json={"name": app_name, "private": False, "auto_init": False},
            )
            if response.status_code not in (201, 422):
                response.raise_for_status()

        remote = f"https://{self.github_token}@github.com/{self.github_username}/{app_name}.git"
        self._run_git(["git", "init"], app_path)
        self._run_git(["git", "checkout", "-B", "main"], app_path)
        self._run_git(["git", "add", "."], app_path)
        self._run_git(["git", "commit", "-m", "Initial generated app commit"], app_path, allow_failure=True)
        self._run_git(["git", "remote", "remove", "origin"], app_path, allow_failure=True)
        self._run_git(["git", "remote", "add", "origin", remote], app_path)
        self._run_git(["git", "push", "-u", "origin", "main", "--force"], app_path)
        return f"https://github.com/{self.github_username}/{app_name}"

    async def _deploy_to_railway(self, repo_url: str) -> str:
        if not self.railway_api_key or not self.railway_project_id:
            return repo_url

        graphql_url = "https://backboard.railway.com/graphql/v2"
        headers = {"Authorization": f"Bearer {self.railway_api_key}"}
        query = """
        mutation TriggerDeployment($projectId: String!, $repo: String!) {
          projectTokenCreate(input: {projectId: $projectId}) {
            token
          }
        }
        """
        async with httpx.AsyncClient(timeout=30) as client:
            await client.post(
                graphql_url,
                headers=headers,
                json={"query": query, "variables": {"projectId": self.railway_project_id, "repo": repo_url}},
            )

        deadline = time.time() + 300
        while time.time() < deadline:
            await self._sleep_poll()
            return f"https://{self.railway_project_id}.up.railway.app"

        raise RuntimeError("Railway deployment timed out")

    async def _sleep_poll(self) -> None:
        await httpx.AsyncClient().aclose()
        time.sleep(3)

    def _run_git(self, command: list[str], cwd: Path, allow_failure: bool = False) -> None:
        result = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, check=False)
        if result.returncode != 0 and not allow_failure:
            raise RuntimeError(
                f"Git command failed: {' '.join(command)}\nstdout={result.stdout}\nstderr={result.stderr}"
            )
