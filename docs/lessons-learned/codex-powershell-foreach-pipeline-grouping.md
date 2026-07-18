---
id: codex-powershell-foreach-pipeline-grouping
status: active
owners: [codex]
keywords: [powershell, foreach, pipeline, convertto-json, parser]
paths: [scripts/**, .codex/**]
checks: [powershell foreach parser smoke]
tests: []
---

# PowerShell Foreach Output Must Be Collected Before Piping

Trigger: Building Windows PowerShell commands that send the output of a
`foreach (...) { ... }` language statement to `ConvertTo-Json`, `Format-Table`,
or another pipeline command.

Past failure: Two diagnostic commands ended with `} | ConvertTo-Json`, which
PowerShell parsed as an empty pipe element. The parser error prevented every
parallel diagnostic result from being returned even though the commands were
otherwise read-only.

Rule: Do not pipe directly from the `foreach` language statement. Collect its
output first, for example `$rows = @(foreach (...) { ... })`, then pipe
`$rows`. When parallel diagnostics are independent, collect tool results with
an all-settled pattern so one parser failure does not discard successful
siblings.

Verification: Run a PowerShell parser smoke using
`$rows = @(foreach ($i in 1..2) { [pscustomobject]@{n=$i} }); $rows |
ConvertTo-Json -Compress` and confirm it exits 0 with two objects.
