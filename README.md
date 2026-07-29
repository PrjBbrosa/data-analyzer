# TraceLab / MF4 Data Analyzer

TraceLab 是用于工程测量数据浏览、时域/频域/阶次分析、批处理和采集回放的 PyQt5 桌面工具。

## 7.9 当前版本

- 精密触控板的 Ctrl / Shift 缩放在时域、FFT、FFT 预览、时频图、阶次和切片视图中统一支持双向缩放；叠加模式下 Shift 缩放 Y 轴可以正常放大和缩小。
- 时域交互的粗刷新间隔限制为 100 ms，密集叠加曲线会根据绘制压力自动控制抗锯齿，拖动与缩放更稳定。
- 通道配置管理器升级为草稿编辑：可预览当前 View 的通道匹配和单位，支持新建、复制、重命名、单项/批量删除与撤销；只有“保存更改”才写入本机配置。
- 通道配置可导入/导出 JSON；同名配置导入时可选择保留、替换或跳过，旧配置仍可继续读取。
- 导入 `.wwt`：读取原生 WinWert 测量文件，保留时间轴、单位和缩放信息。
- 导入 `.zfd`：读取 ZFGE2 / TestRunPRO 通道块；文件未提供可靠采样间隔时会明确标记估算采样率。
- 导入 `.mat`：支持 MATLAB v4-v7，并通过 HDF5 兼容 v7.3；识别显式时间变量，不猜测工程单位。
- Windows 同时提供完整包 `TraceLab7.9` 与仅分析功能的轻量包 `TraceLabAnalyzer7.9`。

## 数据导入约束

- 分隔型 ASCII 必须带可识别的时间列；固定宽度 ASCII 必须带已验证的采样间隔。软件不会猜测采样率。
- TDMS 仅导入带有效波形时基的非空数值通道；`.tdms_index` 是配套索引，不是可打开的数据文件。
- WWT 使用文件内 `Zeit` 时基；ZFD 在时基缺失时会显示估算状态；MAT 只使用可识别的显式时间变量，单位留空而不臆测。
- 批处理与图形界面使用同一套 ASCII/TDMS 导入规则。

## 文档入口

- 产品与功能文档：`docs/analyzer/`
- 7.7 发布说明（归档）：`docs/analyzer/user-guide/tracelab-v7.7-release-notes.md`
- 应用内使用说明：`mf4_analyzer/help/TraceLab-使用说明.html`
- 时域操作指南：`mf4_analyzer/help/time-domain-guide.html`
