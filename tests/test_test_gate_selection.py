"""Resolver tests for scripts/select_test_gate.py.

Synthetic add/delete/rename/shared-fixture/unknown/cross-module cases run in a
throwaway project. A few checks pin the real route map to files that exist.
These tests never launch the repository full suite.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.select_test_gate import (
    FileChange,
    discover_changes_from_git,
    format_ledger,
    load_routes,
    select_gate,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_ROUTES = REPO_ROOT / "scripts" / "test_gate_routes.json"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _mini_routes() -> dict:
    return {
        "schema_version": 1,
        "policy": {"never_claim_full_coverage_from_focused": True},
        "acceptance_sets": {
            "focused": {
                "when": "daily",
                "command": "{python} -m pytest {nodes} -q",
                "result_scope": "PASS applies only to selected nodes.",
            },
            "full_integration": {
                "when": "milestone",
                "commands": [
                    "{python} -m pytest --ignore=tests/acquisition_ui",
                    "{python} -m pytest tests/acquisition_ui",
                ],
                "result_scope": "default non-slow integration only",
            },
            "slow": {"when": "perf", "command": "{python} -m pytest -m slow -o addopts="},
            "real_file": {
                "when": "samples",
                "command": "{python} -m pytest tests/integration/test_real.py -q",
            },
        },
        "infra": {
            "pytest_config": ["pytest.ini", "conftest.py"],
            "conftest": ["conftest.py", "tests/conftest.py"],
            "shared_helpers": ["tests/conftest.py"],
            "required_nodes": ["tests/test_conftest_autouse_scope.py"],
            "infra_regressions": [
                "tests/test_conftest_autouse_scope.py",
                "tests/test_qsettings_isolation.py",
            ],
            "requires_stable_integration_gate": True,
        },
        "selector": {
            "id": "selector",
            "source_paths": [
                "scripts/select_test_gate.py",
                "scripts/test_gate_routes.json",
            ],
            "owner_tests": ["tests/test_test_gate_selection.py"],
            "boundary_tests": [],
        },
        "owners": [
            {
                "id": "signal",
                "label": "signal/filter/spectrogram",
                "source_paths": ["mf4_analyzer/signal/"],
                "owner_tests": ["tests/test_filters.py"],
                "boundary_tests": ["tests/test_signal_no_gui_import.py"],
                "suggested_extra_gates": [],
            },
            {
                "id": "io",
                "label": "IO/real-file",
                "source_paths": ["mf4_analyzer/io/"],
                "owner_tests": ["tests/test_head_hdf.py"],
                "boundary_tests": [],
                "suggested_extra_gates": ["real_file"],
            },
        ],
    }


def _mini_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "gate-repo"
    repo.mkdir(parents=True)
    _write(repo / "pytest.ini", "[pytest]\n")
    _write(repo / "conftest.py", "# collector identity repair stub\n")
    _write(repo / "scripts" / "select_test_gate.py", "print('selector')\n")
    _write(
        repo / "scripts" / "test_gate_routes.json",
        json.dumps(_mini_routes(), indent=2) + "\n",
    )
    _write(repo / "mf4_analyzer" / "signal" / "filters.py", "def lowpass(x):\n    return x\n")
    _write(repo / "mf4_analyzer" / "io" / "head_hdf.py", "def load(path):\n    return path\n")
    _write(repo / "tests" / "__init__.py", "")
    _write(repo / "tests" / "conftest.py", "import pytest\n")
    for name in (
        "test_filters.py",
        "test_signal_no_gui_import.py",
        "test_head_hdf.py",
        "test_conftest_autouse_scope.py",
        "test_qsettings_isolation.py",
        "test_test_gate_selection.py",
    ):
        _write(repo / "tests" / name, "def test_ok():\n    assert True\n")
    _write(
        repo / "tests" / "ui" / "test_helper.py",
        "def harness():\n    return 1\n\ndef test_helper_self():\n    assert harness() == 1\n",
    )
    _write(
        repo / "tests" / "ui" / "test_mid.py",
        "from tests.ui.test_helper import harness\n"
        "def mid():\n    return harness() + 1\n"
        "def test_mid():\n    assert mid() == 2\n",
    )
    _write(
        repo / "tests" / "ui" / "test_leaf.py",
        "from tests.ui.test_mid import mid\n"
        "def test_leaf():\n    assert mid() == 2\n",
    )
    _write(repo / "tests" / "ui" / "__init__.py", "")
    return repo


def _select(repo: Path, changes: list[FileChange], **kwargs):
    return select_gate(
        changes,
        repo_root=repo,
        routes=_mini_routes(),
        include_event_summary=False,
        python=sys.executable,
        **kwargs,
    )


def test_add_source_selects_owner_and_boundary(tmp_path):
    repo = _mini_repo(tmp_path)
    _write(repo / "mf4_analyzer" / "signal" / "spectrogram.py", "def compute():\n    return 0\n")
    report = _select(repo, [FileChange("mf4_analyzer/signal/spectrogram.py", "add")])
    assert report.selected == [
        "tests/test_filters.py",
        "tests/test_signal_no_gui_import.py",
    ]
    assert {reason.via for reason in report.reasons["tests/test_filters.py"]} == {"owner"}
    assert {reason.via for reason in report.reasons["tests/test_signal_no_gui_import.py"]} == {
        "boundary"
    }
    assert report.unmapped == []
    assert report.coverage_claim == "focused-mapped"
    assert report.claims_full_coverage is False
    assert "fully covered" not in format_ledger(report).lower()
    assert "focused PASS is not full PASS" in format_ledger(report)


def test_delete_product_still_selects_owner_tests(tmp_path):
    repo = _mini_repo(tmp_path)
    (repo / "mf4_analyzer" / "io" / "head_hdf.py").unlink()
    report = _select(repo, [FileChange("mf4_analyzer/io/head_hdf.py", "delete")])
    assert "tests/test_head_hdf.py" in report.selected
    extra_ids = {gate["id"] for gate in report.suggested_extra_gates}
    assert "real_file" in extra_ids
    assert "tests/test_head_hdf.py" not in report.missing_selected


def test_delete_test_file_is_not_a_pytest_node(tmp_path):
    repo = _mini_repo(tmp_path)
    (repo / "tests" / "test_filters.py").unlink()
    report = _select(repo, [FileChange("tests/test_filters.py", "delete")])
    assert "tests/test_filters.py" not in report.selected
    assert all((repo / node).is_file() for node in report.selected)


def test_rename_maps_new_path_and_drops_missing_old_test(tmp_path):
    repo = _mini_repo(tmp_path)
    old = repo / "tests" / "test_filters.py"
    new = repo / "tests" / "test_filters_renamed.py"
    old.rename(new)
    report = _select(
        repo,
        [
            FileChange(
                "tests/test_filters_renamed.py",
                "rename",
                previous_path="tests/test_filters.py",
            )
        ],
    )
    assert "tests/test_filters_renamed.py" in report.selected
    assert "tests/test_filters.py" not in report.selected

    product_repo = _mini_repo(tmp_path / "product-rename")
    product = _select(
        product_repo,
        [
            FileChange(
                "mf4_analyzer/signal/filters_new.py",
                "rename",
                previous_path="mf4_analyzer/signal/filters.py",
            )
        ],
    )
    assert "tests/test_filters.py" in product.selected
    assert "tests/test_signal_no_gui_import.py" in product.selected


def test_from_diff_tracks_add_delete_rename_untracked(tmp_path):
    repo = _mini_repo(tmp_path)
    _write(repo / ".gitignore", "__pycache__/\n.pytest_cache/\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test Gate")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "initial")

    _write(repo / "mf4_analyzer" / "signal" / "new_filter.py", "x = 1\n")
    (repo / "mf4_analyzer" / "io" / "head_hdf.py").unlink()
    old = repo / "tests" / "test_filters.py"
    new = repo / "tests" / "test_filters_moved.py"
    _git(repo, "mv", str(old.relative_to(repo)), str(new.relative_to(repo)))
    _write(repo / "mystery.txt", "untracked\n")

    changes = discover_changes_from_git(repo)
    kinds = {(item.path, item.kind) for item in changes}
    assert ("mf4_analyzer/signal/new_filter.py", "add") in kinds
    assert ("mf4_analyzer/io/head_hdf.py", "delete") in kinds
    assert ("mystery.txt", "add") in kinds
    renamed = [item for item in changes if item.kind == "rename"]
    assert any(item.path.endswith("test_filters_moved.py") for item in renamed)

    report = _select(repo, changes)
    assert "tests/test_signal_no_gui_import.py" in report.selected
    assert "tests/test_head_hdf.py" in report.selected
    assert "tests/test_filters_moved.py" in report.selected
    assert any(item["path"] == "mystery.txt" for item in report.unmapped)
    assert report.coverage_sufficient is False
    assert report.coverage_claim == "needs-coordinator-inspection"


def test_shared_conftest_is_wide_and_requires_autouse_scope(tmp_path):
    repo = _mini_repo(tmp_path)
    report = _select(repo, [FileChange("tests/conftest.py", "modify")])
    assert "tests/test_conftest_autouse_scope.py" in report.selected
    assert "tests/test_qsettings_isolation.py" in report.selected
    extra_ids = {gate["id"] for gate in report.suggested_extra_gates}
    assert "full_integration" in extra_ids
    assert report.coverage_sufficient is False
    assert report.coverage_claim == "infra-wide-requires-integration"
    joined = " ".join(report.commands)
    assert joined.strip().startswith(sys.executable) or "test_conftest_autouse_scope.py" in joined


def test_pytest_ini_is_wide(tmp_path):
    repo = _mini_repo(tmp_path)
    report = _select(repo, [FileChange("pytest.ini", "modify")])
    assert "tests/test_conftest_autouse_scope.py" in report.selected
    assert report.coverage_claim == "infra-wide-requires-integration"


def test_unknown_path_does_not_claim_coverage_or_default_all(tmp_path):
    repo = _mini_repo(tmp_path)
    report = _select(repo, [FileChange("docs/unmapped.md", "add")])
    assert report.selected == []
    assert report.unmapped[0]["path"] == "docs/unmapped.md"
    assert "coordinator must inspect" in report.unmapped[0]["action"]
    assert report.coverage_sufficient is False
    assert report.coverage_claim == "needs-coordinator-inspection"
    assert report.claims_full_coverage is False
    joined = " ".join(report.commands)
    assert "-m pytest -q" not in joined
    assert "unmapped" in joined
    ledger = format_ledger(report)
    assert "coverage_claim: needs-coordinator-inspection" in ledger
    assert "claims_full_coverage: false" in ledger


def test_cross_module_product_plus_helper_combo(tmp_path):
    repo = _mini_repo(tmp_path)
    report = _select(
        repo,
        [
            FileChange("mf4_analyzer/signal/filters.py", "modify"),
            FileChange("tests/ui/test_helper.py", "modify"),
        ],
    )
    assert "tests/test_filters.py" in report.selected
    assert "tests/test_signal_no_gui_import.py" in report.selected
    assert "tests/ui/test_helper.py" in report.selected
    assert "tests/ui/test_mid.py" in report.selected
    assert "tests/ui/test_leaf.py" in report.selected
    helper_reasons = {
        reason.via for reason in report.reasons["tests/ui/test_leaf.py"]
    }
    assert "test-helper-consumer" in helper_reasons


def test_helper_consumers_are_multi_level(tmp_path):
    repo = _mini_repo(tmp_path)
    report = _select(repo, [FileChange("tests/ui/test_helper.py", "modify")])
    assert report.selected == [
        "tests/ui/test_helper.py",
        "tests/ui/test_leaf.py",
        "tests/ui/test_mid.py",
    ]


def test_helper_graph_is_not_cached_across_mutation(tmp_path):
    repo = _mini_repo(tmp_path)
    extra = repo / "tests" / "ui" / "test_extra.py"
    _write(extra, "def test_extra():\n    assert True\n")
    first = _select(repo, [FileChange("tests/ui/test_helper.py", "modify")])
    assert "tests/ui/test_extra.py" not in first.selected
    extra.write_text(
        "from tests.ui.test_helper import harness\n"
        "def test_extra():\n    assert harness() == 1\n",
        encoding="utf-8",
    )
    second = _select(repo, [FileChange("tests/ui/test_helper.py", "modify")])
    assert "tests/ui/test_extra.py" in second.selected
    extra.write_text("def test_extra():\n    assert True\n", encoding="utf-8")
    third = _select(repo, [FileChange("tests/ui/test_helper.py", "modify")])
    assert "tests/ui/test_extra.py" not in third.selected


def test_selected_nodes_exist_via_collection(tmp_path):
    repo = _mini_repo(tmp_path)
    report = _select(
        repo,
        [FileChange("mf4_analyzer/signal/filters.py", "modify")],
        collect_validate=True,
    )
    assert report.collect_validation is not None
    assert report.collect_validation["ok"] is True
    collected = report.collect_validation["collected"]
    assert any(item.startswith("tests/test_filters.py") for item in collected)
    assert any(
        item.startswith("tests/test_signal_no_gui_import.py") for item in collected
    )
    assert report.collect_validation["missing"] == []
    command = report.collect_validation["command"]
    assert set(command[-2:]) == {
        "tests/test_filters.py",
        "tests/test_signal_no_gui_import.py",
    }


def test_selector_own_tests_are_selected(tmp_path):
    repo = _mini_repo(tmp_path)
    report = _select(repo, [FileChange("scripts/select_test_gate.py", "modify")])
    assert report.selected == ["tests/test_test_gate_selection.py"]
    self_change = _select(
        repo, [FileChange("tests/test_test_gate_selection.py", "modify")]
    )
    assert "tests/test_test_gate_selection.py" in self_change.selected


def test_real_route_nodes_exist():
    routes = load_routes(REAL_ROUTES)
    missing = []
    for owner in [routes["selector"], *routes["owners"]]:
        for spec in list(owner.get("owner_tests") or []) + list(
            owner.get("boundary_tests") or []
        ):
            path = REPO_ROOT / spec
            if spec.endswith("/") or path.is_dir():
                if not path.is_dir():
                    missing.append(spec)
                continue
            if not path.is_file():
                missing.append(spec)
    for spec in routes["infra"]["required_nodes"] + routes["infra"]["infra_regressions"]:
        if not (REPO_ROOT / spec).is_file():
            missing.append(spec)
    for spec in routes["acceptance_sets"]["real_file"]["nodes"]:
        if not (REPO_ROOT / spec).is_file():
            missing.append(spec)
    assert missing == []


def test_real_filters_owner_example_collects():
    report = select_gate(
        [FileChange("mf4_analyzer/signal/filters.py", "modify")],
        repo_root=REPO_ROOT,
        routes_path=REAL_ROUTES,
        collect_validate=True,
        include_event_summary=False,
        python=sys.executable,
    )
    assert "tests/test_filters.py" in report.selected
    assert "tests/test_signal_no_gui_import.py" in report.selected
    assert report.unmapped == []
    assert report.coverage_claim == "focused-mapped"
    assert report.claims_full_coverage is False
    assert report.collect_validation is not None
    assert report.collect_validation["ok"] is True
    assert report.collect_validation["missing"] == []


def test_real_ultraview_helper_selects_consumers():
    report = select_gate(
        [FileChange("tests/ui/test_ultraview_page.py", "modify")],
        repo_root=REPO_ROOT,
        routes_path=REAL_ROUTES,
        include_event_summary=False,
        python=sys.executable,
    )
    assert "tests/ui/test_ultraview_page.py" in report.selected
    assert "tests/ui/test_ultraview_author_multiselect.py" in report.selected
    assert "tests/ui/test_ultraview_page_wiring.py" in report.selected
    reasons = {
        reason.via
        for reason in report.reasons["tests/ui/test_ultraview_author_multiselect.py"]
    }
    assert "test-helper-consumer" in reasons


def test_dry_run_cli_prints_ledger_only(tmp_path):
    repo = _mini_repo(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "select_test_gate.py"),
            "--repo-root",
            str(repo),
            "--routes",
            str(repo / "scripts" / "test_gate_routes.json"),
            "--files",
            "mf4_analyzer/signal/filters.py",
            "--no-event-summary",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "dry-run; commands not executed" in completed.stdout
    assert "tests/test_filters.py" in completed.stdout
    assert "fully covered" not in completed.stdout.lower()
    assert "focused PASS is not full PASS" in completed.stdout


def test_missing_test_runs_does_not_invent_slow_numbers(tmp_path):
    repo = _mini_repo(tmp_path)
    report = select_gate(
        [FileChange("mf4_analyzer/signal/filters.py", "modify")],
        repo_root=repo,
        routes=_mini_routes(),
        include_event_summary=True,
        python=sys.executable,
    )
    assert report.slow_node_summary is None
    assert any("test-runs" in note for note in report.notes)
