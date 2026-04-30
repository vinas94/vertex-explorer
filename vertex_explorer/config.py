import json
import logging
from pathlib import Path

import colorlog

colorlog.basicConfig(
    level=logging.INFO,
    format="%(log_color)s%(asctime)s %(name)s %(levelname)s%(reset)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_SETTINGS_PATH = Path.home() / ".config" / "vertex-explorer" / "settings.json"

PROJECT = "martin-test-datalab"
LOCATIONS = ["europe-west3", "europe-west4"]

RUNS_DAYS = 3
SCHEDULES_DAYS = 3

RUNS_PAGE_SIZE = 100
RUN_STATE_STYLE = {
    "PIPELINE_STATE_SUCCEEDED": "green",
    "PIPELINE_STATE_RUNNING": "cyan",
    "PIPELINE_STATE_FAILED": "red",
    "PIPELINE_STATE_CANCELLED": "yellow",
    "PIPELINE_STATE_CANCELLING": "yellow",
}


def load_settings() -> None:
    global PROJECT, LOCATIONS, RUNS_DAYS, SCHEDULES_DAYS
    try:
        data = json.loads(_SETTINGS_PATH.read_text())
    except Exception:
        return
    PROJECT = data.get("PROJECT", PROJECT)
    LOCATIONS = list(dict.fromkeys(data.get("LOCATIONS", LOCATIONS)))
    RUNS_DAYS = data.get("RUNS_DAYS", RUNS_DAYS)
    SCHEDULES_DAYS = data.get("SCHEDULES_DAYS", SCHEDULES_DAYS)


def save_settings() -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(
        json.dumps(
            {
                "PROJECT": PROJECT,
                "LOCATIONS": LOCATIONS,
                "RUNS_DAYS": RUNS_DAYS,
                "SCHEDULES_DAYS": SCHEDULES_DAYS,
            },
            indent=2,
        )
    )


load_settings()
