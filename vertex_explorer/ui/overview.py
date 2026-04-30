import webbrowser
from datetime import datetime, timezone

import pendulum
from rich.text import Text
from textual import events, on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input

from vertex_explorer.config import LOCATIONS, RUN_STATE_STYLE, RUNS_PAGE_SIZE
from vertex_explorer.filters import parse_filter
from vertex_explorer.processor import build_runs_index, build_schedules
from vertex_explorer.ui.formatters import (
    _console_url,
    _fmt_duration,
    _fmt_name,
    _fmt_region,
    _fmt_time,
    _highlight,
    _run_dots,
)


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
    filter: reactive[str] = reactive("")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._schedules: list[dict] = []
        self._runs_by_schedule: dict[str, list] = {}
        self._last_refresh: datetime | None = None
        self._loading_schedules = False
        self._loading_runs = False
        self._run_cursors: dict[str, str] = {}
        self._run_offsets: dict[str, int] = {}
        self._current_schedule: str | None = None
        self._total_schedules: int = 0
        self._st_prev_col = None
        self._rt_name_col = None

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self):
        yield Input(placeholder="filter...", id="filter-input")
        yield Horizontal(
            _DataTable(id="schedules-table", cursor_foreground_priority="renderable"),
            _DataTable(id="runs-table", cursor_foreground_priority="renderable"),
            id="content",
        )

    def on_mount(self) -> None:
        st = self.query_one("#schedules-table", _DataTable)
        st.add_column("Region")
        st.add_column("Status")
        st.add_column("Cron")
        st.add_column("Next Run")
        self._st_prev_col = st.add_column("Prev", width=7)
        st.add_column("Name")
        st.cursor_type = "row"

        rt = self.query_one("#runs-table", _DataTable)
        rt.add_columns("Status", "Start", "Duration")
        rt.cursor_type = "row"

        self.watch(rt, "scroll_y", self._on_runs_scroll_y)
        self.reload()

    def focus_default(self) -> None:
        self.query_one("#schedules-table", _DataTable).focus()

    # ── actions ───────────────────────────────────────────────────────────────

    def reload(self) -> None:
        if self._loading_schedules or self._loading_runs:
            return
        self._loading_schedules = True
        self._loading_runs = True
        self._schedules = []
        self._runs_by_schedule = {}
        self._current_schedule = None

        self.query_one("#schedules-table", _DataTable).clear()
        rt = self.query_one("#runs-table", _DataTable)
        rt.clear()
        rt.remove_class("-scheduled")
        self._rt_name_col = rt.add_column("Name")

        self._update_status()
        self.app.fetch_data()

    def open_current(self) -> None:
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

    def escape(self) -> None:
        fi = self.query_one("#filter-input", Input)
        if fi.has_focus:
            self.focus_default()

    def action_focus_filter(self) -> None:
        self.query_one("#filter-input", Input).focus()

    def action_toggle_region(self) -> None:
        cycle = dict(zip([None, *LOCATIONS], [*LOCATIONS, None]))
        self.region_ = cycle[self.region_]
        self._repopulate_schedules()
        self.app._update_binding_highlights()

    def action_toggle_active(self) -> None:
        self.active = not self.active
        self._repopulate_schedules()
        self.app._update_binding_highlights()

    def watch_filter(self) -> None:
        self._repopulate_schedules()
        self.app._update_binding_highlights()

    def action_focus_right(self) -> None:
        st = self.query_one("#schedules-table", _DataTable)
        if st.has_focus:
            self.query_one("#runs-table", _DataTable).focus()

    def action_focus_left(self) -> None:
        rt = self.query_one("#runs-table", _DataTable)
        if rt.has_focus:
            self.query_one("#schedules-table", _DataTable).focus()

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
            self._repopulate_runs()

    @on(DataTable.RowHighlighted, "#runs-table")
    def _on_run_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._current_schedule and event.cursor_row == event.data_table.row_count - 1:
            self._load_more_runs()

    def _on_runs_scroll_y(self, scroll_y: float) -> None:
        table = self.query_one("#runs-table", _DataTable)
        if self._current_schedule and table.max_scroll_y > 0 and scroll_y >= table.max_scroll_y:
            self._load_more_runs()

    # ── data loading ──────────────────────────────────────────────────────────

    def _on_schedules_ready(self, schedules_by_loc: dict) -> None:
        self._schedules = build_schedules(schedules_by_loc)
        self._total_schedules = sum(1 for s in self._schedules if not s.get("_synthetic"))
        self._last_refresh = datetime.now()
        self._loading_schedules = False
        self._repopulate_schedules()

    def _on_runs_ready(self, runs_by_loc: dict) -> None:
        all_runs = [r for rl in runs_by_loc.values() for r in rl]
        self._runs_by_schedule = build_runs_index(all_runs)
        self._loading_runs = False
        self._update_dots()
        self._repopulate_runs()

    def _update_dots(self) -> None:
        table = self.query_one("#schedules-table", _DataTable)
        for row_key in table.rows:
            dots = _run_dots(self._runs_by_schedule.get(row_key.value, []))
            try:
                table.update_cell(row_key, self._st_prev_col, dots)
            except Exception:
                pass

    def _on_fetch_error(self) -> None:
        self._loading_schedules = False
        self._loading_runs = False

    # ── rendering ─────────────────────────────────────────────────────────────

    def _repopulate_schedules(self) -> None:
        table = self.query_one("#schedules-table", _DataTable)
        predicate, filter_terms = parse_filter(self.filter)

        try:
            saved_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            saved_key = None

        count = 0
        table.clear()
        region_rank = {loc: len(LOCATIONS) - i - 1 for i, loc in enumerate(LOCATIONS)}

        def _sort_key(s):
            return (
                1 if s.get("_synthetic") else 0,
                region_rank.get(s["name"].split("/")[3], -1),
                s.get("nextRunTime") or datetime.min.replace(tzinfo=timezone.utc),
            )

        for sched in sorted(self._schedules, key=_sort_key, reverse=True):
            name = sched["name"]
            state = sched.get("state", "")
            display = sched.get("display_name", "")
            synthetic = sched.get("_synthetic")

            if self.active and state != "ACTIVE" and not synthetic:
                continue
            if self.region_ and name.split("/")[3] != self.region_:
                continue
            if predicate and not predicate(display):
                continue

            if synthetic:
                name_cell = Text(display, style="italic dim")
            elif filter_terms:
                name_cell = _highlight(display, filter_terms)
            else:
                name_cell = display

            table.add_row(
                _fmt_region(name),
                Text(state, style="green" if state == "ACTIVE" else "dim"),
                sched.get("cron", "-") or "-",
                _fmt_time(sched.get("nextRunTime")),
                _run_dots(self._runs_by_schedule.get(name, [])),
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

        self._update_status(count)

    def _repopulate_runs(self) -> None:
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
        runs_table.clear()
        if is_unscheduled and self._rt_name_col is None:
            self._rt_name_col = runs_table.add_column("Name")
        elif not is_unscheduled and self._rt_name_col is not None:
            runs_table.remove_column(self._rt_name_col)
            self._rt_name_col = None

        all_runs = self._runs_by_schedule.get(selected_schedule, [])
        self._append_run_rows(runs_table, all_runs[:RUNS_PAGE_SIZE], is_unscheduled)
        self._run_offsets[selected_schedule] = RUNS_PAGE_SIZE

        if selected_schedule in self._run_cursors:
            saved = self._run_cursors[selected_schedule]
            for idx, row_key in enumerate(runs_table.rows):
                if row_key.value == saved:
                    runs_table.move_cursor(row=idx)
                    break

    def _load_more_runs(self) -> None:
        selected = self._current_schedule
        all_runs = self._runs_by_schedule.get(selected, [])
        offset = self._run_offsets.get(selected, 0)
        batch = all_runs[offset : offset + RUNS_PAGE_SIZE]
        if not batch:
            return
        is_unscheduled = selected.endswith("__unscheduled__")
        table = self.query_one("#runs-table", _DataTable)
        self._append_run_rows(table, batch, is_unscheduled)
        self._run_offsets[selected] = offset + len(batch)

    def _append_run_rows(self, table: _DataTable, runs: list, is_unscheduled: bool) -> None:
        cutoff_24h = pendulum.now("UTC").subtract(hours=24)
        for run in runs:
            state_name = run.state.name
            state = Text(state_name.replace("PIPELINE_STATE_", ""), style=RUN_STATE_STYLE.get(state_name, "dim"))
            recent_fail = (
                state_name == "PIPELINE_STATE_FAILED" and run.end_time and pendulum.instance(run.end_time) >= cutoff_24h
            )
            start = Text(_fmt_time(run.start_time), style="red" if recent_fail else "")
            duration = Text(_fmt_duration(run.start_time, run.end_time))
            extra = (Text(_fmt_name(run.name)),) if is_unscheduled else ()
            table.add_row(state, start, duration, *extra, key=run.name)

    @property
    def _selected_schedule(self) -> str | None:
        try:
            st = self.query_one("#schedules-table", _DataTable)
            return st.coordinate_to_cell_key(st.cursor_coordinate).row_key.value
        except Exception:
            return None

    def _update_status(self, visible_schedules: int | None = None) -> None:
        if self._loading_schedules or self._loading_runs:
            left = f"Fetching {'schedules' if self._loading_schedules else 'runs'}..."
        elif visible_schedules is not None and visible_schedules != self._total_schedules:
            left = f"{visible_schedules}/{self._total_schedules} schedules"
        else:
            left = f"{self._total_schedules} schedules"

        right = self._last_refresh.strftime("%H:%M:%S") if self._last_refresh else ""
        self.app.update_status(left=left, right=right)
