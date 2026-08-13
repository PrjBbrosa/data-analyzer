# UltraView P0 补完与加固规格

- 日期：2026-08-13
- 状态：**READY FOR REMEDIATION，当前实现仍为 NO-GO**
- 当前实现基线：`8d6d80f1f67b13ba149fd6ff6ca141c1886822af`
- 当前主线基线：`8cdc095c4143402d586671bb7e9bb2079e7d9d05`
- 上游产品规格：
  `docs/analyzer/specs/2026-08-12-ultraview-p0-spec.md`
- Supersedes（剩余实施合同）：
  `docs/analyzer/plans/2026-08-12-ultraview-p0-implementation.md`
- 配套计划：
  `docs/analyzer/plans/2026-08-13-ultraview-p0-completion-hardening-plan.md`

## 0. 文档效力与结论

`8d6d80f1` 已完成 UltraView 的大部分 P0 骨架：Qt-free BoardState、六种布局、
PreviewStore、只抓已有可见画布的捕获管线、页内 View 库、Board/托盘、第五个
Inspector context、第六模式和一批聚焦测试。技术路线仍成立，不需要推倒重做。

但当前实现不能作为 P0 成品合入或发布。阻断项不是视觉微调，而是生命周期崩溃、
项目数据未保存、导出按钮无接收端、项目重置会永久拆断交互，以及 inactive View
digest 读取 active canvas 的身份污染。本规格只补齐这些缺口并收紧验收，不扩张到
P1/P2。

本规格与 2026-08-12 P0 spec 的关系：

- 原 spec 继续定义产品目标、2/4/6 布局、四态、零计算、预览预算和非目标；
- 本规格覆盖原 plan 中已被实现证明不完整或实现错误的部分；
- 两者冲突时，以本规格对生命周期、持久化、导出、digest、信号和验收的修订为准；
- HTML 原型继续只作为交互方向，不作为运行时或验收证据。

## 1. 当前证据与问题清单

### 1.1 已证实阻断项

| ID | 严重度 | 当前事实 | 用户影响 |
|---|---|---|---|
| UV-R01 | P0 | `PreviewStore.__init__()` 将 Python closure 连接到自身 `destroyed`，closure 在 QObject 析构阶段改写含 QImage 的记录 | MainWindow/Store 销毁可触发 Qt/Python 生命周期崩溃 |
| UV-R02 | P0 | `UltraViewCoordinator.clear()` 同时清数据、timer、canvas hooks 和 page/Inspector hooks | 清项目一次后，UltraView 页面按钮永久失联 |
| UV-R03 | P0 | `close_all()` 在“无文件”和用户确认之前调用 `uv.clear()` | 用户取消关闭也会丢 Board/预览并拆断信号 |
| UV-R04 | P0 | `ProjectDocument`、save/open 路径没有 `ultraview` 字段，也直接保存 `chart_stack.current_mode()` | Board 不能随 `.tlproj` 保存；在总览保存会写旧版未知 mode |
| UV-R05 | P0 | `copy_board_requested`、`copy_card_image_requested`、`export_png_requested` 没有 coordinator receiver；仓库没有 compositor | 复制与 PNG 控件可点击但不产生成品 |
| UV-R06 | P0 | `_analysis_payload()` 对任意 ref 都读取该 section 当前 page 的 `pane_count()` 与 markup；时域也会 fallback 到 active canvas | inactive View 会因另一个 active View 的运行态变化而误判 stale/fresh |
| UV-R07 | P1-for-P0 | Inspector 能改 `show_titles/show_sources`，但 Page 投影始终传 title/source | 保存的显示选项不生效 |
| UV-R08 | P1-for-P0 | `PreviewStore.touch()` 只有单元测试直接调用，卡片、焦点与导出读取没有 touch | 未放置预览的 LRU 次序不是实际使用次序 |
| UV-R09 | P1-for-P0 | `hints.py`、`quickref.py`、help guide、截图工具与打包面没有 UltraView | 功能缺少发现性和随包帮助 |
| UV-R10 | P1-for-P0 | 零计算序列没有覆盖演示、复制、导出、保存；teardown test 没有断言进程安全 | 现有绿测不能证明完整 P0 操作链 |

### 1.2 主线集成状态

2026-08-13 已按用户要求把 `feat/ultraview-p0` rebase 到 `origin/main@8cdc095c`；
实现提交由 `f625ae43` 等价重写为 `8d6d80f1`。`git range-diff` 显示实现补丁与文档
补丁均保持等价，分支相对主线为 `0 behind / 2 ahead`。

rebase 前双方在下列 9 个文件上同时有变化：

```text
mf4_analyzer/ui/main_window/_analysis_mixin.py
mf4_analyzer/ui/main_window/_project_io_mixin.py
mf4_analyzer/ui/main_window/_view_mixin.py
mf4_analyzer/ui/main_window/window.py
mf4_analyzer/ui/pg_canvas/line_canvas.py
mf4_analyzer/ui_kit/style.qss
tests/ui/test_chart_stack.py
tests/ui/test_pg_line_canvas.py
tests/ui/test_pg_timedomain_canvas.py
```

rebase 没有产生文本冲突；以上 9 个文件已按双方 diff 做语义复核，没有使用
ours/theirs 整文件覆盖。UltraView 聚焦集为 `80 passed`。重叠 owner 组合在 feature
上为 `704 passed / 3 failed`，同一组合在原样 `origin/main` 上为
`702 passed / 3 failed`，且相同三个节点单独运行均为 `3 passed`；因此记录为既有
测试顺序/Qt 全局状态基线，不作为 UltraView rebase 回归，也不在本次顺手修复。

## 2. 补完目标与非目标

### 2.1 完成目标

P0 补完后必须同时成立：

1. MainWindow/PreviewStore 可反复创建、关闭和销毁，不发生 abort、segfault 或析构回调；
2. 新项目、打开项目、关闭全部和关闭窗口各走自己的生命周期语义；
3. Board 布局、引用、托盘、名称和显示选项能随 `.tlproj` round-trip；
4. 复制整板、复制单卡和 PNG 1×/2×真实可用，且不抓源、不计算；
5. 每个 ref 的 digest 只读取该 ref 的状态和与它绑定的运行态；
6. 所有用户可见控件都有接收端或明确禁用，不存在“假按钮”；
7. 完整 P0 序列的计算、任务、cache 写入、restore pending 和源 View 快照不变；
8. hints、quickref、help、截图和打包资源与成品一致；
9. 聚焦测试、架构门禁、两进程全套回归和 macOS Cocoa 前景证据分层报告。

### 2.2 本轮不做

- 不做 preview sidecar，不把 QImage 写入项目；
- 不做后台补算、cache miss 重算或独立数值 renderer；
- 不做 PDF/SVG、自由画布、超过 6 个屏上槽位或多 Board；
- 不把卡片改成 live canvas，不 reparent 源 QWidget；
- 不重构五个 source section 的全局常量体系；
- 不顺手修复与 UltraView 无关的主线 baseline debt；
- 不以 offscreen 测试替代 Cocoa 前景或 Windows frozen 验收。

## 3. 生命周期与状态所有权合同

### 3.1 PreviewStore

`PreviewStore` 是 GUI 线程中的普通 QObject 数据 owner。它必须满足：

- 不把 Python closure、bound method 或 lambda 连接到**自身** `destroyed` 以清理 QImage；
- 像素释放由 owner 在 QObject 仍有效时显式调用 `clear()`；
- `clear()` 幂等，只清 records、pinned、clock 和统计，不连接/断开外部信号；
- parent 销毁时即使漏调显式 clear，也必须由 Python/Qt 正常析构，不能执行晚期回调；
- `publish/drop/clear/set_pinned_refs` 继续只允许 GUI 线程；
- 销毁安全必须用独立子进程测试，因为 abort 不能被普通 pytest exception 断言捕获。

### 3.2 Coordinator 的三种动作

`UltraViewCoordinator.clear()` 语义拆成具名动作：

| 动作 | 使用时机 | 清 Board/Store | 清 runtime ledger/timer/canvas hooks | 断开 Page/Inspector/Stack hooks |
|---|---|---:|---:|---:|
| `reset_project_state()` | 新建、成功关闭全部、打开另一个项目前 | 是 | 是 | 否 |
| `restore_project_state(payload)` | managers/View IDs 就绪后 | 替换 Board；Store 保持空 | 清旧 runtime | 否 |
| `shutdown()` | MainWindow 最终 closeEvent | 是 | 是 | 是 |

补充约束：

- `attach()` 只能执行一次，或具备显式去重；project reset 后不能重复连接；
- `shutdown()` 幂等，先停 timer、断信号，再清 QImage；随后才允许 `deleteLater()`；
- queued callback 只能捕获 weak handle 和不可变 ref/digest，执行前复核 coordinator、
  widget、binding 与 digest；shutdown 后 queued callback 必须 no-op；
- `_page_hooks` 与 `_hooks` 是连接登记表，不是项目数据，不得在 reset 时清空。

### 3.3 新建、打开、关闭全部与关闭窗口

- `close_all(force=False)` 必须先判断是否有文件、收集引用并完成用户确认；只有确认后
  才调用 `reset_project_state()`；取消时 Board、Store、hooks 和源状态全部不变；
- `close_all(force=True)` 无对话框，但仍只 reset 一次；
- 没有已加载文件时调用 close-all 不得丢弃用户刚恢复/配置的 Board；
- `open_project()` 在用户已选择有效文件、读取成功且准备替换当前项目时 reset；解析失败
  或选择取消不得清当前 Board；
- MainWindow `closeEvent()` 调用 `uv.shutdown()`，随后关闭 analysis jobs，再交给 super；
- 项目 reset 后页面所有 add/layout/ratio/focus/open/copy/export 信号仍有且只有一个接收端。

## 4. `.tlproj` 持久化与兼容合同

### 4.1 数据形状

顶层 `SCHEMA_VERSION` 继续为 2。`ProjectDocument` 在 dataclass **末尾**追加：

```python
ultraview: dict | None = None
```

JSON 形状沿用原 P0 spec：

```json
{
  "schema_version": 2,
  "current_mode": "fft",
  "ultraview": {
    "schema": 1,
    "board": {
      "board_id": "...",
      "name": "全局对比",
      "layout_id": "hero_left_4",
      "primary_ratio": 0.67,
      "show_titles": true,
      "show_sources": true,
      "placements": [],
      "unplaced": []
    }
  }
}
```

禁止写入：QImage、digest、runtime ledger、selected、comparison filter、focus、presentation、
侧栏 snapshot、LRU/statistics、cache 或 job 状态。

### 4.2 保存

- coordinator 暴露 `to_project_payload()`，只返回合法化后的 Qt-free dict；
- 当前 mode 为 source section 时照常保存；当前 mode 为 `ultraview` 时保存
  `last_source_mode`；无合法历史时为 `time`；
- 保存前不得把 UltraView 当 time/analysis page 做 capture 或 state apply；
- Board name、layout、ratio、placements、unplaced、`show_titles/show_sources` round-trip；
- 顶层 schema 不升级，保护旧版读取现有字段。

### 4.3 加载与退化

- `load_project()` 对 `current_mode` 使用五个 source section 白名单，未知值回退 `time`；
- 缺少 `ultraview` 时创建默认空 Board；
- nested schema/layout/ratio/ref/重复项继续走 `normalize_board_payload()` 并返回 warnings；
- warnings 进入既有项目恢复可见路径或带上下文日志，不能静默吞掉；
- 在 time/analysis managers 与稳定 view_id 恢复完成后，再恢复 Board；找不到的合法 ref
  保留为 orphaned；
- 重开后 PreviewStore 为空，所以合法 ref 为 missing、缺失 ref 为 orphaned；不补算；
- 新项目被旧版打开后再次保存会丢 `ultraview`，这是已接受的向后写回限制。

## 5. 导出、复制与信号闭环合同

### 5.1 必须闭环的页面信号

coordinator 必须显式连接并登记：

```text
copy_board_requested       -> copy_board_to_clipboard()
copy_card_image_requested  -> copy_card_to_clipboard(ref)
export_png_requested       -> choose_and_export_png(scale)
```

`locate_ref_requested` 与 `rebind_arm_requested` 若页面内部已经完整处理，必须删除无消费的
冗余上行信号，或为它们定义真实 coordinator 行为；不能保留看似产品事件、实际无人接收
的接口。每个用户可见动作都要有 receiver-count/行为测试。

### 5.2 Compositor

新增 `ui/chart_stack/ultraview/compositor.py`，它接收不可变 Board 投影与 PreviewRecord
快照，不接收 MainWindow、UltraViewPage 或 QWidget screenshot。

- 1× 固定输出 1600×900，2× 固定输出 3200×1800，DPR=1；
- 使用 `layouts.py` 同一模板、slot 顺序、ratio 和 gutter；
- 绘制 Board 名、可选标题、可选来源、状态、卡片 chrome、预览或 missing 占位；
- 只合成 placements，不把 View 库、Inspector、托盘、滚动位置或 comparison dim 写入；
- fresh/stale/orphaned 可使用最后有效图，missing 只能画明确占位；
- 卡图 contain-fit，任何方向不超过 raw 100%，2× 只提升 chrome/版面分辨率；
- 不调用 QWidget.grab、源 render、`do_*`、job service 或 cache store；
- image allocation/save/clipboard 失败返回结构化错误，由 coordinator toast + warning；
- PNG 使用临时同目录文件成功保存后 `os.replace`，失败不遗留伪成功空文件。

### 5.3 LRU 与显示选项

- 卡片真实显示有效 image、打开焦点层、复制单卡、整板合成时调用 `store.touch(ref)`；
- 构建 library row 或只查状态不算真实使用，不 touch；
- `show_titles=False` 时卡片与 compositor 隐藏标题但保留状态/可访问名称；
- `show_sources=False` 时卡片与 compositor 隐藏来源摘要；
- Board 名称至少提供一个非拖拽、可键盘完成的编辑入口，修改后立即更新 BoardState；
- Esc 优先级最终为 focus → replacement → presentation → popup；退出 presentation 必须
  通过 coordinator 恢复右 Inspector snapshot。

## 6. Per-ref presentation digest 合同

### 6.1 禁止 active canvas 污染

对 ref A 计算 digest 时，禁止读取只属于 ref B 的 active page/canvas 运行态。以下写法
均不允许：

- 仅按 section 取得 `_analysis_page(section)` 后无条件读取 `pane_count/markup_revision`；
- 找不到 ref 绑定后 fallback 到 `canvas_time` 或 section page；
- 用当前 active index、标题或 list index 替代稳定 view_id；
- 为修复误判而删掉 markup/result generation 字段。

### 6.2 Runtime ledger

coordinator 拥有项目级、进程内 `PresentationRuntimeLedger`，key 为 `UltraViewRef`，只存
无法从 ViewState 重建的轻量运行事实：

```python
@dataclass(frozen=True)
class PresentationRuntimeFacts:
    markup_revision: int = 0
    visible_pane_count: int | None = None
```

规则：

- ViewState/PaneState、params、ranges、sources、pins、result generation 仍从该 ref 自身
  的 manager/cache owner 读取；
- 只有 `bound_ref_for(widget) == ref` 时，才允许从 widget 读取 markup/pane 运行事实；
- 成功 capture 时把匹配 ref 的事实提交到 ledger；inactive ref 使用自己的最后事实；
- active ref 在标注变化后，即使尚未重新 capture，也应通过匹配 binding 读到新 revision
  并判 stale；
- 切换到另一个 ref 后，旧 ref digest 保持稳定，不随新 active page 的 pane/markup 变化；
- reset/open/shutdown 清 ledger；项目文件不保存 ledger；
- digest 不可得时仍遵守“有旧图 stale、无图 missing”，不得乐观 fresh。

### 6.3 结果与 pane 身份

- `pane_count` 优先来自该 ViewState 的 pane structure；只有与 ref 匹配的可见捕获上下文
  才可补充运行态；
- cache key/pin/result generation 全部带 `(section, view_id, pane_idx)`；
- 同 key/同 result object 的 cache hit 不推进 generation；同 key 换对象推进；
- inactive view 的 worker completion 可以更新它自己的 generation，但不能抓 active canvas；
- 时域 markup 与分析 markup 使用同一 binding 规则。

## 7. 帮助、视觉与交付合同

### 7.1 帮助与发现性

必须同步：

- `mf4_analyzer/ui/hints.py`：加入总览、托盘、四态、打开来源、导出；
- `mf4_analyzer/ui/quickref.py`：明确“五个分析工作区 + 一个只读总览”；
- `mf4_analyzer/help/__init__.py` 与新 `help/ultraview-guide.html`；
- `tools/gen_help_screenshots.py` 的 mode/context；
- help、quickref、hints、screenshot 和 packaging tests。

不得写入已不存在或 P1 才有的能力：PDF/SVG、自由缩放、后台补图、sidecar、多 Board、
卡片 live 编辑。

### 7.2 视觉与可访问性

- 1100 px 顶栏六 mode 不裁切；需要时六个 mode 统一进入 icon-only 紧凑态；
- 1280×800、1600×900、普通 DPR probe、Retina Cocoa 覆盖 hero/6-grid/托盘/四态；
- `show_titles/show_sources` 关闭后不留下空白占位带；
- keyboard focus、右键菜单、Esc、拖拽和等价按钮路径均可用；
- 自动生成 contact sheet/geometry 检查，不能让用户逐张人工找差异；
- offscreen 只能证明结构和像素规则，Cocoa 前景单独签字，Windows frozen 未跑就写
  `UNVERIFIED`。

## 8. 验收矩阵

| ID | 验收结果 |
|---|---|
| UV-R01 | PreviewStore/MainWindow 子进程反复构造销毁退出码 0，无 Qt abort |
| UV-R02 | reset 后所有 Page/Inspector actions 仍恰好触发一次；shutdown 后为 0 |
| UV-R03 | close-all 取消不改变 Board/Store/hooks；确认后清空且功能仍可继续使用 |
| UV-R04 | schema=2 的 UltraView payload、last source mode、旧项目和非法 payload 全部 round-trip/退化正确 |
| UV-R05 | 复制整板、复制单卡、PNG 1×/2×有真实输出和错误反馈，不存在假按钮 |
| UV-R06 | inactive A 的 digest 不随 active B 的 pane/markup 改变；A 自身变化仍能 stale |
| UV-R07 | show titles/sources 同时作用于屏上与导出，并随项目保存 |
| UV-R08 | card/focus/copy/export 推进真实 LRU；状态查询不推进 |
| UV-R09 | Board name 可编辑并 round-trip；Esc 可按优先级退出所有瞬态层 |
| UV-R10 | hints/quickref/help/screenshot/packaging 全部登记 UltraView |
| UV-R11 | 完整操作序列覆盖演示、复制、1×/2×、保存，三层计算计数为 0 |
| UV-R12 | restore pending、五 manager View 快照、cache/pin、active index 前后不变 |
| UV-R13 | 现有捕获稳定性、DPR、预算、布局、托盘、四态测试合并后继续通过 |
| UV-R14 | state ownership/import boundaries/pg backref/packaging gates 不放宽 |
| UV-R15 | 主套件与 acquisition_ui 两个新进程完整结束；异常退出为 UNVERIFIED |
| UV-R16 | macOS Cocoa 前景通过布局、拖放、焦点、侧栏恢复、clipboard 和 PNG 观感 |
| UV-R17 | 34 个原 `UV-A01…UV-A34` 在最终报告中映射到 R-ID 与实际证据，无遗漏 |
| UV-R18 | Windows Full/Lite frozen 有真实包证据；未执行时明确 UNVERIFIED，不阻塞源码合入但阻塞 Windows 发布签字 |

## 9. Done 定义

只有以下条件同时满足，UltraView P0 才可从 NO-GO 改为可合入：

1. `main` 已合入且 9 个重叠文件完成语义复核；
2. UV-R01～R17 为 PASS，或非发布平台项有产品 owner 明确接受的 UNVERIFIED；
3. 生命周期子进程、项目 round-trip、compositor 与完整零计算链有自动化证据；
4. 两进程全套测试正常退出；
5. Cocoa 前景完成，不以 HTML、source review 或 offscreen 代替；
6. 最终 verification 文档逐项列命令、结果、证据路径和未验平台；
7. 提交范围只含 UltraView 补完、必要兼容和对应 tests/docs，不混入其他功能。
