import webbrowser
from datetime import datetime, timezone

import pendulum
from rich.text import Text
from textual import events, on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input

import vertex_explorer.config as config
from vertex_explorer.filters import parse_filter
from vertex_explorer.ui.formatters import (
    _console_url,
    _fmt_duration,
    _fmt_name,
    _fmt_region,
    _fmt_time,
    _highlight,
    _run_dots,
)
from vertex_explorer.ui.widgets import ClickableInput


class _FilterInput(ClickableInput):
    pass


class _DataTable(DataTable):
    def _on_resize(self, event: events.Resize) -> None:
        super()._on_resize(event)
        self._clear_caches()
        self.refresh()


class OverviewTab(Vertical):
    BINDINGS = [
        Binding("f", "focus_filter", "Filter"),
        Binding("r", "toggle_region", "Region"),
        Binding("a", "toggle_active", "Active"),
        Binding("right", "focus_right", show=False),
        Binding("left", "focus_left", show=False),
    ]

    active: reactive[bool] = reactive(False)
    region_: reactive[str | None] = reactive(None)
    filter: reactive[str] = reactive("", init=False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._run_cursors: dict[str, str] = {}
        self._run_offsets: dict[str, int] = {}
        self._current_schedule: str | None = None
        self._total_schedules: int = 0
        self._visible_schedules: int = 0
        self._st_prev_col = None

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self):
        yield _FilterInput(placeholder="filter...", id="filter-input")
        yield Horizontal(
            _DataTable(id="schedules-table", cursor_foreground_priority="renderable"),
            _DataTable(id="runs-table", cursor_foreground_priority="renderable"),
            id="content",
        )

    def on_mount(self) -> None:
        self.query_one("#schedules-table", _DataTable).cursor_type = "row"
        rt = self.query_one("#runs-table", _DataTable)
        rt.cursor_type = "row"
        self.watch(rt, "scroll_y", self._on_runs_scroll_y)

    def focus_default(self) -> None:
        self.query_one("#schedules-table", _DataTable).focus()

    # ── actions ───────────────────────────────────────────────────────────────

    def action_focus_filter(self) -> None:
        self.query_one("#filter-input", _FilterInput).focus()

    def watch_filter(self) -> None:
        self.repopulate_schedules()
        self.app.update_binding_highlights()

    def action_toggle_region(self) -> None:
        cycle = dict(zip([None, *config.LOCATIONS], [*config.LOCATIONS, None]))
        self.region_ = cycle[self.region_]
        self.repopulate_schedules()
        self.app.update_binding_highlights()

    def action_toggle_active(self) -> None:
        self.active = not self.active
        self.repopulate_schedules()
        self.app.update_binding_highlights()

    def action_open_current(self) -> None:
        st = self.query_one("#schedules-table", _DataTable)
        rt = self.query_one("#runs-table", _DataTable)
        try:
            if st.has_focus:
                name = st.coordinate_to_cell_key(st.cursor_coordinate).row_key.value
                if name and not name.endswith("__unscheduled__"):
                    webbrowser.open(_console_url(name, "schedules"))
            elif rt.has_focus:
                name = rt.coordinate_to_cell_key(rt.cursor_coordinate).row_key.value
                if name:
                    webbrowser.open(_console_url(name, "runs"))
        except Exception:
            pass

    def action_focus_right(self) -> None:
        st = self.query_one("#schedules-table", _DataTable)
        if st.has_focus:
            self.query_one("#runs-table", _DataTable).focus()

    def action_focus_left(self) -> None:
        rt = self.query_one("#runs-table", _DataTable)
        if rt.has_focus:
            self.query_one("#schedules-table", _DataTable).focus()

    def escape(self) -> None:
        fi = self.query_one("#filter-input", _FilterInput)
        if fi.has_focus:
            self.focus_default()

    def repopulate(self) -> None:
        self.repopulate_schedules()
        self.repopulate_runs()

    def reset(self) -> None:
        self._current_schedule = None
        self.query_one("#schedules-table", _DataTable).clear(columns=True)
        self.query_one("#runs-table", _DataTable).clear(columns=True)

    # ── events ────────────────────────────────────────────────────────────────

    @on(Input.Changed, "#filter-input")
    def _on_filter_changed(self, event: Input.Changed) -> None:
        self.filter = event.value

    @on(Input.Submitted, "#filter-input")
    def _on_filter_submitted(self, _: Input.Submitted) -> None:
        self.focus_default()

    @on(DataTable.RowHighlighted, "#schedules-table")
    def _on_schedule_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key.value != self._current_schedule:
            self.repopulate_runs()

    @on(DataTable.RowHighlighted, "#runs-table")
    def _on_run_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._current_schedule and event.cursor_row == event.data_table.row_count - 1:
            self._load_more_runs()

    def _on_runs_scroll_y(self, scroll_y: float) -> None:
        table = self.query_one("#runs-table", _DataTable)
        if self._current_schedule and 0 < table.max_scroll_y <= scroll_y:
            self._load_more_runs()

    # ── rendering ─────────────────────────────────────────────────────────────

    def repopulate_schedules(self) -> None:
        schedules = self.app.schedules
        runs_by_schedule = self.app.runs_by_schedule
        table = self.query_one("#schedules-table", _DataTable)
        predicate, filter_terms = parse_filter(self.filter)

        try:
            saved_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            saved_key = None

        table.clear(columns=True)
        table.add_column("Region")
        table.add_column("Status")
        table.add_column("Cron")
        table.add_column("Next Run")
        self._st_prev_col = table.add_column("Prev", width=5)
        table.add_column("Name")

        region_rank = {loc: len(config.LOCATIONS) - i - 1 for i, loc in enumerate(config.LOCATIONS)}

        def _sort_key(s):
            return (
                1 if s.get("_synthetic") else 0,
                region_rank.get(s["name"].split("/")[3], -1),
                s.get("nextRunTime") or datetime.min.replace(tzinfo=timezone.utc),
            )

        count = 0
        for sched in sorted(schedules, key=_sort_key, reverse=True):
            name = sched["name"]
            state = sched.get("state", "")
            display_name = sched.get("display_name", "")
            synthetic = sched.get("_synthetic")

            if self.active and state != "ACTIVE" and not synthetic:
                continue
            if self.region_ and name.split("/")[3] != self.region_:
                continue
            if predicate and not predicate(display_name):
                continue

            if synthetic:
                name_cell = Text(display_name, style="italic dim")
            elif filter_terms:
                name_cell = _highlight(display_name, filter_terms)
            else:
                name_cell = display_name

            table.add_row(
                _fmt_region(name),
                Text(state, style="green" if state == "ACTIVE" else "dim" if not synthetic else ""),
                sched.get("cron", ""),
                _fmt_time(sched.get("nextRunTime")),
                _run_dots(runs_by_schedule.get(name, [])),
                name_cell,
                key=name,
            )

            if not synthetic:
                count += 1

        if saved_key:
            for idx, row_key in enumerate(table.rows):
                if row_key.value == saved_key:
                    table.move_cursor(row=idx)
                    break

        self._total_schedules = sum(1 for s in schedules if not s.get("_synthetic"))
        self._visible_schedules = count
        self.app.refresh_status(right=self.app.last_refresh.strftime("%H:%M:%S") if self.app.last_refresh else "")

    def repopulate_runs(self) -> None:
        selected_schedule = self._selected_schedule

        runs_table = self.query_one("#runs-table", _DataTable)

        try:
            key = runs_table.coordinate_to_cell_key(runs_table.cursor_coordinate).row_key.value
            if key:
                self._run_cursors[self._current_schedule] = key
        except Exception:
            pass

        is_unscheduled = selected_schedule.endswith("__unscheduled__")
        self._current_schedule = selected_schedule

        runs_table.set_class(not is_unscheduled, "-scheduled")
        runs_table.clear(columns=True)
        runs_table.add_columns("Status", "Start", "Duration")
        if is_unscheduled:
            runs_table.add_column("Name")

        all_runs = self.app.runs_by_schedule.get(selected_schedule, [])
        self._append_run_rows(runs_table, all_runs[: config.RUNS_PAGE_SIZE], is_unscheduled)
        self._run_offsets[selected_schedule] = config.RUNS_PAGE_SIZE

        if selected_schedule in self._run_cursors:
            saved = self._run_cursors[selected_schedule]
            for idx, row_key in enumerate(runs_table.rows):
                if row_key.value == saved:
                    runs_table.move_cursor(row=idx)
                    break

    def _load_more_runs(self) -> None:
        selected = self._current_schedule
        all_runs = self.app.runs_by_schedule.get(selected, [])
        offset = self._run_offsets.get(selected, 0)
        batch = all_runs[offset : offset + config.RUNS_PAGE_SIZE]
        if not batch:
            return
        is_unscheduled = selected.endswith("__unscheduled__")
        table = self.query_one("#runs-table", _DataTable)
        self._append_run_rows(table, batch, is_unscheduled)
        self._run_offsets[selected] = offset + len(batch)

    def update_dots(self) -> None:
        table = self.query_one("#schedules-table", _DataTable)
        for row_key in table.rows:
            dots = _run_dots(self.app.runs_by_schedule.get(row_key.value, []))
            table.update_cell(row_key, self._st_prev_col, dots)

    @staticmethod
    def _append_run_rows(table: _DataTable, runs: list, is_unscheduled: bool) -> None:
        cutoff_24h = pendulum.now("UTC").subtract(hours=24)
        for run in runs:
            state_name = run.state.name
            state = Text(state_name.replace("PIPELINE_STATE_", ""), style=config.RUN_STATE_STYLE.get(state_name, "dim"))
            recent_fail = (
                state_name == "PIPELINE_STATE_FAILED" and run.end_time and pendulum.instance(run.end_time) >= cutoff_24h
            )
            start = Text(_fmt_time(run.start_time), style="red" if recent_fail else "")
            duration = Text(_fmt_duration(run.start_time, run.end_time))
            extra = (Text(_fmt_name(run.name)),) if is_unscheduled else ()
            table.add_row(state, start, duration, *extra, key=run.name)

    @property
    def _selected_schedule(self) -> str | None:
        st = self.query_one("#schedules-table", _DataTable)
        if not st.row_count:
            return None
        return st.coordinate_to_cell_key(st.cursor_coordinate).row_key.value

    @property
    def notification(self) -> str:
        if self._visible_schedules != self._total_schedules:
            return f"{self._visible_schedules}/{self._total_schedules} schedules"
        return f"{self._total_schedules} schedules"
