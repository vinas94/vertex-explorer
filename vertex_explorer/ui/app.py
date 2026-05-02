import os

import pendulum
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label
from textual.widgets._footer import FooterKey

import vertex_explorer.config as config
from vertex_explorer.client import fetch_all
from vertex_explorer.processor import build_runs_index, build_schedules
from vertex_explorer.ui.overview import OverviewTab
from vertex_explorer.ui.settings import SettingsScreen
from vertex_explorer.ui.tracker import TrackerTab


class _Footer(Footer):
    async def recompose(self) -> None:
        await super().recompose()
        self.app.update_binding_highlights()
        for key in self.query(FooterKey):
            if key.action in self.app._persistent_pressed:
                key.add_class("-pressed")


class VertexExplorer(App):
    ALLOW_SELECT = False
    BINDINGS = [
        Binding("R", "refresh", "Refresh"),
        Binding("o", "open", "Open"),
        Binding("s", "settings", "Settings"),
        Binding("q", "quit", "Quit"),
        Binding("escape", "escape", show=False, priority=True),
        Binding("tab", "next_tab", show=False, priority=True),
    ]
    CSS_PATH = "styles.tcss"

    TABS = ["overview", "tracker"]
    tab: reactive[str] = reactive("overview")

    notification: str = ""

    schedules: list[dict] = []
    schedule_names: dict[str, str] = {}
    runs: list = []
    runs_by_schedule: dict[str, list] = {}
    runs_by_name: dict[str, object] = {}

    loading_schedules: bool = False
    loading_runs: bool = False
    last_refresh: pendulum.DateTime | None = None

    _auth_granted: bool = False
    _persistent_pressed: set[str] = set()

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
        yield OverviewTab(id="overview-tab")
        yield TrackerTab(id="tracker-tab")
        yield _Footer()

    def on_mount(self) -> None:
        if not config.PROJECT:
            self.set_notification("[yellow]Configure Project in settings[/]")
            return

        self.set_notification("Initialising...")
        self.fetch_data()

    def on_click(self, event) -> None:
        blur_input = getattr(self._active_tab, "blur_active_input", None)
        if blur_input:
            blur_input(event.widget)
        if event.widget and event.widget.id == "tab-overview":
            self.tab = "overview"
        elif event.widget and event.widget.id == "tab-tracker":
            self.tab = "tracker"

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
        self.query_one(OverviewTab).reset()
        self.query_one(TrackerTab).reset()
        self.fetch_data()

    def action_open(self) -> None:
        self._flash_key("open")
        self._active_tab.action_open_current()

    def action_settings(self) -> None:
        self._flash_key("settings", auto_clear=False)

        def _on_dismiss(needs_refresh: bool) -> None:
            self._persistent_pressed.discard("settings")
            for key in self.query(FooterKey):
                if key.action == "settings":
                    key.remove_class("-pressed")
            if needs_refresh:
                self.action_refresh()

        self.push_screen(SettingsScreen(), _on_dismiss)

    def action_quit(self) -> None:
        self._flash_key("quit")
        self.set_timer(0.005, self._do_quit)

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

    def action_escape(self) -> None:
        if isinstance(self.screen, ModalScreen):
            if isinstance(self.focused, Input):
                self.focused.value = getattr(self.focused, "_original_value", self.focused.value)
                self.screen.set_focus(None)
            else:
                self.screen.dismiss(False)
            return
        self._active_tab.escape()

    def action_next_tab(self) -> None:
        if isinstance(self.screen, ModalScreen):
            if hasattr(self.screen, "tab_next"):
                self.screen.tab_next()
            return
        blur_input = getattr(self._active_tab, "blur_active_input", None)
        if blur_input:
            return
        self.tab = self.TABS[(self.TABS.index(self.tab) + 1) % len(self.TABS)]

    def watch_tab(self) -> None:
        on_overview = self.tab == "overview"
        self.query_one(OverviewTab).display = on_overview
        self.query_one(TrackerTab).display = not on_overview
        self.query_one("#tab-overview").set_class(on_overview, "-active")
        self.query_one("#tab-tracker").set_class(not on_overview, "-active")
        self._active_tab.focus_default()
        self.refresh_status()

    # ── data ─────────────────────────────────────────────────────────────────

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

    @property
    def _active_tab(self) -> OverviewTab | TrackerTab:
        return self.query_one(OverviewTab if self.tab == "overview" else TrackerTab)

    def _flash_key(self, action: str, *, auto_clear: bool = True) -> None:
        if not auto_clear:
            self._persistent_pressed.add(action)
        for key in self.query(FooterKey):
            if key.action == action:
                key.add_class("-pressed")
                if auto_clear:
                    self.set_timer(0.15, lambda k=key: k.remove_class("-pressed"))

    def update_binding_highlights(self) -> None:
        toggled = {}
        if self.tab == "overview":
            tab = self.query_one(OverviewTab)
            toggled = {
                "focus_filter": bool(tab.filter),
                "toggle_region": tab.region_ is not None,
                "toggle_active": tab.active,
            }
        elif self.tab == "tracker":
            tab = self.query_one(TrackerTab)
            toggled = {
                "focus_filter": bool(tab.filter),
                "toggle_region": tab.region_ is not None,
                "toggle_running": tab.show_running,
                "toggle_failed": tab.show_failed,
                "toggle_cancelled": tab.show_cancelled,
            }
        for key in self.query(FooterKey):
            key.set_class(toggled.get(key.action, False), "-toggled")

    def repopulate(self) -> None:
        self.query_one(OverviewTab).repopulate()
        self.query_one(TrackerTab).repopulate()

    def set_notification(self, msg: str) -> None:
        self.notification = msg
        self.refresh_status()

    def refresh_status(self, right: str = "") -> None:
        left = self.notification or getattr(self._active_tab, "notification", "")
        self.query_one("#status-left", Label).update(left)
        self.query_one("#status-right", Label).update(right)
