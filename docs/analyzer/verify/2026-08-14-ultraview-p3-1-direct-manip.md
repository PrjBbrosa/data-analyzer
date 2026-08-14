# UltraView P3-1 直接操纵验收

- 日期：2026-08-14
- 分支：`codex/ultraview-p1-p2`
- Spec：`docs/analyzer/specs/2026-08-14-ultraview-p3-canvas-interaction-spec.md`
- Plan：`docs/analyzer/plans/2026-08-14-ultraview-p3-canvas-interaction-implementation.md` Task 6

## 已用 offscreen 钉住的行为

UV-P3-A01 / A02 / A03 / A04 / A05 / A13 / A14 / A15：真实鼠标事件驱动的移动、
resize、框选与组平移、替换环、扩容回填、digest characterization、hints/quickref/帮助
无「Alt+拖」残留。跑的是仓库 venv + `QT_QPA_PLATFORM=offscreen`。

## 真机 Cocoa

操作者于 2026-08-14 在前景 TraceLab 确认下列项可用。本记录不编造帧时数字。

| 项 | 结果 |
|---|---|
| 拖动跟手性 | **OK**（操作者确认） |
| ghost 无残影 | **OK**（操作者确认） |
| handle 命中与光标 | **OK**（操作者确认） |
| 框选 / 组移动手感 | **OK**（操作者确认） |
| 替换环悬停 | **OK**（操作者确认） |

## 里程碑

**P3-1 完成**（offscreen 契约 + 操作者 Cocoa 确认）。P3-2 见
`docs/analyzer/verify/2026-08-14-ultraview-zoom-spike.md`。
