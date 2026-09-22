"""W6a: launcher hidden probe routing and source/bundled/modular bootstrap."""
from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import sys
from types import ModuleType

import pytest

from mf4_analyzer.extensions.contract import ManagerExitCode
from mf4_analyzer.extensions.locking import write_staging_auth
from mf4_analyzer.extensions.probe import (
    PROBE_ARGV_FLAGS,
    PROBE_REQUEST_FLAG,
    PROBE_RESULT_FLAG,
    build_probe_request,
    write_result_json,
)
from mf4_analyzer.extensions.runtime import (
    MODE_BUNDLED,
    MODE_MODULAR,
    MODE_SOURCE,
    STATUS_NOT_INSTALLED,
    STATUS_READY,
)
from mf4_analyzer.io.source_adapters import (
    OPEN_EXTENSION_MANAGER_ACTION,
    SourceAdapterRegistry,
    bind_extension_runtime,
    current_extension_runtime,
)
from tests.test_extension_transaction import RUNTIME_ID, _write_core


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "MF4 Data Analyzer V1.py"


@pytest.fixture(autouse=True)
def _reset_bootstrap():
    from mf4_analyzer.app import reset_extension_bootstrap_for_tests

    reset_extension_bootstrap_for_tests()
    yield
    reset_extension_bootstrap_for_tests()


def _staging(app_root: Path, txn: str = "txn-boot") -> Path:
    staging = app_root / "extensions" / ".staging" / txn
    staging.mkdir(parents=True)
    (staging / "media" / "site-packages" / "av").mkdir(parents=True)
    (staging / "media" / "site-packages" / "av" / "__init__.py").write_text(
        "ok\n", encoding="utf-8"
    )
    return staging


def test_source_mode_uses_venv_and_ignores_neighbor_extensions(tmp_path):
    from mf4_analyzer.app import bootstrap_extension_runtime

    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    (app_root / "extensions" / "install-id").write_text("abc\n", encoding="utf-8")
    snapshot = bootstrap_extension_runtime(app_root=app_root, frozen=False)
    assert snapshot.mode == MODE_SOURCE
    assert snapshot.core is None
    media = SourceAdapterRegistry.default().adapter_for("clip.wav").availability()
    assert media.action == ""


def test_bundled_mode_does_not_read_neighbor_extensions(tmp_path):
    from mf4_analyzer.app import bootstrap_extension_runtime

    app_root = tmp_path / "TraceLab"
    leftover = app_root / "extensions"
    leftover.mkdir(parents=True)
    (leftover / "active.json").write_text("{not-a-valid-active}", encoding="utf-8")
    snapshot = bootstrap_extension_runtime(app_root=app_root, frozen=True)
    assert snapshot.mode == MODE_BUNDLED
    assert snapshot.lease is None
    assert current_extension_runtime() is snapshot
    media = SourceAdapterRegistry.default().adapter_for("clip.wav").availability()
    assert media.action == ""
    assert media.component == ""


def test_modular_mode_consumes_load_runtime_not_find_spec(tmp_path, monkeypatch):
    from mf4_analyzer.app import bootstrap_extension_runtime

    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    (app_root / "extensions" / "install-id").write_text("id-1\n", encoding="utf-8")
    monkeypatch.setattr(
        "mf4_analyzer.io.source_adapters._package_available", lambda _name: True
    )
    snapshot = bootstrap_extension_runtime(app_root=app_root, frozen=True)
    assert snapshot.mode == MODE_MODULAR
    media = SourceAdapterRegistry.default().adapter_for("clip.wav").availability()
    matlab = SourceAdapterRegistry.default().adapter_for("run.mat").availability()
    assert media.status == "unavailable"
    assert media.component_status == STATUS_NOT_INSTALLED
    assert media.action == OPEN_EXTENSION_MANAGER_ACTION
    assert matlab.action == OPEN_EXTENSION_MANAGER_ACTION
    mdf = SourceAdapterRegistry.default().adapter_for("run.mf4").availability()
    assert mdf.action == ""


def test_explicit_source_switch_may_consume_extensions_folder(tmp_path, monkeypatch):
    from mf4_analyzer.app import bootstrap_extension_runtime

    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    (app_root / "extensions" / "install-id").write_text("id-2\n", encoding="utf-8")
    monkeypatch.setenv("TRACELAB_USE_EXTENSIONS", "1")
    snapshot = bootstrap_extension_runtime(app_root=app_root, frozen=False)
    assert snapshot.mode == MODE_MODULAR
    assert snapshot.availability("media").status == STATUS_NOT_INSTALLED


def test_bootstrap_keeps_dll_directory_handles_until_reset(tmp_path, monkeypatch):
    from mf4_analyzer.app import (
        apply_extension_search_path,
        extension_dll_directory_handles,
    )
    from mf4_analyzer.extensions.runtime import PlannedSearchPath

    site = tmp_path / "site-packages"
    site.mkdir()
    native = tmp_path / "native"
    native.mkdir()
    added: list[str] = []

    class _Handle:
        def __init__(self, path: str):
            self.path = path

    def fake_add(path):
        added.append(str(path))
        return _Handle(str(path))

    monkeypatch.setattr(os, "add_dll_directory", fake_add, raising=False)
    handles = apply_extension_search_path(
        PlannedSearchPath(module_roots=(site,), dll_directories=(native,))
    )
    assert str(site) in sys.path
    assert added == [str(native)]
    assert extension_dll_directory_handles() == tuple(handles)
    assert handles[0].path == str(native)


def test_optional_import_message_keeps_pip_copy_in_source_and_manager_copy_in_modular(
    tmp_path,
):
    from mf4_analyzer.io.source_adapters import optional_native_import_message
    from tests.test_source_adapters import _modular_snapshot

    assert "请安装 scipy" in optional_native_import_message("scipy", adapter_key="mat")
    bind_extension_runtime(_modular_snapshot(tmp_path, media_status=STATUS_READY))
    text = optional_native_import_message("scipy", adapter_key="mat")
    assert "打开扩展管理" in text
    assert "pip" not in text.lower()


def test_launcher_probe_abbreviation_fails_without_routing(tmp_path, monkeypatch):
    calls: list[str] = []

    def trap_child(argv=None):
        calls.append("probe")
        return 0

    fake_app = ModuleType("mf4_analyzer.app")
    fake_app.main = lambda: calls.append("gui") or None
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setattr(
        "mf4_analyzer.extensions.probe.child_main", trap_child
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["TraceLab.exe", "--extension-probe-re", str(tmp_path / "request.json")],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 2
    assert calls == []


def test_launcher_rejects_probe_payload_without_mode(tmp_path, monkeypatch):
    calls: list[str] = []
    fake_app = ModuleType("mf4_analyzer.app")
    fake_app.main = lambda: calls.append("gui") or None
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            "--extension-probe-result",
            str(tmp_path / "result.json"),
            "--importer-runtime-smoke",
            "--import-path",
            str(tmp_path / "a.mat"),
            "--json",
            str(tmp_path / "out.json"),
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 2
    assert calls == []
    assert not (tmp_path / "result.json").exists()
    assert not (tmp_path / "out.json").exists()


def test_launcher_probe_conflicts_with_importer_before_routing(tmp_path, monkeypatch):
    calls: list[str] = []

    def trap_child(argv=None):
        calls.append("probe")
        return 0

    importer = ModuleType("mf4_analyzer.io.importer_runtime_smoke")
    importer.run = lambda *_a, **_k: calls.append("importer") or 0
    fake_app = ModuleType("mf4_analyzer.app")
    fake_app.bootstrap_extension_runtime = lambda **_k: calls.append("boot")
    fake_app.main = lambda: calls.append("gui") or None
    monkeypatch.setitem(sys.modules, "mf4_analyzer.io.importer_runtime_smoke", importer)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setattr("mf4_analyzer.extensions.probe.child_main", trap_child)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            "--extension-probe-request",
            str(tmp_path / "request.json"),
            "--importer-runtime-smoke",
            "--import-path",
            str(tmp_path / "a.mat"),
            "--json",
            str(tmp_path / "out.json"),
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 2
    assert calls == []


def test_launcher_probe_rejects_result_alias_of_exe_and_active(tmp_path, monkeypatch):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    staging = _staging(app_root)
    nonce = "nonce-boot"
    write_staging_auth(staging, nonce)
    request = build_probe_request(
        core_build_id="cb1-test",
        runtime_id=RUNTIME_ID,
        transaction_id="txn-boot",
        components=["media"],
        package_hashes=["aa" * 32],
        staging_relpath=".staging/txn-boot",
        staging_nonce=nonce,
    )
    request_path = staging / "request.json"
    write_result_json(request_path, request)
    exe = app_root / "TraceLabAnalyzer.exe"
    original = exe.read_bytes()
    calls: list[str] = []
    monkeypatch.setattr(
        "mf4_analyzer.extensions.probe.child_main",
        lambda argv=None: calls.append("probe") or 0,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            PROBE_REQUEST_FLAG,
            str(request_path),
            PROBE_RESULT_FLAG,
            str(exe),
            "--extension-probe-staging",
            str(staging),
            "--extension-probe-staging-nonce",
            nonce,
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 2
    assert calls == []
    assert exe.read_bytes() == original

    active = app_root / "extensions" / "active.json"
    active.write_bytes(b"keep-me")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            PROBE_REQUEST_FLAG,
            str(request_path),
            PROBE_RESULT_FLAG,
            str(active),
            "--extension-probe-staging",
            str(staging),
            "--extension-probe-staging-nonce",
            nonce,
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 2
    assert active.read_bytes() == b"keep-me"
    core_files = app_root / "core-files.json"
    core_bytes = core_files.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            PROBE_REQUEST_FLAG,
            str(request_path),
            PROBE_RESULT_FLAG,
            str(core_files),
            "--extension-probe-staging",
            str(staging),
            "--extension-probe-staging-nonce",
            nonce,
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 2
    assert core_files.read_bytes() == core_bytes


def test_launcher_probe_windowed_none_streams_use_exit_and_json(tmp_path, monkeypatch):
    app_root = tmp_path / "TraceLab"
    _write_core(app_root)
    staging = _staging(app_root)
    nonce = "nonce-windowed"
    write_staging_auth(staging, nonce)
    request = build_probe_request(
        core_build_id="cb1-test",
        runtime_id=RUNTIME_ID,
        transaction_id="txn-boot",
        components=["media"],
        package_hashes=["aa" * 32],
        staging_relpath=".staging/txn-boot",
        staging_nonce=nonce,
    )
    request_path = staging / "request.json"
    result_path = staging / "result.json"
    write_result_json(request_path, request)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            PROBE_REQUEST_FLAG,
            str(request_path),
            PROBE_RESULT_FLAG,
            str(result_path),
            "--extension-probe-staging",
            str(staging),
            "--extension-probe-staging-nonce",
            nonce,
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == ManagerExitCode.SUCCESS
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["components"] == ["media"]


def test_probe_argv_flags_are_wired_on_the_launcher():
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "allow_abbrev=False" in text
    assert "add_mutually_exclusive_group" in text
    for flag in PROBE_ARGV_FLAGS:
        assert flag in text
    gui_import = "from mf4_analyzer.app import main"
    assert gui_import in text
    assert text.index("if args.pyxcp_import_probe_child") < text.index(gui_import)
    assert text.index("if args.a2l_probe_child") < text.index(gui_import)


def test_launcher_pyxcp_child_does_not_bootstrap_or_start_gui(monkeypatch):
    calls: list[str] = []
    acquisition = ModuleType("mf4_analyzer.acquisition_capture.runtime_smoke")
    acquisition.run_import_probe_child = lambda: calls.append("pyxcp") or 0
    fake_app = ModuleType("mf4_analyzer.app")
    fake_app.bootstrap_extension_runtime = lambda **_k: calls.append("boot")
    fake_app.main = lambda: calls.append("gui") or None
    monkeypatch.setitem(
        sys.modules, "mf4_analyzer.acquisition_capture.runtime_smoke", acquisition
    )
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setattr(sys, "argv", ["TraceLab.exe", "--pyxcp-import-probe-child"])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 0
    assert calls == ["pyxcp"]


def test_launcher_importer_bootstraps_before_runtime_smoke(tmp_path, monkeypatch):
    calls: list[str] = []
    importer = ModuleType("mf4_analyzer.io.importer_runtime_smoke")
    importer.run = lambda *_a, **_k: calls.append("importer") or 0
    fake_app = ModuleType("mf4_analyzer.app")
    fake_app.bootstrap_extension_runtime = lambda **_k: calls.append("boot")
    fake_app.main = lambda: calls.append("gui") or None
    monkeypatch.setitem(sys.modules, "mf4_analyzer.io.importer_runtime_smoke", importer)
    monkeypatch.setitem(sys.modules, "mf4_analyzer.app", fake_app)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "TraceLab.exe",
            "--importer-runtime-smoke",
            "--import-path",
            str(tmp_path / "a.mat"),
            "--json",
            str(tmp_path / "out.json"),
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(LAUNCHER), run_name="__main__")
    assert stopped.value.code == 0
    assert calls == ["boot", "importer"]
