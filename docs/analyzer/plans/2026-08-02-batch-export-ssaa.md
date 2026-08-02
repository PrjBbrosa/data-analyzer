# 计划：批处理 PNG 导出抗锯齿（SSAA）

- 日期：2026-08-02
- **状态：已完成**（实施偏差见设计文档 §8）
- 设计文档：`docs/analyzer/specs/2026-08-02-batch-export-ssaa-design.md`（先读）
- 改动面：`mf4_analyzer/batch_render_qt/_export.py`、`_builder.py`、
  相关测试与 `tools/verify_batch_qt_render_parity.py`

## 前置

- 一律用仓库 venv：`.venv/bin/python`；Qt 用例带
  `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=.`。
- **先取基线**：`main` 上 `tests/ui/` 既有红色用例（`test_split_*`），与本
  改动无关；动手前记录本计划涉及套件的当前通过数：

  ```bash
  TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
    tests/test_batch_render_qt.py tests/test_batch_render_qt_display_envelope.py \
    tests/test_batch_qt_render_parity.py -q
  ```

- **性能基线**：改动前跑一次基准探针（附录 A），记录"A 现状"数值，验收
  gate 3 以此为参照（参考值：offscreen FHD 5 面板 60k×5 ≈ 143 ms）。

## 步骤

### 1. `_export.py`：SSAA 光栅化（核心）

按设计 §3.1/§3.2 重写 `render_scene_image`：

- 新增模块级 `supersample_factor(width_px, height_px)` 与三个常量
  （`_SSAA_MAX_FACTOR=3`、`_SSAA_MAX_SIDE_PX=32_000`、
  `_SSAA_MAX_PIXELS=160_000_000`）；
- 新增 `_cosmetic_pens_scaled(widget, factor)` 上下文管理器：覆盖
  opts-dict pens / AxisItem(setPen) / ViewBox.border，仅 cosmetic 笔，
  宽 0 视为 1.0，退出还原原 QPen 并触发 update；
- 渲染原语换成 `scene.widget.scene().render(painter, target, source)`，
  factor==1 也走同一路径；
- `setText` 元数据与 `setDotsPerMeter*` 移到最终（缩放后）图上。

`save_png` 不动。

验证：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_batch_render_qt.py tests/test_batch_qt_render_parity.py -q
```

此时 `test_batch_render_qt.py:383` 尚未改（builder 未动），应仍绿；若
`test_batch_qt_render_parity.py` 的 corner-ink 阈值（160）被 SSAA 边缘像素
打破，按实测重标定阈值并在断言旁注明原因。

### 2. `_builder.py`：AA 归一化 + 删规则

按设计 §3.3：三处 `antialias` 归一为 False / 移除参数，删除
`_native_time_antialias` 与两个 `_HIGH_RASTER_*` 常量。确认删完后
`grep -n antialias mf4_analyzer/batch_render_qt/_builder.py` 无残留。

同步更新契约（设计 §5 枚举）：

- `tests/test_batch_render_qt.py:383` → `is False`，测试名同步；
- `tests/test_batch_render_qt_display_envelope.py:172/190` → 两处断言
  `is False`，删掉针对旧规则语义的命名与注释；
- `tools/verify_batch_qt_render_parity.py:1245` → token 语义反转
  （`batch_export_antialias` 全 False，token 名改为反映新契约）。

### 3. 新增 `tests/test_batch_render_qt_ssaa.py`

设计 §7 gate 1 的五组断言：钳制表、双渲染幂等、平滑量化（monkeypatch
`supersample_factor`）、元数据存续、四 kind 的 1× 原语等价。fixture 复用
`test_batch_render_qt_display_envelope.py` 的构造方式（噪声用固定 seed 的
`default_rng`）。

### 4. 批处理域回归

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_batch_render_qt.py tests/test_batch_render_qt_ssaa.py \
  tests/test_batch_render_qt_display_envelope.py \
  tests/test_batch_qt_render_parity.py tests/test_batch_runner.py -q
```

`test_batch_runner.py` 覆盖 `batch_time_group_acceptance` 间接路径。

### 5. 性能与工具核验

- 复跑附录 A 探针：增量 ≤ +100 ms（gate 3；参考实测 3× ≈ +55 ms）。
- `tools/verify_batch_qt_render_parity.py` 跑通（gate 4）。

### 6. 真实产物目检（gate 5）

用真实 .zfd 批任务导出四类图各一张，放大检查：曲线边缘平滑无台阶、线宽
与改动前观感一致（cosmetic 补偿正确）、图例/轴/边框无变细变淡、fft_time
热力图无发糊、PNG 元数据（Title、DPI）在位。

### 7. 收尾

- 视改动 diff 决定是否补跑更大范围（`tests/integration/` 中触及批处理导
  出的用例）；全量套件按 CLAUDE.md 约定仅在收尾时跑一次。
- 提交拆两个 commit：①`_export.py` SSAA + 新测试；②builder 归一化 + 契
  约更新。任一步出问题可独立回滚。

## 回滚

改动集中在 `_export.py` 一个函数与 `_builder.py` 的删减；回滚即恢复
`widget.render` 原语与 `_native_time_antialias` 规则，无数据/配置迁移。

## 附录 A：基准探针方法

复现自根因分析（2026-08-02 会话），按需重建：

1. 合成 5 条 `BatchSeries`：`t=linspace(0,20,60000)`，
   `travel=0.065*sin(2π·0.05t)-0.012+N(0,2e-5)`（非单调 X），
   `force=-14·travel+0.25·sign(∇travel)+N(0,0.004)`；
2. `BatchTimeFigureSpec(layout="subplot", x_source="channel",
   x_origin="absolute")`，`BatchRenderOptions(1920×1080, line_width=1.5)`；
3. `build_batch_scene` → `render_scene_image` 三次取最优，offscreen；
4. 参考值（本机 2026-08-02）：AA-off 143 ms；原生 AA 2275 ms；
   2× SSAA+补偿 164 ms；3× SSAA+补偿 199 ms；1× `scene().render` 与
   `widget.render` 逐字节相同。
