import re
from typing import TYPE_CHECKING

import pendulum
from rich.text import Text

import vertex_explorer.config as config

if TYPE_CHECKING:
    from google.cloud.aiplatform_v1 import PipelineJob


def console_url(resource_name: str, kind: str) -> str:
    _, project, _, region, _, resource_id = resource_name.split("/")
    return (
        f"https://console.cloud.google.com/agent-platform/pipelines/locations/{region}"
        f"/{kind}/{resource_id}?project={project}"
    )


def run_dots(runs: list) -> Text:
    rt = Text()
    for run in runs[:5]:
        rt.append("●", style=config.RUN_STATE_STYLE.get(run.state.name, "dim"))
    return rt


def fmt_region(resource_name: str) -> str:
    _, project, _, region, _, resource_id = resource_name.split("/")
    if config.SHORT_REGIONS:
        return region.split("-", maxsplit=1)[1]
    return region


def fmt_name(resource_name: str) -> str:
    _, project, _, region, _, resource_id = resource_name.split("/")
    return re.sub(r"-\d{14,}$", "", resource_id)


def fmt_time(ts) -> str:
    try:
        return pendulum.instance(ts).format("MM-DD HH:mm")
    except Exception:
        return ""


def fmt_duration(start, end) -> str:
    try:
        d = pendulum.instance(end) - pendulum.instance(start)
        h, m, s = d.hours, d.minutes, d.remaining_seconds
        if h:
            return f"{h:2d}h {m:02d}m"
        if m:
            return f"{m:2d}m {s:02d}s"
        return f"    {s:2d}s"
    except Exception:
        return ""


def fmt_run_cells(run: "PipelineJob") -> tuple[Text, Text, Text]:
    cutoff_24h = pendulum.now("UTC").subtract(hours=24)

    state_name = run.state.name
    state = Text(state_name.replace("PIPELINE_STATE_", ""), style=config.RUN_STATE_STYLE.get(state_name, "dim"))
    recent_fail = (
        state_name == "PIPELINE_STATE_FAILED" and run.end_time and pendulum.instance(run.end_time) >= cutoff_24h
    )
    start = Text(fmt_time(run.start_time), style="red" if recent_fail else "")
    duration = Text(fmt_duration(run.start_time, run.end_time))
    return state, start, duration


def highlight(text: str, terms: list[str]) -> Text:
    rt = Text(text)
    tl = text.lower()
    for term in terms:
        start = 0
        while (idx := tl.find(term, start)) != -1:
            rt.stylize("bold yellow", idx, idx + len(term))
            start = idx + len(term)
    return rt
