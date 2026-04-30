from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Input, Static


class Tick(Static):
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
        self.toggle()
        event.stop()


class ClickableInput(Input):
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
