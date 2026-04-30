from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, Label

import vertex_explorer.config as config
from vertex_explorer.ui.widgets import ClickableInput

_GRID = [
    [("Runs Days", "s-runs-days"), ("Project", "s-project")],
    [("Schedules Days", "s-schedules-days"), ("Locations", "s-locations")],
]

_GRID_POS = {id_: (r, c) for r, pair in enumerate(_GRID) for c, (_, id_) in enumerate(pair)}
_GRID_ORDER = [(r, c) for r in range(len(_GRID)) for c in range(2)]


def _current_value(id_: str) -> str:
    return {
        "s-runs-days": str(config.RUNS_DAYS),
        "s-project": config.PROJECT,
        "s-schedules-days": str(config.SCHEDULES_DAYS),
        "s-locations": ", ".join(config.LOCATIONS),
    }[id_]


class _NavInput(ClickableInput):
    can_focus = False
    _original_value: str = ""

    def _on_focus(self, event) -> None:
        self._original_value = self.value

    async def _on_click(self, event) -> None:
        self.can_focus = True
        self.focus()
        self.screen.cursor = _GRID_POS[self.id]  # noqa
        await super()._on_click(event)

    def on_blur(self) -> None:
        self.can_focus = False


class SettingsScreen(ModalScreen[bool]):
    cursor: reactive[tuple[int, int]] = reactive((0, 0))

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            with Horizontal(id="settings-header"):
                yield Label("Settings", id="settings-title")
                yield Label("shift+enter to save", id="settings-hint")
            with Horizontal(id="settings-columns"):
                with Vertical(classes="settings-col"):
                    for (lbl, id_), _ in _GRID:
                        with Horizontal(classes="setting-row"):
                            yield Label(lbl, classes="setting-label")
                            yield _NavInput(_current_value(id_), id=id_)
                with Vertical(classes="settings-col"):
                    for _, (lbl, id_) in _GRID:
                        with Horizontal(classes="setting-row"):
                            yield Label(lbl, classes="setting-label")
                            yield _NavInput(_current_value(id_), id=id_)

    def on_mount(self) -> None:
        self.watch_cursor()

    def on_key(self, event) -> None:
        if event.key == "s" and self.focused is None:
            self.dismiss(False)
            event.stop()
            return
        if event.key in ("ctrl+j", "shift+enter"):
            self.set_focus(None)
            needs_refresh = self._save()
            if needs_refresh:
                self.app.notify("Settings updated")
            self.dismiss(needs_refresh)
            event.stop()
            return

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
            inp = self.query_one(f"#{_GRID[row][col][1]}", Input)
            inp.can_focus = True
            inp.focus()
        else:
            return

        event.stop()

    def on_click(self, event) -> None:
        if event.widget is self:
            self.dismiss(False)

    def tab_next(self) -> None:
        if self.focused is not None:
            self.set_focus(None)
        self.cursor = _GRID_ORDER[(_GRID_ORDER.index(self.cursor) + 1) % len(_GRID_ORDER)]

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.set_focus(None)

    def watch_cursor(self) -> None:
        row, col = self.cursor
        for r, pair in enumerate(_GRID):
            for c, (_, id_) in enumerate(pair):
                self.query_one(f"#{id_}").set_class(r == row and c == col, "-cursor")

    def _save(self) -> bool:
        def _str(idx: str) -> str:
            return self.query_one(idx, Input).value.strip()

        def _int(idx: str, fallback: int) -> int:
            try:
                return int(self.query_one(idx, Input).value.strip())
            except ValueError:
                return fallback

        def _list(idx: str) -> list[str]:
            return list(dict.fromkeys([v.strip() for v in self.query_one(idx, Input).value.split(",") if v.strip()]))

        new_runs_days = _int("#s-runs-days", config.RUNS_DAYS)
        new_schedules_days = _int("#s-schedules-days", config.SCHEDULES_DAYS)
        new_project = _str("#s-project")
        new_locations = _list("#s-locations")

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

        if needs_refresh:
            config.save_settings()

        return needs_refresh
