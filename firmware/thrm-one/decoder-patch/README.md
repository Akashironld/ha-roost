# OpenTherm edge-timestamp decoder for ESPHome (patch against ESPHome 2026.10.1)

Patch: `esphome-2026.10.1-opentherm-edge-decoder.patch` (against `esphome/components/opentherm` of 2026.10.1).
Apply it to a copy of that component and load it as an external component:

```yaml
external_components:
  - source: {type: local, path: components}
    components: [opentherm]

opentherm:
  in_pin: GPIO6
  out_pin: GPIO7
  edge_decoder: true   # decode responses from edge timestamps instead of 5 kHz sampling
  rmt_capture: true    # ESP32: let the RMT peripheral record the response (needs edge_decoder)
  edge_stats: false    # true: log pulse-width statistics every minute (tag "otedge") + edge list of rejected frames
```

All three options default to `false`, so without them the component behaves exactly like stock ESPHome.

## What it does
- **edge_decoder**: after a response has been received (36 ms after the start edge), it is decoded from the edge
  timestamps. For every bit the mandatory mid-bit transition is searched within ±330 µs of where it is expected,
  and the edge found becomes the reference for the next bit (re-sync per bit). Pulses < 100 µs are dropped as
  glitches. Start bit and stop bit must be 1; parity is checked by the hub as before.
- **rmt_capture**: an RMT RX channel on the input pin (1 MHz, 48 symbols, 2 ms idle threshold) records the
  response in hardware, so interrupt latency (Wi-Fi on a single-core C6, flash writes) cannot drop edges.
  Without it, a GPIO edge interrupt with `esp_timer_get_time()` timestamps is used.
- **edge_stats**: pulse-width statistics (min/avg/max and 50 µs histograms for high/low, short/long pulses).
- Single protocol errors and timeouts are logged at DEBUG instead of WARN and counted (`get_error_count()` on the
  hub); the config can turn that into an error-rate sensor and warn above a threshold.

## Measurements (THRM ONE v0.2 + Weheat Blackbird P80, 19–20 Nov 2026)

| Pulse | Nominal | Measured min / avg / max (RMT, 1 µs) |
|---|---|---|
| high, half bit | 500 µs | 599 / 600 / 602 µs |
| low, half bit | 500 µs | 399 / 399 / 400 µs |
| high, full bit | 1000 µs | 1100 / 1100 / 1101 µs |
| low, full bit | 1000 µs | 899 / 899 / 900 µs |

| Variant | Responses | Rejected |
|---|---|---|
| stock decoder (also with sync_mode) | ~250/min | 2.5–4 % |
| edge decoder, GPIO interrupt timestamps | 7,561 | 0.50 % |
| edge decoder + RMT capture | 2,514 | 0.40 % |
| edge decoder + RMT capture, re-terminated wires, no sync_mode | 10 min | 0.57 % |

The remaining rejections are responses that break off mid-frame with the line staying in the "high" state for
> 2 ms (random bit positions), plus occasional missing responses – visible in the RMT capture as well, so they do
not originate in the decoder.

## Why the stock decoder trips
It samples every 200 µs and counts ≥ 4 equal samples as a full bit. A 600 µs half bit is exactly 3 samples, so a
few µs of jitter decides between 3 and 4 samples; 4 is read as a full bit and the expected mid-bit transition is
then "missing" (NO_TRANSITION). The receive path is the common Ihor Melnyk design (bridge + PC817 + 1.5 kΩ
pull-up); PC817 switching with a kΩ load is slow and asymmetric, which fits a constant ~100 µs skew. How large the
skew is likely depends on the boiler's current levels and the opto's CTR, which may be why many boards never hit it.
