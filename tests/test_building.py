"""Building register (BAG): outside walls, starting values, facade directions."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from core import load, run_all  # noqa: E402

building = load("building")
model = load("model")

LAT, LON = 52.0, 5.0
M_LAT = 1 / 111_320
M_LON = 1 / (111_320 * math.cos(math.radians(LAT)))


def box(x0, y0, w, d):
    """A rectangle w m east-west, d m north-south, its south-west corner x0 m east and y0 m north of the home point."""
    pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + d), (x0, y0 + d), (x0, y0)]
    return {"type": "Polygon", "coordinates": [[[LON + x * M_LON, LAT + y * M_LAT] for x, y in pts]]}


def terrace():
    """Three terraced houses in a row east-west; ours in the middle: front south, back north, neighbours east and west."""
    pand = {"features": [
        {"properties": {"identificatie": "W", "bouwjaar": 1978}, "geometry": box(-8.0, -5.0, 6.0, 10.0)},
        {"properties": {"identificatie": "OURS", "bouwjaar": 1978}, "geometry": box(-2.0, -5.0, 6.0, 10.0)},
        {"properties": {"identificatie": "E", "bouwjaar": 1978}, "geometry": box(4.0, -5.0, 6.0, 10.0)},
    ]}
    vbo = {"features": [
        {"properties": {"gebruiksdoel": "woonfunctie", "oppervlakte": 120, "bouwjaar": 1978, "pandidentificatie": "W"},
         "geometry": {"type": "Point", "coordinates": [LON - 5 * M_LON, LAT]}},
        {"properties": {"gebruiksdoel": "woonfunctie", "oppervlakte": 120, "bouwjaar": 1978, "pandidentificatie": "OURS"},
         "geometry": {"type": "Point", "coordinates": [LON + 1 * M_LON, LAT]}},
        {"properties": {"gebruiksdoel": "winkelfunctie", "oppervlakte": 300, "pandidentificatie": "E"},
         "geometry": {"type": "Point", "coordinates": [LON, LAT]}},
    ]}
    return pand, vbo


def test_terraced_house_has_only_front_and_back():
    b = building.parse(*terrace(), LAT, LON)
    assert b["year"] == 1978 and b["area_m2"] == 120
    dirs = sorted(round(az) for az, _m in b["walls"])
    assert dirs == [0, 180], b["walls"]                       # north and south; east and west are shared
    assert building.facades(b, model.FACADES) == (135.0, 180.0, 225.0)   # around the south front; east/west are shared
    corner = {"year": 1976, "area_m2": 152, "walls": [(180.0, 9.1), (0.0, 9.1), (90.0, 4.9), (270.0, 1.0)]}
    assert building.facades(corner, model.FACADES) == (90.0, 135.0, 180.0, 225.0)   # west: 1 m, too little


def test_starting_values_from_age_and_area():
    p = building.prior({"year": 1978, "area_m2": 120, "walls": []})
    assert p == {"H": round(120 * 1.7 / 1000, 3), "C": round(120 * 0.13, 1)}
    assert building.prior({"year": None, "area_m2": 120}) is None
    assert building.prior(None) is None and building.facades(None, model.FACADES) is None


def test_far_pin_and_flats():
    pand, vbo = terrace()
    far = building.parse(pand, vbo, LAT + 60 * M_LAT, LON)          # pin 60 m off: not trusted
    assert far is None
    pand["features"][1]["properties"]["aantal_verblijfsobjecten"] = 12   # a block of flats
    flat = building.parse(pand, vbo, LAT, LON)
    assert flat["area_m2"] == 120 and flat["walls"] == [] and building.facades(flat, model.FACADES) is None


def test_no_dwelling_nearby():
    pand, vbo = terrace()
    vbo["features"] = [f for f in vbo["features"] if f["properties"]["gebruiksdoel"] != "woonfunctie"]
    assert building.parse(pand, vbo, LAT, LON) is None


if __name__ == "__main__":
    run_all(dict(globals()))
