import webbrowser

import pendulum
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable

import vertex_explorer.config as config
from vertex_explorer.ui.formatters import (
    _console_url,
    _fmt_duration,
    _fmt_name,
    _fmt_region,
    _fmt_time,
    _run_dots,
)


class _DataTable(DataTable):
    def _on_resize(self, event: events.Resize) -> None:
        super()._on_resize(event)
        self.refresh()


class TrackerTab(Vertical):
    BINDINGS = [
        Binding("r", "toggle_region", "Region"),
        Binding("a", "toggle_running", "Running"),
        Binding("d", "toggle_failed", "Failed"),
        Binding("c", "toggle_cancelled", "Cancelled"),
        Binding("O", "open_schedule", show=False),
    ]

    region_: reactive[str | None] = reactive(None)
    show_running: reactive[bool] = reactive(False)
    show_failed: reactive[bool] = reactive(False)
    show_cancelled: reactive[bool] = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._offset: int = 0

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self):
        yield Horizontal(
            Vertical(id="tracker-filters"),
            _DataTable(id="tracker-table", cursor_foreground_priority="renderable"),
        )

    def on_mount(self) -> None:
        t = self.query_one("#tracker-table", _DataTable)
        t.cursor_type = "row"
        self.watch(t, "scroll_y", self._on_scroll_y)

    def focus_default(self) -> None:
        self.query_one("#tracker-table", _DataTable).focus()

    # ── actions ───────────────────────────────────────────────────────────────

    def action_toggle_region(self) -> None:
        cycle = dict(zip([None, *config.REGIONS], [*config.REGIONS, None]))
        self.region_ = cycle[self.region_]
        self.repopulate()
        self.app.update_binding_highlights()

    def action_toggle_running(self) -> None:
        self.show_running = not self.show_running
        self.repopulate()
        self.app.update_binding_highlights()

    def action_toggle_failed(self) -> None:
        self.show_failed = not self.show_failed
        self.repopulate()
        self.app.update_binding_highlights()

    def action_toggle_cancelled(self) -> None:
        self.show_cancelled = not self.show_cancelled
        self.repopulate()
        self.app.update_binding_highlights()

    def action_open_current(self) -> None:
        t = self.query_one("#tracker-table", _DataTable)
        try:
            name = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
            if name:
                webbrowser.open(_console_url(name, "runs"))
        except Exception:
            pass

    def action_open_schedule(self) -> None:
        t = self.query_one("#tracker-table", _DataTable)
        try:
            run_name = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
            if run_name:
                run = self.app.runs_by_name.get(run_name)
                if run and run.schedule_name and not run.schedule_name.endswith("__unscheduled__"):
                    webbrowser.open(_console_url(run.schedule_name, "schedules"))
        except Exception:
            pass

    def escape(self) -> None:
        pass

    def repopulate(self) -> None:
        t = self.query_one("#tracker-table", _DataTable)

        try:
            saved_key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
        except Exception:
            saved_key = None

        hover = t.hover_coordinate
        t.clear(columns=True)
        t.hover_coordinate = hover
        t.add_columns("Region", "Status", "Cron", "Next Run", "Prev", "Start", "End", "Duration", "Name")

        runs = self._filtered_runs
        self._append_rows(t, runs[: config.RUNS_PAGE_SIZE])
        self._offset = config.RUNS_PAGE_SIZE

        if saved_key:
            for idx, row_key in enumerate(t.rows):
                if row_key.value == saved_key:
                    t.move_cursor(row=idx)
                    break

        self.app.refresh_status()

    def reset(self) -> None:
        self._offset = 0
        self.region_ = None
        self.query_one("#tracker-table", _DataTable).clear(columns=True)

    # ── rendering ─────────────────────────────────────────────────────────────

    def _on_scroll_y(self, scroll_y: float) -> None:
        t = self.query_one("#tracker-table", _DataTable)
        if self.app.runs and 0 < t.max_scroll_y <= scroll_y:
            self._load_more()

    def _load_more(self) -> None:
        runs = self._filtered_runs
        batch = runs[self._offset : self._offset + config.RUNS_PAGE_SIZE]
        if not batch:
            return
        t = self.query_one("#tracker-table", _DataTable)
        self._append_rows(t, batch)
        self._offset += len(batch)

    def _append_rows(self, table: _DataTable, runs: list) -> None:
        schedules_by_name = {s["name"]: s for s in self.app.schedules}
        runs_by_schedule = self.app.runs_by_schedule
        cutoff_24h = pendulum.now("UTC").subtract(hours=24)
        for run in runs:
            state_name = run.state.name
            state = Text(state_name.replace("PIPELINE_STATE_", ""), style=config.RUN_STATE_STYLE.get(state_name, "dim"))
            recent_fail = (
                state_name == "PIPELINE_STATE_FAILED" and run.end_time and pendulum.instance(run.end_time) >= cutoff_24h
            )
            region = Text(_fmt_region(run.name) if run.name else "")
            start = Text(_fmt_time(run.start_time), style="red" if recent_fail else "")
            end = Text(_fmt_time(run.end_time))
            duration = Text(_fmt_duration(run.start_time, run.end_time))
            sched = schedules_by_name.get(run.schedule_name) if run.schedule_name else None
            cron = sched["cron"] if sched else ""
            next_run = _fmt_time(sched["nextRunTime"]) if sched else ""
            prev = _run_dots(runs_by_schedule.get(run.schedule_name, [])) if run.schedule_name else ""
            name = Text(_fmt_name(run.name))
            table.add_row(region, state, cron, next_run, prev, start, end, duration, name, key=run.name)

    @property
    def notification(self) -> str:
        total = len(self.app.runs)
        visible = len(self._filtered_runs)
        if not total:
            return ""
        if visible != total:
            return f"{visible}/{total} runs"
        return f"{total} runs"

    @property
    def _filtered_runs(self) -> list:
        runs = self.app.runs
        if self.region_:
            runs = [r for r in runs if r.name and r.name.split("/")[3] == self.region_]
        if self.show_running or self.show_failed or self.show_cancelled:
            allowed = set()
            if self.show_running:
                allowed.add("PIPELINE_STATE_RUNNING")
            if self.show_failed:
                allowed.add("PIPELINE_STATE_FAILED")
            if self.show_cancelled:
                allowed.add("PIPELINE_STATE_CANCELLED")
                allowed.add("PIPELINE_STATE_CANCELLING")
            runs = [r for r in runs if r.state.name in allowed]
        return runs
