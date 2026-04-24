import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import colorlog
import pendulum
from google.cloud import aiplatform_v1
from google.protobuf import field_mask_pb2

from config import PROJECT

colorlog.basicConfig(
    level=logging.INFO,
    format="%(log_color)s%(asctime)s %(name)s %(levelname)s%(reset)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

RUNS_DAYS = 28
SCHEDULES_DAYS = 7

RUN_READ_MASK = field_mask_pb2.FieldMask(paths=["name", "start_time", "end_time", "state", "schedule_name"])


def fetch_location_runs(location: str, filter_str: str) -> tuple[str, list]:
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
    return location, runs


def fetch_location_schedules(location: str, filter_str: str) -> tuple[str, list]:
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
    return location, schedules


def fetch_all(on_schedules=None, on_runs=None) -> dict:
    runs_filter = f'createTime>="{pendulum.now("UTC").subtract(days=RUNS_DAYS).to_iso8601_string()}"'
    schedules_filter = f'nextRunTime>="{pendulum.now("UTC").subtract(days=SCHEDULES_DAYS).to_iso8601_string()}"'

    schedules: dict = {}
    runs: dict = {}
    lock_sched = threading.Lock()
    lock_runs = threading.Lock()

    def _on_sched_done(loc, future):
        _, data = future.result()
        with lock_sched:
            schedules[loc] = data
            if len(schedules) == 2 and on_schedules:
                on_schedules(dict(schedules))

    def _on_runs_done(loc, future):
        _, data = future.result()
        with lock_runs:
            runs[loc] = data
            if len(runs) == 2 and on_runs:
                on_runs(dict(runs))

    # 3 workers: sched_w3, sched_w4, runs_w3 start immediately.
    # runs_w4 is queued and picked up by whichever worker finishes first.
    with ThreadPoolExecutor(max_workers=3) as executor:
        f_sched_w3 = executor.submit(fetch_location_schedules, "europe-west3", schedules_filter)
        f_sched_w4 = executor.submit(fetch_location_schedules, "europe-west4", schedules_filter)
        f_runs_w3 = executor.submit(fetch_location_runs, "europe-west3", runs_filter)
        f_runs_w4 = executor.submit(fetch_location_runs, "europe-west4", runs_filter)

        f_sched_w3.add_done_callback(lambda f: _on_sched_done("europe-west3", f))
        f_sched_w4.add_done_callback(lambda f: _on_sched_done("europe-west4", f))
        f_runs_w3.add_done_callback(lambda f: _on_runs_done("europe-west3", f))
        f_runs_w4.add_done_callback(lambda f: _on_runs_done("europe-west4", f))

    return {"runs": runs, "schedules": schedules}


if __name__ == "__main__":
    result = fetch_all()

#
# LOOKBACK_DAYS = 7
# PREFIXES = [
#     "go-model-treebased-install-prediction",
#     "tensorflow-install-prediction",
#     "tensorflow-action-prediction",
#     "tensorflow-audience-similarity",
#     "tensorflow-win-price-prediction",
# ]
#
#
# ua_failed_runs = []
# for region, runs in result["runs"].items():
#     for run in runs:
#         run_name = run.name.split("/")[-1]
#
#         if run.end_time and run.end_time < pendulum.now("UTC").add(days=-LOOKBACK_DAYS):
#             continue
#
#         if run.state.name != "PIPELINE_STATE_FAILED":
#             continue
#
#         if not any(run_name.startswith(p) for p in PREFIXES):
#             continue
#
#         ua_failed_runs.append(run)
#
# print(len(ua_failed_runs))
