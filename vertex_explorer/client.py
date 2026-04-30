import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pendulum

from vertex_explorer.config import LOCATIONS, PROJECT, RUNS_DAYS, SCHEDULES_DAYS

log = logging.getLogger(__name__)


def fetch_location_runs(location: str, filter_str: str) -> list:
    from google.cloud import aiplatform_v1
    from google.protobuf import field_mask_pb2

    RUN_READ_MASK = field_mask_pb2.FieldMask(paths=["name", "start_time", "end_time", "state", "schedule_name"])

    client = aiplatform_v1.PipelineServiceClient(
        client_options={"api_endpoint": f"{location}-aiplatform.googleapis.com"}
    )
    request = aiplatform_v1.ListPipelineJobsRequest(
        parent=f"projects/{PROJECT}/locations/{location}",
        filter=filter_str,
        read_mask=RUN_READ_MASK,
    )
    log.info(f"{location}: start fetching runs")
    runs = list(client.list_pipeline_jobs(request))
    log.info(f"{location}: {len(runs)} runs retrieved")
    return runs


def fetch_location_schedules(location: str, filter_str: str) -> list:
    from google.cloud import aiplatform_v1

    client = aiplatform_v1.ScheduleServiceClient(
        client_options={"api_endpoint": f"{location}-aiplatform.googleapis.com"}
    )
    request = aiplatform_v1.ListSchedulesRequest(
        parent=f"projects/{PROJECT}/locations/{location}",
        filter=filter_str,
    )
    log.info(f"{location}: start fetching schedules")
    schedules = [
        {
            "name": s.name,
            "display_name": s.display_name,
            "state": s.state.name,
            "cron": s.cron,
            "nextRunTime": s.next_run_time,
        }
        for s in client.list_schedules(request)
    ]
    log.info(f"{location}: {len(schedules)} schedules retrieved")
    return schedules


def fetch_all(on_schedules=None, on_runs=None, on_error=None) -> dict:
    runs_filter = f'createTime>="{pendulum.now("UTC").subtract(days=RUNS_DAYS).to_iso8601_string()}"'
    schedules_filter = f'nextRunTime>="{pendulum.now("UTC").subtract(days=SCHEDULES_DAYS).to_iso8601_string()}"'

    schedules: dict = {}
    runs: dict = {}
    lock_sched = threading.Lock()
    lock_runs = threading.Lock()

    def _on_sched_done(loc, future):
        try:
            data = future.result()
        except Exception as e:
            log.error(f"{loc}: failed to fetch schedules: {e}")
            if on_error:
                on_error()
            return
        with lock_sched:
            schedules[loc] = data
            if len(schedules) == len(LOCATIONS) and on_schedules:
                on_schedules(dict(schedules))

    def _on_runs_done(loc, future):
        try:
            data = future.result()
        except Exception as e:
            log.error(f"{loc}: failed to fetch runs: {e}")
            if on_error:
                on_error()
            return
        with lock_runs:
            runs[loc] = data
            if len(runs) == len(LOCATIONS) and on_runs:
                on_runs(dict(runs))

    with ThreadPoolExecutor(max_workers=len(LOCATIONS) * 2 - 1) as executor:
        for loc in LOCATIONS:
            fs = executor.submit(fetch_location_schedules, loc, schedules_filter)
            fr = executor.submit(fetch_location_runs, loc, runs_filter)
            fs.add_done_callback(lambda f, loc=loc: _on_sched_done(loc, f))
            fr.add_done_callback(lambda f, loc=loc: _on_runs_done(loc, f))

    return {"runs": runs, "schedules": schedules}
