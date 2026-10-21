"""Weheat's hourly history kept by Roost (history.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

history = load("history")


def test_a_gas_boiler_that_ran_makes_a_hybrid():
    """#5: a hybrid heat pump is told apart by the hours its gas boiler ran (Weheat's hourly logs)."""
    hours = {t: {"q": 1.0} for t in range(100)}
    assert history.boiler_hours(hours) == 0
    hours.update({1: {"boiler_s": 1200}, 2: {"boiler_s": 900}, 3: {"boiler_s": 60}, 4: {"boiler_s": 3600}})
    assert history.boiler_hours(hours) == 3 >= history.HYBRID_HOURS          # 60 s is not running


if __name__ == "__main__":
    run_all(dict(globals()))
