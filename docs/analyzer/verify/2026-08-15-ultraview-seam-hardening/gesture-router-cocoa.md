# UltraView viewport gesture router · Cocoa 验收记录

- 日期：2026-08-16
- 代码提交：`7912d8a7` (`refactor(ultraview): centralize viewport gesture routing`)
- 状态：**UNVERIFIED（本机锁屏，未进行前台 UI 操作）**

## 已完成的自动证据

offscreen 的 `tests/ui/test_ultraview_viewport_router.py` 已覆盖五个起点
（模板卡片/模板空白/自由卡片/自由空白/滚动视口）的中键和空格左键连续平移，Ctrl 与
Cmd/Meta 滚轮缩放、原生 pinch、普通左键不进入平移、文本输入焦点、CanvasHost 外控件和
hide/show 卸载重装。最终该文件结果为 **29 passed**。

连同状态 owner、视口、页面、投影/捕获、浮层几何、会话、模式、自由布局、生命周期与结构
边界的最终聚焦组合，结果为 **543 passed, 103 warnings**。警告均来自 pyqtgraph 对 NumPy
shape 设置的弃用提示；测试无失败。

## 未执行的 Cocoa 清单

桌面控制尝试在列出前台应用时返回“Mac is locked”，所以没有启动、点击或观察 TraceLab。
以下项目不能由 offscreen 结果替代：

- 指针经过卡片、空白、滚动条、rail、浮岛和已打开弹层时，中键与空格左键平移是否连续；
- Ctrl+滚轮、Cmd+滚轮和触控板 pinch 的锚点是否保持在指针下；
- 弹层/菜单点击是否仍可用，Esc 与窗口失焦是否正确取消；
- 需要留存的前台截图。

解锁后应在同一提交启动 TraceLab，按以上清单操作并补充截图、应用版本和结论。未观察到
弹层冲突，故尚不触发 spec D4 的 `grabMouse()` 回退判据。
