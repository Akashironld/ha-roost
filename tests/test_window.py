"""A window open: recognised from a fast drop or a window sensor; the hours are marked so Roost does not learn from them."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

window = load("window")

T0 = 1_800_000_000 - 1_800_000_000 % 3600


def run(w, temps, step=120, contact=None):
    """Feed one reading every `step` seconds; -> the events with their minute."""
    out = []
    for i, v in enumerate(temps):
        c = contact[i] if contact else None
        ev = w.feed(T0 + i * step, v, c)
        if ev:
            out.append((ev, i * step // 60))
    return out


def test_airing_is_recognised_and_ends_when_the_room_is_back():
    temps = [21.0] * 5 + [20.8, 20.5, 20.3, 20.2, 20.2] + [20.2] * 6 + [20.4, 20.6, 20.8, 20.9, 21.0]
    w = window.WindowWatch()
    ev = run(w, temps)
    assert ev[0] == ("open", 12) and ev[-1][0] == "end", ev       # 0.5 °C down at minute 12
    assert int(T0 // 3600 * 3600) in w.hours and not w.active()


def test_slow_cooling_is_not_a_window():
    w = window.WindowWatch()
    assert run(w, [21.0 - 0.004 * i for i in range(60)]) == []     # 0.24 °C in two hours: a house cooling
    assert not w.hours


def test_a_window_sensor_starts_and_closes_it():
    w = window.WindowWatch()
    temps = [21.0, 21.0, 20.9, 20.8, 20.8, 20.8, 20.9, 21.0, 21.0, 21.0]
    contact = [False, True, True, True, False, False, False, False, False, False]
    ev = run(w, temps, contact=contact)
    assert ev == [("open", 2), ("end", 8)], ev                      # open by the sensor; closed, the room is back


def test_an_episode_never_lasts_for_ever():
    w = window.WindowWatch()
    ev = run(w, [21.0] * 3 + [20.0] * 120, contact=[False] * 3 + [True] * 120)
    assert ev == [("open", 6), ("end", window.MAX_MIN + 6)], ev     # a sensor stuck open does not start it again


if __name__ == "__main__":
    run_all(dict(globals()))
