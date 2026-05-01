import webbrowser

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
        self.refresh()


class OverviewTab(Vertical):
    BINDINGS = [
        Binding("f", "focus_filter", "Filter"),
        Binding("r", "toggle_region", "Region"),
        Binding("a", "toggle_active", "Active"),
        Binding("right", "focus_right", show=False),
        Binding("left", "focus_left", show=False),
    ]

    filter: reactive[str] = reactive("", init=False)
    region_: reactive[str | None] = reactive(None)
    active: reactive[bool] = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._run_cursors: dict[str, str] = {}
        self._run_offsets: dict[str, int] = {}
        self._current_schedule: str | None = None
        self._st_prev_col = None
        self._rt_name_col = None

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
        self.repopulate_runs()
        self.app.update_binding_highlights()

    def action_toggle_region(self) -> None:
        cycle = dict(zip([None, *config.REGIONS], [*config.REGIONS, None]))
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
        self._rt_name_col = None
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
    @on(DataTable.RowSelected, "#schedules-table")
    def _on_schedule_highlighted(self, event: DataTable.RowHighlighted | DataTable.RowSelected) -> None:
        if event.row_key.value != self._current_schedule:
            self.repopulate_runs(event.row_key.value)

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
        table = self.query_one("#schedules-table", _DataTable)

        try:
            saved_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            saved_key = None

        with table.prevent(DataTable.RowHighlighted, DataTable.RowSelected):
            hover = table.hover_coordinate
            table.clear(columns=True)
            table.hover_coordinate = hover
            table.add_column("Region")
            table.add_column("Status")
            table.add_column("Cron")
            table.add_column("Next Run")
            self._st_prev_col = table.add_column("Prev", width=5)
            table.add_column("Name")

            def _sort_key(s):
                region_rank = {loc: len(config.REGIONS) - i - 1 for i, loc in enumerate(config.REGIONS)}
                return (
                    1 if s.get("_synthetic") else 0,
                    region_rank.get(s["name"].split("/")[3], -1),
                    s.get("nextRunTime") or pendulum.DateTime.min,
                )

            synthetic_scheds = [
                schedule
                for schedule in self.app.schedules
                if schedule.get("_synthetic")
                and (not self.region_ or schedule["name"].split("/")[3] == self.region_)
                and self._filtered_unscheduled_runs(schedule["name"])
            ]
            for sched in sorted(self._filtered_schedules + synthetic_scheds, key=_sort_key, reverse=True):
                name = sched["name"]
                state = sched.get("state", "")
                display_name = sched.get("display_name", "")
                synthetic = sched.get("_synthetic")

                _, filter_terms = parse_filter(self.filter)
                if synthetic:
                    name_cell = Text(display_name, style="italic dim")
                elif filter_terms:
                    name_cell = _highlight(display_name, filter_terms)
                else:
                    name_cell = display_name

                runs_by_schedule = self.app.runs_by_schedule
                table.add_row(
                    _fmt_region(name),
                    Text(state, style="green" if state == "ACTIVE" else "dim" if not synthetic else ""),
                    sched.get("cron", ""),
                    _fmt_time(sched.get("nextRunTime")),
                    _run_dots(runs_by_schedule.get(name, [])),
                    name_cell,
                    key=name,
                )

            if saved_key:
                for idx, row_key in enumerate(table.rows):
                    if row_key.value == saved_key:
                        table.move_cursor(row=idx)
                        break

            self.app.refresh_status(right=self.app.last_refresh.strftime("%H:%M:%S") if self.app.last_refresh else "")

    def repopulate_runs(self, selected_schedule: str | None = None) -> None:
        if selected_schedule is None:
            selected_schedule = self._selected_schedule

        if not selected_schedule:
            self._current_schedule = None
            return

        runs_table = self.query_one("#runs-table", _DataTable)
        if not runs_table.columns:
            runs_table.add_columns("Status", "Start", "Duration")
        runs_table.clear()

        is_unscheduled = selected_schedule.endswith("__unscheduled__")
        runs_table.set_class(is_unscheduled, "-unscheduled")

        if is_unscheduled and self._rt_name_col is None:
            self._rt_name_col = runs_table.add_column("Name")
        elif not is_unscheduled and self._rt_name_col is not None:
            runs_table.remove_column(self._rt_name_col)
            self._rt_name_col = None

        runs = self.app.runs_by_schedule.get(selected_schedule, [])

        predicate, filter_terms = parse_filter(self.filter)
        if is_unscheduled and predicate:
            runs = [run for run in runs if run.name and predicate(_fmt_name(run.name))]
        self._append_run_rows(runs_table, runs[: config.RUNS_PAGE_SIZE], is_unscheduled, filter_terms)
        self._run_offsets[selected_schedule] = config.RUNS_PAGE_SIZE

        try:
            key = runs_table.coordinate_to_cell_key(runs_table.cursor_coordinate).row_key.value
            if key:
                self._run_cursors[self._current_schedule] = key
        except Exception:
            pass

        self._current_schedule = selected_schedule

        if selected_schedule in self._run_cursors:
            saved = self._run_cursors[selected_schedule]
            for idx, row_key in enumerate(runs_table.rows):
                if row_key.value == saved:
                    runs_table.move_cursor(row=idx)
                    break

    def _load_more_runs(self) -> None:
        selected = self._current_schedule
        is_unscheduled = selected.endswith("__unscheduled__")
        _, filter_terms = parse_filter(self.filter)
        all_runs = (
            self._filtered_unscheduled_runs(selected) if is_unscheduled else self.app.runs_by_schedule.get(selected, [])
        )
        offset = self._run_offsets.get(selected, 0)
        batch = all_runs[offset : offset + config.RUNS_PAGE_SIZE]
        if not batch:
            return
        table = self.query_one("#runs-table", _DataTable)
        self._append_run_rows(table, batch, is_unscheduled, filter_terms)
        self._run_offsets[selected] = offset + len(batch)

    def _filtered_unscheduled_runs(self, schedule_name: str | None) -> list:
        if not schedule_name:
            return []

        runs = self.app.runs_by_schedule.get(schedule_name, [])
        predicate, _ = parse_filter(self.filter)
        if not predicate:
            return runs

        return [run for run in runs if run.name and predicate(_fmt_name(run.name))]

    def update_dots(self) -> None:
        table = self.query_one("#schedules-table", _DataTable)
        for row_key in table.rows:
            dots = _run_dots(self.app.runs_by_schedule.get(row_key.value, []))
            table.update_cell(row_key, self._st_prev_col, dots)

    @staticmethod
    def _append_run_rows(table: _DataTable, runs: list, is_unscheduled: bool, filter_terms: list[str]) -> None:
        cutoff_24h = pendulum.now("UTC").subtract(hours=24)
        for run in runs:
            state_name = run.state.name
            state = Text(state_name.replace("PIPELINE_STATE_", ""), style=config.RUN_STATE_STYLE.get(state_name, "dim"))
            recent_fail = (
                state_name == "PIPELINE_STATE_FAILED" and run.end_time and pendulum.instance(run.end_time) >= cutoff_24h
            )
            start = Text(_fmt_time(run.start_time), style="red" if recent_fail else "")
            duration = Text(_fmt_duration(run.start_time, run.end_time))
            extra = ()
            if is_unscheduled:
                run_name = _fmt_name(run.name)
                extra = (_highlight(run_name, filter_terms) if filter_terms else Text(run_name),)
            table.add_row(state, start, duration, *extra, key=run.name)

    @property
    def _selected_schedule(self) -> str | None:
        st = self.query_one("#schedules-table", _DataTable)
        if not st.row_count:
            return None
        return st.coordinate_to_cell_key(st.cursor_coordinate).row_key.value

    @property
    def notification(self) -> str:
        total = sum(1 for s in self.app.schedules if not s.get("_synthetic"))
        visible = len(self._filtered_schedules)
        if not total:
            return ""
        if visible != total:
            return f"{visible}/{total} schedules"
        return f"{total} schedules"

    @property
    def _filtered_schedules(self) -> list:
        predicate, _ = parse_filter(self.filter)
        return [
            schedules
            for schedules in self.app.schedules
            if not schedules.get("_synthetic")
            and (not self.active or schedules.get("state") == "ACTIVE")
            and (not self.region_ or schedules["name"].split("/")[3] == self.region_)
            and (not predicate or predicate(schedules.get("display_name", "")))
        ]
