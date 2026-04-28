import os
import subprocess
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
from textual.widgets._footer import FooterKey

from vertex_explorer.client import fetch_all
from vertex_explorer.config import LOCATIONS, RUN_STATE_STYLE
from vertex_explorer.filters import parse_filter
from vertex_explorer.processor import build_runs_index, build_schedules, fmt_name
from vertex_explorer.ui.formatters import (
    _console_url,
    _fmt_duration,
    _fmt_region,
    _fmt_time,
    _highlight,
    _run_dots,
)


class SchedulesApp(App):
    BINDINGS = [
        Binding("R", "refresh", "Refresh", priority=True),
        Binding("f", "focus_filter", "Filter"),
        Binding("r", "toggle_region", "Region"),
        Binding("a", "toggle_active_only", "Active"),
        Binding("o", "open", "Open"),
        Binding("q", "quit", "Quit"),
        Binding("escape", "escape", "Escape", show=False, priority=True),
        Binding("right", "focus_right", show=False, priority=True),
        Binding("left", "focus_left", show=False, priority=True),
    ]
    CSS_PATH = "app.tcss"

    active_only: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self._schedules: list[dict] = []
        self._runs_by_schedule: dict[str, list] = {}
        self._last_refresh: datetime | None = None
        self._loading_schedules = False
        self._loading_runs = False
        self._region: str | None = None
        self._suppress_highlight = False
        self._run_cursors: dict[str, str] = {}
        self._current_schedule: str | None = None

    # ── layout ────────────────────────────────────────────────────────────────

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
        rt.cursor_type = "row"

        self.action_refresh()

    # ── actions ───────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        if self._loading_schedules or self._loading_runs:
            return
        self._loading_schedules = True
        self._loading_runs = True
        self._schedules = []
        self._runs_by_schedule = {}
        self.query_one("#schedules-table", DataTable).clear()
        rt = self.query_one("#runs-table", DataTable)
        rt.clear(columns=True)
        rt.add_columns("Status", "Start", "Duration", "Name")
        self._update_status()
        self._load()

    def action_toggle_region(self) -> None:
        cycle = dict(zip([None, *LOCATIONS], [*LOCATIONS, None]))
        self._region = cycle[self._region]
        self._repopulate_schedules()
        self._update_binding_highlights()

    def action_toggle_active_only(self) -> None:
        self.active_only = not self.active_only
        self._repopulate_schedules()
        self._update_binding_highlights()

    def action_focus_filter(self) -> None:
        self.query_one("#filter-input", Input).focus()

    def action_quit(self) -> None:
        RESTORE_TERMINAL = (
            "\033[?1000l"  # disable mouse click tracking
            "\033[?1002l"  # disable mouse button-event tracking
            "\033[?1003l"  # disable mouse all-motion tracking
            "\033[?1006l"  # disable SGR extended mouse mode
            "\033[?1049l"  # exit alternate screen
            "\033[?25h"  # show cursor
            "\033[0m"  # reset colors
        )

        with open("/dev/tty", "w") as tty:
            tty.write(RESTORE_TERMINAL)
        subprocess.run(["stty", "sane"], stderr=subprocess.DEVNULL)
        os._exit(0)

    def action_escape(self) -> None:
        fi = self.query_one("#filter-input", Input)
        if fi.has_focus:
            self.query_one("#schedules-table", DataTable).focus()

    def action_open(self) -> None:
        st = self.query_one("#schedules-table", DataTable)
        rt = self.query_one("#runs-table", DataTable)
        try:
            if st.has_focus:
                name = st.coordinate_to_cell_key(st.cursor_coordinate).row_key.value
                if name and not name.endswith("/__unscheduled__"):
                    webbrowser.open(_console_url(name, "schedules"))
            elif rt.has_focus:
                name = rt.coordinate_to_cell_key(rt.cursor_coordinate).row_key.value
                if name:
                    webbrowser.open(_console_url(name, "runs"))
        except Exception:
            pass

    def action_focus_right(self) -> None:
        st = self.query_one("#schedules-table", DataTable)
        if st.has_focus:
            self.query_one("#runs-table", DataTable).focus()

    def action_focus_left(self) -> None:
        rt = self.query_one("#runs-table", DataTable)
        if rt.has_focus:
            self.query_one("#schedules-table", DataTable).focus()

    # ── events ────────────────────────────────────────────────────────────────

    @on(Input.Changed, "#filter-input")
    def _on_filter_changed(self, _: Input.Changed) -> None:
        self._repopulate_schedules()

    @on(Input.Submitted, "#filter-input")
    def _on_filter_submitted(self, _: Input.Submitted) -> None:
        self.query_one("#schedules-table", DataTable).focus()

    @on(DataTable.RowHighlighted, "#schedules-table")
    def _on_schedule_highlighted(self, _: DataTable.RowHighlighted) -> None:
        if not self._suppress_highlight:
            self._repopulate_runs()

    # ── data loading ──────────────────────────────────────────────────────────

    @work(thread=True)
    def _load(self) -> None:
        def _call(fn, *args):
            try:
                self.call_from_thread(fn, *args)
            except RuntimeError:
                pass

        try:
            fetch_all(
                on_schedules=lambda s: _call(self._on_schedules_ready, s),
                on_runs=lambda r: _call(self._on_runs_ready, r),
            )
        except Exception as e:
            _call(self._on_error, str(e))

    def _on_schedules_ready(self, schedules_by_loc: dict) -> None:
        self._schedules = build_schedules(schedules_by_loc)
        self._last_refresh = datetime.now()
        self._loading_schedules = False
        self._repopulate_schedules()

    def _on_runs_ready(self, runs_by_loc: dict) -> None:
        all_runs = [r for rl in runs_by_loc.values() for r in rl]
        self._runs_by_schedule = build_runs_index(all_runs)
        self._loading_runs = False
        self._repopulate_schedules()
        self._repopulate_runs()
        self._update_status()

    def _on_error(self, msg: str) -> None:
        self._loading_schedules = False
        self._loading_runs = False
        self.query_one("#status-left", Label).update(f"[red]Error:[/] {msg[:60]}")
        self.query_one("#status-right", Label).update("")

    def _update_binding_highlights(self) -> None:
        toggled = {
            "toggle_region": self._region is not None,
            "toggle_active_only": self.active_only,
        }
        for key in self.query(FooterKey):
            key.set_class(toggled.get(key.action, False), "-toggled")

    # ── rendering ─────────────────────────────────────────────────────────────

    def _repopulate_schedules(self) -> None:
        table = self.query_one("#schedules-table", DataTable)
        predicate, terms = parse_filter(self.query_one("#filter-input", Input).value)

        try:
            saved_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            saved_key = None

        table.clear()
        count = 0
        region_rank = {loc: len(LOCATIONS) - i - 1 for i, loc in enumerate(LOCATIONS)}
        for sched in sorted(
            self._schedules,
            key=lambda s: (
                1 if s.get("_synthetic") else 0,
                region_rank.get(s["name"].split("/")[3], -1),
                s.get("nextRunTime") or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        ):
            state = sched.get("state", "")
            name = sched["name"]
            display = sched.get("display_name", "")

            if self.active_only and state != "ACTIVE" and not sched.get("_synthetic"):
                continue
            if self._region and name.split("/")[3] != self._region:
                continue
            if predicate is not None and not predicate(display):
                continue

            name_cell = (
                Text(display, style="italic dim")
                if sched.get("_synthetic")
                else _highlight(display, terms)
                if terms
                else display
            )
            table.add_row(
                _fmt_region(name),
                Text(state, style="green" if state == "ACTIVE" else "dim"),
                sched.get("cron", "-") or "-",
                _fmt_time(sched.get("nextRunTime")),
                _run_dots(self._runs_by_schedule.get(name, [])),
                name_cell,
                key=name,
            )
            count += 1

        if saved_key:
            self._suppress_highlight = True
            for idx, row_key in enumerate(table.rows):
                if row_key.value == saved_key:
                    table.move_cursor(row=idx)
                    break
            self._suppress_highlight = False

        self._update_status(count)

    def _repopulate_runs(self) -> None:
        selected = self._selected_schedule()
        is_unscheduled = selected is not None and selected.endswith("/__unscheduled__")

        table = self.query_one("#runs-table", DataTable)

        if self._current_schedule:
            try:
                key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                if key:
                    self._run_cursors[self._current_schedule] = key
            except Exception:
                pass

        table.clear(columns=True)
        if is_unscheduled:
            table.add_columns("Status", "Start", "Duration", "Name")
        else:
            table.add_columns("Status", "Start", "Duration")

        self.query_one("#runs-table").styles.width = "1fr" if is_unscheduled else 50

        runs = self._runs_by_schedule.get(selected, []) if selected else []
        cutoff_24h = pendulum.now("UTC").subtract(hours=24)
        for run in runs:
            state_name = run.state.name
            state_cell = Text(state_name.replace("PIPELINE_STATE_", ""), style=RUN_STATE_STYLE.get(state_name, "dim"))
            recent_fail = (
                state_name == "PIPELINE_STATE_FAILED" and run.end_time and pendulum.instance(run.end_time) >= cutoff_24h
            )
            start_cell = Text(_fmt_time(run.start_time), style="red" if recent_fail else "")
            if is_unscheduled:
                table.add_row(
                    state_cell,
                    start_cell,
                    _fmt_duration(run.start_time, run.end_time),
                    fmt_name(run.name),
                    key=run.name,
                )
            else:
                table.add_row(state_cell, start_cell, _fmt_duration(run.start_time, run.end_time), key=run.name)

        if selected and selected in self._run_cursors:
            saved = self._run_cursors[selected]
            for idx, row_key in enumerate(table.rows):
                if row_key.value == saved:
                    table.move_cursor(row=idx)
                    break

        self._current_schedule = selected

    def _selected_schedule(self) -> str | None:
        try:
            st = self.query_one("#schedules-table", DataTable)
            return st.coordinate_to_cell_key(st.cursor_coordinate).row_key.value
        except Exception:
            return None

    def _update_status(self, count: int | None = None) -> None:
        if self._loading_schedules:
            left = "Fetching schedules..."
        elif self._loading_runs:
            left = "Fetching runs..."
        else:
            total = len(self._schedules)
            left = f"{count}/{total} schedules" if self.active_only and count is not None else f"{total} schedules"

        right_parts = []
        if self._last_refresh:
            right_parts.append(self._last_refresh.strftime("%H:%M:%S"))

        self.query_one("#status-left", Label).update(left)
        self.query_one("#status-right", Label).update("  ".join(right_parts))
