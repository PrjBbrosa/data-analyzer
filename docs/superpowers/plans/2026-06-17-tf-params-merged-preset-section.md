# 时频参数「预设 + 折叠」合并段实施计划（方案 B）

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 按任务逐条实现。步骤用复选框（`- [ ]`）跟踪。每个任务先写失败测试，再实现，再跑测试。

**Goal:** 把 FFT / FFT-vs-Time / Order 三个 section 的「主参数组 + 预设」合并为一个段：预设按钮常驻、详细参数默认折叠、标题行常显参数摘要、折叠态持久化、手动改参数后预设取消高亮。UI 匹配 `docs/mockups/tf-params-merged-section.html`。

**Architecture:** 抽出一个可复用部件 `_CollapsibleParamSection`（封装 mockup 里的「标题行(箭头+标题+右对齐摘要) + 常驻区(预设) + 可折叠 body(详细参数)」），复用现有 `inspectorCollapser` 的 QSS 与 `PersistentTop._sync_collapser` 的折叠/持久化套路。三个 contextual 各自把已有的主参数 `QGroupBox`（清空其标题）塞进 body、把 `preset_bar` 从底部迁到常驻区，并接上摘要联动与高亮清除。

**Tech Stack:** Python, PyQt5（`QToolButton`/`QFrame`/`QFormLayout`/`QSettings`），pytest + pytest-qt（`qtbot`）。

Spec: `docs/superpowers/specs/2026-06-17-tf-params-merged-preset-section.md`

> **测试环境注意：** 本机 `%TEMP%` 受限会让用到 `tmp_path` 的用例报
> `PermissionError [WinError 5]`（环境问题，非代码）。跑测试时加
> `--basetemp=.pytmp/run`（项目内可写目录）绕过。venv 解释器：
> `.venv/Scripts/python.exe`。

---

### Task 1：可复用折叠段部件 `_CollapsibleParamSection`

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`（在 `PresetBar`/`_make_params_card` 附近新增类；参考 `PersistentTop` ~1566–1799 的折叠条实现）
- Test: `tests/ui/test_side_panel_widgets.py`（已有 inspector 部件测试）

- [x] **Step 1：写失败测试**

```python
def test_collapsible_param_section_defaults_collapsed_and_persists(qtbot, tmp_path):
    from PyQt5.QtCore import QSettings
    from PyQt5.QtWidgets import QLabel
    from mf4_analyzer.ui.inspector_sections import _CollapsibleParamSection
    st = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    sec = _CollapsibleParamSection("时频参数", "inspector/fft_time/params_expanded",
                                   settings=st)
    qtbot.addWidget(sec)
    body = QLabel("detail"); sec.set_body(body)
    persistent = QLabel("presets"); sec.add_persistent(persistent)
    sec.set_summary("1024 · hanning · 80%")
    sec.show()
    qtbot.waitExposed(sec)
    # 默认折叠：body 隐藏，摘要可见，箭头朝右
    assert body.isVisible() is False
    assert persistent.isVisible() is True
    assert "1024 · hanning · 80%" in sec.summary_text()
    # 展开 → body 显示并持久化
    sec.set_expanded(True)
    assert body.isVisible() is True
    assert st.value("inspector/fft_time/params_expanded") in (True, "true", 1, "1")
    # 常驻区不受折叠影响
    sec.set_expanded(False)
    assert persistent.isVisible() is True
    assert body.isVisible() is False
```

- [x] **Step 2：实现 `_CollapsibleParamSection`**

  - `__init__(self, title, settings_key, *, settings=None, default_expanded=False, parent=None)`：
    - 头部 `QToolButton(objectName="inspectorCollapser")`，可勾选、AutoRaise、`ToolButtonTextBesideIcon`、左对齐、箭头 Right/Down——直接照搬 `PersistentTop` 的样式串。
    - 头部行用一个 `QHBoxLayout`：左 = toggle 按钮（拉伸），右 = `QLabel`（objectName 如 `inspectorParamSummary`，灰色小字，右对齐）。
    - 常驻容器 `QWidget`（`add_persistent(w)` 往其布局加，如 preset_bar）。
    - 可折叠 body 容器 `QFrame`（`set_body(w)`）。
  - 方法：`set_summary(text)`、`summary_text()`、`set_expanded(bool)`、`is_expanded()`、`add_persistent(w)`、`set_body(w)`。
  - `set_expanded` → body `setVisible`、箭头方向、写 `settings.setValue(key, expanded)`；构造时从 settings 读取（缺省 `default_expanded`，本特性传 `False`）。
  - `settings` 缺省用 `_preset_settings()`；测试可注入。
  - QSS：摘要 label 可在 `style.qss` 加一条 `#inspectorParamSummary { color:#64748b; font-size:11px; }`（匹配 mockup 灰字）。

- [x] **Step 3：跑测试** `… -m pytest tests/ui/test_side_panel_widgets.py -q --basetemp=.pytmp/run`

---

### Task 2：FFT-vs-Time 接入（`FFTTimeContextual`，~3008）

**Files:**
- Modify: `mf4_analyzer/ui/inspector_sections.py`（`时频参数` 组 ~3052–3076；`预设` 组 ~3135–3159；新增摘要/高亮辅助 + apply guard，见 `_apply_preset` ~3505+）
- Test: `tests/ui/test_side_panel_widgets.py`

- [x] **Step 1：写失败测试**

```python
def test_fft_time_params_section_merged_collapsed_with_summary(qtbot):
    from mf4_analyzer.ui.inspector_sections import FFTTimeContextual
    ctx = FFTTimeContextual(); qtbot.addWidget(ctx)
    ctx.show(); qtbot.waitExposed(ctx)
    # 旧的独立「预设」组没了；preset_bar 迁入主参数段的常驻区
    assert not hasattr(ctx, "_preset_group") or ctx._preset_group is None
    sec = ctx._tf_section                       # _CollapsibleParamSection
    assert ctx.preset_bar.isVisible() is True   # 常驻
    assert ctx.is_tf_expanded() is False        # 默认折叠
    assert ctx.combo_nfft.isVisible() is False  # 详细参数折叠
    assert sec.summary_text() == "1024 · hanning · 80%"

def test_fft_time_summary_updates_and_clears_preset_highlight(qtbot):
    ctx = FFTTimeContextual(); qtbot.addWidget(ctx)
    ctx.show(); qtbot.waitExposed(ctx)
    ctx.preset_bar.set_recommended(2)
    ctx.combo_nfft.setCurrentText("2048")       # 手动改
    assert ctx._tf_section.summary_text().startswith("2048 · ")
    assert ctx.preset_bar._recommended_slot is None   # 取消高亮
    ctx.preset_bar.set_recommended(2)
    ctx.chk_remove_mean.setChecked(not ctx.chk_remove_mean.isChecked())
    assert ctx.preset_bar._recommended_slot is None

def test_fft_time_apply_preset_keeps_highlight(qtbot):
    ctx = FFTTimeContextual(); qtbot.addWidget(ctx)
    ctx.show(); qtbot.waitExposed(ctx)
    ctx.preset_bar.set_recommended(2)
    ctx._apply_preset({"nfft": "4096", "window": "hamming", "overlap": 70})
    assert ctx._tf_section.summary_text() == "4096 · hamming · 70%"
    # 程序化应用不应触发「手动改→取消高亮」（guard 生效）
    assert ctx.preset_bar._recommended_slot == 2

def test_fft_time_preset_load_sets_highlight(qtbot):
    ctx = FFTTimeContextual(); qtbot.addWidget(ctx)
    ctx.show(); qtbot.waitExposed(ctx)
    ctx.preset_bar._load(2)
    assert ctx.preset_bar._recommended_slot == 2
    assert ctx.preset_bar._load_btns[2].property("recommended") == "true"
```

- [x] **Step 2：实现**
  - 把 `时频参数` `QGroupBox`（含 combo_nfft/combo_win/spin_overlap/chk_remove_mean）标题清空（`g.setTitle("")`）作为段 body；新建 `self._tf_section = _CollapsibleParamSection("时频参数", "inspector/fft_time/params_expanded")`，`set_body(g)`。
  - 删除底部独立 `预设` 组，把 `self.preset_bar` 改 `self._tf_section.add_persistent(self.preset_bar)`。
  - `params_lay.addWidget(self._tf_section)` 放在最上（替换原 `时频参数` 组的位置）；`幅值`/`坐标轴设置`/`色标`/`计算` 顺序不变。
  - 摘要：`_refresh_tf_summary()` 读 `combo_nfft/combo_win/spin_overlap` → `self._tf_section.set_summary(...)`；连 `combo_nfft.currentTextChanged`、`combo_win.currentTextChanged`、`spin_overlap.valueChanged`。
  - 高亮：新增 `_on_preset_param_changed()`，若**非** `self._applying_preset` 则 `self.preset_bar.set_recommended(None)`，然后刷新摘要。清高亮信号覆盖合并 body 里的可保存主参数：`combo_nfft`、`combo_win`、`spin_overlap`、`chk_remove_mean`；其中只有前三项影响摘要文本。
  - guard：`_apply_preset` 入口 `self._applying_preset = True`，`finally` 复位；末尾 `_refresh_tf_summary()`。
  - 预设加载高亮：在 `PresetBar._load(slot)` 成功调用 `_apply(params)` 后调用 `self.set_recommended(slot)`；失败时不改推荐状态。
  - 暴露 `is_tf_expanded()` 便于测试/外部。
- [x] **Step 3：跑测试**

---

### Task 3：FFT 接入（`FFTContextual`，~1984）

**Files:** `mf4_analyzer/ui/inspector_sections.py`（`谱参数` ~2053–2119；`预设配置` ~2144–2154），`tests/ui/test_side_panel_widgets.py`

- [x] 新建 `self._fft_section = _CollapsibleParamSection("谱参数", "inspector/fft/params_expanded")`，把原 `谱参数` `QGroupBox` 标题清空后放入 body，并把 `self.preset_bar` 放入常驻区。`params_lay` 顺序保持为合并段 → `坐标轴设置` → `计算 FFT`。
- [x] 摘要 = `combo_nfft.currentText() · combo_win.currentText() · f"{spin_overlap.value()}%"`（`combo_nfft` 含 `自动`）。`谱参数` 组里除三项外还有 平均模式/重叠率/幅值轴——这些**留在 body 内**随展开显示，只是不进摘要。
- [x] 写对应四测（合并/折叠/摘要、手动改清高亮、apply 保持高亮、preset load 设置高亮）+ 实现 + 跑测试。手动清高亮覆盖 `combo_win`、`combo_nfft`、`spin_overlap`、`combo_avg_mode`、`spin_avg_overlap`、`combo_amp_y`。暴露 `is_fft_params_expanded()`。

---

### Task 4：Order 接入（`OrderContextual`，~2439）

**Files:** `mf4_analyzer/ui/inspector_sections.py`（`谱参数` ~2493–2532；`预设配置` ~2569–2578），`tests/ui/test_side_panel_widgets.py`

- [x] 新建 `self._order_section = _CollapsibleParamSection("谱参数", "inspector/order/params_expanded")`，把原 `谱参数` `QGroupBox` 标题清空后放入 body，并把 `self.preset_bar` 放入常驻区。`params_lay` 顺序保持为合并段 → `坐标轴设置` → `时间-阶次`。
- [x] 摘要 = `f"≤{spin_mo.value()}阶" · f"{spin_order_res.value():g}" · combo_nfft.currentText()`，例 `"≤20阶 · 0.1 · 2048"`。摘要联动信号：`spin_mo.valueChanged`、`spin_order_res.valueChanged`、`combo_nfft.currentTextChanged`。
- [x] 写对应四测（合并/折叠/摘要、手动改清高亮、apply 保持高亮、preset load 设置高亮）+ 实现 + 跑测试。手动清高亮覆盖 `spin_mo`、`spin_order_res`、`spin_time_res`、`combo_nfft`、`spin_samples_per_rev`。暴露 `is_order_params_expanded()`。

---

### Task 5：清理既有测试 + 全量回归

**Files:** `tests/ui/test_side_panel_widgets.py`、`tests/ui/test_inspector*.py`、其它

- [x] 全仓搜既有断言并更新：`rg -n "预设配置|预设|preset_bar|inspectorCollapser" tests/`。重点核对是否有测试断言「预设组在底部/是独立 group」「主参数组常驻展开」——按新结构改。
- [x] 保住 A1 标签列对齐契约：`test_fft_contextual_fields_fill_column_under_qss` 等仍通过（迁移控件时调用既有 `_enforce_label_widths`/统一列宽的逻辑不要漏）。
- [x] 确认 `main_window` 读参数控件、project 存取、`_collect_preset`/`_apply_preset` 不回归（这些控件仍存在、仅折叠隐藏）。
- [x] 跑相关用例：
      `… -m pytest tests/ui/test_side_panel_widgets.py tests/ui/test_inspector.py tests/ui/test_analyzer_opens_cockpit.py -q --basetemp=.pytmp/run`
- [x] 视觉自查：对照 `tf-params-merged-section.html`（折叠态/展开态各一）。
- [x] 更新本 plan 勾选；如需可在 mockup 旁留一句"已实现"。

---

### 风险 / 注意

- **A1 列宽契约**：主参数组迁进 body 后，QFormLayout 的标签列宽对齐逻辑要继续生效，否则 sig_card 与参数列右边缘会错位。
- **apply guard 漏包**：若 `_apply_preset` 里有提前 return 分支，guard 的 `finally` 复位务必覆盖，避免标志卡死。
- **持久化 store 一致**：折叠状态与 PresetBar/PersistentTop 折叠条同用 `_preset_settings()`，key 命名空间用 `inspector/{kind}/params_expanded` 避免冲突。
- **三个 section 各自独立**：各自的折叠状态、摘要、高亮互不影响（独立 key、独立 section 实例）。
