# TraceLab 8.4.6 版本同步验收

日期：2026-11-03。基础提交：`2e81d2e5`。本次只同步版本与发布说明，不新增计算或导入行为。

- `APP_VERSION` 更新为 `v8.4.6`，窗口标题继续由它派生。
- README、当前产品基线、主帮助页、六份模块指南、用户指南、Windows Full/Lite/Modular 构建默认值与启动脚本同步；历史版本条目保持原日期和编号。
- 发布说明覆盖已提交的导入容错、可见诊断、原始缺口保留、分析状态和固定游标生命周期修复。
- 原有未提交的 8.4.5 发布草稿、Nm 基准、Windows Lite 构建逻辑及其他工作区修改仍保留，未混入本次提交。

## 检查结果

从暂存树导出独立副本，使用项目虚拟环境运行：

```text
tests/test_help_content.py
tests/test_windows_build_script.py
tests/test_packaging_imports.py
tests/ui/test_project_session.py
154 passed, 12 skipped, 194 warnings in 25.58s — exit 0
```

版本旧值搜索仅留下历史条目；`git diff --cached --check` 通过。Chrome headless 实际渲染主帮助页的更新历史，8.4.6、日期及四条更新均完整可读，无新增条目裁切。日志、JUnit、截图及暂存树标识保存在 `.state/release-8.4.6/`。

本次未重跑完整主套件。前一轮完整门禁及最后七项修复的定向验收见[回归验收记录](2026-11-03-regression-recovery-verification.md)，不将其表述为最终全套绿色。未重启用户当前 TraceLab 实例，未生成或验收 Windows Full/Lite frozen 程序；本次版本提交不等同于安装包发布。
