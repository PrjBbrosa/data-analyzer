# Matplotlib 精简打包与圆角浮层黑边修复计划（修订版）

> 基线：`f6ab485`
>
> 本修订版替代原计划中 A-3、A-5、A-9、A-10、A-11、B-1～B-5 的冲突描述。
> 用户已于 2026-07-31 确认按本修订口径直接执行。

## 已确认的根因

1. `mf4_analyzer/batch_render.py` 顶层导入 Matplotlib，但 `requirements.txt`
   未声明它，完整版和 lite 版 Windows 构建脚本还显式排除了它，因此冻结包的
   图片/PDF 批处理必然在进入原子写入前失败。
2. `SignalPickerPopup` 是 `Qt.Popup` 顶层 `QFrame`，只有透明背景，没有
   `FramelessWindowHint`、`NoDropShadowWindowHint` 和 `QFrame.NoFrame`；Windows
   原生 chrome 可以在圆角客户区外留下方形黑边。

## 全局约束

- 所有生产代码变更遵循 TDD：先写并观察目标测试失败，再写最小实现。
- 不改变 CSV 与图片写入过程中“同一有效输出集合整组提交/整组回滚”的原子性。
- 只有渲染后端在任务开始前因 `ImportError`/`ModuleNotFoundError` 不可用时，
  才允许 data+image 请求降级为 data-only；实际渲染或写盘错误仍整组失败。
- data+image 降级项的 item 状态保持 `done`，但必须记录 degraded reason；run
  状态为 `partial`，并提供 `degraded_count`/warnings。image-only 后端不可用仍失败，
  data-only 不探测渲染器。
- manifest 同时保存 requested outputs、effective outputs 和 degraded reason；降级项
  不得被 resume 当成原请求已完整交付。
- 打包排除护栏必须是 flavor-aware 的显式外部依赖契约，不允许用“扫描所有源码
  import 对所有排除项”的一刀切规则误报 `pyxcp`、`pya2l`、内部 acquisition 模块
  或 lite 的有意子模块排除。
- Matplotlib TTF 使用精确白名单：`DejaVuSans.ttf`、
  `DejaVuSans-Bold.ttf`、`DejaVuSans-Oblique.ttf`、
  `DejaVuSans-BoldOblique.ttf`；不能用 `DejaVuSans*.ttf` 通配符。
- `text.parse_math=False` 必须在 Figure/Text 创建前生效。
- `mpl_toolkits` 只作为实验性排除；裁剪后冻结烟测全部通过才保留。
- 不修改版本号、无关 UI、游标吸附或批处理配色。

## Task 1: 修复 Matplotlib 运行时与打包依赖契约

**范围**

- `requirements.txt`
- `mf4_analyzer/io/runtime_dependencies.py`
- `tests/test_windows_runtime_dependencies.py`
- `tests/test_windows_build_script.py`
- `tools/build_windows_folder.ps1`
- `tools/build_windows_folder_lite.ps1`

**步骤**

- [ ] 先写失败测试：requirements 声明 Matplotlib，两个脚本不得排除根包；人为
      向任一 flavor 加回 Matplotlib root exclusion 时契约验证必须失败。
- [ ] 把 Matplotlib 声明为 batch image/PDF export 的 Windows 冻结运行时依赖。
- [ ] 删除两个脚本中错误的 root exclusion 和失效注释。
- [ ] 实现 flavor-aware 外部依赖/排除契约；保留并测试 vendored/guarded/root 与
      intentional submodule exclusions 的明确例外。
- [ ] 审计现有 exclusions，确认不会新增 `pyxcp`、`pya2l`、acquisition 或 scipy
      子模块误报。`tools/` 开发脚本不在产品源码扫描范围，无需伪造注释豁免。

**验证**

- [ ] `tests/test_windows_runtime_dependencies.py`
- [ ] `tests/test_windows_build_script.py`

## Task 2: 字面文本、精简收集、裁剪与冻结渲染烟测

**范围**

- `mf4_analyzer/batch_render.py`
- batch renderer tests
- 两个 Windows 构建脚本
- 必要的冻结烟测入口/脚本及其测试

**步骤**

- [ ] 先写失败测试，证明标题/单位中的 `$...$` 保持字面文本；测试必须能在
      `text.parse_math=True` 或 rc_context 时序错误时失败。
- [ ] 将 Figure/Text 的创建也放进含 `text.parse_math=False` 的 rc_context，或对
      所有相关 Text 显式关闭 parse_math；选择最小且可测的实现。
- [ ] 构建环境设置 `MPLBACKEND=Agg`，排除实际不需要的 Qt/Tk/Wx/GTK/macOS/
      web/nbagg GUI backend、`matplotlib.tests` 与 `tkinter`。
- [ ] 排除已经过目标 PDF/SVG 路径验证未使用的 fontTools 子包：`qu2cu`、
      `cu2qu`、`ufoLib`、`voltLib`、`mtiLib`、`merge`。
- [ ] PyInstaller 收集完成后、冻结烟测前删除 `mpl-data/sample_data`，并按四文件
      精确白名单裁剪 `mpl-data/fonts/ttf`；保留 AFM 与 pdfcorefonts。
- [ ] 在同一次构建中记录裁剪前和裁剪后的 `_internal` 总字节数及文件数，避免用
      site-packages 安装体积代替冻结产物体积。
- [ ] 冻结产物运行四种 kind（time/fft/fft_time/order_time）× PNG/PDF/SVG，标题
      强制含 `单帧振动加速度`。检查 12 个非空有效文件、CJK 无 glyph-missing
      warning、PDF 文字可提取且不是 tofu、Turbo 色图取样正确。
- [ ] 再试验排除 `mpl_toolkits`；只有同一冻结烟测仍通过才保留，否则撤回。

**验证**

- [ ] batch renderer 目标测试（包含 RED→GREEN 证据）
- [ ] Windows full 和 lite 构建脚本测试
- [ ] 至少一个真实 Windows 冻结目录完成 12 输出烟测并记录裁剪前后体积

## Task 3: 渲染后端不可用时仅降级数据输出

**范围**

- `mf4_analyzer/batch.py`
- `mf4_analyzer/batch_manifest.py`
- `mf4_analyzer/batch_output.py`（仅在保持单一原子写入权威所必需时）
- BatchRunResult/manifest/UI 文案与对应测试

**步骤**

- [ ] 先写注入式失败测试：data+image + backend import unavailable 只发布 CSV，
      无 PDF、无 stage/reservation/partial 残留，manifest 可重新加载；image-only
      失败；data-only 不触发渲染探测。
- [ ] 在 reservation 之前探测所请求的渲染后端并计算 effective outputs。
- [ ] data+image 的已知 import-unavailable 情况只为 data 建 reservation/writers，
      item=`done` 并记录固定中文 warning/degraded reason；run=`partial` 且
      `degraded_count > 0`。
- [ ] manifest 记录 requested/effective outputs；resume 发现请求图片缺失时不得把
      降级项标为 resumed。
- [ ] 任意实际 image writer/render 异常继续使用原有 atomic rollback；保留现有
      “图片写入失败时 CSV 也不发布”测试。
- [ ] UI 将纯降级 partial 与 failed/blocked 区分，不能把降级项称为失败任务。
- [ ] 所有 output schema 规则仍由 GUI-free `validate_outputs` 单一权威提供；不新增
      runner/UI 重复校验。

**验证**

- [ ] batch runner/output/manifest 目标测试
- [ ] `tests/test_batch_validation.py`
- [ ] BatchSheet runner/smoke 目标测试

## Task 4: 统一圆角 popup shell 并修复 SignalPicker

**范围**

- 新建或现有 `mf4_analyzer/ui_kit/popup_shell.py`
- `mf4_analyzer/ui_kit/combo_popup_shell.py`
- `mf4_analyzer/ui_kit/menus.py`
- `mf4_analyzer/ui/drawers/batch/signal_picker.py`
- popup/SignalPicker/completer tests

**步骤**

- [ ] 先扩充业务组件测试：SignalPicker popup 必须保留 `Qt.Popup`，含
      Frameless/NoDropShadow，启用 translucent，且 `frameShape()==NoFrame`。
- [ ] 公共 helper 只追加 shell flags 并启用 translucent，必须保留已有 window
      flags，且重复调用安全；类型特定的 `QFrame.NoFrame` 和 combo 私有 container
      stylesheet 留在各自实现层。
- [ ] SignalPicker 使用 helper，不再手写第二份 flags；combo 和 menus 复用同一常量
      或 helper。
- [ ] 给 SearchableCombo completer popup 补 shell 属性回归测试；现有创建/prepare
      时序已覆盖，不为不存在的时序缺陷添加生产代码。
- [ ] glass tooltip 只做真实 Windows 截图检查；只有复现相同黑边才改并补专属测试。
- [ ] Windows 真实桌面（非 offscreen、非 `widget.grab()`）显示实际 SignalPicker，
      用桌面合成截图按 DPR 检查四个圆角外部像素仍为宿主背景，并保存整屏及裁剪证据。

**验证**

- [ ] `tests/ui/test_batch_signal_picker.py`
- [ ] `tests/ui/test_combo_popup_shell.py`
- [ ] Windows 桌面合成截图与像素探针

## Task 5: 冻结包端到端验收、文档与 lessons

- [ ] 使用新冻结包跑三份不同 source identity 的 `EpsDrvrSteerTq`，请求 CSV+PDF。
- [ ] 断言六个非空输出，三个 manifest item 均同时含 data/image format、size、
      checksum，且没有 `.partial.json`、stage、reservation 残留。
- [ ] 若仓库/机器上没有三份用户数据，使用三个独立生成的最小 MF4 fixture 完成
      自动验收，并把“真实用户数据未提供”作为单独人工验收项，不伪称已完成。
- [ ] 运行完整相关测试、`git diff --check`，复核没有版本号漂移。
- [ ] 新增或更新 lessons：冻结依赖契约必须覆盖产品源码入口；裁包必须以冻结目标
      路径的实测 smoke 为证据；圆角 popup 使用公共 shell 且属性测试不能替代真实
      Windows 合成截图。

## 验收标准

- 冻结包的 12 组合渲染烟测全部通过，PDF CJK 可读，Turbo 映射正确。
- 冻结包三文件 × CSV/PDF 产生六个完整产物及可校验 manifest。
- Matplotlib root exclusion 回归会被 flavor-aware 契约测试阻止。
- 裁剪前/后真实 `_internal` 字节数和文件数有记录。
- SignalPicker 的属性测试与 Windows 桌面像素验收均通过，圆角外无黑边。
