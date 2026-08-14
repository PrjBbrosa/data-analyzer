# UltraView P1 可扩展多 Board 工作区规格

- 日期：2026-08-13
- 状态：`P1 Core IMPLEMENTED 2026-08-14；nested schema 3；sidecar 惰性加载已接线；前景/Cocoa/全量平台验收见 verification 文档`
- 分析起始快照：`main@9c91debf`；成稿时并行实现已推进到 `main@5e36b27a`，且 worktree
  仍有 P0/UI 改动，实施和 Claude 评审必须以届时 HEAD 重新定位符号
- 配套计划：
  `docs/analyzer/plans/2026-08-13-ultraview-p1-scalable-board-workspace-implementation.md`
- 上游规格：
  `docs/analyzer/specs/2026-08-12-ultraview-p0-spec.md`
- P0 补完规格：
  `docs/analyzer/specs/2026-08-13-ultraview-p0-completion-hardening-spec.md`
- 最新入口规格：
  `docs/analyzer/specs/2026-08-13-ultraview-view-rail-dock-spec.md`

## 0. 结论与阶段定位

P1 把 UltraView 从“一张最多 6 图的临时快照板”升级成可以随项目长期保存、按问题组织、
一次容纳最多 12 张图的 **全局对比工作区**。

P1 的产品重点不是把更多 live canvas 塞进窗口，而是：

1. 一个项目可以拥有多个命名 Board；
2. 单个 Board 增加 3×3 与 4×3 模板，最多放置 12 张静态卡片；
3. 大 Board 使用可滚动逻辑画布，卡片不因窗口变窄而无限缩小；
4. 所有 Board 共享同一份稳定 View 预览，不按 Board 复制像素；
5. 预览可通过独立 sidecar 随项目恢复，重开项目不再默认全是 missing；
6. Board 切换、项目保存、预览恢复、整板概览和导出继续保持零分析计算。

P1 仍然是“全局阅读层”，不是新的分析工作区。自由拖拽尺寸、单卡 live 检查和同轴引导
属于 P2，见配套 P2 规格。

## 1. 文档效力与 P0 入口门槛

### 1.1 增量覆盖

本规格覆盖旧文档中以下远期描述：

- “每项目只有一个 Board”；
- “屏上最多 6 个槽位”；
- “项目不保存任何预览像素”；
- P1 仅等同于“缓存结果独立 renderer”。

以下 P0 契约保持不变：

- `UltraViewRef = (section, view_id)` 是唯一身份；
- 卡片是源 View 的只读投影；
- fresh / stale / missing / orphaned 四态由真实状态派生；
- UltraView 不调用分析计算、项目恢复重算或隐藏 View 渲染；
- 不 reparent 源图表 QWidget；
- 源 View 改名/换色更新卡片 chrome，不改变身份；
- 打开源 View 是离开 Board 阅读层的显式导航动作。

入口与宿主以最新 View 栏 Dock 规格为准：UltraView 是独立非模态工具窗，不是顶部第六
分析模式。本规格不得复活 `current_mode="ultraview"` 或全局 Navigator 换页方案。

### 1.2 P0 必须先关闭的问题

P1 开始前，当前 P0 review 中下列正确性问题必须已有测试和合入证据，不能在 P1 中改名
为“增强功能”：

1. 空分析画布不能发布 fresh 预览；
2. 独立工具窗关闭/重开不能遗留 presentation、隐藏主 Inspector 或产生重复窗口；
3. coordinator 必须订阅五个 ViewManager 的创建、删除、改名、换色和重排；
4. orphaned “重新绑定”必须调用 `rebind_ref()`，不能把旧 ref 顶进托盘；
5. PreviewStore LRU 淘汰像素后，相同 digest 的可见 View 必须允许重新抓取；
6. P0 完整零计算、项目 round-trip、复制/导出、两进程测试和 Cocoa 前景证据必须分层记录。

若以上任一项未关闭，P1 状态只能是 `BLOCKED BY P0`。

## 2. 用户场景

### 2.1 多问题线并行

同一项目可能同时存在“整车工况”“左右悬架”“异响问题链”“修改前后”四类对比。
用户不应反复清空一张 Board，而是把每条问题线保存为独立 Board，并在工具窗顶部快速
切换。

### 2.2 9～12 图全局扫描

六张图适合局部对比，但完整工况矩阵常包含 8～12 个 View。P1 允许 3×3 或 4×3，
在 100% 阅读模式下通过滚动浏览，在“整板概览”中一次看到完整结构。

### 2.3 项目重开继续评审

用户保存项目、关闭应用、第二天重开后，应立即看到上次 Board 的预览。若源状态发生变化，
系统仍显示旧图但诚实标记 stale；sidecar 丢失或损坏时只退化为 missing，不破坏项目。

### 2.4 跨 Board 复用同一 View

同一个 FFT View 可以同时出现在“整车工况”和“修改前后”Board 中。它们共享同一预览、
同一 digest 与状态，但各自保存位置。更新一次预览后，两张 Board 都能看到新图。

## 3. P1 目标与非目标

### 3.1 必须交付

- 多 Board 的新建、复制、重命名、删除、切换和重排；
- 2/4/6 既有模板，以及 3×3（9 图）、4×3（12 图）模板；
- 每个 Board 最多 12 个 placed refs，额外 refs 进入该 Board 的托盘；
- 大 Board 的 100% 滚动阅读与整板概览；
- 所有 Board 共用的进程内 PreviewStore；
- 版本化、校验、可丢失的预览 sidecar；
- 活动 Board 优先的内存驻留与延迟加载；
- 多 Board 项目迁移、保存和恢复；
- 全 Board 动态尺寸合成、复制和 PNG 1×/2×导出；
- P1 完整操作链的零分析计算证明；
- hints、quickref、帮助页和前景验收同步。

### 3.2 条件性交付

“从现有分析结果 cache 重建缺失预览”不是 P1 Core 的无条件承诺。只有满足 §14 的使用
数据门槛，才能实施 P1-E 独立预览 renderer。即使不实施该 renderer，P1 Core 也必须完整
可用并通过验收。

### 3.3 明确不做

- 不做像素坐标自由画布、卡片任意重叠或无限画布；
- 不做卡片自由尺寸；
- 不超过 12 个 placed cards；
- 不同时创建多张 live pyqtgraph 画布；
- 不在 Board 中修改源参数、滤波、坐标范围或标注；
- 不保存数值结果、cache、Qt 对象或源数据到 sidecar；
- 不用 sidecar 的存在掩盖 stale/orphaned；
- 不承诺 sidecar 随单独复制 `.tlproj` 自动同行；缺失必须安全退化；
- 不做 PDF/SVG；PNG 仍是位图交付；
- 不以 offscreen 或 HTML 原型代替真实 Cocoa/Windows 证据。

## 4. 产品信息架构

### 4.1 三层对象

```text
UltraViewWorkspace
├── active_board_id
├── Boards[]
│   ├── Board A: layout / placements / tray / display flags
│   ├── Board B: layout / placements / tray / display flags
│   └── Board C: ...
├── PreviewStore               # 进程内，按 UltraViewRef 唯一
└── PreviewSidecarCatalog      # 磁盘目录/manifest，按 UltraViewRef 唯一
```

Board 只拥有引用与布局；PreviewStore 和 sidecar 不属于某一张 Board。不得把相同 ref 的
QImage 按 Board 复制。

### 4.2 Board 切换器

工具窗 Board 区顶部新增 `BoardSwitcher`：

- 使用可滚动/带 overflow 的 `QTabBar` 表示 Board；
- 当前 Board 始终可见；
- `+` 新建空 Board；
- 右键或旁边菜单提供复制、重命名、删除；
- 支持拖动重排，并提供键盘“前移/后移”替代；
- Board 名允许重复，`board_id` 才是身份；
- UI 创建路径最多创建 20 个 Board，达到后禁用 `+` 并给出明确提示；
- loader 不因数量大于 20 静默丢弃合法 Board，只警告并全部恢复，避免未来/外部项目数据丢失。

20 是 P1 的交互和测试上限，不是用 Board 名或索引做身份的理由。

### 4.3 Board 操作

| 操作 | 行为 |
|---|---|
| 新建 | 创建新 `board_id`，默认名“全局对比 N”，默认 `hero_left_4`，空引用 |
| 复制 | 复制布局、显示选项、placements 和 tray；生成新 ID；不复制像素 |
| 重命名 | 修改当前 Board name；空白输入回退旧名 |
| 删除 | 非空 Board 需要确认；至少保留一个 Board；最后一个只能“清空” |
| 重排 | 只改变 Workspace 的 Boards 顺序，不改变 `board_id` |
| 切换 | 关闭 focus/replacement/presentation 瞬态，显示新 Board；不触发抓图或计算 |

同一个 ref 可以出现在不同 Board；同一 Board 内仍禁止重复 membership。

### 4.4 Board 级与工作区级状态

Board 保存：名称、模板、比例、placements、tray、show flags。

Workspace 保存：Boards 顺序和 `active_board_id`。active Board 是工具窗内部用户意图，
可以持久化；它不等于应用 `current_mode`，重开项目仍不自动打开 UltraView 工具窗。

不保存：选择、搜索、compare filter、focus、replacement、presentation、滚动位置、临时
overview、当前内存驻留和 sidecar load queue。

## 5. 固定模板与大画布

### 5.1 模板矩阵

| `layout_id` | 容量 | 结构 | 用途 |
|---|---:|---|---|
| `split_horizontal` | 2 | 2 列 × 1 行 | 双工况 |
| `split_vertical` | 2 | 1 列 × 2 行 | 上下证据 |
| `grid_2x2` | 4 | 2 × 2 | 四工况 |
| `hero_left_4` | 4 | 左主图 + 右三辅图 | 主问题链 |
| `hero_top_4` | 4 | 上主图 + 下三辅图 | 宽主图 |
| `grid_3x2` | 6 | 3 × 2 | 六工况扫描 |
| `grid_3x3` | 9 | 3 × 3 | 九工况矩阵 |
| `grid_4x3` | 12 | 4 × 3 | 十二工况矩阵 |

P1 不增加 8 图的专用模板；8 个 refs 使用 3×3，保留一个空槽。模板缩容时，超出 refs
继续按原顺序进入当前 Board 托盘，不能丢失。

### 5.2 逻辑画布

`BoardGrid` 不再始终压缩到 viewport，而是放进 `QScrollArea`：

- 2/4/6 模板在有空间时继续填满 viewport；
- 9/12 模板遵守卡片最低阅读尺寸；viewport 不够时扩大逻辑 Board 并出现滚动条；
- 默认卡片最小内容目标为 300×180 logical px；最终值必须用真实字体、标题/来源带和
  1280×800 前景截图验证，不能只冻结这两个草案数字；
- Board 的 logical size 由纯几何函数根据模板、viewport、gutter 和可验证最低卡片尺寸
  计算；屏幕与 compositor 共用几何合同；
- 水平/垂直滚动不改变 card identity、模板或项目状态；
- Trackpad、滚轮、PageUp/PageDown、Home/End 均可导航；滚轮不得穿透去修改源图轴。

### 5.3 100% 阅读与整板概览

大 Board 提供两种明确状态：

1. **阅读模式**：真实卡片 QWidget，保持最低尺寸，可滚动、选择、拖放、打开来源；
2. **整板概览**：使用当前 Board compositor 生成一张适应 viewport 的只读 QImage；
   不创建 live canvas，不编码 PNG，不改变布局。

概览中可点击一个 slot：退出概览、回到阅读模式并滚动到对应卡片。演示模式在 9/12 图
时默认使用整板概览，在 2/4/6 图时可继续使用真实卡片布局。Esc 先退出概览/演示，再按
既有层级处理工具窗。

## 6. 多 Board 预览共享与内存合同

### 6.1 唯一像素身份

PreviewStore 的 key 继续是 `UltraViewRef`。Board ID、slot ID、Board 名称和 Board 顺序
都不能进入 key。

若 ref A 同时位于五张 Board：

- 内存最多一份 A 的 QImage；
- sidecar 最多一份 A 的 PNG；
- digest/status 计算一次后可投影到五张 Board；
- live View 改名/换色后五张 Board 的 chrome 同步刷新；
- source 删除后五张 Board 全部转 orphaned，但各自保留位置。

### 6.2 驻留优先级

进程内像素按以下顺序分配：

1. 当前 focus/overview/export 正在使用的 ref；
2. active Board 当前可见 viewport 内 refs；
3. active Board 其余 placed refs；
4. inactive Board 或 tray refs；
5. 最近访问但已不属于任何 Board 的 ref（应尽快淘汰）。

`PreviewStore` 需从单一 `set_pinned_refs()` 扩展为具名 residency 请求，但仍只有一个
像素 owner。active Board 的 12 个 refs 不能因为“全部 pinned”而无底线保留 1600px
原图；预算不足时按真实卡片显示尺寸成比例降采样，焦点图优先保留高分辨率。磁盘 sidecar
保留的压缩图不因内存降采样而被覆盖。

### 6.3 内存预算

P1 不凭感觉直接把 `MAX_PREVIEW_PIXELS` 从 16M 放大。实施必须先运行 6/9/12 图 DPR 1/2
探针，报告：raw pixels、estimated bytes、decode 峰值、Board switch 峰值和 eviction 次数。

硬合同：

- Board 数量增加不能线性增加常驻 QImage；
- active 12 图在实际显示尺寸下必须都有可读像素，不允许因 budget 变 1×1 或 None；
- focus 关闭后高分辨率临时驻留必须释放/降级；
- 单次分配失败可见退化，不得 abort；
- 任何预算调整都以测量、测试和 Cocoa 证据为依据。

## 7. 预览 sidecar

### 7.1 定位

Sidecar 是可删除、可重建、非权威的预览加速层。`.tlproj` 中的 Workspace/Boards/ref 是
权威语义；sidecar 缺失、过期或损坏不能阻止打开项目，也不能改变 source View。

### 7.2 物理格式

每次成功保存使用项目旁的版本化目录：

```text
project.tlproj
project.tlproj.ultraview/
└── <generation>.uvpz
```

`.uvpz` 是 ZIP 容器，包含：

```text
manifest.json
images/<ref_hash>.png
```

- 文件名只由 canonical `section + view_id` 哈希生成，不使用 View 名、通道名或用户路径；
- ZIP 内禁止绝对路径、`..`、symlink 和重复条目；
- 只使用 JSON + PNG，不使用 pickle、任意 Python object 或可执行内容；
- manifest 记录格式版本、generation、每个 ref、captured digest、capture metadata、原始尺寸、
  PNG 字节数和 SHA-256；
- `.tlproj` nested payload 只保存相对 sidecar 路径、generation 和 manifest hash；
- 保存新 generation 成功且 `.tlproj` 已原子替换后，才清理旧的已引用 generation。

### 7.3 保存事务

当前 `ui/project_io.py::save_project_to_json()` 直接使用 `Path.write_text()`，不是原子写。
P1 实施必须在保持公共函数签名和 MainWindow `_write_project_document()` monkeypatch seam 的
前提下，将项目 JSON 写入升级为同目录临时文件、flush/close 后 `os.replace`。不能把现状
误当成已有原子能力。

推荐次序：

1. 收集所有 Boards membership 的唯一有效 PreviewRecords；
2. 在相邻目录写唯一临时 ZIP，逐图校验并 fsync/close；
3. 计算 manifest hash，原子 rename 为新 generation；
4. 写引用该 generation 的临时 `.tlproj` 并 `os.replace`；
5. 新项目保存成功后，删除本应用可确认不再被当前 `.tlproj` 引用的旧 generation。

若 sidecar 写失败：

- `.tlproj` 语义状态仍允许保存；
- payload 不得引用未完成 generation；
- 普通“保存”若已有上一代有效 descriptor，可以继续引用上一代 sidecar；若不存在则省略；
- “另存为”失败时不得跨项目引用源项目的 sidecar，只能省略新项目的 descriptor；
- toast/log 明确提示“项目已保存，预览未保存”；
- 不删除上一次仍被旧项目引用的有效 sidecar；
- 不遗留伪成功零字节 ZIP。

### 7.4 保存范围

Sidecar 保存 Workspace 所有 Boards 的唯一 membership（placed + tray）中当前拥有合法像素
的 refs。它不保存 View 库中从未加入任何 Board 的图片。

不写入：数值结果、源数组、analysis cache、pins、restore pending、选择、滚动位置、
QPixmap、QObject、MainWindow 状态或 access token。

### 7.5 加载与安全退化

打开项目时先恢复 Workspace 语义，再延迟加载 sidecar：

- manifest/hash/generation 不匹配：整个 generation 不可信，忽略并 warning；
- 单张 PNG hash/尺寸不匹配：只拒绝该 ref，其他图片继续；
- 先通过 `QImageReader.size()` 与 manifest 检查单图边长、总像素、压缩/解压预算，再 decode；
- 禁止一次性解码所有 inactive Boards；active Board 每 event-loop tick 限量加载；
- 图片 decode/publish 遵守 GUI thread 和 Qt 生命周期合同；
- sidecar captured digest 与当前 digest 相同才可 fresh；不同为 stale；digest 不可得为 stale；
- source ref 不存在时为 orphaned，即使 sidecar 有图也不能伪装 fresh；
- 当前 ViewManager 的 title/color/source chrome 优先于历史 manifest；只有 orphaned 才 fallback。

## 8. 项目状态与迁移

### 8.1 Nested schema 3

顶层项目 `SCHEMA_VERSION` 保持 2；UltraView nested schema 现为 **3**（writer 只写 3）。
schema 2 仍可读。schema 1 单 `board` 继续迁成 Workspace。

旧读者若只认识 schema 1：读到 schema 2/3 会回退默认 Board，下一次保存会丢掉多 Board。
当前产品尚未把 UltraView 作为已发布数据合同，该损失被接受，不双写 schema 1 镜像。

未知 nested schema（`> 3`）走 opaque passthrough：运行时用默认 Workspace，用户未改
UltraView 时原样写回。

```json
{
  "ultraview": {
    "schema": 3,
    "workspace": {
      "active_board_id": "board-a",
      "boards": [
        {
          "board_id": "board-a",
          "name": "整车工况",
          "layout_id": "grid_4x3",
          "primary_ratio": 0.67,
          "show_titles": true,
          "show_sources": true,
          "placements": [
            {"slot_id": "r0c0", "section": "time", "view_id": "view-1"}
          ],
          "unplaced": []
        }
      ]
    },
    "preview_sidecar": {
      "format": 1,
      "path": "project.tlproj.ultraview/8f31….uvpz",
      "generation": "8f31…",
      "manifest_sha256": "…"
    }
  }
}
```

### 8.2 Schema 1 → 2

旧 `schema:1 / board:{...}` 必须确定性迁移：

- 原 Board 保留 `board_id/name/layout/ratio/placements/unplaced/show flags`；
- 包装为 `boards:[old_board]`；
- `active_board_id = old_board.board_id`；
- 无 sidecar；现有运行时预览逻辑不变；
- 合法 missing/orphaned refs 不删除；
- 迁移不写回文件，只有用户下一次保存才写当前 nested schema（现为 3）。

### 8.3 非法 payload

- Boards 缺失/空：创建一个默认 Board并 warning；
- 重复 board_id：首个保留，后续生成新 ID 并 warning，不按名称合并；
- active ID 不存在：选择第一张并 warning；
- 单 Board 重复 ref：按既有规则只保留首个 membership 并 warning；
- layout 未知：回退 `hero_left_4`，超出 placement 进入托盘；
- Board 数量超过 UI 创建上限：全部读取，创建按钮禁用并 warning，不静默截断。

### 8.4 Save As、移动和删除

- Save As 在新项目旁写新的 sidecar generation，不让新项目继续引用旧项目相对目录；
- 单独移动/复制 `.tlproj` 后 sidecar 缺失是合法退化；
- 删除项目不是 UltraView 的职责，不自动递归删除旁边目录；
- 应提供帮助说明：若要完整移交可同时复制 `.tlproj.ultraview` 目录；未来可另做“打包项目”。

## 9. 多 Board 生命周期与实时同步

### 9.1 ViewManager 变化

五个 manager 的 `views_changed` 继续作为 library/chrome/exists 刷新触发源：

- 新建 View：所有 Boards 库立即出现；
- 删除 View：所有引用 Board 的卡片和托盘同时 orphaned；
- 改名/换色：所有 Board chrome 同步；
- 重排：不改变任何 Board 引用；
- coordinator reset/shutdown 必须对称断开，不能每个 Board 各连一套 manager signal。

### 9.2 Board 切换

切换 Board 的同步操作仅包括：

- 更新 `active_board_id`；
- 取消 selection/focus/replacement/presentation/overview；
- 替换 page 投影；
- 更新 active residency；
- 安排 sidecar lazy load。

禁止同步路径执行：抓源 widget、cache restore、`do_*`、analysis submit、项目保存、PNG 编码
或一次性 decode 所有图片。

### 9.3 工具窗关闭与项目 reset

- 关闭 UltraViewSheet 只清瞬态 UI，不清 Workspace/PreviewStore/sidecar catalog；
- 新建/成功替换项目清 Workspace、像素、catalog 与 pending load queue，但保留页面信号；
- MainWindow shutdown 先取消 sidecar load queue、断 signal/timer，再释放 QImage；
- queued lazy-load callback 必须带 workspace generation + ref，晚到时复核 active project；
- reopen 工具窗恢复 active Board，不创建第二套 Workspace。

## 10. 导出、复制和概览合成

### 10.1 动态 Board 几何

P0 compositor 固定 1600×900。P1 由纯函数根据模板生成 canonical export size：

- 2/4/6 保持当前视觉基线；
- 9/12 保证每卡最小导出内容区域，不把十二图硬压进不可读的小格；
- 1× 与 2×使用同一几何乘数；
- 最大单边与总像素设置防御上限，超过时返回结构化错误，不尝试危险分配；
- 最终限值在实施时用 12 图中文标题/来源、DPR 2 与真实 PNG 内存探针冻结。

### 10.2 内容

整板复制/导出：

- 只导出 active Board；
- 包含 Board 名、所有 placed slots、标题/来源 flags、状态和空槽；
- 不包含 Board tabs、View 库、托盘、滚动条、搜索、selection 或 transient overview；
- sidecar lazy load 尚未完成的卡片语义仍为 `missing`，可叠加瞬态“正在加载预览”提示；
  `loading` 不进入四态模型、项目或导出，不阻塞等待隐藏 IO；
- 不从源 QWidget 临时 grab，不触发预览补抓；
- 导出读取图片要 `touch`，但不得永久 pin inactive Board。

### 10.3 失败语义

分配失败、PNG 编码失败、路径错误和 clipboard 失败必须 toast + warning；不得生成空文件、
1×1 图片或只导出当前 viewport 却提示“整板”。

## 11. 性能与响应性合同

P1 新增确定性与真机两类门禁：

### 11.1 普通 CI

- Board 数从 1 增到 20，不增加 PreviewStore 中相同 ref 的 image count；
- 切换 Board 的同步路径不 decode PNG、不 encode、不 grab、不 compute；
- active Board 之外的 cards 不创建第二份 QImage；
- scroll/resize burst 合并 relayout，同一 event-loop turn 不重复平滑缩放全部 12 图；
- lazy load 回调带 generation，项目切换/销毁后 no-op；
- 12 图 export 几何无重叠、无越界、顺序稳定；
- sidecar hostile ZIP/oversize PNG 被拒绝而不崩溃。

### 11.2 Cocoa 参考门禁

实施时建立本机 accepted baseline，至少记录三轮：

- 20 Boards、每 Board 12 placements、60 个唯一 refs 的项目恢复；
- Board switch callback、首屏卡片出现、全部 active Board 卡片出现；
- 12 图连续滚动、resize、overview enter/exit；
- 12 图 PNG 1×/2×合成；
- raw pixels、RSS 峰值、最大 GUI stall。

建议初始目标：Board switch 同步回调 `<50 ms`，任何单次 GUI stall `<500 ms`。它们在真实
Cocoa 测量前只是目标，不得在实现报告中冒充已通过标准。

## 12. 可访问性与键盘合同

- Board tabs 可通过 Ctrl+Tab / Ctrl+Shift+Tab 切换；
- 新建、复制、重命名、删除、前移/后移都有非拖拽入口；
- tab tooltip 显示完整 Board 名；
- 9/12 图滚动区的卡片 focus 顺序按 slot row-major；
- Home/End 作用于 Board 滚动时不得改变源 View range；
- overview 可通过键盘选择 slot 并 Enter 定位；
- screen reader 可读 Board 名、序号、卡片总数和当前状态；
- 删除确认不以颜色为唯一风险提示。

## 13. 零分析计算合同

P1 操作链必须同时监控：

1. `do_plot/do_fft/do_fft_time/do_frf/do_order` 等入口；
2. `AnalysisJobService.submit/submit_batch` 与各 coordinator submit；
3. `_store_analysis_result` / analysis cache 新写入；
4. `_analysis_restore_pending` 集合；
5. 五个 ViewManager/source snapshots。

序列至少包括：

```text
打开/置前 UltraView
→ 新建/复制/重命名/重排/删除 Board
→ 切换 2/4/6/9/12 模板
→ 在 Board 间重复放置同一 ref
→ 滚动/overview/presentation
→ 保存项目与 sidecar
→ 关闭并重开项目
→ sidecar lazy load
→ 复制与 PNG 1×/2×导出
```

UltraView 归因分析计算与 cache 写入均为 0；restore pending 和源快照不变。PNG decode、
QImage scaling、QPainter 合成属于展示工作，不等同分析计算，但仍受 GUI stall 门禁。

## 14. 条件项：已有 cache → 缺失预览 renderer

### 14.1 启动门槛

P1 Core 先增加不含数据内容的本地诊断计数：

- 打开 Board 时 placed refs 总数；
- fresh/stale/missing/orphaned 数量；
- missing 中“对应分析 cache 当前存在”的数量；
- sidecar hit/miss/reject 数量；
- 用户从 missing 卡片跳回源 View 的次数。

只有满足任一条件，才进入 renderer 实施：

- 真实使用样本中，sidecar 正常项目的 placed cards 仍有 `>10%` cache-backed missing；
- 或产品 owner 明确把“没有可见 QWidget 也必须从已有结果补图”设为交付要求。

诊断不得上传源名称、通道名、路径、图像或参数。

### 14.2 renderer 边界

若启动，renderer：

- 只读取已存在 cache result；cache miss 保持 missing；
- 不调用 `_render_analysis_view_from_cache()`，因为该路径拥有 deferred restore recompute；
- 不修改 active View、Inspector、Navigator、pins 或 restore pending；
- 不复制 FFT/FRF/Order 数值算法；
- 通过 section-specific render-document adapter 调用现有 presenter/canvas；
- 所有 Qt 对象在 GUI thread，隐藏 host 有明确 owner 和 shutdown；
- 一次只渲染一张 missing card，并可取消；
- parity 只证明同输入两路径一致，仍需 owner-level result 正确性和真实图像 diff；
- time-domain 不在该条件项承诺内，除非已有 render-ready model 可直接复用且不重新装载数据。

### 14.3 post-paint 信号

不得仅为理论完整性改写 pyqtgraph 热路径。只有 P1 诊断证明现有组合稳定判据仍持续产生
空白/中间态预览，才另开 spec 给 post-paint acknowledgement；它不和 cache renderer
顺手混做。

## 15. 架构所有权

推荐新增/扩展：

```text
mf4_analyzer/ui/ultraview_state.py
  WorkspaceState / schema 1→2 migration / Board operations

mf4_analyzer/ui/chart_stack/ultraview/workspace.py
  BoardSwitcher + page-level workspace projection intents

mf4_analyzer/ui/chart_stack/ultraview/layouts.py
  9/12 template logical/screen/export geometry

mf4_analyzer/ui/chart_stack/ultraview/preview_sidecar.py
  manifest/ZIP validation and atomic storage; no MainWindow

mf4_analyzer/ui/chart_stack/ultraview/preview_store.py
  shared residency tiers and measured budget

mf4_analyzer/ui/chart_stack/ultraview/compositor.py
  dynamic complete-Board QImage composition

mf4_analyzer/ui/main_window/ultraview_coordinator.py
  Workspace orchestration, ViewManager facts, project lifecycle, lazy-load routing
```

约束：

- Qt-free schema/legalization 不 import QWidget/MainWindow；
- sidecar codec 不 import MainWindow 或分析算法；
- Page 只发 typed intents，不写 project/session；
- Coordinator 不重新拥有 ViewManager 内部状态；
- 不新增跨 mixin 的零散 `MainWindow` mutable fields；需要状态放 coordinator/holder；
- 条件 renderer 若实施，必须使用独立 adapter/document seam，不塞进兼容 facade。

## 16. 验收矩阵

| ID | 结果合同 |
|---|---|
| UV-P1-A01 | schema 1 单 Board 确定性迁移成 schema 2 Workspace，字段/ref 不丢失 |
| UV-P1-A02 | 新建/复制/重命名/删除/重排 Board 行为和最少一 Board合同正确 |
| UV-P1-A03 | 同 ref 可跨 Board 复用，同 Board 内不重复，稳定身份不使用名称/索引 |
| UV-P1-A04 | 2/4/6/9/12 模板切换、缩容托盘和空槽顺序确定 |
| UV-P1-A05 | 9/12 图遵守最低可读尺寸并通过滚动访问全部卡片 |
| UV-P1-A06 | overview 显示完整 Board，slot 定位回阅读模式正确，不计算 |
| UV-P1-A07 | 20 Boards 不复制 QImage；active residency 与 inactive eviction 符合预算 |
| UV-P1-A08 | sidecar 原子写、manifest/hash、Save As、旧 generation 清理正确 |
| UV-P1-A09 | sidecar 缺失/损坏/恶意 ZIP/超限 PNG 安全退化，项目仍打开 |
| UV-P1-A10 | sidecar 图片按当前 digest 派生 fresh/stale/orphaned；live chrome 优先 |
| UV-P1-A11 | active Board lazy load 可取消，项目切换/teardown 无晚到回调 |
| UV-P1-A12 | 12 图屏幕与动态 compositor 几何一致，无卡片重叠/越界/静默裁切 |
| UV-P1-A13 | 复制和 PNG 1×/2×导出完整 active Board，不只导出 viewport |
| UV-P1-A14 | 五 manager 变化同步所有 Boards，signal 只连接一套且 reset 对称 |
| UV-P1-A15 | 完整 P1 操作链三层计算计数为 0，restore pending/source snapshots 不变 |
| UV-P1-A16 | hints/quickref/help/keyboard/accessibility 与多 Board/大 Board 一致 |
| UV-P1-A17 | 6/9/12 图 DPR/内存/切换/滚动/导出探针有 JSON 证据，无 >500ms 未解释 stall |
| UV-P1-A18 | 聚焦测试、架构门禁、主套件与 acquisition_ui 两进程完整结束 |
| UV-P1-A19 | 1280×800、1600×900、Retina Cocoa 完成多 Board、12 图、overview、导出验收 |
| UV-P1-A20 | Windows Full/Lite frozen 未跑则明确 UNVERIFIED，不以源码/offscreen 替代 |
| UV-P1-E01 | 条件 renderer 只有在 §14 门槛成立后实施，cache miss 仍 missing且零计算 |

## 17. Done 定义

P1 Core 只有在以下条件同时成立时才完成：

1. P0 入口门槛全部关闭；
2. UV-P1-A01～A19 均有测试、探针或 Cocoa 证据；
3. schema migration、sidecar hostile-input、zero-compute 和 lifecycle 有自动化证据；
4. 12 图在 1280×800 仍可通过滚动/overview 有效阅读，不靠无限缩小；
5. 多 Board 不使相同 ref 的内存像素按 Board 数量复制；
6. full suites 以两个新进程正常结束；异常退出为 UNVERIFIED；
7. Windows 发布签字仍使用真实 frozen 包；
8. 条件 renderer 未达到门槛时明确记录 `DEFERRED BY EVIDENCE GATE`，不影响 Core 完成；
9. 最终 verification 文档逐项映射本规格 ID、命令、结果、证据路径和未验证平台。

## 18. 请求 Claude 重点评审

请按 `P1 blocker / needs revision / optional optimization` 分级挑战：

1. nested schema 2 与旧 reader 安全退化是否充分，是否需要额外保留未知字段；
2. 20 Board UI 上限、12 placed-card 上限和不限量 tray 是否需要更明确的 hostile-input 硬限；
3. 3×3/4×3 的最低阅读尺寸与滚动策略是否适合 1280×800；
4. sidecar ZIP、原子保存、上一代 descriptor 和 Save As 失败语义是否存在半写/错引用窗口；
5. PreviewStore residency 是否会因同 ref 跨 Board、focus/export 与 lazy load 发生优先级反转；
6. 12 图动态 compositor 是否应直接分页，还是 P1 单张 PNG 上限足够；
7. P1-E `>10% cache-backed missing` 门槛是否合理，需不需要更长的样本窗口；
8. 计划中的 owner/file/test seam 是否与评审时的最新 HEAD 一致，有无兼容 facade 或
   MainWindow state ownership 违约。
