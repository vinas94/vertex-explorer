import os

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label
from textual.widgets._footer import FooterKey

from vertex_explorer.client import fetch_all
from vertex_explorer.ui.overview import OverviewTab
from vertex_explorer.ui.settings import SettingsScreen
from vertex_explorer.ui.tracker import TrackerTab


class _Footer(Footer):
    async def recompose(self) -> None:
        pressed = {k.action for k in self.query(FooterKey) if "-pressed" in k.classes}
        await super().recompose()
        self.app._update_binding_highlights()
        for key in self.query(FooterKey):
            if key.action in pressed:
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
    _loading_schedules: bool = False
    _loading_runs: bool = False
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
        yield OverviewTab(id="overview-tab")
        yield TrackerTab(id="tracker-tab")
        yield _Footer()

    def on_mount(self) -> None:
        self.set_notification("Initialising...")
        self.fetch_data()

    def on_click(self, event) -> None:
        if event.widget and event.widget.id == "tab-overview":
            self.tab = "overview"
        elif event.widget and event.widget.id == "tab-tracker":
            self.tab = "tracker"

    # ── actions ───────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._flash_key("refresh")
        if self._loading_schedules or self._loading_runs:
            return
        self.query_one(OverviewTab).reset()
        self.query_one(TrackerTab).reset()
        self.fetch_data()

    def action_open(self) -> None:
        self._flash_key("open")
        self._active_tab.action_open_current()

    def action_settings(self) -> None:
        self._flash_key("settings", auto_clear=False)

        def _on_dismiss(needs_refresh: bool) -> None:
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
        self.tab = self.TABS[(self.TABS.index(self.tab) + 1) % len(self.TABS)]

    def watch_tab(self) -> None:
        on_overview = self.tab == "overview"
        self.query_one(OverviewTab).display = on_overview
        self.query_one(TrackerTab).display = not on_overview
        self.query_one("#tab-overview").set_class(on_overview, "-active")
        self.query_one("#tab-tracker").set_class(not on_overview, "-active")
        self._active_tab.focus_default()
        self._refresh_status()

    # ── data loading ─────────────────────────────────────────────────────────

    def fetch_data(self) -> None:
        if self._loading_schedules or self._loading_runs:
            return
        self._loading_schedules = True
        self._loading_runs = True
        self._fetch_worker()

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
                self._loading_schedules = False
                self._loading_runs = False
                return

        def on_error():
            self._loading_schedules = False
            self._loading_runs = False
            _call(self.set_notification, "[red]Error during fetching[/]")

        try:
            import google.cloud.aiplatform_v1  # noqa: F401

            _call(self.set_notification, "Fetching schedules...")

            overview = self.query_one(OverviewTab)

            def on_schedules(s):
                self._loading_schedules = False
                _call(self.set_notification, "Fetching runs...")
                _call(overview._on_schedules_ready, s)

            def on_runs(r):
                self._loading_runs = False
                _call(self.set_notification, "")
                _call(overview._on_runs_ready, r)

            fetch_all(on_schedules=on_schedules, on_runs=on_runs, on_error=on_error)
        except Exception:
            on_error()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _check_auth(self) -> bool:
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
        for key in self.query(FooterKey):
            if key.action == action:
                key.add_class("-pressed")
                if auto_clear:
                    self.set_timer(0.15, lambda k=key: k.remove_class("-pressed"))

    def _update_binding_highlights(self) -> None:
        toggled = {}
        if self.tab == "overview":
            tab = self.query_one(OverviewTab)
            toggled = {
                "toggle_region": tab.region_ is not None,
                "toggle_active": tab.active,
                "focus_filter": bool(tab.filter),
            }
        for key in self.query(FooterKey):
            key.set_class(toggled.get(key.action, False), "-toggled")

    def set_notification(self, msg: str) -> None:
        self.notification = msg
        self._refresh_status()

    def _refresh_status(self, right: str = "") -> None:
        left = self.notification or getattr(self._active_tab, "notification", "")
        self.query_one("#status-left", Label).update(left)
        self.query_one("#status-right", Label).update(right)

    def update_status(self, left: str = "", right: str = "") -> None:
        self.query_one("#status-left", Label).update(left)
        self.query_one("#status-right", Label).update(right)
