from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label

import vertex_explorer.config as config


class SettingsScreen(ModalScreen[bool]):
    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            yield Label("Settings", id="settings-title")
            with Horizontal():
                yield Label("Project")
                yield Input(config.PROJECT, id="s-project")
            with Horizontal():
                yield Label("Locations")
                yield Input(", ".join(config.LOCATIONS), id="s-locations")
            with Horizontal():
                yield Label("Runs Days")
                yield Input(str(config.RUNS_DAYS), id="s-runs-days")
            with Horizontal():
                yield Label("Schedules Days")
                yield Input(str(config.SCHEDULES_DAYS), id="s-schedules-days")
            with Horizontal():
                yield Label("Runs Page Size")
                yield Input(str(config.RUNS_PAGE_SIZE), id="s-runs-page-size")
            with Horizontal():
                yield Label("UA Prefixes")
                yield Input(", ".join(config.UA_PREFIXES), id="s-ua-prefixes")

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.dismiss(self._save())

    def _save(self) -> bool:
        def _int(id: str, fallback: int) -> int:
            try:
                return int(self.query_one(id, Input).value.strip())
            except ValueError:
                return fallback

        def _list(id: str) -> list[str]:
            return [v.strip() for v in self.query_one(id, Input).value.split(",") if v.strip()]

        new_project = self.query_one("#s-project", Input).value.strip()
        new_locations = _list("#s-locations")
        new_runs_days = _int("#s-runs-days", config.RUNS_DAYS)
        new_schedules_days = _int("#s-schedules-days", config.SCHEDULES_DAYS)

        needs_refresh = (
            new_project != config.PROJECT
            or new_locations != config.LOCATIONS
            or new_runs_days != config.RUNS_DAYS
            or new_schedules_days != config.SCHEDULES_DAYS
        )

        config.PROJECT = new_project
        config.LOCATIONS = new_locations
        config.RUNS_DAYS = new_runs_days
        config.SCHEDULES_DAYS = new_schedules_days
        config.RUNS_PAGE_SIZE = _int("#s-runs-page-size", config.RUNS_PAGE_SIZE)
        config.UA_PREFIXES = _list("#s-ua-prefixes")

        return needs_refresh
