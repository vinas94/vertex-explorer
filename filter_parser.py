from rich.text import Text


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
    text = text.strip()
    if not text:
        return None, []
    try:
        return _Parser(_lex(text)).parse()
    except Exception:
        return None, []


def highlight(text: str, terms: list[str]) -> Text:
    rt = Text(text)
    tl = text.lower()
    for term in terms:
        start = 0
        while (idx := tl.find(term, start)) != -1:
            rt.stylize("bold yellow", idx, idx + len(term))
            start = idx + len(term)
    return rt
