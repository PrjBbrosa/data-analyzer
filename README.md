# TraceLab / MF4 Data Analyzer

TraceLab 是用于工程测量数据浏览、时域/频域/阶次分析、批处理和采集回放的 PyQt5 桌面工具。

## 7.7 更新要点

- 导入 `.wwt`：读取原生 WinWert 测量文件，保留时间轴、单位和缩放信息。
- 导入 `.zfd`：读取 ZFGE2 / TestRunPRO 通道块；文件未提供可靠采样间隔时会明确标记估算采样率。
- 导入 `.mat`：支持 MATLAB v4-v7，并通过 HDF5 兼容 v7.3；识别显式时间变量，不猜测工程单位。
- Windows 同时提供完整包 `TraceLab7.7` 与仅分析功能的轻量包 `TraceLabAnalyzer7.7`。

## 数据导入约束

- 分隔型 ASCII 必须带可识别的时间列；固定宽度 ASCII 必须带已验证的采样间隔。软件不会猜测采样率。
- TDMS 仅导入带有效波形时基的非空数值通道；`.tdms_index` 是配套索引，不是可打开的数据文件。
- WWT 使用文件内 `Zeit` 时基；ZFD 在时基缺失时会显示估算状态；MAT 只使用可识别的显式时间变量，单位留空而不臆测。
- 批处理与图形界面使用同一套 ASCII/TDMS 导入规则。

## 文档入口

- 产品与功能文档：`docs/analyzer/`
- 7.7 发布说明：`docs/analyzer/user-guide/tracelab-v7.7-release-notes.md`
- 应用内使用说明：`mf4_analyzer/help/TraceLab-使用说明.html`
- 时域操作指南：`mf4_analyzer/help/time-domain-guide.html`
