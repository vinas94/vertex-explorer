import textual.widgets as widgets
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets._footer import FooterKey


class TabBase(Vertical):
    """Interface every tab in the app implements."""

    @property
    def notification(self) -> str:
        raise NotImplementedError

    @property
    def toggled(self) -> dict[str, bool]:
        raise NotImplementedError

    def focus_default(self) -> None:
        raise NotImplementedError

    def blur_active_input(self, target=None) -> bool:
        raise NotImplementedError

    def escape(self) -> None:
        raise NotImplementedError

    def reset(self) -> None:
        raise NotImplementedError

    def repopulate(self) -> None:
        raise NotImplementedError


class DataTable(widgets.DataTable):
    def _on_resize(self, event: events.Resize) -> None:
        super()._on_resize(event)
        self.refresh()


class Footer(widgets.Footer):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pressed: set[str] = set()
        self._toggled: dict[str, bool] = {}

    async def recompose(self) -> None:
        await super().recompose()
        self._apply_pressed()
        self._apply_toggled()

    def flash(self, action: str) -> None:
        for key in self._keys_for_action(action):
            key.add_class("-pressed")

    def clear_pressed(self, action: str) -> None:
        for key in self._keys_for_action(action):
            key.remove_class("-pressed")

    def hold(self, action: str) -> None:
        self._pressed.add(action)
        for key in self._keys_for_action(action):
            key.add_class("-pressed")

    def release(self, action: str) -> None:
        self._pressed.discard(action)
        for key in self._keys_for_action(action):
            key.remove_class("-pressed")

    def set_toggled(self, actions: dict[str, bool]) -> None:
        self._toggled = actions
        self._apply_toggled()

    def _apply_pressed(self) -> None:
        for key in self._footer_keys:
            key.set_class(key.action in self._pressed, "-pressed")

    def _apply_toggled(self) -> None:
        for key in self._footer_keys:
            key.set_class(self._toggled.get(key.action, False), "-toggled")

    def _keys_for_action(self, action: str):
        return (key for key in self._footer_keys if key.action == action)

    @property
    def _footer_keys(self):
        return self.query(FooterKey)


class Input(widgets.Input):
    BINDINGS = [
        Binding("ctrl+j,shift+enter", "submit", show=False),
    ]

    async def _on_click(self, event) -> None:
        await super()._on_click(event)
        if event.chain == 2:
            self._select_word()
            event.prevent_default()
        elif event.chain >= 3:
            self.action_select_all()
            event.prevent_default()

    def _select_word(self) -> None:
        v, pos = self.value, self.cursor_position
        is_word = lambda c: c.isalnum() or c == "-"
        start = pos
        while start > 0 and is_word(v[start - 1]):
            start -= 1
        end = pos
        while end < len(v) and is_word(v[end]):
            end += 1
        if start < end:
            self.selection = start, end


class SettingsInput(Input):
    can_focus = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._original_value: str = ""

    def _on_focus(self, event) -> None:
        self._original_value = self.value

    def revert(self) -> None:
        self.value = self._original_value

    async def _on_click(self, event) -> None:
        self.can_focus = True
        self.focus()
        await super()._on_click(event)

    def on_blur(self) -> None:
        self.value = self.value.strip()
        self.can_focus = False


class TextArea(widgets.TextArea):
    BINDINGS = [
        Binding("ctrl+j,shift+enter", "submit", show=False),
    ]

    class Submitted(Message):
        def __init__(self, text_area: "TextArea") -> None:
            super().__init__()
            self.text_area = text_area

        @property
        def control(self) -> "TextArea":
            return self.text_area

    def action_submit(self) -> None:
        self.post_message(self.Submitted(self))

    async def _on_click(self, event: events.Click) -> None:
        await super()._on_click(event)
        if event.chain == 2:
            self._select_word()
            event.prevent_default()
        elif event.chain >= 3:
            row, _ = self.cursor_location
            self.select_line(row)
            event.prevent_default()

    def action_delete_to_start_of_line(self) -> None:
        start, end = self.selection
        if start == end:
            row, column = self.cursor_location
            if row > 0 and column == 0:
                previous_line_end = (row - 1, len(self.document.get_line(row - 1)))
                self.delete(previous_line_end, (row, 0), maintain_selection_offset=False)
                return
        super().action_delete_to_start_of_line()

    def _select_word(self) -> None:
        row, column = self.cursor_location
        line = self.document.get_line(row)

        def is_word(char: str) -> bool:
            return char.isalnum() or char == "-"

        start = column
        while start > 0 and is_word(line[start - 1]):
            start -= 1
        end = column
        while end < len(line) and is_word(line[end]):
            end += 1
        if start < end:
            self.move_cursor((row, start))
            self.move_cursor((row, end), select=True)


class Static(widgets.Static):
    checked: reactive[bool] = reactive(False)

    def __init__(self, value: bool = False, **kwargs) -> None:
        super().__init__("[x]" if value else "[ ]", **kwargs)
        self.checked = value

    def watch_checked(self) -> None:
        self.update(Text("[x]" if self.checked else "[ ]"))

    @property
    def value(self) -> bool:
        return self.checked

    def toggle(self) -> None:
        self.checked = not self.checked

    async def _on_click(self, event) -> None:
        self.screen.set_focus(None)
        self.toggle()
        event.stop()
