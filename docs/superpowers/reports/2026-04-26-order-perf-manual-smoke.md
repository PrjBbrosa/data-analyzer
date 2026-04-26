# Order Perf 手动烟雾测试清单

数据集：`testdoc/` 下任意 ≥ 60 s 的 MF4。

## A. 行为烟雾

- [ ] 切到 order 模式
- [ ] 选信号 + RPM 通道，按「时间-阶次谱」
- [ ] 计算期间窗体不冻结：尝试切到 time / fft 模式 → 应正常切换
- [ ] 计算期间按「取消计算」→ statusBar 显示「阶次计算已取消」
- [ ] 计算完成后，pan/zoom order 谱：视觉无卡顿（30+ fps 主观感受）
- [ ] 切「转速-阶次谱」按钮再算一次：复用 axes，不闪
- [ ] 切「阶次跟踪」按钮：下半幅 RPM 拖动无卡顿
- [ ] 关闭主窗口（计算未结束时）：无 QThread destroyed warning
- [ ] open 批处理 → 把刚才的 order_time 当 preset 跑：导出图视觉与画布一致

## B. Gouraud vs Bilinear 视觉对比（codex round-1 F21）

在切到 imshow 之前，跑一次 order_time，截图保存为 `gouraud-baseline.png`。
切完后，用同样数据集 / 同样参数再跑一次，截图保存为 `bilinear-current.png`。

- [ ] 两张图横向并排放，肉眼对比
- [ ] 色阶位置一致，无明显平移
- [ ] 高峰位置不模糊化（bilinear 不应让窄峰变宽）
- [ ] 低幅区域不出现 banding
- [ ] 用户签字接受（report 末尾追加签字栏）

## C. Batch 200 文件内存观察（codex round-2 G24 / D15 → manual）

plan 内的 `tracemalloc` 测试（T1 Step 19-20）只覆盖 single-compute chunk 上界，
不能等同于 batch 200 文件 + image export。本节用真实 batch 跑一次：

- [ ] `testdoc/` 准备 200 个小 MF4（或同一文件复制 200 份）
- [ ] 启动 `python -m memory_profiler MF4\ Data\ Analyzer\ V1.py`（或 `psutil` snapshot）
- [ ] 加载文件 → 选信号 + RPM → 跑「时间-阶次谱」一次 → 触发批处理（free_config + order_time + image=on）
- [ ] 记录峰值 RSS 增量
- [ ] 验收：增量 < 200 MB；超阈值则在 spec §11 deferred 中开"batch 内存优化"条目

## 用户签字栏

| 项 | 签字 | 日期 |
|---|---|---|
| §A 行为烟雾全部通过 | | |
| §B Gouraud vs Bilinear 视觉接受 | | |
| §C Batch 200 文件内存增量 < 200 MB | | |
