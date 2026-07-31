# Repository Instructions

**Project:** MF4 Data Analyzer — PyQt5 桌面 GUI，分析 MF4 / HEAD-HDF 等测量数据
（FFT、阶次分析、滤波、加窗），含 CAN 采集。

## TraceLab 7.7 product baseline

- Import supports MF4/MDF, CSV/Excel/HDF, BLF+DBC, audio/video, generic ASCII
  (`.asc`/`.fdc`), waveform-based NI TDMS (`.tdms`), native WinWert (`.wwt`),
  ZFGE2/TestRunPRO (`.zfd`), and MATLAB (`.mat`, including v7.3 via HDF5).
- ASCII needs either a recognizable time column or verified fixed-width sampling
  metadata. TDMS needs valid waveform timing; never invent a fallback rate.
- `.tdms_index` is a TDMS sidecar, never an importable data file.
- WWT uses the file's `Zeit` axis and preserves units/scale/offset. ZFD may use
  an explicitly marked 1 kHz estimated fallback when its timing is invalid.
  MAT uses recognizable time variables only and never guesses engineering units.
- The main time-domain workspace supports up to 12 Views. At narrow widths tabs
  compact to ordinal labels, then overflow into `»`; preserve active View
  visibility, tooltip names, reordering, and context actions.

## Dev commands
```bash
pip install -r requirements.txt        # 依赖
python "MF4 Data Analyzer V1.py"       # 启动 GUI（薄启动器 → mf4_analyzer.app.main）
pytest                                  # 测试（pytest.ini 默认 -m "not slow"）
pytest -m slow                          # 仅性能/长跑用例
```

## Architecture
- `mf4_analyzer/` 主包：`app.py`(入口) · `io/` · `signal/`(数值算法) ·
  `ui/`+`ui_kit/`(PyQt 界面) · `acquisition*/`(采集) · `batch.py`。
- `tests/`（pytest / pytest-qt 自动化测试）· `scripts/`（冒烟/回归脚本）。
- `AGENTS.md` 是 **Codex 专用**，与本文件并行，勿混用。

## Gotchas
- **验真机渲染**：UI/视觉问题（尤其 macOS 原生）必须验真实渲染（截图 / objc 读原生
  属性），别凭「属性设上了 + 单测过」就判定修好。
- 嵌入浮层/菜单的自定义 `QWidget` 必须透明背景；`WA_TranslucentBackground` 会让本体
  QSS 失效 → 需 `paintEvent` 或内部子 widget 兜底。
- 若项目位于 `~/Downloads`：子进程（codex 等）跑过后触发 macOS TCC，对项目目录
  EPERM。解法：给终端 Full Disk Access，或把项目移出 Downloads。

---

# Agent squad（planner-executor 拆分）

主 Claude 是**唯一调度者**。`squad-orchestrator` 只产出计划、**不**调度专家
（Claude Code 不给子 agent `Task` 工具）。完整设计见
`docs/superpowers/specs/2026-04-22-agent-squad-design.md`；拆分原因见
`docs/lessons-learned/orchestrator/2026-04-22-task-tool-unavailable-blocks-dispatch.md`。

## Routing（强制）
用户消息含以下 token（不分大小写 / 子串 / 中英）即必须走 runbook，且**全程不得
自己写改 `.py`**，所有代码改动经专家子 agent：
`agent` · `squad` · `团队` · `分工` · `重构` · `refactor` · `多专家` · `multi-agent`

- **Opt-out**：消息以 `skip squad:` 或 `直接改：` 开头 → 直接处理（一行小修用）。
- **Out of scope（优先于触发词）**：纯 Q&A、`how`/`what` 提问（除非要改代码）、
  用户明确让你跑的 ops（`pip install` 等）。例：「该怎么重构模块 X？」是 Q&A，
  直接答、不路由。
- **漏触发**：你认为该路由却没命中关键词 → 仍路由，并在 orchestrator prompt 里
  注明漏掉的词。

## Runbook
1. **Plan** — `Task(squad-orchestrator, "mode: plan\n\nuser request:\n<原文>")`；
   解析 `decomposition[]` + `applicable_lessons[]`；`status: blocked` 则上报用户。
   （orchestrator 的 `notes` 可能要求先调某个 `superpowers:*` skill，照做。）
2. **Execute** — 按 `depends_on` 调度每个 item：
   `Task(item.expert, item.brief + 上游输出 + 引用 lessons)`。有依赖串行，无依赖
   并行（同一 message 块发）。保留各专家返回的角色字段（`ui_verified` /
   `tests_run` / `tests_before` / `tests_after` / `files_moved`）。
3. **Aggregate + rework 检测** — 汇总成最终对象（见下）。
   - **Rework**：任意有序对 `(S_i,S_j), i<j`，若 `files_changed` 交集非空且专家不同
     → S_j 返工 S_i：写 `cause: rework` lesson 到
     `docs/lessons-learned/orchestrator/`，双写 `LESSONS.md` 索引，路径计入
     `lessons_added`。
   - **Flagged**：某 `flagged.for` 专家不在任何 `depends_on` → 补派（写一条
     decomposition lesson）或上报用户。
   - **Retry cap**：同一 `(subtask, expert)` 连续两次 `blocked`/`needs_info` → 停，
     返回 `blocked` + 两次 trace。
4. **State + prune** — 读改写 `docs/lessons-learned/.state.yml`（保留全部字段）：
   `top_level_status` 为 `done`/`partial` 时 `top_level_completions += 1`
   （`blocked` 不加）。若 `top_level_completions - last_prune_at >= 20` →
   `Task(squad-orchestrator, "mode: prune")`，收 `{prune_report_path, counts}`，
   置 `last_prune_at := top_level_completions`。

最后向用户口语化汇报，并附最终 JSON：
```json
{
  "top_level_status": "done|partial|blocked",
  "done": ["..."],
  "blocked": [{"subtask": "...", "reason": "..."}],
  "flagged": [{"from": "...", "for": "...", "issue": "..."}],
  "subtasks": ["<each specialist's full return>"],
  "lessons_added": ["..."],
  "lessons_merged": ["..."],
  "prune_report_path": null
}
```
