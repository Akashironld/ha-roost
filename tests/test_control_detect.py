"""How the heat pump is controlled, from its answers to steps in the requested water temperature."""
from core import load, run_all

cd = load("control_detect")


def run(tracker, t0, minutes, request, supply, running=True):
    """Feed one reading every 2 minutes; request and supply are functions of the minute."""
    for k in range(0, minutes, 2):
        tracker.update(t0 + k * 60, request(k), supply(k), running)
    return t0 + minutes * 60


def follow_steps(n, gain, t0=1_000_000.0):
    tr = cd.StepTracker()
    t = t0
    for i in range(n):
        lo, hi = 30.0, 32.0
        # 30 min at lo, then a step to hi; the supply moves gain × step towards it over the next 20 minutes
        t = run(tr, t, 30, lambda k: lo, lambda k: lo + 1)
        t = run(tr, t, 30, lambda k: hi, lambda k: lo + 1 + gain * (hi - lo) * min(k, 20) / 20)
    return tr, t


def test_a_unit_that_follows_is_opentherm():
    tr, t = follow_steps(12, 0.9)
    d = cd.detect(tr.steps, t)
    assert d.mode == cd.OPENTHERM and d.steps >= 10 and d.gain > 0.4


def test_a_unit_on_its_curve_does_not_move():
    tr, t = follow_steps(12, 0.0)
    d = cd.detect(tr.steps, t)
    assert d.mode == cd.HEATING_CURVE and d.gain < 0.15


def test_too_few_steps_is_unknown():
    tr, t = follow_steps(4, 0.9)
    assert cd.detect(tr.steps, t).mode == cd.UNKNOWN


def test_in_between_is_unknown():
    tr, t = follow_steps(12, 0.25)
    assert cd.detect(tr.steps, t).mode == cd.UNKNOWN


def test_a_step_right_after_the_start_does_not_count():
    tr = cd.StepTracker()
    t = run(tr, 0.0, 4, lambda k: 30.0, lambda k: 30.0)          # only 4 minutes running
    run(tr, t, 30, lambda k: 32.0, lambda k: 32.0)
    assert tr.steps == []


def test_a_request_that_moves_again_drops_the_step():
    tr = cd.StepTracker()
    t = run(tr, 0.0, 20, lambda k: 30.0, lambda k: 30.0)
    t = run(tr, t, 10, lambda k: 32.0, lambda k: 31.0)           # stepped, but 10 min later ...
    run(tr, t, 30, lambda k: 31.0, lambda k: 31.0)                # ... it moved again
    assert all(abs(s[1]) < 5 for s in tr.steps) and len(tr.steps) <= 1


def test_the_unit_stopping_drops_the_step():
    tr = cd.StepTracker()
    t = run(tr, 0.0, 20, lambda k: 30.0, lambda k: 30.0)
    t = run(tr, t, 6, lambda k: 32.0, lambda k: 30.5)
    run(tr, t, 30, lambda k: 32.0, lambda k: 25.0, running=False)
    assert tr.steps == []


def test_a_restart_or_reset_is_not_a_step():
    tr = cd.StepTracker()
    t = run(tr, 0.0, 20, lambda k: 10.0, lambda k: 30.0)          # thermostat sends 10 (idle value)
    run(tr, t, 30, lambda k: 30.0, lambda k: 30.0)                # jump of 20 °C
    assert tr.steps == []


def test_old_steps_fall_out_of_the_window():
    tr, t = follow_steps(12, 0.9)
    assert cd.detect(tr.steps, t + 8 * 86400).mode == cd.UNKNOWN


def test_round_trip_through_storage():
    tr, t = follow_steps(3, 0.5)
    again = cd.StepTracker.from_dict(tr.as_dict())
    assert again.steps == tr.steps
    assert cd.StepTracker.from_dict(None).steps == []
    assert cd.StepTracker.from_dict({"steps": [[1, 2, 3], "x"]}).steps == []


def test_mismatch():
    assert cd.mismatch(cd.HEATING_CURVE, cd.OPENTHERM)
    assert cd.mismatch(cd.OPENTHERM, cd.HEATING_CURVE)
    assert not cd.mismatch(cd.OPENTHERM, cd.OPENTHERM)
    for unchecked in (cd.OPENTHERM_SMART, "on_off", "cloud_thermostat", None):   # no expected answer: never a mismatch
        assert not cd.mismatch(unchecked, cd.HEATING_CURVE) and not cd.mismatch(unchecked, cd.OPENTHERM)
    assert not cd.mismatch(cd.HEATING_CURVE, cd.UNKNOWN)


def test_method_names_as_the_unit_reports_them():
    assert cd.method_name(1) == cd.HEATING_CURVE and cd.method_name("3") == cd.OPENTHERM
    assert cd.method_name(4) == cd.OPENTHERM_SMART and cd.method_name(5) == "cloud_thermostat"
    assert cd.method_name(99) is None and cd.method_name(None) is None


def test_a_reading_missing_for_a_tick_keeps_the_step():
    tr = cd.StepTracker()
    t = run(tr, 0.0, 20, lambda k: 30.0, lambda k: 30.0)
    t = run(tr, t, 10, lambda k: 32.0, lambda k: 30.0 + 0.1 * k)
    tr.update(t, None, None, True)                               # the cloud skipped one reading
    run(tr, t + 120, 14, lambda k: 32.0, lambda k: 31.8)
    assert len(tr.steps) == 1 and tr.steps[0][1] > 0.8


def test_old_steps_are_pruned_while_the_unit_stands_still():
    tr, t = follow_steps(3, 0.5)
    tr.update(t + 8 * 86400, None, None, False)
    assert tr.steps == []


if __name__ == "__main__":
    run_all(globals())
