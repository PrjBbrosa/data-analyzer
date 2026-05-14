import subprocess
import sys


def _patched_subprocess_call(exit_codes, calls):
    """Return a callable that records calls and yields exit codes in order."""
    iterator = iter(exit_codes)

    def fake_call(cmd, *args, **kwargs):
        calls.append((cmd, args, kwargs))
        try:
            return next(iterator)
        except StopIteration:
            return 0

    return fake_call


def _pytest_targets(cmd):
    assert cmd[1:3] == ["-m", "pytest"]
    assert cmd[-1] == "-v"
    return cmd[3:-1]


def test_smoke_runner_skip_regression_returns_zero(monkeypatch):
    from scripts import acquisition_smoke

    calls = []
    monkeypatch.setattr(subprocess, "call", _patched_subprocess_call([0], calls))
    monkeypatch.setattr(sys, "argv", ["acquisition_smoke.py", "--skip-regression"])

    rc = acquisition_smoke.main()

    assert rc == 0
    assert len(calls) == 1
    assert _pytest_targets(calls[0][0]) == [
        "tests/test_acquisition_manifest.py",
        "tests/test_acquisition_preflight.py",
        "tests/test_acquisition_regression.py",
        "tests/test_acquisition_signals.py",
        "tests/test_acquisition_smoke.py",
        "tests/synthetic",
    ]


def test_smoke_runner_returns_one_on_pytest_failure(monkeypatch):
    from scripts import acquisition_smoke

    calls = []
    monkeypatch.setattr(subprocess, "call", _patched_subprocess_call([3], calls))
    monkeypatch.setattr(sys, "argv", ["acquisition_smoke.py", "--skip-regression"])

    rc = acquisition_smoke.main()

    assert rc == 1
    assert len(calls) == 1


def test_smoke_runner_skips_manifest_absent_with_zero_exit(
    monkeypatch, tmp_path, capsys
):
    from scripts import acquisition_smoke

    calls = []
    monkeypatch.setattr(subprocess, "call", _patched_subprocess_call([0], calls))
    absent = tmp_path / "absent.json"
    monkeypatch.setattr(
        sys, "argv", ["acquisition_smoke.py", "--manifest", str(absent)]
    )

    rc = acquisition_smoke.main()
    captured = capsys.readouterr()

    assert rc == 0
    assert len(calls) == 1
    assert "not found" in captured.out
