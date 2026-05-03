from typing import TYPE_CHECKING

import pendulum
from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets._data_table import CellDoesNotExist

import vertex_explorer.config as config
from vertex_explorer.filters import parse_filter
from vertex_explorer.ui.formatters import fmt_name, fmt_region, fmt_run_cells, fmt_time, highlight, run_dots
from vertex_explorer.ui.widgets import DataTable, Input

if TYPE_CHECKING:
    from google.cloud.aiplatform_v1 import PipelineJob


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
        self._predicate = None
        self._filter_terms: list[str] = []

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self):
        yield Input(placeholder="filter...", id="overview-filter")
        yield Horizontal(
            DataTable(id="schedules-table", cursor_foreground_priority="renderable"),
            DataTable(id="runs-table", cursor_foreground_priority="renderable"),
            id="overview-content",
        )

    def on_mount(self) -> None:
        self.query_one("#schedules-table", DataTable).cursor_type = "row"
        rt = self.query_one("#runs-table", DataTable)
        rt.cursor_type = "row"
        self.watch(rt, "scroll_y", self._on_runs_scroll_y)

    # ── focus ─────────────────────────────────────────────────────────────────

    def focus_default(self) -> None:
        self.query_one("#schedules-table", DataTable).focus()

    def blur_active_input(self, target=None) -> bool:
        return self._blur_filter(target)

    def escape(self) -> None:
        if self._blur_filter():
            self.focus_default()

    # ── render ────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        self._current_schedule = None
        self._rt_name_col = None
        self.query_one("#schedules-table", DataTable).clear(columns=True)
        self.query_one("#runs-table", DataTable).clear(columns=True)

    def repopulate(self) -> None:
        self.repopulate_schedules()
        self.repopulate_runs()

    def repopulate_schedules(self) -> None:
        table = self.query_one("#schedules-table", DataTable)
        runs_by_schedule = self.app.runs_by_schedule
        filter_terms = self._filter_terms
        region_rank = {loc: len(config.REGIONS) - i - 1 for i, loc in enumerate(config.REGIONS)}

        try:
            saved_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except CellDoesNotExist:
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
                return (
                    1 if s.get("_synthetic") else 0,
                    region_rank.get(s["name"].split("/")[3], -1),
                    s.get("nextRunTime") or pendulum.DateTime.min,
                )

            synthetic_schedules = [
                schedule
                for schedule in self.app.schedules
                if schedule.get("_synthetic")
                and (not self.region_ or schedule["name"].split("/")[3] == self.region_)
                and self._filtered_unscheduled_runs(schedule["name"])
            ]
            for sched in sorted(self._filtered_schedules + synthetic_schedules, key=_sort_key, reverse=True):
                name = sched.get("name", "")
                state = sched.get("state", "")
                display_name = sched.get("display_name", "")
                synthetic = sched.get("_synthetic")

                if synthetic:
                    name_cell = Text(display_name, style="italic dim")
                elif filter_terms:
                    name_cell = highlight(display_name, filter_terms)
                else:
                    name_cell = display_name

                table.add_row(
                    fmt_region(name),
                    Text(state, style="green" if state == "ACTIVE" else "dim" if not synthetic else ""),
                    sched.get("cron"),
                    fmt_time(sched.get("nextRunTime")),
                    run_dots(runs_by_schedule.get(name, [])),
                    name_cell,
                    key=name,
                )

            if saved_key:
                for idx, row_key in enumerate(table.rows):
                    if row_key.value == saved_key:
                        table.move_cursor(row=idx)
                        break

            self.app.refresh_status(right=self.app.last_refresh.strftime("%H:%M:%S") if self.app.last_refresh else "")

    def repopulate_runs(self) -> None:
        selected_schedule = self._selected_schedule
        if not selected_schedule:
            return

        runs_table = self.query_one("#runs-table", DataTable)

        try:
            if current := self._current_schedule:
                if key := runs_table.coordinate_to_cell_key(runs_table.cursor_coordinate).row_key.value:
                    self._run_cursors[current] = key
        except CellDoesNotExist:
            pass

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

        if is_unscheduled and self._predicate:
            runs = [run for run in runs if run.name and self._predicate(fmt_name(run.name))]
        target_offset = max(self._run_offsets.get(selected_schedule, 0), config.RUNS_PAGE_SIZE)
        self._append_run_rows(runs_table, runs[:target_offset], is_unscheduled, self._filter_terms)
        self._run_offsets[selected_schedule] = target_offset

        self._current_schedule = selected_schedule

        if selected_schedule in self._run_cursors:
            saved = self._run_cursors[selected_schedule]
            for idx, row_key in enumerate(runs_table.rows):
                if row_key.value == saved:
                    runs_table.move_cursor(row=idx)
                    break

    def update_dots(self) -> None:
        table = self.query_one("#schedules-table", DataTable)
        for row_key in table.rows:
            dots = run_dots(self.app.runs_by_schedule.get(row_key.value, []))
            table.update_cell(row_key, self._st_prev_col, dots)

    # ── actions ───────────────────────────────────────────────────────────────

    def action_focus_filter(self) -> None:
        self.query_one("#overview-filter", Input).focus()

    def watch_filter(self) -> None:
        self._predicate, self._filter_terms = parse_filter(self.filter)
        self.repopulate_schedules()
        self.repopulate_runs()
        self.app.update_binding_highlights()

    def action_toggle_region(self) -> None:
        options = [None, *config.REGIONS]
        self.region_ = options[(options.index(self.region_) + 1) % len(options)]
        self.repopulate_schedules()
        self.app.update_binding_highlights()

    def action_toggle_active(self) -> None:
        self.active = not self.active
        self.repopulate_schedules()
        self.app.update_binding_highlights()

    def action_focus_right(self) -> None:
        st = self.query_one("#schedules-table", DataTable)
        if st.has_focus:
            self.query_one("#runs-table", DataTable).focus()

    def action_focus_left(self) -> None:
        rt = self.query_one("#runs-table", DataTable)
        if rt.has_focus:
            self.query_one("#schedules-table", DataTable).focus()

    # ── events ────────────────────────────────────────────────────────────────

    @on(Input.Changed, "#overview-filter")
    def _on_filter_changed(self, event: Input.Changed) -> None:
        self.filter = event.value.strip()

    @on(Input.Submitted, "#overview-filter")
    def _on_filter_submitted(self, _: Input.Submitted) -> None:
        filters = self.query_one("#overview-filter", Input)
        filters.value = filters.value.strip()
        self.focus_default()

    @on(DataTable.RowHighlighted, "#schedules-table")
    @on(DataTable.RowSelected, "#schedules-table")
    def _on_schedule_highlighted(self, _: DataTable.RowHighlighted | DataTable.RowSelected) -> None:
        if self.app.runs:
            self.repopulate_runs()

    @on(DataTable.RowHighlighted, "#runs-table")
    def _on_run_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._current_schedule and event.cursor_row == event.data_table.row_count - 1:
            self._load_more_runs()

    def _on_runs_scroll_y(self, scroll_y: float) -> None:
        table = self.query_one("#runs-table", DataTable)
        if self._current_schedule and 0 < table.max_scroll_y <= scroll_y:
            self._load_more_runs()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _blur_filter(self, target=None) -> bool:
        filters = self.query_one("#overview-filter", Input)
        if filters.has_focus and target is not filters:
            filters.value = filters.value.strip()
            if isinstance(target, DataTable):
                target.focus()
            else:
                self.focus_default()
            return True
        return False

    def _load_more_runs(self) -> None:
        selected = self._current_schedule
        if not selected:
            return
        is_unscheduled = selected.endswith("__unscheduled__")
        all_runs = (
            self._filtered_unscheduled_runs(selected) if is_unscheduled else self.app.runs_by_schedule.get(selected, [])
        )
        offset = self._run_offsets.get(selected, 0)
        batch = all_runs[offset : offset + config.RUNS_PAGE_SIZE]
        if not batch:
            return
        table = self.query_one("#runs-table", DataTable)
        self._append_run_rows(table, batch, is_unscheduled, self._filter_terms)
        self._run_offsets[selected] = offset + len(batch)

    def _filtered_unscheduled_runs(self, schedule_name: str | None) -> list["PipelineJob"]:
        if not schedule_name:
            return []

        runs = self.app.runs_by_schedule.get(schedule_name, [])
        if not self._predicate:
            return runs

        return [run for run in runs if run.name and self._predicate(fmt_name(run.name))]

    @staticmethod
    def _append_run_rows(
        table: DataTable, runs: list["PipelineJob"], is_unscheduled: bool, filter_terms: list[str]
    ) -> None:
        cutoff_24h = pendulum.now("UTC").subtract(hours=24)
        for run in runs:
            state, start, duration = fmt_run_cells(run, cutoff_24h)
            extra = ()
            if is_unscheduled:
                run_name = fmt_name(run.name)
                extra = (highlight(run_name, filter_terms) if filter_terms else Text(run_name),)
            table.add_row(state, start, duration, *extra, key=run.name)

    # ── properties ────────────────────────────────────────────────────────────

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
    def toggled(self) -> dict[str, bool]:
        return {
            "focus_filter": bool(self.filter),
            "toggle_region": self.region_ is not None,
            "toggle_active": self.active,
        }

    @property
    def _selected_schedule(self) -> str | None:
        st = self.query_one("#schedules-table", DataTable)
        if not st.row_count:
            return None
        try:
            return st.coordinate_to_cell_key(st.cursor_coordinate).row_key.value
        except CellDoesNotExist:
            return None

    @property
    def _filtered_schedules(self) -> list[dict]:
        return [
            schedules
            for schedules in self.app.schedules
            if not schedules.get("_synthetic")
            and (not self.active or schedules.get("state") == "ACTIVE")
            and (not self.region_ or schedules["name"].split("/")[3] == self.region_)
            and (not self._predicate or self._predicate(schedules.get("display_name")))
        ]
