"""
Entry point for the CI Dashboard refresh pipeline.

Run once:
  python src/main.py

Run on a schedule (Docker / background):
  REFRESH_INTERVAL_HOURS=4 python src/main.py
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
API_TOKEN  = os.getenv("CLICKUP_API_TOKEN", "")
SPACE_ID   = os.getenv("CLICKUP_SPACE_ID", "90154275110")
TEAM_ID    = os.getenv("CLICKUP_TEAM_ID",  "90151097204")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))
INTERVAL_H = float(os.getenv("REFRESH_INTERVAL_HOURS", "0"))  # 0 = run once
TEAM_MEMBERS = [m.strip().lower() for m in os.getenv("TEAM_MEMBERS", "").split(",") if m.strip()]

# Folder IDs inside CI Projects Space (hard-coded for stability)
PROJECTS_FOLDER_ID  = "90156514552"
INTERNAL_FOLDER_ID  = "90157620199"
SIDE_JOBS_FOLDER_ID = "90157449904"  # contains Sunlight Retention Policies etc.

# List name prefixes to skip (ClickUp separator rows / sprint meta-lists)
_SKIP_PREFIXES = ("---", "Sprint ", "Example")


# ── Core pipeline ─────────────────────────────────────────────────────────────

def run_once() -> None:
    from clickup_client import ClickUpClient
    from data_processor import classify_list, classify_from_tasks, process_project_list, get_task_category
    from html_generator import HtmlGenerator

    if not API_TOKEN:
        logger.error("CLICKUP_API_TOKEN is not set. Aborting.")
        sys.exit(1)

    client    = ClickUpClient(API_TOKEN)
    generator = HtmlGenerator()

    # ── Active / Waiting projects ─────────────────────────────────────────────
    client_project_folders = [PROJECTS_FOLDER_ID, SIDE_JOBS_FOLDER_ID]
    active_projects: list  = []
    waiting_projects: list = []

    for folder_id in client_project_folders:
        logger.info("Fetching project lists from folder %s …", folder_id)
        raw_lists = client.get_lists(folder_id)

        for lst in raw_lists:
            name = lst.get("name", "")

            # Skip separator rows and sprint meta-lists
            if any(name.strip().startswith(p) for p in _SKIP_PREFIXES):
                continue

            # Enrich with full list details (includes status.color)
            try:
                lst = client.get_list(lst["id"])
            except Exception as exc:
                logger.warning("Could not fetch list detail for '%s': %s", name, exc)

            initial_state = classify_list(lst)

            # Hard red (cancelled) → always skip, no need to fetch tasks
            if initial_state == "red":
                logger.info("  [RED ] %s — skipping (cancelled)", name)
                continue

            # Fetch tasks for all non-red lists
            logger.info("  [%s] %s", initial_state.upper()[:4], name)
            tasks = client.get_tasks(lst["id"], include_closed=True, subtasks=True)

            # Determine final state based on color; only green is skipped.
            if initial_state == "unknown":
                # No color set — treat as waiting, not active.
                state = "grey"
            elif initial_state == "green":
                # List marked complete — verify tasks are actually all closed
                open_count = sum(1 for t in tasks if get_task_category(t) != "complete")
                if open_count > 0:
                    logger.info("    → reclassified YELLOW (%d open tasks despite 'complete' label)", open_count)
                    state = "yellow"
                else:
                    state = "green"
            else:
                state = initial_state

            if state == "green":
                logger.info("    → skipping (green)")
                continue

            project = process_project_list(lst, tasks)

            # If TEAM_MEMBERS env var is set, only include projects with
            # at least one assignee matching the allowed team members.
            def _normalize_name(text: str) -> str:
                return " ".join(
                    token for token in text.lower().replace(".", " ").split() if token
                )

            def _build_team_tokens(member: str) -> tuple[set[str], str]:
                normalized = _normalize_name(member)
                tokens = set(normalized.split())
                short = " ".join([token[0] for token in normalized.split() if token])
                return tokens, short

            TEAM_TOKEN_DATA = [_build_team_tokens(m) for m in TEAM_MEMBERS]

            def _matches_team_member(value: str) -> bool:
                normalized = _normalize_name(value)
                value_tokens = set(normalized.split())
                normalized_no_space = normalized.replace(" ", "")
                for tokens, short in TEAM_TOKEN_DATA:
                    if not tokens:
                        continue
                    if tokens.issubset(value_tokens):
                        return True
                    if short and short in normalized_no_space:
                        return True
                    # match by first and last name tokens if both present
                    if len(tokens) >= 2:
                        first, last = list(tokens)[:2]
                        if first in value_tokens and last in value_tokens:
                            return True
                    # allow matching by first name only when the assignee is clearly a short form
                    if len(tokens) == 1 and next(iter(tokens)) in value_tokens:
                        return True
                return False

            def _project_has_team_member(proj: dict) -> bool:
                if not TEAM_MEMBERS:
                    return True

                for a in proj.get("assignees_raw", []):
                    for key in ("username", "email", "email_address", "emailAddress"):
                        val = a.get(key) or ""
                        if val and _matches_team_member(val):
                            return True
                    try:
                        from data_processor import format_assignee
                        short = format_assignee(a)
                        if _matches_team_member(short):
                            return True
                    except Exception:
                        pass

                for name in proj.get("assignees", []):
                    if name and _matches_team_member(name):
                        return True

                return False

            if not _project_has_team_member(project):
                logger.info("    → skipping project (no matching team member): %s", project.get("raw_name"))
                continue

            if state in ("unknown", "grey"):
                logger.info("    → waiting (%s)", state)
                waiting_projects.append(project)
            else:
                # yellow, red (if any slipped through) etc. count as active
                active_projects.append(project)

    logger.info(
        "Projects: %d active, %d waiting",
        len(active_projects), len(waiting_projects),
    )

    # ── Internal / R&D projects ───────────────────────────────────────────────
    logger.info("Fetching internal projects from folder %s …", INTERNAL_FOLDER_ID)
    internal_lists = client.get_lists(INTERNAL_FOLDER_ID)
    internal_projects: list = []

    for lst in internal_lists:
        name = lst.get("name", "")
        if any(name.strip().startswith(p) for p in _SKIP_PREFIXES):
            continue
        tasks = client.get_tasks(lst["id"], include_closed=True, subtasks=True)
        project = process_project_list(lst, tasks)
        if project["total_tasks"] > 0:
            internal_projects.append(project)

    # ── Team members ─────────────────────────────────────────────────────────
    # Engineers are derived from task assignees — no separate API call needed.
    members: list = []

    # ── Generate HTML ─────────────────────────────────────────────────────────
    logger.info("Generating HTML dashboard …")
    html = generator.generate(
        active_projects=active_projects,
        waiting_projects=waiting_projects,
        internal_projects=internal_projects,
        members=members,
        generated_at=datetime.now(tz=timezone.utc),
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUTPUT_DIR / "index.html"
    out_file.write_text(html, encoding="utf-8")

    logger.info("Dashboard written → %s", out_file.resolve())
    logger.info(
        "Summary: %d active | %d waiting | %d overdue | %d internal",
        len(active_projects),
        len(waiting_projects),
        sum(1 for p in active_projects if p["is_overdue"]),
        len(internal_projects),
    )


# ── Scheduler loop ────────────────────────────────────────────────────────────

def main() -> None:
    if INTERVAL_H <= 0:
        run_once()
        return

    logger.info("Running in daemon mode (every %.1f hours).", INTERVAL_H)
    while True:
        try:
            run_once()
        except Exception as exc:
            logger.exception("Pipeline failed: %s", exc)

        sleep_s = INTERVAL_H * 3600
        logger.info("Next refresh in %.1f hours. Sleeping …", INTERVAL_H)
        time.sleep(sleep_s)


if __name__ == "__main__":
    main()
