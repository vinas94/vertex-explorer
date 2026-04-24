import os
import re

os.environ.setdefault("GRPC_VERBOSITY", "none")

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

from fetch_jobs import fetch_all

UA_PREFIXES = [
    "tensorflow-install-prediction",
]
UA_LOOKBACK_DAYS = 7

# ── helpers ───────────────────────────────────────────────────────────────────


def _run_url(resource_name: str) -> str:
    parts = resource_name.split("/")
    project, location, run_id = parts[1], parts[3], parts[5]
    return (
        f"https://console.cloud.google.com/agent-platform/pipelines/locations/{location}"
        f"/runs/{run_id}?project={project}"
    )


def _schedule_url(resource_name: str) -> str:
    parts = resource_name.split("/")
    project, location, schedule_id = parts[1], parts[3], parts[5]
    return (
        f"https://console.cloud.google.com/agent-platform/pipelines/locations/{location}"
        f"/schedules/{schedule_id}?project={project}"
    )


def _short_name(resource_name: str) -> str:
    return resource_name.split("/")[-1]


def _run_display_name(resource_name: str) -> str:
    return re.sub(r"-\d{14,}$", "", resource_name.split("/")[-1])


def _location(resource_name: str) -> str:
    parts = resource_name.split("/")
    loc = parts[3] if len(parts) > 3 else "?"
    return loc.replace("europe-", "")


def _fmt_duration(start, end) -> str:
    if not start or not end:
        return "-"
    try:
        secs = int((pendulum.instance(end) - pendulum.instance(start)).total_seconds())
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m {secs % 60:02d}s"
        return f"{secs // 3600}h {(secs % 3600) // 60:02d}m"
    except Exception:
        return "-"


_DOT_STYLE = {
    "PIPELINE_STATE_SUCCEEDED": ("●", "green"),
    "PIPELINE_STATE_FAILED": ("●", "red"),
    "PIPELINE_STATE_RUNNING": ("●", "cyan"),
    "PIPELINE_STATE_CANCELLED": ("●", "yellow"),
    "PIPELINE_STATE_CANCELLING": ("●", "yellow"),
}


def _run_dots(runs: list) -> Text:
    rt = Text()
    for run in runs[:5]:
        dot, style = _DOT_STYLE.get(run.state.name, ("●", "dim"))
        rt.append(dot, style=style)
    return rt


def _trunc(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _fmt_time(ts) -> str:
    if ts is None:
        return "-"
    try:
        return pendulum.instance(ts).format("YYYY-MM-DD HH:mm")
    except Exception:
        return str(ts)[:16]


# ── filter parser ─────────────────────────────────────────────────────────────
# Grammar:
#   expr   = term ("|" term)*
#   term   = factor ("&" factor)*
#   factor = WORD | "(" expr ")"


class _Tok:
    WORD, AND, OR, LP, RP, EOF = "WORD", "AND", "OR", "LP", "RP", "EOF"

    def __init__(self, kind: str, val: str = ""):
        self.kind = kind
        self.val = val


def _lex(text: str) -> list[_Tok]:
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c.isspace():
            i += 1
        elif c == "&":
            out.append(_Tok(_Tok.AND))
            i += 1
        elif c == "|":
            out.append(_Tok(_Tok.OR))
            i += 1
        elif c == "(":
            out.append(_Tok(_Tok.LP))
            i += 1
        elif c == ")":
            out.append(_Tok(_Tok.RP))
            i += 1
        else:
            j = i
            while j < len(text) and text[j] not in " &|()\t\n\r":
                j += 1
            out.append(_Tok(_Tok.WORD, text[i:j]))
            i = j
    out.append(_Tok(_Tok.EOF))
    return out


class _Parser:
    def __init__(self, tokens: list[_Tok]):
        self._t = tokens
        self._i = 0

    def _cur(self) -> _Tok:
        return self._t[self._i]

    def _eat(self) -> _Tok:
        t = self._t[self._i]
        self._i += 1
        return t

    def parse(self) -> tuple:
        if self._cur().kind == _Tok.EOF:
            return None, []
        return self._expr()

    def _expr(self) -> tuple:
        pred, terms = self._term()
        while self._cur().kind == _Tok.OR:
            self._eat()
            rp, rt = self._term()
            lp = pred
            pred = lambda s, lp=lp, rp=rp: lp(s) or rp(s)
            terms = terms + rt
        return pred, terms

    def _term(self) -> tuple:
        pred, terms = self._factor()
        while self._cur().kind == _Tok.AND:
            self._eat()
            rp, rt = self._factor()
            lp = pred
            pred = lambda s, lp=lp, rp=rp: lp(s) and rp(s)
            terms = terms + rt
        return pred, terms

    def _factor(self) -> tuple:
        cur = self._cur()
        if cur.kind == _Tok.LP:
            self._eat()
            pred, terms = self._expr()
            if self._cur().kind == _Tok.RP:
                self._eat()
            return pred, terms
        elif cur.kind == _Tok.WORD:
            w = self._eat().val.lower()
            return lambda s, w=w: w in s.lower(), [w]
        else:
            self._eat()
            return lambda s: True, []


def parse_filter(text: str) -> tuple:
    """Return (predicate | None, highlight_terms). None predicate means no filter."""
    text = text.strip()
    if not text:
        return None, []
    try:
        return _Parser(_lex(text)).parse()
    except Exception:
        return None, []


def _highlight(text: str, terms: list[str]) -> Text:
    rt = Text(text)
    tl = text.lower()
    for term in terms:
        start = 0
        while (idx := tl.find(term, start)) != -1:
            rt.stylize("bold yellow", idx, idx + len(term))
            start = idx + len(term)
    return rt


# ── app ───────────────────────────────────────────────────────────────────────


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
        self._ua_view = not self._ua_view
        self._refresh_runs_table()
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
            cell_key = table.coordinate_to_cell_key(table.cursor_coordinate)
            name = cell_key.row_key.value
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
        full_loc = f"europe-{loc}"
        return {
            "name": f"projects/martin-test-datalab/locations/{full_loc}/schedules/__unscheduled__",
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
                synthetic_name = f"projects/martin-test-datalab/locations/europe-{loc}/schedules/__unscheduled__"
                by_sched.setdefault(synthetic_name, []).append(r)

        _key = lambda r: r.start_time or datetime.min.replace(tzinfo=timezone.utc)
        for runs in by_sched.values():
            runs.sort(key=_key, reverse=True)

        self._runs_by_schedule = by_sched

        cutoff = pendulum.now("UTC").subtract(days=UA_LOOKBACK_DAYS)
        self._ua_failed_runs = [
            r
            for r in self._all_runs
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
        width_changed = runs_widget.styles.width != new_width
        if width_changed:
            runs_widget.styles.width = new_width

        self.call_after_refresh(self._populate_runs_table, wide, selected)

    def _populate_runs_table(self, wide: bool, selected: str | None) -> None:
        table = self.query_one("#runs-table", DataTable)
        table.clear(columns=True)
        if wide:
            table.add_columns("Status", "Start", "Duration", "Prev", "Name")
        else:
            table.add_columns("Status", "Start", "Duration")

        runs = self._ua_failed_runs if self._ua_view else (self._runs_by_schedule.get(selected, []) if selected else [])
        sorted_runs = sorted(
            runs,
            key=lambda r: r.start_time or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        for run in sorted_runs:
            state_name = run.state.name
            short_state = state_name.replace("PIPELINE_STATE_", "")
            state_cell = Text(short_state, style=self._RUN_STATE_STYLE.get(state_name, "dim"))
            if wide:
                prev = (
                    _run_dots(self._runs_by_schedule[run.schedule_name])
                    if run.schedule_name in self._runs_by_schedule
                    else Text()
                )
                table.add_row(
                    state_cell,
                    _fmt_time(run.start_time),
                    _fmt_duration(run.start_time, run.end_time),
                    prev,
                    _run_display_name(run.name),
                    key=run.name,
                )
            else:
                table.add_row(
                    state_cell,
                    _fmt_time(run.start_time),
                    _fmt_duration(run.start_time, run.end_time),
                    key=run.name,
                )

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
                name_cell = _highlight(display, terms)
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
            n = len(self._ua_failed_runs)
            style = "bold orange" if self._ua_view else "orange"
            right_parts.append(f'[@click="app.toggle_ua_view"][{style} not underline]⚠ {n} Failed UA Runs[/][/]')
        if self._region:
            right_parts.append(self._region)
        if self._last_refresh:
            right_parts.append(self._last_refresh.strftime("%H:%M:%S"))

        self.query_one("#status-left", Label).update(left)
        self.query_one("#status-right", Label).update("  ".join(right_parts))


def main() -> None:
    import logging

    _devnull = open(os.devnull, "w")
    for _h in logging.root.handlers:
        if hasattr(_h, "stream"):
            _h.stream = _devnull

    SchedulesApp().run()


if __name__ == "__main__":
    main()
