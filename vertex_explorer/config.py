import logging

import colorlog

colorlog.basicConfig(
    level=logging.INFO,
    format="%(log_color)s%(asctime)s %(name)s %(levelname)s%(reset)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


PROJECT = "martin-test-datalab"
LOCATIONS = ["europe-west3", "europe-west4"]

RUNS_DAYS = 28
SCHEDULES_DAYS = 7

RUNS_PAGE_SIZE = 100

RUN_STATE_STYLE = {
    "PIPELINE_STATE_SUCCEEDED": "green",
    "PIPELINE_STATE_RUNNING": "cyan",
    "PIPELINE_STATE_FAILED": "red",
    "PIPELINE_STATE_CANCELLED": "yellow",
    "PIPELINE_STATE_CANCELLING": "yellow",
}


# result = fetch_all()
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
