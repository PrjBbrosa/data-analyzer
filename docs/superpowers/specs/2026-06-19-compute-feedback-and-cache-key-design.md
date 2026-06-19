# 计算反馈契约 + 阶次缓存键修复设计

日期：2026-06-19
分支：`main`
审计来源：本会话两路只读审计
- 缓存键横展审计（order / fft / fft_time 的「键含字段 vs 计算消费字段」差集）
- 全局静默无反馈审计（toast / statusBar / QMessageBox 基础设施 + no-op 清单）

## 背景

用户现象：在阶次（COT）页调整最上方 **RPM系数** 后点「时间-阶次」，图形不变，像是「没反应」。

根因（已取证）：阶次分析的缓存键漏掉了 `rpm_factor`（和 `fs`）。`rpm_factor`
真正参与计算——`_order_rpm_for()` 把转速数组整体乘以系数
（`mf4_analyzer/ui/main_window/_order_mixin.py:58-59`），但缓存键
`_order_compute_cache_params()`（`_order_mixin.py:140-153`）只登记了 8 个字段，
不含系数。于是改系数后键不变 → 命中旧缓存 → 直接重渲染上一次结果。命中分支
只在状态栏 `statusBar.showMessage("使用缓存结果")`（`_order_mixin.py:241`）一闪，
用户更确信「坏了」。

这暴露了两个层面的问题，本设计一并收敛：

1. **正确性**：计算输入参数漏进缓存键（改参数不刷新）。横展后确认只有 order 一处。
2. **可感知性**：大量用户主动操作在某些分支下静默 no-op 或只有最弱的状态栏反馈，
   用户无法区分「真没反应 / 已用缓存 / 被跳过 / 正忙 / 出错」。

## 范围

- **P0**（正确性 + 数据安全）：补 order 缓存键；修保存图片吞异常。
- **P1**（统一反馈契约）：抽一个纯函数 summarizer + 一个 `_emit_compute_feedback`，
  替换三个计算按钮散落的状态栏/静默分支，给出一致、可见、可区分的 toast 反馈。
- **P2**（体验兜底）：切片手势落空、空图占位、被吞异常的恢复路径、保存项目成功 toast
  对称性、fft_time 多余键去除（perf）。

## 非目标

- 不重做 popup 圆角/阴影（那是 `2026-06-02-global-uiux-popup-polish-design.md` 的议题，
  与本轮「反馈可见性」正交，不重叠）。
- 不改 pyqtgraph 绘图热路径、pan/zoom/cursor 重绘、实时抗锯齿。
- 不重构三个计算按钮的整体分屏/队列架构，只在既有终点插入反馈。
- 不新增模态向导/教程。

## 性能边界

- 反馈只在用户点击计算 / 完成回调 / 手势落点等**低频**事件触发，不进入每帧刷新。
- summarizer 是纯 Python（无 Qt、无 numpy 大数组），O(图数)。
- 缓存键新增两个标量字段，键构造成本不变（仍是 `json.dumps` 一个小 dict）。

## 锁定决策

| 决策 | 内容 | 理由 |
|---|---|---|
| order 键补 `rpm_factor` + `fs` | 二者都是真正进入 COT 计算的用户可调输入 | `rpm_factor` 永远生效；`fs` 在时间戳退化分支重建时间网格时生效（`_order_mixin.py:296-297`） |
| 不改 FFT / FFT_time 键 | 审计确认它们无缺失计算参数 | 避免无谓改动稳定路径 |
| 反馈核心抽成纯函数 | `summarize_compute()` 无 Qt 依赖 | 可脱离 GUI 单测；DRY，三个按钮共用一套消息规范 |
| 命中缓存也要 toast | 用 `info` toast「已用缓存结果（参数未变）」替代状态栏一闪 | 这是用户「以为没反应」的直接来源 |
| 跳过要汇总告知 | 多 pane 计算结束时把跳过原因汇总成一条 `warning` toast | 静默 `return False` / `continue` 是投诉主体 |
| 保存图片失败必须弹窗 | `QMessageBox.warning` + 不关闭，禁止 `except: return` | 当前是「假成功 + 丢数据」，最高危 |
| 真机验收 | offscreen 测试只证逻辑与计数；toast 实际可见性需真机/截图复核 | 历史教训：offscreen Qt 不复现原生渲染（见 memory `feedback-verify-ui-visually`） |

## 审计证据（file:line）

### 缓存键缺失（确认 bug）

| Section | 缺失字段 | 可调位置 | 消费位置 | 严重度 |
|---|---|---|---|---|
| order | `rpm_factor` | `contextual_order.py:91-95`（getter `:519`） | `_order_mixin.py:58-59`（rpm × factor） | 高（永远生效） |
| order | `fs` | `contextual_order.py:86-90`（getter `:511`） | `_order_mixin.py:307`（`COTParams.fs`）+ `:296-297`（退化时重建时间网格） | 中（仅退化分支影响数值） |

- 键构造唯一权威点：`_order_compute_cache_params()` `_order_mixin.py:140-153`。
- 命中检查路径：`_analysis_cache_key('order',…)` → `_analysis_compute_params('order')`
  `_analysis_mixin.py:382-391` → `_order_analysis_cache_key` → 同一个权威点。
- 存储路径：`_dispatch_order_job` 用 `op = dict(get_params())` → `_order_analysis_cache_key`
  `_order_mixin.py:313-319` → 同一个权威点。
- `get_params()`（`contextual_order.py:522-542`）**不含** `rpm_factor`/`fs`，故两条路径都需注入。

FFT / FFT_time：审计确认键里无缺失计算参数（FFT 的 `fs` 取 `fd.fs` 文件固有量、已被 `fid`
锁定；FFT 的 `overlap` 仅喂批处理预设、不进谱计算）。

反向发现（白重算，低优先）：fft_time 键里 `db_reference`（`_fft_time_mixin.py:61`、
`_analysis_mixin.py:378`）是显示参数，compute 不读（`spectrogram.py:241-293`），dB 转换
在画布层另有缓存（`spectrogram.py:23`）。只改 dB 参考会整张重算。

### 反馈基础设施（可见度，强→弱）

| 通道 | 定义 | 形态 | 可见度 |
|---|---|---|---|
| `QMessageBox` | PyQt 原生 | 模态弹窗，必须确认 | 最强 |
| `toast(msg, level)` | `window.py:284`；实现 `ui/widgets/__init__.py:546` | 底部浮层，单条替换，4 级图标（info/success/warning/error），停留 3.5–7s，不挡操作 | 中 |
| `statusBar.showMessage` | PyQt 原生（~70 处） | 最底一行小字，常 2000ms 一闪 | 最弱（本案根源） |

### 静默 / 弱反馈 no-op 清单（节选，完整见下方分类）

完全静默（最高优先）：
- **保存图片** `pix.save()` 失败被 `except: return` 吞掉 → 假成功 + 丢数据。
  `ui/chart_stack/toolbar.py:652-655`。
- 阶次 per-pane 信号过短 `len(sig)<100` → `return False`（`_order_mixin.py:283-284`）。
- 阶次 per-pane 转速取不到 → `return False`（`_order_mixin.py:286-287`）。
- 阶次队列全跳过静默 drain（`_order_mixin.py:269-274`）。
- FFT per-source 过短 `len(sig)<10` → `continue`（`_fft_mixin.py:158-159,165-166`）。
- FFT 全跳过 `any_multi and not any_rendered` → 静默 `return`（`_fft_mixin.py:187-191`）。
- FFT-vs-Time per-pane 4 处 `return False`（`_fft_time_mixin.py:413,418,422,435`）。
- 导出 Excel 无数据/无勾选 → `return`（`window.py:1806-1807`）。
- 通道编辑器缺源/越界 → `return`（`dialogs.py:341,361,375,376,409`）。
- 点谱图取切片：结果未就绪 / 点在数据范围外 → `return`（`heatmap_canvas.py:1529,1533-1539`）。

仅状态栏（中优先）：
- 阶次缓存命中 `_order_mixin.py:241`；re-entry `_order_mixin.py:203-204`。
- FFT-vs-Time 缓存命中 `_fft_time_mixin.py:292-298,354-359`；re-entry `:232-233`。
- 切 Tab 缓存缺失 → 空白图 + 状态栏 `_analysis_mixin.py:531-537`。
- 保存项目成功仅状态栏 `_project_io_mixin.py:225`（与导出/加载有 toast 不对称）。

被吞异常（低优先但隐患）：
- 打开项目渲染恢复 `except Exception:` 仅状态栏 `_project_io_mixin.py:329-331`。
- 打开后自动重算 `except Exception: pass` `_analysis_mixin.py:466-467`。

## 反馈契约（核心）

**原则**：*每个用户主动触发的动作，都必须有一个可见的结局*——成功 / 已用缓存 /
被跳过（含原因）/ 正忙 / 失败。禁止静默 `return` 和裸 `except: pass` 出现在用户主动路径上。

### 计算结果汇总：纯函数 summarizer

新增 `mf4_analyzer/ui/compute_feedback.py`，无 Qt 依赖：

```python
from dataclasses import dataclass, field
from collections import Counter


@dataclass
class ComputeOutcome:
    """一次「计算」按钮按下后，每个 pane/source 命运的累加器。"""
    computed: int = 0                       # 新算（worker 实际跑了）
    cached: int = 0                         # 命中缓存直接渲染
    failed: int = 0                         # 计算抛异常
    skipped: list = field(default_factory=list)  # list[str]，每项一个跳过原因

    @property
    def rendered(self) -> int:
        return self.computed + self.cached


def summarize_compute(outcome, *, busy=False, section_label="计算"):
    """返回 (level, message) 供 toast，或 None 表示无需提示（交给 legacy 路径）。
    纯函数：给定 outcome 输出确定，无 Qt、无副作用。"""
    if busy:
        return ('info', f"{section_label}进行中，请稍候…")
    rendered, failed, skipped = outcome.rendered, outcome.failed, outcome.skipped
    if rendered == 0 and failed == 0 and not skipped:
        return None                          # 没有任何源 → 调用方走 legacy/单信号路径
    if rendered == 0:                        # 全军覆没
        if failed:
            return ('error', f"{section_label}失败：{failed} 个图计算出错")
        return ('warning', _skip_text(skipped, none_rendered=True))
    if failed == 0 and not skipped:          # 全成功
        if outcome.computed == 0:
            return ('info', f"已用缓存结果（参数未变）· {outcome.cached} 图")
        return ('success', f"{section_label}完成 · {rendered} 图")
    parts = [f"{rendered} 图已出"]           # 部分成功 + 部分跳过/失败
    if skipped:
        parts.append(_skip_text(skipped, none_rendered=False))
    if failed:
        parts.append(f"{failed} 个出错")
    return ('warning', " · ".join(parts))


def _skip_text(skipped, *, none_rendered):
    counts = Counter(skipped)
    detail = "、".join(f"{n} 个{reason}" for reason, n in counts.items())
    return f"无可计算的图：{detail}" if none_rendered else f"{len(skipped)} 图跳过（{detail}）"
```

### 反馈出口（薄 Qt 包装）

挂在主窗口（`_analysis_mixin.py`）：

```python
def _emit_compute_feedback(self, outcome, *, busy=False, section_label="计算"):
    res = summarize_compute(outcome, busy=busy, section_label=section_label)
    if res is None:
        return False                         # 调用方据此决定是否走 legacy 路径
    level, msg = res
    self.toast(msg, level)
    self.statusBar.showMessage(msg)
    return True
```

### 三个按钮的消息规范（统一）

| 分支 | level | 文案 |
|---|---|---|
| 正在计算（re-entry） | info | `时间-阶次进行中，请稍候…` / `FFT-vs-Time进行中…` |
| 全命中缓存（参数未变） | info | `已用缓存结果（参数未变）· N 图` |
| 全部新算 | success | `<section>完成 · N 图` |
| 部分跳过 | warning | `M 图已出 · K 图跳过（2 个信号过短、1 个缺转速）` |
| 全跳过 | warning | `无可计算的图：2 个信号过短、1 个缺转速` |
| 有出错 | error/warning | `<section>失败：J 个图计算出错` 或并入「部分」文案 |

跳过原因字符串约定（供 `outcome.skipped.append`）：`"信号过短"`、`"缺转速"`、
`"非均匀且未重建"`、`"样本不足"`。

### 异步路径的 outcome 生命周期

- `do_order_time` / `do_fft_time`（有 worker 队列）：
  - 进入时若 re-entry → `_emit_compute_feedback(busy=True)` 直接返回。
  - 在 pane 循环里累加 `cached` 与 `skipped`（命中/取不到源即时可知）。
  - 队列为空 → 立即 `_emit_compute_feedback(outcome)`（覆盖「全命中」「全跳过」）。
  - 队列非空 → 把 outcome 暂存 `self._order_outcome`/`self._fft_time_outcome`；每个 job
    完成回调 `computed += 1`；队列 drain 终点（`_start_next_*_job` 退出 / 末个 `_on_*_finished`）
    调 `_emit_compute_feedback`。
- `do_fft`（同步、无 worker）：pane 循环里累加 `cached`/`computed`/`failed`/`skipped`，
  循环结束统一 `_emit_compute_feedback`；保留 legacy 单信号 fallback（outcome 为空 → None → fallback）。

## 各档详细设计

### P0-1 阶次缓存键补字段

三处小改（同源同值，命中键与存储键自动一致）：

1. `contextual_order.py:get_params()`（`:534-542`）返回 dict 增加
   `rpm_factor=self.spin_rf.value()`、`fs=self.spin_fs.value()`（附加键，向后兼容）。
2. `_analysis_compute_params('order')`（`_analysis_mixin.py:382-391`）手建 dict 增加
   `'rpm_factor': p.get('rpm_factor')`、`'fs': p.get('fs')`。
3. `_order_compute_cache_params`（`_order_mixin.py:144-153`）返回 dict 增加
   `'rpm_factor': p.get('rpm_factor')`、`'fs': p.get('fs')`。

效果：改 RPM系数 → 键变 → 真重算 → 出图 + `success` toast。参数真没变时仍命中 →
`info`「已用缓存结果（参数未变）」。

### P0-2 保存图片失败弹窗

`toolbar.py:652-655` 改为检查 `pix.save()` 返回值（坏路径返 False 不抛异常）：

```python
ok = False
try:
    ok = bool(pix.save(path))
except Exception:
    ok = False
if not ok:
    QMessageBox.warning(self, "保存失败", f"无法保存图片到：\n{path}")
    return
```

注：toolbar 是 `QWidget`，`QMessageBox.warning(self, …)` 可直接用；不依赖主窗口 toast。

### P1 统一反馈（见上「反馈契约」）

落点：`compute_feedback.py`（新）、`_analysis_mixin.py`（`_emit_compute_feedback`）、
`_order_mixin.py`、`_fft_time_mixin.py`、`_fft_mixin.py`（三个 entry + 异步终点 +
per-pane skip 记原因）。

### P1 附：导出 / 通道编辑缺通道提示

- `window.py:1806-1807` 导出无数据/无勾选：`return` 前 `self.toast("没有可导出的数据或未勾选通道", "warning")`。
- `dialogs.py:341,361,375,376,409` 通道编辑器缺源/越界：`return` 前
  `QMessageBox.warning(self, "无法创建", "源通道不存在或参数越界")`（对话框语境用模态更合适）。

### P2 体验兜底

- **切片手势**（`heatmap_canvas.py:1529,1533-1539`）：结果未就绪 → 轻 toast「先点计算生成谱图」；
  点在数据范围外 → 轻 toast「点击位置超出谱图范围」。经画布的信号/回调转交主窗口 toast。
- **空图占位**（`_analysis_mixin.py:531-537`）：切 Tab 命中缺失时，画一层「点击『计算』生成」占位
  而非纯白（具体占位实现可复用现有 hint/empty-state 控件，若无则画居中提示文字）。
- **被吞异常**（`_analysis_mixin.py:466-467`、`_project_io_mixin.py:329-331`）：`pass` / 仅状态栏
  改为 `self.toast("恢复渲染失败，请手动点计算", "warning")`（不可让用户主动开项目却完全无感）。
- **保存项目成功**（`_project_io_mixin.py:225`）：补 `self.toast("已保存项目", "success")`，与导出/加载对称。
- **fft_time 去 `db_reference`（perf）**：从 `_fft_time` 键（`_fft_time_mixin.py:61`、
  `_analysis_mixin.py:378`）移除 `db_reference`。注意 `SpectrogramParams` 是 `frozen` 且
  `db_reference` 持久化在 `result.params`，改动面较大，**列为可选**，若不做不影响正确性。

## 防回归

- 在 `_order_compute_cache_params` 上方加注释规约：「凡进入 COT 计算的用户可调参数都必须在此登记」。
- 新增契约测试：构造同 `fid/ch/p`，只改 `rpm_factor`（再单独只改 `fs`），断言
  `_order_compute_cache_params` 产出的 dict 不同（从而键不同）。
- summarizer 全分支单测，锁定文案与 level。

## 验收标准

- P0-1：新缓存键单测先红后绿；改 rpm_factor 后 `do_order_time` 触发真重算（集成测试断言
  worker 被调度，而非命中缓存）。
- P0-2：保存图片在 `pix.save` 返回 False 时弹 `QMessageBox.warning`（offscreen 用 monkeypatch
  断言被调用），成功路径不弹。
- P1：`summarize_compute` 全分支单测通过；三个按钮在「全命中 / 全跳过 / 部分跳过 / re-entry」
  四态下产出预期 toast（offscreen，monkeypatch `toast` 收集调用）。
- P2：各项各自 offscreen 断言；空图占位与 toast 可见性标注「需真机复核」。
- 全量 `pytest` 绿；无新增 warning。
- 真机：改 RPM系数→出图；保存到只读路径→弹窗；阶次某图信号过短→结束有 warning toast。
