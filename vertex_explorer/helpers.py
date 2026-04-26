import re

import pendulum
from rich.text import Text

from .config import DOT_STYLE


def _run_url(resource_name: str) -> str:
    _, project, _, region, _, resource_id = resource_name.split("/")
    return (
        f"https://console.cloud.google.com/agent-platform/pipelines/locations/{region}"
        f"/runs/{resource_id}?project={project}"
    )


def _schedule_url(resource_name: str) -> str:
    _, project, _, region, _, resource_id = resource_name.split("/")
    return (
        f"https://console.cloud.google.com/agent-platform/pipelines/locations/{region}"
        f"/schedules/{resource_id}?project={project}"
    )


def _run_dots(runs: list) -> Text:
    rt = Text()
    for run in runs[:5]:
        dot, style = DOT_STYLE.get(run.state.name, ("●", "dim"))
        rt.append(dot, style=style)
    return rt


def _fmt_name(resource_name: str) -> str:
    _, project, _, region, _, resource_id = resource_name.split("/")
    return re.sub(r"-\d{14,}$", "", resource_id)


def _fmt_region(resource_name: str) -> str:
    _, project, _, region, _, resource_id = resource_name.split("/")
    return region.replace("europe-", "")


def _fmt_time(ts) -> str:
    try:
        return pendulum.instance(ts).format("YYYY-MM-DD HH:mm")
    except Exception:
        return "-"


def _fmt_duration(start, end) -> str:
    try:
        d = pendulum.instance(end) - pendulum.instance(start)
        h, m, s = d.hours, d.minutes, d.remaining_seconds
        if h:
            return f"{h}h {m:02d}m"
        if m:
            return f"{m}m {s:02d}s"
        return f"{s}s"
    except Exception:
        return "-"
