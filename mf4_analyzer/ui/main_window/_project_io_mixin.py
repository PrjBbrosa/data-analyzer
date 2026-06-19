"""ProjectIOMixin: file load/close and .tlproj save/open for MainWindow."""

from pathlib import Path

from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

from ...io import DataLoader, FileData, HAS_ASAMMDF


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
        """统一打开入口：文件对话框同时接受数据文件和 .tlproj。
        数据文件追加；单个项目替换（有文件时先确认）；项目+文件先开项目再追加；≥2个项目拒绝。"""
        from pathlib import Path
        import sys as _sys
        _pkg = _sys.modules.get('mf4_analyzer.ui.main_window')
        _QFileDialog = getattr(_pkg, 'QFileDialog', QFileDialog) if _pkg is not None else QFileDialog
        fps, _ = _QFileDialog.getOpenFileNames(
            self, "打开", "",
            "所有支持的文件 (*.mf4 *.mdf *.csv *.xlsx *.xls *.hdf *.tlproj);;"
            "项目 (*.tlproj);;数据文件 (*.mf4 *.mdf *.csv *.xlsx *.xls *.hdf)",
        )
        if not fps:
            return
        projects = [p for p in fps if Path(p).suffix.lower() == ".tlproj"]
        data_files = [p for p in fps if Path(p).suffix.lower() != ".tlproj"]

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
        """保存项目 handler: overwrite the current .tlproj if one is open,
        otherwise prompt Save-As."""
        from pathlib import Path
        from PyQt5.QtWidgets import QFileDialog
        if self._project_path is not None:
            self.save_project(self._project_path)
            return
        fp, _ = QFileDialog.getSaveFileName(self, "保存项目", "", "TraceLab 项目 (*.tlproj)")
        if not fp:
            return
        if not fp.lower().endswith(".tlproj"):
            fp = fp + ".tlproj"
        self.save_project(Path(fp))

    def load_files(self):
        import sys as _sys
        _pkg = _sys.modules.get('mf4_analyzer.ui.main_window')
        _QFileDialog = getattr(_pkg, 'QFileDialog', QFileDialog) if _pkg is not None else QFileDialog
        fps, _ = _QFileDialog.getOpenFileNames(self, "选择文件", "", "All (*.mf4 *.mdf *.csv *.xlsx *.xls *.hdf)")
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
                            source_metadata=None, channel_metadata=None,
                            label_suffix=""):
        fid = f"f{self._fc}"; self._fc += 1
        fd = FileData(fp, data, chs, units, len(self.files),
                      source_metadata=source_metadata,
                      channel_metadata=channel_metadata,
                      label_suffix=label_suffix)
        self.files[fid] = fd
        self.navigator.add_file(fid, fd)
        self.canvas_time.invalidate_envelope_cache("file loaded")
        self.canvas_time.invalidate_monotonicity_cache()
        self._fft_time_cache_clear_for_fid(fid)
        self._refresh_channel_dependent_controls()
        if fd.time_array is not None and len(fd.time_array):
            current_hi = self.inspector.top.spin_end.maximum()
            new_hi = max(current_hi, fd.time_array[-1])
            self.inspector.top.set_range_limits(0, new_hi)
            if len(self.files) == 1:
                self.inspector.top.spin_end.setValue(fd.time_array[-1])
        return fd

    def _load_one(self, fp):
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
                    f"✅ 已加载: {p.name} → {len(groups)} 组 | 共 {len(self.files)} 文件")
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
        # FFT vs Time cache: per-file targeted clear — the source ndarray
        # is about to be released, so any cached SpectrogramResult keyed
        # under this fid is now strictly stale.
        self._fft_time_cache_clear_for_fid(fid)
        # Per-section analysis caches (V7) are keyed on (fid, ch, params).
        # _fft_time_cache and analysis_caches['fft_time'] are double-written
        # on compute, so both must be torn down for this fid here — otherwise
        # reopening a file that reuses the same fid would hit a stale result.
        for cache in self.analysis_caches.values():
            cache.invalidate_fid(fid)
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
            file_refs.append(pio.ProjectFileRef(
                fid=fid,
                path_abs=abs_p,
                path_rel=pio.make_relative(abs_p, path),
                fs=float(fd.fs),
                time_source=fd._time_source,
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
        for ref in doc.files:
            resolved = pio.resolve_file_path(ref, path)
            if resolved is None:
                missing.append(ref.path_abs)
                continue
            before = len(self.files)
            self._load_one(str(resolved))
            if len(self.files) <= before:
                missing.append(ref.path_abs)
                continue
            new_fid = next(reversed(self.files))
            fid_map[ref.fid] = new_fid
            fd = self.files[new_fid]
            fd.fs = float(ref.fs)
            if ref.time_source in ("generated", "manual"):
                fd.rebuild_time_axis(float(ref.fs))

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
        self._opening_project = True
        try:
            self.toolbar._set_mode(doc.current_mode)
        finally:
            self._opening_project = False

        if missing:
            QMessageBox.warning(
                self, "部分文件缺失",
                "以下文件找不到，已跳过：\n" + "\n".join(missing),
            )

        # The project's files/views are loaded by this point, so the document
        # is "open" regardless of whether the final view render succeeds —
        # record the path BEFORE the render guard so a render hiccup doesn't
        # leave 保存项目 prompting Save-As for an already-open project.
        self._project_path = path

        try:
            self._apply_active_view(self.view_manager.active)
        except Exception:
            self.statusBar.showMessage(f"已打开项目: {path.name}（渲染恢复失败）")
            self.toast("恢复渲染失败，请手动点计算", "warning")
            return

        self.statusBar.showMessage(f"已打开项目: {path.name}")

    def close_all(self):
        if not self.files:
            return
        n = len(self.files)
        # Cache invalidation site 2 (close-all variant): wipe everything.
        self.canvas_time.invalidate_envelope_cache("all files closed")
        self.canvas_time.invalidate_monotonicity_cache()
        # FFT vs Time cache: every entry is keyed against a now-dead fid.
        self._fft_time_cache.clear()
        # Per-section analysis caches: every entry is now stale (close-all
        # variant of the per-fid invalidate in ``_close``).
        for cache in self.analysis_caches.values():
            cache.clear()
        for fid in list(self.files.keys()):
            del self.files[fid]
            self.navigator.remove_file(fid)
        self._active = None
        self._update_info()
        self._reset_plot_state(scope='all')
        self.statusBar.showMessage("已关闭全部")
        self.toast(f"已关闭全部 {n} 个文件", "info")
