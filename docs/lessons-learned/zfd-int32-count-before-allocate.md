---
id: zfd-int32-count-before-allocate
status: active
owners: [codex]
keywords: [zfd, int32, uint16, count, long-record, marker-scan]
paths: [mf4_analyzer/io/zfd_format.py, tests/zfd_fixtures.py]
checks: [rg -n "struct.unpack\\('<H'" mf4_analyzer/io/zfd_format.py, rg -n "matlab_ports" mf4_analyzer/io/zfd_format.py]
tests: [tests/test_zfd_format.py]
---

# Binary count fields keep official width and remaining-byte bounds

Trigger: Reading a binary measurement format whose records declare a sample count, especially ZFD / ZFGE2 or any format that also has a historical marker-scan parser.

Past failure: Product `_try_channel` unpacked the ordinary-channel count as little-endian uint16 (`<H`). Official ZFGE2 uses signed int32. A 3,608,000-point / 1 kHz record therefore decoded as `3608000 % 65536 = 3520` points (3.519 s). Truncating the last channel still succeeded because the scanner skipped the damaged candidate as a false marker.

Rule: Use the official signed field width for count. Validate `count > 0` and `count * itemsize <= remaining` before allocating. Parse declared records in order; do not keep a guess-the-marker scan on the success path, and do not import a research port into the product.

Verification: `tests/test_zfd_format.py` A1/A2/A3 (65536+ and 3,608,000 points; truncated last channel fails closed). `rg` shows no `<H` count unpack and no `matlab_ports` import in `mf4_analyzer/io/zfd_format.py`.
