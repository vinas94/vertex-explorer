import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import colorlog

colorlog.basicConfig(
    level=logging.INFO,
    format="%(log_color)s%(asctime)s %(name)s %(levelname)s%(reset)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

_SETTINGS_PATH = Path.home() / ".config" / "vertex-explorer" / "settings.json"

RUNS_PAGE_SIZE = 100
RUN_STATE_STYLE = {
    "PIPELINE_STATE_SUCCEEDED": "green",
    "PIPELINE_STATE_RUNNING": "cyan",
    "PIPELINE_STATE_FAILED": "red",
    "PIPELINE_STATE_CANCELLED": "yellow",
    "PIPELINE_STATE_CANCELLING": "yellow",
}


@dataclass
class Settings:
    project: str = ""
    regions: list[str] = field(default_factory=list)
    runs_days: int = 14
    schedules_days: int = 14
    short_regions: bool = True
    tracker_filters: list[str] = field(default_factory=list)

    def load(self) -> None:
        try:
            data = json.loads(_SETTINGS_PATH.read_text())
        except Exception:
            return
        try:
            self.project = data.get("PROJECT", self.project)
            self.regions = list(dict.fromkeys(data.get("REGIONS", self.regions)))
            self.runs_days = data.get("RUNS_DAYS", self.runs_days)
            self.schedules_days = data.get("SCHEDULES_DAYS", self.schedules_days)
            self.short_regions = bool(data.get("SHORT_REGIONS", self.short_regions))
            self.tracker_filters = [
                s for line in data.get("TRACKER_FILTERS", self.tracker_filters) if (s := line.strip())
            ]
        except Exception:
            pass

    def save(self) -> None:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SETTINGS_PATH.write_text(
            json.dumps(
                {
                    "PROJECT": self.project,
                    "REGIONS": self.regions,
                    "RUNS_DAYS": self.runs_days,
                    "SCHEDULES_DAYS": self.schedules_days,
                    "SHORT_REGIONS": self.short_regions,
                    "TRACKER_FILTERS": self.tracker_filters,
                },
                indent=2,
            )
        )


settings = Settings()
settings.load()
