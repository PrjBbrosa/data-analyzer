"""Guard: a directory conftest keeps its fixtures when arguments re-enter it.

pytest 9.1.1 re-collects an argument's parent directory whenever the argument
names a file, which mints a second collector node for every sub-directory
underneath it. Fixture lookup is keyed by node identity, so tests collected
under the duplicate node lose their directory conftest's fixtures — silently,
with no warning. See the repo-root ``conftest.py`` for the full write-up and
the repair.

The failure this protects against is invisible in a normal run: the affected
tests do not error, they just execute without their fixtures. In this repo
that meant ``tests/ui/conftest.py``'s ``_isolate_qsettings`` stopped applying
and ``tests/ui/test_inspector.py`` started reading (and writing) the
developer's real ``MF4Analyzer/DataAnalyzer`` preference store.

This exercises the mechanism on a throwaway project rather than on the real
suite so it stays fast and does not depend on which files happen to live in
``tests/ui/``. It asserts only the correct behaviour, so it keeps passing —
and the root conftest quietly stops doing anything — once pytest fixes the
underlying bug.
"""

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT_CONFTEST = REPO_ROOT / "conftest.py"


def _write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


def _make_project(root):
    """A project whose sub-directory conftest supplies an autouse fixture."""
    assert ROOT_CONFTEST.is_file(), (
        f"{ROOT_CONFTEST} is missing — it carries the collection repair this "
        f"guard covers."
    )
    _write(root / "pytest.ini", "[pytest]\n")
    shutil.copy(ROOT_CONFTEST, root / "conftest.py")
    _write(
        root / "pkg" / "conftest.py",
        """
        import pytest

        @pytest.fixture(autouse=True)
        def _directory_fixture(request):
            request.node.stash_directory_fixture = True
            yield

        @pytest.fixture
        def requestable():
            return "visible"
        """,
    )
    body = """
        def test_autouse_applied_{tag}(request):
            assert getattr(request.node, "stash_directory_fixture", False), (
                "pkg/conftest.py autouse fixture did not apply"
            )

        def test_named_fixture_visible_{tag}(requestable):
            assert requestable == "visible"
    """
    _write(root / "pkg" / "test_first.py", body.format(tag="first"))
    _write(root / "pkg" / "test_second.py", body.format(tag="second"))
    _write(root / "test_outside.py", "def test_outside():\n    pass\n")


def _run(root, *args):
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=root,
        capture_output=True,
        text=True,
    )


def test_directory_conftest_survives_arguments_leaving_and_re_entering(tmp_path):
    """``pkg/a.py  outside.py  pkg/b.py`` must not strip ``pkg``'s conftest."""
    _make_project(tmp_path)

    completed = _run(
        tmp_path,
        "pkg/test_first.py",
        "test_outside.py",
        "pkg/test_second.py",
    )

    assert completed.returncode == 0, (
        "A directory conftest lost its fixtures when the argument list left "
        "and re-entered its directory.\n"
        f"{completed.stdout}\n{completed.stderr}"
    )
    assert "5 passed" in completed.stdout, completed.stdout


def test_directory_conftest_applies_for_plain_orderings(tmp_path):
    """The repair must not disturb the orderings that already worked."""
    _make_project(tmp_path)

    for args in (
        ("pkg",),
        ("pkg/test_first.py", "pkg/test_second.py"),
        ("pkg/test_first.py", "pkg/test_first.py"),
        (".",),
    ):
        completed = _run(tmp_path, *args)
        assert completed.returncode == 0, (
            f"pytest {' '.join(args)} regressed:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
