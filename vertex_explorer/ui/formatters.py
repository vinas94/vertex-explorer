import pendulum
from rich.text import Text

from vertex_explorer.config import RUN_STATE_STYLE


def _console_url(resource_name: str, kind: str) -> str:
    _, project, _, region, _, resource_id = resource_name.split("/")
    return (
        f"https://console.cloud.google.com/agent-platform/pipelines/locations/{region}"
        f"/{kind}/{resource_id}?project={project}"
    )


def _run_dots(runs: list) -> Text:
    rt = Text()
    for run in runs[:5]:
        rt.append("●", style=RUN_STATE_STYLE.get(run.state.name, "dim"))
    return rt


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


def _highlight(text: str, terms: list[str]) -> Text:
    rt = Text(text)
    tl = text.lower()
    for term in terms:
        start = 0
        while (idx := tl.find(term, start)) != -1:
            rt.stylize("bold yellow", idx, idx + len(term))
            start = idx + len(term)
    return rt
