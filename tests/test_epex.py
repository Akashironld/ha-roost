"""Built-in day-ahead prices: Energy-Charts' payload, the formula, when to ask again."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

epex = load("epex")
series = load("series")

T0 = 1_800_000_000 - 1_800_000_000 % 3600


def test_energy_charts_payload_per_quarter():
    payload = {"unix_seconds": [T0 + q * 900 for q in range(8)], "price": [200.0, 220.0, 240.0, 260.0, 100.0, None, 100.0, 100.0],
               "unit": "EUR / MWh"}
    slots = epex.parse(payload)
    assert len(slots) == 7 and slots[0] == (T0, T0 + 900, 0.2)              # per MWh -> per kWh
    hour = series.hourly(slots, T0, 2)
    assert abs(hour[0] - 0.23) < 1e-9 and abs(hour[1] - 0.1) < 1e-9          # the hour's average; a missing quarter skipped


def test_formula_and_zone():
    assert abs(epex.formula(0.10, 1.21, 0.15) - 0.271) < 1e-12               # (EPEX + fee + tax) × VAT
    assert epex.formula(0.10, 1.0, -0.02) == 0.08                            # export with a fee
    assert epex.zone_for("NL") == "NL" and epex.zone_for("de") == "DE-LU" and epex.zone_for(None) == "NL"


def test_asks_sparingly():
    slots_today = [(T0, T0 + 3600, 0.2)]
    end_tomorrow = T0 + 30 * 3600
    assert epex.needs_refresh([], None, T0, 10, end_tomorrow)                   # never asked
    assert not epex.needs_refresh(slots_today, T0, T0 + 600, 10, end_tomorrow)  # asked 10 minutes ago
    assert epex.needs_refresh(slots_today, T0, T0 + 3600, 10, end_tomorrow)     # an hour ago
    assert epex.needs_refresh(slots_today, T0, T0 + 900, 14, end_tomorrow)      # afternoon, tomorrow missing: every 15 min
    full = slots_today + [(end_tomorrow - 3600, end_tomorrow, 0.2)]
    assert not epex.needs_refresh(full, T0, T0 + 900, 14, end_tomorrow)         # tomorrow is there
    assert not epex.needs_refresh([], T0, T0 + 300, 14, end_tomorrow)          # a failed try: not again within 15 min


if __name__ == "__main__":
    run_all(dict(globals()))
