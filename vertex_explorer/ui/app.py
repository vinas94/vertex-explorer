import os
import webbrowser
from typing import TYPE_CHECKING

import pendulum
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import Click
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Label

import vertex_explorer.config as config
from vertex_explorer.client import fetch_all
from vertex_explorer.processor import build_runs_index, build_schedules
from vertex_explorer.ui.formatters import console_url
from vertex_explorer.ui.overview import OverviewTab
from vertex_explorer.ui.settings import SettingsScreen
from vertex_explorer.ui.tracker import TrackerTab
from vertex_explorer.ui.widgets import Footer, SettingsInput

if TYPE_CHECKING:
    from google.cloud.aiplatform_v1 import PipelineJob


class VertexExplorer(App):
    ALLOW_SELECT = False
    CSS_PATH = "styles.tcss"
    BINDINGS = [
        Binding("R", "refresh", "Refresh"),
        Binding("o", "open", "Open"),
        Binding("O", "shift_open", show=False),
        Binding("s", "settings", "Settings"),
        Binding("q", "quit", "Quit"),
        Binding("escape", "escape", show=False, priority=True),
        Binding("tab", "next_tab", show=False, priority=True),
    ]

    TABS = {
        "overview": OverviewTab,
        "tracker": TrackerTab,
    }
    TABLE_KINDS = {
        "schedules-table": "schedules",
        "runs-table": "runs",
        "tracker-table": "runs",
    }

    notification: str = ""

    tab: reactive[str] = reactive("overview")

    schedules: list[dict] = []
    schedule_names: dict[str, str] = {}
    runs: list["PipelineJob"] = []
    runs_by_schedule: dict[str, list["PipelineJob"]] = {}
    runs_by_name: dict[str, "PipelineJob"] = {}

    loading_schedules: bool = False
    loading_runs: bool = False
    last_refresh: pendulum.DateTime | None = None

    _auth_granted: bool = False

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Label("", id="status-left"),
            Horizontal(
                Label("Overview", id="tab-overview", classes="tab"),
                Label("Tracker", id="tab-tracker", classes="tab"),
                id="tab-indicator",
            ),
            Label("VERTEX EXPLORER", id="status-center"),
            Label("", id="status-right"),
            id="titlebar",
        )
        yield OverviewTab()
        yield TrackerTab()
        yield Footer()

    def on_mount(self) -> None:
        if not config.PROJECT:
            self.set_notification("[yellow]Configure Project in settings[/]")
            return

        self.set_notification("Initialising...")
        self.fetch_data()

    # ── render ────────────────────────────────────────────────────────────────

    def repopulate(self) -> None:
        for tab_cls in self.TABS.values():
            self.query_one(tab_cls).repopulate()

    def update_binding_highlights(self) -> None:
        self.query_one(Footer).set_toggled(self._active_tab.toggled)

    def set_notification(self, msg: str) -> None:
        self.notification = msg
        self.refresh_status()

    def refresh_status(self, right: str = "") -> None:
        left = self.notification or self._active_tab.notification
        self.query_one("#status-left", Label).update(left)
        self.query_one("#status-right", Label).update(right)

    # ── actions ───────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._flash_key("refresh")
        if self.loading_schedules or self.loading_runs:
            return
        self.schedules = []
        self.schedule_names = {}
        self.runs = []
        self.runs_by_schedule = {}
        self.runs_by_name = {}
        for tab_cls in self.TABS.values():
            self.query_one(tab_cls).reset()
        self.fetch_data()

    def action_open(self) -> None:
        self._flash_key("open")
        if res := self._focused_resource:
            kind, name = res
            webbrowser.open(console_url(name, kind))

    def action_shift_open(self) -> None:
        self._flash_key("open")
        if not (res := self._focused_resource):
            return
        kind, name = res
        if kind == "schedules":
            webbrowser.open(console_url(name, "schedules"))
            return
        run = self.runs_by_name.get(name)
        if run and run.schedule_name and not run.schedule_name.endswith("__unscheduled__"):
            webbrowser.open(console_url(run.schedule_name, "schedules"))

    def action_settings(self) -> None:
        self._flash_key("settings", auto_clear=False)

        def _on_dismiss(needs_refresh: bool | None) -> None:
            self.query_one(Footer).release("settings")
            if needs_refresh:
                self.action_refresh()

        self.push_screen(SettingsScreen(), _on_dismiss)

    def action_quit(self) -> None:
        self._flash_key("quit")
        self.set_timer(0.005, self._do_quit)

    def action_escape(self) -> None:
        if not isinstance(self.screen, ModalScreen):
            self._active_tab.escape()
            return
        focused = self.focused
        if not isinstance(focused, Input):
            self.screen.dismiss(False)
            return
        if isinstance(focused, SettingsInput):
            focused.revert()
        self.screen.set_focus(None)

    def action_next_tab(self) -> None:
        if isinstance(self.screen, ModalScreen):
            if hasattr(self.screen, "tab_next"):
                self.screen.tab_next()
            return
        names = list(self.TABS)
        self.tab = names[(names.index(self.tab) + 1) % len(names)]

    def watch_tab(self) -> None:
        for name, tab_cls in self.TABS.items():
            is_active = name == self.tab
            self.query_one(tab_cls).display = is_active
            self.query_one(f"#tab-{name}").set_class(is_active, "-active")
        self._active_tab.focus_default()
        self.refresh_status()

    # ── events ────────────────────────────────────────────────────────────────

    def on_click(self, event: Click) -> None:
        self._active_tab.blur_active_input(event.widget)

    @on(Click, ".tab")
    def _on_tab_click(self, event: Click) -> None:
        if event.widget and (wid := event.widget.id):
            self.tab = wid.removeprefix("tab-")

    # ── data ──────────────────────────────────────────────────────────────────

    def fetch_data(self) -> None:
        if self.loading_schedules or self.loading_runs:
            return
        self.loading_schedules = True
        self.loading_runs = True
        self.last_refresh = pendulum.now()
        self._fetch_worker()

    def on_schedules_ready(self, schedules_by_loc: dict) -> None:
        self.loading_schedules = False
        self.schedules = build_schedules(schedules_by_loc)
        self.schedule_names = {s["name"]: s.get("display_name", "") for s in self.schedules}
        self.set_notification("Fetching runs...")
        self.query_one(OverviewTab).repopulate_schedules()

    def on_runs_ready(self, runs_by_loc: dict) -> None:
        self.loading_runs = False
        all_runs = [r for rl in runs_by_loc.values() for r in rl]
        self.runs_by_schedule = build_runs_index(all_runs)
        self.runs_by_name = {r.name: r for r in all_runs if r.name}
        self.runs = sorted(
            all_runs,
            key=lambda r: r.start_time or pendulum.DateTime.min,
            reverse=True,
        )
        self.set_notification("")
        overview = self.query_one(OverviewTab)
        overview.repopulate_schedules()
        overview.update_dots()
        overview.repopulate_runs()
        self.query_one(TrackerTab).repopulate()

    @work(thread=True)
    def _fetch_worker(self) -> None:
        def _call(fn, *args, **kwargs):
            try:
                self.call_from_thread(fn, *args, **kwargs)
            except RuntimeError:
                pass

        if not self._auth_granted:
            self._auth_granted = self._check_auth()
            if not self._auth_granted:
                _call(self.set_notification, "[red]Authentication error[/]")
                self.loading_schedules = False
                self.loading_runs = False
                return

        def on_error():
            self.loading_schedules = False
            self.loading_runs = False
            _call(self.set_notification, "[red]Fetching failed[/]")

        try:
            import google.cloud.aiplatform_v1  # noqa

            _call(self.set_notification, "Fetching schedules...")
            fetch_all(
                on_schedules=lambda s: _call(self.on_schedules_ready, s),
                on_runs=lambda r: _call(self.on_runs_ready, r),
                on_error=on_error,
            )
        except Exception:
            on_error()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _flash_key(self, action: str, *, auto_clear: bool = True) -> None:
        footer = self.query_one(Footer)
        if auto_clear:
            footer.flash(action)
            self.set_timer(0.15, lambda: footer.clear_pressed(action))
        else:
            footer.hold(action)

    def _do_quit(self) -> None:
        self.workers.cancel_all()
        _stop = self._driver.stop_application_mode

        def _stop_and_exit():
            _stop()
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, 1)
            os.dup2(devnull, 2)
            os.close(devnull)
            os._exit(0)

        self._driver.stop_application_mode = _stop_and_exit
        self.exit()

    @staticmethod
    def _check_auth() -> bool:
        import google.auth
        import google.auth.exceptions
        import google.auth.transport.requests

        try:
            credentials, _ = google.auth.default()
            credentials.refresh(google.auth.transport.requests.Request())
            return True
        except (
            google.auth.exceptions.DefaultCredentialsError,
            google.auth.exceptions.RefreshError,
            google.auth.exceptions.TransportError,
        ):
            return False

    # ── properties ────────────────────────────────────────────────────────────

    @property
    def _active_tab(self) -> OverviewTab | TrackerTab:
        return self.query_one(self.TABS[self.tab])

    @property
    def _focused_resource(self) -> tuple[str, str] | None:
        table = self.focused
        if not isinstance(table, DataTable):
            return None
        kind = self.TABLE_KINDS.get(table.id or "")
        if not kind:
            return None
        try:
            name = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        except Exception:
            return None
        if not name or name.endswith("__unscheduled__"):
            return None
        return kind, name
