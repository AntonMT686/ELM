"""Minimal GitLab REST v4 client (standard library only, so it adds no offline dependency).

The access token lives in server configuration (ELM_GITLAB_TOKEN) and is sent only to the configured GitLab host. Callers
pass registered repositories only, so the browser can never make ELM call an arbitrary project or URL."""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.errors import AppError


class GitLabError(AppError):
    def __init__(self, message: str, *, status: int | None = None, details: dict | None = None):
        super().__init__(message, code="GITLAB_ERROR", status_code=502, details={**(details or {}), "gitlab_status": status})
        self.gitlab_status = status


@dataclass
class GitLab:
    base_url: str
    token: str
    timeout: int = 15

    @classmethod
    def from_settings(cls) -> GitLab:
        s = get_settings()
        if not s.gitlab_enabled:
            raise AppError("GitLab integration is switched off. Set ELM_GITLAB_ENABLED=true and the GitLab URL and token in .env.", code="GITLAB_DISABLED", status_code=409)
        if not s.gitlab_token:
            raise AppError("No GitLab access token is configured (ELM_GITLAB_TOKEN).", code="GITLAB_NOT_CONFIGURED", status_code=409)
        return cls(s.gitlab_url.rstrip("/"), s.gitlab_token, s.gitlab_timeout_seconds)

    # ------------------------------------------------------------ transport
    def _call(self, method: str, path: str, *, params: dict | None = None, body: dict | None = None):
        url = f"{self.base_url}/api/v4{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={"PRIVATE-TOKEN": self.token, "Accept": "application/json", **({"Content-Type": "application/json"} if data else {})})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 - host comes from server configuration only
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read() or b"{}")
            except ValueError:
                detail = {}
            msg = detail.get("message") or detail.get("error") or e.reason
            if isinstance(msg, (list, dict)):
                msg = json.dumps(msg)
            hint = {401: "The GitLab token is invalid or expired.", 403: "The GitLab token does not have permission for this action.", 404: "Not found in GitLab (check the project path and the token's access)."}.get(e.code, "")
            raise GitLabError(f"GitLab refused the request ({e.code}): {msg}. {hint}".strip(), status=e.code) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise GitLabError(f"GitLab is not reachable at {self.base_url}: {getattr(e, 'reason', e)}. Check that the GitLab container is running and ELM_GITLAB_URL.") from None

    @staticmethod
    def _pid(project: str) -> str:
        return urllib.parse.quote(str(project), safe="")

    # ------------------------------------------------------------ API used by ELM
    def version(self) -> dict:
        return self._call("GET", "/version")

    def project(self, id_or_path: str) -> dict:
        return self._call("GET", f"/projects/{self._pid(id_or_path)}")

    def branches(self, project: str, search: str | None = None) -> list[dict]:
        return self._call("GET", f"/projects/{self._pid(project)}/repository/branches", params={"search": search, "per_page": 100}) or []

    def branch(self, project: str, name: str) -> dict:
        return self._call("GET", f"/projects/{self._pid(project)}/repository/branches/{self._pid(name)}")

    def create_branch(self, project: str, name: str, ref: str) -> dict:
        return self._call("POST", f"/projects/{self._pid(project)}/repository/branches", params={"branch": name, "ref": ref})

    def commits(self, project: str, ref: str, limit: int = 50) -> list[dict]:
        return self._call("GET", f"/projects/{self._pid(project)}/repository/commits", params={"ref_name": ref, "per_page": limit}) or []

    def compare(self, project: str, base: str, head: str) -> dict:
        return self._call("GET", f"/projects/{self._pid(project)}/repository/compare", params={"from": base, "to": head, "straight": "false"})

    def merge_requests(self, project: str, source_branch: str | None = None, state: str | None = None) -> list[dict]:
        return self._call("GET", f"/projects/{self._pid(project)}/merge_requests", params={"source_branch": source_branch, "state": state, "per_page": 100}) or []

    def merge_request(self, project: str, iid: int | str) -> dict:
        return self._call("GET", f"/projects/{self._pid(project)}/merge_requests/{int(iid)}")

    def create_merge_request(self, project: str, source: str, target: str, title: str, description: str) -> dict:
        return self._call("POST", f"/projects/{self._pid(project)}/merge_requests", body={"source_branch": source, "target_branch": target, "title": title, "description": description, "remove_source_branch": False})

    # ------------------------------------------------------------ deployment (§14)
    def commit(self, project: str, sha_or_ref: str) -> dict:
        """Resolves a commit SHA, tag or branch to its commit."""
        return self._call("GET", f"/projects/{self._pid(project)}/repository/commits/{self._pid(sha_or_ref)}")

    def create_pipeline(self, project: str, ref: str, variables: dict[str, str]) -> dict:
        return self._call("POST", f"/projects/{self._pid(project)}/pipeline", body={"ref": ref, "variables": [{"key": k, "value": str(v)} for k, v in variables.items()]})

    def pipeline(self, project: str, pipeline_id: int | str) -> dict:
        return self._call("GET", f"/projects/{self._pid(project)}/pipelines/{int(pipeline_id)}")
