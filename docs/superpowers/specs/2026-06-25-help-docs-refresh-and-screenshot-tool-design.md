# 帮助文档刷新 + 配图生成脚本 — 设计

- 日期：2026-06-25
- 状态：设计已确认，待写实现计划
- 触发：用户「针对最近的更新，优化迭代 help 相关文件（文字描述、offscreen 图、操作方式），并问能否做成固定/自动任务」

---

## 1. 背景与目标

最近 1-2 个月（2026-05 ~ 06）新增/改动了大量**用户可见功能**，但帮助文档停在 2026-06-20
（主手册 `meta.updated`），4 个面板指南停在 2026-06-22。本轮目标：

1. **内容补齐（全覆盖）**：把已发布 + 即将发布（当前分支在做的 BLF candidate、设计完成待实现的
   overlay 共轴组）的用户可见功能写进帮助。
2. **顺手做一个可重跑的配图生成脚本** `tools/gen_help_screenshots.py`，让以后 UI 改动后重出面板
   截图有据可依、半机械化。
3. 回答「能否自动化」：本轮只做内容 + 脚本；**提醒 hook / 定期起草**留作下一步（见 §7）。

非目标见 §7。

---

## 2. 现状：帮助是「两套架构」

### 2.1 主手册 `mf4_analyzer/help/TraceLab-使用说明.html`（数据驱动）

- 全部文案在顶部 `<script type="application/json" id="deckData">` 的 JSON 里：
  `meta`（含 `version` / `versionLabel` / `docVersion` / `updated`）、`slides[]`、`changelog[]`。
- 渲染器（同文件内 JS）支持块类型：`lead` / `when` / `tip` / `cards` / `steps` / `kv` / `card` /
  `cols` / `flow` / `changelog` / `raw`。页码、总页数、导航全自动。
- **配图是手绘的**（内联 SVG / HTML mock，`raw` / `mock` 块），**不依赖真实截图**。
- 维护成本低：加页 = 往 `slides[]` 加一个 JSON 对象；改文案 = 改 JSON 字符串。
- 现状已覆盖到 v2.1（2026-06-20）：load 页 pills 已含音视频、fft 页已写 A 计权、changelog 有 v2.1。

### 2.2 4 个面板指南（手写 HTML 幻灯片）

`time-domain-guide.html` / `fft-guide.html` / `ffttime-guide.html` / `order-analysis-guide.html`

- 结构：封面 → 一张 `assets/<x>-panel.png` **真实面板截图** + 写死的数字 `pin`（`left/top %`）
  + 若干步骤页（内联 SVG / HTML mock）。
- **只有这 4 张 `*-panel.png` 是真实截图**；pin 坐标绑定 UI 元素在截图中的位置。
- 入口：`mf4_analyzer/help/__init__.py` 的 `open_guide(name)` → 系统浏览器打开；
  主窗口底部「软件说明」按钮 → `manual`；Inspector 右下「? 使用说明」→ 按当前 mode 打开对应 guide。

### 2.3 关键约束

- **pin 与截图强耦合**：重出 `*-panel.png` 后，pin 的 `left/top %` 必须重新对位，否则数字标错位置。
- **CLAUDE.md 红线**：UI/视觉必须验真机渲染（截图 / 读原生属性）；**offscreen ≠ 真机**。
- **TCC 约束**：项目在 `~/Downloads`，真机 GUI 子进程易触发 macOS TCC EPERM。Claude 经 Bash 跑
  cocoa 渲染可能被封；offscreen 可跑但仅作布局/初稿，不算「真机已验」。

---

## 3. 内容补齐范围（本轮全覆盖）

### 3.1 主手册 `deckData` JSON（改 JSON，最干净）

新增 / 扩写以下用户可见功能：

| 主题 | 落点 | 用户视角要点 |
|---|---|---|
| 时域滤波 | 新增/扩写时域相关页 | 频域零相位滤波，类型 低通/高通/带通/带阻 + 阶数 2/4/6/8；勾「显示原始/显示滤波后」做前后对比（滤波为**虚线**叠加）；超奈奎斯特自动钳制提示；滤波结果**不参与** FFT/阶次，不存项目 |
| overlay 叠加交互 | 扩写 time / multiview 页 | 框选缩放**同步所有通道 Y**（框啥得啥，无需先选通道）；裸滚轮平移；**Shift+滚轮**缩 X；**Alt/Option+滚轮**缩单通道 Y；坐标轴 gutter 拖 = 只拖该通道刻度 |
| GPU 加速开关 | 扩写 time / 速查页 | Inspector 右下「GPU 加速（时域图）」**默认关**；全屏/高分屏/多通道卡顿时开；导出自动切回 CPU；**macOS 平台默认关闭** |
| BLF/DBC 导入 | load 页 pills + 步骤 | `.blf` 加入「支持的文件」；首次打开弹 DBC 选择（强/弱匹配提示）；同总线后续 BLF 自动推荐上次 DBC 一键确认；DBC 绑定随 `.tlproj` 持久化 |
| 跨速率 Order | 扩写 order 页 | 转速通道与信号采样率可不同（任意比例混合） |
| 色阶显示范围 | 带一句（spectro/order） | 自动色阶跨度 30dB（更细），色阶为纯显示电平不烘死数据 |

维护项：
- `changelog[]` 加 **v2.2 / 2026-06-25** 条目（用「面向使用者」语言，不塞类名/文件路径）。
- `meta.updated` → `2026-06-25`；`meta.docVersion` 升一位（如 `2.0` → `2.1`，注意旧编辑暂存按
  `docVersion` 隔离，升版会作废旧 localStorage 编辑，符合预期）。

### 3.2 4 个面板指南

| 文件 | 新增内容 |
|---|---|
| `time-domain-guide.html` | 「滤波」步骤页；「overlay 缩放 / 滚轮修饰键 / 坐标轴拖拽」步骤页；提一句 GPU 开关 |
| `fft-guide.html` | 「频率加权 / A 计权（IEC 61672）」说明 |
| `ffttime-guide.html` | 「频率加权 / A 计权」说明 |
| `order-analysis-guide.html` | 「频率加权」+「跨速率 COT」说明 |

约束：**BLF candidate 流程 + overlay 手动共轴组** 属「即将/最新」，仅在主手册以相应措辞写，
**不**在面板指南展开（面板指南是「认准位置」型，不宜写尚未稳定的 UI）。

---

## 4. 配图生成脚本 `tools/gen_help_screenshots.py`

### 4.1 职责

仿现有 `tools/_screenshot_order_pg_migration.py` 范式，一次生成 4 张面板截图，供面板指南复用。

### 4.2 流程

1. 设置 High-DPI flags（先于 `QApplication`），`setup_chinese_font()` + `load_stylesheet` +
   `install_glass_tooltips`（与 `app.main` 对齐，保证字体/样式真实）。
2. 启动 `MainWindow`，**固定窗口几何**（写死并在脚本顶部文档化，例如 `1280×820`，与现有面板图
   接近，保证 pin 坐标跨次稳定）。
3. 加载**合成数据**（rpm 斜坡 + 振动 order1/order2 + 一路扭矩，seeded、确定性，复用 order 脚本思路）。
4. 依次对 `time` / `fft` / `fft_time` / `order` 四个 mode：切 mode → 选通道/转速 → 设参数 →
   （fft/fft_time/order）驱动 worker、用 `QEventLoop` + watchdog 等算完 → `processEvents` 数次 →
   `win.grab(scale=2)` **整窗截图**（面板图是三栏全窗，不是单 canvas）。
5. 保存到 **staging 目录** `output/help-shots/<mode>-panel.png`，**不直接覆盖** `help/assets/`。

### 4.3 CLI

- 默认真机 cocoa 平台；`--platform offscreen` headless fallback。
- `--promote`：人审后把 staging 图拷进 `mf4_analyzer/help/assets/`（覆盖旧 `*-panel.png`）。
- `--only <mode>`：只出某一个面板（可选，省时）。
- 退出码：成功 0；选通道失败 / compute 超时 / 退化 pixmap 分别非 0（仿 order 脚本）。

### 4.4 几何稳定性

固定窗口尺寸 + 固定数据 → 重出图布局稳定 → pin 只在「UI 控件位置真的移动」时才需要重定位，
而非每次重出都全改。脚本顶部 docstring 记录所用几何与数据，作为后续基线。

---

## 5. 重出截图 + 重定位 pin（验真机环节）

1. 跑脚本出 4 张新图到 `output/help-shots/`。
2. 对每个面板指南：把新图与现有 pin 坐标对照，调整 `left/top %` 使数字落在正确 UI 元素上。
3. **验真机**：最终面板图应由**真机 cocoa 渲染**产出并**肉眼确认** pin 对位；浏览器打开 guide 复核。
4. `--promote` 提升进 `help/assets/`。

### 5.1 TCC 约束下的交付拆分

- Claude 能做：写脚本、写全部文案、（若 offscreen 可跑）出**临时图 + 初步 pin 定位**验证脚本与布局。
- 可能需用户做：在本机用 `! .venv/bin/python tools/gen_help_screenshots.py`（必要时 `--promote`）跑
  **真机渲染**并肉眼确认；Claude 不把 offscreen 图当「真机已验」交付，会显式标注哪些图未经真机确认。

---

## 6. 验收标准

- 主手册 JSON 通过（页面能渲染、JSON 合法、`meta.updated`/`changelog` 已更新、新功能均有页/段覆盖）。
- 4 个面板指南新增内容就位，措辞面向使用者（无类名/文件路径/pyqtgraph 等开发词）。
- `tools/gen_help_screenshots.py` 可运行（至少 offscreen 路径跑通、输出 4 张非退化 PNG 到 staging）。
- 未发布功能（BLF candidate / 共轴组）仅出现在主手册且措辞为「最新/即将」。
- 任何「真机已验」claim 都有真实渲染证据；未验的图显式标注。

---

## 7. 非目标（本轮不做，留下一步）

- **「帮助过期」提醒 hook**：当 `help/` 之外的功能/UI 文件比帮助文件有新提交时，提示帮助可能过期
  （只提醒、不写内容）。
- **`/schedule` 定期起草**：定期 diff 自上次帮助更新 → 起草帮助修改草稿交用户审（半自动，不无人值守合并）。
- overlay 手动共轴组、BLF candidate 流程的**实现本身**（属各自的功能分支，不在本帮助任务内）。

---

## 8. 风险

- **滞后风险**：BLF candidate 未合并、共轴组待实现，写进手册有「用户暂时找不到」风险（用户已确认全写）；
  以「最新/即将」措辞软化，若后续撤回需返工对应段落。
- **TCC / 真机渲染**：见 §5.1，最终图可能依赖用户在本机跑。
- **pin 漂移**：若固定几何选得与现有图差异大，本轮 4 个指南 pin 需全量重定位（一次性成本）。
