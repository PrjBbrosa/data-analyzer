# WinWert 导出资源

两个文件对应 `mf4_analyzer.io.wwt_export` 的两条路。机制与实测台账见
`docs/analyzer/specs/2026-08-11-wwt-export-dual-compat-spec.md`。

## `winwert_display_trailer.bin`（clean-room 路径，默认）

真实的 `DatenFenste2` 显示块，32 KB。导出时由
`wwt_display.rebuild_display_trailer` 按目标通道重建曲线表，接到自写的正文
（`Zeit` + N×`Real` float64）后面——点数原生保留、通道数不限、零量化。

来源：**WinWert 自己写的文件**（用户用 WinWert 直接把 `.mat` 导成 `.wwt`）。
抽取时已清空源文件的会话文本（页脚注释 / 标题 / 注释 / 署名），资源本身不带
任何客户的台架编号、试验规范或操作员姓名；`test_wwt_display.py::
test_bundled_trailer_asset_carries_no_session_text` 看守这一点。

重新生成：`PYTHONPATH=. .venv/bin/python tools/make_wwt_display_trailer.py`

## `winwert_export_template.wwt`（模板路径，回退）

完整的真实 WinWert 骨架，`wwt_inplace.convert_to_wwt` 把序列重采样进它的
6 个测量槽位（9936 点）。来源样本 `testdoc/wwt/Servo drive stiffness_000089.wwt`。
这条路的 WinWert 显示已由人工开箱验证，作为 clean-room 的回退保留。

## 不要做的事

- 不要换成从零合成的骨架：WinWert 拒开（2026-08-11 实测）。
- 极简（256 B）尾块下记录头的 `xkanalnr` 必须非 0，否则同样被拒——
  详见 `wwt_writer.write_wwt` 的说明。
