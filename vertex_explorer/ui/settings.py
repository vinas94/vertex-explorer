from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label

import vertex_explorer.config as config


class SettingsScreen(ModalScreen[bool]):
    def compose(self) -> ComposeResult:
        left = [
            ("Runs Days", str(config.RUNS_DAYS), "s-runs-days"),
            ("Schedules Days", str(config.SCHEDULES_DAYS), "s-schedules-days"),
            ("Runs Page Size", str(config.RUNS_PAGE_SIZE), "s-runs-page-size"),
        ]
        right = [
            ("Project", config.PROJECT, "s-project"),
            ("Locations", ", ".join(config.LOCATIONS), "s-locations"),
            ("UA Prefixes", ", ".join(config.UA_PREFIXES), "s-ua-prefixes"),
        ]

        with Vertical(id="settings-dialog"):
            yield Label("Settings", id="settings-title")
            with Horizontal(id="settings-columns"):
                with Vertical(classes="settings-col"):
                    for lbl, val, id_ in left:
                        with Horizontal(classes="setting-row"):
                            yield Label(lbl, classes="setting-label")
                            yield Input(val, id=id_)
                with Vertical(classes="settings-col"):
                    for lbl, val, id_ in right:
                        with Horizontal(classes="setting-row"):
                            yield Label(lbl, classes="setting-label")
                            yield Input(val, id=id_)

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
