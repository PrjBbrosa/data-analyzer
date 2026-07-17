"""ProjectIOMixin: file load/close and .tlproj save/open for MainWindow."""

import json
from pathlib import Path

from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from ...io import DataLoader, FileData, HAS_ASAMMDF
from ...io.loader import (
    AUDIO_VIDEO_EXTS,
    CSV_LIKE_EXTS,
    format_dropped_channels_notice,
)


AUDIO_VIDEO_GLOB = "*.mp4 *.mov *.mkv *.m4v *.mp3 *.m4a *.aac *.wav *.flac"
CSV_LIKE_GLOB = " ".join(f"*{ext}" for ext in sorted(CSV_LIKE_EXTS))
DATA_FILE_GLOB = f"*.mf4 *.mdf *.blf *.tdms {CSV_LIKE_GLOB} *.xlsx *.xls *.hdf *.wwt *.zfd *.mat {AUDIO_VIDEO_GLOB}"
PROJECT_OR_DATA_FILTER = (
    f"所有支持的文件 ({DATA_FILE_GLOB} *.tlproj);;"
    f"项目 (*.tlproj);;数据文件 ({DATA_FILE_GLOB});;"
    f"音视频文件 ({AUDIO_VIDEO_GLOB})"
)
OPEN_FILES_FILTER = (
    f"所有支持的文件 ({DATA_FILE_GLOB});;"
    f"数据文件 ({DATA_FILE_GLOB});;"
    f"音视频文件 ({AUDIO_VIDEO_GLOB})"
)
AUDIO_VIDEO_FILE_FILTER = f"音视频文件 ({AUDIO_VIDEO_GLOB})"
BLF_DBC_RECENT_SETTINGS_KEY = "blf/recent_dbc_path_sets"
BLF_DBC_RECENT_MAX = 20


class ProjectIOMixin:
    """Domain mixin: data-file load/close and project (.tlproj) IO.

    ``QFileDialog`` is resolved via ``sys.modules`` at call time so the
    smoke-suite ``patch('mf4_analyzer.ui.main_window.QFileDialog.
    getOpenFileNames', ...)`` reaches these call sites (the patch targets
    a class attribute, but the runtime lookup keeps it robust against
    name-rebinding patches too).

    ``open_acquisition_cockpit`` intentionally stays in window.py because
    the cockpit test patches ``main_window.importlib`` at the package
    namespace, which the window module owns.
    """

    def open_files_or_project(self):
        """统一打开入口：文件对话框同时接受数据文件和 .tlproj。"""
        import sys as _sys
        _pkg = _sys.modules.get('mf4_analyzer.ui.main_window')
        _QFileDialog = getattr(_pkg, 'QFileDialog', QFileDialog) if _pkg is not None else QFileDialog
        fps, _ = _QFileDialog.getOpenFileNames(
            self, "打开", "", PROJECT_OR_DATA_FILTER,
        )
        if not fps:
            return
        self._open_paths(fps)

    def _open_paths(self, paths):
        """共享分发：数据文件追加；单个 .tlproj 替换（先确认）；项目+文件先开项目再
        追加；≥2 个项目拒绝。由「打开」菜单和拖放共用，行为零分叉。"""
        from pathlib import Path
        projects = [p for p in paths if Path(p).suffix.lower() == ".tlproj"]
        data_files = [p for p in paths if Path(p).suffix.lower() != ".tlproj"]

        if len(projects) >= 2:
            QMessageBox.warning(self, "无法打开", "一次只能打开一个项目（.tlproj）。")
            return

        if projects:
            if self.files:
                resp = QMessageBox.question(
                    self, "打开项目",
                    f"打开项目将关闭当前 {len(self.files)} 个文件，是否继续？",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if resp != QMessageBox.Yes:
                    return
            self.open_project(projects[0])
            for fp in data_files:
                self._load_one(fp)
            return

        for fp in data_files:
            self._load_one(fp)

    def save_project_via_dialog(self):
        """「保存」handler: overwrite the current .tlproj if one is open,
        otherwise fall back to Save-As."""
        if self._project_path is not None:
            self.save_project(self._project_path)
            return
        self.save_project_as_via_dialog()

    def save_project_as_via_dialog(self):
        """「另存为」handler: always prompt for a new .tlproj path."""
        from pathlib import Path
        from PyQt5.QtWidgets import QFileDialog
        start = str(self._project_path) if self._project_path is not None else ""
        fp, _ = QFileDialog.getSaveFileName(self, "另存为项目", start, "TraceLab 项目 (*.tlproj)")
        if not fp:
            return
        if not fp.lower().endswith(".tlproj"):
            fp = fp + ".tlproj"
        self.save_project(Path(fp))

    def load_files(self):
        import sys as _sys
        _pkg = _sys.modules.get('mf4_analyzer.ui.main_window')
        _QFileDialog = getattr(_pkg, 'QFileDialog', QFileDialog) if _pkg is not None else QFileDialog
        fps, _ = _QFileDialog.getOpenFileNames(
            self, "选择文件", "", OPEN_FILES_FILTER)
        for fp in fps: self._load_one(fp)

    def load_file(self, path) -> None:
        """Public Analyzer handoff for single-file loads.

        Stage 5 of the Acquisition Cockpit plan
        (``docs/analyzer/acquisition/plans/2026-05-15-acquisition-cockpit-ui-implementation.md``)
        wires Cockpit's review modal to this method. Spec §Architecture
        Contract / Analyzer Handoff pins the contract:

        - Public method, accepts ``str | Path``.
        - Thin wrapper around the existing private ``_load_one(fp)`` flow.
        - Cockpit MUST NOT call ``_load_one`` directly.

        This is the only Analyzer-side modification authorized by the
        plan; ``_load_one``'s body stays unchanged.
        """
        self._load_one(str(path))

    def _register_file_data(self, fp, data, chs, units, *,
                            fs=None,
                            source_metadata=None, channel_metadata=None,
                            label_suffix=""):
        fid = f"f{self._fc}"; self._fc += 1
        kwargs = dict(
            source_metadata=source_metadata,
            channel_metadata=channel_metadata,
            label_suffix=label_suffix,
        )
        if fs is not None:
            kwargs["fs"] = fs
        try:
            fd = FileData(fp, data, chs, units, len(self.files), **kwargs)
        except TypeError as exc:
            if fs is None or "fs" not in str(exc):
                raise
            kwargs.pop("fs", None)
            fd = FileData(fp, data, chs, units, len(self.files), **kwargs)
            try:
                fd.rebuild_time_axis(float(fs))
            except Exception:
                fd.fs = float(fs)
        self.files[fid] = fd
        self.navigator.add_file(fid, fd)
        self.canvas_time.invalidate_envelope_cache("file loaded")
        self.canvas_time.invalidate_monotonicity_cache()
        # Unified entry point: also clears analysis_caches for this fid in
        # case the same fid integer was previously used by a now-closed file
        # (问题① fix).
        self._invalidate_all_analysis_caches_for_fid(fid)
        self._refresh_channel_dependent_controls()
        is_audio_source = getattr(fd, "is_audio_source", None)
        try:
            is_audio = bool(is_audio_source()) if callable(is_audio_source) else False
        except Exception:
            is_audio = False
        if is_audio:
            signal_channels = (
                fd.get_signal_channels()
                if hasattr(fd, "get_signal_channels")
                else chs
            )
            if signal_channels:
                apply_audio_default = getattr(
                    self, "_apply_audio_weighting_default", None
                )
                if callable(apply_audio_default):
                    apply_audio_default((fid, signal_channels[0]))
        if fd.time_array is not None and len(fd.time_array):
            current_hi = self.inspector.top.spin_end.maximum()
            new_hi = max(current_hi, fd.time_array[-1])
            self.inspector.top.set_range_limits(0, new_hi)
            if len(self.files) == 1:
                self.inspector.top.spin_end.setValue(fd.time_array[-1])
        return fd

    def _load_one(self, fp, *, blf_dbc_paths=None):
        try:
            self.statusBar.showMessage(f"加载: {fp}");
            QApplication.processEvents()
            p = Path(fp);
            ext = p.suffix.lower()
            if ext in ('.mf4', '.mdf'):
                if not HAS_ASAMMDF: QMessageBox.critical(self, "错误", "asammdf 未安装"); return
                data, chs, units = DataLoader.load_mf4(fp)
            elif ext in ('.xlsx', '.xls'):
                data, chs, units = DataLoader.load_excel(fp)
            elif ext in AUDIO_VIDEO_EXTS:
                data, chs, units, fs, smeta = DataLoader.load_audio_video(fp)
                fd = self._register_file_data(
                    fp, data, chs, units, fs=fs, source_metadata=smeta)
                self._update_info()
                self.statusBar.showMessage(
                    f"✅ 已加载音轨: {p.name} ({len(data)} 采样 @ {fs:.0f} Hz) | 共 {len(self.files)} 文件")
                self.toast(f"已加载音轨 {p.name}", "success")
                return
            elif ext == '.blf':
                dbc_paths = None
                if blf_dbc_paths:
                    dbc_paths = self._validated_blf_dbc_paths(p, blf_dbc_paths)
                if not dbc_paths:
                    dbc_paths = self._resolve_blf_dbc_paths(p)
                if not dbc_paths:
                    self.statusBar.showMessage(f"已取消 BLF: {p.name}")
                    return
                data, chs, units = DataLoader.load_blf(fp, dbc_paths=dbc_paths)
                self._register_file_data(
                    fp, data, chs, units,
                    source_metadata={
                        "source_kind": "blf",
                        "dbc_paths": list(dbc_paths),
                    },
                )
                self._remember_blf_dbc_paths(dbc_paths)
                self._update_info()
                mode = f"DBC×{len(dbc_paths)} 解码"
                self.statusBar.showMessage(
                    f"✅ 已加载 BLF: {p.name} ({len(data)} 行 · {mode}) | 共 {len(self.files)} 文件")
                self.toast(f"已加载 {p.name} · {mode}", "success")
                return
            elif ext == '.tdms':
                data, chs, units = DataLoader.load_tdms(fp)
                self._register_file_data(
                    fp, data, chs, units, source_metadata={"source_kind": "tdms"})
                self._update_info()
                self.statusBar.showMessage(
                    f"✅ 已加载 TDMS: {p.name} ({len(data)} 行) | 共 {len(self.files)} 文件")
                self.toast(f"已加载 TDMS {p.name} · {len(data)} 行", "success")
                return
            elif ext == '.hdf':
                groups = DataLoader.load_hdf(fp)
                for g in groups:
                    self._register_file_data(
                        fp, g["data"], g["channels"], g["units"],
                        source_metadata=g["source_metadata"],
                        channel_metadata=g["channel_metadata"],
                        label_suffix=g["label_suffix"])
                self._update_info()
                self.statusBar.showMessage(
                    f"✅ 已加载: {p.name} → {len(groups)} 组 | 共 {self.navigator.file_list_count()} 个源文件")
                self.toast(f"已加载 {p.name} · {len(groups)} 组", "success")
                # dropped_channels（非 FLOAT32 / 全 NaN）之前只存在 metadata、
                # 用户无从知晓；加载后显式提示一次，别静默少通道。
                dropped = (groups[0]["source_metadata"].get("dropped_channels")
                           if groups else None)
                notice = format_dropped_channels_notice(dropped)
                if notice:
                    self.toast(notice, "warning")
                return
            elif ext == '.asc':
                data, chs, units, fs, smeta = DataLoader.load_ascii(fp)
                self._register_file_data(
                    fp, data, chs, units, fs=fs, source_metadata=smeta)
                self._update_info()
                self.statusBar.showMessage(
                    f"✅ 已加载 ASCII: {p.name} ({len(data)} 行) | 共 {len(self.files)} 文件")
                self.toast(f"已加载 ASCII {p.name} · {len(data)} 行", "success")
                return
            elif ext == '.wwt':
                groups = DataLoader.load_wwt(fp)
                for g in groups:
                    self._register_file_data(
                        fp, g["data"], g["channels"], g["units"],
                        source_metadata=g["source_metadata"],
                        channel_metadata=g["channel_metadata"],
                        label_suffix=g["label_suffix"])
                self._update_info()
                self.statusBar.showMessage(
                    f"✅ 已加载 WWT: {p.name} → {len(groups)} 组 | 共 {self.navigator.file_list_count()} 个源文件")
                self.toast(f"已加载 {p.name} · {len(groups)} 组", "success")
                return
            elif ext == '.zfd':
                groups = DataLoader.load_zfd(fp)
                for g in groups:
                    self._register_file_data(
                        fp, g["data"], g["channels"], g["units"],
                        source_metadata=g["source_metadata"],
                        channel_metadata=g["channel_metadata"],
                        label_suffix=g["label_suffix"])
                self._update_info()
                self.statusBar.showMessage(
                    f"✅ 已加载 ZFD: {p.name} → {len(groups)} 组 | 共 {self.navigator.file_list_count()} 个源文件")
                self.toast(f"已加载 {p.name} · {len(groups)} 组", "success")
                return
            elif ext == '.mat':
                groups = DataLoader.load_mat(fp)
                for g in groups:
                    self._register_file_data(
                        fp, g["data"], g["channels"], g["units"],
                        source_metadata=g["source_metadata"],
                        channel_metadata=g["channel_metadata"],
                        label_suffix=g["label_suffix"])
                self._update_info()
                self.statusBar.showMessage(
                    f"✅ 已加载 MAT: {p.name} → {len(groups)} 组 | 共 {self.navigator.file_list_count()} 个源文件")
                self.toast(f"已加载 {p.name} · {len(groups)} 组", "success")
                return
            else:
                data, chs, units = DataLoader.load_csv(fp)
            fd = self._register_file_data(fp, data, chs, units)
            # User-request 2026-05-20: do NOT auto-select channel[0] on file
            # load. The canvas opens empty; the user picks the channel(s)
            # they want explicitly. Any previously-checked channels on
            # *other* loaded files remain checked and visible — their fids
            # are unaffected by the freshly minted ``fid`` above.
            self._update_info()
            self.statusBar.showMessage(f"✅ 已加载: {p.name} ({len(data)} 行) | 共 {len(self.files)} 文件")
            self.toast(f"已加载 {p.name} · {len(data)} 行", "success")
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

    def _canonical_blf_dbc_paths(self, dbc_paths):
        return tuple(str(Path(p).resolve()) for p in (dbc_paths or []) if p)

    def _blf_dbc_settings(self):
        try:
            from ..inspector_sections._helpers import _preset_settings
            return _preset_settings()
        except Exception:
            return QSettings("MF4Analyzer", "DataAnalyzer")

    def _clean_blf_dbc_history(self, history):
        cleaned = []
        seen = set()
        for paths in history or []:
            key = self._canonical_blf_dbc_paths(paths)
            if not key or key in seen:
                continue
            if not all(Path(p).exists() for p in key):
                continue
            seen.add(key)
            cleaned.append(list(key))
        return cleaned[-BLF_DBC_RECENT_MAX:]

    def _load_recent_blf_dbc_history(self):
        raw = self._blf_dbc_settings().value(BLF_DBC_RECENT_SETTINGS_KEY, "")
        if not raw:
            return []
        if isinstance(raw, (list, tuple)):
            parsed = raw
        else:
            try:
                parsed = json.loads(str(raw))
            except (TypeError, ValueError):
                return []
        history = self._clean_blf_dbc_history(parsed)
        if history != parsed:
            self._save_recent_blf_dbc_history(history)
        return history

    def _save_recent_blf_dbc_history(self, history=None):
        history = self._clean_blf_dbc_history(
            history if history is not None
            else getattr(self, "_blf_dbc_history", [])
        )
        settings = self._blf_dbc_settings()
        settings.setValue(
            BLF_DBC_RECENT_SETTINGS_KEY,
            json.dumps(history, ensure_ascii=False),
        )
        settings.sync()
        return history

    def _remember_blf_dbc_paths(self, dbc_paths):
        key = self._canonical_blf_dbc_paths(dbc_paths)
        if not key:
            return
        history = list(getattr(self, "_blf_dbc_history", []))
        history = [paths for paths in history if tuple(paths) != key]
        history.append(list(key))
        self._blf_dbc_history = self._save_recent_blf_dbc_history(history)

    def _candidate_blf_dbc_paths(self, path):
        candidates = []
        seen = set()

        def add(paths):
            key = self._canonical_blf_dbc_paths(paths)
            if not key or key in seen:
                return
            seen.add(key)
            candidates.append(list(key))

        for paths in reversed(getattr(self, "_blf_dbc_history", [])):
            add(paths)

        nearby = set()
        for pattern in ("*.dbc", "*.DBC"):
            nearby.update(Path(path).parent.glob(pattern))
        for dbc in sorted(nearby, key=lambda p: p.name.lower()):
            add([dbc])
        return candidates

    def _probe_blf_dbc_candidates(self, path):
        candidates = []
        for dbc_paths in self._candidate_blf_dbc_paths(path):
            try:
                probe = DataLoader.probe_blf_dbc(str(path), dbc_paths)
            except ImportError:
                raise
            except ValueError as exc:
                if "BLF 文件没有可读的 CAN 数据帧" in str(exc):
                    raise
                continue
            except Exception:
                continue
            if probe.is_match:
                candidates.append({"paths": list(dbc_paths), "probe": probe})
        return candidates

    def _format_blf_dbc_paths(self, dbc_paths):
        names = [Path(p).name for p in dbc_paths]
        if len(names) == 1:
            return names[0]
        return f"DBC×{len(names)}: " + ", ".join(names[:3]) + (
            "..." if len(names) > 3 else ""
        )

    def _format_blf_dbc_candidate(self, candidate):
        probe = candidate["probe"]
        return (
            f"{self._format_blf_dbc_paths(candidate['paths'])} "
            f"· {probe.strength} · "
            f"CAN ID {probe.matched_frame_id_count}/{probe.total_frame_id_count} · "
            f"帧 {probe.decoded_frame_count}/{probe.total_frame_count} · "
            f"信号 {len(probe.signal_names)}"
        )

    def _resolve_blf_dbc_paths(self, path):
        candidates = self._probe_blf_dbc_candidates(path)
        if not candidates:
            message = (
                f"未找到可自动匹配 {path.name} 的 DBC。\n"
                "需要选择一个 DBC 后才能打开该 BLF。"
            )
            if not self._ask_open_blf_dbc_dialog(path, message):
                return None
            return self._choose_blf_dbc_with_retry(path)

        if len(candidates) == 1:
            action = self._ask_blf_dbc_candidate_action(path, candidates[0])
            if action == "use":
                return list(candidates[0]["paths"])
            if action == "choose":
                return self._choose_blf_dbc_with_retry(path)
            return None

        selected = self._ask_multiple_blf_dbc_candidates(path, candidates)
        if selected == "choose":
            return self._choose_blf_dbc_with_retry(path)
        if selected:
            return list(selected)
        return None

    def _validated_blf_dbc_paths(self, path, dbc_paths):
        key = list(self._canonical_blf_dbc_paths(dbc_paths))
        if not key:
            return None
        try:
            probe = DataLoader.probe_blf_dbc(str(path), key)
        except Exception:
            return None
        return key if probe.is_match else None

    def _choose_blf_dbc_with_retry(self, path):
        while True:
            dbc_paths = self._prompt_blf_dbc(path)
            if not dbc_paths:
                return None
            try:
                probe = DataLoader.probe_blf_dbc(str(path), dbc_paths)
            except Exception as exc:
                action = self._ask_blf_dbc_mismatch_action(
                    path, dbc_paths, detail=str(exc)
                )
                if action == "retry":
                    continue
                return None
            if probe.is_match:
                return list(dbc_paths)
            action = self._ask_blf_dbc_mismatch_action(path, dbc_paths)
            if action != "retry":
                return None

    def _ask_open_blf_dbc_dialog(
        self, path, message, icon=QMessageBox.Information
    ):
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle("选择 DBC")
        box.setText(message)
        choose = box.addButton("选择 DBC", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(choose)
        box.exec_()
        return box.clickedButton() is choose

    def _ask_blf_dbc_candidate_action(self, path, candidate):
        probe = candidate["probe"]
        is_weak = probe.strength == "weak"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning if is_weak else QMessageBox.Information)
        box.setWindowTitle("确认 DBC")
        if is_weak:
            box.setText(
                f"{self._format_blf_dbc_paths(candidate['paths'])} 只能部分匹配 "
                f"{path.name}。\n是否仍使用该 DBC 解码？"
            )
            use_text = "仍然使用"
        else:
            box.setText(
                f"检测到 {path.name} 可使用已匹配的 "
                f"{self._format_blf_dbc_paths(candidate['paths'])} 解码。\n"
                "是否使用？"
            )
            use_text = "使用此 DBC"
        box.setInformativeText(self._format_blf_dbc_candidate(candidate))
        use = box.addButton(use_text, QMessageBox.AcceptRole)
        choose = box.addButton("选择其他 DBC", QMessageBox.ActionRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(use)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is use:
            return "use"
        if clicked is choose:
            return "choose"
        return "cancel"

    def _ask_multiple_blf_dbc_candidates(self, path, candidates):
        items = [self._format_blf_dbc_candidate(c) for c in candidates]
        other = "选择其他 DBC..."
        items.append(other)
        choice, ok = QInputDialog.getItem(
            self,
            "选择 DBC",
            f"检测到多个可匹配 {path.name} 的 DBC，请确认：",
            items,
            0,
            False,
        )
        if not ok:
            return None
        if choice == other:
            return "choose"
        try:
            idx = items.index(choice)
        except ValueError:
            return None
        if idx >= len(candidates):
            return None
        return list(candidates[idx]["paths"])

    def _ask_blf_dbc_mismatch_action(self, path, dbc_paths, detail=""):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("DBC 不匹配")
        box.setText(
            f"选择的 {self._format_blf_dbc_paths(dbc_paths)} 无法解码 "
            f"{path.name}。\n请重新选择 DBC。"
        )
        if detail:
            box.setInformativeText(detail)
        retry = box.addButton("重新选择", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(retry)
        box.exec_()
        return "retry" if box.clickedButton() is retry else "cancel"

    def _prompt_blf_dbc(self, path):
        """Chained DBC picker shown when opening a ``.blf``.

        Returns the list of chosen ``.dbc`` paths, or ``[]`` if the user
        cancels — the BLF UI flow treats cancel as "do not open this file".
        ``QFileDialog`` is resolved via ``sys.modules`` so smoke tests can patch
        it the same way they patch the main open dialog (and so ``_load_one``
        never pops a real dialog under test)."""
        import sys as _sys
        _pkg = _sys.modules.get('mf4_analyzer.ui.main_window')
        _QFileDialog = getattr(_pkg, 'QFileDialog', QFileDialog) if _pkg is not None else QFileDialog
        dbcs, _ = _QFileDialog.getOpenFileNames(
            self, f"为 {path.name} 选择 DBC（取消则按原始字节打开）", "",
            "CAN 数据库 (*.dbc);;所有文件 (*)",
        )
        return list(dbcs)

    def _close(self, fid):
        if fid not in self.files: return
        name = self.files[fid].short_name
        # Cache invalidation site 2: drop entries for this file before
        # we discard the FileData — capture fid so the per-data_id filter
        # can match. Same for the monotonicity cache (custom-x source
        # may also be this file).
        self.canvas_time.invalidate_envelope_cache(
            "file closed", data_id=fid
        )
        self.canvas_time.invalidate_monotonicity_cache(custom_xaxis_fid=fid)
        # All analysis caches (legacy LRU + per-section AnalysisResultCache)
        # must be cleared before we release the FileData. Use the unified
        # single entry point so the 'fft' and 'order' caches are also cleared
        # (previously two separate calls; now one, semantically equivalent).
        self._invalidate_all_analysis_caches_for_fid(fid)
        del self.files[fid]
        self.navigator.remove_file(fid)
        self._active = self.navigator._active_fid  # navigator picks fallback
        self._update_info()
        self._reset_plot_state(scope='file')
        self.statusBar.showMessage(f"已关闭 | 剩余 {len(self.files)} 文件")
        self.toast(f"已关闭 {name}", "info")

    def save_project(self, path):
        """Serialize the current session (open files + all Views) to a
        reference-only ``.tlproj`` JSON file. No UI entry point yet — this is
        the callable used by tests and a future menu/button."""
        from pathlib import Path
        from .. import project_io as pio
        path = Path(path)

        self._capture_focused_view()
        # Flush each analysis section's live UI state into its active view so
        # the last (uncommitted) inspector edit / source / compare toggle is
        # serialized rather than lost.
        current_mode = self.chart_stack.current_mode()
        for sec in self.analysis_managers:
            self._capture_active_analysis_view(
                sec, capture_sources=(sec == current_mode))

        file_refs = []
        for fid, fd in self.files.items():
            abs_p = str(Path(fd.filepath).resolve())
            dbc_refs = [
                pio.make_path_ref(str(Path(dbc).resolve()), path)
                for dbc in fd.source_metadata.get("dbc_paths", [])
            ]
            file_refs.append(pio.ProjectFileRef(
                fid=fid,
                path_abs=abs_p,
                path_rel=pio.make_relative(abs_p, path),
                fs=float(fd.fs),
                time_source=fd._time_source,
                dbc_refs=dbc_refs,
            ))

        vm = {
            "active": int(self.view_manager.active),
            "split_pairs": {
                str(host): int(src)
                for host, src in self.view_manager._split_pairs.items()
            },
        }
        doc = pio.ProjectDocument(
            active_file=self._active,
            current_mode=self.chart_stack.current_mode(),
            files=file_refs,
            views=[v.to_dict() for v in self.view_manager.views],
            view_manager=vm,
            analysis_views={
                sec: {
                    "active": mgr.active,
                    "views": [v.to_dict() for v in mgr.views],
                }
                for sec, mgr in self.analysis_managers.items()
            },
            filter=self._project_filter_payload(),
        )
        pio.save_project_to_json(doc, path)
        self._project_path = path
        self.statusBar.showMessage(f"已保存项目: {path.name}")
        self.toast("已保存项目", "success")

    def open_project(self, path):
        """Restore a session from a ``.tlproj`` file: re-read referenced source
        files (skipping missing ones), reinstall saved Views with fids remapped
        to freshly minted ids, and select the saved active file / mode."""
        from pathlib import Path
        from PyQt5.QtWidgets import QMessageBox
        from .. import project_io as pio
        from ..view_state import ViewState
        path = Path(path)

        doc = pio.load_project_from_json(path)
        self.close_all()
        # Fresh restore: clear any stale auto-recompute queue from a prior open.
        self._analysis_restore_pending = set()

        fid_map = {}
        missing = []
        pending_by_path = {}  # resolved path -> new fids from one _load_one, unconsumed
        for ref in doc.files:
            resolved = pio.resolve_file_path(ref, path)
            if resolved is None:
                missing.append(ref.path_abs)
                continue
            key = str(resolved)
            if not pending_by_path.get(key):
                before = set(self.files.keys())
                dbc_paths = pio.resolve_dbc_paths(ref, path)
                self._load_one(key, blf_dbc_paths=dbc_paths)
                new_fids = [f for f in self.files.keys() if f not in before]
                if not new_fids:
                    missing.append(ref.path_abs)
                    continue
                pending_by_path[key] = new_fids
            new_fid = pending_by_path[key].pop(0)
            fid_map[ref.fid] = new_fid
            fd = self.files[new_fid]
            fd.fs = float(ref.fs)
            if ref.time_source in ("generated", "manual"):
                fd.rebuild_time_axis(float(ref.fs))

        self._restore_project_filter(doc.filter)

        remapped = pio.remap_view_fids(doc.views, fid_map)
        states = [ViewState.from_dict(v) for v in remapped]
        if not states:
            states = [self.view_manager._make(0)]
        self.view_manager.views = states
        self.view_manager._split_pairs = {
            int(host): int(src)
            for host, src in (doc.view_manager.get("split_pairs") or {}).items()
            if 0 <= int(host) < len(states) and 0 <= int(src) < len(states)
        }
        active_idx = int(doc.view_manager.get("active", 0))
        self.view_manager.active = max(0, min(active_idx, len(states) - 1))
        self.view_manager._set_active_split_from_pairs()
        self.view_manager.views_changed.emit()

        # Restore each analysis section's view list (fids remapped to the
        # freshly minted ids). An old project without analysis_views yields an
        # empty remapped dict -> every section keeps its default single view.
        from ..project_io import remap_analysis_view_fids
        from ..analysis_view_state import AnalysisViewState
        remapped = remap_analysis_view_fids(doc.analysis_views, fid_map)
        for sec, mgr in self.analysis_managers.items():
            block = remapped.get(sec)
            if not block or not block.get("views"):
                continue
            mgr.views = [AnalysisViewState.from_dict(v) for v in block["views"]]
            mgr.active = min(int(block.get("active", 0)), len(mgr.views) - 1)
            # Queue every source-bearing view for auto-recompute (recompute-on-
            # open): the project stored params + sources but not the numeric
            # results. The active view recomputes immediately via the emit
            # below; the rest recompute lazily the first time they're shown.
            for i, v in enumerate(mgr.views):
                if any(p.sources for p in v.panes):
                    self._analysis_restore_pending.add((sec, i))
            mgr.views_changed.emit()
            # active_changed drives _on_analysis_view_switched: it applies the
            # restored structure/params/sources, then _render_analysis_view_from
            # _cache recomputes this view (queued above) so the chart repopulates.
            mgr.active_changed.emit(mgr.active)

        self._active = fid_map.get(doc.active_file)
        # Route the mode through the toolbar's programmatic setter (not
        # chart_stack.set_mode directly): _set_mode checks the matching
        # segment button AND emits mode_changed -> _on_mode_changed, which
        # syncs chart_stack + inspector + toolbar enabled-state together.
        # Calling chart_stack.set_mode alone leaves the toolbar segment and
        # the inspector panel stuck on the previous mode (desync on reopen of
        # a project saved in FFT / Order / FFT-vs-Time).
        #
        # _opening_project stays True through _apply_active_view() below, not
        # just this mode-set call: when the saved mode is 'time',
        # _apply_active_view -> _plot_time_on_canvas synchronously calls
        # _begin_compute_progress(process_events=True), whose
        # QApplication.processEvents() can drain a still-pending post-load
        # analysis auto-recompute (QTimer.singleShot(0, ...), queued above)
        # BEFORE open_project() returns. That drained recompute's "capture
        # current live selection" step (_capture_analysis_sources) must know
        # a restore is still in progress so it does not mistake the shared
        # Time/FFT navigator's state -- already overwritten by this same
        # restore's own Time-view apply -- for fresh user intent. See
        # docs/lessons-learned/signal-processing/2026-07-12-processevents-
        # drains-queued-recompute-during-restore.md.
        self._opening_project = True
        try:
            self.toolbar._set_mode(doc.current_mode)

            if missing:
                QMessageBox.warning(
                    self, "部分文件缺失",
                    "以下文件找不到，已跳过：\n" + "\n".join(missing),
                )

            # The project's files/views are loaded by this point, so the
            # document is "open" regardless of whether the final view render
            # succeeds — record the path BEFORE the render guard so a render
            # hiccup doesn't leave 保存项目 prompting Save-As for an
            # already-open project.
            self._project_path = path

            try:
                self._apply_active_view(self.view_manager.active)
            except Exception:
                self.statusBar.showMessage(
                    f"已打开项目: {path.name}（渲染恢复失败）")
                self.toast("恢复渲染失败，请手动点计算", "warning")
                return
        finally:
            self._opening_project = False

        self.statusBar.showMessage(f"已打开项目: {path.name}")

    def _project_filter_payload(self):
        fp = getattr(getattr(self, "inspector", None), "filter_panel", None)
        if fp is None:
            return None
        return {
            "enabled": bool(fp.is_enabled()),
            "spec": fp.filter_spec().to_dict(),
            "show_original": bool(fp.show_original()),
            "show_filtered": bool(fp.show_filtered()),
        }

    def _restore_project_filter(self, payload):
        fp = getattr(getattr(self, "inspector", None), "filter_panel", None)
        if fp is None:
            return
        if not payload:
            fp.set_enabled(False)
            return
        from ...signal.filters import FilterSpec

        spec = FilterSpec.from_dict(payload.get("spec"))
        label_for_kind = {
            "low": "低通",
            "high": "高通",
            "band": "带通",
            "bandstop": "带阻",
        }.get(spec.kind, "低通")
        fp.set_kind(label_for_kind)
        if spec.kind in ("band", "bandstop"):
            fp.set_band(spec.cutoff_lo, spec.cutoff_hi)
        else:
            fp.set_cutoff(spec.cutoff)
        fp.set_order(spec.order)
        fp.chk_orig.setChecked(bool(payload.get("show_original", True)))
        fp.chk_filt.setChecked(bool(payload.get("show_filtered", True)))
        fp.set_enabled(bool(payload.get("enabled", False)))

    def close_all(self):
        if not self.files:
            return
        n = len(self.files)
        # Cache invalidation site 2 (close-all variant): wipe everything.
        self.canvas_time.invalidate_envelope_cache("all files closed")
        self.canvas_time.invalidate_monotonicity_cache()
        # Per-section analysis caches: every entry is now stale (close-all
        # variant of the per-fid invalidate in ``_close``).
        for cache in self.analysis_caches.values():
            cache.clear()
        # FftTimeCoordinator holds in-flight pending contexts that cache.clear()
        # above does NOT touch — drop them too so a fft_time job still running
        # when all files close cannot resurrect a dead-fid result into the
        # just-cleared cache (N1; mirrors _close's per-fid coordinator.invalidate).
        coordinator = getattr(self, "_fft_time_coordinator", None)
        if coordinator is not None:
            coordinator.invalidate_all()
        for fid in list(self.files.keys()):
            del self.files[fid]
            self.navigator.remove_file(fid)
        self._active = None
        self._update_info()
        self._reset_plot_state(scope='all')
        self.statusBar.showMessage("已关闭全部")
        self.toast(f"已关闭全部 {n} 个文件", "info")
