"""Extra rooms: kinds and hours, the room model, too cold, and the planner keeping their minimums."""
import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

rooms = load("rooms")
model = load("model")
heatpump = load("heatpump")
planner = load("planner")


def test_kinds_and_hours():
    bed = rooms.Room("a", "Slaapkamer", "sensor.x", "bedroom")
    assert bed.settings(7, 22) == (16.0, 19, 23)
    other = rooms.Room("b", "Zolder", "sensor.y", "other", minimum=15.0)
    assert other.settings(7, 22) == (15.0, 7, 22)                       # the house's comfort hours
    assert rooms.active(20, 19, 23) and not rooms.active(23, 19, 23)
    assert rooms.active(23, 22, 7) and rooms.active(3, 22, 7) and not rooms.active(12, 22, 7)   # through midnight
    assert not rooms.active(-1, 0, 24)


def test_room_model_learned():
    true = rooms.RoomModel(b0=0.0, b_heat=0.12, b_out=0.03, b_main=0.08)
    rnd = random.Random(2)
    T, samples = 18.0, []
    for h in range(200):
        q = max(0.0, 2.5 + 2 * math.sin(h / 5))
        t_out, t_main = 5 + 3 * math.sin(h / 24 * 2 * math.pi), 20.5 + 0.5 * math.sin(h / 7)
        T1 = true.step(T, q, t_out, t_main) + rnd.gauss(0, 0.01)
        samples.append((T, T1, q, t_out, t_main))
        T = T1
    m = rooms.learn(samples)
    assert m and abs(m.b_heat - 0.12) < 0.03 and abs(m.b_out - 0.03) < 0.015 and abs(m.b_main - 0.08) < 0.04, m
    assert rooms.learn(samples[:50]) is None


def test_too_cold_needs_a_pattern():
    day = lambda d, n: [(d, True, 15.0, 16.0)] * n + [(d, True, 17.0, 16.0)] * (5 - n)
    assert rooms.too_cold(day("1", 3) + day("2", 4) + day("3", 0))
    assert not rooms.too_cold(day("1", 3) + day("2", 1) + day("3", 0))
    assert not rooms.too_cold([("1", False, 12.0, 16.0)] * 10 + [("2", False, 12.0, 16.0)] * 10)   # outside its hours


def test_planner_keeps_a_cold_room_warm_enough():
    house = model.HouseModel(C=19.0, H=0.125, g=5.5, lag=1.0, internal=0.0, Hw=0.007, source="learned")
    hp = heatpump.HeatPumpModel()
    hp.a, hp.k, hp.offset, hp.follow = 0.9, 1.0, 0.3, 0.35
    s = planner.Settings(comfort=20.5, day_min=20.0, night_min=19.0, store_max=22.5, sp_min=17.0)
    hours = []
    for i in range(36):
        hr = (13 + i) % 24
        price = 0.45 if 17 <= hr < 22 else 0.25
        hours.append(planner.HourIn(t_out=0.0, wind=4, rad=0.0, p_grid=price, p_own=price, day=7 <= hr < 22, hour=hr))
    bedroom = rooms.RoomModel(b0=0.0, b_heat=0.15, b_out=0.02, b_main=0.03)      # cools fast, lives on the heat pump
    act = [rooms.active(h.hour, 17, 23) for h in hours]
    room = {"model": bedroom, "T": 18.5, "min": 18.0, "active": act}
    without = planner.plan(house, hp, s, hours, 21.0, 2.0, 20.0, w_now=2.0)
    with_room = planner.plan(house, hp, s, hours, 21.0, 2.0, 20.0, w_now=2.0, rooms=[room])
    temps = with_room.rooms[0]
    evening = [t for t, a in zip(temps, act) if a]
    assert min(evening) >= 17.6, temps
    assert sum(x.heat for x in with_room.hours[:10]) > sum(x.heat for x in without.hours[:10]), "more heat for the room"


if __name__ == "__main__":
    run_all(dict(globals()))
