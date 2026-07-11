# Vector/XCP evidence template

One directory per bench run. Retain JSON and literal errors before changing settings.

```text
date/operator:
branch/commit:
Python bitness/application version:
python-can/pyxcp versions:
Vector model/serial/driver/application slot/channel:
CAN mode/arbitration/data bitrate:
ECU side/A2L path/A2L SHA-256/command-response IDs:
harness/termination/power state:
DAQ protection/provider identity (no secret):
selected events/signals:
```

| Gate | Source | Packaged | First DTO | MF4 reopen | Drops/errors | Result |
| --- | --- | --- | --- | --- | --- | --- |
| declared classic-CAN configuration | link | link | link | link | counters | PASS/PARTIAL/BLOCKED |
| CAN-FD | NOT TESTED or link | NOT TESTED or link | ... | ... | ... | ... |
| additional VN model | NOT TESTED or link | NOT TESTED or link | ... | ... | ... | ... |
