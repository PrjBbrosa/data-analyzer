# 可行性报告:系统关联 .mf4 / 新增 mdf 支持 / 资源管理器列显示备注

- 日期:2026-06-12
- 状态:仅调查与方案,**未实施任何代码改动**
- 分发形态:PyInstaller `--onedir` → `dist\TraceLab6.5\TraceLab6.5.exe`(Windows)
- 解析库:`asammdf` 的 `MDF()`

---

## 贯穿性前提:程序当前不接收命令行文件路径

`mf4_analyzer/app.py:79` 的 `QApplication(sys.argv)` 只用于 Qt 解析样式参数,**没有任何地方读 `sys.argv[1]` 去加载文件**。因此即便系统关联做好,双击 .mf4 也只会拉起空界面。这是"系统关联"功能的硬前提改动。

---

## 问题一:关联系统 .mf4 打开(不要管理员权限)

**结论:可行,且无需管理员权限。** 需两块改动配合。

### ① 注册表关联(无需管理员)
写在「当前用户级」`HKEY_CURRENT_USER\Software\Classes`,普通权限即可,不碰 `HKLM`/`HKEY_CLASSES_ROOT`。三处:
- `HKCU\Software\Classes\.mf4` → ProgID(如 `TraceLab.mf4`)
- `HKCU\Software\Classes\TraceLab.mf4\shell\open\command` → `"C:\...\TraceLab6.5.exe" "%1"`
- `DefaultIcon` → 复用已有 `assets/icons/tracelab.ico`,资源管理器即显示自定义图标

> 注意:Win10/11 有 UserChoice 保护。首次双击系统可能弹「你要如何打开」让用户选一次本程序,选完固定。系统行为,无法绕过,不影响功能。

### ② 程序接收文件路径参数(必须改代码)
入口解析 `sys.argv`,拿到 `%1` 路径后走现有 `_load_one()` 流程。建议同时加**单实例**(QLocalServer / QtSingleApplication):程序已开着时再双击文件,转发路径给已有窗口,而非开第二个进程。

### ③ 注册时机
- 首次运行时程序自己用纯 Python `winreg` 写 HKCU(最省事,无需管理员);或
- 打包流程附「关联 / 取消关联」开关

---

## 问题二:新增 mdf 格式支持

**结论:顺手,风险很低。** `asammdf` 的 `MDF()` 本就同时支持 MDF v3(.mdf/.dat)与 MDF v4(.mf4),底层不用改。当前问题只是派发逻辑漏掉了 .mdf。

需改两处:
1. `mf4_analyzer/ui/main_window.py:1759-1760` QFileDialog 过滤器加 `*.mdf`(以及待定的 `*.dat`)
2. `mf4_analyzer/ui/main_window.py:1846` 扩展名分支:把 `.mdf`/`.dat` 并入 `.mf4` 的 `DataLoader.load_mf4()` 分支(现状 `else` 会把 .mdf 误当 CSV 解析而失败)

`mf4_analyzer/io/loader.py` 的 `load_mf4()` 基本不动。`.dat` 扩展名有歧义(部分是纯文本),是否纳入待定。

---

## 问题三:资源管理器的列显示 mf4 内部备注

**结论:在"不要管理员权限"前提下做不到。** 系统架构硬约束,非工作量问题。

- 备注存在 mf4 文件内部(MDF header comment,`mdf.header.comment`)。当前 `load_mf4()` **根本没读这个字段**。
- 要让资源管理器某列显示文件内部备注,唯一正路是注册 **Property Handler 外壳扩展**(原生 C++/COM DLL),解析 mf4 并映射成 `System.Comment`。
- 该 Handler 注册键 `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\PropertySystem\PropertyHandlers` 是**机器级、必须管理员**,无 HKCU 旁路。
- 纯 Python / PyInstaller 做不出原生组件;XP 时代写入 NTFS 数据流的旧法 Vista 后已移除。

**取舍:二选一**——要么接受"管理员权限 + 原生扩展",要么放弃"资源管理器列",改为**在 TraceLab 程序内显示备注**(读 `header.comment`,放标题栏/信息面板/标签 tooltip,纯 Python,投入产出比远胜原生扩展)。

> 公共前置:无论哪种"显示备注"方案,第一步都是先在 `loader.py` 读出 `header.comment`,零风险。

---

## 整体优先级建议

| 事项 | 可行性 | 需管理员 | 改动量 | 建议 |
|---|---|---|---|---|
| 二、加 mdf 支持 | 可行 | 否 | 极小(2 处) | 先做 |
| 一、关联系统 .mf4 | 可行 | 否(HKCU) | 中(argv+单实例+注册) | 再做 |
| 三、资源管理器列显示备注 | 受限 | 是(原生扩展) | 大(另起 C++ 项目) | 放弃列方案,改程序内显示 |

---

## 关键文件索引

| 项 | 路径 | 行号 |
|---|---|---|
| 入口(未读 argv) | `mf4_analyzer/app.py` | 79 |
| MF4 库导入 | `mf4_analyzer/io/loader.py` | 8-12 |
| QFileDialog 过滤器 | `mf4_analyzer/ui/main_window.py` | 1759-1760, 1804 |
| 扩展名判断 | `mf4_analyzer/ui/main_window.py` | 1846-1854 |
| MF4 加载实现(未读 comment) | `mf4_analyzer/io/loader.py` | 114-164 |
| PyInstaller 配置 | `build/spec/MF4DataAnalyzer.spec` | 全文 |
| 构建脚本 | `tools/build_windows_folder.ps1` | 全文 |
| 图标资源 | `assets/icons/tracelab.ico` | — |
