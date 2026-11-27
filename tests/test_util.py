"""The shared helpers: a finite number, stored values back into an object, a small linear solve."""
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

util = load("util")


def test_num_takes_finite_numbers_only():
    assert util.num("21.5") == 21.5 and util.num(3) == 3.0
    for bad in (None, "unavailable", "abc", float("nan"), float("inf"), "-inf"):
        assert util.num(bad) is None


@dataclass
class _Thing:
    a: float = 1.0
    b: str = "x"

    @property
    def twice(self) -> float:
        return 2 * self.a


def test_fill_keeps_known_fields_and_skips_properties():
    t = util.fill(_Thing(), {"a": 5.0, "unknown": 1, "twice": 99})
    assert t.a == 5.0 and t.b == "x" and t.twice == 10.0
    assert util.fill(_Thing(), None) == _Thing()


def test_solve():
    x = util.solve([[2.0, 1.0], [1.0, 3.0]], [3.0, 5.0])
    assert abs(x[0] - 0.8) < 1e-9 and abs(x[1] - 1.4) < 1e-9
    assert util.solve([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0]) is None


if __name__ == "__main__":
    run_all(globals())
