"""
ClickUp API v2 client with rate-limiting, retries, and pagination.
"""
from __future__ import annotations

import time
import logging
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

_BASE = "https://api.clickup.com/api/v2"
_MAX_TASKS_PER_PAGE = 100


class ClickUpClient:
    def __init__(self, api_token: str, requests_per_minute: int = 60):
        self._token = api_token
        self._min_interval = 60.0 / requests_per_minute
        self._last_request_time: float = 0.0

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": api_token,
            "Content-Type": "application/json",
        })

    # ── Rate limiter ─────────────────────────────────────────────────────────

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()

    # ── HTTP ──────────────────────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[dict] = None, retries: int = 3) -> Any:
        url = f"{_BASE}{path}"
        for attempt in range(retries):
            self._throttle()
            try:
                resp = self._session.get(url, params=params or {}, timeout=30)
            except requests.RequestException as exc:
                logger.warning("Request error (attempt %d/%d): %s", attempt + 1, retries, exc)
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 10))
                logger.warning("Rate limited. Waiting %ds…", retry_after)
                time.sleep(retry_after)
                continue

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError(f"Failed to GET {url} after {retries} attempts")

    # ── Space / Folder / List ─────────────────────────────────────────────────

    def get_folders(self, space_id: str, archived: bool = False) -> list[dict]:
        data = self._get(f"/space/{space_id}/folder", {"archived": str(archived).lower()})
        return data.get("folders", [])

    def get_lists(self, folder_id: str, archived: bool = False) -> list[dict]:
        data = self._get(f"/folder/{folder_id}/list", {"archived": str(archived).lower()})
        return data.get("lists", [])

    def get_list(self, list_id: str) -> dict:
        return self._get(f"/list/{list_id}")

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def get_tasks(
        self,
        list_id: str,
        include_closed: bool = True,
        subtasks: bool = True,
    ) -> list[dict]:
        """Fetch ALL tasks in a list (handles pagination automatically)."""
        all_tasks: list[dict] = []
        page = 0

        while True:
            params = {
                "include_closed": str(include_closed).lower(),
                "subtasks": str(subtasks).lower(),
                "page": page,
            }
            data = self._get(f"/list/{list_id}/task", params)
            batch: list[dict] = data.get("tasks", [])
            all_tasks.extend(batch)

            # ClickUp returns fewer than 100 items on the last page
            if len(batch) < _MAX_TASKS_PER_PAGE:
                break
            page += 1

        return all_tasks

    # ── Team members ─────────────────────────────────────────────────────────

    def get_members(self, team_id: str) -> list[dict]:
        data = self._get(f"/team/{team_id}/member")
        return data.get("members", [])
