# TraceLab runtime diagnostics

TraceLab writes standard Python, unhandled main/worker exception, selected Qt,
and selected low-frequency chart recovery records to a rotating UTF-8 log.
Logging failures never prevent the application from starting.

## Default location

| Platform | Directory |
|---|---|
| Windows | `%LOCALAPPDATA%\TraceLab\logs` (fallback: `%USERPROFILE%\AppData\Local\TraceLab\logs`) |
| macOS | `~/Library/Logs/TraceLab` |
| Linux/other | `${XDG_STATE_HOME:-~/.local/state}/TraceLab/logs` |

The active file is `tracelab.log`. It rotates at 5 MiB and retains five
backups, so the active file plus backups are bounded at approximately 30 MiB.

## Overrides

- `TRACELAB_LOG_DIR` selects another log directory.
- `TRACELAB_LOG_LEVEL` selects the file threshold using a standard logging
  name such as `DEBUG`, `INFO`, `WARNING`, or `ERROR`. The default is `INFO`.

Warnings and errors are also written to stderr when the process has one.
Windows `--windowed` packages normally do not expose stderr, so collect the log
directory above when reporting a startup or chart-recovery problem.

The file keeps `INFO` and above from TraceLab's `mf4_analyzer.*` loggers and
`WARNING` and above from third-party libraries. Repeated chart/Qt failures are
rate-limited: the first records are kept and suppressed counts are summarized
after the time window, before throttle-key eviction, or during an orderly
shutdown.

## Support collection

Reproduce the issue once, close TraceLab, then copy `tracelab.log` and any
numbered backups from the directory. Logs can contain file paths, channel names,
and exception details; review them before sharing outside the project.
