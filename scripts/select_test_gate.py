#!/usr/bin/env python3
"""Select focused pytest nodes from an explicit owner map.

The runner (``scripts/run_test_gate.py``) stays the executor. This script only
prints a selection ledger and the commands a coordinator would run.

First-version routes cover confirmed high-frequency owners only. Unknown paths
are reported for coordinator inspection; they never default to the full suite
or to an empty "fully covered" claim.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROUTES_PATH = Path(__file__).resolve().parent / "test_gate_routes.json"
_TEST_MODULE_PREFIXES = ("test_",)
_TEST_MODULE_SUFFIXES = ("_test.py",)
_FOCUS_NOTE = "focused PASS is not full PASS"


@dataclass(frozen=True)
class FileChange:
    """One path observed as added, modified, deleted, or renamed."""

    path: str
    kind: str
    previous_path: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"add", "modify", "delete", "rename"}:
            raise ValueError(f"unknown change kind: {self.kind!r}")


@dataclass(frozen=True)
class SelectionReason:
    node: str
    via: str
    source: str
    owner_id: str = ""
    detail: str = ""


@dataclass
class SelectionReport:
    changes: list[FileChange]
    selected: list[str]
    reasons: dict[str, list[SelectionReason]]
    unmapped: list[dict[str, str]]
    suggested_extra_gates: list[dict[str, Any]]
    coverage_sufficient: bool
    coverage_claim: str
    commands: list[str]
    notes: list[str]
    missing_selected: list[str] = field(default_factory=list)
    collect_validation: dict[str, Any] | None = None
    slow_node_summary: dict[str, Any] | None = None
    claims_full_coverage: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "changes": [
                {
                    "path": change.path,
                    "kind": change.kind,
                    "previous_path": change.previous_path,
                }
                for change in self.changes
            ],
            "selected": list(self.selected),
            "reasons": {
                node: [
                    {
                        "node": reason.node,
                        "via": reason.via,
                        "source": reason.source,
                        "owner_id": reason.owner_id,
                        "detail": reason.detail,
                    }
                    for reason in reasons
                ]
                for node, reasons in self.reasons.items()
            },
            "unmapped": list(self.unmapped),
            "suggested_extra_gates": list(self.suggested_extra_gates),
            "coverage_sufficient": self.coverage_sufficient,
            "coverage_claim": self.coverage_claim,
            "claims_full_coverage": False,
            "commands": list(self.commands),
            "notes": list(self.notes),
            "missing_selected": list(self.missing_selected),
            "collect_validation": self.collect_validation,
            "slow_node_summary": self.slow_node_summary,
        }


def posix_rel(path: str | Path) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def _default_python(repo_root: Path) -> str:
    candidate = repo_root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "python"
    return str(candidate) if candidate.exists() else sys.executable


def load_routes(path: str | Path | None = None) -> dict[str, Any]:
    routes_path = Path(path) if path is not None else DEFAULT_ROUTES_PATH
    return json.loads(routes_path.read_text(encoding="utf-8"))


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def discover_changes_from_git(repo_root: Path) -> list[FileChange]:
    """Tracked diffs vs HEAD plus untracked files. Renames keep both paths."""

    diff = _run_git(repo_root, "diff", "--name-status", "-M", "-z", "HEAD")
    if diff.returncode != 0:
        raise RuntimeError(
            "git diff failed; --from-diff needs a git checkout:\n"
            f"{diff.stderr.strip()}"
        )
    changes: list[FileChange] = []
    seen: set[tuple[str, str, str | None]] = set()
    tokens = [part for part in diff.stdout.split("\0") if part]
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        code = status[0] if status else ""
        if code in {"R", "C"}:
            if index + 1 >= len(tokens):
                break
            old = posix_rel(tokens[index])
            new = posix_rel(tokens[index + 1])
            index += 2
            kind = "rename"
            key = (new, kind, old)
            if key not in seen:
                seen.add(key)
                changes.append(FileChange(path=new, kind=kind, previous_path=old))
            continue
        if index >= len(tokens):
            break
        path = posix_rel(tokens[index])
        index += 1
        kind = {"A": "add", "D": "delete", "M": "modify", "T": "modify"}.get(code, "modify")
        key = (path, kind, None)
        if key not in seen:
            seen.add(key)
            changes.append(FileChange(path=path, kind=kind))

    untracked = _run_git(
        repo_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )
    if untracked.returncode != 0:
        raise RuntimeError(
            "git ls-files failed; --from-diff needs a git checkout:\n"
            f"{untracked.stderr.strip()}"
        )
    for raw in untracked.stdout.split("\0"):
        if not raw:
            continue
        path = posix_rel(raw)
        key = (path, "add", None)
        if key not in seen:
            seen.add(key)
            changes.append(FileChange(path=path, kind="add"))
    return changes


def _path_matches(path: str, pattern: str) -> bool:
    rel = posix_rel(path)
    pat = posix_rel(pattern)
    if "*" in pat or "?" in pat or "[" in pat:
        return fnmatch.fnmatch(rel, pat)
    stripped = pat.rstrip("/")
    if rel == stripped:
        return True
    return rel.startswith(stripped + "/")


def _is_test_module(path: str) -> bool:
    name = Path(posix_rel(path)).name
    if not name.endswith(".py"):
        return False
    if name.startswith(_TEST_MODULE_PREFIXES):
        return True
    return name.endswith(_TEST_MODULE_SUFFIXES)


def _is_under_tests(path: str) -> bool:
    rel = posix_rel(path)
    return rel == "tests" or rel.startswith("tests/")


def _existing_file(repo_root: Path, rel: str) -> bool:
    return (repo_root / rel).is_file()


def expand_test_spec(repo_root: Path, spec: str) -> tuple[list[str], bool]:
    """Expand a route entry to concrete test modules.

    Returns ``(paths, found)``. Directories expand to ``test_*.py`` children.
    Missing files return ``found=False``.
    """

    rel = posix_rel(spec)
    path = repo_root / rel
    if rel.endswith("/") or path.is_dir():
        if not path.is_dir():
            return [], False
        found = [
            posix_rel(child.relative_to(repo_root))
            for child in sorted(path.rglob("test_*.py"))
            if child.is_file()
        ]
        return found, True
    if path.is_file():
        return [rel], True
    return [rel], False


def _iter_py_files(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return
    for path in root.rglob("*.py"):
        if path.is_file() and "__pycache__" not in path.parts:
            yield path


def _resolve_imported_module(module: str, repo_root: Path) -> Path | None:
    if not module or module.startswith("."):
        return None
    parts = module.split(".")
    rel = Path(*parts)
    candidate = repo_root / rel.with_suffix(".py")
    package = repo_root / rel / "__init__.py"
    if candidate.is_file():
        return candidate
    if package.is_file():
        return package
    # Keep missing tests.* helpers so a delete/rename still finds consumers.
    if parts[0] == "tests":
        return candidate
    return None


def _imported_test_paths(tree: ast.AST, source_path: Path, repo_root: Path) -> set[str]:
    found: set[str] = set()

    def _keep(resolved: Path | None) -> None:
        if resolved is None:
            return
        try:
            rel = posix_rel(resolved.resolve().relative_to(repo_root.resolve()))
        except ValueError:
            return
        if not _is_under_tests(rel):
            return
        found.add(rel)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _keep(_resolve_imported_module(alias.name, repo_root))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                package_dir = source_path.parent
                for _ in range(node.level - 1):
                    package_dir = package_dir.parent
                if module:
                    abs_mod_parts = list(package_dir.relative_to(repo_root).parts)
                    abs_mod_parts.extend(module.split("."))
                    abs_mod = ".".join(abs_mod_parts)
                else:
                    abs_mod = ".".join(package_dir.relative_to(repo_root).parts)
            else:
                abs_mod = module
            _keep(_resolve_imported_module(abs_mod, repo_root))
            if abs_mod:
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    submodule = _resolve_imported_module(f"{abs_mod}.{alias.name}", repo_root)
                    if submodule is None:
                        continue
                    try:
                        sub_rel = posix_rel(submodule.resolve().relative_to(repo_root.resolve()))
                    except ValueError:
                        continue
                    if submodule.is_file() or _is_test_module(sub_rel):
                        _keep(submodule)
    found.discard(posix_rel(source_path.resolve().relative_to(repo_root)))
    return found


def scan_test_helper_graph(repo_root: Path) -> dict[str, set[str]]:
    """Map helper path → direct consumer test paths.

    Built from the current files on disk for this call only. Do not reuse the
    result across monkeypatch or mutation; a later ``select_gate`` must scan
    again.
    """

    graph: dict[str, set[str]] = defaultdict(set)
    tests_root = repo_root / "tests"
    for path in _iter_py_files(tests_root):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        consumer = posix_rel(path.resolve().relative_to(repo_root))
        for helper in _imported_test_paths(tree, path, repo_root):
            graph[helper].add(consumer)
    return graph


def transitive_consumers(helper: str, graph: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    queue: deque[str] = deque([helper])
    while queue:
        current = queue.popleft()
        for consumer in graph.get(current, ()):
            if consumer in seen:
                continue
            seen.add(consumer)
            queue.append(consumer)
    seen.discard(helper)
    return seen


def _infra_paths(routes: dict[str, Any]) -> set[str]:
    infra = routes.get("infra") or {}
    names = (
        list(infra.get("pytest_config") or [])
        + list(infra.get("conftest") or [])
        + list(infra.get("shared_helpers") or [])
    )
    return {posix_rel(item) for item in names}


def _owner_records(routes: dict[str, Any]) -> list[dict[str, Any]]:
    records = list(routes.get("owners") or [])
    selector = routes.get("selector")
    if selector:
        records = [selector, *records]
    return records


def _match_owners(path: str, routes: dict[str, Any]) -> list[dict[str, Any]]:
    matched = []
    for owner in _owner_records(routes):
        patterns = list(owner.get("source_paths") or [])
        if any(_path_matches(path, pattern) for pattern in patterns):
            matched.append(owner)
    return matched


def _add_reason(
    reasons: dict[str, list[SelectionReason]],
    reason: SelectionReason,
) -> None:
    existing = reasons.setdefault(reason.node, [])
    key = (reason.via, reason.source, reason.owner_id, reason.detail)
    if any(
        (item.via, item.source, item.owner_id, item.detail) == key for item in existing
    ):
        return
    existing.append(reason)


def _change_paths(change: FileChange) -> list[str]:
    paths = [change.path]
    if change.previous_path and change.previous_path not in paths:
        paths.append(change.previous_path)
    return paths


def _acceptance_command(python: str, template: str, nodes: Sequence[str] | None = None) -> str:
    filled = template.replace("{python}", shlex.quote(python))
    if nodes is not None:
        filled = filled.replace("{nodes}", shlex.join(nodes))
    return filled


def summarize_slow_nodes(run_root: Path, *, limit: int = 15) -> dict[str, Any] | None:
    """Summarize durations from existing runner events. Invent nothing."""

    if not run_root.is_dir():
        return None
    event_files = sorted(run_root.rglob("pytest-events.jsonl"))
    if not event_files:
        return {
            "present": True,
            "events_found": False,
            "nodes": [],
            "note": "test-runs directory exists but no pytest event logs were found",
        }

    totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {"setup": 0.0, "call": 0.0, "teardown": 0.0, "total": 0.0}
    )
    parsed = 0
    for event_path in event_files:
        try:
            lines = event_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            nodeid = payload.get("nodeid")
            phase = payload.get("phase")
            duration = payload.get("duration_seconds")
            if not nodeid or phase not in {"setup", "call", "teardown"}:
                continue
            if not isinstance(duration, (int, float)):
                continue
            parsed += 1
            bucket = totals[str(nodeid)]
            bucket[str(phase)] += float(duration)
            bucket["total"] += float(duration)
    ranked = sorted(totals.items(), key=lambda item: item[1]["total"], reverse=True)
    return {
        "present": True,
        "events_found": True,
        "event_files": [str(path) for path in event_files],
        "parsed_duration_events": parsed,
        "nodes": [
            {"nodeid": nodeid, **durations} for nodeid, durations in ranked[:limit]
        ],
    }


def validate_collection(
    repo_root: Path,
    nodes: Sequence[str],
    *,
    python: str | None = None,
    timeout_seconds: float = 180.0,
) -> dict[str, Any]:
    """Collect the selected subset with pytest. Preserve the given node order."""

    if not nodes:
        return {
            "ok": True,
            "collected": [],
            "missing": [],
            "command": [],
            "returncode": 0,
        }
    python = python or _default_python(repo_root)
    command = [python, "-m", "pytest", "--collect-only", "-q", *nodes]
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env.setdefault("TMPDIR", "/tmp")
    env.setdefault("MPLCONFIGDIR", "/tmp")
    env["PYTHONPATH"] = (
        str(repo_root)
        if not env.get("PYTHONPATH")
        else os.pathsep.join([str(repo_root), env["PYTHONPATH"]])
    )
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout_seconds,
    )
    collected: list[str] = []
    for line in completed.stdout.splitlines():
        text = line.strip()
        if "::" in text and not text.startswith("="):
            collected.append(text.split()[0])
    missing = [node for node in nodes if not any(item.startswith(node) for item in collected)]
    return {
        "ok": completed.returncode == 0 and not missing,
        "collected": collected,
        "missing": missing,
        "command": command,
        "returncode": completed.returncode,
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-20:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-20:]),
    }


def select_gate(
    changes: Sequence[FileChange],
    *,
    repo_root: Path,
    routes: dict[str, Any] | None = None,
    routes_path: str | Path | None = None,
    collect_validate: bool = False,
    include_event_summary: bool = False,
    python: str | None = None,
) -> SelectionReport:
    repo_root = repo_root.resolve()
    if routes is None:
        routes = load_routes(routes_path)
    python = python or _default_python(repo_root)
    helper_graph = scan_test_helper_graph(repo_root)
    infra_paths = _infra_paths(routes)
    infra_cfg = routes.get("infra") or {}
    reasons: dict[str, list[SelectionReason]] = {}
    unmapped: list[dict[str, str]] = []
    suggested: dict[str, dict[str, Any]] = {}
    wide_infra = False
    mapped_change_keys: set[str] = set()

    def remember_gate(name: str, *, why: str) -> None:
        acceptance = (routes.get("acceptance_sets") or {}).get(name) or {}
        command = ""
        if "command" in acceptance:
            command = _acceptance_command(python, str(acceptance["command"]))
        elif acceptance.get("commands"):
            command = _acceptance_command(python, str(acceptance["commands"][0]))
        current = suggested.get(name)
        if current is None:
            suggested[name] = {
                "id": name,
                "why": why,
                "command": command,
                "when": acceptance.get("when", ""),
                "result_scope": acceptance.get("result_scope", ""),
            }
        elif why not in current["why"]:
            current["why"] = f"{current['why']}; {why}"

    def select_spec(
        spec: str,
        *,
        via: str,
        source: str,
        owner_id: str = "",
        detail: str = "",
    ) -> None:
        expanded, found = expand_test_spec(repo_root, spec)
        if not found:
            _add_reason(
                reasons,
                SelectionReason(
                    node=posix_rel(spec),
                    via="missing",
                    source=source,
                    owner_id=owner_id,
                    detail=detail or "route names a path that is not on disk",
                ),
            )
            return
        for node in expanded:
            if not _existing_file(repo_root, node):
                _add_reason(
                    reasons,
                    SelectionReason(
                        node=node,
                        via="missing",
                        source=source,
                        owner_id=owner_id,
                        detail=detail,
                    ),
                )
                continue
            _add_reason(
                reasons,
                SelectionReason(
                    node=node,
                    via=via,
                    source=source,
                    owner_id=owner_id,
                    detail=detail,
                ),
            )

    for change in changes:
        change_mapped = False
        for path in _change_paths(change):
            rel = posix_rel(path)
            if rel in infra_paths or any(_path_matches(rel, item) for item in infra_paths):
                change_mapped = True
                wide_infra = True
                for spec in list(infra_cfg.get("required_nodes") or []) + list(
                    infra_cfg.get("infra_regressions") or []
                ):
                    select_spec(
                        spec,
                        via="infra",
                        source=rel,
                        owner_id="infra",
                        detail="shared helper / conftest / pytest config is wide",
                    )
                remember_gate(
                    "full_integration",
                    why=f"wide infra path {rel} requires a stable integration gate after infra regressions",
                )

            for owner in _match_owners(rel, routes):
                change_mapped = True
                owner_id = str(owner.get("id") or "")
                for spec in owner.get("owner_tests") or []:
                    select_spec(
                        spec,
                        via="owner",
                        source=rel,
                        owner_id=owner_id,
                        detail=str(owner.get("label") or owner_id),
                    )
                for spec in owner.get("boundary_tests") or []:
                    select_spec(
                        spec,
                        via="boundary",
                        source=rel,
                        owner_id=owner_id,
                        detail="applicable boundary listed by the owner route",
                    )
                for gate_name in owner.get("suggested_extra_gates") or []:
                    remember_gate(
                        str(gate_name),
                        why=f"owner {owner_id} lists extra gate {gate_name} for {rel}",
                    )

            if _is_under_tests(rel):
                if _is_test_module(rel) and _existing_file(repo_root, rel) and change.kind != "delete":
                    change_mapped = True
                    select_spec(
                        rel,
                        via="changed-test",
                        source=rel,
                        detail="changed test module is always selected",
                    )
                if _existing_file(repo_root, rel) or change.kind != "add":
                    consumers = transitive_consumers(rel, helper_graph)
                    if consumers or rel in helper_graph:
                        change_mapped = True
                    for consumer in sorted(consumers):
                        if not _existing_file(repo_root, consumer):
                            continue
                        select_spec(
                            consumer,
                            via="test-helper-consumer",
                            source=rel,
                            detail="test module imported this helper (multi-level scan)",
                        )

            if change.kind == "rename" and change.previous_path:
                old = posix_rel(change.previous_path)
                if _is_test_module(rel) and _existing_file(repo_root, rel):
                    change_mapped = True
                    select_spec(
                        rel,
                        via="changed-test",
                        source=old,
                        detail=f"renamed from {old}",
                    )

        if change_mapped:
            mapped_change_keys.add(f"{change.kind}:{change.path}")
        else:
            unmapped.append(
                {
                    "path": change.path,
                    "kind": change.kind,
                    "previous_path": change.previous_path or "",
                    "action": (
                        "coordinator must inspect this path and add an explicit "
                        "owner route if it needs a focused gate; not defaulting "
                        "to all tests or to an empty complete-coverage set"
                    ),
                }
            )

    selected: list[str] = []
    missing_selected: list[str] = []
    seen_nodes: set[str] = set()
    for node, node_reasons in reasons.items():
        if any(reason.via == "missing" for reason in node_reasons) and not _existing_file(
            repo_root, node
        ):
            missing_selected.append(node)
            continue
        if node in seen_nodes:
            continue
        if not _existing_file(repo_root, node):
            missing_selected.append(node)
            continue
        seen_nodes.add(node)
        selected.append(node)
    selected.sort()

    notes = [
        _FOCUS_NOTE,
        "Default full integration remains two sequential fresh processes: "
        "main (--ignore=tests/acquisition_ui) then tests/acquisition_ui.",
        "Slow, real-file, native, and frozen sets stay explicit extra gates.",
        "Collector identity repair lives in repo-root conftest.py; "
        "tests/test_conftest_autouse_scope.py is the required guard. "
        "Do not freeze pytest argument order to hide fixture loss.",
        "Unknown paths are not treated as complete coverage.",
    ]
    if wide_infra:
        notes.append(
            "Wide infra: run listed infra regressions first, then a coordinator-"
            "owned stable integration gate."
        )
    if unmapped:
        notes.append(
            "Unmapped paths require coordinator inspection; the selector did "
            "not default to all tests and did not claim complete coverage."
        )

    if unmapped:
        coverage_claim = "needs-coordinator-inspection"
        coverage_sufficient = False
    elif wide_infra:
        coverage_claim = "infra-wide-requires-integration"
        coverage_sufficient = False
    elif missing_selected:
        coverage_claim = "mapped-but-missing-nodes"
        coverage_sufficient = False
    elif selected:
        coverage_claim = "focused-mapped"
        coverage_sufficient = True
    else:
        coverage_claim = "no-focused-nodes"
        coverage_sufficient = False

    commands: list[str] = []
    if selected:
        commands.append(
            shlex.join([python, "-m", "pytest", *selected, "-q"])
        )
    elif unmapped:
        commands.append(
            "# no focused pytest command; unmapped paths require coordinator inspection"
        )
    elif wide_infra:
        commands.append(
            "# no additional focused product nodes; run infra regressions then full_integration"
        )
    else:
        commands.append(
            "# no focused pytest command; nothing mapped and nothing selected"
        )

    extra_list = list(suggested.values())
    if wide_infra and not any(item["id"] == "full_integration" for item in extra_list):
        remember_gate(
            "full_integration",
            why="wide infra requires a stable integration gate",
        )
        extra_list = list(suggested.values())

    collect_validation = None
    if collect_validate:
        collect_validation = validate_collection(repo_root, selected, python=python)

    slow_summary = None
    if include_event_summary:
        slow_summary = summarize_slow_nodes(repo_root / ".state" / "test-runs")
        if slow_summary is None:
            notes.append(
                "No .state/test-runs directory; slow-node summary skipped "
                "(numbers not invented)."
            )

    return SelectionReport(
        changes=list(changes),
        selected=selected,
        reasons={node: reasons[node] for node in selected if node in reasons},
        unmapped=unmapped,
        suggested_extra_gates=extra_list,
        coverage_sufficient=coverage_sufficient,
        coverage_claim=coverage_claim,
        commands=commands,
        notes=notes,
        missing_selected=missing_selected,
        collect_validation=collect_validation,
        slow_node_summary=slow_summary,
        claims_full_coverage=False,
    )


def format_ledger(report: SelectionReport) -> str:
    lines = [
        "=== test gate selection (dry-run; commands not executed) ===",
        f"coverage_claim: {report.coverage_claim}",
        f"coverage_sufficient: {str(report.coverage_sufficient).lower()}",
        f"claims_full_coverage: false",
        _FOCUS_NOTE,
        "",
        "Changes:",
    ]
    if report.changes:
        for change in report.changes:
            extra = f"  (was {change.previous_path})" if change.previous_path else ""
            lines.append(f"  {change.kind:<7} {change.path}{extra}")
    else:
        lines.append("  (none)")

    lines.extend(["", "Selected nodes:"])
    if report.selected:
        for node in report.selected:
            lines.append(f"  {node}")
            for reason in report.reasons.get(node, []):
                owner = f" owner={reason.owner_id}" if reason.owner_id else ""
                detail = f" {reason.detail}" if reason.detail else ""
                lines.append(
                    f"    - via={reason.via} source={reason.source}{owner}{detail}"
                )
    else:
        lines.append("  (none)")

    lines.extend(["", "Unmapped paths:"])
    if report.unmapped:
        for item in report.unmapped:
            lines.append(f"  {item['kind']:<7} {item['path']}")
            lines.append(f"    {item['action']}")
    else:
        lines.append("  (none)")

    if report.missing_selected:
        lines.extend(["", "Route nodes missing on disk:"])
        for node in report.missing_selected:
            lines.append(f"  {node}")

    lines.extend(["", "Suggested extra gates:"])
    if report.suggested_extra_gates:
        for gate in report.suggested_extra_gates:
            lines.append(f"  {gate['id']}: {gate.get('why', '')}")
            if gate.get("command"):
                lines.append(f"    command: {gate['command']}")
            if gate.get("result_scope"):
                lines.append(f"    scope: {gate['result_scope']}")
    else:
        lines.append("  (none beyond the focused command; milestone full integration still exists)")

    lines.extend(["", "Notes:"])
    for note in report.notes:
        lines.append(f"  - {note}")

    if report.slow_node_summary is not None:
        lines.extend(["", "Slow-node summary from existing events:"])
        summary = report.slow_node_summary
        if not summary.get("events_found"):
            lines.append(f"  {summary.get('note') or 'no events found; no numbers invented'}")
        else:
            lines.append(
                f"  parsed_duration_events={summary.get('parsed_duration_events', 0)}"
            )
            for item in summary.get("nodes") or []:
                lines.append(
                    f"  {item['nodeid']}: total={item['total']:.4f}s "
                    f"setup={item['setup']:.4f}s call={item['call']:.4f}s "
                    f"teardown={item['teardown']:.4f}s"
                )
    elif any("test-runs" in note for note in report.notes):
        pass

    if report.collect_validation is not None:
        lines.extend(["", "Collection validation:"])
        payload = report.collect_validation
        lines.append(f"  ok={payload.get('ok')} collected={len(payload.get('collected') or [])}")
        if payload.get("missing"):
            lines.append(f"  missing: {', '.join(payload['missing'])}")

    lines.extend(["", "Commands (not executed):"])
    for command in report.commands:
        lines.append(f"  {command}")
    lines.append("")
    return "\n".join(lines)


def _parse_renamed(value: str) -> tuple[str, str]:
    if "=" not in value and ":" not in value:
        raise argparse.ArgumentTypeError("rename must be OLD=NEW or OLD:NEW")
    sep = "=" if "=" in value else ":"
    old, new = value.split(sep, 1)
    old, new = old.strip(), new.strip()
    if not old or not new:
        raise argparse.ArgumentTypeError("rename must be OLD=NEW")
    return old, new


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Select focused pytest nodes from scripts/test_gate_routes.json. "
            "Dry-run only: prints the ledger and commands; does not run the gate."
        )
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--routes", type=Path, default=None, help="Route map JSON.")
    parser.add_argument("--files", nargs="*", default=[], help="Specified changed paths.")
    parser.add_argument(
        "--deleted",
        nargs="*",
        default=[],
        help="Specified deleted paths (not passed as pytest nodes).",
    )
    parser.add_argument(
        "--renamed",
        nargs="*",
        default=[],
        type=_parse_renamed,
        help="Specified renames as OLD=NEW.",
    )
    parser.add_argument(
        "--from-diff",
        action="store_true",
        help="Include current tracked/untracked git diff.",
    )
    parser.add_argument(
        "--collect-validate",
        action="store_true",
        help="Collection-check the selected subset with pytest --collect-only.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional JSON report path.",
    )
    parser.add_argument(
        "--no-event-summary",
        action="store_true",
        help="Skip reading .state/test-runs even if present.",
    )
    return parser


def build_changes_from_args(args: argparse.Namespace, repo_root: Path) -> list[FileChange]:
    changes: list[FileChange] = []
    seen: set[tuple[str, str, str | None]] = set()

    def add(change: FileChange) -> None:
        key = (change.path, change.kind, change.previous_path)
        if key in seen:
            return
        seen.add(key)
        changes.append(change)

    if args.from_diff:
        for change in discover_changes_from_git(repo_root):
            add(change)
    for path in args.files:
        rel = posix_rel(path)
        kind = "delete" if not (repo_root / rel).exists() else "modify"
        add(FileChange(path=rel, kind=kind))
    for path in args.deleted:
        add(FileChange(path=posix_rel(path), kind="delete"))
    for old, new in args.renamed:
        add(FileChange(path=posix_rel(new), kind="rename", previous_path=posix_rel(old)))
    return changes


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    if not args.from_diff and not args.files and not args.deleted and not args.renamed:
        parser.error("provide --files, --deleted, --renamed, and/or --from-diff")
    try:
        changes = build_changes_from_args(args, repo_root)
    except RuntimeError as exc:
        parser.error(str(exc))
    report = select_gate(
        changes,
        repo_root=repo_root,
        routes_path=args.routes,
        collect_validate=args.collect_validate,
        include_event_summary=not args.no_event_summary,
    )
    sys.stdout.write(format_ledger(report) + "\n")
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if report.collect_validation is not None and not report.collect_validation.get("ok"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
