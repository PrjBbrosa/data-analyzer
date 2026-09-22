"""Tk presenter for the TraceLab extension manager.

Widgets only project engine / repository / runtime results. Qualification,
locking, and package selection stay in those owners. Tk is imported lazily so
presenter tests do not need a display.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys
import threading
from typing import Any, Callable, Mapping, Sequence

from mf4_analyzer.app_meta import APP_VERSION
from mf4_analyzer.extensions.contract import (
    OFFICIAL_COMPONENTS,
    ReasonCode,
    compare_semver,
)
from mf4_analyzer.extensions.runtime import (
    STATUS_CORRUPT,
    STATUS_INCOMPATIBLE,
    STATUS_NOT_INSTALLED,
    STATUS_READY,
    STATUS_REPAIR_REQUIRED,
    STATUS_REVOKED,
    load_runtime,
)
from tools.extension_manager.engine import InstallEngine
from tools.extension_manager.transaction import CANCELABLE_STAGES, TransactionResult

MANAGER_VERSION = "1.0.0"
WRITE_ACTIONS = frozenset(
    {"install", "update", "uninstall", "repair", "install_local"}
)
COMMIT_PHASES = frozenset({"publish", "commit", "committed"})
_TOKEN_RE = re.compile(
    r"(?i)(authorization|token|bearer|api[_-]?key)\s*[:=]\s*\S+"
)

COMPONENT_COPY = {
    "media": ("音视频", "读取 WAV / MP4 等音视频文件"),
    "matlab": ("MATLAB", "读取传统 MAT 与 v7.3 MAT（不是 HEAD 的 .hdf）"),
}

STATUS_LABELS = {
    STATUS_NOT_INSTALLED: "未安装",
    STATUS_READY: "已安装",
    STATUS_INCOMPATIBLE: "不兼容",
    STATUS_CORRUPT: "需修复",
    STATUS_REPAIR_REQUIRED: "需修复",
    STATUS_REVOKED: "需修复",
}

_NEXT_STEP = {
    ReasonCode.COMPONENT_MISSING: "在扩展管理器中安装对应组件。",
    ReasonCode.COMPONENT_INCOMPATIBLE: "安装与当前主程序匹配的扩展，不要把它当成必须更新安装器。",
    ReasonCode.COMPONENT_CORRUPT: "使用「修复」重新安装该组件。",
    ReasonCode.MANAGER_TOO_OLD: "先下载新版扩展管理器，关闭本窗口后再替换根目录文件。",
    ReasonCode.PROTOCOL_UNSUPPORTED: "下载仍受支持的扩展管理器后再试。",
    ReasonCode.NO_COMPATIBLE_PACKAGE: "目前没有适配此主程序版本的扩展包。",
    ReasonCode.CORE_INCONSISTENT: "确认目标目录是完整的 TraceLab 安装后再试。",
    ReasonCode.APP_RUNNING: "请在 TraceLab 里保存并退出，再回来完成安装。管理器不会结束该程序。",
    ReasonCode.UNSUPPORTED_FILESYSTEM: "把 TraceLab 复制到本地可写磁盘后再安装。",
    ReasonCode.VERIFICATION_FAILED: "丢弃这次下载，改用官方包或有效离线集合后重试。",
    ReasonCode.PROBE_FAILED: "查看本次日志后修复或重装该组件。",
    ReasonCode.TRANSACTION_RECOVERY_REQUIRED: "使用「修复」恢复未完成的安装。",
    "NETWORK_CHECK_FAILED": "检查网络后点「检查更新」，或改用有效离线包。",
}


def sanitize_log_text(text: str) -> str:
    return _TOKEN_RE.sub(r"\1=<redacted>", str(text))


def format_download_size(length: int | None) -> str:
    if length is None or length < 0:
        return "—"
    if length < 1024:
        return f"{length} B"
    if length < 1024 * 1024:
        return f"{length / 1024:.1f} KB"
    return f"{length / (1024 * 1024):.1f} MB"


def manager_log_path(app_root: Path, transaction_id: str = "") -> Path:
    name = f"manager-{transaction_id or 'session'}.log"
    return Path(app_root) / "extensions" / "logs" / name


def default_app_root(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    cwd = Path.cwd().resolve()
    if (cwd / "core.json").is_file() or (cwd / "TraceLabAnalyzer.exe").is_file():
        return cwd
    return Path(sys.executable).resolve().parent


def resolve_help_page(refresh: Any) -> str:
    status = getattr(refresh, "manager_status", None) if refresh is not None else None
    if status is None:
        return ""
    if hasattr(status, "help_page"):
        return str(status.help_page or "")
    if isinstance(status, Mapping):
        return str(status.get("help_page") or "")
    return ""


@dataclass(frozen=True)
class HeaderView:
    app_root: str
    app_version: str
    manager_version: str
    banner: str
    status_line: str
    write_allowed: bool
    installer_update_allowed: bool
    qualification_reason: str | None = None


@dataclass(frozen=True)
class ComponentRow:
    component: str
    name: str
    purpose: str
    status: str
    status_label: str
    version: str
    download_size: str
    actions: tuple[str, ...]
    reason_code: str | None = None


@dataclass(frozen=True)
class PlanView:
    action: str
    components: tuple[str, ...]
    summary: str
    requires_close: bool
    close_message: str
    download_cancelable: bool
    commit_blocks_cancel: bool


@dataclass(frozen=True)
class UpdateCheckView:
    manager_message: str
    component_messages: tuple[str, ...]
    check_failed: str | None = None
    latest_manager_version: str = ""
    help_page: str = ""


@dataclass(frozen=True)
class ErrorView:
    stage: str
    reason_code: str | None
    message: str
    next_step: str
    log_path: str


@dataclass(frozen=True)
class ManagerUpdateView:
    version: str
    path: str
    replace_message: str


@dataclass(frozen=True)
class CancelDecision:
    accepted: bool
    message: str


def actions_for_status(
    status: str,
    *,
    write_allowed: bool,
    has_update: bool,
) -> tuple[str, ...]:
    if not write_allowed:
        return ()
    if status == STATUS_NOT_INSTALLED:
        return ("install", "install_local")
    if status == STATUS_READY:
        actions = ["uninstall"]
        if has_update:
            actions.insert(0, "update")
        return tuple(actions)
    if status in {STATUS_CORRUPT, STATUS_REPAIR_REQUIRED, STATUS_REVOKED}:
        return ("repair", "install_local")
    if status == STATUS_INCOMPATIBLE:
        return ("install", "install_local")
    return ()


def interpret_failure(
    *,
    stage: str,
    reason_code: str | None,
    detail: str,
    log_path: Path,
) -> ErrorView:
    code = str(reason_code) if reason_code else None
    next_step = _NEXT_STEP.get(code or "", "查看本次日志后按提示重试。")
    if code == ReasonCode.APP_RUNNING:
        message = "目标程序仍在运行。"
    elif code:
        message = f"失败阶段：{stage}（{code}）"
    else:
        message = f"失败阶段：{stage}"
    if detail:
        message = f"{message}\n{sanitize_log_text(detail)}"
    return ErrorView(
        stage=stage,
        reason_code=code,
        message=message,
        next_step=next_step,
        log_path=str(log_path),
    )


def plan_for_action(
    action: str,
    components: Sequence[str],
    *,
    download_size: str = "—",
) -> PlanView:
    names = tuple(components)
    label = {
        "install": "安装",
        "update": "更新",
        "uninstall": "卸载",
        "repair": "修复",
        "install_local": "从本地包安装",
    }.get(action, action)
    joined = "、".join(COMPONENT_COPY.get(name, (name, name))[0] for name in names) or "所选组件"
    requires_close = action in WRITE_ACTIONS
    summary = f"将{label}：{joined}（下载 {download_size}）。"
    close_message = (
        "需要先关闭 TraceLab。未保存内容请在主程序里处理；管理器不会结束该程序。"
        if requires_close
        else "查看和下载不必关闭主程序。"
    )
    return PlanView(
        action=action,
        components=names,
        summary=summary,
        requires_close=requires_close,
        close_message=close_message,
        download_cancelable=True,
        commit_blocks_cancel=True,
    )


class ManagerPresenter:
    """Pure adapter over engine / repository / runtime snapshots."""

    def __init__(
        self,
        app_root: str | Path,
        *,
        engine: InstallEngine | None = None,
        repository: Any | None = None,
        runtime_loader: Callable[..., Any] = load_runtime,
        app_version: str = APP_VERSION,
        manager_version: str = MANAGER_VERSION,
    ) -> None:
        self.app_root = Path(app_root).expanduser().resolve()
        self.engine = engine or InstallEngine(
            self.app_root, manager_version=manager_version
        )
        self.repository = repository
        self.runtime_loader = runtime_loader
        self.app_version = app_version
        self.manager_version = manager_version
        self._phase = "idle"
        self._cancel = threading.Event()
        self._last_refresh: Any | None = None

    @property
    def phase(self) -> str:
        return self._phase

    def note_phase(self, phase: str) -> None:
        self._phase = str(phase)

    def can_cancel(self) -> bool:
        return self._phase in {"idle", "download", *CANCELABLE_STAGES}

    def request_cancel(self) -> CancelDecision:
        if self._phase in COMMIT_PHASES or not self.can_cancel():
            return CancelDecision(False, "正在完成安装，无法取消。")
        self._cancel.set()
        return CancelDecision(True, "已请求取消。下载尚未提交，现有组件不变。")

    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    def reset_cancel(self) -> None:
        self._cancel.clear()

    def log_path_for(self, transaction_id: str = "") -> Path:
        path = manager_log_path(self.app_root, transaction_id or "session")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write_log(self, message: str, *, transaction_id: str = "") -> Path:
        path = self.log_path_for(transaction_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = sanitize_log_text(message).rstrip() + "\n"
        path.open("a", encoding="utf-8").write(line)
        return path

    def load_local_snapshot(self) -> Any:
        return self.runtime_loader(self.app_root, acquire_lease=False)

    def header(self, snapshot: Any | None = None) -> HeaderView:
        snapshot = snapshot if snapshot is not None else self.load_local_snapshot()
        refresh = self._last_refresh
        write_allowed = False
        installer_update_allowed = False
        qualification = None
        banner = ""
        status_line = "显示本地状态。在线检查只在打开本窗口或点击「检查更新」时进行。"
        if refresh is not None:
            snap = getattr(refresh, "snapshot", None)
            if snap is not None:
                write_allowed = bool(getattr(snap, "change_authorized", False))
                installer_update_allowed = bool(
                    getattr(snap, "installer_update_authorized", False)
                )
                qualification = getattr(snap, "qualification_reason", None)
            status = getattr(refresh, "manager_status", None)
            latest = _status_latest(status)
            if latest and compare_semver(self.manager_version, latest) < 0:
                if qualification == ReasonCode.MANAGER_TOO_OLD:
                    banner = f"需要扩展管理器 ≥ {latest}"
                else:
                    banner = "扩展管理器有更新"
            if not getattr(refresh, "ok", False):
                reason = getattr(refresh, "reason_code", None)
                if reason == ReasonCode.MANAGER_TOO_OLD:
                    status_line = banner or "当前管理器过旧，不能更改组件。"
                elif reason:
                    status_line = "无法检查更新，仍显示本地真实状态。"
                else:
                    status_line = "无法检查更新，仍显示本地真实状态。"
        return HeaderView(
            app_root=str(self.app_root),
            app_version=self.app_version,
            manager_version=self.manager_version,
            banner=banner,
            status_line=status_line,
            write_allowed=write_allowed,
            installer_update_allowed=installer_update_allowed,
            qualification_reason=qualification,
        )

    def component_rows(self, snapshot: Any | None = None) -> tuple[ComponentRow, ...]:
        snapshot = snapshot if snapshot is not None else self.load_local_snapshot()
        catalog = None
        write_allowed = False
        if self._last_refresh is not None:
            catalog = getattr(self._last_refresh, "catalog", None)
            snap = getattr(self._last_refresh, "snapshot", None)
            if snap is not None:
                write_allowed = bool(getattr(snap, "change_authorized", False))
        packages = _catalog_packages(catalog)
        rows = []
        components = getattr(snapshot, "components", {}) or {}
        for name in sorted(OFFICIAL_COMPONENTS):
            availability = components.get(name)
            status = getattr(availability, "status", STATUS_NOT_INSTALLED)
            reason = getattr(availability, "reason_code", ReasonCode.COMPONENT_MISSING)
            package = packages.get(name)
            version = "—"
            size = "—"
            if package is not None:
                revision = package.get("package_revision")
                version = str(revision) if revision is not None else "—"
                size = format_download_size(package.get("length"))
            has_update = status == STATUS_READY and package is not None
            label, purpose = COMPONENT_COPY.get(name, (name, name))
            rows.append(
                ComponentRow(
                    component=name,
                    name=label,
                    purpose=purpose,
                    status=status,
                    status_label=STATUS_LABELS.get(status, status),
                    version=version,
                    download_size=size,
                    actions=actions_for_status(
                        status, write_allowed=write_allowed, has_update=has_update
                    ),
                    reason_code=reason,
                )
            )
        return tuple(rows)

    def check_updates(self) -> UpdateCheckView:
        refresh = self._refresh_repository()
        if refresh is None:
            return UpdateCheckView(
                manager_message="无法检查扩展管理器更新（本机没有在线仓库客户端）。",
                component_messages=(),
                check_failed="无法检查更新",
            )
        self._last_refresh = refresh
        if not getattr(refresh, "ok", False) and getattr(refresh, "reason_code", None) not in {
            ReasonCode.MANAGER_TOO_OLD,
            None,
        }:
            return UpdateCheckView(
                manager_message="无法检查扩展管理器更新。",
                component_messages=("无法检查组件更新。",),
                check_failed="无法检查更新",
                help_page=resolve_help_page(refresh),
            )
        status = getattr(refresh, "manager_status", None)
        latest = _status_latest(status)
        if latest and compare_semver(self.manager_version, latest) < 0:
            manager_message = f"扩展管理器有新版本 {latest}（当前 {self.manager_version}）。"
        else:
            manager_message = f"扩展管理器已是可用版本（{self.manager_version}）。"
        component_messages = []
        packages = _catalog_packages(getattr(refresh, "catalog", None))
        snapshot = self.load_local_snapshot()
        components = getattr(snapshot, "components", {}) or {}
        for name in sorted(OFFICIAL_COMPONENTS):
            label = COMPONENT_COPY.get(name, (name, name))[0]
            availability = components.get(name)
            status_name = getattr(availability, "status", STATUS_NOT_INSTALLED)
            if name not in packages:
                component_messages.append(f"{label}：暂无适配此运行时的扩展。")
                continue
            if status_name == STATUS_NOT_INSTALLED:
                component_messages.append(f"{label}：可安装。")
            elif status_name == STATUS_READY:
                component_messages.append(f"{label}：已安装，当前包仍可用。")
            elif status_name == STATUS_INCOMPATIBLE:
                component_messages.append(f"{label}：需要匹配此版本的扩展，不是必须更新安装器。")
            else:
                component_messages.append(
                    f"{label}：{STATUS_LABELS.get(status_name, status_name)}。"
                )
        failed = None
        if getattr(refresh, "reason_code", None) == ReasonCode.MANAGER_TOO_OLD:
            failed = None
        return UpdateCheckView(
            manager_message=manager_message,
            component_messages=tuple(component_messages),
            check_failed=failed,
            latest_manager_version=latest,
            help_page=resolve_help_page(refresh),
        )

    def plan(self, action: str, components: Sequence[str], *, download_size: str = "—") -> PlanView:
        return plan_for_action(action, components, download_size=download_size)

    def result_to_error(
        self,
        result: TransactionResult | BaseException,
        *,
        stage: str | None = None,
    ) -> ErrorView | None:
        if isinstance(result, TransactionResult):
            if result.outcome in {"installed", "uninstalled", "recovered"}:
                return None
            if result.outcome == "cancelled":
                return interpret_failure(
                    stage=result.stage,
                    reason_code=None,
                    detail="用户取消。现有组件未改。",
                    log_path=self.log_path_for(result.transaction_id),
                )
            path = self.log_path_for(result.transaction_id)
            self.write_log(
                f"stage={result.stage} outcome={result.outcome} reason={result.reason_code}",
                transaction_id=result.transaction_id,
            )
            return interpret_failure(
                stage=result.stage,
                reason_code=result.reason_code,
                detail=result.outcome,
                log_path=path,
            )
        reason = getattr(result, "reason_code", None)
        path = self.log_path_for()
        self.write_log(f"stage={stage or self._phase} error={result!r}")
        return interpret_failure(
            stage=stage or self._phase,
            reason_code=reason,
            detail=str(result),
            log_path=path,
        )

    def download_manager_update(self) -> ManagerUpdateView | ErrorView:
        repo = self.repository
        if repo is None:
            help_page = resolve_help_page(self._last_refresh)
            extra = f" 固定说明：{help_page}" if help_page else ""
            return interpret_failure(
                stage="download",
                reason_code="NETWORK_CHECK_FAILED",
                detail="当前没有可用的在线信任状态，不能下载未知地址的安装器。" + extra,
                log_path=self.log_path_for(),
            )
        self.note_phase("download")
        self.reset_cancel()
        try:
            dest = Path(
                repo.download_manager_installer(
                    self.app_root, cancel_event=self._cancel
                )
            )
        except BaseException as exc:
            self.note_phase("idle")
            return self.result_to_error(exc, stage="download")
        self.note_phase("idle")
        root_installer = (self.app_root / "installer.exe").resolve()
        if dest.resolve() == root_installer:
            return interpret_failure(
                stage="download",
                reason_code=ReasonCode.VERIFICATION_FAILED,
                detail="拒绝覆盖正在运行的安装器。",
                log_path=self.log_path_for(),
            )
        version = ""
        if self._last_refresh is not None:
            version = _status_latest(getattr(self._last_refresh, "manager_status", None))
        return ManagerUpdateView(
            version=version,
            path=str(dest),
            replace_message=(
                f"已下载扩展管理器 {version or dest.name} 到：\n{dest}\n\n"
                "请关闭本窗口后，用该文件替换根目录的 installer.exe。"
                "不要在运行中覆盖当前管理器。"
            ),
        )

    def run_engine(
        self,
        action: str,
        *,
        packages: Sequence[Any] = (),
        components: Sequence[str] = (),
        hooks: Any | None = None,
    ) -> TransactionResult:
        self.reset_cancel()
        extra = hooks
        if extra is None:
            from tools.extension_manager.transaction import TransactionHooks

            extra = TransactionHooks(cancel_requested=self.cancel_requested)
        if action == "uninstall":
            self.note_phase("prepared")
            result = self.engine.uninstall(components, hooks=extra)
        elif action == "repair":
            self.note_phase("prepared")
            result = self.engine.recover()
        elif action == "install_from_repository":
            self.note_phase("download")
            result = self.engine.install_from_repository(
                self.repository, components, hooks=extra
            )
        else:
            self.note_phase("prepared")
            result = self.engine.install(packages, hooks=extra)
        self.note_phase(result.stage)
        return result

    def _refresh_repository(self) -> Any | None:
        repo = self.repository
        if repo is None:
            repo = self._try_make_repository()
            self.repository = repo
        if repo is None:
            return None
        return repo.refresh()

    def _try_make_repository(self) -> Any | None:
        # Production freeze supplies a bound repository. Tests inject fakes.
        # Never import TUF here so the app venv can load this presenter.
        return None

    def run_local_install(self, path: str) -> TransactionResult | ErrorView:
        loader = getattr(self.repository, "load_offline_bundle", None)
        if not callable(loader):
            return interpret_failure(
                stage="prepared",
                reason_code=ReasonCode.VERIFICATION_FAILED,
                detail="从本地安装需要附带受信元数据的官方离线集合，不能导入任意 ZIP 或 pip 包。",
                log_path=self.log_path_for(),
            )
        packages = loader(path)
        return self.run_engine("install", packages=packages)


def _status_latest(status: Any) -> str:
    if status is None:
        return ""
    if hasattr(status, "latest_manager_version"):
        return str(status.latest_manager_version or "")
    if isinstance(status, Mapping):
        return str(status.get("latest_manager_version") or "")
    return ""


def _catalog_packages(catalog: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(catalog, Mapping):
        return {}
    found: dict[str, Mapping[str, Any]] = {}
    for item in catalog.get("packages") or ():
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("component") or "")
        if name:
            found[name] = item
    return found


def run_app(
    app_root: str | Path | None = None,
    *,
    manager_version: str | None = None,
    presenter: ManagerPresenter | None = None,
) -> int:
    """Create the Tk window. Foreground DPI / CJK on this host is UNVERIFIED."""

    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root_dir = default_app_root(app_root)
    view = presenter or ManagerPresenter(
        root_dir, manager_version=manager_version or MANAGER_VERSION
    )

    class ManagerWindow(tk.Tk):
        def __init__(self) -> None:
            super().__init__()
            self.title("TraceLab 扩展管理器")
            self.geometry("760x480")
            self._rows: dict[str, ComponentRow] = {}
            self._busy = False
            self._build()
            self.reload()

        def _build(self) -> None:
            pad = {"padx": 12, "pady": 4}
            self.header = tk.Label(self, justify="left", anchor="w")
            self.header.pack(fill="x", **pad)
            self.banner = tk.Label(self, fg="#8a5a00", justify="left", anchor="w")
            self.banner.pack(fill="x", **pad)
            columns = ("name", "purpose", "status", "version", "size")
            self.tree = ttk.Treeview(self, columns=columns, show="headings", height=8)
            headings = {
                "name": "名称",
                "purpose": "用途",
                "status": "状态",
                "version": "版本",
                "size": "下载大小",
            }
            for key, title in headings.items():
                self.tree.heading(key, text=title)
                self.tree.column(key, width=120 if key != "purpose" else 240)
            self.tree.pack(fill="both", expand=True, padx=12, pady=8)
            buttons = tk.Frame(self)
            buttons.pack(fill="x", padx=12, pady=4)
            specs = (
                ("install", "安装"),
                ("update", "更新"),
                ("uninstall", "卸载"),
                ("repair", "修复"),
                ("install_local", "从本地包安装"),
                ("check", "检查更新"),
                ("manager_update", "更新管理器"),
            )
            self._buttons: dict[str, tk.Button] = {}
            for action, label in specs:
                btn = tk.Button(
                    buttons,
                    text=label,
                    command=getattr(self, f"_on_{action}"),
                )
                btn.pack(side="left", padx=4)
                self._buttons[action] = btn
            self.cancel_btn = tk.Button(buttons, text="取消下载", command=self._on_cancel)
            self.cancel_btn.pack(side="right", padx=4)
            self.status = tk.Label(self, justify="left", anchor="w")
            self.status.pack(fill="x", **pad)

        def reload(self) -> None:
            try:
                snapshot = view.load_local_snapshot()
            except Exception as exc:
                error = view.result_to_error(exc, stage="load")
                self._show_error(error)
                return
            header = view.header(snapshot)
            self.header.configure(
                text=(
                    f"目标目录：{header.app_root}\n"
                    f"主程序版本：{header.app_version}    "
                    f"管理器版本：{header.manager_version}"
                )
            )
            self.banner.configure(text=header.banner)
            self.status.configure(text=header.status_line)
            for item in self.tree.get_children():
                self.tree.delete(item)
            self._rows = {}
            for row in view.component_rows(snapshot):
                self._rows[row.component] = row
                self.tree.insert(
                    "",
                    "end",
                    iid=row.component,
                    values=(
                        row.name,
                        row.purpose,
                        row.status_label,
                        row.version,
                        row.download_size,
                    ),
                )
            self._buttons["manager_update"].configure(
                state="normal" if header.installer_update_allowed or header.banner else "normal"
            )

        def _selected(self) -> str | None:
            choice = self.tree.selection()
            return choice[0] if choice else None

        def _on_check(self) -> None:
            result = view.check_updates()
            parts = [result.manager_message, *result.component_messages]
            if result.check_failed:
                parts.insert(0, result.check_failed)
            messagebox.showinfo("检查更新", "\n".join(part for part in parts if part))
            self.reload()

        def _on_install(self) -> None:
            self._run_write("install")

        def _on_update(self) -> None:
            self._run_write("update")

        def _on_uninstall(self) -> None:
            self._run_write("uninstall")

        def _on_repair(self) -> None:
            self._run_write("repair")

        def _on_install_local(self) -> None:
            path = filedialog.askopenfilename(title="选择本地扩展包")
            if not path:
                return
            messagebox.showinfo(
                "从本地包安装",
                "本地安装只接受附带受信元数据的官方离线集合，不能导入任意 pip 包。",
            )
            self._run_write("install_local", detail=path)

        def _on_manager_update(self) -> None:
            result = view.download_manager_update()
            if isinstance(result, ErrorView):
                self._show_error(result)
                return
            messagebox.showinfo("更新管理器", result.replace_message)

        def _on_cancel(self) -> None:
            decision = view.request_cancel()
            self.status.configure(text=decision.message)
            if not decision.accepted:
                messagebox.showinfo("无法取消", decision.message)

        def _run_write(self, action: str, detail: str = "") -> None:
            component = self._selected()
            if action != "repair" and not component:
                messagebox.showinfo("扩展管理", "请先选择一个组件。")
                return
            row = self._rows.get(component or "")
            if row is not None and action not in row.actions and action != "repair":
                messagebox.showinfo(
                    "扩展管理",
                    "当前不能执行该操作。请先检查更新，或按顶部说明处理管理器版本。",
                )
                return
            plan = view.plan(
                action,
                (component,) if component else (),
                download_size=row.download_size if row else "—",
            )
            text = (
                f"{plan.summary}\n\n{plan.close_message}\n\n"
                "下载过程可以取消；写入配置的最后一步开始后将无法取消。"
            )
            if not messagebox.askokcancel("确认计划", text):
                return
            self.status.configure(text="正在完成…请勿关闭。")
            try:
                if action == "install_local":
                    result = view.run_local_install(detail)
                elif action in {"install", "update"}:
                    result = view.run_engine(
                        "install_from_repository",
                        components=(component,) if component else (),
                    )
                elif action == "uninstall":
                    result = view.run_engine("uninstall", components=(component,))
                else:
                    result = view.run_engine("repair")
            except Exception as exc:
                self._show_error(view.result_to_error(exc, stage=view.phase))
                return
            if isinstance(result, ErrorView):
                self._show_error(result)
                self.reload()
                return
            error = view.result_to_error(result)
            if error is not None:
                self._show_error(error)
            else:
                messagebox.showinfo("扩展管理", "操作完成。")
            self.reload()

        def _show_error(self, error: ErrorView | None) -> None:
            if error is None:
                return
            messagebox.showerror(
                "扩展管理",
                f"{error.message}\n\n下一步：{error.next_step}\n本次日志：{error.log_path}",
            )
            self.status.configure(text=f"{error.message}  日志：{error.log_path}")

    window = ManagerWindow()
    window.mainloop()
    return 0
