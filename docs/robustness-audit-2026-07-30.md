# TraceLab 全局鲁棒性审计

**修订 2026-07-30 (rev2，codex 复核后)：** 第一版被 codex 判定
`needs revision` —— 风险方向基本正确，但执行结论需要修订。本版做了五件事：
① 补上固定基线（commit SHA + 依赖版本 + 测量命令）；
② 把「静默 except」按**捕获宽度**拆开统计（这一步推翻了 Inspector / 批处理
两个 feature 的评级）；
③ 修正三个不可复现或已漂移的数字（批处理体量、真实渲染验证数、canvas 状态字段数）；
④ 把两个**已端到端复现**的正确性 bug 提到 P0，把两个静态推断降级；
⑤ 撤掉 P0「296 处统一加 logger.debug」和「12 View 文档不一致」（后者是误报）。
逐条核对见 §12。

---

## 0. 基线（本报告所有数字的测量条件）

| 项 | 值 |
|---|---|
| **commit** | `b5d7956eb8c80c7981d174ed92575e876d171c2b`（`main`，2026-07-30 18:01:45 +0800） |
| 工作树 | 干净，除本报告 + `.playwright-cli/` 临时文件为未跟踪 |
| 测量时间 | 2026-07-30 |
| Python | 3.12.13（`.venv/bin/python`；系统 `python3` 是 3.14.6 且**无 PyQt5**，跑不了任何运行时探针） |
| Qt / PyQt5 | 5.15.14 / 5.15.11 |
| numpy / scipy / pyqtgraph | 2.5.1 / 1.18.0 / 0.14.0 |
| asammdf / pytest / pytest-qt | 8.8.22 / 9.1.1 / 4.5.0 |
| 平台 | macOS 27.0 (26A5388g)，arm64 |
| 运行探针的方式 | `QT_QPA_PLATFORM=offscreen PYTHONPATH=<repo> .venv/bin/python …` |

**范围：** `mf4_analyzer/` 全部 88,054 行 —— 绘图、坐标、显示、View 状态机、
各类 mixin、导入层、数值算法、采集、测试护栏。
**性质：** 只读审计，未修改任何 `.py`。所有结论均以可复现的命令为证据（附录 A）。

> **数字会漂移。** rev1 没记 SHA，重跑时批处理体量已经和报告不一致。本版所有
> 表格都是在上面这个 SHA 上重新测的；后续任何引用请连 SHA 一起引。

---

## 1. 一句话结论

**不稳定不是分散的，它高度集中在一层：`ui/`，而且集中在 `ui/pg_canvas` 里。**

`signal/`（数值算法）、`io/`（导入）、`view_state.py`（View 模型）、
`acquisition_capture/`（采集内核）这四块的工程质量是**扎实**的 —— 有明确的
数据契约、异常向上传播、覆盖良好。问题全部出在它们之上的 UI 编排层。

"改一处就牵扯很多东西"不是错觉，它有四个可量化的机制性原因：

| # | 根因 | 一句话 | 证据强度 | 证据 |
|---|---|---|---|---|
| **R1** | **静默失败** | `ui/pg_canvas` 有 **288 处宽泛 `except Exception: pass`**，且全进程**没有** `sys.excepthook`、没有 Qt 消息处理器、`ui/` 里几乎没有 logging | 静态事实 + 已复现 2 个下游 bug | §3 |
| **R2** | **分解是名义上的** | `_CanvasBackref` 让 5 个「协作者」对象的 `self.X = ...` **静默写穿透**到 canvas 上；它们共享一个全局可变命名空间 | 已用脚本枚举复现 | §4 |
| **R3** | **无主的共享标志位** | `canvas._refresh` 被 6 个文件写 19 次、**从未被读**；`_channel_render_profiles` 有 5 个读点、3 个惰性创建点、无初始化、无清理 | 已复现 | §5 |
| **R4** | **测试与实现强耦合** | 1,232 处私有属性断言 + 894 处对内部的 monkeypatch，对真实渲染的验证只有 **47** 处 | 只是结构指标，**因果未证明** | §6 |

R1 让你**看不见**问题；R2+R3 让问题**扩散**；R4 **可能**让重构代价变高。

> **R4 的降级说明。** rev1 把 R4 写成「测试锁死实现细节 → 所以不敢拆
> `canvas.py`」。这个因果链**没有证据支撑**：1,232 处私有属性断言里，有多少
> 是性能状态机不变量、缓存键契约、绘图内部不变量（这些**本该**白盒测），
> 目前没人数过。在抽样分类之前，R4 只能作为「值得调查的结构指标」，
> 不能作为「先补契约测试才能重构」的论据。见 §6 和 W4。

---

## 2. 量化基线

### 2.1 各子系统体量与静默吞异常密度

**关键修正（rev2）：** rev1 只统计「静默 `pass`」总数，把
`except (TypeError, ValueError): pass`（一个有意的窄类型转换守卫）和
`except Exception: pass`（吞掉一切，包括 `RuntimeError` / `KeyError` /
逻辑 bug）算成同一件事。按捕获宽度拆开后，结论变了：

| 子系统 | LOC | except 处理器 | 静默 `pass` | 静默率 | **其中宽泛 `except Exception`** | **宽泛静默率** |
|---|---:|---:|---:|---:|---:|---:|
| **`ui/pg_canvas`（绘图·坐标）** | **16,914** | **522** | **296** | 57% | **288** | **55%** |
| `ui/inspector_sections`（右栏） | 5,206 | 48 | 37 | 77% | **3** | **6%** |
| `ui/drawers/batch`（批处理） | **4,895** | **26** | 12 | 46% | **2** | **8%** |
| `ui/main_window`（mixin·路由） | 8,705 | 52 | 6 | 12% | 待测 | — |
| `ui/widgets`（通道树·配置） | 3,881 | 14 | 2 | 14% | 待测 | — |
| `ui/chart_stack`（卡片·分屏） | 3,702 | 23 | 3 | 13% | 待测 | — |
| `ui/markup`（标注编辑） | 2,122 | 1 | 1 | 100% | 待测 | — |
| `ui_kit`（基础控件） | 1,711 | 10 | 2 | 20% | 待测 | — |
| `acquisition_ui` | 11,187 | 41 | 6 | 15% | 待测 | — |
| `acquisition_capture` | 5,734 | 72 | 6 | **8%** | 待测 | — |
| `io` | 3,477 | 49 | 6 | **12%** | 待测 | — |
| `signal` | 2,179 | 1 | 0 | **0%** | 0 | **0%** |
| `ui/` 合计 | 56,326 | 752 | 379 | 50% | — | — |

按捕获类型的完整分解（附录 A-1b 可复现）：

```
ui/pg_canvas          (296 静默)   288 × except Exception
                                     7 × except (RuntimeError, TypeError)
                                     1 × except ValueError
ui/inspector_sections  (37 静默)    27 × except (TypeError, ValueError)
                                     4 × except ValueError
                                     3 × except TypeError
                                     3 × except Exception      ← 只有 3 处是宽泛的
ui/drawers/batch       (12 静默)    10 × except (TypeError, ValueError)
                                     2 × except Exception
```

**这直接推翻 rev1 §7 里对 Inspector 的评级。** Inspector 的 34/37 是
`except (TypeError, ValueError): pass`，绝大多数是兼容旧 preset 的数值转换路径，
带 docstring 说明的有意行为，例如：

```python
# ui/inspector_sections/_helpers.py:168  apply_db_reference_partial
if 'db_reference' in d:
    try:
        control.editor.setValue(float(d['db_reference']))
    except (TypeError, ValueError):     # 旧 preset 里的非数值 → 保持当前值
        pass
```

这和 `pg_canvas` 里 288 处「吞掉一切」的风险**不是一个量级**。
`ui/pg_canvas` 平均**每 32 行一个 except 处理器，其中 55% 吞掉一切**。

单文件 top 5（静默 `except: pass` 计数）：

```
canvas.py           65
line_canvas.py      60
overlay_axes.py     48
heatmap_canvas.py   40
context_menu.py     23
                   ---
                   236   = ui/ 全部 379 处的 62%
```

**这 5 个文件正是"坐标更新 / 绘图更新"问题的所在地。**

### 2.2 其他全局指标

| 指标 | 数值 | 解读 |
|---|---:|---|
| `.connect(` / `.disconnect(` | 669 / 21 | **只是结构指标**，见下 |
| 只 connect 从不 disconnect 的函数 | 88 个（含 314 处 connect） | 同上 |
| `pyqtSignal` 声明 / `.emit(` | 185 / 286 | 事件流复杂度 |
| `blockSignals` | 165 | 靠临时静音而非结构隔离 |
| `getattr(self, ...)` / `hasattr(self, ...)` | 208 / 49 | 防御性访问 = 隐式契约的代价 |
| `QTimer` / `singleShot` | 42 | 延迟执行 → 时序耦合 |
| `sys.excepthook` / `qInstallMessageHandler` | **0 / 0** | 无全局兜底（已 grep 确认，含 `tools/`、`scripts/`） |
| `logging.getLogger` 所在文件 | 12 个（`ui/` 仅 `line_canvas.py` + `renderer.py`） | 无诊断轨迹 |
| 裸 `except:` | 3 | 这个反而很干净 |
| 测试函数总数 | 3,714 | CLAUDE.md 写的是 164，**文档过期 22 倍** |
| lessons-learned 条目 | 279（`pyqt-ui/` 独占 74） | 教训分布本身就指向 UI 层 |
| `canvas.py` | 4,042 LOC / 158 方法 / `__init__` 74 处 `self.X=` | 单类体量 |

> **`connect:disconnect = 32:1` 不能证明有重复连接。** QObject 析构会自动断开
> 以它为 sender/receiver 的连接，绝大多数 UI 连接的生命周期等于 widget 生命周期，
> 本来就不需要显式 disconnect。这个比例只说明「连接生命周期没有被显式管理」，
> 是**审查成本**指标，不是**缺陷**指标。真要证明重复连接，得测同一 sender/signal/slot
> 三元组的连接计数（未做）。§9 里已按此降级。

---

## 3. R1 —— 静默失败：你根本看不见东西坏了

### 现象

```python
# ui/pg_canvas/canvas.py:2029  restore_visible_ylims —— 坐标恢复的核心路径
for name, ylim in (ylims or {}).items():
    pair = view_state_lines.get(name) or legacy_lines.get(name)
    if pair is None:
        continue
    try:
        pair[0].set_ylim(*ylim)
        if name in view_state_lines:
            restored_keys.add(name)
        changed = True
    except Exception:          # ← 任何失败：静默跳过
        continue
if restored_keys and len(restored_keys) < len(view_state_lines):
    # ↓ 没恢复成功的通道，走「新通道自动 fit」分支
    ...  _fit_channel_y_to_visible_x(...)
```

**这段代码的行为契约是：**"恢复失败 = 当作新通道处理，自动 fit"。
用户看到的是「我保存的 Y 轴范围没了，自己跳到别的范围」。
日志里没有任何记录。开发者只能靠猜。

**而且这条 fallback 分支本身就有一个已复现的正确性 bug** —— 见 §9.2。
这是 R1 的最好例证：静默降级路径上藏着真 bug，没人发现，因为它不报错。

这个「宽泛 + 静默」的模式在 `ui/pg_canvas` 里出现 **288** 次。

### 为什么这会让「改一处牵扯很多」

改动 A 在 B 处引发一个异常 → 被吞掉 → B 静默降级 → C 依赖 B 的结果 →
C 表现异常 → 你去查 C，但根因在 A。**因果链被 `except Exception: pass` 切断了。**

### 缺失的兜底

全进程没有 `sys.excepthook`，没有 `qInstallMessageHandler`。PyQt5 下未捕获的
槽函数异常会打到 stderr，且 **PyQt 5.5+ 起默认调用 `abort()`**（PyQt 维护者
Phil Thompson 在 riverbank 邮件列表确认过这个行为变更）。
`mf4_analyzer/app.py` 的 `main()`（第 64 行）**只做 HiDPI + 字体 + 样式**，
没有任何日志或异常配置：

```python
def main():
    _configure_high_dpi()
    ...
    window = MainWindow(); window.show()
    sys.exit(app.exec_())          # ← 没有 excepthook，没有 logging.basicConfig
```

打包后 stderr 不可见 —— 等于用户端崩溃/异常**零可观测性**。
`ui/` 56,326 行里只有 `line_canvas.py` 和 `renderer.py` 两个文件碰了 logging。

**打包目标只有 Windows。** `tools/` 下唯一的打包脚本是
`build_windows_folder.ps1`，默认走 `--windowed`（第 272 行），即 GUI 子系统、
无控制台。没有 macOS 打包脚本。所以**任何只落 macOS 路径的日志方案对实际
交付物无效** —— rev1 的 `~/Library/Application Support/TraceLab/logs/` 建议
在这一点上是错的。

### 建议（修正版）

1. **装跨平台的全局兜底**（W2）：`sys.excepthook` + `threading.excepthook` +
   `qInstallMessageHandler`，落盘到平台正确的目录（Windows
   `%LOCALAPPDATA%\TraceLab\logs`、macOS `~/Library/Logs/TraceLab`、
   Linux `$XDG_STATE_HOME`），**带轮转 + 大小上限 + 保留期 + 级别开关**。
   UI 上出 toast。
2. **~~给 296 处统一加 `logger.debug`~~ —— 撤销。** 理由见 §12-3：这些位置
   大量落在 pan/zoom、绘制、光标热路径上；一旦某个异常**持续**发生，无限频的
   debug 日志会造成日志风暴、磁盘增长和新的卡顿 —— 用一个可观测性措施制造
   一个性能故障。**改为：** 先有轮转 + 限频（同一 `(文件, 行号, 异常类型)`
   在时间窗内只记一次 + 计数聚合）基础设施，再挑 **5–10 条**高价值的
   状态/坐标路径接上（W2 第二步）。剩下的 280 处等日志里出现真实信号再动。
3. **给 `except Exception: pass` 分类，而不是全部消灭**。三类：
   - **真·可忽略**（Qt C++ 对象已销毁、样式设置失败）→ 收窄成
     `except (RuntimeError, AttributeError): pass` + 一行注释说明为何可忽略。
     `pg_canvas` 里已有 7 处 `except (RuntimeError, TypeError): pass` 是这个
     写法的正面样板。
   - **降级路径**（本条通道渲染失败，其他继续）→ 必须限频记录通道名 + 异常。
   - **不该发生**（坐标恢复、状态同步）→ `logger.exception` 并向上报，
     debug 构建下直接抛。
4. **加一条 lint 规则**：新增的 `except Exception: pass` 必须带
   `# noqa: silent-ok — <理由>`。存量豁免，增量卡死。**先止血。**

---

## 4. R2 —— `_CanvasBackref`：分解是名义上的

### 机制

`ui/pg_canvas/_backref.py`（47 行）是整个绘图子系统的架构核心，也是最大的隐患：

```python
class _CanvasBackref:
    def __getattr__(self, name):
        return getattr(self._c, name)              # 读：落空就去 canvas 拿

    def __setattr__(self, name, value):
        if name in owned_names or name in delegate_names:
            object.__setattr__(self, name, value)
            return
        setattr(self._c, name, value)              # 写：没声明就写到 canvas 上
```

`Renderer` / `OverlayAxisManager` / `CursorController` / `QualityManager` /
`AnnotationManager` / `TickDensityController` 全部继承它。

**后果：这 6 个类和 `TimeDomainCanvasPG` 共享同一个可变命名空间。**
文件被拆开了，耦合一点没减。更糟的是耦合现在**不可见**了 —— 你在
`renderer.py` 里看到 `self._display_x_coverage = ...`，它实际改的是
`canvas._display_x_coverage`，而 `dense_raster.py` 和 `quality.py` 都在读它。

### 实测的写穿透清单

附录 A-8 的脚本输出（本 SHA 上重新跑过，与 rev1 一致）：

| 协作者 | 声明的名字数 | `self.X = ...` 实际写到 canvas 上的属性 |
|---|---:|---|
| `Renderer` | 10 | `_channel_render_profiles`, `_display_x_coverage`, `_display_x_coverage_by_channel`, `_last_refresh_signature`, `_refresh`, `_refresh_pending`, `_y_overflow_wall_active` |
| `OverlayAxisManager` | 60 | `_channel_render_profiles`, `_refresh` |
| `CursorController` | 38 | `_refresh` |
| `TickDensityController` | 14 | `_refresh` |
| `AnnotationManager` | 19 | `_artist`, `_last_rclick_scene_pos` |
| `QualityManager` | 15 | （无） |

`AnnotationManager.__init__` 里的 `self._artist = RemarkArtist()`（annotations.py:53）
值得单独说：`_owned_names` 只有 `{enabled, remarks, press_pos, press_dragged}`，
**`_artist` 不在其中**，所以这个对象被写到了 **canvas** 上。之后
`self._artist` 的读取路径是：`__getattribute__` 找不到 → `AttributeError`
→ `__getattr__` → `getattr(canvas, '_artist')`。**它是靠两跳 fallback 意外
生效的。** 已确认 `canvas.py` 自己完全不用 `_artist` 这个名字（同族的
`line_canvas.py` / `heatmap_canvas.py` 用的是 `_remark_artist`），
所以当前没冲突 —— 但哪天 canvas 需要一个 `_artist`，标注功能会在毫无提示的
情况下坏掉。

### 另一个方向的坑：静默方法遮蔽

`__getattribute__` 对 `_delegate_names` 里的名字，会**优先**返回
`canvas.__dict__` 里的同名条目。这是为测试 monkeypatch 留的缝
（`canvas._refresh_visible_data = fake`），但它同时意味着：
**任何在 canvas 实例上创建的同名属性，会静默替换掉协作者的方法。**

运行时实测（`QT_QPA_PLATFORM=offscreen` 下真实实例化 `TimeDomainCanvasPG`）：

```
declared owned/delegate names total:               156
names that are NOT methods on TimeDomainCanvasPG:  106
names colliding with canvas.__init__ instance attrs: 0
canvas.__init__ instance attr count:                75      (rev1 写 74；74 是
                                                             静态 self.X= 赋值数，
                                                             运行时实例属性是 75)
```

**目前实测 0 冲突** —— 但这是运气，不是设计保障，且没有任何测试守着它。

### 建议

- **W3 · 加不变量测试（1 天，零风险）**：断言
  ① 每个协作者的 `_delegate_names ∩ canvas 实例属性集 == ∅`；
  ② 每个协作者方法里赋值的 `self.X`，要么在 `_owned_names`，要么在一份
  **显式的 `_writes_through` 白名单**里。
  → 从此写穿透必须是**主动声明**的，而不是默认行为。
  附录 A-8 的脚本可以直接改造成这个测试。
- **P2 · 收口 `__setattr__`**：白名单之外的写入直接 `AttributeError`。
  这一步会把 §5 的无主标志位全部逼出来。
- **W3 · 让 `AnnotationManager._artist` 归位**：加进 `_owned_names`。

---

## 5. R3 —— 无主的共享标志位

### 5.1 `canvas._refresh`：写 19 次，读 0 次

```
mf4_analyzer/ui/main_window/window.py:2022     self.canvas_time._refresh = True
mf4_analyzer/ui/pg_canvas/canvas.py            × 5   (385, 1000, 2247, 2299, 2499)
mf4_analyzer/ui/pg_canvas/overlay_axes.py      × 8
mf4_analyzer/ui/pg_canvas/cursor.py            × 2
mf4_analyzer/ui/pg_canvas/renderer.py          × 1
mf4_analyzer/ui/pg_canvas/tick_density.py      × 2
                                              ────
                                               19 处写
```

**读取处：0。** 全仓库（含 `getattr(x, "_refresh")` / `"_refresh"` 字符串形式）
搜不到任何读取。唯一引用它的是一个测试：

```python
# tests/ui/test_pg_timedomain_canvas.py:1533
canvas._refresh = False
... assert canvas._refresh is True
```

删除安全性已额外核过三件事：
- 全仓库**没有** `def _refresh(` —— 不存在「赋 True 把一个方法遮蔽掉」的情况；
- `TimeDomainCanvasPG` 类上没有 `_refresh`（只有实例属性），
  Qt / pyqtgraph 基类也没有这个名字；
- 相邻名字 `_refresh_pending` / `_refresh_timer` / `_refresh_visible_data` /
  `_refresh_overlay_axis_labels` 都是**活的**，删除时不能连带误伤。

即：**一个纯粹的死标志位，6 个模块在维护它，一个测试在保护它不被删除。**
每个写新渲染路径的人都会照抄这行，因为它看起来像是必须的。

这是整个仓库状态管理问题的完美缩影，也是**最容易拿下的第一个胜利**：
删掉 19 处写 + 1 个测试断言，行为零变化。

### 5.2 `_channel_render_profiles`：小型无界缓存 + 生命周期缺陷

| 文件 | 行为 |
|---|---|
| `renderer.py:527-530` | `getattr(...)` → `None` 就现场创建 |
| `overlay_axes.py:315-318` | 同上 |
| `overlay_axes.py:425-428` | 同上 |
| `dense_raster.py:241/403/435` | 读（`getattr(self.canvas, ..., {})`） |
| `quality.py:88/300` | 读 |

- `canvas.__init__` 里**没有**它。
- `clear()` / `full_reset()` 里**没有**它。
- 全仓库**没有任何**重置/清理点（`grep` 验证）。

**定性修正（rev2）：** rev1 写的是「泄漏」。实测每个条目存的是
`RenderProfile`（`render_profile.py:23`，`@dataclass(frozen=True)`，9 个字段
全是标量 / 3 元 float 元组），**不持有原始数组**：

```
fields: source_revision, source_length, finite_count, monotonic_time,
        approx_unique_count, transition_fraction,
        normalized_step_quantiles, discrete_small_domain, strategy
holds ndarray? False
approx bytes/entry: 380     →  10,000 条陈旧条目 ≈ 3.6 MiB
```

所以准确定性是：**小型无界缓存 + 生命周期缺陷**，不是严重内存泄漏。
`source_revision` 逐条失效机制也在兜底，所以也不是正确性 bug。

真正的代价是**认知成本**：任何人想改渲染策略的分类逻辑，得同时想明白 5 个
读点 + 3 个惰性创建点 —— 而 IDE 帮不了他，因为访问全是
`getattr(canvas, "...", {})` 字符串。

### 5.3 `clear()` 是手写重置

`canvas.__init__` 有 74 处 `self.X =` 赋值（运行时实例属性 75 个）；
`clear()` 手工重置其中 38 个，`full_reset()` 再补 2 个。
**没有任何测试断言这两者的对应关系。**

新增一个 `__init__` 字段而忘了在 `clear()` 里镜像 → 陈旧状态跨重建泄漏 →
表现为「切换文件后图还带着上一个文件的某些属性」。这类 bug 症状飘忽、
复现困难，而且**审阅 diff 时看不出来**（你只加了一行 `__init__`）。

> 说明：我逐项核过那 36 个"未在 `clear()` 中重置"的属性，其中大部分是常量、
> 协作者对象，或通过 `_teardown_*()` / `.clear()` 方法间接清理的（AST 扫不到）。
> **真正无主的只有 `_channel_render_profiles` 一个。** 所以这一条是
> **流程风险**（下次新增字段没人挡）而非当下的存量 bug。

### 建议

- **W3 · 删掉 `canvas._refresh`**（19 处写 + 1 个测试断言）。零行为变化，
  立刻给团队一个"死状态是可以删的"的信号。
- **W3 · `_channel_render_profiles` 认领主人**：在 `__init__` 里显式初始化，
  在 `clear()` 里清空，把 8 个 `getattr` 触点改成直接属性访问。
- **P2 · 加 `clear()` 对称性测试**：
  ```python
  def test_clear_resets_all_mutable_init_state():
      c = TimeDomainCanvasPG(); plot_something(c)
      before = snapshot_mutable_attrs(c)   # 排除白名单：常量、协作者、QWidget
      c.clear()
      assert snapshot_mutable_attrs(c) == pristine_snapshot
  ```
  白名单显式化，新增字段默认进入检查。**这一条测试能挡住未来一整类 bug。**
  排在 W3 之后 —— 它需要先把 `_channel_render_profiles` 的生命周期定下来，
  否则白名单要为一个已知缺陷开口子。

---

## 6. R4 —— 测试与实现强耦合（结构指标，因果未证明）

附录 A-6 的命令在本 SHA 上重跑，**逐字复现**：

| 测试风格 | rev1 | rev2 实测 |
|---|---:|---:|
| 私有属性断言（`assert obj._x ...`） | 1,232 | **1,232** ✅ |
| 对内部的 `monkeypatch.setattr` / `canvas._x = ` | 894 | **894** ✅（拆开：860 + 34） |
| 真实渲染验证（`grab()` / `toImage()` / `pixelColor`） | ~92 | **47** ❌ |

**第三行 rev1 是错的。** 实测 `grab(` 10 行 + `toImage()` 16 行 +
`pixelColor` 30 行 = 56 行匹配，去重后 47 行。方向上这让差距**更大**
（1,232 : 47，不是 1,232 : 92），不是更小。

> codex 复核时报的是 `1,232 / 947 / 47`。中间那个 947 用附录 A-6 写的命令
> 复现不出来（`grep -rn ... | wc -l` 是数**行**，同一行同时命中
> `monkeypatch.setattr` 和 `canvas._x =` 只算一次，结果就是 894）。
> 947 大概来自 `rg --count-matches` 之类按**匹配数**计数的变体。
> 两边都记录在这里，命令即定义。

测试与源码的体量比：

| 源文件 | 源 LOC | 测试 LOC | 比 |
|---|---:|---:|---:|
| `pg_canvas/canvas.py` | 4,042 | 8,643 | 2.1× |
| `chart_stack/stack.py` | 1,306 | 2,973 | 2.3× |
| `pg_canvas/heatmap_canvas.py` | 2,984 | 3,762 | 1.3× |
| `view_state.py` | 303 | 110 | 0.4× |

### 这些数字支持什么、不支持什么

**支持：** ① 真实渲染验证覆盖确实薄（47 处 / 3,714 个测试函数）；
② `canvas.py` 的测试体量是源码 2.1×，任何改动的测试维护面确实大。

**不支持（rev1 越界的地方）：**

1. **「测试套件在惩罚清理行为」** —— 这是一个因果断言，但 1,232 处私有属性
   断言里，有多少是「本该白盒测」的东西（性能状态机、缓存键契约、
   envelope/dense-raster 内部不变量、`_CanvasBackref` 委派语义），
   没人数过。这个仓库的 lessons-learned 里有大量「属性设上了但渲染没变」的
   教训，其中一部分白盒断言正是**为了**锁住那些不变量而写的。
   **不能一律当成技术债。**
2. **「让契约测试成为重构时唯一必须绿的那一层」** —— 太强。性能状态机和缓存
   不变量做不到只用公开方法断言；把它们降级为「重构时可以红」会直接放开
   已经付过代价的回归面。
3. **「这直接解释了 `canvas.py` 为什么是 4,042 行」** —— 未验证的归因。
   同样可以由「增量开发 + 没有拆分预算」解释。

**因此 R4 的正确下一步不是「补契约测试」，而是「先分类」** —— 见 W4：
对 1,232 处断言做分层抽样（每层 ≥30 条）+ 覆盖率数据，把它们分成
「实现细节耦合 / 有意的白盒不变量 / 可迁移到行为级」三类，
再决定要不要建契约测试层和白盒标注规则。

`view_state.py` 是唯一的反例：0.4× 的测试比，因为它是纯数据模型，
**测行为不测实现**，所以少量测试就够了。这条观察仍然成立。

---

## 7. mixin 层审计（`ui/main_window`，8 个 mixin）

`MainWindow(DropImportMixin, AnalysisMixin, FFTMixin, OrderMixin, FFTTimeMixin,
ChannelScopeMixin, ProjectIOMixin, ViewMixin, QMainWindow)`

### 好消息：状态所有权是清楚的

| 文件 | 方法调用 | 数据读 | 数据写 | 读到 window 未拥有的属性 |
|---|---:|---:|---:|---:|
| `window.py` | — | 235 | **60** | — |
| `_project_io_mixin.py` | 48 | 14 | 7 | 0 |
| `_analysis_mixin.py` | 44 | 10 | 1 | 0 |
| `_order_mixin.py` | 27 | 8 | 1 | 0 |
| `_fft_time_mixin.py` | 25 | 10 | 1 | 1 |
| `_view_mixin.py` | 25 | 16 | 8 | 3 |
| `_fft_mixin.py` | 23 | 8 | 0 | 0 |
| `_channel_scope_mixin.py` | 19 | 6 | 2 | 1 |
| `_drop_import_mixin.py` | 12 | 2 | 1 | 2 |

**状态几乎全部由 `window.__init__` 拥有（60 个写），mixin 只写 0–8 个。**
跨文件共享写的属性只有 13 个，且大多是 `window` + 一个 mixin 的组合。

**这比 `pg_canvas` 的情况健康一个数量级。** mixin 拆分本身是合理的。

### 坏消息：调用图是有环的，没有分层

29 条跨文件调用边，其中双向环：

```
window  ⇄  _analysis_mixin      (22 出 / 7 回)
window  ⇄  _view_mixin          (10 出 / 6 回)
window  ⇄  _order_mixin         ( 4 出 / 5 回)
window  ⇄  _fft_time_mixin      ( 4 出 / 6 回)
window  ⇄  _project_io_mixin    ( 3 出 / 7 回)
window  ⇄  _channel_scope_mixin ( 3 出 / 3 回)
window  ⇄  _fft_mixin           ( 1 出 / 9 回)
```

且 `_analysis_mixin` 是事实上的 hub —— 被 `_fft` / `_fft_time` / `_order` /
`_view` / `_project_io` 5 个 mixin 调用。动它的任何方法，波及面是
`window` + 5 个 mixin。这就是"一改牵扯很多"在 mixin 层的具体形态。

### 具体隐患：guard 标志位跨文件，且靠 `getattr` 默认值兜底

`_restoring_project` 横跨 2 个文件、3 个角色（已复核）：

```
_channel_scope_mixin.py:29    self._restoring_project = False          ← 初始化
_project_io_mixin.py:1315-20  old = getattr(...); set True; finally 还原  ← 写（可重入）
_channel_scope_mixin.py:91    or getattr(self, "_restoring_project", False)  ← 读
```

写侧是 save/restore 形式，本身可重入 —— 这点做得对。风险在初始化侧：
第 29 行**无条件**写 `False`，所以若 `_init_channel_scope()` 在恢复过程中被
再调一次，guard 会被**清零**，`_on_source_load_finished` 就会在恢复项目时
错误地自动挂载文件。

同类且更糟的是 `_applying_view`：**全仓库没有任何初始化点**，
`window.py:1525` 和 `_view_mixin.py:115/135/277` 全靠
`getattr(self, '_applying_view', False)` 读。拼错属性名不会报错，
只会**静默退化成"没有 guard"**。
（对比：`_applying_analysis_view` 在 `window.py:257` 有显式初始化，是正面样板。）

### 建议

- **P2 · 给 mixin 加显式协议**。用一个 `MainWindowProtocol`
  （`typing.Protocol`）声明所有 mixin 依赖的属性和方法，每个 mixin 标注
  `self: MainWindowProtocol`。mypy 能查出：谁读了不存在的属性、
  拼错的 guard 名、改签名后漏掉的调用点。**零运行时成本，纯静态收益。**
  排 P2 是因为要先确认仓库有没有可用的 mypy 基线（当前无配置）。
- **P2 · guard 标志位收归 `window.__init__`**，禁止 `getattr(..., False)`
  形式的读取。`_applying_view` 是最该先补的一个。
- **P2 · 打破 `_analysis_mixin` 的 hub 地位**：把它被 5 个 mixin 共用的那
  几个方法（`_analysis_ctx` / `_analysis_page` / `_capture_analysis_*`）
  抽成一个无状态的 `AnalysisContext` 协作对象。

---

## 8. 逐 feature 静态结构风险

**列名修正（rev2）：** 这一栏原名「稳定性」，改为「静态结构风险」。
它衡量的是**审查/修改成本与失效不可见程度**，**不是**已证明的运行时缺陷率
—— 后者需要崩溃/缺陷数据，而当前恰恰因为 R1 拿不到（这也正是 W2 要解决的）。

| Feature | 静态结构风险 | 依据 |
|---|:---:|---|
| **数值算法**（FFT / 阶次 / 滤波 / 加窗 / 谱图） | 🟢 **低** | 2,179 LOC，1 个 except 处理器（0 宽泛静默），无 GUI 依赖（有 `test_signal_no_gui_import` 守着）。**例外：22 行的 `channel_math.py` 零测试覆盖，见 §9.3** |
| **数据导入**（MF4 / HDF / CSV / BLF / TDMS / WWT / ZFD / MAT / 音视频） | 🟢 **低** | 3,477 LOC，静默率 12%，异常多为 `raise` 或显式 fallback，每种格式都有独立测试文件。契约在 CLAUDE.md 里写得很清楚（不猜采样率、不造工程单位） |
| **View 状态模型**（`view_state.py`） | 🟢 **低** | 纯 dataclass + `ViewManager`，索引越界全部有守卫，split 配对在 reorder/delete 时按**对象身份**重建而非索引 —— 设计得很对。JSON 往返有调色板兼容注释 |
| **采集内核**（`acquisition_capture`） | 🟢 **低** | 静默率 8%，有 logging，测试覆盖是全仓库最系统的（20+ 个专项测试文件） |
| **右栏 Inspector** | 🟢→🟡 **低-中**（rev1 是 🟠 弱） | **重新评级。** 37 个静默 `pass` 里 **34 个只捕获 `TypeError`/`ValueError`**，是带 docstring 的旧-preset 数值兼容守卫；只有 **3 处**宽泛。剩余风险是 `_applying_preset` guard 横跨 4 个文件，不是异常处理 |
| **批处理** | 🟢→🟡 **低-中**（rev1 是 🟡 中） | **重新测量。** 4,895 LOC（不是 5,186）/ 26 处理器（不是 27）；12 个静默里 10 个是窄 `TypeError`/`ValueError`，仅 2 处宽泛。有 `batch_validation` / `batch_manifest` 等结构化测试 |
| **采集界面** | 🟡 **中** | 11,187 LOC，静默率 15%，5 个 mixin 结构清晰，但 `live_cards.py` 单文件 1,934 行 |
| **主窗口 mixin 路由** | 🟡 **中** | 状态所有权干净，但调用图有环、guard 标志位跨文件、`_applying_view` 无初始化、无静态类型约束 |
| **通道树 / 通道配置** | 🟡 **中** | 静默率 14% 不高，但 `channel_config_manager.py` 1,276 行、`widgets/__init__.py` 1,760 行 + 24 处 `_updating` guard |
| **绘图 / 坐标 / 显示**（`pg_canvas`） | 🔴 **高** | 16,914 LOC，**288 处宽泛静默**（55%），`_CanvasBackref` 写穿透，`canvas.py` 单类 4,042 行 / 75 状态字段 / 158 方法，`clear()` 手写 38 项重置无测试保护，死标志位 `_refresh`，无主缓存 `_channel_render_profiles`，**已复现 1 个 Y 轴串台正确性 bug**（§9.2）。**lessons-learned 里 74/279 条来自这里** |

---

## 9. 已核实的问题

**rev2 重新分档：** 本节按**证据强度**排序 —— 已端到端复现的正确性 bug 在前，
静态推断的地雷在后。这是相对 rev1 最重要的结构改动。

### 9.1 ✅ 已复现 · `moving_avg` 返回长度与输入不一致 —— 真 bug

`signal/channel_math.py`（全文 22 行）：

```python
@staticmethod
def moving_avg(sig, ws=50):
    return np.convolve(sig, np.ones(ws) / ws, mode='same')    # ← 无长度校验
```

`np.convolve(..., mode='same')` 返回 `max(len(sig), ws)` 个元素，
不是 `len(sig)`。实测（附录 A-10）：

| `len(sig)` | `ws` | `len(out)` | |
|---:|---:|---:|---|
| 3 | 50 | **50** | 不一致 |
| 10 | 100 | **100** | 不一致 |
| 2000 | 5000 | **5000** | 不一致 |
| 1000 | 50 | 1000 | ok |

**UI 可达。** `ui/dialogs.py:362` 调用
`ChannelMath.moving_avg(sig, max(int(p), 3))`，其中 `p` 来自 `spin_p`，
量程是 **±1e12**（`dialogs.py:125`），没有按通道长度做上界。
短通道 + 大窗口 → 新通道的数据数组比时间轴长，下游任何
`zip(t, result)` / 绘图 / 导出都会出错或悄悄截断。

**零测试覆盖。** `channel_math` 是 `signal/` 里**唯一**没有任何测试文件引用的
模块：

```
__init__: 49    envelope: 13    order: 115    weighting: 29
fft: 80         filters: 18     spectrogram: 23
channel_math: 0   ← 唯一的 0
```

`tests/ui/test_dialogs.py` 里两处 `dlg._create_single()` 只测错误分支
（源通道不存在、运算类型未知），**从未真正调用过任何一个 ChannelMath 运算**。

**修复（W1b）：** `ws = max(1, min(int(ws), len(sig)))`，`len(sig) == 0` 早退，
并建立 `tests/signal/test_channel_math.py`。

### 9.2 ✅ 已复现 · 同名通道的 Y 轴串台 —— 真 bug（本报告最强的发现）

`canvas.py:2046-2054`，`restore_visible_ylims` 的「新通道自动 fit」分支：

```python
for key, (handle, line) in view_state_lines.items():   # key = 复合键
    if key in restored_keys:
        continue
    get_label = getattr(line, "get_label", None)
    channel_name = get_label() if callable(get_label) else key   # ← 退回显示名
    if self._fit_channel_y_to_visible_x(channel_name, handle, ...):
```

`_fit_channel_y_to_visible_x`（canvas.py:2064）第一行是
`row = self.channel_data.get(name)`。`channel_data` 是 `_ChannelKeyDict`，
其 `_resolve` 对**歧义的裸名读取**是 *"Last-bound wins"*（`_shared.py:99-101`，
注释自己写明了）。所以两个文件同名通道时，**用后绑定那条的数据去 fit
前一条的 Y 轴。**

**端到端复现**（附录 A-11，真实 `TimeDomainCanvasPG`，offscreen）：

```
display name A = '[measurem…_run_2026] sig'      (file A: 范围 [-1, 1])
display name B = '[measurem…_run_2026] sig'      (file B: 范围 [100, 200])
names collide  = True

before restore:  A=(-1.0, 1.0)         B=(100.0, 200.0)
after  restore:  A=(95.0000, 204.9999) B=(100.0, 200.0)
                    ↑↑↑ file A 的坐标轴被 file B 的数据拟合了

channel_data.get('[measurem…_run_2026] sig') → min/max = 100.000 / 200.000
file A 真实 min/max                          → -1.000 / 1.000
```

用户看到的：加载两个同名（短名截断后同名）文件后，重新勾选某个通道，
它的 Y 轴跳到另一个文件那条曲线的量程上，自己的曲线变成一条贴边的直线。

**修复已验证可行。** `view_state_lines` 的 key 就是复合键，且
`channel_data` 的存储键与之**完全一致**（实测两边 key 集合相等），
所以把复合键直接传给 fitter 即可：

```
channel_data.get(composite A) -> min/max -1.000/1.000        ✅ 解析正确
A axis after fit with COMPOSITE key: (-1.0999, 1.0999)       ✅ 修复
```

`_fit_channel_y_to_visible_x` 全仓库**只有这一个调用点**，改动面极小。
详见 W1a。

### 9.3 ⚠️ API 级缺陷（当前 UI 不可达）· `integral` 的整数截断

```python
@staticmethod
def integral(t, sig):
    r = np.zeros_like(sig)                                    # ← 继承 sig 的 dtype
    r[1:] = np.cumsum(0.5 * (sig[1:] + sig[:-1]) * np.diff(t))
    return r
```

整数入参 → `np.zeros_like` 给出 `int64` 数组 → 梯形积分的 `.5` 全部被截断：

```
t=[0,1,2,3], sig=[0,1,2,3]
int   入参 → [0 0 2 4]        dtype=int64
float 入参 → [0. 0.5 2. 4.5]  ← 正确值
```

**降级理由（rev2）：** rev1 把它和 `moving_avg` 并列。但唯一的 UI 调用点
`dialogs.py:347` 在调用前已经做了 `.astype(float)`：

```python
sig = self.fd.data[src].values.astype(float)     # dialogs.py:347
...
r = ChannelMath.integral(t, sig)                 # dialogs.py:356
```

所以**从这个对话框走不到**。它仍然是一个应该修的 API 契约缺陷（模块零测试
覆盖，下一个调用者不会知道这个前提），但严重度是「潜在」，不是「活的 bug」。

顺带核到的第三个边界（rev1 未提）：`derivative(t, sig)` 在 0 样本时抛
`IndexError`（`np.gradient` 内部），`moving_avg` 在空数组上抛
`ValueError: a cannot be empty`。两者都会**抛**而不是静默 —— `dialogs.py`
的 `except Exception` 会转成 `QMessageBox.critical`，所以不是可观测性问题，
但错误文案对用户没有意义。

**修复（W1b）：** `integral` 用 `np.zeros(len(sig), dtype=float)`；
三个函数的空/短数组行为写进测试。

### 9.4 ⚠️ 地雷 · `_ChannelKeyDict` 的 dict 协议逃逸（比 rev1 说的更严重，但也更难修）

`_shared.py:25` 的 `_ChannelKeyDict` 是为解决「两个文件同名通道互相覆盖」而
设计的（docstring 明确写着 *"the ROOT fix, not a probability reduction"*）。
它重写了 `__iter__` / `keys` / `values` / `items` / `__getitem__` / `get` /
`__contains__` / `pop` / `__delitem__` / `clear`，
**但没有重写 `update` / `setdefault` / `copy`，也挡不住 `dict(d)` 和 `{**d}`。**

实测（附录 A-7，本 SHA）：

```
原始:              len(d) = 2   items() = [('torque','A-data'), ('torque','B-data')]
d.get('torque') -> 'B-data'                              ← last-bound wins（有意设计）
dict(d)         -> len = 1      {'torque': 'B-data'}      ← A 通道数据丢失
{**d}           -> len = 1      {'torque': 'B-data'}      ← 同上
d.copy()        -> len = 1      {'torque': 'B-data'}      ← 同上，且返回普通 dict
e.update(d)     -> len(e) = 1   [('torque','B-data')]     ← 同上
```

**rev2 新发现（rev1 和 codex 都没提）：`setdefault` 不是「没保护」，
而是主动制造污染。**

```
d.setdefault('torque', 'X')  -> 返回 'X'            ← 不是已存在的 'B-data'！
len(d)                       -> 3                   ← 凭空多出一条
composite_items()            -> [('["fileA","torque"]', 'torque', 'A-data'),
                                 ('["fileB","torque"]', 'torque', 'B-data'),
                                 ('torque',             'torque', 'X')]  ← 幽灵条目
```

因为 `setdefault` 走的是 `dict.setdefault`，绕过了 `__contains__` 的
名字解析，直接以**裸显示名**为键插了一条。此后 `_resolve('torque')` 的第一步
`dict.__contains__(self, 'torque')` 命中这个幽灵条目 → **之后所有裸名读取
都拿到 `'X'`**，两个真实通道同时被遮蔽。这是一条真实的状态污染路径，
不只是「转换时折叠」。

现状：`grep` 全仓库，**当前没有活的 `dict(...)` / `setdefault` 调用点**。
所以这是地雷不是伤口。但它是一个**长得完全像普通 dict 的对象**，
任何人做重构时顺手 `dict()` 一下就会重新引入那个已经被修过一次的 bug。

**修复方向修正（rev2）：** rev1 写「重写 `update`/`setdefault`/`copy`，成本 20 行」。
这个估算过于乐观，且方案不完整：

- `copy()` 可以修（返回 `_ChannelKeyDict` 而非 `dict`）；
- `update(other)` 可以修（`other` 是 `_ChannelKeyDict` 时走 `composite_items()`）；
- `setdefault()` 可以修（先 `_resolve`，命中就返回既有值）；
- **`dict(d)` / `{**d}` 修不了。** 因为普通 `dict` 在物理上无法保存两个
  完全相同的显示键 —— 只要 `keys()` 暴露显示名，任何到普通 dict 的转换
  必然折叠。实测确认：`{k: v for k, v in d.items()}` 也只剩 1 条。

所以正确方向是**明确区分两个面**：「复合身份映射」（唯一、可转换）
与「显示标签序列」（可重复、只能迭代不能当 mapping 用），提供显式转换 API
（`as_composite_dict()` / `display_pairs()`），并让「当普通 dict 用」这件事
**失败得响亮**而不是静默折叠。这需要自己的设计文档，不是 20 行。
本轮只做可安全修的三个方法 + 折叠行为的基线测试（W1c），
完整的面分离进 P2。

### 9.5 ⚠️ 低 · 副屏 canvas 创建后永不销毁

`chart_stack/stack.py:603 enter_split()` —— 9 处 connect 全部包在
`if self._secondary_card is None:` 里，**幂等，没有重复连接问题**（这点做得对）。
`exit_split()` 只 `setVisible(False)`，不销毁。

代价：副屏 canvas 及其持有的通道数据在退出分屏后仍常驻内存。
**是内存权衡，不是正确性问题**，但大文件场景下值得知道。

### 9.6 ✅ 已有防护 · `_chart_options_ax` 悬垂引用

`clear()` 不重置 `_chart_options_ax`，但 `_resolve_active_axis_handle()` 用
`remembered in self.axes_list` 校验存活。**这是对的。** 记在这里是因为它
说明代码里已经有正确的防御模式 —— 问题是这种模式没有系统化。

---

## 10. 修复计划（rev2 重排）

**排序原则变了。** rev1 按「机械化程度 + 覆盖面」排（先给 296 处加日志）。
rev2 按「证据强度」排：**已复现的正确性 bug 先修，再建可观测性，
再动状态卫生，最后才用数据决定测试策略。**

配套文档：
- 设计规格：`docs/superpowers/specs/2026-07-30-robustness-remediation-phase1-design.md`
- 实施计划：`docs/superpowers/plans/2026-07-30-robustness-remediation-phase1.md`

| 包 | 内容 | 证据 | 预估 | 归属专家 |
|---|---|---|---|---|
| **W1a** | `_fit_channel_y_to_visible_x` 改收复合键（同名通道 Y 轴串台） | §9.2 已端到端复现 | 0.5 天 | `pyqt-ui-engineer` |
| **W1b** | `channel_math` 长度/dtype 守卫 + 首个测试文件 | §9.1 / §9.3 已复现 | 0.5 天 | `signal-processing-expert` |
| **W1c** | `_ChannelKeyDict` 修 `copy`/`update`/`setdefault` + 折叠基线测试 | §9.4 已复现（含幽灵条目） | 0.5 天 | `pyqt-ui-engineer` |
| **W2** | 跨平台轮转日志 + `sys.excepthook` / `threading.excepthook` / `qInstallMessageHandler` + 限频器；接 5–10 条关键路径 | §3 | 2 天 | `pyqt-ui-engineer` |
| **W3** | 删 `_refresh`；`_channel_render_profiles` 认领主人；`_CanvasBackref` 写穿透白名单测试；`_artist` 归位 | §4 / §5 均已复现 | 1.5 天 | `refactor-architect` |
| **W4** | 测试分类研究（分层抽样 ≥30/层 + 覆盖率），产出报告 —— **不改生产代码** | §6 | 1 天 | `refactor-architect` |

### 明确推迟（附理由）

| 项 | 为什么不在本轮 |
|---|---|
| 给 296 处 `except: pass` 统一加 `logger.debug` | 热路径日志风暴风险；必须先有 W2 的轮转 + 限频。之后按日志里的真实信号增量加，不做批量 |
| 拆 `canvas.py`（4,042 行） | R4 的因果没证明（§6），W4 出结论前动它是在赌 |
| 契约测试层 + `@pytest.mark.whitebox` 规则 | 同上，W4 的输出决定要不要做、做多大 |
| `_ChannelKeyDict` 身份/标签双面分离 | 需要自己的设计文档；W1c 只堵可安全堵的洞 |
| `MainWindowProtocol` + mypy | 仓库当前无 mypy 基线，引入成本要单独评估 |
| `_CanvasBackref.__setattr__` 收口为白名单抛错 | 先让 W3 的白名单测试跑一段时间收集真实写穿透，再收口 |
| `clear()` / `__init__` 对称性测试 | 依赖 W3 先定下 `_channel_render_profiles` 的生命周期 |
| `ui/inspector_sections` 静默率专项清理 | §2.1 重新测量后，34/37 是有意的窄守卫，收益远低于 rev1 估计 |

### 顺序

```
W1a + W1b + W1c  (可并行，互不相交)
        ↓
       W2  (可观测性基础设施 → 拿到真实故障信号)
        ↓
       W3  (状态卫生；依赖 W2 的日志确认删除无回归)
        ↓
       W4  (测试分类研究 → 决定 P2 要不要做拆分 / 契约层)
```

**不要先拆 `canvas.py`。** 不是因为「测试会拖死你」（那个因果没证明），
而是因为在 W2 之前你没有任何观测手段确认拆完没坏东西 —— 296 处静默
`except` 会把拆分引入的回归全部吃掉。

---

## 11. 值得肯定的部分

审计不是只找问题。这个仓库有几处做得明显好于同类项目：

1. **设计意图被写进了代码。** `canvas.py` 里大段注释记录了性能测量数据
   （"58.1 ms → 29.8 ms → 15.7 ms"）、为什么选 A 不选 B、以及具体的
   lessons-learned 文件引用。这在 PyQt 项目里非常罕见，**极大降低了
   接手成本**。这次审计能在一天内定位到 §9.2 那个 bug，靠的就是这些注释。
2. **lessons-learned 制度真的在运行。** 279 条，带索引、带模板、带 orchestrator
   剪枝流程。而且分布诚实地反映了痛点（`pyqt-ui/` 74 条）。
3. **`signal/` 和 `io/` 的分层纪律。** `test_signal_no_gui_import`、
   `test_native_import_boundaries`、`test_packaging_imports` 这类边界测试
   说明有人在认真守护依赖方向。
4. **`_ChannelKeyDict` 的问题定义是对的。** 它的 docstring 明确区分了
   "root fix" 和 "probability reduction"，还点名了「身份敏感的消费者必须用
   复合键」这条规则 —— 这是很高的工程标准。执行有缺口（§9.4），但思路对，
   而且 §9.2 那个 bug 恰恰就是它 docstring 里已经警告过的那类误用。
5. **`ViewManager` 的 split 配对按对象身份重建**，而不是按索引 —— 说明写的
   人真的想过 reorder/delete 的边界。
6. **裸 `except:` 只有 3 处**，且 `pg_canvas` 里已有 7 处
   `except (RuntimeError, TypeError): pass` 是「收窄 + 注释」的正面样板。
   问题不是"不会写"，是**局部质量标准在 `ui/` 层没有被同样地贯彻**。
7. **`view_state.py` 的 `MAX_VIEWS` 注释**（第 16-18 行）主动解释了为什么
   模块默认是 6 而主窗口传 12 —— rev1 曾把这当成文档不一致，是误报
   （见 §12 末表最后一行）。

---

## 12. 逐条核对 codex 复核意见

codex 判定 `needs revision`。五条主要意见全部在本 SHA 上复核过，
结论：**5 条全部成立**（其中 2 条我进一步收紧或修正了 codex 自己的数字）。

| # | codex 意见 | 复核结论 | 本版处置 |
|---|---|---|---|
| 1 | 审计缺少固定基线；批处理实测 4,895 LOC / 26 handlers，不是 5,186 / 27 | **成立。** 复现批处理 4,895 / 26 / 12 静默（46%）。另外自查出 3 处漂移：`ui/markup` 静默率应为 100% 而非「—」；`canvas.py` 158 方法（rev1 写 150）；canvas 运行时实例属性 75（rev1 的 74 是静态赋值数） | 加 §0 基线块（SHA + 版本 + 平台 + 探针方式）；表格全部重测 |
| 2 | R4 证据不足且不可复现；实测 `1,232 / 947 / 47` | **成立，但数字要澄清。** 按附录 A-6 原样复跑得 **1,232 / 894 / 47**：前两个和 rev1 一致（894 = 860 + 34），**第三个 rev1 的 ~92 是错的，实际 47**。codex 的 947 用 A-6 的命令复现不出来（行计数 vs 匹配计数）。因果论断（「测试惩罚清理」「唯一必须绿的层」）确实没有证据 | §6 改数字 + 明确列出「支持什么/不支持什么」；R4 在 §1 表里标注「因果未证明」；契约测试从 P1 降为「W4 之后再定」 |
| 3 | 「296 处统一加 `logger.debug`」不该作为机械化 P0；无级别/轮转/保留期配置；macOS 日志目录对 Windows `--windowed` 包不适用 | **成立，且比 codex 说的更硬。** `tools/` 下唯一打包脚本是 `build_windows_folder.ps1`，默认 `--windowed`（第 272 行），**没有 macOS 打包脚本** —— rev1 的 macOS 路径对实际交付物完全无效。`app.py` 全文无 logging/excepthook。288/296 是宽泛 `except Exception`，多在 pan/zoom/绘制/光标热路径 | 撤销该 P0；§3 建议改为「跨平台轮转 + 限频基础设施先行，再接 5–10 条关键路径」；日志目录按平台分支 |
| 4 | `_ChannelKeyDict` 地雷是真的，但方案不完整；重写 `update/setdefault/copy` 无法让普通 dict 保存两个同名键；20 行估算过于乐观 | **成立。** 实测 `{k:v for k,v in d.items()}` 同样折叠到 1 条 —— 只要 `keys()` 暴露显示名，到普通 dict 的转换必然折叠，重写挡不住。**另补一条 codex 也没提的发现：`setdefault('torque','X')` 会以裸名插入第三条幽灵条目，之后所有裸名读取都被它遮蔽** —— 这是主动污染，不只是折叠 | §9.4 补幽灵条目实测；修复拆成「W1c 可安全修的三个方法 + 折叠基线测试」与「P2 身份/标签双面分离（需独立设计文档）」 |
| 5 | 按异常密度给 feature 评级过度；Inspector 的 37 个 `pass` 中 34 个只捕获 `TypeError`/`ValueError`；`connect/disconnect=32:1` 不能证明重复连接 | **成立，数字逐个吻合。** Inspector：27 × `(TypeError, ValueError)` + 4 × `ValueError` + 3 × `TypeError` = **34 窄 / 3 宽**。批处理：10 窄 / 2 宽。对比 `pg_canvas` 288 宽。QObject 析构自动断连，32:1 只是审查成本指标 | §2.1 加「宽泛 `except Exception`」列；Inspector 🟠→🟡、批处理评级下调；§8 列名从「稳定性」改为「静态结构风险」；§2.2 给 connect 比例加降级说明 |

### codex 确认应保留的部分（我逐条独立复现）

| 结论 | 独立复现结果 |
|---|---|
| `_CanvasBackref` 隐式写穿透 | ✅ 用 AST 脚本（附录 A-8，rev2 已把脚本写进报告）逐类枚举，与 rev1 表格完全一致 |
| `AnnotationManager._artist` 不在 `_owned_names` 却被写到 canvas | ✅ `_owned_names = {enabled, remarks, press_pos, press_dragged}`；另确认 canvas 自己完全不用 `_artist`（同族用 `_remark_artist`） |
| `_refresh` 19 写 / 0 生产读取，删除候选成立 | ✅ 另补三项删除安全性核查：无 `def _refresh(`、类上无该属性、相邻 `_refresh_*` 名字都是活的 |
| `_channel_render_profiles` 无初始化无清理；定性应为「小型无界缓存 + 生命周期缺陷」而非严重泄漏 | ✅ 实测 `RenderProfile` 是 frozen dataclass，9 个标量字段，不持有 ndarray，≈380 B/条；10,000 条 ≈ 3.6 MiB。§5.2 已改定性 |
| 同名通道 Y 轴串台是最强的真实发现（file-A `[-1,1]` 被 file-B 拟合成 `(95,205)`） | ✅ 独立复现，数值吻合：`(95.0000169803578, 204.9999830196422)`。另**验证了修复可行性**：传复合键得 `(-1.0999, 1.0999)`，且 `channel_data` 与 `view_state_lines` 的 key 集合完全相等 |
| `moving_avg(3, ws=50)` 返回 50 个元素，UI 允许大窗口，是实际 bug | ✅ 复现；另补 `spin_p` 量程 ±1e12 与「`channel_math` 是 `signal/` 里唯一零测试引用模块」两项证据 |
| `integral` 整数截断在当前 UI 路径不可达（`dialogs.py:347` 已 `astype(float)`），应降低严重度 | ✅ 确认。降为「API 级潜在缺陷」；另给出真正体现截断的用例（`[0,0,2,4]` vs `[0,0.5,2,4.5]`） |
| 「12 View 文档不一致」是误报 | ✅ 确认误报。`view_state.py:16-18` 的注释**主动解释**了 6 是留给分析区的历史默认值，`window.py:237` 显式传 12，CLAUDE.md 第 17 行说的是"主时域"。**§13 已删除该行**，并改记入 §11 值得肯定的部分 |

---

## 13. 文档一致性问题（顺带发现）

| 位置 | 写的 | 实际 | 影响 |
|---|---|---|---|
| `CLAUDE.md` → Architecture | "`tests/`（164 个 pytest 用例）" | **3,714 个测试函数** | 严重低估，会让人误判测试成本 |

建议在 CLAUDE.md 里把测试数量改成动态说明（或直接删掉具体数字）。

> **rev1 的第二行已删除。** 原文写「`view_state.MAX_VIEWS = 6` 与文档的 12 不一致」。
> 复核后确认是误报：CLAUDE.md 第 17 行说的是「**主时域**工作区最多 12 个 View」，
> `window.py:237` 明确传 `max_views=12`，而 `view_state.py:16-18` 的注释
> 已经说明模块级默认 6 是**故意**留给分析区（fft / fft_time / order）的。
> 三者一致，没有问题。

---

## 附录 A · 复现命令

> 所有命令在 `commit b5d7956e` 上验证过。运行时探针必须用 `.venv/bin/python`
> （系统 `python3` 无 PyQt5），并设 `QT_QPA_PLATFORM=offscreen` 和
> `PYTHONPATH=<repo>`。纯静态的 AST/grep 脚本用任意 `python3` 都行。

```bash
cd "<repo>"
git rev-parse HEAD                      # 期望 b5d7956eb8c80c7981d174ed92575e876d171c2b

# A-0 版本基线
.venv/bin/python -c "
import sys; from PyQt5.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
import numpy, scipy, pyqtgraph, asammdf, pytest
print('py', sys.version.split()[0], '| Qt', QT_VERSION_STR, '| PyQt5', PYQT_VERSION_STR)
print('numpy', numpy.__version__, '| scipy', scipy.__version__,
      '| pyqtgraph', pyqtgraph.__version__, '| asammdf', asammdf.__version__,
      '| pytest', pytest.__version__)"
```

### A-1 各子系统 LOC + except 静默率

```bash
python3 - <<'EOF'
import ast, os
targets = {
 'ui/pg_canvas':'mf4_analyzer/ui/pg_canvas',
 'ui/inspector_sections':'mf4_analyzer/ui/inspector_sections',
 'ui/drawers/batch':'mf4_analyzer/ui/drawers/batch',
 'ui/main_window':'mf4_analyzer/ui/main_window',
 'ui/widgets':'mf4_analyzer/ui/widgets',
 'ui/chart_stack':'mf4_analyzer/ui/chart_stack',
 'ui/markup':'mf4_analyzer/ui/markup',
 'ui_kit':'mf4_analyzer/ui_kit',
 'acquisition_ui':'mf4_analyzer/acquisition_ui',
 'acquisition_capture':'mf4_analyzer/acquisition_capture',
 'io':'mf4_analyzer/io',
 'signal':'mf4_analyzer/signal',
 'ui (all)':'mf4_analyzer/ui',
 'mf4_analyzer (all)':'mf4_analyzer',
}
for label, d in targets.items():
    loc = h = s = 0
    for dd, _, fs in os.walk(d):
        if '__pycache__' in dd: continue
        for f in sorted(fs):
            if not f.endswith('.py'): continue
            src = open(os.path.join(dd, f), encoding='utf-8').read()
            loc += len(src.splitlines())
            for n in ast.walk(ast.parse(src)):
                if isinstance(n, ast.ExceptHandler):
                    h += 1
                    if len(n.body) == 1 and isinstance(n.body[0], ast.Pass): s += 1
    rate = f'{100*s/h:.0f}%' if h else '-'
    print(f'{label:24s} LOC={loc:6d} handlers={h:4d} silent_pass={s:4d} ({rate})')
EOF
```

### A-1b 静默处理器按捕获类型分解（rev2 新增，§2.1 的关键证据）

```bash
python3 - <<'EOF'
import ast, os, collections
def census(d):
    kinds = collections.Counter()
    for dd, _, fs in os.walk(d):
        if '__pycache__' in dd: continue
        for f in sorted(fs):
            if not f.endswith('.py'): continue
            src = open(os.path.join(dd, f), encoding='utf-8').read()
            for n in ast.walk(ast.parse(src)):
                if isinstance(n, ast.ExceptHandler) and len(n.body) == 1 \
                        and isinstance(n.body[0], ast.Pass):
                    t = n.type
                    if t is None:
                        key = 'bare except:'
                    else:
                        elts = t.elts if isinstance(t, ast.Tuple) else [t]
                        key = ', '.join(sorted(ast.unparse(e) for e in elts))
                    kinds[key] += 1
    return kinds
for label, d in [('pg_canvas', 'mf4_analyzer/ui/pg_canvas'),
                 ('inspector_sections', 'mf4_analyzer/ui/inspector_sections'),
                 ('drawers/batch', 'mf4_analyzer/ui/drawers/batch')]:
    c = census(d)
    print(f'=== {label}: {sum(c.values())} silent pass handlers ===')
    for k, v in c.most_common():
        print(f'  {v:4d}  except {k}')
EOF
```

### A-2 死标志位 `canvas._refresh`（应只见写，不见读）

```bash
grep -rn "\._refresh\b" mf4_analyzer/ tests/ --include="*.py" | grep -v pycache
grep -rn '"_refresh"' mf4_analyzer/ tests/ --include="*.py" | grep -v pycache  # 应无输出
grep -rn "def _refresh(" mf4_analyzer/ --include="*.py" | grep -v pycache      # 应无输出
```

### A-3 `_channel_render_profiles` 无初始化、无重置

```bash
grep -rn "_channel_render_profiles" mf4_analyzer/ tests/ --include="*.py" | grep -v pycache
# 期望：renderer.py:527-530 / overlay_axes.py:315-318,425-428 惰性创建
#       dense_raster.py:241,403,435 + quality.py:88,300 只读
#       canvas.__init__ / clear() / full_reset() 全无
```

### A-3b `RenderProfile` 条目大小（§5.2 的定性依据）

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH="$PWD" .venv/bin/python -c "
import sys, numpy as np
from mf4_analyzer.ui.pg_canvas.render_profile import classify_render_profile
t = np.linspace(0, 10, 100_000); sig = np.sin(t)
p = classify_render_profile(t, sig, source_revision=('rev', 1))
fields = [getattr(p, f) for f in p.__dataclass_fields__]
print('holds ndarray?', any(isinstance(f, np.ndarray) for f in fields))
print('bytes/entry  ~', sys.getsizeof(p) + sum(sys.getsizeof(f) for f in fields))"
```

### A-4 connect / disconnect 比

```bash
grep -rn "\.connect("    mf4_analyzer --include="*.py" | wc -l   # 669
grep -rn "\.disconnect(" mf4_analyzer --include="*.py" | wc -l   # 21
```

### A-5 无全局兜底（应无输出）

```bash
grep -rn "excepthook\|qInstallMessageHandler" mf4_analyzer tools scripts --include="*.py"
```

### A-6 测试风格比例

```bash
grep -rn "assert [a-z_]*\._[a-z_]*" tests --include="*.py" | wc -l              # 1232
grep -rn "monkeypatch.setattr\|canvas\._[a-z_]* *= " tests --include="*.py" | wc -l  # 894
grep -rn "\.grab(\|toImage()\|pixelColor" tests --include="*.py" | wc -l        # 47
# 拆开： monkeypatch.setattr 860 / canvas._x= 34 ; grab( 10 / toImage 16 / pixelColor 30
# 注意：以上是「行」计数。按「匹配」计数（rg --count-matches）会得到更大的数。
```

### A-7 `_ChannelKeyDict` dict 协议逃逸（§9.4）

```bash
.venv/bin/python - <<'EOF'
import sys, types, importlib.util
m = types.ModuleType('mf4_analyzer.ui.plot_helpers'); m._compact_axis_label = lambda *a, **k: ''
sys.modules['mf4_analyzer.ui.plot_helpers'] = m
spec = importlib.util.spec_from_file_location('sh', 'mf4_analyzer/ui/pg_canvas/_shared.py')
sh = importlib.util.module_from_spec(spec); spec.loader.exec_module(sh)

d = sh._ChannelKeyDict()
d.set_with_label(sh._view_state_channel_key('fileA', 'torque'), 'torque', 'A-data')
d.set_with_label(sh._view_state_channel_key('fileB', 'torque'), 'torque', 'B-data')
print('len(d)          =', len(d), list(d.items()))
print("d.get('torque') =", d.get('torque'), '  <- last-bound wins')
print('dict(d)         =', dict(d))          # 折叠成 1 条，A-data 丢失
print('{**d}           =', {**d})
c = d.copy(); print('d.copy()        =', c, type(c).__name__)
e = {}; e.update(d); print('e.update(d)     =', e)
print('setdefault      =', d.setdefault('torque', 'X'), '-> len', len(d),
      '  <- 幽灵条目！')
print('composite_items =', [(k, l, v) for k, l, v in d.composite_items()])
plain = {k: v for k, v in d.items()}
print('comprehension   =', plain, '-> len', len(plain),
      '  <- 重写方法也挡不住')
EOF
```

### A-8 `_CanvasBackref` 写穿透枚举（§4；rev1 只说「脚本见审计记录」，rev2 补全）

```bash
python3 - <<'EOF'
import ast, os
ROOT = "mf4_analyzer/ui/pg_canvas"

def frozenset_literal(node):
    out = set()
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "frozenset":
        node = node.args[0] if node.args else ast.Set(elts=[])
    if isinstance(node, (ast.Set, ast.List, ast.Tuple)):
        for e in node.elts:
            if isinstance(e, ast.Constant) and isinstance(e.value, str):
                out.add(e.value)
    return out

def self_assign_targets(cls):
    out = set()
    for node in ast.walk(cls):
        targets = []
        if isinstance(node, ast.Assign): targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)): targets = [node.target]
        for t in targets:
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) \
                    and t.value.id == "self":
                out.add(t.attr)
    return out

for fname in sorted(os.listdir(ROOT)):
    if not fname.endswith(".py"): continue
    tree = ast.parse(open(os.path.join(ROOT, fname), encoding="utf-8").read())
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        bases = {getattr(b, "id", getattr(b, "attr", "")) for b in cls.bases}
        if "_CanvasBackref" not in bases: continue
        declared = set()
        for stmt in cls.body:
            if isinstance(stmt, ast.Assign) and any(
                    getattr(t, "id", "") in ("_owned_names", "_delegate_names")
                    for t in stmt.targets):
                declared |= frozenset_literal(stmt.value)
        through = sorted(self_assign_targets(cls) - declared - {"_c"})
        print(f"{cls.name} ({fname}) declared={len(declared)}")
        print("  writes through to canvas: " + (", ".join(through) or "(none)"))
EOF
```

### A-8b delegate 名字与 canvas 实例属性的冲突检查（§4 的「0 冲突」）

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH="$PWD" .venv/bin/python - <<'EOF'
import sys
from PyQt5.QtWidgets import QApplication
app = QApplication(sys.argv)
from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG
from mf4_analyzer.ui.pg_canvas import (annotations, cursor, overlay_axes,
                                       quality, renderer, tick_density)
c = TimeDomainCanvasPG(); init_attrs = set(vars(c))
classes = [annotations.AnnotationManager, cursor.CursorController,
           overlay_axes.OverlayAxisManager, quality.QualityManager,
           renderer.Renderer, tick_density.TickDensityController]
total = not_methods = 0; conflicts = []
for cls in classes:
    for n in set(cls._owned_names) | set(cls._delegate_names):
        total += 1
        if not callable(getattr(type(c), n, None)): not_methods += 1
        if n in init_attrs: conflicts.append((cls.__name__, n))
print('declared names:', total, '| not canvas methods:', not_methods)
print('conflicts with canvas.__init__ attrs:', len(conflicts), conflicts)
print('canvas instance attr count:', len(init_attrs))
EOF
```

### A-9 mixin 调用图与状态所有权（§7）

AST 统计每个文件的 `self.attr` Store/Load，并按「被调用者定义在哪个文件」建边。

### A-10 `channel_math` 边界行为（§9.1 / §9.3）

```bash
PYTHONPATH="$PWD" .venv/bin/python - <<'EOF'
import numpy as np
from mf4_analyzer.signal.channel_math import ChannelMath as CM
print('=== moving_avg 长度契约 ===')
for n, ws in [(3, 50), (3, 3), (1000, 50), (10, 100), (2000, 5000)]:
    out = CM.moving_avg(np.arange(n, dtype=float), ws)
    print(f'  len(sig)={n:5d} ws={ws:5d} -> len(out)={len(out):5d}'
          f'  {"MISMATCH" if len(out) != n else "ok"}')
print('=== integral dtype ===')
t = np.array([0, 1, 2, 3]); s = np.array([0, 1, 2, 3])
print('  int  ->', CM.integral(t, s), CM.integral(t, s).dtype)
print('  float->', CM.integral(t.astype(float), s.astype(float)))
print('=== 空/短数组 ===')
for fn, args in [('derivative', (np.array([]), np.array([]))),
                 ('moving_avg', (np.array([]), 3)),
                 ('integral',   (np.array([]), np.array([])))]:
    try: print(f'  {fn}(empty) ->', getattr(CM, fn)(*args))
    except Exception as e: print(f'  {fn}(empty) -> {type(e).__name__}: {e}')
EOF
```

### A-11 同名通道 Y 轴串台端到端复现（§9.2；rev2 新增）

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH="$PWD" .venv/bin/python - <<'EOF'
import sys, numpy as np, pandas as pd
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QCoreApplication
app = QApplication(sys.argv)
from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.ui.pg_canvas._shared import _view_state_channel_key
from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

def mk(stem, off, amp, idx):
    n = 2000; t = np.linspace(0, 1, n); s = off + amp * np.sin(2 * np.pi * 5 * t)
    return FileData(f"{stem}.csv", pd.DataFrame({"time": t, "sig": s}),
                    ["time", "sig"], {"sig": "u"}, idx=idx)

def row(fd, fid):
    return (fd.get_prefixed_channel("sig"), True, fd.time_array,
            fd.data["sig"].to_numpy().astype(float),
            fd.get_color_palette()[0], "u", fid)

# 头尾相同、中间不同 -> middle_ellipsis 折叠成同一个 short_name
a = mk("measurement_AAAA_run_2026",   0.0,  1.0, 0)   # 范围 [-1, 1]
b = mk("measurement_BBBB_run_2026", 150.0, 50.0, 1)   # 范围 [100, 200]
name = a.get_prefixed_channel("sig")
assert name == b.get_prefixed_channel("sig"), "fixture: names must collide"

c = TimeDomainCanvasPG(); c.resize(800, 480); c.show(); QCoreApplication.processEvents()
c.plot_channels([row(a, "fid-A"), row(b, "fid-B")], mode="subplot")
QCoreApplication.processEvents()

ka = _view_state_channel_key("fid-A", name); kb = _view_state_channel_key("fid-B", name)
lines = c._channel_view_state_lines
lines[ka][0].set_ylim(-1.0, 1.0); lines[kb][0].set_ylim(100.0, 200.0)
QCoreApplication.processEvents()
before = c.get_visible_ylims()
print('before:', before[ka], before[kb])

c.restore_visible_ylims({kb: before[kb]})     # 只恢复 B -> A 走 fit fallback
QCoreApplication.processEvents()
print('after :', c.get_visible_ylims()[ka], '  <- 期望 ~[-1,1]，实际落在 B 的量程')

# 修复可行性：复合键解析正确
n_y = max(3, min(20, c._tick_density_controller.density[1]))
c._fit_channel_y_to_visible_x(ka, lines[ka][0], n_y, frame_to_nice=False)
print('fit with COMPOSITE key ->', lines[ka][0].get_ylim())
EOF
```

### A-12 `channel_math` 测试覆盖（§9.1）

```bash
for f in mf4_analyzer/signal/*.py; do
  b=$(basename "$f" .py)
  echo "$b: $(grep -rl "$b" tests/ --include='*.py' 2>/dev/null | wc -l | tr -d ' ') test files"
done
# 期望：channel_math 是唯一的 0
```

---

## 附录 B · 一句话给决策者

> 代码质量的**下限**很高（`signal/`、`io/`、`view_state.py` 都很扎实），
> 问题集中在 `ui/pg_canvas` 这 1.7 万行里：**288 处宽泛静默吞异常 + 零全局
> 日志兜底**，加上 `_CanvasBackref` 写穿透和无主标志位造成的**状态边界缺失**。
>
> 这次审计在这一层挖出了 **2 个已端到端复现的正确性 bug**（同名通道 Y 轴串台、
> 移动平均输出长度），都不是猜测 —— 而它们能长期存活，正是因为静默失败让
> 它们不报错。
>
> **先修这 2 个 bug（1 天），再建跨平台可轮转的异常兜底（2 天），
> 然后做状态卫生（1.5 天）。** 拆 `canvas.py` 和批量改异常处理器都推迟：
> 前者在没有可观测性时是盲改，后者在没有限频时会用日志风暴换来新的卡顿。
> 测试套件要不要动，等 W4 的分类数据出来再定 —— 目前只有结构指标，没有因果。
