from datetime import datetime, timezone

import pendulum

from vertex_explorer.config import PROJECT, UA_LOOKBACK_DAYS, UA_PREFIXES
from vertex_explorer.ui.formatters import _fmt_name, _fmt_region


def synthetic_schedule(loc: str) -> dict:
    return {
        "name": f"projects/{PROJECT}/locations/europe-{loc}/schedules/__unscheduled__",
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
            synthetic_name = f"projects/{PROJECT}/locations/europe-{loc}/schedules/__unscheduled__"
            by_sched.setdefault(synthetic_name, []).append(r)

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
