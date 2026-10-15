"""Looking back: a day in numbers from the hourly log."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

lookback = load("lookback")


def test_day_stats():
    hours = []
    for h in range(24):
        hours.append({"ts": h * 3600, "T": 20.0 if h == 8 else 20.6, "day": 7 <= h < 22, "e": 0.5, "q": 2.0, "cost": 0.15,
                      "sp_t": 21.0 if 2 <= h < 5 else 20.0, "p6": 20.6 if h != 13 else 21.4})
    d = lookback.day_stats(hours, 20.5, by_hand=1, cost_replay=3.6, steady_replay=3.9)
    assert d["kwh"] == 12.0 and d["heat_kwh"] == 48.0 and d["cop"] == 4.0 and d["cost"] == 3.6
    assert d["below_min"] == 60 and d["deficit_ch"] == 0.5 and d["low"] == 20.0      # 08:00 at 20.0
    assert d["changes"] == 2 and d["by_hand"] == 1                                    # 02:00 up, 05:00 down
    assert d["pred_hours"] == 24 and abs(d["pred_max"] - (-0.8)) < 1e-9               # 13:00: 0.8 colder than predicted
    assert abs(d["saving"] - 0.3) < 1e-9


def test_day_stats_empty_fields():
    d = lookback.day_stats([{"ts": 0, "T": 21.0}], 20.5)
    assert d["kwh"] == 0 and d["cop"] is None and d["pred_mae"] is None and "saving" not in d


if __name__ == "__main__":
    run_all(dict(globals()))
