import webbrowser
from datetime import datetime, timezone

import pendulum
from rich.text import Text
from textual import events
from textual.containers import Vertical
from textual.widgets import DataTable

from vertex_explorer.config import RUN_STATE_STYLE, RUNS_PAGE_SIZE
from vertex_explorer.processor import build_schedules
from vertex_explorer.ui.formatters import (
    _console_url,
    _fmt_duration,
    _fmt_name,
    _fmt_region,
    _fmt_time,
)


class _DataTable(DataTable):
    def _on_resize(self, event: events.Resize) -> None:
        super()._on_resize(event)
        self._clear_caches()
        self.refresh()


class TrackerTab(Vertical):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._all_runs: list = []
        self._schedule_names: dict[str, str] = {}
        self._offset: int = 0

    def compose(self):
        yield _DataTable(id="tracker-table", cursor_foreground_priority="renderable")

    def on_mount(self) -> None:
        t = self.query_one("#tracker-table", _DataTable)
        t.add_columns("Status", "Start", "Duration", "Schedule", "Region")
        t.cursor_type = "row"
        self.watch(t, "scroll_y", self._on_scroll_y)

    def focus_default(self) -> None:
        self.query_one("#tracker-table", _DataTable).focus()

    def repopulate(self) -> None:
        t = self.query_one("#tracker-table", _DataTable)
        t.clear(columns=True)
        t.add_columns("Status", "Start", "Duration", "Schedule", "Region")
        self._append_rows(t, self._all_runs[:RUNS_PAGE_SIZE])
        self._offset = RUNS_PAGE_SIZE

    def reset(self) -> None:
        self._all_runs = []
        self._schedule_names = {}
        self._offset = 0
        self.query_one("#tracker-table", _DataTable).clear()

    def escape(self) -> None:
        pass

    def action_open_current(self) -> None:
        t = self.query_one("#tracker-table", _DataTable)
        try:
            name = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
            if name:
                webbrowser.open(_console_url(name, "runs"))
        except Exception:
            pass

    # ── data ─────────────────────────────────────────────────────────────────

    def on_schedules_ready(self, schedules_by_loc: dict) -> None:
        schedules = build_schedules(schedules_by_loc)
        self._schedule_names = {s["name"]: s.get("display_name", "") for s in schedules}

    def on_runs_ready(self, runs_by_loc: dict) -> None:
        all_runs = [r for rl in runs_by_loc.values() for r in rl]
        all_runs.sort(key=lambda r: r.start_time or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        self._all_runs = all_runs
        self._offset = 0
        t = self.query_one("#tracker-table", _DataTable)
        t.clear()
        self._append_rows(t, all_runs[:RUNS_PAGE_SIZE])
        self._offset = RUNS_PAGE_SIZE

    def _on_scroll_y(self, scroll_y: float) -> None:
        t = self.query_one("#tracker-table", _DataTable)
        if self._all_runs and 0 < t.max_scroll_y <= scroll_y:
            self._load_more()

    def _load_more(self) -> None:
        batch = self._all_runs[self._offset : self._offset + RUNS_PAGE_SIZE]
        if not batch:
            return
        t = self.query_one("#tracker-table", _DataTable)
        self._append_rows(t, batch)
        self._offset += len(batch)

    def _append_rows(self, table: _DataTable, runs: list) -> None:
        cutoff_24h = pendulum.now("UTC").subtract(hours=24)
        for run in runs:
            state_name = run.state.name
            state = Text(state_name.replace("PIPELINE_STATE_", ""), style=RUN_STATE_STYLE.get(state_name, "dim"))
            recent_fail = (
                state_name == "PIPELINE_STATE_FAILED" and run.end_time and pendulum.instance(run.end_time) >= cutoff_24h
            )
            start = Text(_fmt_time(run.start_time), style="red" if recent_fail else "")
            duration = Text(_fmt_duration(run.start_time, run.end_time))
            sched_display = self._schedule_name(run)
            region = _fmt_region(run.name) if run.name else "-"
            table.add_row(state, start, duration, sched_display, region, key=run.name)

    def _schedule_name(self, run) -> str:
        if run.schedule_name and run.schedule_name in self._schedule_names:
            name = self._schedule_names[run.schedule_name]
            return name if name else _fmt_name(run.schedule_name)
        return _fmt_name(run.name) if run.name else "-"
