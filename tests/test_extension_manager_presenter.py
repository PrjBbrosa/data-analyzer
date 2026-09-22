"""Tk-free presenter tests for the extension manager."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from mf4_analyzer.app_meta import APP_VERSION
from mf4_analyzer.extensions.contract import ReasonCode
from mf4_analyzer.extensions.runtime import STATUS_NOT_INSTALLED, STATUS_READY
from mf4_analyzer.ui.command_registry import CommandId, metadata_for
from mf4_analyzer.ui.main_window.command_coordinator import (
    current_app_root,
    extension_import_offers_manager,
    extension_manager_argv,
)
from tools.extension_installer import build_parser
from tools.extension_manager.app import (
    MANAGER_VERSION,
    ManagerPresenter,
    sanitize_log_text,
)
from tools.extension_manager.transaction import TransactionResult


@dataclass
class FakeAvailability:
    component: str
    status: str
    reason_code: str | None = None


@dataclass
class FakeSnapshot:
    components: dict = field(default_factory=dict)
    app_root: Path | None = None


@dataclass
class FakeRepoSnapshot:
    change_authorized: bool = False
    installer_update_authorized: bool = False
    qualification_reason: str | None = None
    manager_status: object | None = None
    catalog: dict | None = None


class FakeEngine:
    def __init__(self) -> None:
        self.calls = []

    def install(self, packages, hooks=None):
        self.calls.append(("install", list(packages)))
        return TransactionResult("committed", "txn-1", "installed")

    def uninstall(self, components, hooks=None):
        self.calls.append(("uninstall", list(components)))
        return TransactionResult("committed", "txn-2", "uninstalled")

    def recover(self):
        self.calls.append(("recover", None))
        return TransactionResult("committed", "txn-3", "recovered")

    def install_from_repository(self, repository, components, hooks=None):
        self.calls.append(("install_from_repository", list(components)))
        return TransactionResult("committed", "txn-4", "installed")


class FakeRepository:
    def __init__(self, refresh, dest: Path | None = None) -> None:
        self._refresh = refresh
        self.dest = dest
        self.downloaded = False

    def refresh(self, *, require_fresh: bool = True):
        return self._refresh

    def download_manager_installer(self, app_root, cancel_event=None):
        self.downloaded = True
        assert self.dest is not None
        self.dest.parent.mkdir(parents=True, exist_ok=True)
        self.dest.write_bytes(b"installer")
        return self.dest


def _presenter(tmp_path: Path, **kwargs) -> ManagerPresenter:
    snapshot = kwargs.pop(
        "snapshot",
        FakeSnapshot(
            components={
                "media": FakeAvailability(
                    "media", STATUS_NOT_INSTALLED, ReasonCode.COMPONENT_MISSING
                ),
                "matlab": FakeAvailability(
                    "matlab", STATUS_READY, None
                ),
            }
        ),
    )
    return ManagerPresenter(
        tmp_path,
        engine=kwargs.pop("engine", FakeEngine()),
        repository=kwargs.pop("repository", None),
        runtime_loader=lambda *args, **kw: snapshot,
        **kwargs,
    )


def test_command_id_is_manage_extensions():
    meta = metadata_for(CommandId.MANAGE_EXTENSIONS)
    assert CommandId.MANAGE_EXTENSIONS.value == "manage_extensions"
    assert meta.label == "扩展管理…"
    assert "扩展管理器" in meta.help_text


def test_header_uses_readonly_app_version_and_hides_abi(tmp_path: Path):
    presenter = _presenter(tmp_path)
    header = presenter.header()
    assert header.app_version == APP_VERSION
    assert header.manager_version == MANAGER_VERSION
    assert "ABI" not in header.banner
    assert "hash" not in header.banner.lower()
    assert str(tmp_path.resolve()) == header.app_root


def test_rows_consume_runtime_status_without_widget_rules(tmp_path: Path):
    presenter = _presenter(tmp_path)
    rows = {row.component: row for row in presenter.component_rows()}
    assert rows["media"].status_label == "未安装"
    assert rows["matlab"].status_label == "已安装"
    assert rows["media"].actions == ()
    assert "HEAD" in rows["matlab"].purpose or "hdf" in rows["matlab"].purpose.lower()


def test_authorized_refresh_enables_install_action(tmp_path: Path):
    refresh = SimpleNamespace(
        ok=True,
        reason_code=None,
        manager_status=SimpleNamespace(
            latest_manager_version="1.2.0",
            help_page="https://example.test/help",
        ),
        catalog={
            "packages": [
                {"component": "media", "package_revision": 3, "length": 2048},
            ]
        },
        snapshot=FakeRepoSnapshot(change_authorized=True),
    )
    presenter = _presenter(tmp_path, repository=FakeRepository(refresh))
    presenter.check_updates()
    media = next(row for row in presenter.component_rows() if row.component == "media")
    assert "install" in media.actions
    assert media.download_size.endswith("KB")
    assert media.version == "3"


def test_check_updates_splits_manager_and_components(tmp_path: Path):
    refresh = SimpleNamespace(
        ok=True,
        reason_code=None,
        manager_status=SimpleNamespace(latest_manager_version="1.2.0", help_page=""),
        catalog={"packages": [{"component": "media", "package_revision": 3, "length": 16}]},
        snapshot=FakeRepoSnapshot(change_authorized=True),
    )
    view = _presenter(tmp_path, repository=FakeRepository(refresh)).check_updates()
    blob = " ".join((view.manager_message, *view.component_messages))
    assert "软件过期" not in blob
    assert "扩展管理器有新版本 1.2.0" in view.manager_message
    assert any("音视频" in item for item in view.component_messages)
    assert any("MATLAB" in item for item in view.component_messages)


def test_plan_requires_close_and_does_not_kill(tmp_path: Path):
    plan = _presenter(tmp_path).plan("install", ["media"], download_size="2.0 KB")
    assert plan.requires_close
    assert "不会结束" in plan.close_message
    assert plan.download_cancelable
    assert plan.commit_blocks_cancel


def test_cancel_rejected_in_commit_phase(tmp_path: Path):
    presenter = _presenter(tmp_path)
    presenter.note_phase("download")
    accepted = presenter.request_cancel()
    assert accepted.accepted
    presenter.reset_cancel()
    presenter.note_phase("commit")
    blocked = presenter.request_cancel()
    assert not blocked.accepted
    assert "无法取消" in blocked.message


def test_error_view_has_stage_next_step_and_redacts_tokens(tmp_path: Path):
    presenter = _presenter(tmp_path)

    class Running(Exception):
        reason_code = ReasonCode.APP_RUNNING

        def __str__(self) -> str:
            return "Authorization: secret-token"

    view = presenter.result_to_error(Running(), stage="prepared")
    assert view is not None
    assert view.stage == "prepared"
    assert view.reason_code == ReasonCode.APP_RUNNING
    assert "不会结束" in view.next_step
    assert "secret-token" not in view.message
    assert "manager-" in Path(view.log_path).name
    assert "<redacted>" in sanitize_log_text("token=abc123")


def test_manager_update_stays_in_isolated_cache(tmp_path: Path):
    dest = tmp_path / "extensions" / "cache" / "manager-updates" / "installer-1.2.0.exe"
    refresh = SimpleNamespace(
        ok=True,
        reason_code=None,
        manager_status=SimpleNamespace(latest_manager_version="1.2.0", help_page=""),
        catalog={"packages": []},
        snapshot=FakeRepoSnapshot(
            change_authorized=False, installer_update_authorized=True
        ),
    )
    presenter = _presenter(tmp_path, repository=FakeRepository(refresh, dest=dest))
    presenter.check_updates()
    result = presenter.download_manager_update()
    assert getattr(result, "path") == str(dest)
    assert dest.resolve() != (tmp_path / "installer.exe").resolve()
    assert "不要在运行中覆盖" in result.replace_message


def test_local_install_rejects_bare_zip(tmp_path: Path):
    view = _presenter(tmp_path).run_local_install(str(tmp_path / "random.zip"))
    assert view.reason_code == ReasonCode.VERIFICATION_FAILED
    assert "离线" in view.message or "离线" in view.next_step or "受信" in view.message


def test_launch_argv_uses_script_in_source_tree(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    argv = extension_manager_argv(
        tmp_path,
        frozen=False,
        executable=Path("/usr/bin/python3"),
        repo_root=repo,
    )
    assert argv is not None
    assert argv[1].endswith("tools/extension_installer.py")
    assert "--app-root" in argv
    missing = extension_manager_argv(
        tmp_path,
        frozen=True,
        executable=tmp_path / "TraceLabAnalyzer.exe",
    )
    assert missing is None
    assert current_app_root(frozen=True, executable=tmp_path / "TraceLabAnalyzer.exe") == tmp_path


def test_import_reason_code_offers_manager_command():
    class Missing(Exception):
        reason_code = ReasonCode.COMPONENT_MISSING

    assert extension_import_offers_manager(Missing())
    assert not extension_import_offers_manager(ImportError("python-can 未安装"))


def test_installer_entry_parser_accepts_app_root():
    args = build_parser().parse_args(["--app-root", "/tmp/TraceLab"])
    assert args.app_root == "/tmp/TraceLab"
