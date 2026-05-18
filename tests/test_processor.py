import pendulum

from vertex_explorer.config import settings
from vertex_explorer.processor import build_runs_index, build_schedules, synthetic_name, synthetic_schedule


def test_synthetic_name_format():
    settings.project = "myproj"
    assert synthetic_name("eu-west3") == "projects/myproj/locations/eu-west3/schedules/__unscheduled__"


def test_synthetic_schedule_marked():
    s = synthetic_schedule("eu-west3")
    assert s["_synthetic"] is True
    assert s["display_name"] == "Unscheduled runs"
    assert s["state"] == ""


def test_build_schedules_appends_synthetic_per_location():
    schedules_by_loc = {
        "eu-west3": [{"name": "a"}, {"name": "b"}],
        "eu-west4": [{"name": "c"}],
    }
    out = build_schedules(schedules_by_loc)
    # Real schedules preserved
    real_names = [s["name"] for s in out if not s.get("_synthetic")]
    assert sorted(real_names) == ["a", "b", "c"]
    # One synthetic per location
    synthetic = [s for s in out if s.get("_synthetic")]
    assert len(synthetic) == 2


class _FakeState:
    def __init__(self, name):
        self.name = name


class _FakeRun:
    def __init__(self, name, schedule_name="", start=None):
        self.name = name
        self.schedule_name = schedule_name
        self.start_time = start
        self.state = _FakeState("PIPELINE_STATE_SUCCEEDED")


def test_build_runs_index_groups_by_schedule():
    settings.project = "p"
    r1 = _FakeRun(
        "projects/p/locations/eu/pipelineJobs/r1", schedule_name="sched-a", start=pendulum.datetime(2024, 1, 1)
    )
    r2 = _FakeRun(
        "projects/p/locations/eu/pipelineJobs/r2", schedule_name="sched-a", start=pendulum.datetime(2024, 1, 2)
    )
    r3 = _FakeRun(
        "projects/p/locations/eu/pipelineJobs/r3", schedule_name="sched-b", start=pendulum.datetime(2024, 1, 3)
    )
    idx = build_runs_index([r1, r2, r3])
    assert set(idx.keys()) == {"sched-a", "sched-b"}
    # Within a schedule, sorted desc by start_time
    assert idx["sched-a"][0] is r2
    assert idx["sched-a"][1] is r1


def test_build_runs_index_unscheduled_goes_to_synthetic_bucket():
    settings.project = "p"
    r = _FakeRun("projects/p/locations/eu-west3/pipelineJobs/r", schedule_name="")
    idx = build_runs_index([r])
    expected = "projects/p/locations/eu-west3/schedules/__unscheduled__"
    assert expected in idx
    assert idx[expected] == [r]
