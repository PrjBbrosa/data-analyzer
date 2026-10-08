# HEAD 风格 v1 来源

- 稳定 ID：`tracelab.head-style.v1`
- 显示名：HEAD 风格
- 等级：`screenshot_approximation`
- RGB SHA-256：`76035b39ed2f1223139896d983808146d89f21295f0db78a5c20e1057048d79d`
- 来源：用户提供的 ArtemiS SUITE 12.7 截图，文件名 `codex-clipboard-88787e19-93f4-47e7-b16e-57a15ce8e05a.png`，1920×1080。

取样使用两条横向色带顶部的无文字区域：零起始 x=74～709 与 x=784～1419，y=742～744。合并后的 636 个样本保存在 [source-rgb.csv](source-rgb.csv)，position=index/635。两条色带 RGB 平均绝对差约 0.6132/255，仅代表同截图内部取样一致性。

对合并样本做 7 像素中值去噪，再线性重采样为 256 色；不强制端点变成纯黑/纯白，不整体增亮或拉满饱和度。正式资源精确保留 [首次 HTML demo](../../ui-prototypes/2026-10-08-head-colormap-demo.html) 中 `head` 数组的全部 RGB 字节。原始采样 CSV 与 demo 中的 `raw` 数组一致；正式运行时不依赖这两份作者资料。

Qt 使用均匀的 0～1 位置建立 ColorMap，映射范围由外部色阶上下限决定。RGB 插值合同与图像最终 uint8 量化分开验证；HTML 的插值预览不等同于 Qt 最终像素结果。

本版本没有官方原始 LUT，也未与独立 HEAD 渲染样本逐像素校准。截图可能含缩放、编码和显示色彩管理影响，尤其端点与陡峭过渡。不宣称 HEAD 官方认证或精确等价。后续有更可靠参考时，保留 v1 并创建新版本，记录参考版本、范围、采样误差和匹配证据。
