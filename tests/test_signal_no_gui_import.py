"""Guard test: ``mf4_analyzer.signal.fft`` must not depend on GUI libraries.

Per the modular-restructure design spec, the ``signal/`` subpackage is
forbidden from importing ``PyQt5`` or ``matplotlib.pyplot`` (directly or
transitively). This test enforces the rule mechanically.

Mechanism: we spawn a fresh child Python process whose ``sys.modules``
has ``PyQt5`` and ``matplotlib.pyplot`` POISONED with ``None`` BEFORE
``mf4_analyzer.signal.fft`` is imported. Python's import machinery
treats ``None`` in ``sys.modules`` as a cached "this import has been
blocked" marker and raises ``ModuleNotFoundError`` on any subsequent
``import PyQt5`` (or ``import matplotlib.pyplot``) — so if ``signal/fft``
tried to pull in either of those, the child would crash.

A clean exit with ``clean`` on stdout proves the rule holds. The test
also performs a meta-sanity check in the same child process, confirming
that the poisoning idiom *does* block a direct ``import PyQt5`` (so we
know the guard is actually exercised, not silently bypassed).
"""

from __future__ import annotations

import subprocess
import sys
import unittest


CHILD_SCRIPT = r"""
import sys

# Poison the GUI modules BEFORE importing anything from the signal layer.
# `None` in sys.modules causes CPython's import machinery to raise
# ModuleNotFoundError on any subsequent `import PyQt5` / `import matplotlib.pyplot`
# with message "import of <name> halted; None in sys.modules". This is
# the documented way to block a module from being imported.
sys.modules['PyQt5'] = None
sys.modules['matplotlib.pyplot'] = None

# Meta-sanity check: confirm the poisoning idiom actually blocks imports,
# so a false-positive "clean" can't mask a broken guard.
try:
    import PyQt5  # noqa: F401
except ModuleNotFoundError:
    pass
else:
    print('POISON_INEFFECTIVE_PyQt5')
    sys.exit(2)

try:
    import matplotlib.pyplot  # noqa: F401
except ModuleNotFoundError:
    pass
else:
    print('POISON_INEFFECTIVE_matplotlib_pyplot')
    sys.exit(2)

# The actual rule check: importing the signal layer must NOT trigger
# either poisoned import.
import mf4_analyzer.signal.fft  # noqa: F401

# A sanity smoke: the class must exist and be callable.
from mf4_analyzer.signal.fft import FFTAnalyzer
assert hasattr(FFTAnalyzer, 'compute_fft'), 'FFTAnalyzer.compute_fft missing'

print('clean')
"""


class SignalLayerIsGuiFreeTests(unittest.TestCase):
    def test_signal_fft_imports_without_pyqt5_or_matplotlib_pyplot(self):
        """Importing mf4_analyzer.signal.fft must not pull in PyQt5 or
        matplotlib.pyplot. We poison those in a child process's sys.modules
        and check the import still succeeds cleanly.
        """
        result = subprocess.run(
            [sys.executable, "-c", CHILD_SCRIPT],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=(
                "Child process exited non-zero: returncode="
                f"{result.returncode}\nstdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            ),
        )
        self.assertIn(
            "clean",
            result.stdout,
            msg=(
                "Expected 'clean' marker in child stdout.\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            ),
        )
        self.assertNotIn(
            "POISON_INEFFECTIVE",
            result.stdout,
            msg=(
                "Poisoning idiom did not block the module it was supposed "
                "to block; the guard test is not actually exercising the "
                f"rule.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
