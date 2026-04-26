---
role: orchestrator
tags: [ui, alignment, playground, decision-velocity, brainstorming, html-mockup]
created: 2026-04-26
updated: 2026-04-26
cause: insight
supersedes: []
---

## Context

主 Claude 在 Inspector 紧凑化项目第二轮提出 6 条 UI 优化方案
(``#3 GroupBox 去边框 / #6 折叠 / #7 横坐标精简 / #8 PresetBar 单行 /
#9 rebuild icon 移位 / #10 fft_time overflow``)，每条都附了文字描述
+ 风险评估 + 推荐顺序，期望用户从中挑选。用户回复**"不同的方案我不
太理解是什么区别"**。继续用文字描述细化只会让歧义膨胀，因为这些方案
之间的差别本质是**视觉密度与交互手感**，不是逻辑差别。

## Lesson

当 UI 优化方案的差异是视觉/交互层面而非功能/逻辑层面时，**最快的对齐
方式是写一个一次性 HTML playground**（用 `playground:playground` skill），
而不是继续往返文字描述。playground 的关键要素：

1. **一比一视觉模拟** —— 用项目实际 QSS 色板（边框色 / tinted bg /
   字号 / 圆角）渲染 PyQt 控件外观，让用户看到的就是改完后的样子。
2. **toggle 控件覆盖每条方案** —— 让用户独立切换每条，看实时差异。
3. **底部 prompt 输出 + 复制按钮** —— 用户最终把"请实施 X+Y+Z"复制
   回主对话，跳过任何二次描述。

本项目用 playground 把"6 条方案要选哪几条"从可能的 N 轮文字往返
压缩到 **1 条用户消息**：复制 prompt + 3 条新观察（A/B/C）一次性给完。

## How to apply

触发条件：
- 用户对 UI 提案回复"不太理解差异"/"看不出来"/"做哪个好"等模糊表态
- 提案数量 ≥ 3 且每条都是视觉/手感差异（颜色 / 间距 / 折叠 / 按钮形态）
- 文字描述里出现 "更紧凑" / "更精致" / "更清晰" 等需要视觉确认的形容词

行动：
1. 立即调 `playground:playground` skill 写 `/tmp/<topic>-playground.html`，
   照 `templates/design-playground.md` 来。
2. 控件分两组：**已交付**（toggle 关掉看"改之前"）+ **待讨论**（每条
   独立切换）。
3. 用项目当前 QSS 色板渲染（grep `style.qss` 取主色 / tinted bg /
   border-radius），不要用 Tailwind 默认或猜的色调。
4. 底部 prompt 输出固定格式 `请实施 ... 方案：#X 描述；#Y 描述`，让
   用户的复制就是下一轮的指令。
5. `open <file>.html` 自动打开浏览器。

不适用场景：
- 改动是逻辑/算法/contract（不是视觉）—— 直接讨论比写 mockup 快。
- 改动只有 1-2 条，用户已表达明确偏好 —— playground overhead 不值。
- 项目没有现成 QSS / 设计 token 可参考 —— 视觉模拟可信度低，会误导。
