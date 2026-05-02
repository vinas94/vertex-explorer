from typing import NamedTuple

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, Label

import vertex_explorer.config as config
from vertex_explorer.ui.widgets import SettingsInput, Static


class Cell(NamedTuple):
    label: str
    id: str
    kind: str | None = None


_GRID: list[list[Cell | None]] = [
    [Cell("Runs Days", "s-runs-days"), Cell("Project", "s-project")],
    [Cell("Schedules Days", "s-schedules-days"), Cell("Regions", "s-regions")],
    [Cell("Short Regions", "s-short-regions", "checkbox"), None],
]

_GRID_POS = {cell.id: (r, c) for r, row in enumerate(_GRID) for c, cell in enumerate(row) if cell is not None}
_GRID_ORDER = list(_GRID_POS.values())


def _current_value(id_: str) -> str:
    return {
        "s-runs-days": str(config.RUNS_DAYS),
        "s-project": config.PROJECT,
        "s-schedules-days": str(config.SCHEDULES_DAYS),
        "s-regions": ", ".join(config.REGIONS),
    }[id_]


class SettingsScreen(ModalScreen[bool]):
    cursor: reactive[tuple[int, int]] = reactive((0, 0))

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            with Horizontal(id="settings-header"):
                yield Label("Settings", id="settings-title")
                yield Label("shift+enter to save", id="settings-hint")
            with Horizontal(id="settings-columns"):
                for col_idx in range(2):
                    with Vertical(classes="settings-col"):
                        for row in _GRID:
                            cell = row[col_idx]
                            if cell is not None:
                                with Horizontal(classes="settings-row"):
                                    yield Label(cell.label, classes="settings-label")
                                    if cell.kind == "checkbox":
                                        yield Static(value=config.SHORT_REGIONS, id=cell.id, classes="settings-tick")
                                    else:
                                        yield SettingsInput(_current_value(cell.id), id=cell.id)

    def on_mount(self) -> None:
        self.watch_cursor()

    def on_descendant_focus(self) -> None:
        if self.focused is not None and (pos := _GRID_POS.get(self.focused.id)) is not None:
            self.cursor = pos

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
            if cell.kind == "checkbox":
                self.query_one(f"#{cell.id}", Static).toggle()
            else:
                inp = self.query_one(f"#{cell.id}", Input)
                inp.can_focus = True
                inp.focus()
        else:
            return

        event.stop()

    def on_click(self, event) -> None:
        if self.focused is not None and event.widget is not self.focused:
            self.set_focus(None)
        elif event.widget is self:
            self.dismiss(False)

    def tab_next(self) -> None:
        if self.focused is not None:
            self.set_focus(None)
        self.cursor = _GRID_ORDER[(_GRID_ORDER.index(self.cursor) + 1) % len(_GRID_ORDER)]

    def on_input_submitted(self, _: Input.Submitted) -> None:
        self.set_focus(None)

    def watch_cursor(self) -> None:
        cursor = self.cursor
        for id_, pos in _GRID_POS.items():
            self.query_one(f"#{id_}").set_class(pos == cursor, "-cursor")

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
        new_short_regions = self.query_one("#s-short-regions", Static).value

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
