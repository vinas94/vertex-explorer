from textual.widgets import Input
from textual.widgets._input import Selection


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
            self.selection = Selection(start, end)
