"""Comfort suggestions from changes made by hand."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

comfort = load("comfort")

NOW = 1_800_000_000 - 1_800_000_000 % 86400 + 20 * 3600     # an evening, UTC used as local time here


def local(ts):
    return str(int(ts // 86400)), int(ts % 86400 // 3600)


def at(days_ago, hour, frm, to):
    return {"ts": NOW - days_ago * 86400 - (NOW % 86400) + hour * 3600, "from": frm, "to": to}


def suggest(changes, comfort_t=20.5):
    return comfort.suggest(changes, local, NOW, 7, 22, comfort_t, 20.0)


def test_turned_up_in_the_evening_raises_comfort():
    s = suggest([at(1, 19, 20.5, 21.5), at(3, 18, 20.5, 21.0), at(6, 20, 20.5, 21.5)])
    assert s and s.kind == "raise_comfort" and s.key == "comfort" and s.value == 21.5 and s.days == 3, s


def test_one_evening_of_fiddling_is_not_a_pattern():
    assert suggest([at(1, 19, 20.5, 21.5), at(1, 20, 21.5, 22.0), at(1, 21, 22.0, 22.5)]) is None
    assert suggest([at(1, 19, 20.5, 20.7), at(3, 18, 20.5, 20.8), at(6, 20, 20.5, 20.7)]) is None   # too small


def test_morning_before_the_comfort_hours_starts_them_earlier():
    s = suggest([at(1, 6, 19.0, 20.5), at(2, 6, 19.0, 20.5), at(4, 5, 19.0, 20.5), at(5, 6, 19.0, 20.5)])
    assert s and s.kind == "earlier_day" and s.key == "day_from" and s.value == 5 and s.days == 4, s


def test_turned_down_late_ends_them_earlier_and_old_changes_do_not_count():
    s = suggest([at(1, 21, 20.5, 19.5), at(2, 21, 20.5, 19.0), at(5, 20, 20.5, 19.5)])
    assert s and s.kind == "earlier_night" and s.key == "day_to" and s.value == 21, s
    assert suggest([at(20, 21, 20.5, 19.5), at(21, 21, 20.5, 19.0), at(25, 20, 20.5, 19.5)]) is None


def test_lower_comfort_never_below_the_day_minimum():
    s = suggest([at(1, 12, 20.5, 19.0), at(2, 13, 20.5, 19.0), at(3, 11, 20.5, 19.0)])
    assert s and s.kind == "lower_comfort" and s.value == 20.0, s



def local_minute(ts):
    return str(int(ts // 86400)), int(ts % 86400 // 60)


def test_a_schedule_is_not_a_person():
    sched = [{"ts": NOW - d * 86400 - (NOW % 86400) + 6 * 3600 + 30 * 60 + m * 60, "from": 19.0, "to": 20.0}
             for d, m in ((1, 0), (2, 1), (3, 0), (5, 2))]                    # every morning 06:30 -> 20.0
    person = [at(1, 19, 20.5, 21.5), at(3, 18, 20.5, 21.0)]
    found = comfort.scheduled(sched + person, local_minute, NOW)
    assert len(found) == 1 and found[0]["minute"] == 390 and found[0]["to"] == 20.0 and found[0]["days"] == 4, found
    assert sorted(found[0]["ts"]) == sorted(c["ts"] for c in sched)
    # a person turning up around the same time but not to the minute is not a schedule
    human = [at(1, 6, 19.0, 20.5), {"ts": at(2, 6, 19.0, 20.5)["ts"] + 25 * 60, "from": 19.0, "to": 20.5}, at(4, 6, 19.0, 21.0)]
    assert comfort.scheduled(human, local_minute, NOW) == []


if __name__ == "__main__":
    run_all(dict(globals()))
