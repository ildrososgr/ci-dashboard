"""
Data processing: ClickUp API response → structured dashboard data.

Color → state mapping (set at ClickUp LIST level):
  Yellow  → Active / Running          → shown in "Active Projects"
  Grey    → Waiting to Start          → shown in "Waiting to Start"
  Green   → Complete                  → HIDDEN (excluded from dashboard)
  Red     → Stuck                     → HIDDEN (excluded from dashboard)
"""
from __future__ import annotations

import re
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


# ── Color helpers ─────────────────────────────────────────────────────────────

def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def _rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float, float]:
    rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
    cmax = max(rf, gf, bf)
    cmin = min(rf, gf, bf)
    delta = cmax - cmin

    if delta == 0:
        hue = 0.0
    elif cmax == rf:
        hue = 60 * (((gf - bf) / delta) % 6)
    elif cmax == gf:
        hue = 60 * ((bf - rf) / delta + 2)
    else:
        hue = 60 * ((rf - gf) / delta + 4)

    sat = 0.0 if cmax == 0 else delta / cmax
    return hue, sat, cmax


def classify_color(hex_color: Optional[str]) -> str:
    """
    Map a ClickUp list hex color to project state:
    'yellow', 'grey', 'green', 'red', or 'unknown'.
    """
    if not hex_color:
        return "unknown"
    try:
        r, g, b = _hex_to_rgb(hex_color)
    except (ValueError, IndexError):
        return "unknown"

    h, s, v = _rgb_to_hsv(r, g, b)

    if s < 0.15:           # Low saturation → grey
        return "grey"
    if 40 <= h < 80:       # Yellow / amber
        return "yellow"
    if 80 <= h < 170:      # Green
        return "green"
    if h >= 330 or h < 15: # Red / crimson
        return "red"
    # Orange (15-40) and blue/purple (170-330) → treat as yellow (active)
    return "yellow"


def classify_status_name(name: Optional[str]) -> str:
    """Classify a ClickUp list status name to project state."""
    if not name:
        return "unknown"
    n = name.lower().strip()

    if any(k in n for k in ("complete", "done", "finish", "closed", "archive")):
        return "green"
    if any(k in n for k in ("stuck", "block", "cancel", "abort")):
        return "red"
    if any(k in n for k in ("not start", "to do", "todo", "waiting", "pending", "queue", "backlog")):
        return "grey"
    # 'new', 'active', 'in progress', 'delayed', 'at risk', 'on hold' → yellow
    return "yellow"


def classify_list(list_data: dict) -> str:
    """
    Determine the project state from ClickUp list data.
    Returns 'yellow', 'grey', 'green', 'red', or 'unknown' (no status set).
    """
    status_obj = list_data.get("status") or {}

    color = status_obj.get("color")
    if color:
        result = classify_color(color)
        if result != "unknown":
            return result

    status_name = status_obj.get("status", "")
    if status_name:
        result = classify_status_name(status_name)
        if result != "unknown":
            return result

    return "unknown"  # No status set — caller should use classify_from_tasks()


def classify_from_tasks(tasks: list) -> str:
    """
    Fallback classification when a list has no color/status set.
    Uses task data to determine project state.

    Rules:
      • All tasks closed           → 'green'
      • Any task in-progress       → 'yellow'
      • All todo + any assigned    → 'yellow' (assigned but not started yet)
      • All todo + none assigned   → 'grey'   (waiting to start)
      • No tasks at all            → 'unknown' (empty list, skip)
    """
    if not tasks:
        return "unknown"

    cats = [get_task_category(t) for t in tasks]
    total    = len(cats)
    complete = cats.count("complete")
    in_prog  = cats.count("in_progress")

    if complete == total:
        return "green"
    if in_prog > 0:
        return "yellow"

    # All remaining tasks are "todo" — check if anything is assigned
    open_tasks = [t for t in tasks if get_task_category(t) != "complete"]
    any_assigned = any(len(t.get("assignees", [])) > 0 for t in open_tasks)
    return "yellow" if any_assigned else "grey"


# ── Name parsing ──────────────────────────────────────────────────────────────

def parse_list_name(raw: str) -> tuple[str, str]:
    """
    Parse "N.COMPANY | Project description" → (company, project).
    Also handles "COMPANY | description" and plain names.
    """
    # Strip leading ordinal prefix: "16.EUROMEDNET..." → "EUROMEDNET..."
    clean = re.sub(r"^\d+\.", "", raw).strip()

    if " | " in clean:
        left, right = clean.split(" | ", 1)
        return left.strip(), right.strip()

    return clean, clean


# ── Task categorisation ───────────────────────────────────────────────────────

# Statuses whose *name* suggests in-progress work
_IN_PROGRESS_KEYWORDS = frozenset(
    ("progress", "review", "active", "doing", "working", "testing", "qa", "staging")
)


def get_task_category(task: dict) -> str:
    """Return 'complete', 'in_progress', or 'todo'."""
    status = task.get("status") or {}
    stype = (status.get("type") or "").lower()
    sname = (status.get("status") or "").lower()

    if stype == "closed":
        return "complete"
    if stype == "open":
        return "todo"
    # stype == "custom" → inspect name
    if any(k in sname for k in _IN_PROGRESS_KEYWORDS):
        return "in_progress"
    return "todo"


# ── Date utilities ────────────────────────────────────────────────────────────

def parse_ms(ts) -> Optional[datetime]:
    """Parse a ClickUp millisecond timestamp to an aware UTC datetime."""
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
    except (ValueError, TypeError):
        return None


def fmt_date(dt: Optional[datetime], now: Optional[datetime] = None) -> str:
    if not dt:
        return "—"
    if now is None:
        now = datetime.now(tz=timezone.utc)
    year_suffix = f" '{str(dt.year)[2:]}" if dt.year != now.year else ""
    return f"{dt.strftime('%b')} {dt.day}{year_suffix}"


def fmt_date_overdue(dt: Optional[datetime], now: Optional[datetime] = None) -> str:
    base = fmt_date(dt, now)
    if base == "—":
        return base
    if now is None:
        now = datetime.now(tz=timezone.utc)
    return f"{base} (overdue)" if dt < now else base  # type: ignore[operator]


def is_overdue(dt: Optional[datetime]) -> bool:
    return bool(dt and dt < datetime.now(tz=timezone.utc))


# ── Assignee display ──────────────────────────────────────────────────────────

def format_assignee(user: dict) -> str:
    """Return 'FirstName L.' from a ClickUp user object."""
    username = (user.get("username") or user.get("email") or "").strip()
    parts = username.split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1][0]}."
    return parts[0] if parts else "?"


def get_initials(display_name: str) -> str:
    parts = display_name.split()
    if len(parts) >= 2:
        return f"{parts[0][0]}{parts[1][0]}".upper()
    return display_name[:2].upper() if display_name else "?"


# ── Project aggregation ───────────────────────────────────────────────────────

def process_project_list(list_data: dict, tasks: list) -> dict:
    """Convert a ClickUp list + its tasks into a unified project record."""
    now = datetime.now(tz=timezone.utc)
    raw_name = list_data.get("name", "")
    company, project_desc = parse_list_name(raw_name)

    complete, in_prog, todo = [], [], []
    for task in tasks:
        cat = get_task_category(task)
        if cat == "complete":
            complete.append(task)
        elif cat == "in_progress":
            in_prog.append(task)
        else:
            todo.append(task)

    total = len(tasks)
    progress = round(len(complete) / total * 100) if total else 0

    start_dt = parse_ms(list_data.get("start_date"))
    due_dt   = parse_ms(list_data.get("due_date"))

    # Unique assignees across all tasks
    assignee_map: dict[int, dict] = {}
    for task in tasks:
        for a in task.get("assignees", []):
            uid = a.get("id")
            if uid and uid not in assignee_map:
                assignee_map[uid] = a

    assignees_raw     = list(assignee_map.values())
    assignees_display = [format_assignee(a) for a in assignees_raw]

    # Status label (list-level status name, or derived)
    list_status  = list_data.get("status") or {}
    status_label = (list_status.get("status") or "").strip()
    if not status_label:
        if is_overdue(due_dt):
            status_label = "Overdue"
        elif not assignees_raw:
            status_label = "New"
        elif in_prog:
            status_label = "Active"
        else:
            status_label = "Active"

    # Notes (used in Waiting to Start section)
    notes = ""
    if not assignees_raw:
        notes = "New, pending assignment"
    elif is_overdue(due_dt) and due_dt:
        days_late = (now - due_dt).days
        notes = "Significantly overdue" if days_late > 90 else "Overdue"

    return {
        "id":           list_data.get("id", ""),
        "raw_name":     raw_name,
        "company":      company,
        "project":      project_desc,
        "progress":     progress,
        "in_progress":  len(in_prog),
        "todo":         len(todo),
        "complete":     len(complete),
        "total_tasks":  total,
        "start_date":   start_dt,
        "due_date":     due_dt,
        "start_str":    fmt_date(start_dt, now),
        "due_str":      fmt_date_overdue(due_dt, now),
        "assignees":    assignees_display,
        "assignees_raw": assignees_raw,
        "status":       status_label,
        "is_overdue":   is_overdue(due_dt),
        "notes":        notes,
    }


# ── Engineer workload ─────────────────────────────────────────────────────────

def compute_workload(active_projects: list) -> list[tuple[str, dict]]:
    """
    Return a sorted list of (engineer_name, {count, projects}) tuples,
    ordered by descending task count.
    """
    workload: dict[str, dict] = {}
    for p in active_projects:
        task_count = p["in_progress"] + p["todo"]
        for name in p["assignees"]:
            if name not in workload:
                workload[name] = {"count": 0, "projects": []}
            workload[name]["count"] += task_count
            workload[name]["projects"].append(p["company"])
    return sorted(workload.items(), key=lambda x: -x[1]["count"])


# ── Team availability (July / Aug / Sep) ──────────────────────────────────────

def compute_availability(active_projects: list) -> dict[str, dict]:
    """
    For each engineer, return their state in July, August, September 2026.
    States: 'active', 'overdue', 'available'
    """
    now = datetime.now(tz=timezone.utc)

    def month_start(year: int, month: int) -> datetime:
        return datetime(year, month, 1, tzinfo=timezone.utc)

    months = [
        ("July",      month_start(2026, 7)),
        ("August",    month_start(2026, 8)),
        ("September", month_start(2026, 9)),
    ]

    availability: dict[str, dict[str, str]] = {}

    for p in active_projects:
        project_due  = p["due_date"]
        is_proj_over = p["is_overdue"]

        for name in p["assignees"]:
            if name not in availability:
                availability[name] = {m: "available" for m, _ in months}

            for month_name, month_start_dt in months:
                # Project spans this month if it has no due date (ongoing)
                # or due date is >= start of this month
                spans = (project_due is None) or (project_due >= month_start_dt)
                if not spans:
                    continue

                current = availability[name][month_name]
                if current == "available":
                    availability[name][month_name] = "overdue" if is_proj_over else "active"
                elif current == "active" and is_proj_over:
                    availability[name][month_name] = "overdue"

    return availability


# ── Flags & Blockers ──────────────────────────────────────────────────────────

def compute_flags(
    active_projects: list,
    waiting_projects: list,
    workload: list[tuple[str, dict]],
) -> list[dict]:
    """Generate flags and blockers from aggregated project data."""
    now  = datetime.now(tz=timezone.utc)
    flags: list[dict] = []

    # Overdue projects
    overdue = [p for p in active_projects if p["is_overdue"]]
    if overdue:
        names = ", ".join(p["company"] for p in overdue)
        flags.append({"bold": f"{len(overdue)} project{'s' if len(overdue) > 1 else ''} overdue",
                       "text": f"— {names}"})

    # Heavily loaded engineers (>12 open tasks)
    for name, data in workload:
        if data["count"] > 12:
            projs = ", ".join(dict.fromkeys(data["projects"]))  # deduplicated
            flags.append({"bold": f"{name} heavily loaded",
                           "text": f"— {data['count']} client tasks across {len(data['projects'])} projects"})

    # Active projects with unassigned engineers near due date
    for p in active_projects:
        if not p["assignees"] and p["due_date"]:
            days_left = (p["due_date"] - now).days
            if days_left <= 30:
                flags.append({"bold": f"{p['company']} unassigned",
                               "text": f"— due {p['due_str']}, no engineer assigned"})

    # No scheduled work beyond current month
    if now.month < 12:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    future = [p for p in active_projects if p["due_date"] and p["due_date"] >= next_month]
    if not future:
        flags.append({"bold": "No projects scheduled beyond this month",
                       "text": "— consider adding due dates for upcoming deliverables"})

    # Waiting projects summary
    if waiting_projects:
        unassigned_w = [p for p in waiting_projects if not p["assignees"]]
        flags.append({"bold": f"{len(waiting_projects)} waiting project{'s' if len(waiting_projects) > 1 else ''} pending",
                       "text": f"— {len(unassigned_w)} unassigned, no dates set"})

    return flags



