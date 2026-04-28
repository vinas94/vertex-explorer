from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, Label

import vertex_explorer.config as config


class _NavInput(Input):
    can_focus = False

    def on_blur(self) -> None:
        self.can_focus = False


_GRID = [
    [("Runs Days", str(config.RUNS_DAYS), "s-runs-days"), ("Project", config.PROJECT, "s-project")],
    [
        ("Schedules Days", str(config.SCHEDULES_DAYS), "s-schedules-days"),
        ("Locations", ", ".join(config.LOCATIONS), "s-locations"),
    ],
    [
        ("Runs Page Size", str(config.RUNS_PAGE_SIZE), "s-runs-page-size"),
        ("UA Prefixes", ", ".join(config.UA_PREFIXES), "s-ua-prefixes"),
    ],
]


class SettingsScreen(ModalScreen[bool]):
    cursor: reactive[tuple[int, int]] = reactive((0, 0))

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            yield Label("Settings", id="settings-title")
            with Horizontal(id="settings-columns"):
                with Vertical(classes="settings-col"):
                    for (lbl, val, id_), _ in _GRID:
                        with Horizontal(classes="setting-row"):
                            yield Label(lbl, classes="setting-label")
                            yield _NavInput(val, id=id_)
                with Vertical(classes="settings-col"):
                    for _, (lbl, val, id_) in _GRID:
                        with Horizontal(classes="setting-row"):
                            yield Label(lbl, classes="setting-label")
                            yield _NavInput(val, id=id_)

    def on_mount(self) -> None:
        self._highlight()

    def on_key(self, event) -> None:
        if self.focused is not None:
            return
        row, col = self.cursor
        if event.key == "up":
            self.cursor = (max(0, row - 1), col)
        elif event.key == "down":
            self.cursor = (min(len(_GRID) - 1, row + 1), col)
        elif event.key == "left":
            self.cursor = (row, max(0, col - 1))
        elif event.key == "right":
            self.cursor = (row, min(1, col + 1))
        elif event.key == "enter":
            inp = self.query_one(f"#{_GRID[row][col][2]}", Input)
            inp.can_focus = True
            inp.focus()
        else:
            return
        event.stop()

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.set_focus(None)
        self.dismiss(self._save())

    def on_focus(self, _) -> None:
        self._highlight()

    def watch_cursor(self) -> None:
        self._highlight()

    def _highlight(self) -> None:
        row, col = self.cursor
        for r, pair in enumerate(_GRID):
            for c, (_, _, id_) in enumerate(pair):
                self.query_one(f"#{id_}").set_class(r == row and c == col, "-cursor")

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
