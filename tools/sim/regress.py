"""The closed-loop simulation as a regression check: a fixed set of scenarios and seeds (thermostat steering, OpenTherm
steering and the steady thermostat), compared with tools/sim/baseline.json. A change fails when a scenario gets more
than COST_PCT more expensive or more than COMFORT_K °C·h further below comfort, for either way of steering.

    python3 tools/sim/regress.py            compare (exit code 1 when worse)
    python3 tools/sim/regress.py --update   write the baseline (after a change that was meant to change the results)
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(HERE, "baseline.json")
SET = [("home", 1), ("home", 2), ("radiators", 1), ("cold", 1), ("spring", 1), ("volatile", 1), ("fixed", 1)]
DAYS = 3
COST_PCT, COMFORT_K = 1.0, 0.2


def one(job):
    name, seed = job
    os.environ["SIM_OT"] = "1"
    sys.path.insert(0, HERE)
    import sim
    r = sim.run(name, DAYS, seed)
    return f"{name}/{seed}", {k: {"cost": round(r[k]["cost_level"], 3), "short": round(r[k]["deg_below"], 2),
                                   "below_min": r[k]["hours_below_min"], "starts": r[k]["starts"]}
                              for k in ("roost", "ot", "steady")}


def main() -> int:
    with ProcessPoolExecutor(max_workers=len(SET), mp_context=mp.get_context("fork")) as ex:
        now = dict(ex.map(one, SET))
    if "--update" in sys.argv:
        json.dump(now, open(BASELINE, "w"), indent=1, sort_keys=True)
        print(f"baseline written: {len(now)} runs")
        return 0
    base = json.load(open(BASELINE))
    bad = []
    for key, res in sorted(now.items()):
        for way in ("roost", "ot"):
            b, n = base[key][way], res[way]
            dc = (n["cost"] - b["cost"]) / b["cost"] * 100 if b["cost"] else 0.0
            ds = n["short"] - b["short"]
            flag = dc > COST_PCT or ds > COMFORT_K or n["below_min"] > b["below_min"]
            print(f"{key:12} {way:5} cost {n['cost']:7.2f} ({dc:+5.1f} %)  short {n['short']:5.2f} ({ds:+.2f})  "
                  f"below min {n['below_min']}  starts {n['starts']}{'  WORSE' if flag else ''}")
            bad += [key + "/" + way] if flag else []
    print("OK: nothing worse than the baseline" if not bad else f"WORSE: {', '.join(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
