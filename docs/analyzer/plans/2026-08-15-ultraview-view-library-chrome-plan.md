# UltraView View 库形态优化方案

日期：2026-08-15  
状态：ACCEPTED（用户确认后立即实施）  
原型基线：[2026-08-15-ultraview-view-library-rework-options.html](../ui-prototypes/2026-08-15-ultraview-view-library-rework-options.html)

前一包 `2026-08-15-ultraview-layout-and-material-polish-plan.md` 把 View 库标成非目标。本包只补这一块：把产品 `ViewLibraryPanel` 收到 HTML「展开分组 / 类型概览」形态，并按用户裁掉目录与左侧色条。

## 1. 已确认的决策

1. **两种浏览态，不要第三种。** 默认「展开」：五个分析类型分组，组内直接列出真实 View。另提供「概览」：每类一张摘要卡，点「展开」回到展开态并打开该类。不实现 HTML 里的「目录 / 紧凑目录」。
2. **去掉每个大 section 左侧色条。** 分组卡、概览卡都不用 `--domain` 竖条、彩虹描边或按类型渐变；色条 AI 感过重。行内小圆点仍用该 View 自己的 `tab_color`，那是通道/页签身份，不是装饰条。
3. **不提供「新建」。** UltraView 只引用已有 View，不能在库里创建分析页。概览卡只留「展开」。
4. **保留现有产品合同：** 五类 `SOURCE_SECTIONS`、搜索、加入/移出 Board、拖放、钉住、定位、折叠状态在 rebuild 后仍在。不改 Board schema、零计算、弹层锚点。
5. 材质继续用月白石蓝局部 token（`#FCFDFE` / `#3E709C` / `#EAF2F8` / `#C7D4DF`），不把全局 `CONTROL_COLORS` 改掉。

## 2. 目标形态

```text
┌────────────── View 库 ── 6 个 ── 钉 ─┐
│  搜索 View、信号或分析类型…            │
│  [ 展开 ]  [ 概览 ]                    │
│                                        │
│  按分析类型分组 · 展开后直接操作  收起全部 │
│  ┌──────────────────────────────────┐  │
│  │ 时域                    2        │  │
│  │ 2 个 View                        │  │
│  │  · 转向角 · 时域对比    ＋        │  │
│  │  · 纵向加速度 · 时域    ＋        │  │
│  └──────────────────────────────────┘  │
│  ┌──────────────────────────────────┐  │
│  │ 频谱                    1        │  │
│  └──────────────────────────────────┘  │
└────────────────────────────────────────┘
```

概览态：五张摘要卡，主行是类型名，次行是该类已有 View 名称（` / ` 连接，空类写「暂无 View」），右侧只有「展开」。无色条、无新建。

## 3. 明确不做

- 不实现目录树、不出现「View 1」这类占位名（产品本来就用真实 `row.name`）。
- 不在 View 库创建源 View。
- 不把浏览态写入项目；本次会话内记住即可。
- 不改钉住语义：点画布不关，Esc 仍关。
- 不把月白石蓝铺到分析器其它页面。

## 4. 实施任务

### Task 1：先改 HTML 原型

文件：`docs/analyzer/ui-prototypes/2026-08-15-ultraview-view-library-rework-options.html`

- 顶部架构选项与面板内 tab 都只留「展开 / 概览」，删除「目录」及其 DOM/CSS/JS。
- 去掉 `.group-toggle::before`、`.catalog-card > i` 以及按 `--domain` 上色的左边条/描边/渐变；分组卡改用冷灰边线。
- 去掉所有「新建」按钮。

### Task 2：产品 `ViewLibraryPanel`

文件：`mf4_analyzer/ui/chart_stack/ultraview/widgets.py`、`mf4_analyzer/ui_kit/style.qss`、相关测试。

- 搜索占位改为「搜索 View、信号或分析类型…」；计数「N 个」。
- 增加互斥「展开 / 概览」；默认展开。搜索命中时仍强制展开对应分组（现合同）。
- 分组改成圆角纸面卡片：标题 +「N 个 View」+ 计数徽章 + chevron；**无左边条**。
- 展开态提供「收起全部 / 展开全部」。
- 概览卡点「展开」：切回展开态并打开该类。
- `section_headers()` / `row_widgets()` / 钉住 / 拖放信号保持可测。
- QSS 状态规则只用 `border-color`，不用会打掉圆角的 `border:` 简写。选中行用石蓝 wash，不再用全局强调蓝大底。

### Task 3：说明与回归

- `hints.py` / `quickref.py`：补一句可用概览扫读，仍强调分组可折叠、钉住、＋/−。
- `ultraview-guide.html`：View 库 mock 与「五个分区」说明对齐展开/概览，不写目录。
- 测试：五分组、折叠 rebuild、空组仍在、搜索展开命中、加入/移出颜色可分、钉住；新增：无目录控件、无 section 左边条、概览无新建、概览「展开」切回分组。

## 5. 验证

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_chrome.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_hints.py \
  tests/ui/test_quickref.py \
  tests/test_help_content.py \
  tests/ui_kit/test_qss_border_shorthand.py \
  tests/ui/test_no_lambda_signal_connections.py -q
```

前台仍需看 800×560 / 1280×800：两态切换、无色条、无目录、搜索与钉住仍可用。
