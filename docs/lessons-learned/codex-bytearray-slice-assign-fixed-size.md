---
id: codex-bytearray-slice-assign-fixed-size
status: active
owners: [codex]
keywords: [bytearray, binary, writer, wwt, header, slice]
paths: [mf4_analyzer/io/wwt_writer.py]
checks: []
tests: [tests/test_wwt_writer.py]
---

# Fixed-size bytearray headers must use equal-length slice assigns

Trigger: Packing fixed binary headers with `bytearray(N)` and slice assignment.

Past failure: `head[0:len(magic)] = magic.ljust(15)` with `len(magic)=13`
grew the buffer by 2 bytes, shifting every WWT record so TraceLab saw data
channels before `Zeit`.

Rule: When the buffer size is the contract, assign only equal-length slices
(`head[0:15] = mag[:15].ljust(15, b"\0")`). Never let a longer RHS expand a
shorter LHS slice on a sized `bytearray`.

Verification: `pytest tests/test_wwt_writer.py` — roundtrip loads channels;
spot-check `len(header_bytes) == 0x211` after packing.
