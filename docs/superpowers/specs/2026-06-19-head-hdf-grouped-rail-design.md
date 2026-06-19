# HEAD `.hdf` 多轨左栏分组呈现 — 设计

- 日期：2026-06-19
- 状态：已确认（用户认可竖向两级折叠 mock：`docs/head-hdf-ui-mockup.html`）
- 关联：`docs/superpowers/specs/2026-06-19-head-hdf-import-design.md`（导入功能）

## 目标

一个 `.hdf` 当前加载为 N 个 `FileData`（同 `filepath`，不同 `label_suffix`/`fs`），现在渲染成 **2 个顶部卡 + 2 个并列树节点**，用户嫌割裂。改为：

- **顶部文件区：同 `filepath` 的多个 fid 只显示 1 张卡**。
- **通道树：两级折叠** —— `文件节点（可折）→ 轨道子组节点（可折/整轨勾）→ 通道叶子`。

**纯表现层**：后端 `self.files` 仍每 fid 一项；`get_checked_channels()` 仍返回 `(fid, ch, color)`；分析/绘图按各 fid 的 `fs` 走——**不动**。单文件（mf4/csv，`label_suffix==""`）行为完全不变（仍 1 卡 + 两级"文件→通道"）。

## 分组键与判定

- 分组键 = `fd.filepath`（同一 `.hdf` 的多轨共享）。
- **是否嵌套由 `fd.label_suffix` 决定**：非空 → 该 fid 是某多轨源的一条轨，进"文件→轨道→通道"嵌套；空 → 普通单文件，保持"文件→通道"两级（现状）。

## 1. 顶部卡 `mf4_analyzer/ui/file_navigator.py`

- `FileNavigator` 维护 `filepath → 卡片` 与 卡片 → `[fid…]`。
- `add_file(fid, fd)`：若该 `filepath` 已有卡片 → 把 fid 并入该卡片的组、刷新卡片 meta，**不新建卡**；否则新建卡。仍对每个 fid 调用 `channel_list.add_file(fid, fd)`（通道树内部自己分组）。
- 卡片 meta：多轨组显示 `N 轨 · {fs1}k/{fs2}k Hz · {dur} s`；单轨组保持原 `{rows} 行 · {fs} Hz · {dur} s`。
- 关闭：卡片 `×` 关掉该组**全部 fid**（逐个走既有 `_close`/`close_requested` 流程）。
- 激活：激活卡片 → 主 fid 取该组首个（快轨）fid。
- `remove_file(fid)`：从所属卡组移除该 fid；组空才删卡。
- 头部计数 `_refresh_header`：按**卡片数（唯一源）**计，不按 fid 数。

## 2. 通道树 `mf4_analyzer/ui/widgets/__init__.py`（`MultiFileChannelWidget`）

- 维护 `_source_items: filepath → 文件 QTreeWidgetItem`、`_raster_items: fid → 轨道 QTreeWidgetItem`；保留 `_files: fid→fd`、`_colors:(fid,ch)→color`。
- `add_file(fid, fd)`：
  - `fd.label_suffix` 非空（嵌套）：复用/新建该 `filepath` 的**文件节点**（label=`filepath.stem`，可折，UserRole `('source', filepath_str)`），在其下加**轨道子组节点**（label=`{fs:.1f} Hz`，副标注 `{rows} 行`，可折，整轨可勾，UserRole `('raster', fid)`），轨道下挂通道叶子（UserRole `('channel', fid, ch)`，同现状）。
  - `label_suffix` 空（扁平）：维持现状——文件节点（`('file', fid)`）直挂通道叶子。
- `get_checked_channels()`：**递归遍历整棵树**收集勾选的 channel 叶子（按 UserRole `('channel', fid, ch)`），返回 `[(fid, ch, color)…]`（与现状签名一致，绘图零改）。
- 勾选传播 `_on_item_changed`：勾文件/轨道节点 → 递归勾其下全部通道；取消反之。父节点显示三态（全/部分/无）为加分项。
- `remove_file(fid)`：删该 fid 的轨道子组（含通道、清 `_colors[(fid,*)]`、`_files[fid]`）；其父文件节点若无轨道子组了则一并删。扁平文件按现状删文件节点。
- 过滤 `_apply_filters`、右键 `_on_context_menu`（"设为左轴"）适配多一层：右键仍只对 channel 叶子生效，解析 `('channel', fid, ch)`。

## 3. 主窗口 `_project_io_mixin.py`

- `.hdf` 分支加载后状态栏/计数按**唯一源文件数**显示（用 `navigator.file_list_count()` 或唯一 `filepath` 去重），避免"共 2 文件"误导。

## 4. 测试（qapp，`QT_QPA_PLATFORM=offscreen`）

- 通道树：同 `filepath`+`label_suffix` 调 `add_file` 两次 → 1 个文件节点、2 个轨道子组、通道在第三层；`get_checked_channels()` 勾选后仍返回正确 `(fid, ch)`；勾轨道节点→该轨全通道选中；`remove_file` 删一轨后文件节点仍在、删尽则消失。
- 扁平：单文件（无 label_suffix）`add_file` → 文件直挂通道（两级，回归不破）。
- 顶部卡：同 filepath 两次 `add_file` → `file_list_count()==1`；移除一个 fid 卡仍在，移除全部卡消失。
- 用 `tests/ui/` 既有 `qapp` 范式（见 `test_project_session.py`）。

## 5. 视觉验收（强制）

真机跑 app、加载真实 `.hdf`，截图确认：1 张卡 + 文件→轨道→通道两级折叠、勾选/折叠交互正常（[[feedback-verify-ui-visually]]，不靠"测试过"口头确认）。

## 范围外

不改采样率/分组/标定等数据逻辑；不动 mf4/csv 呈现；项目保存/重开已在导入功能里按 path 去重，无需再改。
