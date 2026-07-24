# 通道配置管理器 V2 — Implementation Plan

日期：2026-07-24
状态：Implemented — focused tests and offscreen Qt rendering verified; front-end macOS session pending
交互基线：`docs/analyzer/ui-prototypes/2026-07-23-channel-config-manager-v2.html`

## Goal

将已确认的 HTML 方案落到现有 PyQt 通道配置功能中，解决以下问题：

- 页面内按钮尺寸和层级不统一；
- 只能看到配置名称和通道数，无法检查或单独删减通道；
- “当前编辑项”和“批量选择项”混在同一组选框里；
- 管理器中的重命名、复制、删除会立即写入 QSettings，无法支持可信的“保存更改 / 放弃更改”；
- 配置只能保存在本机，无法通过文件导入、导出和传递；
- 当前 View 是否能匹配某个通道缺少预览，只能在应用后才知道结果。

完成后，管理器应成为一个明确的 master-detail 编辑器：左侧选一个配置，右侧检查并修改其通道；只有进入“批量管理配置”后才出现配置级复选框；所有增删改和导入先进入草稿，点击“保存更改”后一次性提交。

## Authoritative Inputs

- 视觉与交互目标：`docs/analyzer/ui-prototypes/2026-07-23-channel-config-manager-v2.html`
- 当前持久化模型：`mf4_analyzer/ui/channel_config.py`
- 当前管理器：`mf4_analyzer/ui/widgets/channel_config_manager.py`
- 当前窗口接线：`mf4_analyzer/ui/main_window/_channel_scope_mixin.py`
- 当前样式：`mf4_analyzer/ui_kit/style.qss`
- 当前回归：
  - `tests/ui/test_channel_config.py`
  - `tests/ui/test_channel_config_manager.py`
  - `tests/ui/test_channel_config_bar.py`
  - `tests/ui/test_view_channel_scope.py`
  - `tests/ui/test_combo_popup_shell.py`

HTML 是本轮信息架构、布局和操作模型的权威来源；Qt 只允许为字体度量、窗口 chrome 和控件实现作等价适配，不得换成另一套表格/工具栏工作流。

## Product Contract

### 1. 编辑和保存边界

- 打开管理器时，从 Store 建立独立草稿快照。
- 新建、重命名、复制、删除配置，导入配置，以及增删通道，都只修改草稿。
- 草稿第一次发生有效变化后显示“有未保存修改”，并启用“保存更改”。
- “保存更改”先完整校验快照，再一次性替换 Store 内容并只调用一次 QSettings `sync()`。
- 提交失败时，Store 和 QSettings 保持原状，草稿留在窗口内供用户修正。
- 保存成功后窗口保持打开，当前草稿成为新基线，脏标记清除，配置栏同步刷新。
- 无修改时“关闭”直接退出；有修改时，关闭按钮、窗口关闭键和 Escape 都进入同一个非原生确认流程，默认动作是“继续编辑”，可选择“放弃修改”。
- 管理器里的编辑不自动应用配置，不触发绘图，不改变当前 View 已勾选通道。

### 2. 左侧配置列表

- 普通模式只存在一个活动配置；点击整行切换右侧详情，不显示配置复选框。
- 搜索匹配配置名称或其通道名称；搜索只过滤显示，不改变活动项和草稿内容。
- 每行显示配置名称、通道数和草稿状态；活动行使用固定左侧色条和背景，不靠文字缩进表达选中。
- “批量管理配置”是显式模式：进入后显示配置复选框和批量删除栏，活动配置仍单独高亮。
- 退出批量模式时清空批量勾选，不改变活动配置。
- 新建配置使用当前 View 已勾选通道的名称快照；没有已勾选通道时不创建空配置，并在原位给出明确提示。
- 复制配置生成唯一的“副本”名称并保留通道顺序；重命名保持稳定 `config_id`。
- 删除活动配置后，优先选中其下一项，否则上一项；列表为空时右侧显示空状态。

### 3. 右侧通道详情

- 标题区显示配置名称、通道总数、匹配数、缺失数和草稿状态。
- 通道表固定为五列：批量勾选、通道名称、单位、当前 View、单项移除。
- 通道名称是唯一匹配身份；单位只作为提示信息，不参与匹配或去重。
- “当前 View”在打开窗口和当前 View 上下文刷新时重新计算：
  - 任一已加入文件存在同名原始通道即为“已匹配”；
  - 所有已加入文件均不存在才是“缺失”；
  - 同名通道在多个文件出现仍只显示一行配置通道。
- 单项 `×` 只移除对应草稿通道；通道级批量勾选与配置级批量勾选是两个独立状态集合。
- 通道搜索只过滤当前配置中的行；“移除所选”只处理当前可见且已勾选的通道。
- 最后一次通道移除支持一次撤销；保存成功后清除该撤销记录。
- 不允许保存空配置；若删到零通道，保存时定位该配置并提示用户补充通道或删除整个配置。

### 4. 当前 View 预览

- 打开管理器时由聚焦的 TimeDomain View 生成只读上下文：已加入文件数、可用原始通道名称和单位提示。
- 单位按 View 文件顺序取第一个非空值；不同文件单位不一致时显示第一个单位并提供“不一致”提示，不改变匹配结果。
- 没有聚焦 TimeDomain View 或 View 没有文件时，匹配状态显示“无可用 View”，而不是把所有通道误报为缺失。
- 预览是管理辅助信息，不写入 View 状态，不调用 `resolve_channel_config()` 的应用副作用路径。

### 5. 导入 / 导出

传递文件为 UTF-8 JSON，默认扩展名为 `.tracelab-config.json`，顶层契约：

```json
{
  "format": "tracelab.channel-configs",
  "version": 1,
  "exported_at": "2026-07-24T12:00:00Z",
  "configs": [
    {
      "name": "转向基础信号",
      "channels": [
        {"name": "EPS_1_CRC", "unit": ""},
        {"name": "EPS_DrvrSteerTq", "unit": "Nm"}
      ]
    }
  ]
}
```

传递文件不得包含 `config_id`、创建/更新时间、文件 ID、颜色、勾选状态、显示状态或当前 View 匹配结果。

限制与规范：

- 最大文件 2 MiB；一次最多 100 个配置；每个配置最多 2,000 个通道；
- 配置名称最大 80 个字符，通道名称最大 180 个字符，单位最大 32 个字符；
- 配置名称去除首尾空白后比较，冲突判断使用 `casefold()`；
- 同一配置内重复通道按精确名称去重，保留第一次出现的位置和单位；
- 未知顶层字段忽略；未知格式、版本、字段类型、空配置名或空通道列表拒绝整次导入；
- 导出当前配置和导出全部配置都以窗口内草稿为准；存在未保存修改时，导出成功提示必须说明“包含未保存修改”；
- 导入先显示预览：配置数、通道数、同名冲突数和错误摘要，用户确认后才合并进草稿；
- 同名冲突一次选择一种策略：
  - 保留两份：为导入项生成 `名称（导入）`、`名称（导入 2）` 等唯一名称和新的草稿 ID；
  - 替换：保留本地配置的稳定 ID 和创建时间，用导入内容替换名称对应项；
  - 跳过：同名项不进入草稿；
- 导入完成仍需点击“保存更改”才写入本机配置。

### 6. 单位提示的兼容保存

为了让配置在另一台机器导入、保存、再导出时不丢失单位提示，内部记录增加可选的 `channel_unit_hints`，但保持 `channel_names` 为现有应用和匹配代码的权威字段：

- 读取现有 schema v1 记录时自动得到空的单位提示；
- 写入使用 schema v2，但继续使用现有 QSettings key `channel_selection/configs_v1`，避免旧配置因换 key 消失；
- `from_dict()` 同时接受 v1 和 v2；v1 只在下一次用户真实保存时升级，不在读取时静默改写；
- 单位提示按通道名称关联，缺失时可用当前 View 的单位补齐显示；
- `resolve_channel_config()` 仍只按 `channel_names` 精确匹配。

## Non-goals

- 不把配置改成按文件 ID、CAN ID、DBC signal path 或单位匹配；
- 不在管理器内增加绘图、FFT、过滤、颜色或轴设置；
- 不自动监听 View 的每次勾选变化并重写已打开的草稿；
- 不引入云同步、数据库、压缩包或第三方 JSON/schema 依赖；
- 不改变底部配置栏“应用配置”的现有行为；
- 不在此次工作中重构通道树、BLF/DBC 导入或 CRC 渲染路径。

## File Ownership Map

| 文件 | 责任 |
|---|---|
| `mf4_analyzer/ui/channel_config.py` | v1/v2 兼容模型、草稿快照、原子提交、当前 View 预览纯逻辑 |
| `mf4_analyzer/ui/channel_config_transfer.py`（新增） | 无 QWidget 的 JSON 解析、序列化、限制校验和冲突合并 |
| `mf4_analyzer/ui/widgets/channel_config_manager.py` | V2 master-detail 对话框和纯草稿交互 |
| `mf4_analyzer/ui/main_window/_channel_scope_mixin.py` | 创建上下文、单次保存接线、配置栏刷新和 toast |
| `mf4_analyzer/ui_kit/style.qss` | V2 对象名的视觉样式，不承担关键尺寸计算 |
| `tests/ui/test_channel_config.py` | 模型兼容、原子提交和预览逻辑 |
| `tests/ui/test_channel_config_transfer.py`（新增） | 传递文件契约和冲突策略 |
| `tests/ui/test_channel_config_manager.py` | 草稿状态、列表/详情、通道移除、几何和弹窗 seam |
| `tests/ui/test_view_channel_scope.py` | MainWindow 接线、一次提交、不重绘和关闭放弃 |
| `tests/ui/test_channel_config_bar.py` | 保存后配置栏兼容回归 |
| `tests/ui/test_combo_popup_shell.py` | 管理器改造不得破坏已有配置下拉弹层 |

## Ordered Implementation

### Stage 0 — 基线和测试隔离

1. 记录 `git status --short --branch`、`git diff --stat` 和 `git diff --check`，保护当前工作树已有的通道树对齐改动与原型文件。
2. 连续运行全部相关 `tests/ui` 文件，避免中途离开又重新进入 `tests/ui` 而丢失该目录的 fixture。
3. 为 QSettings 使用测试专用组织名/临时 settings；禁止读写开发者真实配置。
4. 保存当前 Qt 管理器截图作为 before，不把 HTML 浏览器截图当作当前 Qt 真值。

**Checkpoint 0**：现有聚焦回归基线有精确通过/失败记录，且测试未修改用户 QSettings。

### Stage 1 — 草稿模型、schema 兼容和原子提交

先在 `tests/ui/test_channel_config.py` 写失败测试：

- v1 数据可读，v2 单位提示可 round-trip；
- 读取 v1 不立即改写 settings；
- 草稿新增、重命名、复制、删配置和删通道不会触发 Store flush；
- `commit_snapshot()` 只 sync 一次；
- 未变化项保留 `created_at` 和 `updated_at`；变化项保留 ID/创建时间并统一更新 `updated_at`；
- 新增项获得新 ID 和时间；快照中缺失的旧项被删除；
- 重名、重复 ID、空名称、空通道或超限校验失败时，内存和 settings 均无变化；
- 当前 View 预览正确区分已匹配、缺失、无 View 和单位不一致。

实现：

1. 扩展 `ChannelSelectionConfig`，兼容读取 schema v1/v2；保持 `channel_names` 公开接口不变。
2. 增加 widget-free 草稿结构，草稿 ID 在创建时生成，保存前不进入 Store。
3. 增加 `commit_snapshot(drafts)`：先构建、完整校验所有 replacement，再原子替换 `_configs` 并 flush 一次。
4. commit 前保留旧序列化值；写入后检查 QSettings `status()`。发生写入异常或非 `NoError` 状态时恢复旧序列化值和旧 `_configs`，并把错误返回给上层；不得呈现“保存成功”。
5. 增加纯预览 helper，输入 View 文件顺序和文件集合，输出名称级匹配/单位事实。

**Checkpoint 1**：可以在无 QWidget 环境中证明草稿可放弃、提交原子且旧配置无损升级。

### Stage 2 — 传递文件模块

先创建 `tests/ui/test_channel_config_transfer.py` 并写失败测试：

- 中文配置名、中文单位和空单位的单项/全部 round-trip；
- 输出只包含允许的 portable 字段；
- 2 MiB、100 配置、2,000 通道和字符串长度边界；
- 错误 format/version/type/空内容整次拒绝；
- 重复通道保留第一次；
- `keep` 生成确定性后缀，`replace` 保持本地稳定 ID，`skip` 不改变本地项；
- 任一配置无效时不产生半导入草稿；
- View 匹配状态、文件 ID、颜色和时间戳永不进入 JSON。

实现新增的 `channel_config_transfer.py`：

1. 定义 format/version/limits 常量和解析结果 dataclass；
2. `serialize_transfer(drafts, unit_hints, exported_at)` 返回确定性 UTF-8 JSON；
3. `parse_transfer(bytes)` 在 JSON decode 前检查字节数，在构造对象时检查全部限制；
4. `merge_import(drafts, incoming, conflict_mode, id_factory)` 只返回新草稿和摘要，不碰 Store；
5. 文件对话框和磁盘读写留在 UI/主窗口层，核心函数只处理 bytes/对象，便于单元测试。

**Checkpoint 2**：传递契约完全可由纯测试验证，同名策略没有 QWidget 或 QSettings 副作用。

### Stage 3 — 管理器 V2 结构与交互

在 `tests/ui/test_channel_config_manager.py` 先建立失败契约：

- 默认只激活一个配置，未进入批量模式时不存在配置勾选列；
- 进入/退出批量模式不改变活动配置，退出会清空批量勾选；
- 右侧显示全部通道、单位和当前 View 状态；
- 配置搜索和通道搜索互不污染；
- 单项移除、批量移除和一次撤销只改草稿；
- 重命名、复制、新建和删除只改草稿并正确设置 dirty；
- 保存信号携带完整快照；保存成功后基线/dirty 正确重置；
- clean close 直接退出，dirty close/X/Escape 走同一个可注入确认 seam；
- 导入预览确认后只改草稿；导出当前/全部选择正确；
- 默认 1180×790 与最小 940×680 下页脚可见、通道名至少 240 px、没有控件重叠；
- 顶部、行内、底部主要操作按钮的可见高度统一为 36 px；图标按钮为 36×36。

重建 `ChannelConfigManagerDialog`：

1. 默认尺寸 1180×790，最小 940×680；创建时限制到可用屏幕，不让小屏幕窗口越界。
2. 使用 HTML 的 master-detail 主区：左栏固定 310 px，右栏 stretch；通道名称列获得剩余宽度且不少于 240 px。
3. 用明确的活动配置 ID、配置批量 ID 集合、通道批量名称集合分别管理三种状态。
4. 列表和表格行使用稳定 ID/通道名作为数据角色，不从显示文字反推身份。
5. 提供可注入的 import/export 文件选择和确认回调，测试中不打开 native dialog。
6. 导入使用应用内 `QDialog` 预览，不用静态 `QMessageBox`；关闭脏草稿同理，避免 offscreen QTest 挂死。
7. 关键控件高度以 Python helper 和此对话框专用 QSS 的 36 px 外框共同约束；专用选择器不得被全局紧凑按钮规则压缩。
8. 长配置名和长通道名使用省略号并保留 tooltip；中文、英文和高 DPI 下都不靠硬编码文本宽度。

**Checkpoint 3**：所有管理动作都可见、可撤销或可放弃；普通编辑与批量删除不会混淆。

### Stage 4 — MainWindow 接线、样式和兼容回归

先在 `tests/ui/test_view_channel_scope.py` 写失败测试：

- 打开管理器只创建草稿，不写 settings；
- 新建配置使用打开管理器时捕获的当前勾选快照；主窗口被 modal 管理器锁定期间不动态改写这份输入；
- 管理动作期间 Store、配置栏和 View 勾选保持不变；
- 保存只调用一次 `commit_snapshot()`，成功后刷新配置栏并保留活动配置；
- 保存失败不刷新配置栏、不关闭窗口并显示错误；
- 放弃或关闭不改变 Store；
- 导入、导出和管理保存都不触发 `channels_changed`、plot 或配置应用；
- 当前 View 预览使用聚焦 TimeDomain View 的 attached files，不误用全局文件列表或别的 split View；
- 保存后从底部配置栏应用，现有 exact-name、多文件匹配和 missing toast 行为不变。

实现接线：

1. `_manage_channel_config()` 一次性构造当前 View 预览上下文和当前勾选通道/单位 provider。
2. 移除管理器对 `_rename/_copy/_delete...from_manager` 即时 Store 操作的依赖，改为一个 `save_requested(snapshot)` 提交入口。
3. 保存成功后 reload 配置栏、保留仍存在的选中配置，并回传持久化记录让 dialog 重置基线。
4. 文件导入/导出由 manager 的可测试 service seam 调用；所有错误都落在窗口内可读反馈区，不只写日志。
5. 更新 QSS 为 V2 对象名：活动配置、dirty badge、匹配/缺失 chip、danger action、导入预览和 footer；清理仅属于旧 manager 且不再被引用的选择器。
6. 复跑 `test_channel_config_bar.py` 与 `test_combo_popup_shell.py`，确认底部配置选择和下拉宽度没有回归。

**Checkpoint 4**：管理器保存和现有配置栏应用形成清晰的两个动作；前者不绘图，后者保持当前行为。

### Stage 5 — 离屏几何、真实 Qt 和完整验收

离屏自动化：

1. 生成而不是只断言 objectName 的 Qt 截图：
   - 默认单配置；
   - 已删通道的 dirty 状态；
   - 批量管理配置；
   - 导入预览和同名策略；
   - 940×680 最小窗口。
2. 对关键矩形断言：按钮高度、footer 可见、左右栏不重叠、通道名列最小可读宽度、弹窗在宿主窗口内。
3. `git diff --check`；扫描 transfer JSON 不允许字段和废弃 manager signals。

前台 macOS 验收：

1. 从真实 TraceLab 打开含多个文件/通道的 View，进入管理器；
2. 核对 1180×790 与拖到最小尺寸时的文字、按钮、滚动和表格对齐；
3. 单删一个通道、撤销，再批量删两个通道，关闭并放弃，确认原配置没变；
4. 重复编辑并保存，确认配置栏更新但图没有自动重绘；
5. 导出一个包含中文名称/单位的配置，在独立临时 QSettings profile 中导入；分别验证 keep/replace/skip；
6. 保存后应用配置，确认多个已加入文件仍按通道名匹配，缺失通道提示正确；
7. 保存截图并记录窗口尺寸、DPR、配置数、通道数和结果；浏览器 HTML 截图不得替代这一步。

建议聚焦命令：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_channel_config.py \
  tests/ui/test_channel_config_transfer.py \
  tests/ui/test_channel_config_manager.py \
  tests/ui/test_channel_config_bar.py \
  tests/ui/test_view_channel_scope.py \
  tests/ui/test_combo_popup_shell.py
```

随后补跑直接相邻的导航器回归：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q tests/ui/test_file_navigator.py
```

所有显式 `tests/ui` 路径保持连续；会打开确认窗或文件选择器的 QTest 操作必须预先注入确定结果，不允许在 offscreen 测试中等待原生 modal。

## Commit Sequence

建议分为四个可独立回滚的提交，不与当前工作树中其他 UI/性能修改混合：

1. `feat(config): add atomic channel configuration drafts`
2. `feat(config): add portable channel configuration transfer`
3. `feat(ui): rebuild channel configuration manager`
4. `test(ui): verify channel manager rendering and integration`

每个提交前只暂存本阶段 owned files，运行对应 Checkpoint 和 `git diff --cached --check`。未收到明确指令时不 commit、不 push。

## Definition of Done

- 用户能明确看到当前配置包含哪些通道，并能单删、批量删和撤销最近一次通道删除；
- 普通配置选择与批量配置删除是两个可辨识状态；
- 新建、重命名、复制、删除、通道修改和导入在保存前都不会写入 QSettings；
- 保存是一次完整校验和一次原子提交，关闭放弃可靠；
- 可导出当前或全部草稿，可预览导入，并正确处理 keep/replace/skip；
- 旧 schema v1 配置可继续读取和应用，保存后单位提示可跨机器 round-trip；
- 管理动作不触发绘图，配置栏应用逻辑不回归；
- 主要按钮与图标按钮几何一致，最小尺寸无重叠，通道名称仍有可读空间；
- 聚焦测试、相邻导航器测试、`git diff --check` 全绿；
- 至少一组离屏 Qt 截图和一组前台 macOS TraceLab 截图证明真实渲染到位。

## Implementation Evidence — 2026-07-24

- 已实施：v1/v2 QSettings 兼容、可放弃草稿、一次性 `commit_snapshot()`、单位提示、当前 View 预览、配置/通道两级选择、通道单删/批量删/撤销、JSON 导入导出及 keep/replace/skip。
- 管理器编辑不再调用旧的即时 rename/copy/delete Store 路径；只有主窗口的 `save_requested` 接线会提交草稿。底部原有“保存/应用”入口仍可用，并会保存单位提示。
- 聚焦配置回归：`72 passed in 2.81s`（本轮 HTML 操作模型、导入预览和离屏几何修正后）。
- 通过离屏真实 Qt 渲染：
  - `docs/analyzer/verify/2026-07-24-channel-config-manager-v2/channel-config-manager-html-default-1180x790.png`
  - `docs/analyzer/verify/2026-07-24-channel-config-manager-v2/channel-config-manager-html-selected-1180x790.png`
  - `docs/analyzer/verify/2026-07-24-channel-config-manager-v2/channel-config-manager-html-dirty-batch-940x680.png`
  - `docs/analyzer/verify/2026-07-24-channel-config-manager-v2/channel-config-manager-html-import-preview.png`
- 渲染探针断言：左栏固定 310 px，所有主要控件 36 px，通道行 49 px；最小 940×680 时 channel-name 列 316 px，footer 保存按钮未裁剪。
- 本轮未执行前台 macOS TraceLab 人工会话；该项保留为最终真实数据/高 DPI 验收，不由离屏截图替代。

## Risks and Mitigations

| 风险 | 对策 |
|---|---|
| 当前即时写入逻辑与“保存更改”冲突 | Stage 1 先完成草稿和单次 commit，UI 不绕过该边界 |
| schema 升级使旧配置消失 | 保持原 settings key，双版本读取，读取时不自动改写 |
| import replace 意外改变配置栏引用 | 替换保留本地稳定 ID；keep 才生成新 ID |
| 单位被误用为匹配条件 | 数据模型和测试明确单位只为 hint，resolver 仍按 exact name |
| 两级复选框再次混淆 | 普通模式隐藏配置 checkbox，批量状态和通道状态使用独立集合 |
| Qt 原生 modal 让离屏测试挂死 | 确认/文件选择均走可注入 seam，测试先 stub 再 QTest |
| 只看 QSS 导致按钮仍不等高 | Python 固定 36 px + 实际 geometry 断言 + Qt 截图 |
| 小屏或高 DPI 截断页脚/通道名 | availableGeometry 限制、最小尺寸测试和前台 DPR 记录 |
| 管理动作意外触发耗时重绘 | MainWindow 信号 spy 明确断言无 plot/channels_changed |
