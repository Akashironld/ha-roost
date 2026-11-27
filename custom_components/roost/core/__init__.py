"""Roost's functional core: the arithmetic of the runtime, without Home Assistant.

Each module here has a small state bundle (a dataclass) and pure functions: they get the bundle and what was read
(meter readings, weather, prices, the time) and give a new bundle back, plus what happened (events, numbers for the
card). They never read or write Home Assistant, never mutate what they were given, and never import `homeassistant`
(tests/test_core.py checks that). The shell (manager.py and the modules it holds) reads the sensors, calls these
functions, writes the thermostat or the OpenTherm master and stores the bundles.
"""
