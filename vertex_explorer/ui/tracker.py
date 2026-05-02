import webbrowser

import pendulum
from rich.text import Text
from textual import on
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import Label, TextArea

import vertex_explorer.config as config
from vertex_explorer.filters import parse_filter
from vertex_explorer.ui.formatters import (
    console_url,
    fmt_duration,
    fmt_name,
    fmt_region,
    fmt_time,
    run_dots,
)
from vertex_explorer.ui.widgets import FilterTextArea, RefreshingDataTable


class TrackerTab(Vertical):
    BINDINGS = [
        Binding("f", "focus_filter", "Filter"),
        Binding("r", "toggle_region", "Region"),
        Binding("a", "toggle_running", "Running"),
        Binding("d", "toggle_failed", "Failed"),
        Binding("c", "toggle_cancelled", "Cancelled"),
        Binding("O", "open_schedule", show=False),
    ]

    filter: reactive[str] = reactive("", init=False)
    region_: reactive[str | None] = reactive(None)
    show_running: reactive[bool] = reactive(False)
    show_failed: reactive[bool] = reactive(False)
    show_cancelled: reactive[bool] = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._offset: int = 0

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self):
        with Horizontal():
            with Vertical(id="tracker-left"):
                yield Label("Filters")
                yield FilterTextArea(id="tracker-filters")
            yield RefreshingDataTable(id="tracker-table", cursor_foreground_priority="renderable")

    def on_mount(self) -> None:
        t = self.query_one("#tracker-table", RefreshingDataTable)
        t.cursor_type = "row"
        self.watch(t, "scroll_y", self._on_scroll_y)

    def focus_default(self) -> None:
        self.query_one("#tracker-table", RefreshingDataTable).focus()

    def blur_active_input(self, target=None) -> bool:
        return self._blur_filters(target)

    # ── actions ───────────────────────────────────────────────────────────────

    def action_focus_filter(self) -> None:
        self.query_one("#tracker-filters", TextArea).focus()

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
        t = self.query_one("#tracker-table", RefreshingDataTable)
        try:
            name = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
            if name:
                webbrowser.open(console_url(name, "runs"))
        except Exception:
            pass

    def action_open_schedule(self) -> None:
        t = self.query_one("#tracker-table", RefreshingDataTable)
        try:
            run_name = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
            if run_name:
                run = self.app.runs_by_name.get(run_name)
                if run and run.schedule_name and not run.schedule_name.endswith("__unscheduled__"):
                    webbrowser.open(console_url(run.schedule_name, "schedules"))
        except Exception:
            pass

    @on(TextArea.Changed, "#tracker-filters")
    def _on_filter_changed(self, event: TextArea.Changed) -> None:
        self.filter = event.text_area.text.strip()

    def on_key(self, event) -> None:
        if event.key in ("ctrl+j", "shift+enter") and self._blur_filters():
            event.stop()

    def watch_filter(self) -> None:
        self.repopulate()
        self.app.update_binding_highlights()

    def escape(self) -> None:
        self._blur_filters()

    def _strip_filters(self) -> None:
        filters = self.query_one("#tracker-filters", TextArea)
        stripped = "\n".join(line.strip() for line in filters.text.splitlines()).strip()
        if stripped != filters.text:
            filters.load_text(stripped)
        self.filter = stripped

    def _blur_filters(self, target=None) -> bool:
        filters = self.query_one("#tracker-filters", TextArea)
        if filters.has_focus and target is not filters:
            self._strip_filters()
            if isinstance(target, RefreshingDataTable):
                target.focus()
            else:
                self.focus_default()
            return True
        return False

    def repopulate(self) -> None:
        t = self.query_one("#tracker-table", RefreshingDataTable)

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
        self.query_one("#tracker-table", RefreshingDataTable).clear(columns=True)

    # ── rendering ─────────────────────────────────────────────────────────────

    def _on_scroll_y(self, scroll_y: float) -> None:
        t = self.query_one("#tracker-table", RefreshingDataTable)
        if self.app.runs and 0 < t.max_scroll_y <= scroll_y:
            self._load_more()

    def _load_more(self) -> None:
        runs = self._filtered_runs
        batch = runs[self._offset : self._offset + config.RUNS_PAGE_SIZE]
        if not batch:
            return
        t = self.query_one("#tracker-table", RefreshingDataTable)
        self._append_rows(t, batch)
        self._offset += len(batch)

    def _append_rows(self, table: RefreshingDataTable, runs: list) -> None:
        schedules_by_name = {s["name"]: s for s in self.app.schedules}
        runs_by_schedule = self.app.runs_by_schedule
        cutoff_24h = pendulum.now("UTC").subtract(hours=24)
        for run in runs:
            state_name = run.state.name
            state = Text(state_name.replace("PIPELINE_STATE_", ""), style=config.RUN_STATE_STYLE.get(state_name, "dim"))
            recent_fail = (
                state_name == "PIPELINE_STATE_FAILED" and run.end_time and pendulum.instance(run.end_time) >= cutoff_24h
            )
            region = Text(fmt_region(run.name) if run.name else "")
            start = Text(fmt_time(run.start_time), style="red" if recent_fail else "")
            end = Text(fmt_time(run.end_time))
            duration = Text(fmt_duration(run.start_time, run.end_time))
            sched = schedules_by_name.get(run.schedule_name) if run.schedule_name else None
            cron = sched["cron"] if sched else ""
            next_run = fmt_time(sched["nextRunTime"]) if sched else ""
            prev = run_dots(runs_by_schedule.get(run.schedule_name, [])) if run.schedule_name else ""
            name = Text(fmt_name(run.name))
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
        predicates = [parse_filter(line)[0] for line in self.filter.splitlines() if line.strip()]
        predicates = [p for p in predicates if p]
        if predicates:
            runs = [r for r in runs if r.name and any(p(fmt_name(r.name)) for p in predicates)]
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
