# Windows 包体积缩小 + 启动加速 — 调查与优化方案报告

- 日期：2026-07-13
- 模式：只读调查 + 本机（macOS dev, offscreen）量化测量；未改动产品源码与打包脚本。
- 范围：`tools/build_windows_folder.ps1` 打包链、启动 import/构造全链路、依赖装机体积。
- 打包侧结论基于旧构建 COLLECT 清单与装机 site-packages 实测；**Windows 成品机上的
  分段计时（冷启 vs 热启）尚未采集**，见 §7 验证方法。

## 0. 结论先行

**「体积大 / 碎片多 / 启动慢」三个症状同根：onedir 把 ~1500 个文件、500MB+ 平铺进
`_internal`，每次双击都要从磁盘拉起这棵树，首启/更新后还要再付一次 Windows
Defender 全树扫描。** 打包脚本自己已经写明这一点并在冒烟前先热身启动一次
（`tools/build_windows_folder.ps1:279-284`：*"first launch pays a Windows Defender
scan and a cold load of the 500 MB+ _internal tree"*）。

- 代码侧（Python import + 窗口构造）在快速 dev 机上总共 **933ms**——它不是 10 秒的
  主导项，但在慢盘 Windows 机上会放大到 2-4 秒，且全程无 splash，用户看到的是
  纯黑等待。
- 优化分三层：**打包裁剪**（减文件数/字节数，体积与冷启动同时受益）、
  **代码惰性化 + splash**（削掉可延迟的 1-3 秒 + 消除黑屏感知）、
  **环境/分发**（签名、Defender 排除指引——对 10 秒问题可能是最大单项）。
- **onefile 能消灭碎片但会让启动更慢**（每次解压 500MB 到临时目录），两个诉求
  同时存在时应**保持 onedir**，靠裁剪减小树、靠签名/排除减轻扫描。

## 1. 现状事实（已核实锚点）

### 1.1 打包配置

权威配置是 **`tools/build_windows_folder.ps1`**（每次构建重新生成 spec；
`build/spec/MF4DataAnalyzer.spec` 是过时残留，改它无效，lesson 已记录：
`docs/lessons-learned/pyqt-ui/2026-06-23-gl-viewport-needs-full-update-mode-else-pan-blanks.md:77`）。

| 维度 | 取值 | 锚点 |
| --- | --- | --- |
| 模式 | onedir + windowed | ps1 `:210/:212-216` |
| UPX | `--noupx`（**有意关闭**：UPX 压 Qt GL DLL 曾致冻结后渲染故障） | ps1 `:202-209` |
| excludes | pyxcp、pya2l、matplotlib、scipy | ps1 `:230-240` |
| collect | `--collect-submodules pyqtgraph`；`--collect-all qtawesome, asammdf` | ps1 `:241-244` |
| vendoring | pyxcp + pya2ldb 各一整份自包含闭包（含依赖）作为 add-data | ps1 `:97-144` |
| 后处理 | MSVCP140 覆盖 + 热身启动 + `--acquisition-runtime-smoke` | ps1 `:257-302` |

### 1.2 体积与碎片构成

旧构建 COLLECT 落盘清单 ≈**1502 个文件**：448 `.pyd`、248 裸 `.py`、218 `.png`、
**150 个 Qt 翻译 `.qm`（单语应用纯冗余）**、100 `.ttf`、94 `.dll`。

装机体积大头（`.venv-build-win/Lib/site-packages` 实测，总 562M）：

| 包 | 装机 | 进包原因 | 启动时是否加载 |
| --- | --- | --- | --- |
| PyQt5 | 148M | 硬依赖；翻译/插件零裁剪 | 是（DLL 部分） |
| pandas | 67M | `io/loader.py:7` 顶层 import | **是（可延迟）** |
| numpy + OpenBLAS | 33M + 20M | 硬依赖 | 是 |
| asammdf | 9.6M（collect-all 全量） | `io/loader.py:11` 顶层 try-import | **是（可延迟）**，还连带 canmatrix→openpyxl |
| av / PyAV + ffmpeg | 数十 MB 级 DLL | **未 exclude**；唯一用点 `io/loader.py:465` 懒加载 | 否（只占体积/扫描） |
| qtawesome | 6.1M（collect-all） | 图标硬依赖 | 是（24 个 ttf 每次启动 MD5+加载） |
| pyxcp/pya2ldb vendored ×2 | 若干 | 采集功能 | 否（惰性；只占体积/扫描） |

已生效的裁剪：`--exclude-module scipy/matplotlib` 避开约 180M（两轮迁移的成果，
`docs/superpowers/specs/2026-06-21-scipy-to-numpy-windows-design.md:13`）。

### 1.3 启动链量化（macOS dev 机，offscreen，热缓存——Windows 慢盘按 2-4× 放大估计）

```text
imports(app shim + PyQt5)      32 ms
import mf4_analyzer.ui        216 ms   ← 其中 io/loader 191ms（pandas 118 + asammdf 72→canmatrix→openpyxl）
setup_chinese_font              1 ms   （no-op 兼容桩）
QApplication                    4 ms
字体枚举+QSS(64KB)+tooltip     22 ms
MainWindow() 构造             602 ms   ← 64.5%
show + 首批事件                57 ms
TOTAL                         933 ms
```

`MainWindow()` 602ms 无单一热点，是「碎刀」：ChartStack 156ms、Inspector 144ms、
FileNavigator 118ms、427 次 `addWidget` 共 124ms；**4 个 canvas 启动即建**
（time 在 `chart_stack/stack.py:72`；fft/fft_time/order 三张卡在
`analysis_section_page.py:101` 急切调 factory，`stack.py:133-152`），首个
`qta.icon()`（`cards.py:179`）在此触发 **qtawesome 全量字体加载（24 个 ttf 逐个
MD5 校验 + QFontDatabase 注册 + charmap JSON 解析），且每次启动都发生**（PNG 箭头
缓存 `~/.mf4-analyzer-cache/icons/` 只免掉 subcontrol 渲染，不免字体加载）。

其它已确认事实：**无 splash**（`app.py:84-85` 构造完才 `show()`，全程黑屏）；
acquisition/python-can/pyxcp/硬件探测**全部惰性**、不在冷启动链
（`window.py:1901-1923` 三击 logo 才 import）；`batch.py` 惰性
（`window.py:2577` 才 import）；markup 编辑器模块被 `window.py:277` →
`markup/__init__.py:1` 急切拉入（可延迟）；QSettings 读取均为小 blob。

## 2. 归因

### 2.1 体积大

1. onedir 全依赖平铺（模式属性）；
2. `--noupx` 字节原样落盘（历史正确性决策，不建议翻案）；
3. PyQt5 全量：150 个 `.qm` 翻译 + 全插件零裁剪；
4. `--collect-all asammdf/qtawesome` 过度收集（asammdf 488 条 COLLECT 引用）；
5. PyAV/ffmpeg 未排除（服务音视频 A 计权导入这一个功能）;
6. pyxcp+pya2ldb 双份 vendored 闭包；
7. 248 个裸 `.py` 未字节码化、未 strip。

### 2.2 碎片多

onedir 模式的直接后果（1502 文件），其中 150 `.qm` + 248 `.py` + 部分未用插件
属可削减冗余；其余（448 `.pyd`、94 `.dll`）是运行必需。

### 2.3 启动 ≥10s

| 层 | 因素 | 量级估计 |
| --- | --- | --- |
| 打包/环境（主导） | 首启/更新后 Defender 全树扫描 + 500MB/1500 文件冷 I/O；未签名 exe 加重扫描 | 数秒至 >10s（机器/盘/AV 策略相关） |
| 代码-import | pandas+asammdf 顶层 import（启动时无文件可加载，纯浪费） | dev 191ms；慢盘冷 pyd 加载 0.5-2s |
| 代码-构造 | 4 canvas 急切建 + qtawesome 24 ttf 每次启动加载 + markup 急切 import | dev ~650ms；Windows 1-2s |
| 感知 | 无 splash，全程黑屏 | 把上述全部时间变成「无响应感」 |

## 3. 优化方案

### 3.1 行动包 P1 — 打包裁剪（改 ps1，低风险，体积+冷启动同收益）

| 项 | 做法 | 预计收益 | 风险 |
| --- | --- | --- | --- |
| P1-a 删 Qt 翻译 | ps1 后处理段（仿 `:257-277` MSVCP 段）`Remove-Item _internal\PyQt5\Qt5\translations\*.qm` | -150 文件、数 MB | 极低 |
| P1-b 字节码化 | 构建加 `optimize=2` / `PYTHONOPTIMIZE`，去 248 个裸 `.py` | 数 MB、-200+ 文件 | 低 |
| P1-c 收敛 collect-all | `--collect-all asammdf` → 精确 hidden-imports + `--collect-data`；qtawesome 仅留字体+charmap | 中（asammdf 全子模块含无关后端） | 中：asammdf 动态 import 易漏，必须跑打包冒烟 |
| P1-d Qt 插件白名单 | 审计 `_internal\PyQt5\Qt5\plugins`（sqldrivers/imageformats 多余项等）后处理删除 | 数十 MB 级潜力 | 中：漏删运行时缺插件，需逐项 grep+冒烟 |

### 3.2 行动包 P2 — 代码惰性化 + splash（改产品代码，低-中风险，启动直接受益）

| 项 | 做法（落点） | 预计收益 | 风险 |
| --- | --- | --- | --- |
| P2-a lazy pandas/asammdf | `io/loader.py:7,11` 的顶层 import 移入真正读文件的方法；`HAS_ASAMMDF` 改 `importlib.util.find_spec` 探测 | dev 191ms / Windows 冷启 0.5-2s | 低：需全仓 grep `HAS_ASAMMDF`/`pd.` 的模块级引用 |
| P2-b splash | `app.py:83` 后 `QSplashScreen(pixmap).show()+processEvents()`，构造完 `splash.finish(window)` | 感知收益最大（黑屏→有反馈） | 极低 |
| P2-c lazy 三张分析卡 | `analysis_section_page.py:101` 改为首次切到该 section 才 `_make_card()`（factory 已存在，`stack.py:133-152`） | dev ~200-300ms 构造 + 推迟 qtawesome 字体加载 | 中：测试假定 canvas 启动即存在，需同步调整；切页首次延迟移到用户可感知点 |
| P2-d help 按钮去 qtawesome | `window.py:314` `qta.icon('mdi.book-open-variant')` 换程序化 `Icons`（toolbar/navigator 已是此做法） | 配合 P2-c 后启动零 qta 调用 → 24 ttf 加载整体推迟 | 低 |
| P2-e lazy markup | `markup/__init__.py:1` 不再包级 import `MarkupEditor`，`window.py:299` 用点惰性 import | 小（模块+qtawesome 链） | 低 |

### 3.3 行动包 P3 — 环境/分发（非代码，可能是 10 秒问题的最大单项）

1. **代码签名**：未签名 exe 每次启动都可能被 Defender/SmartScreen 深度检查；签名
   显著降低扫描惩罚。
2. **部署指引**：企业环境把安装目录加入 Defender 排除项（IT 策略允许时）；
   避免装在网络盘/同步盘（OneDrive 实时同步 1500 个文件是启动灾难）。
3. **保持 onedir**：不要为消碎片切 onefile——每次启动解压 500MB 会让 10 秒变
   更久；碎片诉求靠 P1 削减 + 分发时 zip/安装器包裹解决。

### 3.4 明确不做 / 需要产品决策

| 项 | 结论 |
| --- | --- |
| 重开 UPX（白名单） | **不建议**：`--noupx` 是历史正确性决策（GL DLL 压缩致渲染故障） |
| 排除 `av`（PyAV/ffmpeg） | **产品决策**：省数十 MB + 减扫描面，但 Windows 包失去音视频导入（2026-06-20 的 A 计权功能）。保留/砍掉由产品定 |
| onefile | 不建议（§3.3.3） |
| 精简 pandas/numpy 本体 | 不可行，硬依赖 |

## 4. 约束红线（实施前必读）

1. `tests/test_windows_build_script.py` 硬断言 `--onedir/--windowed/--collect-all
   qtawesome/asammdf` 等 token（`:11-24`）——改打包参数必须同步改测试。
2. 改完任何打包参数，必须重跑 `--acquisition-runtime-smoke`（ps1 `:285-302`）
   和一次真机手动启动验证。
3. `--noupx` 决策及其 lesson 不动。
4. P2 改动照常受既有测试网约束（pytest 前台 offscreen 全绿）；P2-c 涉及
   canvas 存在性假设的测试需逐个排查，不允许为过测试 stub 掉延迟语义。

## 5. 预期总收益（诚实口径）

| 措施组合 | 体积 | 碎片 | 启动 |
| --- | --- | --- | --- |
| P1-a/b（快赢） | -10~20MB | -350 文件 | 冷启动小改善（扫描面减小） |
| P1-c/d（第二批） | 潜力数十 MB | 再减几十文件 | 同上 |
| P2 全套 | ~0 | 0 | dev 侧 -0.4~0.6s；Windows 冷启预计 -1~3s；感知改善质变（splash） |
| P3 签名/排除 | 0 | 0 | **可能是 10s→数秒的关键**，取决于用户环境 |
| （若砍 av） | -数十 MB | -几十文件 | 扫描面再减 |

**兜底认知**：Python + PyQt5 + pandas/numpy 的桌面应用，Windows 冷启动做到
2-4 秒是现实目标；「秒开」不是——除非换打包技术栈（Nuitka standalone 等），
那是另一个量级的工程且有兼容风险，本报告不推荐现在做。

## 6. 建议实施顺序

1. **先测后改（§7）**：在目标 Windows 机上采集冷/热启动分段数据，确认 Defender
   /I/O 占比——若热启动已经 ≤3s，P3（签名/排除指引）优先级立即升到最高。
2. P2-b splash + P2-a lazy pandas/asammdf + P2-d/e（一次小 PR，纯代码，回归网现成）。
3. P1-a/b（一次 ps1 PR + 测试 token 同步 + 打包冒烟）。
4. P2-c lazy 分析卡（单独 PR，测试面较宽）。
5. P1-c/d 收敛收集与插件白名单（单独 PR，逐项验证）。
6. `av` 取舍与代码签名流程，等产品/分发决策。

## 7. 验证方法（实施前后各跑一遍）

Windows 目标机：

```powershell
# 冷启动（重启后首次）与热启动（紧接着第二次）各测 3 次：
Measure-Command { Start-Process .\TraceLab7.5.exe -Wait:$false; <等待主窗可交互> }
```

- 冷/热差值 ≈ Defender+磁盘冷 I/O 占比（P1/P3 的靶子）；
- 热启动本身 ≈ 代码侧成本（P2 的靶子）；
- 可在 `app.py main()` 里加临时 `time.perf_counter()` 分段日志（写文件，windowed
  无 console）复刻本报告 §1.3 的分段，打包后对照。
- 体积/碎片：`(Get-ChildItem -Recurse _internal | Measure-Object).Count` 与
  `du`，对照本报告 1502 文件 / 500MB+ 基线。

## 8. 证据附录

- 打包体积/碎片调查（2026-07-13 探查）：ps1 `:97-144/:198-249/:257-302`、
  COLLECT-00.toc 统计、site-packages du、`requirements*.txt`。
- 启动链调查（2026-07-13 探查）：`app.py:64-90`、`io/loader.py:7,11,465`、
  `window.py:24,277,314,1901-1923`、`analysis_section_page.py:101`、
  `chart_stack/stack.py:72,133-152`、`cards.py:173-202`、
  `ui_kit/icons.py:436-548`、`pg_canvas/fonts.py:20-88`、
  `ui_kit/stylesheet.py:20`（QSS 64KB）。
- 本机测量（macOS dev, offscreen）：importtime top（`mf4_analyzer.ui` 251ms，
  内 pandas 118ms/asammdf 72ms）；分段计时（总 933ms，MainWindow 602ms）；
  cProfile（ChartStack 156ms / Inspector 144ms / Navigator 118ms /
  427×addWidget 124ms）。
