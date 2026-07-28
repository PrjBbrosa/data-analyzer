# 批处理 Phase 3：导出质量与运行运维 Spec

- 日期：2026-07-28
- 状态：已实施；O1–O8、O10 PASS，O9 PARTIAL（见第 12 节）
- 前置门：Phase 1 C1–C10、Phase 2 P1–P10 全 PASS

## 1. Outcome

本阶段把“能批量算”提升为“可交付、可追溯、可恢复”：用户可以得到真正的 1080p/2K/4K PNG 或 SVG/PDF 矢量图；每次 run 都有 manifest 说明用了什么来源和有效参数；文件冲突、取消、失败和续跑具有明确策略。

## 2. Output schema

`BatchOutput` 以向后兼容方式扩展：

```python
BatchOutput(
    export_data=True,
    export_image=True,
    data_format="csv",
    image_format="png",          # png | svg | pdf
    image_size="1920x1080",      # preset key | custom
    image_width=1920,
    image_height=1080,
    image_dpi=144,
    conflict_policy="auto_number",  # error | skip | overwrite | auto_number
    write_manifest=True,
    resume_policy="none",        # none | manifest
)
```

- 旧 preset 没有这些字段时迁移到兼容默认；不能因 dataclass 新字段破坏 JSON 读取。
- DPI 是 raster metadata/排版参数，像素尺寸仍由 width×height 明确定义；不能把“100 DPI”当作分辨率。
- custom width/height 有合理边界（建议 320–16384 px）和总像素保护，防止意外内存爆炸。

## 3. Raster and vector rendering

### 3.1 Required sizes

- 1920×1080（Full HD，默认）
- 2560×1440（QHD/2K）
- 3840×2160（4K UHD）
- Custom width×height

PNG 测试必须实际解码并断言像素宽高，不只断言文件存在。

### 3.2 Vector formats

- SVG：文字与曲线/heatmap 容器可被标准解析器打开；不是把 PNG base64 包在 SVG 外壳内。热图本身允许作为 raster image 嵌入，但轴、文字和线条保持矢量。
- PDF：至少一页，MediaBox/页面尺寸与设定 aspect 对应，字体/轴标签可读。
- renderer 仍为 GUI-free；QThread 内不创建 Qt GUI 对象。

### 3.3 Figure content

默认图必须包含：

- title：source display name、group（如有）、channel、method；
- axes：物理量/单位、Time/Frequency/Order；
- legend：Time original/filtered 或多 series；
- spectral facts：window、effective NFFT、weighting、averaging/overlap；
- dB：shared formatter 生成的 `dB/dBA re ...`；Linear 不显示 reference；
- footer/subtitle：recipe hash8 或 task id，便于对应 manifest。

长文本采用受控换行/省略并把完整值写入 manifest，不允许标题把绘图区挤为零。

## 4. Conflict policies

- `error`：任一目标 final path 已存在则该 task preflight failed，不写任何 artifact。
- `skip`：已存在 artifact 标为 skipped；只有 manifest 证明其属于同一 task/recipe 时才可视为可恢复完成，否则 warning。
- `overwrite`：仅在用户明确选择时原子替换；原文件直到新文件完整生成前保持可恢复。
- `auto_number`（默认）：生成 `__2`、`__3` 等不冲突 final path；data/image/manifest entry 必须使用同一 resolved suffix。

冲突检查与实际 replace 之间仍可能竞争；实现需用安全 reservation/重试，不能只做一次 `exists()` 后假定路径仍空闲。

## 5. Manifest

每次 run 在输出目录写 UTF-8 JSON：

```text
batch-manifest__{run_id}.json
```

顶层至少包含：

- `schema_version`、`run_id`、`created_at`、`app_version`；
- preset 名、normalized recipe、recipe fingerprint；
- requested output settings；
- summary counts：done/failed/cancelled/skipped/resumed；
- run status 和 blocked reasons。

每个 task entry 至少包含：

- `task_id`、source_id/path/group/display name、channel/unit、method；
- requested params 与 effective facts：actual Fs、effective NFFT/window length、weighting、dB mode/value/source、filter requested/effective/clamp warning、RPM mode/source；
- status、message/warnings、started/finished time；
- data/image final paths、格式、像素尺寸/DPI；
- 成功 artifact 的 size 与 checksum（建议 SHA-256）。

manifest 自身也原子写。运行中可写 `.partial` journal；只有 run terminal 后生成/替换 final manifest。

## 6. Resume and retry

### 6.1 Manifest-proven resume

“恢复上次运行”必须选择或自动匹配 manifest，并同时满足：

- recipe fingerprint 相同；
- task_id 相同；
- source identity 相同；可用时校验 source size/mtime 或内容 fingerprint；
- manifest 中 artifact checksum/size 与磁盘一致。

满足条件的 done task 标为 `resumed`，不重新计算；缺失/损坏/身份变化的 task 重新运行。仅凭同名文件存在不得跳过。

### 6.2 Retry failed

“仅重试失败”以最近一次 run/manifest 中 `failed`、`cancelled` 为 task scope；done/resumed/skipped 不重跑。若 recipe 被修改，UI 必须提示这是新 run，不能把旧失败集合无条件套到新 recipe。

### 6.3 Crash/cancel

- cancel 后当前未完成 artifact 不成为 final-looking 文件；manifest summary 为 cancelled/partial。
- worker unexpected exception 仍写 terminal manifest（若 output dir 可写）并保留已完成 task 事实。
- 恢复操作不要求完整加载所有历史数据到内存。

## 7. Operations UI

OUTPUT 区增加：

- Image format：PNG / SVG / PDF；
- Size preset：1080p / 2K / 4K / Custom；
- Custom width/height；PNG DPI；
- Conflict policy；
- “写入运行清单”开关（默认开）；
- “恢复上次运行…”、“仅重试失败”操作。

运行前预览至少显示：目标 task 数、预计 artifact 数、输出格式/尺寸、冲突策略和已有冲突数量。估算磁盘占用必须标“估算”，不能作为精确保证。

Task list 状态扩展为 done / failed / cancelled / skipped / resumed，并可打开 final artifact 所在位置；该外部打开动作只发生在用户点击后。

## 8. Performance boundaries

- 保持 file-major lazy load、单磁盘来源 cache 驱逐和 image-only matrix-first 路径。
- 4K 图只在 render 阶段分配必要 buffer；不得同时保留多份同尺寸 RGBA 副本。
- SVG/PDF 按 task 流式写，不在内存积累整个 run。
- checksum 流式读取文件；可取消，并在 manifest 中记录未完成 checksum。
- 本阶段仍不并行 compute。并行化需单独性能 spec，以内存预算和可取消性为前置。

## 9. Non-goals

- 不自动上传、发邮件或发布外部系统。
- 不承诺所有字体在不同 OS 完全一致；必须保证中文/英文 fallback 可读。
- 不把 manifest 当作项目文件或长期数据库。
- 不做任意目录递归监控；文件夹批量加入可作为后续小功能，不能阻塞本阶段核心验收。

## 10. Acceptance Criteria

| ID | 验收 |
| --- | --- |
| O1 | PNG 1080p/2K/4K/custom 实际解码尺寸精确，DPI metadata 可读 |
| O2 | SVG/PDF 可由解析器打开，文字/轴存在，SVG 不是纯 PNG wrapper |
| O3 | title/axis/legend/analysis facts/dB label 与 task/recipe 一致 |
| O4 | 四种 conflict policy 行为确定；默认不静默覆盖 |
| O5 | data/image 同一 task 使用协调后的路径后缀；异常无 final 半文件 |
| O6 | terminal manifest schema 完整，summary 与 task entries 一致，checksum 匹配 |
| O7 | manifest-proven resume 只跳过 identity/fingerprint/checksum 均匹配的 done task |
| O8 | retry failed 只运行 failed/cancelled；recipe 变化不会冒充旧 run |
| O9 | cancel/crash 后可从 partial/terminal 事实恢复，UI 解锁且状态不误报 done |
| O10 | 4K/image-only/multi-source run 保持惰性加载与 bounded intermediate allocations |

## 11. Verification

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/test_batch_runner.py \
  tests/test_batch_preset_io.py \
  tests/test_batch_renderer.py \
  tests/test_batch_manifest.py \
  tests/ui/test_batch_output_panel.py \
  tests/ui/test_batch_runner_thread.py \
  tests/ui/test_batch_task_list.py \
  tests/ui/test_batch_smoke.py
```

此外生成一组 1080p PNG、4K PNG、SVG、PDF 与 manifest 实物，分别用图像/PDF/SVG parser 检查；offscreen 只证明结构与渲染，不替代 macOS 前台清晰度与布局验收。

## 12. Implementation Result — 2026-07-28

实现已覆盖高清/矢量导出、严格 manifest、四种冲突策略、manifest-proven resume、失败重试和完整 OUTPUT UI。macOS Cocoa 前台 Retina 截图与 PNG/SVG/PDF 独立解析证据均已完成，证据目录为 `.state/batch-export-proof/`。

| ID | 结果 | 说明 |
| --- | --- | --- |
| O1–O8 | PASS | 精确尺寸/DPI、矢量内容、facts、冲突/原子性、manifest、resume/retry 均有自动化与实物证据 |
| O9 | PARTIAL | 正常取消、writer exception、terminal/partial manifest 与 UI 解锁通过；真实进程被强制终止后遗留的 reservation 仅提供 `inspect_output_reservation` 与显式安全释放，不按 TTL/PID 自动回收，以免误删仍存活进程或外部替换的产物 |
| O10 | PASS | 单来源惰性缓存、image-only matrix-first、data+image 在 4K render 前释放 long table；4K probe max RSS 351,305,728 bytes |

最终 focused 证据：core/source/renderer `328 passed`，Batch UI `145 passed`，P0/P1 review regressions `15 passed`。另有 3 个旧 `test_head_hdf_rail.py` 失败来自未调用 `set_attached_file_ids()` 的陈旧测试契约；相关生产文件与测试文件均未在本任务修改，单独列为既有测试债务，不计为本阶段回归。
