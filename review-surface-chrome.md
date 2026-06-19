# Review 报告:surface 分层收尾两个 UI 全局改动

- **Review 对象**:`8ed8e4d` + `b824579`(当前 HEAD)
- **分支**:`feat/surface-snow-redesign`
- **日期**:2026-06-20
- **验证手段**:完整 diff 走读 + 四态真机截图(`docs/surface-redesign-after/*.png`)+ 实跑测试(`.venv`,offscreen)

> 注:`b824579` 是会话开始之后才提交的,初始 git 快照里只到 `8ed8e4d`。它是顺着"`WA_*` 属性成对出现"的线索查出来的——blame 确认 `WA_TranslucentBackground` 正是 `b824579` 加在 `8ed8e4d` 的 `WA_StyledBackground` 下一行。

---

## 一句话结论

**成果合理、视觉目标达成、测试全绿、无功能性 bug。** 值得清理的是 **Toolbar 一处背景被画了两遍**(冗余/维护陷阱),以及**圆角测试缺一条"中心不透明"断言**(挡不住白底丢失回归)。两者都属健壮性/可维护性,不影响当前运行。

---

## 一、两个 commit 做了什么

| commit | 范围 | 内容 |
|---|---|---|
| **8ed8e4d** (21:36) | 3 文件 | 给 `FileNavigator` / `ChartStack` / `Inspector` / `fileArea` 加 `Qt.WA_StyledBackground`,让 QSS 的 `background:#fff; border-radius` 真正绘制(Qt 经典坑:纯 `QWidget` 子类用 type selector 设背景必须开这个属性);外边距 `8→5` |
| **b824579** (23:56, HEAD) | 22 文件 | 大手术:① 三面板及其**所有子 widget**叠加 `WA_TranslucentBackground + WA_NoSystemBackground + autoFillBackground(False)`;② `Toolbar` 改为自绘圆角 `paintEvent` + 固定 50px + objectName `surfaceTopBar`;③ `StatusBar` 改成塞进 central layout 的 `SurfaceStatusBar` 子类(不再用 `QMainWindow` 原生 status bar);④ 托盘色 `#e8ecf2 → #f2f4f7`;⑤ panel 圆角 `10→7`、card 圆角 `12→6`;⑥ 新增 `tests/ui/test_surface_layering.py`(206 行,7 个用例) |

代码改动只占少数;`b824579` 的 3618 行里绝大部分是文档、HTML mockup 和 4 张 PNG 截图。

---

## 二、实际成果:合理 ✅

四态截图(time / fft / fft_time / order)逐一核对:

- 三栏白卡 + 顶部白圆角 toolbar + 底部白圆角状态栏,正确浮在浅灰托盘(`#f2f4f7`)上,圆角清晰、面板间 3px 缝隙透出托盘色;
- **白底没有因为 `WA_TranslucentBackground` 丢失**——这是本次最该担心的点,截图证明渲染路径产出正确;
- 四态均无错位 / 截断 / 回归;
- 新增 7 个测试 + 改写的 `test_time_controls_spacer_has_toolbar_background_rule`,**实跑 `7 passed`**。

设计目标(白卡浮于灰托盘的 surface 分层)达成。

---

## 三、逻辑问题(无功能性 bug,但有以下三档)

### 🔴 1. Toolbar 背景画了两遍 —— 主要发现

- `style.qss:301-302` 已经有:
  ```css
  Toolbar#surfaceTopBar, QWidget#surfaceTopBar {
      background:#fff; border:1px solid #dbe2eb; border-radius:8px;
  }
  ```
- `toolbar.py:221` 又新增 `paintEvent`,`toolbar.py:226` 用 `QPainter.drawRoundedRect(rect.adjusted(0,0,-1,-1), 8, 8)` 画**完全相同**的白底 + `#dbe2eb` 描边,末尾再 `super().paintEvent()`。因为 `WA_StyledBackground=True`,`super().paintEvent()` 会**再触发一次** QSS 背景绘制。

**同一层背景被画两遍**,且参数分散在两处(QSS 与 Python),以后改圆角/描边只动一处就会两边不一致。

**反证**(说明 `paintEvent` 多余):底部 `SurfaceStatusBar` 与三个面板的属性组合**完全相同**(`WA_TranslucentBackground + WA_StyledBackground`),都**没有** `paintEvent`,截图里白圆角照样正常。可见 QSS 自己就能画出白圆角,toolbar 的自绘是冗余的。

> 唯一可能的动机是自绘 `Antialiasing` 圆角更平滑;但那样 toolbar 圆角质量就和面板/状态栏的 QSS 圆角不一致了,反而更应统一。

**建议**:删 `toolbar.py` 的 `paintEvent`,统一走 QSS(二选一,别并存)。

### 🟡 2. `WA_TranslucentBackground` 散弹枪式铺设,缺覆盖验证

`b824579` 给 stack 的 `stack / _time_page / _time_split / _time_bottom_dock / page_fft…`、navigator 的 `_file_holder / scroll / viewport`、inspector 的 `host / scroll / viewport` 等**一大批子 widget**逐个手设透明三件套。这是"全透明 + 让特定层 QSS 画白"的打法:**只要漏设一个匹配全局 `QWidget { background:#fff }` 的子 widget,就会冒白块**。

当前四态截图没露馅,但**加载文件后 / 各种弹层 / 菜单浮层的状态没有截图覆盖**。属于"未充分验证",非已知 bug——后续若出现局部白块,优先查这里漏设属性的子 widget。

### 🟡 3. 圆角测试盲点:只验角透明,不验中心不透明

`test_surface_layering.py:112` 的 `_corner_alphas` 只取四角像素,`:204` 断言 `max(alphas) < 12`。

**如果哪天 `WA_TranslucentBackground` 真把面板白底吃成全透明,四角依然透明、测试照样过**,但面板会整块消失。这条单测挡不住"白底丢失"回归——现在是靠人工看截图兜的。

**建议**:补一条「中心像素 `alpha≈255` 且接近 `#fff`」的断言,让自动化能真正守住白底。(正是仓库 memory 里"别凭属性设上 + 单测过就说修好"那条教训的形态。)

### ⚪ 小问题

- `test_surface_layering.py:140` 把版本号硬编码成 `assert btn.text() == "v7.0"`,**下次升版本测试会 fail**——应读 `app_meta` 而非写死。
- 托盘色 `#e8ecf2 → #f2f4f7` 是全局替换,已被 `assert "#e8ecf2" not in qss` 锁死,确认替换彻底,无残留。
- `StatusBar` 从 `setStatusBar()` 改为 `root.addWidget()`:`self.statusBar` 属性覆盖 `QMainWindow.statusBar()` 方法的模式是**既有**写法(改动前就是 `self.statusBar = QStatusBar()`),非本次引入,无新增风险;测试已验证 `findChildren(QStatusBar).count == 1`,无重复状态栏。

---

## 四、总评与建议

| 维度 | 结论 |
|---|---|
| 实际成果 | ✅ 合理,视觉达成(四态截图为证) |
| 功能性 bug | ✅ 无 |
| 测试 | ✅ 7 passed;但圆角用例有盲点 |
| 待清理 | 🔴 Toolbar 双重绘制背景;🟡 圆角测试补中心断言;⚪ 版本号别写死 |

**可选后续(均为健壮性/可维护性,不影响运行)**:
1. 删 `toolbar.py:221` 的 `paintEvent`,统一用 QSS 画 toolbar 背景;
2. 给 `test_surface_top_bottom_and_panels_render_rounded_corners` 补"中心不透明"断言;
3. `v7.0` 改读 `app_meta`;
4. 补一张"加载文件后"的截图,验证散弹枪式透明属性没漏子 widget。
