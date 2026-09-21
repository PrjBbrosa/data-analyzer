# Lite Windows 打包与导出渲染优化计划

- 日期：2026-09-21。
- 状态：**源码 Task 1–4 已实施；Lite 冻结验收未做，不能当发布通过。** 验收记录见 `docs/analyzer/reviews/2026-09-21-lite-packaging-render-hardening.md`。
- 基线 HEAD：`5d7868f1961f580263e7ae4ef85a994bfeab6edb`；实际证据来自带未提交修改的工作树及其冻结包，不能归因于该 commit 单独的内容。
- 本轮授权：用户已要求按计划实施；源码 Task 1–4 已落地。未提交、未推送、未重建 Windows EXE。
- 目标：修复离屏文字消失、屏幕 DPI 污染导出排版、像素验证器内存生命周期错误，并将裁剪后的导入验证接入 Lite 构建。
- 执行方式：按依赖顺序实施；不要求多代理或同时运行多个构建。

## 1. 已确认事实与证据边界

下列路径相对仓库根；`.state/` 是本机证据，不承诺随仓库分发。实施时重新定位符号、核验产物哈希，不把历史结果当作新代码的验收结果。

| 编号 | 已确认问题／结果 | 证据与边界 |
| --- | --- | --- |
| F1，P1 | Lite 冻结包在 offscreen 下没有文字，导致整个构建失败 | 构建目录 `.state/build-evidence/lite/20260921-202103-393-253c9e7f87084d3ca1d7aa567630a208/`；`build.log` 中 PyInstaller 退出 0，随后渲染退出 1。6 张 PNG 已生成，但中文标题、英文图例和刻度缺失 |
| F1 补充 | 不是仅凭字体名称推断缺字；普通 Python 也能复现 | `.state/lite-review-20260921/font-probes.log`：offscreen 的中文和 ASCII 均 `supports=true`、`ink_pixels=0`；出现 Qt 字体目录不可用警告。字体发现／加载路径是定位方向，具体修复机制尚未证明 |
| F2，P2 | Windows 平台绘字正常，但固定像素导出受屏幕 DPI 影响，刻度重叠 | 同一 EXE 的 Windows 探针：逻辑 DPI 192、DPR 1、12pt 字体高度 41；仅在新诊断进程设 `QT_FONT_DPI=96` 后高度 21，640×360 图片排版恢复。原图 `render-windows/outputs/time.png`，对照 `windows-dpi96/time.png`，均在上述 review 目录 |
| F3，P2 | 像素检查返回了指向临时 QImage 缓冲区的 NumPy 视图 | `tools/verify_frozen_batch_render.py::_pixel_rgb_array`。本机探针先读到 `[12,34,56]`，新分配一张图后变为 `[210,120,30]`，原始图像未变。此为内存所有权缺陷；不要依赖特定分配器每次复现同一覆盖顺序 |
| F4，验证缺口 | Windows 渲染返回成功，却没有发现重叠刻度 | `.state/lite-review-20260921/windows.json` 为 `ok=true`；当前 verifier 校验文件、尺寸、字体独立出墨和色图，不证明最终页面布局可读 |
| F5，验证缺口 | Lite 删除 SciPy OpenBLAS 后没有自动运行冻结导入检查 | `tools/build_windows_folder_lite.ps1` 的 prune 后仅调用渲染验证；现有 `tools/verify_lite_importer_runtime.py` 尚未接入 |
| 已有正向结果 | 传统 MAT、HDF5 MAT、WAV、MP4 音轨冻结导入通过 | `.state/lite-review-20260921/probes.log`，四类样本分别返回 2、2、1、1 个通道；这是该包的功能冒烟结果，不是所有格式的正确性证明 |
| 已关闭问题 | PowerShell 参数嵌套导致 PyInstaller 退出 2 | 已通过 Windows 原生 argv 回归；保留现有修复和测试，不重复重构日志调用器 |

本次未证明存在可利用的安全漏洞。Windows ARM 虚拟机内运行 x64 包、原生 x64 Windows、macOS Cocoa、前台完整交互是不同证据类别。

## 2. 范围与必须保持的合同

1. 保留 `offscreen` 与 `windows` 两条冻结渲染验证。不得把失败改成 skip、放宽出墨阈值或静默切换平台来获得绿色结果。
2. `BatchRenderOptions.width_px/height_px` 决定输出像素，导出 `dpi` 仍写 PNG 分辨率元数据；同样像素尺寸、样式和字体下，改变屏幕 DPI 不应改变页面布局。
3. 用户的 `font_scale` 继续有效。不得改 `CHART_FONT_PT`、主界面字体、系统缩放或全局 `QApplication` 字体来修复批量导出。
4. 保留 `_export.py` 的“完成绘制后再写 DPI 元数据”、SSAA、pen／symbol／flag 还原合同。不得提前设置 QImage DPI 来掩盖问题，避免 QPicture 刻度回归。
5. 实现留在 owning modules：Batch 专属字体／布局策略由 `batch_render_qt/` 拥有；通用字体发现若确需修改，放 `qt_chart_fonts.py`。不向 `batch_render.py` 或 `_fonts.py` 的兼容导出层塞入实现。
6. 不改 DSP、数据内容、滤波／阶次算法、采集依赖、项目保存功能；不升级 Qt/Python，不新增常驻进程，不做全仓库字体重构。
7. 不改变用户可见操作入口；若实施确实新增或更名操作，须同时更新 `ui/hints.py`、`ui/quickref.py`，并明确新增范围。
8. 不改版本号，不动 `CLAUDE.md`。保留现有未提交修改；项目保存相关文件及 `ssh-keygen` 不属于本任务。

## 3. 推荐方案

### 3.1 先修复验证器内存所有权

`_pixel_rgb_array()` 在局部 QImage 仍存活时完成显式数据复制，返回拥有稳定存储的 RGB 数组。保留逐行 `bytesPerLine` 处理，不能假设每行无 padding。继续从产品 LUT 获取色图参考值，不另写一套 RGB 常量。

回归验证必须在源图及临时转换图销毁后读取数组，并覆盖 RGB888 行 padding、ARGB32 输入和空图行为；空图应给出明确异常。用生命周期与内容断言作为确定性门禁，分配压力覆盖作为补充，避免把分配器恰好复用地址当作唯一通过条件。

### 3.2 为离屏渲染建立真正可绘制的字体来源

先做最小原生探针：同一字体、同一 QPainter 绘制，分别记录字体加载结果、字符覆盖、中文与 ASCII 出墨、Qt 平台、字体文件来源及 stderr。分别验证源码运行与冻结包，不先改大范围字体选择逻辑。

首选在渲染初始化 owner 中显式加载当前机器已有、可读的 CJK 字体文件并验证实际出墨；候选来源通过 Windows 字体目录／注册信息等实测取得，不能写死某台机器的盘符、用户名或单一字体文件名。Qt 应用字体注册及探测在 GUI 线程进行，一次初始化复用，不在每帧扫描目录。若需环境配置，必须发生在独立进程创建 QApplication 前，且仅作用于该进程。

若现有 Qt offscreen 后端无法通过该方式绘字，记录具体失败与候选方案，不把 windows 平台结果冒充 offscreen 通过。更换 Qt 版本、再分发字体或改变支持的平台合同都超出默认修复范围，应先修订方案并取得对应范围授权。系统字体文件的运行时使用不等于获得随软件再分发的许可。

已有 QApplication 必须复用，不能切平台、再创建第二个 app 或污染主界面字体。没有可用字体时输出明确的环境失败，保留证据，不返回成功的无文字报告。

### 3.3 将导出文字几何与屏幕 DPI 分离

以现有 96 逻辑 DPI 正常产物作为布局校准参考；96 是导出文字的参考尺度，不是强制改用户屏幕设置，也不是覆盖用户选择的 PNG dpi。

在 Batch 专属 owner 中统一生成导出字体和富文本尺寸，使以下链路采用同一尺度：标题、副标题、坐标数字、轴名、图例、统计卡片、色条、页脚，以及对应的 QFontMetrics 测量。优先验证局部字体像素尺寸／局部字体换算方案；不能只缩小刻度字体，也不能仅给验证子进程加 `QT_FONT_DPI=96` 而让实际 Batch 仍有问题。

独立子进程的 DPI 环境变量只用于差分实验。嵌入现有 GUI 的 Batch 导出也必须正确，导出前后主界面字体、DPI 属性、当前 View 及后续导出结果保持一致。保留小数 `font_scale` 意图，量化误差由几何测试约束，不靠修改既有测试期望隐藏偏差。

### 3.4 验证最终产物，并收齐构建诊断

- 冒烟结果增加可核查的字体／DPI和布局诊断；主图标题、刻度、图例的实际 PNG 区域都要有文字，不能只相信独立 header 探针。
- 优先复用 renderer 已有几何与测量结果；最终 PNG 区域校验作为独立背书。覆盖已知 192 DPI 坏图、移除标题／图例、重叠刻度等负例，证明门禁能拒绝坏结果。
- Lite 在所有包内容裁剪完成后执行四类冻结导入冒烟。复用现有工具；补齐失败 JSON、stdout/stderr、样本和超时证据，不引入第二套导入算法。
- 预构建、依赖契约、PyInstaller 或必要文件失败仍立即停止。EXE 已生成且结构有效后的独立渲染／导入检查分别记录结果，普通检查失败后继续收集其他独立结果，最后只汇总一次成败；禁止 catch 后丢失失败退出码。超时须终止本次子进程后才能进入下一项。
- 总结明确区分“EXE 已生成”“offscreen 失败”“windows 未运行／失败”“导入通过／失败”。所有必需门禁通过才打印 `Build succeeded: True`。保留失败产物便于诊断，但不能把失败目录作为发布成功产物。

## 4. 执行任务与验收门禁

### Task 0：冻结受影响基线与最小复现

**范围**：只读检查；证据写入新的 `.state/` 目录。

- 记录 HEAD、相关文件的 dirty diff／内容哈希、构建脚本快照、运行时版本和 EXE／关键 Qt DLL 哈希；不保存凭据或复制无关文件。
- 检查正在运行的构建／pytest 及其 cwd，避免覆盖别人正在使用的 `dist` 和证据。
- 为 F3 先增加会失败的生命周期用例；为 F1/F2 保留源码与同一冻结包的最小子进程复现。
- DPI 实验至少记录 96/144/192 的请求值与实际逻辑 DPI、DPR。若 Qt 未采纳某个配置，该项记为 UNKNOWN，不能把环境变量字符串当成完成验收。

**门禁**：上述证据齐全且能区分源码／冻结、offscreen／windows。已有构建日志可复用，不要求先重建或跑全套测试。

### Task 1：像素验证器可靠性（F3）

**文件**：`tools/verify_frozen_batch_render.py`、`tests/test_frozen_batch_render_smoke.py`。

**步骤**：先红后绿地修复复制与 padding；检查该文件所有像素统计消费者；保留已有失败／超时诊断。

**门禁**：新增像素生命周期用例及该 owner 的 verifier／失败保留用例通过；使用既有 PNG 验证结果合理。这里不需要 UI 套件或重新打包。

### Task 2：离屏字体可绘制性（F1）

**文件**：`batch_render_qt/_dispatch.py`、必要时 `qt_chart_fonts.py`、`batch_render_smoke.py`；测试落在 `tests/test_batch_render_qt.py` 和 `tests/test_frozen_batch_render_smoke.py`。

**步骤**：先定位字体注册的最小有效机制，再实现初始化／失败语义；补齐中文和 ASCII 的实际绘制证据。保持显式平台选择，不自动降级。

**门禁**：Windows 源码 offscreen 与 windows 字体探针均通过；覆盖现有 QApplication、无字体、初始化复用、非 GUI 线程调用、正常退出。运行 `tests/test_batch_render_import_boundary.py`；共享字体 helper 有变时补相关现有字体 owner 测试，不扩大为全套 UI。

### Task 3：导出字体与 DPI 隔离（F2）

**文件**：`batch_render_qt/_theme.py`、`_page.py`、`_builder.py`，仅必要时 `_export.py`；不改变共享屏幕字体默认值。

**步骤**：先用同一 640×360 fixture 捕获 96/192 差异，再统一 Batch 的字体创建及测量；逐个覆盖标题、刻度、图例、统计卡和色条。局部 helper 放 owning module 并复用，不在各控件内复制 DPI 算式。

**门禁**：

- 运行 `tests/test_batch_render_qt.py` 的字体、布局、PNG dpi 和既有 `test_subplot_export_draws_before_writing_dpi_metadata_and_contains_ticks`；运行 `tests/test_batch_render_qt_ssaa.py` 保证 SSAA 还原。
- 运行 `tests/test_batch_render_qt_heatmap.py`、`tests/test_batch_render_qt_frf.py` 中受影响的字体／布局用例，覆盖默认 gnuplot2、turbo 和 FRF 图例。
- 新鲜进程比较 96/144/192 DPI；至少覆盖 640×360 冒烟与 1920×1080 实际导出、多面板、`font_scale=1.0/1.5`。已有高字号、多面板边界用例继续保留。
- 同机同字体同 case 的文字包围框和绘图区坐标漂移不超过 2 个输出像素；相邻可见刻度包围框不相交，文字不越界。若测量噪声不满足此门限，先提交差分证据解释，不随意扩大容差。
- PNG dpi 元数据分别验证 72/144/300；它不改变同一像素画布的排版。颜色值仍从产品 LUT 回读，不要求不同 OS 字体光栅逐字节相同。
- 前台已有 QApplication 中导出前后 UI 不变化；补一次真实 Cocoa 输出检查，macOS offscreen 结果不能替代。

### Task 4：布局门禁及 Lite 导入门禁（F4/F5）

**文件**：`batch_render_smoke.py`、`tools/verify_frozen_batch_render.py`、`tools/verify_lite_importer_runtime.py`、`tools/build_windows_folder_lite.ps1` 及各自现有测试。

**步骤**：增加最终 PNG 与布局负例检查；扩展现有 importer 工具的证据保存；在 prune 后接线；为独立后置检查汇总状态，保留整体非零退出。

**门禁**：

- `tests/test_frozen_batch_render_smoke.py`：已知坏图、缺字、无效布局、格式不符均失败；失败／超时保留子进程日志和产物。
- `tests/test_windows_build_script.py`：Windows PowerShell 5.1 原生执行；注入每种后置失败，确认其余独立检查有结果而总状态仍失败；保留原生 stderr 和 argv 测试。
- `tests/test_importer_runtime_smoke.py`、`tests/test_windows_runtime_dependencies.py`：传统 MAT、HDF5 MAT、WAV、MP4 四类路径；工具失败／超时不会丢失 result.json、fixture 和日志。
- `tests/test_packaging_imports.py`、`tests/test_batch_render_import_boundary.py`；只有真的改动相应依赖边界时才扩大到其他架构门禁。

### Task 5：稳定快照集成与冻结验收

1. Task 1–4 的相关门禁全部通过后，锁定待验收快照并记录前后文件指纹；源码仍被其他任务修改时暂不开始构建，不以跨快照结果宣称验收。
2. 用常规 Lite 入口完成一次新构建；环境已齐备且未改 requirements 时可用 `-SkipInstall`。不改变用户机器全局 Qt/DPI 配置。
3. 在最终裁剪后的同一 EXE 上验证 offscreen、windows、四类导入、DPI 矩阵；记录 EXE 和内部依赖哈希，留存 PNG、几何、字体、平台、stdout/stderr、每项退出码。
4. 在虚拟机的正常用户桌面会话中做前台打开、文件导入、图表显示、一次 Batch 导出；检查退出和子进程清理。新包、正常启动及前台视觉分别记录，不由测试数量代替。
5. `git diff --check`、变更范围审查和 lesson 状态检查通过。仅在发生发布／合并验收时运行一次稳定快照全套门禁：先主套件 `--ignore=tests/acquisition_ui`，完成后独立运行 `tests/acquisition_ui`；开始前排除并行全套，异常退出记 UNVERIFIED。

Full 复用 renderer／verifier，因此至少运行共享 owner 与脚本合同测试。若要宣称 Full 发布可用，另需新鲜 Full 冻结验收；本 Lite 任务不能代为证明。原生 x64 Windows 未验证时明确保留该平台门禁，不能用 ARM 虚拟机结果替代。

## 5. 完成标准与交付物

| 检查 | 完成条件 |
| --- | --- |
| 构建 | 原生参数正确，必要依赖齐全，所有必需后置检查完成且成功，总退出码 0 |
| 字体 | offscreen/windows 均有中文及 ASCII 实际出墨，最终图片无整块文字缺失 |
| 布局 | DPI 矩阵满足 Task 3 几何阈值，已知刻度重叠负例被门禁拒绝 |
| 内存 | verifier 返回稳定 RGB 数据，不引用已销毁 QImage 缓冲区 |
| 导入 | 最终裁剪后的同一包完成四类样本导入；源码 import 成功不算此项通过 |
| 隔离 | 前台字体、系统设置、用户 `font_scale`、PNG 元数据、SSAA 和 Qt 所有权合同保持正确 |
| 证据 | 当前快照、产物哈希、每项结果和原生／离屏证据分开保存；失败结果不可发布成通过 |

实施交付应包含：最小源码补丁、对应回归测试、Lite 构建检查接线，以及 `docs/analyzer/reviews/` 下简明验收记录；大体积日志、PNG、环境快照留在 `.state/`，不默认提交。若发现新的重复失败模式，按 project-lessons 流程记录，不重复抄写既有日志／argv 教训。

## 6. 本计划文件的验证

本轮仅新增此 Markdown：检查实际文件／符号引用、任务依赖、成功标准、证据类别及 `git diff --check`。不运行运行时测试，也不修改既有 specs 来伪装已完成；本文第 2–3 节是本次待实施的增量合同，历史规范和测试仍用于约束兼容性。
