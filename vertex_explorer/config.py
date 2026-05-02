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
REGIONS = ["europe-west3", "europe-west4"]

RUNS_DAYS = 14
SCHEDULES_DAYS = 14

SHORT_REGIONS = True
RUNS_PAGE_SIZE = 100
RUN_STATE_STYLE = {
    "PIPELINE_STATE_SUCCEEDED": "green",
    "PIPELINE_STATE_RUNNING": "cyan",
    "PIPELINE_STATE_FAILED": "red",
    "PIPELINE_STATE_CANCELLED": "yellow",
    "PIPELINE_STATE_CANCELLING": "yellow",
}


def load_settings() -> None:
    global PROJECT, REGIONS, RUNS_DAYS, SCHEDULES_DAYS, SHORT_REGIONS

    try:
        data = json.loads(_SETTINGS_PATH.read_text())
    except Exception:
        return

    try:
        PROJECT = data.get("PROJECT", PROJECT)
        REGIONS = list(dict.fromkeys(data.get("REGIONS", REGIONS)))
        RUNS_DAYS = data.get("RUNS_DAYS", RUNS_DAYS)
        SCHEDULES_DAYS = data.get("SCHEDULES_DAYS", SCHEDULES_DAYS)
        SHORT_REGIONS = bool(data.get("SHORT_REGIONS", SHORT_REGIONS))
    except Exception:
        pass


def save_settings() -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(
        json.dumps(
            {
                "PROJECT": PROJECT,
                "REGIONS": REGIONS,
                "RUNS_DAYS": RUNS_DAYS,
                "SCHEDULES_DAYS": SCHEDULES_DAYS,
                "SHORT_REGIONS": SHORT_REGIONS,
            },
            indent=2,
        )
    )


load_settings()
