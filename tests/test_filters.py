from vertex_explorer.filters import parse_filter


def test_empty_returns_none_predicate():
    pred, terms = parse_filter("")
    assert pred is None
    assert terms == []


def test_whitespace_only_returns_none_predicate():
    pred, terms = parse_filter("   \t  ")
    assert pred is None
    assert terms == []


def test_single_word_substring_match():
    pred, terms = parse_filter("foo")
    assert terms == ["foo"]
    assert pred("foobar") is True
    assert pred("xxfooxx") is True
    assert pred("baz") is False


def test_case_insensitive():
    pred, _ = parse_filter("Foo")
    assert pred("FOOBAR") is True
    assert pred("foobar") is True


def test_or():
    pred, terms = parse_filter("foo|bar")
    assert pred("foo") is True
    assert pred("bar") is True
    assert pred("baz") is False
    assert sorted(terms) == ["bar", "foo"]


def test_and_explicit():
    pred, _ = parse_filter("foo & bar")
    assert pred("foobar") is True
    assert pred("barfoo") is True
    assert pred("foo") is False
    assert pred("bar") is False


def test_and_implicit_via_juxtaposition():
    pred, _ = parse_filter("foo bar")
    assert pred("foobar") is True
    assert pred("foo") is False


def test_parens_grouping():
    pred, _ = parse_filter("(foo|bar) & baz")
    assert pred("foobaz") is True
    assert pred("barbaz") is True
    assert pred("foo") is False
    assert pred("baz") is False
    assert pred("xfoobazx") is True


def test_unclosed_paren_ignored():
    pred, _ = parse_filter("(foo")
    assert pred("foo") is True


def test_terms_lowercased():
    _, terms = parse_filter("FoO|BAR")
    assert sorted(terms) == ["bar", "foo"]
