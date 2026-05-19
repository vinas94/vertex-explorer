from typing import Callable

Predicate = Callable[[str], bool]
ParseResult = tuple[Predicate | None, list[str]]


class _Tok:
    WORD, AND, OR, LP, RP, EOF = "WORD", "AND", "OR", "LP", "RP", "EOF"

    def __init__(self, kind: str, val: str = ""):
        self.kind = kind
        self.val = val


def _lex(text: str) -> list[_Tok]:
    i = 0
    out: list[_Tok] = []
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

    def _advance(self) -> _Tok:
        t = self._t[self._i]
        self._i += 1
        return t

    def parse(self) -> ParseResult:
        if self._cur().kind == _Tok.EOF:
            return None, []
        return self._expr()

    def _expr(self) -> ParseResult:
        pred, terms = self._term()
        while self._cur().kind == _Tok.OR:
            self._advance()
            rp, rt = self._term()
            if rp is None:
                continue
            if pred is None:
                pred, terms = rp, rt
                continue
            lp = pred
            pred = lambda s, lp=lp, rp=rp: lp(s) or rp(s)
            terms = terms + rt
        return pred, terms

    def _term(self) -> ParseResult:
        pred, terms = self._factor()
        while self._cur().kind in (_Tok.AND, _Tok.WORD, _Tok.LP):
            if self._cur().kind == _Tok.AND:
                self._advance()
            rp, rt = self._factor()
            if rp is None:
                continue
            if pred is None:
                pred, terms = rp, rt
                continue
            lp = pred
            pred = lambda s, lp=lp, rp=rp: lp(s) and rp(s)
            terms = terms + rt
        return pred, terms

    def _factor(self) -> ParseResult:
        cur = self._cur()
        if cur.kind == _Tok.LP:
            self._advance()
            pred, terms = self._expr()
            if self._cur().kind == _Tok.RP:
                self._advance()
            return pred, terms
        if cur.kind == _Tok.WORD:
            w = self._advance().val.lower()
            return lambda s, w=w: w in s.lower(), [w]
        if cur.kind in (_Tok.RP, _Tok.EOF):
            return None, []
        self._advance()
        return None, []


def parse_filter(text: str) -> ParseResult:
    text = text.strip()
    if not text:
        return None, []
    return _Parser(_lex(text)).parse()
