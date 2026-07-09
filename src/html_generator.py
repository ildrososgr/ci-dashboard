"""
HTML dashboard generator.
Produces a self-contained, single-file HTML dashboard
that mirrors the ClickUp Brain CI Projects Dashboard layout.
"""
from __future__ import annotations

import html as _h
from datetime import datetime, timezone, timedelta
from typing import Optional

from data_processor import get_initials, compute_availability

# ── Status badge colours ──────────────────────────────────────────────────────

_STATUS_STYLE: dict[str, tuple[str, str]] = {
    # (background, text color)
    "active":               ("#fef3c7", "#92400e"),
    "delayed":              ("#fed7aa", "#7c2d12"),
    "delayed from customer":("#fed7aa", "#7c2d12"),
    "overdue":              ("#fee2e2", "#991b1b"),
    "on hold":              ("#f3f4f6", "#374151"),
    "new":                  ("#dbeafe", "#1e3a8a"),
    "blocked":              ("#fee2e2", "#991b1b"),
    "waiting to start":     ("#f3f4f6", "#374151"),
    "complete":             ("#d1fae5", "#065f46"),
}

def _badge_style(status: str) -> tuple[str, str]:
    return _STATUS_STYLE.get(status.lower(), ("#f3f4f6", "#374151"))

def _e(text) -> str:
    """HTML-escape a value."""
    return _h.escape(str(text))


# ── Sub-components ────────────────────────────────────────────────────────────

def _progress_bar(pct: int) -> str:
    clamped = max(0, min(100, pct))
    bar_color = "#10b981" if clamped > 50 else ("#f59e0b" if clamped > 20 else "#ef4444")
    return (
        f'<div class="prog-wrap" title="{clamped}% complete">'
        f'  <div class="prog-bar" style="width:{clamped}%;background:{bar_color}"></div>'
        f'</div>'
        f'<span class="prog-label">{clamped}%</span>'
    )


def _avatars(names: list[str]) -> str:
    if not names:
        return '<span class="unassigned">Unassigned</span>'
    colors = ["#7c3aed", "#0369a1", "#b45309", "#0f766e", "#9f1239",
              "#1d4ed8", "#047857", "#7e22ce", "#b91c1c", "#0c4a6e"]
    parts = []
    for i, name in enumerate(names):
        color = colors[i % len(colors)]
        initials = get_initials(name)
        parts.append(
            f'<span class="avatar" style="background:{color}" title="{_e(name)}">'
            f'{_e(initials)}</span>'
        )
    label = " ".join(_e(n) for n in names)
    return f'<div class="avatars" title="{label}">{"".join(parts)}</div>'


def _status_badge(status: str) -> str:
    bg, fg = _badge_style(status)
    return (
        f'<span class="badge" style="background:{bg};color:{fg};'
        f'border:1px solid {fg}30">{_e(status)}</span>'
    )


def _avail_cell(state: str, content: str = "") -> str:
    styles = {
        "active":    ("background:#fef3c7;color:#92400e;", "Active"),
        "overdue":   ("background:#fee2e2;color:#991b1b;", "Overdue"),
        "available": ("background:#d1fae5;color:#065f46;", "Available"),
    }
    style, label = styles.get(state, ("background:#f3f4f6;color:#6b7280;", state.title()))
    display = _e(content) if content else label
    return f'<td class="avail-cell" style="{style}">{display}</td>'


# ── Section builders ──────────────────────────────────────────────────────────

def _summary_cards(
    active_count: int,
    waiting_count: int,
    new_count: int,
    overdue_count: int,
    engineer_count: int,
) -> str:
    cards = [
        (str(active_count),   "Active Projects (Yellow)",   "#f59e0b", "#fef3c7"),
        (str(waiting_count),  "Waiting to Start (Grey)",    "#9ca3af", "#f3f4f6"),
        (str(new_count),      "New (Unassigned)",           "#3b82f6", "#dbeafe"),
        (str(overdue_count),  "Overdue",                    "#ef4444", "#fee2e2"),
        (str(engineer_count), "Engineers",                  "#7c3aed", "#ede9fe"),
    ]
    items = "".join(
        f'<div class="card" style="border-top:4px solid {color};background:{bg}">'
        f'  <div class="card-num" style="color:{color}">{num}</div>'
        f'  <div class="card-label">{_e(label)}</div>'
        f'</div>'
        for num, label, color, bg in cards
    )
    return f'<div class="cards">{items}</div>'


def _active_projects_table(projects: list) -> str:
    if not projects:
        return '<p class="empty">No active projects found.</p>'

    rows = []
    for p in projects:
        rows.append(
            f'<tr>'
            f'  <td class="project-cell">'
            f'    <span class="company">{_e(p["company"])}</span>'
            f'    <span class="proj-desc">{_e(p["project"])}</span>'
            f'  </td>'
            f'  <td class="prog-cell">{_progress_bar(p["progress"])}</td>'
            f'  <td class="num">{p["in_progress"]}</td>'
            f'  <td class="num">{p["todo"]}</td>'
            f'  <td class="date">{_e(p["start_str"])}</td>'
            f'  <td class="date {"overdue-date" if p["is_overdue"] else ""}">{_e(p["due_str"])}</td>'
            f'  <td>{_avatars(p["assignees"])}</td>'
            f'  <td>{_status_badge(p["status"])}</td>'
            f'</tr>'
        )

    return (
        '<div class="section-header">'
        '  <h2>Active Projects <span class="yellow-label">(Yellow)</span></h2>'
        f'  <span class="count">{len(projects)} projects</span>'
        '</div>'
        '<div class="table-wrap">'
        '<table>'
        '  <thead><tr>'
        '    <th>Project</th><th>Progress</th>'
        '    <th title="In Progress">In Prog.</th><th>To Do</th>'
        '    <th>Start Date</th><th>Due Date</th>'
        '    <th>Assignees</th><th>Status</th>'
        '  </tr></thead>'
        f'  <tbody>{"".join(rows)}</tbody>'
        '</table>'
        '</div>'
    )


def _waiting_table(projects: list) -> str:
    if not projects:
        return ""

    rows = []
    for p in projects:
        rows.append(
            f'<tr>'
            f'  <td class="project-cell">'
            f'    <span class="company">{_e(p["company"])}</span>'
            f'    <span class="proj-desc">{_e(p["project"])}</span>'
            f'  </td>'
            f'  <td class="num">{p["total_tasks"]}</td>'
            f'  <td class="date">{_e(p["start_str"])}</td>'
            f'  <td class="date {"overdue-date" if p["is_overdue"] else ""}">{_e(p["due_str"])}</td>'
            f'  <td>{_avatars(p["assignees"])}</td>'
            f'  <td class="notes">{_e(p["notes"])}</td>'
            f'</tr>'
        )

    return (
        '<div class="section-header">'
        '  <h2>Waiting to Start <span class="grey-label">(Grey / To Do)</span></h2>'
        f'  <span class="count">{len(projects)} projects</span>'
        '</div>'
        '<div class="table-wrap">'
        '<table>'
        '  <thead><tr>'
        '    <th>Project</th><th>Tasks</th>'
        '    <th>Start Date</th><th>Due Date</th>'
        '    <th>Assignees</th><th>Notes</th>'
        '  </tr></thead>'
        f'  <tbody>{"".join(rows)}</tbody>'
        '</table>'
        '</div>'
    )


def _availability_section(active_projects: list) -> str:
    avail = compute_availability(active_projects)
    if not avail:
        return ""

    months = ["July", "August", "September"]

    header_cells = "".join(f"<th>{m}</th>" for m in months)
    rows = []
    for engineer, month_states in sorted(avail.items()):
        cells = "".join(
            _avail_cell(month_states.get(m, "available"))
            for m in months
        )
        rows.append(f"<tr><td class='eng-name'>{_e(engineer)}</td>{cells}</tr>")

    legend_items = [
        ("#fef3c7", "#92400e", "Active client work"),
        ("#fee2e2", "#991b1b", "Overdue"),
        ("#d1fae5", "#065f46", "Available"),
    ]
    legend = "".join(
        f'<span class="legend-dot" style="background:{bg};color:{fg};'
        f'border:1px solid {fg}40;padding:2px 8px;border-radius:4px;font-size:11px">{_e(label)}</span>'
        for bg, fg, label in legend_items
    )

    return (
        '<div class="section-header">'
        '  <h2>Team Availability: July – August – September 2026</h2>'
        '</div>'
        '<div class="table-wrap">'
        '<table class="avail-table">'
        f'  <thead><tr><th>Engineer</th>{header_cells}</tr></thead>'
        f'  <tbody>{"".join(rows)}</tbody>'
        '</table>'
        '</div>'
        f'<div class="legend">{legend}</div>'
    )


def _workload_section(workload: list) -> str:
    if not workload:
        return ""

    max_count = max((d["count"] for _, d in workload), default=1) or 1
    rows = []
    for name, data in workload:
        pct = round(data["count"] / max_count * 100)
        projects_str = ", ".join(dict.fromkeys(data["projects"]))
        color = "#ef4444" if data["count"] > 14 else "#f59e0b" if data["count"] > 8 else "#10b981"
        rows.append(
            f'<div class="workload-row">'
            f'  <div class="workload-header">'
            f'    <span class="eng-name">{_e(name)}</span>'
            f'    <span class="workload-count" style="color:{color}">{data["count"]}</span>'
            f'  </div>'
            f'  <div class="workload-projects">{_e(projects_str)}</div>'
            f'  <div class="workload-bar-wrap">'
            f'    <div class="workload-bar" style="width:{pct}%;background:{color}"></div>'
            f'  </div>'
            f'</div>'
        )

    return (
        '<div class="section-header"><h2>Team Workload <span class="sub">(Client Projects)</span></h2></div>'
        f'<div class="workload-list">{"".join(rows)}</div>'
    )


def _flags_section(flags: list) -> str:
    if not flags:
        return ""

    items = "".join(
        f'<li><strong>{_e(f["bold"])}</strong> {_e(f["text"])}</li>'
        for f in flags
    )
    return (
        '<div class="section-header"><h2>Flags &amp; Blockers</h2></div>'
        f'<ul class="flags-list">{items}</ul>'
    )


def _internal_section(projects: list) -> str:
    if not projects:
        return ""

    rows = []
    for p in projects:
        rows.append(
            f'<tr>'
            f'  <td>{_e(p["company"] if p["company"] != p["project"] else p["project"])}</td>'
            f'  <td class="num">{p["total_tasks"] if p["total_tasks"] < 100 else "30+"}</td>'
            f'  <td>{_avatars(p["assignees"])}</td>'
            f'</tr>'
        )

    return (
        '<div class="section-header">'
        '  <h2>Internal / R&amp;D</h2>'
        f'  <span class="count">{len(projects)} active</span>'
        '</div>'
        '<div class="table-wrap">'
        '<table>'
        '  <thead><tr><th>Project</th><th>Tasks</th><th>Owner</th></tr></thead>'
        f'  <tbody>{"".join(rows)}</tbody>'
        '</table>'
        '</div>'
    )


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 13px;
  background: #f0f2f5;
  color: #111827;
}

/* Header */
.dash-header {
  background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%);
  color: #fff;
  padding: 28px 40px 24px;
}
.dash-header h1 { font-size: 24px; font-weight: 700; letter-spacing: -0.3px; }
.dash-header .subtitle { font-size: 13px; color: rgba(255,255,255,0.75); margin-top: 4px; }

/* Container */
.container {
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px 32px 48px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

/* Summary cards */
.cards {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}
.card {
  background: #fff;
  border-radius: 10px;
  padding: 18px 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08);
}
.card-num { font-size: 32px; font-weight: 700; line-height: 1; }
.card-label { font-size: 11px; color: #6b7280; margin-top: 6px; font-weight: 500; text-transform: uppercase; letter-spacing: .3px; }

/* Section headers */
.section-header {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 10px;
}
.section-header h2 {
  font-size: 15px;
  font-weight: 700;
  color: #111827;
}
.yellow-label { color: #b45309; font-weight: 500; }
.grey-label   { color: #6b7280; font-weight: 500; }
.sub          { color: #6b7280; font-weight: 400; }
.count        { font-size: 12px; color: #6b7280; }

/* Tables */
.table-wrap { overflow-x: auto; }
table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,.08);
}
thead { background: #f9fafb; }
th {
  text-align: left;
  padding: 10px 14px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .4px;
  color: #6b7280;
  border-bottom: 1px solid #e5e7eb;
  white-space: nowrap;
}
td {
  padding: 11px 14px;
  border-bottom: 1px solid #f3f4f6;
  vertical-align: middle;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: #f9fafb; }

.project-cell { min-width: 200px; }
.company { display: block; font-weight: 600; color: #111827; }
.proj-desc { display: block; font-size: 11px; color: #6b7280; margin-top: 1px; }
.num { text-align: center; font-weight: 600; color: #374151; }
.date { white-space: nowrap; color: #374151; }
.overdue-date { color: #dc2626; font-weight: 500; }
.notes { color: #6b7280; font-style: italic; }
.eng-name { font-weight: 600; color: #111827; }
.empty { color: #6b7280; }

/* Progress */
.prog-cell { min-width: 120px; }
.prog-wrap {
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 4px;
}
.prog-bar { height: 100%; border-radius: 3px; transition: width .3s; }
.prog-label { font-size: 11px; color: #6b7280; font-weight: 500; }

/* Avatars */
.avatars { display: flex; gap: 4px; flex-wrap: wrap; }
.avatar {
  width: 26px; height: 26px;
  border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 9px; font-weight: 700; color: #fff;
  flex-shrink: 0;
}
.unassigned { color: #9ca3af; font-style: italic; font-size: 12px; }

/* Badges */
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 20px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

/* Availability */
.avail-table td, .avail-table th { text-align: center; }
.avail-table td:first-child { text-align: left; }
.avail-cell {
  font-size: 11px;
  font-weight: 600;
  padding: 10px 14px;
  border-radius: 4px;
}
.legend { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.legend-dot { display: inline-block; font-size: 11px; }

/* Workload */
.workload-list { display: flex; flex-direction: column; gap: 12px; background: #fff; border-radius: 10px; padding: 16px 20px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
.workload-row {}
.workload-header { display: flex; justify-content: space-between; align-items: center; }
.workload-count { font-size: 18px; font-weight: 700; }
.workload-projects { font-size: 11px; color: #6b7280; margin: 2px 0 5px; }
.workload-bar-wrap { height: 6px; background: #e5e7eb; border-radius: 3px; overflow: hidden; }
.workload-bar { height: 100%; border-radius: 3px; }

/* Flags */
.flags-list {
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08);
  padding: 16px 20px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.flags-list li { font-size: 13px; color: #374151; line-height: 1.5; }
.flags-list li strong { color: #111827; }

/* Two-column layout */
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

/* Footer */
.footer {
  text-align: center;
  font-size: 11px;
  color: #9ca3af;
  border-top: 1px solid #e5e7eb;
  padding-top: 16px;
}

@media (max-width: 900px) {
  .cards { grid-template-columns: repeat(2, 1fr); }
  .two-col { grid-template-columns: 1fr; }
  .container { padding: 16px; }
  .dash-header { padding: 20px 16px; }
}
"""


# ── Main generator ────────────────────────────────────────────────────────────

class HtmlGenerator:
    def generate(
        self,
        active_projects: list,
        waiting_projects: list,
        internal_projects: list,
        members: list,
        generated_at: datetime,
    ) -> str:
        now = datetime.now(tz=timezone.utc)

        # ── Stats for summary cards ──
        overdue_count  = sum(1 for p in active_projects if p["is_overdue"])
        new_count      = sum(1 for p in (active_projects + waiting_projects) if not p["assignees"])
        all_engineers: set[str] = set()
        for p in active_projects:
            all_engineers.update(p["assignees"])

        # ── Workload ──
        from data_processor import compute_workload, compute_flags
        workload = compute_workload(active_projects)
        flags    = compute_flags(active_projects, waiting_projects, workload)

        # ── Format date header (Windows-safe) ──
        date_str = generated_at.strftime("%B %d, %Y").replace(" 0", " ")

        # ── Build HTML ──
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="3600">
  <title>CI Projects Dashboard</title>
  <style>{_CSS}</style>
</head>
<body>

<div class="dash-header">
  <h1>CI Projects Dashboard</h1>
  <div class="subtitle">{_e(date_str)} &middot; Modern Workplace &amp; Cloud Team</div>
</div>

<div class="container">

  {_summary_cards(
      len(active_projects),
      len(waiting_projects),
      new_count,
      overdue_count,
      len(all_engineers),
  )}

  <div>
    {_active_projects_table(active_projects)}
  </div>

  <div>
    {_waiting_table(waiting_projects)}
  </div>

  <div>
    {_availability_section(active_projects)}
  </div>

  <div class="two-col">
    <div>{_workload_section(workload)}</div>
    <div>{_flags_section(flags)}</div>
  </div>

  <div>
    {_internal_section(internal_projects)}
  </div>

  <div class="footer">
    <p>Source: CI Projects Space &nbsp;&middot;&nbsp; Yellow = active &nbsp;&middot;&nbsp;
       Grey = waiting &nbsp;&middot;&nbsp; Green = excluded (complete) &nbsp;&middot;&nbsp;
       Team: Modern Workplace &amp; Cloud ({len(all_engineers)} engineers)</p>
    <p style="margin-top:4px">Generated {_e(generated_at.strftime("%b %d, %Y %H:%M UTC"))}</p>
  </div>

</div>
</body>
</html>"""
