import pendulum

from vertex_explorer.config import settings
from vertex_explorer.ui.formatters import console_url, fmt_duration, fmt_name, fmt_region, fmt_time, highlight

SCHEDULE_NAME = "projects/myproj/locations/europe-west3/schedules/abc"
RUN_NAME = "projects/myproj/locations/europe-west3/pipelineJobs/myjob-20240115120000"


def test_console_url_schedule():
    url = console_url(SCHEDULE_NAME, "schedules")
    assert "europe-west3" in url
    assert "/schedules/abc" in url
    assert "project=myproj" in url


def test_console_url_run():
    url = console_url(RUN_NAME, "runs")
    assert "/runs/myjob-20240115120000" in url


def test_fmt_region_short():
    settings.short_regions = True
    assert fmt_region(SCHEDULE_NAME) == "west3"


def test_fmt_region_long():
    settings.short_regions = False
    try:
        assert fmt_region(SCHEDULE_NAME) == "europe-west3"
    finally:
        settings.short_regions = True


def test_fmt_name_strips_timestamp_suffix():
    assert fmt_name(RUN_NAME) == "myjob"


def test_fmt_name_keeps_resource_id_when_no_suffix():
    name = "projects/myproj/locations/eu/pipelineJobs/no-timestamp"
    assert fmt_name(name) == "no-timestamp"


def test_fmt_time_formats_pendulum_instance():
    ts = pendulum.datetime(2024, 1, 15, 12, 30)
    assert fmt_time(ts) == "01-15 12:30"


def test_fmt_time_returns_empty_on_none():
    assert fmt_time(None) == ""


def test_fmt_duration_seconds_only():
    start = pendulum.datetime(2024, 1, 1, 0, 0, 0)
    end = pendulum.datetime(2024, 1, 1, 0, 0, 42)
    assert "42s" in fmt_duration(start, end)


def test_fmt_duration_minutes():
    start = pendulum.datetime(2024, 1, 1, 0, 0, 0)
    end = pendulum.datetime(2024, 1, 1, 0, 5, 30)
    out = fmt_duration(start, end)
    assert "5m" in out and "30s" in out


def test_fmt_duration_hours():
    start = pendulum.datetime(2024, 1, 1, 0, 0, 0)
    end = pendulum.datetime(2024, 1, 1, 2, 15, 0)
    out = fmt_duration(start, end)
    assert "2h" in out and "15m" in out


def test_fmt_duration_returns_empty_on_invalid():
    assert fmt_duration(None, None) == ""


def test_highlight_marks_term():
    rt = highlight("hello foo world", ["foo"])
    assert "foo" in rt.plain


def test_highlight_case_insensitive_match():
    rt = highlight("Hello FOO world", ["foo"])
    assert "FOO" in rt.plain
