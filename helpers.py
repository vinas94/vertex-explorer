import re

import pendulum
from rich.text import Text


def _run_url(resource_name: str) -> str:
    parts = resource_name.split("/")
    project, location, run_id = parts[1], parts[3], parts[5]
    return (
        f"https://console.cloud.google.com/agent-platform/pipelines/locations/{location}"
        f"/runs/{run_id}?project={project}"
    )


def _schedule_url(resource_name: str) -> str:
    parts = resource_name.split("/")
    project, location, schedule_id = parts[1], parts[3], parts[5]
    return (
        f"https://console.cloud.google.com/agent-platform/pipelines/locations/{location}"
        f"/schedules/{schedule_id}?project={project}"
    )


def _short_name(resource_name: str) -> str:
    return resource_name.split("/")[-1]


def _run_display_name(resource_name: str) -> str:
    return re.sub(r"-\d{14,}$", "", resource_name.split("/")[-1])


def _location(resource_name: str) -> str:
    parts = resource_name.split("/")
    loc = parts[3] if len(parts) > 3 else "?"
    return loc.replace("europe-", "")


def _fmt_duration(start, end) -> str:
    if not start or not end:
        return "-"
    try:
        secs = int((pendulum.instance(end) - pendulum.instance(start)).total_seconds())
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m {secs % 60:02d}s"
        return f"{secs // 3600}h {(secs % 3600) // 60:02d}m"
    except Exception:
        return "-"


def _fmt_time(ts) -> str:
    if ts is None:
        return "-"
    try:
        return pendulum.instance(ts).format("YYYY-MM-DD HH:mm")
    except Exception:
        return str(ts)[:16]


def _trunc(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


_DOT_STYLE = {
    "PIPELINE_STATE_SUCCEEDED": ("●", "green"),
    "PIPELINE_STATE_FAILED": ("●", "red"),
    "PIPELINE_STATE_RUNNING": ("●", "cyan"),
    "PIPELINE_STATE_CANCELLED": ("●", "yellow"),
    "PIPELINE_STATE_CANCELLING": ("●", "yellow"),
}


def _run_dots(runs: list) -> Text:
    rt = Text()
    for run in runs[:5]:
        dot, style = _DOT_STYLE.get(run.state.name, ("●", "dim"))
        rt.append(dot, style=style)
    return rt
