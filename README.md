# TraceLab / MF4 Data Analyzer

TraceLab 是用于工程测量数据浏览、时域/频域/阶次分析、批处理和采集回放的 PyQt5 桌面工具。

## 7.6 更新要点

- 导入 `.asc`：支持常规分隔表和带稳定列布局的固定宽度 ASCII（包括带已验证采样间隔的 WinWert 类文件）。
- 导入 `.tdms`：读取 NI TDMS 的数值波形通道、工程单位和时间轴。
- 时域 View：最多可新建 12 个；窗口变窄时标签自动紧凑显示，放不下的 View 可从 `»` 菜单切换。

## 数据导入约束

- 分隔型 ASCII 必须带可识别的时间列；固定宽度 ASCII 必须带已验证的采样间隔。软件不会猜测采样率。
- TDMS 仅导入带有效波形时基的非空数值通道；`.tdms_index` 是配套索引，不是可打开的数据文件。
- 批处理与图形界面使用同一套 ASCII/TDMS 导入规则。

## 文档入口

- 产品与功能文档：`docs/analyzer/`
- 7.6 发布说明：`docs/analyzer/user-guide/tracelab-v7.6-release-notes.md`
- 应用内使用说明：`mf4_analyzer/help/TraceLab-使用说明.html`
- 时域操作指南：`mf4_analyzer/help/time-domain-guide.html`
