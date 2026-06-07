import subprocess
import sys


def test_a2l_probe_dataclasses_import_without_pya2l():
    code = r"""
import importlib.abc
import sys


class BlockPya2l(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "pya2l" or fullname.startswith("pya2l."):
            raise ImportError("blocked pya2l")
        return None


sys.meta_path.insert(0, BlockPya2l())
from can_logger.p0.a2l_probe import A2LSummary, MeasurementSummary

print(A2LSummary.__name__, MeasurementSummary.__name__)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "A2LSummary MeasurementSummary" in result.stdout
