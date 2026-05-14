from typing import TYPE_CHECKING

from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Label
from textual.widgets._data_table import CellDoesNotExist

import vertex_explorer.config as config
from vertex_explorer.filters import parse_filter
from vertex_explorer.ui.formatters import fmt_name, fmt_region, fmt_run_cells, fmt_time, run_dots
from vertex_explorer.ui.widgets import DataTable, TextArea

if TYPE_CHECKING:
    from google.cloud.aiplatform_v1 import PipelineJob


class TrackerTab(Vertical):
    BINDINGS = [
        Binding("f", "focus_filter", "Filter"),
        Binding("r", "toggle_region", "Region"),
        Binding("a", "toggle_running", "Running"),
        Binding("d", "toggle_failed", "Failed"),
        Binding("c", "toggle_cancelled", "Cancelled"),
    ]

    filter: reactive[str] = reactive("", init=False)
    region_: reactive[str | None] = reactive(None)
    running: reactive[bool] = reactive(False)
    failed: reactive[bool] = reactive(False)
    cancelled: reactive[bool] = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._offset: int = 0
        self._predicates: list = []

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self):
        with Horizontal():
            with Vertical(id="tracker-sidebar"):
                yield Label("Filters")
                yield TextArea(id="tracker-filters")
            yield DataTable(id="tracker-table", cursor_foreground_priority="renderable")

    def on_mount(self) -> None:
        t = self.query_one("#tracker-table", DataTable)
        t.cursor_type = "row"
        self.watch(t, "scroll_y", self._on_scroll_y)
        if config.TRACKER_FILTERS:
            self.query_one("#tracker-filters", TextArea).load_text("\n".join(config.TRACKER_FILTERS))

    # ── focus ─────────────────────────────────────────────────────────────────

    def focus_default(self) -> None:
        self.query_one("#tracker-table", DataTable).focus()

    def blur_active_input(self, target=None) -> bool:
        return self._blur_filters(target)

    def escape(self) -> None:
        self._blur_filters()

    # ── render ────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        self._offset = 0
        self.region_ = None
        self.query_one("#tracker-table", DataTable).clear(columns=True)

    def repopulate(self) -> None:
        t = self.query_one("#tracker-table", DataTable)

        try:
            saved_key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
        except CellDoesNotExist:
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

    # ── actions ───────────────────────────────────────────────────────────────

    def action_focus_filter(self) -> None:
        self.query_one("#tracker-filters", TextArea).focus()

    def watch_filter(self) -> None:
        self._predicates = [
            p for line in self.filter.splitlines() if line.strip() for p in [parse_filter(line)[0]] if p
        ]
        self.repopulate()
        self.app.update_binding_highlights()

    def action_toggle_region(self) -> None:
        options = [None, *config.REGIONS]
        self.region_ = options[(options.index(self.region_) + 1) % len(options)]
        self.repopulate()
        self.app.update_binding_highlights()

    def action_toggle_running(self) -> None:
        self.running = not self.running
        self.repopulate()
        self.app.update_binding_highlights()

    def action_toggle_failed(self) -> None:
        self.failed = not self.failed
        self.repopulate()
        self.app.update_binding_highlights()

    def action_toggle_cancelled(self) -> None:
        self.cancelled = not self.cancelled
        self.repopulate()
        self.app.update_binding_highlights()

    # ── events ────────────────────────────────────────────────────────────────

    @on(TextArea.Changed, "#tracker-filters")
    def _on_filter_changed(self, event: TextArea.Changed) -> None:
        self.filter = event.text_area.text.strip()

    @on(TextArea.Submitted, "#tracker-filters")
    def _on_filter_submitted(self, _: TextArea.Submitted) -> None:
        self._blur_filters()

    def _on_scroll_y(self, scroll_y: float) -> None:
        table = self.query_one("#tracker-table", DataTable)
        if self.app.runs and 0 < table.max_scroll_y <= scroll_y:
            self._load_more()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _blur_filters(self, target=None) -> bool:
        filters = self.query_one("#tracker-filters", TextArea)
        if filters.has_focus and target is not filters:
            self._strip_filters()
            config.TRACKER_FILTERS = [line for line in self.filter.splitlines() if line.strip()]
            config.save_settings()
            if isinstance(target, DataTable):
                target.focus()
            else:
                self.focus_default()
            return True
        return False

    def _strip_filters(self) -> None:
        filters = self.query_one("#tracker-filters", TextArea)
        stripped = "\n".join(line.strip() for line in filters.text.splitlines()).strip()
        if stripped != filters.text:
            filters.load_text(stripped)
        elif self.filter != stripped:
            self.filter = stripped

    def _load_more(self) -> None:
        runs = self._filtered_runs
        batch = runs[self._offset : self._offset + config.RUNS_PAGE_SIZE]
        if not batch:
            return
        t = self.query_one("#tracker-table", DataTable)
        self._append_rows(t, batch)
        self._offset += len(batch)

    def _append_rows(self, table: DataTable, runs: list["PipelineJob"]) -> None:
        schedules_by_name = self.app.schedules_by_name
        runs_by_schedule = self.app.runs_by_schedule
        for run in runs:
            state, start, duration = fmt_run_cells(run)
            region = Text(fmt_region(run.name) if run.name else "")
            end = Text(fmt_time(run.end_time))
            sched = schedules_by_name.get(run.schedule_name, {})
            cron = sched.get("cron")
            next_run = fmt_time(sched.get("nextRunTime"))
            prev = run_dots(runs_by_schedule.get(run.schedule_name, []))
            name = Text(fmt_name(run.name))
            table.add_row(region, state, cron, next_run, prev, start, end, duration, name, key=run.name)

    # ── properties ────────────────────────────────────────────────────────────

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
    def toggled(self) -> dict[str, bool]:
        return {
            "focus_filter": bool(self.filter),
            "toggle_region": self.region_ is not None,
            "toggle_running": self.running,
            "toggle_failed": self.failed,
            "toggle_cancelled": self.cancelled,
        }

    @property
    def _filtered_runs(self) -> list["PipelineJob"]:
        runs = self.app.runs
        if self._predicates:
            runs = [r for r in runs if r.name and any(p(fmt_name(r.name)) for p in self._predicates)]
        if self.region_:
            runs = [r for r in runs if r.name and r.name.split("/")[3] == self.region_]
        if self.running or self.failed or self.cancelled:
            allowed = set()
            if self.running:
                allowed.add("PIPELINE_STATE_RUNNING")
            if self.failed:
                allowed.add("PIPELINE_STATE_FAILED")
            if self.cancelled:
                allowed.add("PIPELINE_STATE_CANCELLED")
                allowed.add("PIPELINE_STATE_CANCELLING")
            runs = [r for r in runs if r.state.name in allowed]
        return runs
