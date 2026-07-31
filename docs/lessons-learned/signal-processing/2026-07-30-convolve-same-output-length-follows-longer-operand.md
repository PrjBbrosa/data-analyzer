---
id: signal-processing/2026-07-30-convolve-same-output-length-follows-longer-operand
status: active
owners: [codex]
keywords: [numpy, convolve, moving-average, window, output-shape, ui-parameter]
paths: [mf4_analyzer/signal/channel_math.py]
checks: [output length equals input length]
tests: [tests/signal/test_channel_math.py]
---

# `np.convolve(mode="same")` follows the longer operand's length

Trigger: A UI-controlled filter or smoothing window reaches
`np.convolve(..., mode="same")`, especially when its configured window may be
longer than the selected signal.

Past failure: A moving average with three samples and window 50 returned 50
values. The caller paired that result with the original time axis, violating
the channel-length contract; integer integration also silently truncated
fractional trapezoids.

Rule: Define and test the public shape and dtype contracts before choosing the
NumPy primitive. Clamp or explicitly handle an oversized window so the output
length equals the input length, and allocate numeric accumulators with the
required floating dtype.

Verification: Run `.venv/bin/python -m pytest tests/signal/test_channel_math.py -q`;
cover oversized windows, empty input, integer input, and analytic cases.
