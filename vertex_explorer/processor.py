import re
from datetime import datetime, timezone

import pendulum

from vertex_explorer.config import PROJECT, UA_LOOKBACK_DAYS, UA_PREFIXES


def _synthetic_name(loc: str) -> str:
    return f"projects/{PROJECT}/locations/europe-{loc}/schedules/__unscheduled__"


def _fmt_name(resource_name: str) -> str:
    _, project, _, region, _, resource_id = resource_name.split("/")
    return re.sub(r"-\d{14,}$", "", resource_id)


def _fmt_region(resource_name: str) -> str:
    _, project, _, region, _, resource_id = resource_name.split("/")
    return region.replace("europe-", "")


def synthetic_schedule(loc: str) -> dict:
    return {
        "name": _synthetic_name(loc),
        "display_name": "Unscheduled runs",
        "state": "-",
        "cron": "-",
        "nextRunTime": None,
        "_synthetic": True,
    }


def build_schedules(schedules_by_loc: dict) -> list[dict]:
    schedules = [s for sl in schedules_by_loc.values() for s in sl]
    for loc in schedules_by_loc:
        schedules.append(synthetic_schedule(loc.replace("europe-", "")))
    return schedules


def build_runs_index(all_runs: list) -> dict[str, list]:
    by_sched: dict[str, list] = {}
    for r in all_runs:
        if r.schedule_name:
            by_sched.setdefault(r.schedule_name, []).append(r)
        else:
            loc = _fmt_region(r.name) if r.name else "?"
            by_sched.setdefault(_synthetic_name(loc), []).append(r)

    _key = lambda r: r.start_time or datetime.min.replace(tzinfo=timezone.utc)
    for runs in by_sched.values():
        runs.sort(key=_key, reverse=True)
    return by_sched


def build_ua_failed_runs(all_runs: list) -> list:
    cutoff = pendulum.now("UTC").subtract(days=UA_LOOKBACK_DAYS)
    return [
        r
        for r in all_runs
        if r.state.name == "PIPELINE_STATE_FAILED"
        and any(_fmt_name(r.name).startswith(p) for p in UA_PREFIXES)
        and (not r.end_time or pendulum.instance(r.end_time) >= cutoff)
    ]
