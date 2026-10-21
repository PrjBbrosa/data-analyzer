---
id: expression-functions-reject-numpy-output-arguments
status: active
owners: [codex]
keywords: [expression, numpy, out, validation, channel]
paths: [mf4_analyzer/signal/expression.py]
checks: [verify expression function positional arity before invoking numpy]
tests: [tests/signal/test_expression_check.py]
---

# Expression Functions Must Reject NumPy Output Arguments

Trigger: Adding expression validation, trial evaluation, or functions backed by NumPy.

Past failure: The function-name whitelist forwarded arbitrary positional arguments. `sqrt(A, B)` was accepted as NumPy's `out=B`, so evaluating a formula could overwrite another input buffer.

Rule: Whitelist mathematical argument signatures as well as function names. Reject output-buffer/axis/control parameters that are not part of the expression language before calling NumPy. Validation and creation use the same evaluator; workers receive owned source snapshots.

Verification: `tests/signal/test_expression_check.py::test_numpy_out_argument_is_not_an_expression_feature` rejects the call and proves B remains unchanged. Full-signal and check/create tests preserve the accepted numerical semantics.
