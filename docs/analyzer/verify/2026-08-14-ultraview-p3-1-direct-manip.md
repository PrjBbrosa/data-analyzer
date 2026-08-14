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

| 项 | 结果 |
|---|---|
| 拖动跟手性 | **UNVERIFIED** |
| ghost 无残影 | **UNVERIFIED** |
| handle 命中与光标 | **UNVERIFIED** |
| 框选 / 组移动手感 | **UNVERIFIED** |
| 替换环悬停 | **UNVERIFIED** |

offscreen 只能当排版草稿，量不出 paint 成本，也不能写成视觉验收通过。

## 里程碑

**P3-1 不得声明完成**，直到本机不用 offscreen 的前景 TraceLab 补上上表读数。

P3-2 仍因 `docs/analyzer/verify/2026-08-14-ultraview-zoom-spike.md` 暂停。
