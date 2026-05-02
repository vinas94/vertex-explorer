from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, Label

import vertex_explorer.config as config
from vertex_explorer.ui.widgets import ClickableInput, Tick

_GRID = [
    [("Runs Days", "s-runs-days"), ("Project", "s-project")],
    [("Schedules Days", "s-schedules-days"), ("Regions", "s-regions")],
    [("Short Regions", "s-short-regions", "checkbox"), None],
]

_GRID_POS = {
    id_: (r, c) for r, pair in enumerate(_GRID) for c, cell in enumerate(pair) if cell for (_, id_, *_) in [cell]
}
_GRID_ORDER = [(r, c) for r in range(len(_GRID)) for c in range(2) if _GRID[r][c] is not None]


def _current_value(id_: str) -> str:
    return {
        "s-runs-days": str(config.RUNS_DAYS),
        "s-project": config.PROJECT,
        "s-schedules-days": str(config.SCHEDULES_DAYS),
        "s-regions": ", ".join(config.REGIONS),
    }[id_]


class _NavInput(ClickableInput):
    can_focus = False
    _original_value: str = ""

    def _on_focus(self, event) -> None:
        self._original_value = self.value

    async def _on_click(self, event) -> None:
        blur_input = getattr(self.screen, "_blur_input", None)
        if blur_input:
            blur_input(self)
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
                    for row in _GRID:
                        cell = row[0]
                        if cell:
                            lbl, id_, *kind = cell
                            with Horizontal(classes="setting-row"):
                                yield Label(lbl, classes="setting-label")
                                if kind and kind[0] == "checkbox":
                                    yield Tick(value=config.SHORT_REGIONS, id=id_, classes="setting-tick")
                                else:
                                    yield _NavInput(_current_value(id_), id=id_)
                with Vertical(classes="settings-col"):
                    for row in _GRID:
                        cell = row[1]
                        if cell:
                            lbl, id_, *kind = cell
                            with Horizontal(classes="setting-row"):
                                yield Label(lbl, classes="setting-label")
                                if kind and kind[0] == "checkbox":
                                    yield Tick(value=config.SHORT_REGIONS, id=id_, classes="setting-tick")
                                else:
                                    yield _NavInput(_current_value(id_), id=id_)

    def on_mount(self) -> None:
        self.watch_cursor()

    def on_key(self, event) -> None:
        if event.key == "s" and self.focused is None:
            self.dismiss(False)
            event.stop()
            return
        if event.key in ("ctrl+j", "shift+enter"):
            needs_refresh = self._save()
            self.dismiss(needs_refresh)
            event.stop()
            return

        if self.focused is not None:
            return

        row, col = self.cursor
        if event.key == "up":
            new_row = max(0, row - 1)
            new_col = col if _GRID[new_row][col] is not None else (1 - col)
            self.cursor = (new_row, new_col)
        elif event.key == "down":
            new_row = min(len(_GRID) - 1, row + 1)
            new_col = col if _GRID[new_row][col] is not None else (1 - col)
            self.cursor = (new_row, new_col)
        elif event.key == "left":
            new_col = max(0, col - 1)
            self.cursor = (row, new_col) if _GRID[row][new_col] is not None else (row, col)
        elif event.key == "right":
            new_col = min(1, col + 1)
            self.cursor = (row, new_col) if _GRID[row][new_col] is not None else (row, col)
        elif event.key == "enter":
            cell = _GRID[row][col]
            _, id_, *kind = cell
            if kind and kind[0] == "checkbox":
                self.query_one(f"#{id_}", Tick).toggle()
            else:
                inp = self.query_one(f"#{id_}", Input)
                inp.can_focus = True
                inp.focus()
        else:
            return

        event.stop()

    def on_click(self, event) -> None:
        if self._blur_input(event.widget):
            if event.widget is self:
                event.stop()
            return
        if event.widget is self:
            self.dismiss(False)

    def tab_next(self) -> None:
        if self.focused is not None:
            self.set_focus(None)
        self.cursor = _GRID_ORDER[(_GRID_ORDER.index(self.cursor) + 1) % len(_GRID_ORDER)]

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.input.value = event.input.value.strip()
        self.set_focus(None)

    def _blur_input(self, target=None) -> bool:
        focused = self.focused
        if isinstance(focused, Input) and focused is not target:
            focused.value = focused.value.strip()
            self.set_focus(None)
            return True
        return False

    def watch_cursor(self) -> None:
        row, col = self.cursor
        for r, pair in enumerate(_GRID):
            for c, cell in enumerate(pair):
                if cell:
                    _, id_, *_ = cell
                    self.query_one(f"#{id_}").set_class(r == row and c == col, "-cursor")

    def _save(self) -> bool:
        def _int(idx: str, fallback: int) -> int:
            try:
                return int(self.query_one(idx, Input).value.strip())
            except ValueError:
                return fallback

        def _list(idx: str) -> list[str]:
            return list(dict.fromkeys([v.strip() for v in self.query_one(idx, Input).value.split(",") if v.strip()]))

        new_runs_days = _int("#s-runs-days", config.RUNS_DAYS)
        new_schedules_days = _int("#s-schedules-days", config.SCHEDULES_DAYS)
        new_project = self.query_one("#s-project", Input).value.strip()
        new_regions = _list("#s-regions")
        new_short_regions = self.query_one("#s-short-regions", Tick).value

        needs_refresh = (
            new_project != config.PROJECT
            or new_regions != config.REGIONS
            or new_runs_days != config.RUNS_DAYS
            or new_schedules_days != config.SCHEDULES_DAYS
        )
        changed = new_short_regions != config.SHORT_REGIONS

        config.PROJECT = new_project
        config.REGIONS = new_regions
        config.RUNS_DAYS = new_runs_days
        config.SCHEDULES_DAYS = new_schedules_days
        config.SHORT_REGIONS = new_short_regions

        if needs_refresh or changed:
            config.save_settings()
            self.app.notify("Settings updated")

        if changed and not needs_refresh:
            self.app.repopulate()

        return needs_refresh
