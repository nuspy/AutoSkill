"""HTTP client for the AutoSkill server with retries and an offline queue for telemetry."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from autoskill_local.config import HOME


class ServerError(Exception):
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        code = body.get("error", {}).get("code") if isinstance(body, dict) else None
        message = body.get("error", {}).get("message") if isinstance(body, dict) else None
        super().__init__(f"{status} {code or ''} {message or ''}".strip())

    @property
    def code(self) -> str | None:
        return self.body.get("error", {}).get("code") if isinstance(self.body, dict) else None


class Client:
    def __init__(
        self,
        server_url: str,
        api_key: str | None = None,
        trial_token: str | None = None,
        timeout: float = 60.0,
        transport=None,
    ):
        self.base = server_url.rstrip("/") + "/api/v1"
        self.headers: dict[str, str] = {}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        if trial_token:
            self.headers["X-AutoSkill-Trial"] = trial_token
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self.queue_path = HOME / "queue.jsonl"

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict | None = None,
        headers: dict | None = None,
        retries: int = 3,
        timeout: float | None = None,
    ) -> Any:
        last: Exception | None = None
        for attempt in range(retries):
            try:
                res = self._http.request(
                    method,
                    self.base + path,
                    json=json_body,
                    params=params,
                    headers={**self.headers, **(headers or {})},
                    timeout=timeout,
                )
            except httpx.HTTPError as exc:
                last = exc
                time.sleep(min(2**attempt, 8))
                continue
            if res.status_code >= 500:
                last = ServerError(res.status_code, _safe_json(res))
                time.sleep(min(2**attempt, 8))
                continue
            if res.status_code >= 400:
                raise ServerError(res.status_code, _safe_json(res))
            if res.headers.get("content-type", "").startswith("application/json"):
                return res.json()
            return res.content
        assert last is not None
        raise last

    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, json_body: Any = None, **kw) -> Any:
        return self.request("POST", path, json_body=json_body, **kw)

    # --- offline queue for telemetry ------------------------------------------------

    def post_or_queue(self, path: str, json_body: Any, headers: dict | None = None) -> Any:
        try:
            result = self.post(path, json_body, headers=headers)
        except (httpx.HTTPError, ServerError) as exc:
            if isinstance(exc, ServerError) and exc.status < 500:
                raise
            self.queue_path.parent.mkdir(parents=True, exist_ok=True)
            with self.queue_path.open("a") as fh:
                fh.write(
                    json.dumps({"path": path, "body": json_body, "headers": headers or {}, "at": time.time()}) + "\n"
                )
            return {"queued": True}
        self.flush_queue()
        return result

    def flush_queue(self) -> int:
        if not self.queue_path.exists():
            return 0
        lines = self.queue_path.read_text().splitlines()
        remaining: list[str] = []
        sent = 0
        for line in lines:
            try:
                item = json.loads(line)
                self.post(item["path"], item["body"], headers=item.get("headers"), retries=1)
                sent += 1
            except ServerError as exc:
                if exc.status >= 500:
                    remaining.append(line)
            except Exception:  # noqa: BLE001
                remaining.append(line)
        if remaining:
            self.queue_path.write_text("\n".join(remaining) + "\n")
        else:
            self.queue_path.unlink(missing_ok=True)
        return sent


def _safe_json(res: httpx.Response) -> Any:
    try:
        return res.json()
    except ValueError:
        return {"error": {"code": "http_error", "message": res.text[:300]}}


def paths_from(config) -> Path:
    return Path(config)
