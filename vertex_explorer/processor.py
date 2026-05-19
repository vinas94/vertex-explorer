from typing import TYPE_CHECKING

import pendulum

from vertex_explorer.config import settings

if TYPE_CHECKING:
    from google.cloud.aiplatform_v1 import PipelineJob


def synthetic_name(location: str) -> str:
    return f"projects/{settings.project}/locations/{location}/schedules/__unscheduled__"


def synthetic_schedule(location: str) -> dict:
    return {
        "name": synthetic_name(location),
        "display_name": "Unscheduled runs",
        "state": "",
        "cron": "",
        "nextRunTime": None,
        "_synthetic": True,
    }


def build_schedules(schedules_by_loc: dict[str, list[dict]]) -> list[dict]:
    schedules = [s for sl in schedules_by_loc.values() for s in sl]
    for location in schedules_by_loc:
        schedules.append(synthetic_schedule(location))
    return schedules


def build_runs_index(all_runs: list["PipelineJob"]) -> dict[str, list["PipelineJob"]]:
    by_sched: dict[str, list["PipelineJob"]] = {}
    for run in all_runs:
        if run.schedule_name:
            by_sched.setdefault(run.schedule_name, []).append(run)
        else:
            location = run.name.split("/")[3] if run.name else "unknown"
            by_sched.setdefault(synthetic_name(location), []).append(run)

    _key = lambda r: r.start_time or pendulum.DateTime.min
    for runs in by_sched.values():
        runs.sort(key=_key, reverse=True)
    return by_sched
