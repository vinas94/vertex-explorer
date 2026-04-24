import webbrowser
from datetime import datetime, timezone

import pendulum
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Input, Label

from config import PROJECT, UA_LOOKBACK_DAYS, UA_PREFIXES
from fetch_jobs import fetch_all
from filter_parser import highlight, parse_filter
from helpers import (
    _fmt_duration,
    _fmt_time,
    _location,
    _run_display_name,
    _run_dots,
    _run_url,
    _schedule_url,
    _short_name,
)


class SchedulesApp(App):
    BINDINGS = [
        Binding("R", "refresh", "Refresh", priority=True),
        Binding("r", "toggle_region", "Region"),
        Binding("f", "focus_filter", "Filter"),
        Binding("a", "toggle_active_only", "Active"),
        Binding("d", "toggle_ua_view", "Failed", priority=True),
        Binding("o", "open_browser", "Open schedule"),
        Binding("O", "open_run", "Open run"),
        Binding("q", "quit", "Quit"),
        Binding("escape", "escape", "Escape", show=False, priority=True),
        Binding("right", "focus_right", show=False, priority=True),
        Binding("left", "focus_left", show=False, priority=True),
    ]
    CSS = """
    #titlebar {
        height: 1;
        background: $primary-darken-1;
        padding: 0 1;
    }
    #titlebar Label { height: 1; }
    #status-left  { width: 1fr; content-align: left middle; }
    #status-center { width: auto; content-align: center middle; text-style: bold; }
    #status-right { width: 1fr; content-align: right middle; link-color: orange; link-style: none; }
    #filter-input { height: 1; border: none; padding: 0 1; }
    #content { height: 1fr; }
    #schedules-table { width: 1fr; overflow-x: hidden; }
    #runs-table { width: 70; overflow-x: hidden; }
    """

    active_only: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self._all_schedules: list[dict] = []
        self._all_runs: list = []
        self._last_refresh: datetime | None = None
        self._loading_schedules: bool = False
        self._loading_runs: bool = False
        self._runs_by_schedule: dict[str, list] = {}
        self._region: str | None = None
        self._ua_failed_runs: list = []
        self._ua_view: bool = False
        self._suppress_row_highlight: bool = False
        self._pre_ua_focus: str | None = None
        self._last_ua_run_key: str | None = None

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Label("", id="status-left"),
            Label("VERTEX EXPLORER", id="status-center"),
            Label("", id="status-right"),
            id="titlebar",
        )
        yield Input(placeholder="filter...", id="filter-input")
        yield Horizontal(
            DataTable(id="schedules-table", cursor_foreground_priority="renderable"),
            DataTable(id="runs-table", cursor_foreground_priority="renderable"),
            id="content",
        )
        yield Footer()

    def on_mount(self) -> None:
        st = self.query_one("#schedules-table", DataTable)
        st.add_column("Region")
        st.add_column("Status")
        st.add_column("Cron")
        st.add_column("Next Run")
        st.add_column("Prev", width=7)
        st.add_column("Name")
        st.cursor_type = "row"
        st.focus()

        rt = self.query_one("#runs-table", DataTable)
        rt.add_columns("Status", "Start", "Duration")
        rt.cursor_type = "row"

        self.action_refresh()

    # ── actions ───────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        if self._loading_schedules or self._loading_runs:
            return
        self._loading_schedules = True
        self._loading_runs = True
        self._all_schedules = []
        self._all_runs = []
        self._runs_by_schedule = {}
        self.query_one("#schedules-table", DataTable).clear()
        self.query_one("#runs-table", DataTable).clear()
        self._update_bar()
        self._load()

    def action_focus_filter(self) -> None:
        self.query_one("#filter-input", Input).focus()

    def action_toggle_ua_view(self) -> None:
        if not self._ua_view:
            focused = self.focused
            self._pre_ua_focus = focused.id if focused else None
            self._ua_view = True
            self._refresh_runs_table()
            self.call_after_refresh(lambda: self.query_one("#runs-table", DataTable).focus())
        else:
            try:
                rt = self.query_one("#runs-table", DataTable)
                self._last_ua_run_key = rt.coordinate_to_cell_key(rt.cursor_coordinate).row_key.value
            except Exception:
                pass
            self._ua_view = False
            self._refresh_runs_table()
            if self._pre_ua_focus:
                try:
                    self.query_one(f"#{self._pre_ua_focus}").focus()
                except Exception:
                    self.query_one("#schedules-table", DataTable).focus()
            else:
                self.query_one("#schedules-table", DataTable).focus()
        self._update_bar()

    def action_toggle_region(self) -> None:
        cycle = {None: "west3", "west3": "west4", "west4": None}
        self._region = cycle[self._region]
        self._refresh_table()

    def action_toggle_active_only(self) -> None:
        self.active_only = not self.active_only
        self._refresh_table()

    def action_open_browser(self) -> None:
        table = self.query_one("#schedules-table", DataTable)
        if not table.rows:
            return
        try:
            name = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            if name and not name.endswith("/__unscheduled__"):
                webbrowser.open(_schedule_url(name))
        except Exception:
            pass

    def action_open_run(self) -> None:
        table = self.query_one("#runs-table", DataTable)
        if not table.rows:
            return
        try:
            name = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            if name:
                webbrowser.open(_run_url(name))
        except Exception:
            pass

    def action_focus_right(self) -> None:
        st = self.query_one("#schedules-table", DataTable)
        rt = self.query_one("#runs-table", DataTable)
        if st.has_focus:
            rt.focus()

    def action_focus_left(self) -> None:
        st = self.query_one("#schedules-table", DataTable)
        rt = self.query_one("#runs-table", DataTable)
        if rt.has_focus:
            st.focus()

    def action_escape(self) -> None:
        fi = self.query_one("#filter-input", Input)
        if fi.has_focus:
            self.query_one("#schedules-table", DataTable).focus()

    # ── events ────────────────────────────────────────────────────────────────

    @on(Input.Changed, "#filter-input")
    def _on_filter_changed(self, _: Input.Changed) -> None:
        self._refresh_table()

    @on(Input.Submitted, "#filter-input")
    def _on_filter_submitted(self, _: Input.Submitted) -> None:
        self.query_one("#schedules-table", DataTable).focus()

    @on(DataTable.RowHighlighted, "#schedules-table")
    def _on_schedule_highlighted(self, _: DataTable.RowHighlighted) -> None:
        if not self._suppress_row_highlight:
            self._refresh_runs_table()

    @on(DataTable.RowSelected, "#runs-table")
    def _on_run_selected(self, event: DataTable.RowSelected) -> None:
        if not self._ua_view:
            return
        run_name = event.row_key.value if event.row_key else None
        if not run_name:
            return
        run = next((r for r in self._ua_failed_runs if r.name == run_name), None)
        if not run or not run.schedule_name:
            return
        self._last_ua_run_key = run_name
        self._ua_view = False
        self._update_bar()
        st = self.query_one("#schedules-table", DataTable)
        for idx, row_key in enumerate(st.rows):
            if row_key.value == run.schedule_name:
                self._suppress_row_highlight = True
                st.move_cursor(row=idx)
                st.focus()

                def _after():
                    self._suppress_row_highlight = False
                    self._refresh_runs_table()

                self.call_after_refresh(_after)
                break

    # ── worker ────────────────────────────────────────────────────────────────

    @work(thread=True)
    def _load(self) -> None:
        try:
            fetch_all(
                on_schedules=lambda s: self.call_from_thread(self._on_schedules_ready, s),
                on_runs=lambda r: self.call_from_thread(self._on_runs_ready, r),
            )
        except Exception as e:
            self.call_from_thread(self._on_error, str(e))

    @staticmethod
    def _synthetic_schedule(loc: str) -> dict:
        return {
            "name": f"projects/{PROJECT}/locations/europe-{loc}/schedules/__unscheduled__",
            "display_name": "Unscheduled runs",
            "state": "-",
            "cron": "-",
            "nextRunTime": None,
            "_synthetic": True,
        }

    def _on_schedules_ready(self, schedules_by_loc: dict) -> None:
        self._all_schedules = [s for sl in schedules_by_loc.values() for s in sl]
        for loc in schedules_by_loc:
            self._all_schedules.append(self._synthetic_schedule(loc.replace("europe-", "")))
        self._last_refresh = datetime.now()
        self._loading_schedules = False
        self._refresh_table()

    def _on_runs_ready(self, runs_by_loc: dict) -> None:
        self._all_runs = [r for rl in runs_by_loc.values() for r in rl]

        by_sched: dict[str, list] = {}
        for r in self._all_runs:
            if r.schedule_name:
                by_sched.setdefault(r.schedule_name, []).append(r)
            else:
                loc = _location(r.name) if r.name else "?"
                synthetic_name = f"projects/{PROJECT}/locations/europe-{loc}/schedules/__unscheduled__"
                by_sched.setdefault(synthetic_name, []).append(r)

        _key = lambda r: r.start_time or datetime.min.replace(tzinfo=timezone.utc)
        for runs in by_sched.values():
            runs.sort(key=_key, reverse=True)
        self._runs_by_schedule = by_sched

        cutoff = pendulum.now("UTC").subtract(days=UA_LOOKBACK_DAYS)
        self._ua_failed_runs = [
            r for r in self._all_runs
            if r.state.name == "PIPELINE_STATE_FAILED"
            and any(_run_display_name(r.name).startswith(p) for p in UA_PREFIXES)
            and (not r.end_time or pendulum.instance(r.end_time) >= cutoff)
        ]

        self._loading_runs = False
        self._refresh_runs_table()
        self._refresh_table()
        self._update_bar()

    def _on_error(self, msg: str) -> None:
        self._loading_schedules = False
        self._loading_runs = False
        self.query_one("#status-left", Label).update(f"[red]Error:[/] {msg[:60]}")
        self.query_one("#status-right", Label).update("")

    # ── rendering ─────────────────────────────────────────────────────────────

    _RUN_STATE_STYLE = {
        "PIPELINE_STATE_RUNNING": "cyan",
        "PIPELINE_STATE_SUCCEEDED": "green",
        "PIPELINE_STATE_FAILED": "red",
        "PIPELINE_STATE_CANCELLED": "yellow",
        "PIPELINE_STATE_CANCELLING": "yellow",
    }

    def _refresh_runs_table(self) -> None:
        selected = self._selected_schedule_name()
        is_unscheduled = selected is not None and selected.endswith("/__unscheduled__")
        wide = self._ua_view or is_unscheduled

        runs_widget = self.query_one("#runs-table")
        new_width = "1fr" if wide else 50
        if runs_widget.styles.width != new_width:
            runs_widget.styles.width = new_width

        self.call_after_refresh(self._populate_runs_table, wide, selected)

    def _populate_runs_table(self, wide: bool, selected: str | None) -> None:
        table = self.query_one("#runs-table", DataTable)
        table.clear(columns=True)
        if wide:
            table.add_columns("Status", "Start", "Duration", "Prev", "Name")
        else:
            table.add_columns("Status", "Start", "Duration")

        runs = self._ua_failed_runs if self._ua_view else (
            self._runs_by_schedule.get(selected, []) if selected else []
        )
        sorted_runs = sorted(
            runs,
            key=lambda r: r.start_time or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        cutoff_24h = pendulum.now("UTC").subtract(hours=24)
        for run in sorted_runs:
            state_name = run.state.name
            short_state = state_name.replace("PIPELINE_STATE_", "")
            state_cell = Text(short_state, style=self._RUN_STATE_STYLE.get(state_name, "dim"))
            recent_fail = (
                state_name == "PIPELINE_STATE_FAILED"
                and run.end_time
                and pendulum.instance(run.end_time) >= cutoff_24h
            )
            start_cell = Text(_fmt_time(run.start_time), style="red" if recent_fail else "")
            if wide:
                prev = (
                    _run_dots(self._runs_by_schedule[run.schedule_name])
                    if run.schedule_name in self._runs_by_schedule
                    else Text()
                )
                table.add_row(
                    state_cell,
                    start_cell,
                    _fmt_duration(run.start_time, run.end_time),
                    prev,
                    _run_display_name(run.name),
                    key=run.name,
                )
            else:
                table.add_row(
                    state_cell,
                    start_cell,
                    _fmt_duration(run.start_time, run.end_time),
                    key=run.name,
                )

        if self._ua_view and self._last_ua_run_key:
            for idx, row_key in enumerate(table.rows):
                if row_key.value == self._last_ua_run_key:
                    table.move_cursor(row=idx)
                    break

    def _selected_schedule_name(self) -> str | None:
        try:
            st = self.query_one("#schedules-table", DataTable)
            return st.coordinate_to_cell_key(st.cursor_coordinate).row_key.value
        except Exception:
            return None

    def _refresh_table(self) -> None:
        table = self.query_one("#schedules-table", DataTable)
        predicate, terms = parse_filter(self.query_one("#filter-input", Input).value)

        try:
            saved_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            saved_key = None

        table.clear()
        count = 0
        _region_rank = {"west3": 1, "west4": 0}
        sorted_schedules = sorted(
            self._all_schedules,
            key=lambda s: (
                1 if s.get("_synthetic") else 0,
                _region_rank.get(_location(s["name"]), -1),
                s.get("nextRunTime") or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        for sched in sorted_schedules:
            state = sched.get("state", "")
            if self.active_only and state != "ACTIVE":
                continue
            name = sched["name"]
            if self._region and _location(name) != self._region:
                continue
            display = sched.get("display_name") or _short_name(name)
            if predicate is not None and not predicate(display):
                continue

            if sched.get("_synthetic"):
                name_cell = Text(display, style="italic dim")
            elif terms:
                name_cell = highlight(display, terms)
            else:
                name_cell = display
            state_cell = Text(state, style="green" if state == "ACTIVE" else "dim")

            recent_runs = self._runs_by_schedule.get(name, [])
            table.add_row(
                _location(name),
                state_cell,
                sched.get("cron", "-") or "-",
                _fmt_time(sched.get("nextRunTime")),
                _run_dots(recent_runs),
                name_cell,
                key=name,
            )
            count += 1

        if saved_key:
            self._suppress_row_highlight = True
            for idx, row_key in enumerate(table.rows):
                if row_key.value == saved_key:
                    table.move_cursor(row=idx)
                    break
            self._suppress_row_highlight = False

        self._update_bar(count)

    def _update_bar(self, count: int | None = None) -> None:
        if self._loading_schedules:
            left = "Fetching schedules..."
        elif self._loading_runs:
            left = "Fetching runs..."
        else:
            total = len(self._all_schedules)
            left = f"{count}/{total} schedules" if self.active_only and count is not None else f"{total} schedules"

        right_parts = []
        if self._ua_failed_runs:
            cutoff = pendulum.now("UTC").subtract(hours=24)
            n = sum(
                1 for r in self._ua_failed_runs
                if r.end_time and pendulum.instance(r.end_time) >= cutoff
            )
            if n:
                style = "bold orange" if self._ua_view else "orange"
                right_parts.append(f'[@click="app.toggle_ua_view"][{style} not underline]⚠ {n} New Failed UA Runs[/][/]')
        if self._region:
            right_parts.append(self._region)
        if self._last_refresh:
            right_parts.append(self._last_refresh.strftime("%H:%M:%S"))

        self.query_one("#status-left", Label).update(left)
        self.query_one("#status-right", Label).update("  ".join(right_parts))
