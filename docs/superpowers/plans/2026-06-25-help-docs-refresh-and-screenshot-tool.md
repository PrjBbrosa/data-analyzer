# 帮助文档刷新 + 配图生成脚本 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把最近 1-2 个月的用户可见功能补进帮助文档（主手册 + 4 个面板指南），并新增一个可重跑的面板截图生成脚本。

**Architecture:** 帮助是两套架构——主手册 `TraceLab-使用说明.html` 是数据驱动（改顶部 `deckData` JSON 即可），4 个面板指南是手写 HTML 幻灯片（封面 + 真实截图 + 写死 pin + 内联 mock）。本计划：改主手册 JSON、给 4 个指南加内容、写 `tools/gen_help_screenshots.py` 生成面板图到 staging、最后重出截图并重定位 pin（真机验证环节，可能交用户跑）。

**Tech Stack:** PyQt5 · 纯 HTML/CSS/JS（帮助 deck，无 QWebEngine）· numpy（合成数据）· pytest。

设计依据：`docs/superpowers/specs/2026-06-25-help-docs-refresh-and-screenshot-tool-design.md`

## Global Constraints

- **面向使用者措辞**：帮助文字讲「怎么操作」，禁止出现 `pyqtgraph` / `matplotlib` / `scipy` / `QWidget` / `PyQt5` 等开发内部词与文件路径、类名。
- **EPS 领域**：示例信号名用 `电机转速` / `方向盘扭矩` / `电机扭矩`；阶次 base 是电机转速，别用 engine / n_engine。
- **offscreen ≠ 真机**：任何「真机已验」的判断必须有真实 cocoa 渲染证据；offscreen 图只作布局/初稿，须显式标注未经真机确认。
- **主手册版本位**：`meta.updated` 改 `2026-06-25`；`meta.docVersion` 由 `"2.0"` 升到 `"2.1"`；`changelog` 顶部新增 `v2.2` 条目。
- **未发布功能**（BLF candidate 选择流程 / overlay 手动共轴组）只写进主手册、措辞为「最新 / 即将」；面板指南不展开。
- **提交锁路径**：用 `git commit -m "..." -- <path>` 只提交本任务文件，不碰当前分支上 codex 的 BLF 改动（`mf4_analyzer/io/loader.py`、`ui/project_io.py`、`ui/main_window/_project_io_mixin.py`、`window.py`、`tests/test_blf_*`、`tests/ui/test_project_session.py` 等未提交文件留给 codex）。
- **配图输出**：脚本写到 staging `output/help-shots/`，`--promote` 才覆盖 `mf4_analyzer/help/assets/`。

---

## File Structure

- Modify `mf4_analyzer/help/TraceLab-使用说明.html` — 主手册 `deckData` JSON：新增滤波页、扩写 load/order/cheat、changelog v2.2、meta 版本位。
- Modify `mf4_analyzer/help/time-domain-guide.html` — 新增「滤波」「overlay 缩放/滚轮」步骤页 + GPU 一句。
- Modify `mf4_analyzer/help/fft-guide.html` — 新增「频率加权 / A 计权」内容。
- Modify `mf4_analyzer/help/ffttime-guide.html` — 新增「频率加权 / A 计权」内容。
- Modify `mf4_analyzer/help/order-analysis-guide.html` — 新增「频率加权」+「跨速率」内容。
- Create `tools/gen_help_screenshots.py` — 4 面板截图生成器（staging + --promote）。
- Create `tests/test_help_content.py` — 帮助内容覆盖 + 主手册 JSON 合法性守卫。
- Create `tests/test_gen_help_screenshots.py` — 生成器纯函数/常量测试。
- Output (untracked) `output/help-shots/*.png` — 截图 staging。

---

## Task 1: 主手册 `deckData` 内容补齐 + 内容守卫测试

**Files:**
- Modify: `mf4_analyzer/help/TraceLab-使用说明.html`（仅顶部 `<script id="deckData">` JSON 块）
- Test: `tests/test_help_content.py`

**Interfaces:**
- Produces: 测试辅助 `_deck_data()`（被本任务测试复用）；主手册新增 slide `id: "filter"`。

- [ ] **Step 1: 写失败测试** — `tests/test_help_content.py`

```python
import json
import re
from pathlib import Path

HELP = Path(__file__).resolve().parents[1] / "mf4_analyzer" / "help"
MANUAL = HELP / "TraceLab-使用说明.html"


def _deck_data() -> dict:
    """Extract and parse the deckData JSON block from the main manual."""
    html = MANUAL.read_text(encoding="utf-8")
    m = re.search(
        r'<script type="application/json" id="deckData">(.*?)</script>',
        html, re.S,
    )
    assert m, "deckData block not found"
    return json.loads(m.group(1))


def test_deck_data_valid_and_version_bumped():
    d = _deck_data()
    assert d["meta"]["updated"] == "2026-06-25"
    assert d["meta"]["docVersion"] == "2.1"
    assert "v2.2" in [c["v"] for c in d["changelog"]]


def test_manual_has_filter_slide():
    d = _deck_data()
    assert any(s.get("id") == "filter" for s in d["slides"])


def test_manual_covers_new_features():
    html = MANUAL.read_text(encoding="utf-8")
    for kw in ["滤波", "低通", "高通", "带通", "带阻", ".blf", "DBC",
               "GPU", "框选", "A 计权", "采样率"]:
        assert kw in html, f"manual missing: {kw}"


def test_help_has_no_developer_jargon():
    banned = ["pyqtgraph", "matplotlib", "scipy", "QWidget", "PyQt5"]
    for f in HELP.glob("*.html"):
        text = f.read_text(encoding="utf-8")
        for b in banned:
            assert b not in text, f"{f.name} contains dev jargon: {b}"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_help_content.py -v`
Expected: FAIL（`test_deck_data_valid_and_version_bumped` 等失败，因 docVersion 仍是 2.0、无 filter 页、缺关键词）

- [ ] **Step 3: 改 `meta` 版本位**

把 JSON 里：
```json
    "docVersion": "2.0",
    "updated": "2026-06-20"
```
改为：
```json
    "docVersion": "2.1",
    "updated": "2026-06-25"
```

- [ ] **Step 4: 在 `time` slide 之后插入「滤波」slide**

在 `{ "id": "time", ... }` 对象的结尾 `},` 之后、`{ "id": "multiview", ...` 之前插入：
```json
    { "id": "filter", "sec": "看波形", "kicker": "TIME DOMAIN · FILTER", "title": "看波形 · <c>滤波</c>对比", "foot": "原始实线 · 滤波虚线",
      "blocks": [
        { "type": "when", "html": "想滤掉高频毛刺、或只留某段频率看清趋势时用它——在时域里直接做，立刻看前后对比。" },
        { "type": "cols", "align": "start",
          "left": [ { "type": "steps", "items": [
            "在右侧「时间范围 · 滤波」卡片里打开<b>滤波</b>开关。",
            "选类型：<b>低通 / 高通 / 带通 / 带阻</b>，填截止频率（带通 / 带阻填上下两个）。",
            "选<b>陡峭程度</b>（越大越陡），点 <span class='mono'>绘图</span>。",
            "勾「显示原始 / 显示滤波后」做<b>前后对比</b>——滤波结果以<b>虚线</b>叠在原曲线上。"
          ] } ],
          "right": [ { "type": "card", "accent": "teal", "no": "放心用", "h": "不变形 · 不卡 · 可随时关",
            "paras": [
              "滤波<b>不会让波形前后错位</b>，峰谷的时间位置仍然准。",
              "截止频率<b>超过该通道能表达的上限</b>时会自动收回并提示。",
              "滤波只用于<b>时域显示对比</b>，不改 FFT / 阶次的计算，也不写进工程。"
            ] } ] }
      ] },
```

- [ ] **Step 5: 给 `load` slide 的「支持的文件」加 `.blf` + DBC 说明**

把 load slide 里 `"pills": [".mf4", ".mdf", ".csv", ".xlsx", ".xls", ".hdf", ".mp4", ".mp3", ".wav"]` 改为在末尾加 `".blf"`：
```json
            "pills": [".mf4", ".mdf", ".csv", ".xlsx", ".xls", ".hdf", ".mp4", ".mp3", ".wav", ".blf"],
```
并在该 card 的 `"paras"` 数组末尾追加一段：
```json
              "<b>CAN 总线录制（.blf）</b>也能打开：第一次会让你选一个 <b>DBC 数据库</b>把信号翻译出来；选过之后，<b>同一条总线</b>的下一个 .blf 会自动推荐上次的 DBC，一键确认即可。DBC 的选择会随工程一起记住。"
```

- [ ] **Step 6: 给 `order` slide 加「跨速率」提示**

在 order slide 的 `"blocks"` 数组末尾（最后一个 `cols` 块之后）追加：
```json
        { "type": "tip", "label": "提示", "html": "转速通道和信号通道<b>采样率不一样也没关系</b>（比如转速记得稀、振动记得密），软件会自动对齐再算阶次。分析声音类信号时，还能像 FFT 一样开 <b>A 计权</b>。" }
```

- [ ] **Step 7: 给 `cheat`（速查）slide 的左侧 `kv` 加 overlay/GPU 行**

在 cheat slide 左侧 `kv` 的 `"items"` 数组末尾追加四行：
```json
            { "k": "叠加 · 框选放大", "v": "在叠加图上框一块，所有通道的纵向一起跟着放大（不用先选某条）" },
            { "k": "叠加 · Shift+滚轮", "v": "横向缩放时间轴" },
            { "k": "叠加 · Alt/Option+滚轮", "v": "只缩当前这条通道的纵向刻度" },
            { "k": "GPU 加速（时域）", "v": "右侧面板右下角；多通道 / 高分屏卡顿时再开，导出图片不受影响" }
```

- [ ] **Step 8: 在 `changelog` 顶部新增 v2.2 条目**

在 `"changelog": [` 之后、`{ "v": "v2.1", ...` 之前插入：
```json
    { "v": "v2.2", "date": "2026-06-25", "items": [
      "时域新增<b>滤波</b>：低通 / 高通 / 带通 / 带阻 + 陡峭度，勾「显示滤波后」与原曲线做<b>前后对比</b>（虚线叠加）。",
      "「打开数据」新增支持 <b>CAN 总线录制（.blf）</b>：首次选 DBC 翻译信号，同总线后续自动推荐、随工程记住。",
      "叠加视图交互升级：<b>框选放大同步所有通道</b>；Shift / Alt 滚轮分别缩时间轴 / 单通道纵轴。",
      "新增<b>时域图 GPU 加速</b>开关（右侧面板右下，默认关，卡顿时再开）。",
      "阶次支持<b>转速与信号采样率不同</b>；时频 / 阶次的自动色阶范围更精细。"
    ] },
```

- [ ] **Step 9: 运行测试确认通过**

Run: `pytest tests/test_help_content.py -v`
Expected: 4 个测试全 PASS（若 `test_help_has_no_developer_jargon` 在既有文件上失败，说明既有文件有开发词，按面向用户原则就地清理后再过）

- [ ] **Step 10: 提交**

```bash
git add "mf4_analyzer/help/TraceLab-使用说明.html" tests/test_help_content.py
git commit -m "docs(help): 主手册补齐滤波/BLF/overlay/GPU/跨速率 + 内容守卫测试

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011UGHyVqvAKk2k1MtuJUs2o" -- "mf4_analyzer/help/TraceLab-使用说明.html" tests/test_help_content.py
```

---

## Task 2: `time-domain-guide.html` 新增滤波 + overlay 交互页

**Files:**
- Modify: `mf4_analyzer/help/time-domain-guide.html`（在 `</main>` 之前插入新 `<section class="slide">`）
- Test: `tests/test_help_content.py::test_panel_guides_cover_new_topics`（本任务新增）

**Interfaces:**
- Consumes: 现有 deck.css 类（`slide` / `frame` / `topbar` / `eyebrow` / `step-head` / `step-grid` / `instr` / `blk` / `k` / `ui` / `pos` / `note` / `tbar`）。
- Produces: 该文件含「滤波」「框选/滚轮」内容。

- [ ] **Step 1: 给 `tests/test_help_content.py` 加面板指南覆盖测试**

在 `tests/test_help_content.py` 末尾追加：
```python
def test_panel_guides_cover_new_topics():
    checks = {
        "time-domain-guide.html": ["滤波", "框选", "Shift"],
        "fft-guide.html": ["A 计权"],
        "ffttime-guide.html": ["A 计权"],
        "order-analysis-guide.html": ["加权", "采样率"],
    }
    for fname, kws in checks.items():
        text = (HELP / fname).read_text(encoding="utf-8")
        for kw in kws:
            assert kw in text, f"{fname} missing: {kw}"
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_help_content.py::test_panel_guides_cover_new_topics -v`
Expected: FAIL（time guide 无「滤波」等）

- [ ] **Step 3: 在 `time-domain-guide.html` 的 `</main>` 之前插入「滤波」slide**

```html
    <section class="slide">
        <div class="frame">
            <div class="topbar reveal d1"><span class="eyebrow">05 · <b>滤波看前后</b></span><span class="turbo-rule"></span></div>
            <div class="step-head reveal d2"><span class="big">05</span><h2>滤掉杂讯，原始对滤波</h2></div>
            <div class="step-grid">
                <div class="instr">
                    <div class="blk reveal d3"><span class="k">①</span><p>右侧 <span class="ui">时间范围 · 滤波</span> 卡片里打开<span class="ui">滤波</span>开关。</p></div>
                    <div class="blk reveal d4"><span class="k">②</span><p>选 <span class="ui">低通 / 高通 / 带通 / 带阻</span>，填截止频率，选陡峭程度，点 <span class="ui">绘图</span>。</p></div>
                    <div class="blk reveal d5"><span class="k">▸</span><p>勾 <span class="ui">显示原始 / 显示滤波后</span> 做<b>前后对比</b>：滤波结果是<b>虚线</b>，叠在原曲线上。</p></div>
                    <div class="blk reveal d5"><span class="k">▸</span><p>滤波<b>不让波形错位</b>、不改 FFT / 阶次结果；超出范围会自动提示。</p></div>
                </div>
                <div class="mock reveal d3">
                    <div class="cap"><span>滤波</span><em>右侧卡片</em></div>
                    <div class="row" style="justify-content:flex-start;gap:14px"><span class="ui">滤波 ●</span><span class="pos">低通 · 100 Hz</span></div>
                    <div style="background:#fff;padding:14px;margin-top:10px">
                        <svg viewBox="0 0 600 90" preserveAspectRatio="none" style="width:100%;height:80px">
                            <polyline points="0,55 40,20 80,70 120,25 160,68 200,22 240,66 280,28 320,64 360,24 400,68 440,26 480,62 520,30 560,60 600,40" fill="none" stroke="#1769e0" stroke-width="2"/>
                            <polyline points="0,55 80,48 160,44 240,42 320,42 400,43 480,45 560,48 600,50" fill="none" stroke="#13a36b" stroke-width="3" stroke-dasharray="7 6"/>
                        </svg>
                    </div>
                    <p class="note" style="margin-top:10px"><b>实线</b>＝原始；<b>虚线</b>＝滤波后。</p>
                </div>
            </div>
        </div>
    </section>
```

- [ ] **Step 4: 紧接着插入「overlay 缩放 / 滚轮」slide**

```html
    <section class="slide">
        <div class="frame">
            <div class="topbar reveal d1"><span class="eyebrow">06 · <b>叠加图怎么缩放</b></span><span class="turbo-rule"></span></div>
            <div class="step-head reveal d2"><span class="big">06</span><h2>叠加模式 · 框选与滚轮</h2></div>
            <div class="step-grid" style="grid-template-columns:1fr 1fr;align-items:center">
                <div class="instr">
                    <div class="blk reveal d3"><span class="k">▸</span><p><b>框选放大</b>：在叠加图上框一块，<b>所有通道</b>的纵向一起按这块放大——<span class="pos">不用先选某条通道</span>。</p></div>
                    <div class="blk reveal d4"><span class="k">▸</span><p><b>裸滚轮</b>＝整图上下平移；<span class="ui">Shift+滚轮</span>＝横向缩放时间轴。</p></div>
                    <div class="blk reveal d5"><span class="k">▸</span><p><span class="ui">Alt / Option + 滚轮</span>＝只缩<b>当前这条</b>通道的纵向刻度。</p></div>
                    <div class="blk reveal d5"><span class="k">▸</span><p>在<b>坐标轴刻度区</b>拖动＝只拖该通道的轴；在<b>图中间</b>拖＝整体平移。</p></div>
                </div>
                <div class="reveal d3">
                    <div class="viz">
                        <div style="background:#fff;padding:14px;position:relative">
                            <svg viewBox="0 0 600 130" preserveAspectRatio="none" style="width:100%;height:120px">
                                <polyline points="0,40 100,30 200,55 300,35 400,60 500,38 600,50" fill="none" stroke="#1769e0" stroke-width="2.5"/>
                                <polyline points="0,90 100,80 200,100 300,85 400,105 500,88 600,98" fill="none" stroke="#13a36b" stroke-width="2.5"/>
                                <rect x="220" y="15" width="150" height="105" fill="rgba(23,105,224,.10)" stroke="#1769e0" stroke-dasharray="5 4"/>
                            </svg>
                        </div>
                    </div>
                    <p class="note reveal d4" style="margin-top:14px">框住的范围＝放大后看到的范围，<b>每条通道各按自己的比例缩</b>。</p>
                    <p class="note reveal d5" style="margin-top:10px">图卡顿时，可在右侧面板右下角打开 <span class="ui">GPU 加速（时域图）</span>（默认关）。</p>
                </div>
            </div>
        </div>
    </section>
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest "tests/test_help_content.py::test_panel_guides_cover_new_topics" -v`
Expected: time-domain-guide 的断言通过（fft/ffttime/order 仍失败，留给后续任务）

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/help/time-domain-guide.html tests/test_help_content.py
git commit -m "docs(help): 时域指南新增滤波 + overlay 缩放/滚轮页

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011UGHyVqvAKk2k1MtuJUs2o" -- mf4_analyzer/help/time-domain-guide.html tests/test_help_content.py
```

---

## Task 3: `fft-guide.html` + `ffttime-guide.html` 加 A 计权说明

**Files:**
- Modify: `mf4_analyzer/help/fft-guide.html`
- Modify: `mf4_analyzer/help/ffttime-guide.html`
- Test: `tests/test_help_content.py::test_panel_guides_cover_new_topics`

**Interfaces:**
- Consumes: 各指南现有 deck.css 类（与 time guide 同款 `slide/frame/topbar/step-head/step-grid/instr/blk/mock`）。
- Produces: 两个文件含 `A 计权`。

- [ ] **Step 1: 运行测试确认当前失败**

Run: `pytest "tests/test_help_content.py::test_panel_guides_cover_new_topics" -v`
Expected: FAIL（fft-guide / ffttime-guide 缺 `A 计权`）

- [ ] **Step 2: 在 `fft-guide.html` 的 `</main>` 之前插入「频率加权」slide**

```html
    <section class="slide">
        <div class="frame">
            <div class="topbar reveal d1"><span class="eyebrow">+ · <b>频率加权 / A 计权</b></span><span class="turbo-rule"></span></div>
            <div class="step-head reveal d2"><span class="big">+</span><h2>分析声音 · 开 A 计权</h2></div>
            <div class="step-grid">
                <div class="instr">
                    <div class="blk reveal d3"><span class="k">①</span><p>右侧面板找到 <span class="ui">频率加权</span>，默认是 <span class="ui">无</span>。</p></div>
                    <div class="blk reveal d4"><span class="k">②</span><p>分析<b>声音</b>类信号时切到 <span class="ui">A 计权</span>：按人耳听感对各频段加权（IEC 61672 标准），更贴近主观响度。</p></div>
                    <div class="blk reveal d5"><span class="k">▸</span><p>打开<b>音视频文件</b>时，软件会<b>自动</b>把加权预设成 A，你也可以手动改回无。</p></div>
                    <div class="blk reveal d5"><span class="k">▸</span><p>这是<b>相对加权</b>（看各频段相对强弱），不是绝对声压级 dB。</p></div>
                </div>
                <div class="mock reveal d3">
                    <div class="cap"><span>频率加权</span><em>右侧</em></div>
                    <div class="row" style="justify-content:flex-start;gap:14px"><span class="ui">无</span><span class="ui" style="background:#13a36b;color:#fff">A 计权</span></div>
                    <div style="background:#fff;padding:14px;margin-top:10px">
                        <svg viewBox="0 0 600 90" preserveAspectRatio="none" style="width:100%;height:80px">
                            <polyline points="0,80 80,40 160,30 240,28 320,32 400,40 480,52 560,66 600,74" fill="none" stroke="#13a36b" stroke-width="3"/>
                        </svg>
                    </div>
                    <p class="note" style="margin-top:10px">低频和极高频被压低，中频保留——这就是 A 计权曲线。</p>
                </div>
            </div>
        </div>
    </section>
```

- [ ] **Step 3: 在 `ffttime-guide.html` 的 `</main>` 之前插入同主题 slide**

```html
    <section class="slide">
        <div class="frame">
            <div class="topbar reveal d1"><span class="eyebrow">+ · <b>频率加权 / A 计权</b></span><span class="turbo-rule"></span></div>
            <div class="step-head reveal d2"><span class="big">+</span><h2>时频图也能开 A 计权</h2></div>
            <div class="step-grid">
                <div class="instr">
                    <div class="blk reveal d3"><span class="k">①</span><p>右侧 <span class="ui">频率加权</span> 选 <span class="ui">A 计权</span>，整张时频图按人耳听感（IEC 61672）重新加权。</p></div>
                    <div class="blk reveal d4"><span class="k">▸</span><p>分析录音、噪声升降的<b>声学</b>场景时更直观；打开音视频文件会自动预设成 A。</p></div>
                    <div class="blk reveal d5"><span class="k">▸</span><p>属<b>相对加权</b>显示，配合右侧<b>显示范围</b>一起调，弱信号也看得清。</p></div>
                </div>
                <div class="mock reveal d3">
                    <div class="cap"><span>频率加权</span><em>右侧</em></div>
                    <div class="row" style="justify-content:flex-start;gap:14px"><span class="ui">无</span><span class="ui" style="background:#13a36b;color:#fff">A 计权</span></div>
                    <p class="note" style="margin-top:14px">同一段录音，开 A 计权后高低频被压、中频突出，更接近「听上去」的样子。</p>
                </div>
            </div>
        </div>
    </section>
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest "tests/test_help_content.py::test_panel_guides_cover_new_topics" -v`
Expected: fft-guide / ffttime-guide 断言通过（order 仍失败，留给 Task 4）

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/help/fft-guide.html mf4_analyzer/help/ffttime-guide.html
git commit -m "docs(help): FFT / 时频图指南新增 A 计权说明

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011UGHyVqvAKk2k1MtuJUs2o" -- mf4_analyzer/help/fft-guide.html mf4_analyzer/help/ffttime-guide.html
```

---

## Task 4: `order-analysis-guide.html` 加 A 计权 + 跨速率

**Files:**
- Modify: `mf4_analyzer/help/order-analysis-guide.html`
- Test: `tests/test_help_content.py::test_panel_guides_cover_new_topics`

**Interfaces:**
- Consumes: order guide 现有 deck.css 类。
- Produces: 该文件含 `加权` 与 `采样率`。

- [ ] **Step 1: 运行测试确认当前失败**

Run: `pytest "tests/test_help_content.py::test_panel_guides_cover_new_topics" -v`
Expected: FAIL（order-analysis-guide 缺 `加权` / `采样率`）

- [ ] **Step 2: 在 `order-analysis-guide.html` 的 `</main>` 之前插入「加权 + 跨速率」slide**

注：阶次 base 是<b>电机转速</b>（EPS 域），示例信号用电机转速 / 方向盘扭矩。
```html
    <section class="slide">
        <div class="frame">
            <div class="topbar reveal d1"><span class="eyebrow">+ · <b>跨速率 + 频率加权</b></span><span class="turbo-rule"></span></div>
            <div class="step-head reveal d2"><span class="big">+</span><h2>转速记得稀也能算</h2></div>
            <div class="step-grid">
                <div class="instr">
                    <div class="blk reveal d3"><span class="k">▸</span><p><b>转速通道和信号通道采样率不同也没关系</b>：比如<span class="ui">电机转速</span>记得稀、振动记得密，软件会自动对齐再算阶次。</p></div>
                    <div class="blk reveal d4"><span class="k">▸</span><p>阶次的基准是<b>电机转速</b>——第 N 阶＝振动频率是电机转速的 N 倍。</p></div>
                    <div class="blk reveal d5"><span class="k">▸</span><p>分析<b>声音</b>类信号时，右侧 <span class="ui">频率加权</span> 可切 <span class="ui">A 计权</span>（IEC 61672），更贴近主观响度。</p></div>
                </div>
                <div class="mock reveal d3">
                    <div class="cap"><span>转速 / 信号</span><em>可不同采样率</em></div>
                    <div class="chk"><span class="box">✓</span>电机转速 · 1 kHz</div>
                    <div class="chk"><span class="box">✓</span>振动 · 8 kHz</div>
                    <p class="note" style="margin-top:14px">两路采样率不同，软件自动对齐——问题阶次仍稳稳落在同一条线上。</p>
                </div>
            </div>
        </div>
    </section>
```

- [ ] **Step 3: 运行测试确认全部通过**

Run: `pytest tests/test_help_content.py -v`
Expected: 全部 PASS（含 order 断言）

- [ ] **Step 4: 提交**

```bash
git add mf4_analyzer/help/order-analysis-guide.html
git commit -m "docs(help): 阶次指南新增跨速率 + A 计权说明

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011UGHyVqvAKk2k1MtuJUs2o" -- mf4_analyzer/help/order-analysis-guide.html
```

---

## Task 5: 配图生成脚本 `tools/gen_help_screenshots.py` + 纯函数测试

**Files:**
- Create: `tools/gen_help_screenshots.py`
- Test: `tests/test_gen_help_screenshots.py`

**Interfaces:**
- Consumes（均已在代码库验证存在）：`mf4_analyzer.ui.MainWindow`、`win.load_file(path)`、`win.toolbar._set_mode(mode)`、`win.do_fft()` / `win.do_order_time()` / `win.do_fft_time()`、`win.inspector.fft_ctx / fft_time_ctx / order_ctx`、`win.canvas_time / canvas_fft / canvas_fft_time / canvas_order`、`mf4_analyzer.ui.widgets.MultiFileChannelWidget`（`.tree` QTreeWidget，叶子 `setCheckState(0, Qt.Checked)`）。
- Produces: `build_synthetic_csv() -> Path`、常量 `PANEL_MODES = ("time", "fft", "fft_time", "order")`、`STAGING_DIR`、`ASSETS_DIR`、`PANEL_FILES`、`main() -> int`。

- [ ] **Step 1: 写失败测试** — `tests/test_gen_help_screenshots.py`

```python
from pathlib import Path


def test_panel_modes_and_files_align():
    from tools.gen_help_screenshots import PANEL_MODES, PANEL_FILES
    assert PANEL_MODES == ("time", "fft", "fft_time", "order")
    # 每个 mode 都有对应的目标 *-panel.png 文件名
    assert set(PANEL_FILES) == set(PANEL_MODES)
    assert PANEL_FILES["time"] == "time-panel.png"
    assert PANEL_FILES["fft_time"] == "ffttime-panel.png"


def test_synthetic_csv_has_rpm_and_signal():
    from tools.gen_help_screenshots import build_synthetic_csv
    path = build_synthetic_csv()
    assert path.exists()
    header = path.read_text(encoding="utf-8").splitlines()[0]
    for col in ("time", "rpm", "vib", "torque"):
        assert col in header, f"synthetic CSV missing column: {col}"


def test_staging_dir_is_under_output_not_assets():
    from tools.gen_help_screenshots import STAGING_DIR, ASSETS_DIR
    assert STAGING_DIR.parts[-2:] == ("output", "help-shots")
    assert ASSETS_DIR.parts[-3:] == ("mf4_analyzer", "help", "assets")
```

- [ ] **Step 2: 运行确认失败**

Run: `pytest tests/test_gen_help_screenshots.py -v`
Expected: FAIL（`ModuleNotFoundError: tools.gen_help_screenshots`）

- [ ] **Step 3: 写脚本** — `tools/gen_help_screenshots.py`

```python
"""Regenerate the four help-guide panel screenshots (time / fft / fft_time /
order) by booting the real MainWindow, loading synthetic data, driving each
mode to a populated state, and grabbing the whole window at 2x.

Outputs to a STAGING dir (output/help-shots/) by default — review the PNGs,
then re-run with --promote to copy them over mf4_analyzer/help/assets/. The
guides' numbered pins are tied to UI element positions, so after promoting
NEW screenshots you must re-check the pin left/top% in each *-guide.html.

Renders against a REAL Qt platform (cocoa on macOS) by default so the panels
look exactly as the user sees them. --platform offscreen is a headless
fallback for layout/draft ONLY (offscreen != real render; do not treat an
offscreen image as visually verified).

Window geometry is FIXED (1280x820) so pin coordinates stay stable across
regenerations; only move pins when a UI control actually relocates.

Usage:
    .venv/bin/python tools/gen_help_screenshots.py                 # all 4 -> staging
    .venv/bin/python tools/gen_help_screenshots.py --only time
    .venv/bin/python tools/gen_help_screenshots.py --platform offscreen
    .venv/bin/python tools/gen_help_screenshots.py --promote       # copy staging -> assets
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

PANEL_MODES = ("time", "fft", "fft_time", "order")
PANEL_FILES = {
    "time": "time-panel.png",
    "fft": "fft-panel.png",
    "fft_time": "ffttime-panel.png",
    "order": "order-panel.png",
}
STAGING_DIR = REPO_ROOT / "output" / "help-shots"
ASSETS_DIR = REPO_ROOT / "mf4_analyzer" / "help" / "assets"
WIN_W, WIN_H = 1280, 820
GRAB_SCALE = 2


def build_synthetic_csv() -> Path:
    """rpm ramp 600->3600 + vib (order1+order2) + a torque channel."""
    fs = 8000.0
    dur = 6.0
    n = int(fs * dur)
    t = np.arange(n, dtype=float) / fs
    rpm = np.linspace(600.0, 3600.0, n)
    revs = np.cumsum(rpm / 60.0) / fs
    phase = 2.0 * np.pi * revs
    rng = np.random.default_rng(7)
    vib = 1.0 * np.sin(phase) + 0.6 * np.sin(2.0 * phase) + 0.05 * rng.standard_normal(n)
    torque = 8.0 + 2.0 * np.sin(2.0 * np.pi * 0.5 * t) + 0.02 * rng.standard_normal(n)
    out = Path(tempfile.gettempdir()) / "_help_shots_synth.csv"
    data = np.column_stack([t, rpm, vib, torque])
    np.savetxt(out, data, delimiter=",", header="time,rpm,vib,torque",
               comments="", fmt="%.6g")
    return out


def _select_combo_by_channel(combo, channel_name: str) -> bool:
    for i in range(combo.count()):
        data = combo.itemData(i)
        if isinstance(data, tuple) and len(data) == 2 and data[1] == channel_name:
            combo.setCurrentIndex(i)
            return True
    return False


def _check_channels(win, names) -> None:
    """Tick the named channel leaves in the left MultiFileChannelWidget tree."""
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.widgets import MultiFileChannelWidget
    widget = win.findChild(MultiFileChannelWidget)
    if widget is None:
        return
    tree = widget.tree
    for top in range(tree.topLevelItemCount()):
        file_node = tree.topLevelItem(top)
        for i in range(file_node.childCount()):
            leaf = file_node.child(i)
            if leaf.text(0) in names:
                leaf.setCheckState(0, Qt.Checked)


def _wait(loop_factory, trigger, finished_attr, failed_attr, win, timeout_ms=60_000):
    """Drive a worker-backed compute and block until finished/failed/timeout."""
    from PyQt5.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    done = {"ok": False}
    orig_fin = getattr(win, finished_attr)
    orig_fail = getattr(win, failed_attr)

    def on_fin(result, _o=orig_fin):
        _o(result)
        done["ok"] = True
        loop.quit()

    def on_fail(msg, _o=orig_fail):
        _o(msg)
        loop.quit()

    setattr(win, finished_attr, on_fin)
    setattr(win, failed_attr, on_fail)
    wd = QTimer()
    wd.setSingleShot(True)
    wd.timeout.connect(loop.quit)
    wd.start(timeout_ms)
    trigger()
    loop.exec_()
    wd.stop()
    setattr(win, finished_attr, orig_fin)
    setattr(win, failed_attr, orig_fail)
    return done["ok"]


def _drive_mode(win, app, mode: str) -> None:
    win.toolbar._set_mode(mode)
    app.processEvents()
    if mode == "time":
        _check_channels(win, {"vib", "torque"})
        app.processEvents()
        return
    if mode == "fft":
        _select_combo_by_channel(win.inspector.fft_ctx.combo_sig, "vib")
        app.processEvents()
        win.do_fft()  # FFT renders synchronously
        for _ in range(5):
            app.processEvents()
        return
    if mode == "fft_time":
        _select_combo_by_channel(win.inspector.fft_time_ctx.combo_sig, "vib")
        app.processEvents()
        _wait(None, lambda: win.do_fft_time(force=True),
              "_on_fft_time_finished", "_on_fft_time_failed", win)
        for _ in range(5):
            app.processEvents()
        return
    if mode == "order":
        ctx = win.inspector.order_ctx
        _select_combo_by_channel(ctx.combo_sig, "vib")
        _select_combo_by_channel(ctx.combo_rpm, "rpm")
        ctx.set_fs(8000.0)
        ctx.apply_params({"max_order": 6, "order_res": 0.05, "time_res": 0.05,
                          "nfft": 4096, "amplitude_mode": "Amplitude",
                          "x_auto": True, "y_auto": True, "z_auto": True})
        app.processEvents()
        _wait(None, win.do_order_time,
              "_on_order_finished", "_on_order_failed", win)
        for _ in range(5):
            app.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", default=None,
                        help="QT_QPA_PLATFORM override (e.g. offscreen)")
    parser.add_argument("--only", choices=PANEL_MODES, default=None)
    parser.add_argument("--promote", action="store_true",
                        help="copy staging PNGs over help/assets after review")
    args = parser.parse_args()

    if args.platform:
        os.environ["QT_QPA_PLATFORM"] = args.platform
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.ui import MainWindow
    from mf4_analyzer.ui_kit import (setup_chinese_font, load_stylesheet,
                                     install_glass_tooltips)

    setup_chinese_font()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    load_stylesheet(app)
    install_glass_tooltips(app)

    win = MainWindow()
    win.resize(WIN_W, WIN_H)
    win.show()
    app.processEvents()
    win.load_file(str(build_synthetic_csv()))
    app.processEvents()

    modes = (args.only,) if args.only else PANEL_MODES
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for mode in modes:
        _drive_mode(win, app, mode)
        pix = win.grab()
        if GRAB_SCALE != 1:
            pix = pix.scaled(WIN_W * GRAB_SCALE, WIN_H * GRAB_SCALE)
        out = STAGING_DIR / PANEL_FILES[mode]
        if pix.isNull() or pix.width() < 10:
            print(f"FAIL: degenerate pixmap for {mode}", file=sys.stderr)
            return 2
        pix.save(str(out))
        saved.append(out)
        print(f"saved staging: {out} ({pix.width()}x{pix.height()})")

    if args.promote:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        for src in saved:
            dst = ASSETS_DIR / src.name
            shutil.copy2(src, dst)
            print(f"promoted: {dst}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 运行纯函数测试确认通过**

Run: `pytest tests/test_gen_help_screenshots.py -v`
Expected: 3 个测试 PASS

- [ ] **Step 5: offscreen 烟雾跑一次（验证脚本能产图，非真机验收）**

Run: `.venv/bin/python tools/gen_help_screenshots.py --platform offscreen --only time`
Expected: 打印 `saved staging: .../output/help-shots/time-panel.png (2560x1640)`，文件存在。
注：若项目在 `~/Downloads` 触发 TCC EPERM 导致子进程无法写文件/启动，记录现象并把这步连同 Task 6 的真机生成一起交用户在本机跑（见 Task 6 §交付拆分）。

- [ ] **Step 6: 提交**

```bash
git add tools/gen_help_screenshots.py tests/test_gen_help_screenshots.py
git commit -m "tools: 新增 help 面板截图生成脚本(staging + --promote)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011UGHyVqvAKk2k1MtuJUs2o" -- tools/gen_help_screenshots.py tests/test_gen_help_screenshots.py
```

---

## Task 6: 重出 4 张面板图 + 重定位 pin（真机验证环节）

**Files:**
- Run: `tools/gen_help_screenshots.py`
- Modify（按需重定位 pin）: `mf4_analyzer/help/time-domain-guide.html`、`fft-guide.html`、`ffttime-guide.html`、`order-analysis-guide.html`
- Promote: `mf4_analyzer/help/assets/{time,fft,ffttime,order}-panel.png`

**Interfaces:**
- Consumes: Task 5 的 `gen_help_screenshots.py`；各指南里现有的 `<div class="pin" style="left:..%;top:..%">N</div>`。

- [ ] **Step 1: 真机生成 4 张图到 staging**

Run（本机 cocoa，必要时由用户在终端执行）：
`.venv/bin/python tools/gen_help_screenshots.py`
Expected: `output/help-shots/` 下出现 4 张非退化 PNG（约 2560×1640）。

- [ ] **Step 2: 逐图核对 pin 是否仍对位**

对 time / fft / ffttime / order 四个指南：用 Read 工具打开 `output/help-shots/<x>-panel.png` 看图，对照该指南第二页 `.shot` 里每个 `.pin` 的 `left/top%` 是否仍落在它标注的 UI 元素上（如时域的「分屏/叠加」「游标」按钮、FFT 的「频率加权」下拉等）。

- [ ] **Step 3: 重定位漂移的 pin**

对位置不对的 pin，调整其 `style="left:..%;top:..%"`。例（仅示意，按实图改）：时域面板新增滤波卡片后，若「View 标签」pin 下移，把 `top:93.5%` 调到实际位置。每改一个 pin，浏览器打开该 guide 复核数字落点。

- [ ] **Step 4: 真机肉眼验收（CLAUDE.md 红线）**

在浏览器逐个打开 4 个 `*-guide.html`，确认：截图清晰、pin 数字对准其说明的 UI、整体观感与真实软件一致。**只有真机渲染 + 肉眼确认后**，才认定截图通过；offscreen 图不算。

- [ ] **Step 5: 提升进 assets**

Run: `.venv/bin/python tools/gen_help_screenshots.py --promote`
（或确认 staging 图已满意后单独 `--promote`）

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/help/assets/time-panel.png mf4_analyzer/help/assets/fft-panel.png mf4_analyzer/help/assets/ffttime-panel.png mf4_analyzer/help/assets/order-panel.png mf4_analyzer/help/time-domain-guide.html mf4_analyzer/help/fft-guide.html mf4_analyzer/help/ffttime-guide.html mf4_analyzer/help/order-analysis-guide.html
git commit -m "docs(help): 重出 4 张面板截图并重定位 pin(真机验收)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011UGHyVqvAKk2k1MtuJUs2o" -- mf4_analyzer/help/assets/time-panel.png mf4_analyzer/help/assets/fft-panel.png mf4_analyzer/help/assets/ffttime-panel.png mf4_analyzer/help/assets/order-panel.png mf4_analyzer/help/time-domain-guide.html mf4_analyzer/help/fft-guide.html mf4_analyzer/help/ffttime-guide.html mf4_analyzer/help/order-analysis-guide.html
```

### 交付拆分（TCC 约束）

- Claude 可独立完成 Task 1–5（内容 + 脚本 + 纯函数测试 + 提交）。
- Task 6 依赖**真机 GUI 渲染**：若 `~/Downloads` 的 TCC EPERM 阻止 Claude 经 Bash 启动 cocoa 渲染/写文件，则 Task 6 的生成（Step 1）与 `--promote`（Step 5）交用户在本机 `! .venv/bin/python tools/gen_help_screenshots.py [--promote]` 执行；pin 重定位（Step 3）与肉眼验收（Step 4）可在用户跑出图后由 Claude 用 Read 看图协助、或用户自行核对。Claude 绝不把 offscreen 图当「真机已验」交付。

---

## Self-Review

**Spec coverage**（对照 spec §3 / §4 / §5 / §6）：
- 时域滤波 → Task 1 Step 4 + Task 2 Step 3 ✅
- overlay 交互（框选/Shift/Alt/拖拽）→ Task 1 Step 7 + Task 2 Step 4 ✅
- GPU 开关 → Task 1 Step 7/8 + Task 2 Step 4 ✅
- BLF/DBC 导入 → Task 1 Step 5 + changelog Step 8 ✅
- 跨速率 Order → Task 1 Step 6 + Task 4 Step 2 ✅
- 色阶 30dB → Task 1 Step 8（changelog 一句）✅
- A 计权（fft/ffttime/order）→ Task 3 + Task 4 ✅
- changelog v2.2 + meta 版本位 → Task 1 Step 3/8 ✅
- 配图脚本（staging/--promote/offscreen/固定几何）→ Task 5 ✅
- 重出截图 + 重定位 pin + 真机验收 → Task 6 ✅
- 未发布功能仅主手册措辞软化 → Task 1（BLF/跨速率写主手册），面板指南只写已发布 ✅
- 验收标准（JSON 合法、无开发词、脚本可跑、真机 claim 有据）→ Task 1 测试 + Task 5 测试 + Task 6 Step 4 ✅

**Placeholder scan:** 无 TBD/TODO；每个代码步骤含完整内容。

**Type consistency:** `PANEL_MODES` / `PANEL_FILES` / `STAGING_DIR` / `ASSETS_DIR` / `build_synthetic_csv` / `_select_combo_by_channel` 在 Task 5 定义并被同任务测试与 `main()` 一致引用；`_deck_data()` 在 Task 1 测试内定义并复用。驱动入口（`do_fft` / `do_fft_time` / `do_order_time` / `_on_*_finished/_failed` / `*_ctx` / `MultiFileChannelWidget.tree`）均已在代码库 grep 验证存在。
