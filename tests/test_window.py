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


def test_a_thermostat_in_half_degrees_is_not_a_window_when_it_rounds():
    """Only the thermostat as room temperature (a Lyric T6 shows 0.5 °C steps): a room cooling a tenth past 20.75
    shows 21 → 20.5 at once, and near that point it flips back and forth. Seen 22-10-2026 in the author's house: a
    window three times in one night with everything closed. A real airing drops it two steps (1 °C)."""
    w = window.WindowWatch()
    temps = [21.0] * 5 + [20.5, 21.0, 20.5] + [20.5] * 20 + [20.0] * 10
    assert run(w, temps) == [] and not w.hours
    assert window.reading_step([21.0, 21.0, 20.5, 21.0]) == 0.5 and window.reading_step([20.4, 20.3, 20.3]) == 0.1
    assert window.reading_step([20.0, 20.0]) == 0.0
    w = window.WindowWatch()
    ev = run(w, [21.0, 20.5, 21.0, 21.0, 20.5, 20.0, 20.0] + [20.0] * 10 + [20.5, 21.0])
    assert ev[0] == ("open", 10) and ev[-1][0] == "end", ev       # 1 °C within 15 minutes: airing


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
