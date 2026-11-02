# ZFD 完整结构下的局部通道跳过合同补充

日期：2026-11-02

配套执行范围：[文件导入容错与异常提示 Plan](../plans/2026-11-02-import-recovery-and-diagnostics-plan.md) T5。

本补充替代 [2026-09-09 ZFD Spec](2026-09-09-zfd-long-record-robustness-spec.md) §4.4、§5 对齐/空记录、§8 A3/A7 中“结构完整但个别 type 4 通道不可用时整文件失败”的部分。原文是历史合同，其余完整性、时基、dtype、身份和长记录保护继续适用。

## 允许局部跳过的前提

所有声明记录均已按已知 type 0/4 布局完整读取，字节边界已验证；首条且唯一的 type 0 时间记录有效；至少存在一个完整、X=0、点数与时间轴一致的 type 4 测量通道。

满足前提时，下列 type 4 记录跳过并产生 `partial` 诊断：

- count=0 的空通道，完整元数据和后继记录边界已验证。
- count>0 但与时间轴点数不一致，完整声明负载已读到。
- 非零 X 引用；不推断该 X 的含义，不为其借用时间轴。

三个条件同时出现时，一条物理记录只记录一个主要跳过原因，依次优先空通道、非零 X、点数不一致。诊断保留原 record_index、offset、原名、声明点数和预期时间点数。

## 保留的硬失败

头/注释/记录头/负载截断、负 count、未知或 type 1/2/3、多个时间记录、首条不是时间记录、无效时间轴或无剩余可用测量通道仍整文件失败。即使前面已经读到正常通道，末条损坏也不提交部分组。

不得扫描 marker 抢救、截断长通道、补齐短通道、改变 dtype 或生成估算时间轴。零点 type 0 仍失败；合法单点测量继续使用元数据 dt。

## 元数据与兼容

保留现有 groups 接口、`parser_profile=zfge2-single-time-f32-v1` 和 `zfd_import.schema=1`，该 profile 仍描述可导入测量的格式。新增 `import_policy=complete-structure-local-skip-v1` 描述局部跳过策略。

- `structure_records_complete=true`：全部声明记录的已知结构与字节长度已确认；不包含尾区语义。
- `measurement_records_complete`：保守兼容标记；只有全部声明测量通道都完整导入时为 true，存在跳过时为 false。当前产品无该字段的控制逻辑消费者，旧正常文件语义不变。
- `declared_measurement_count/imported_measurement_count/skipped_measurement_count`：明确覆盖范围。
- `source_metadata.import_diagnostics`：统一的 state/issues/counts；部分导入时 state=partial，跳过项携带物理身份。保留 legacy `skipped_channels`。

其他字段包括时间轴、sample_count、parsed/declared_record_count、trailing_bytes 保持原含义；有效通道的记录序号不压缩。同名通道不靠显示名合并。整个文件结构验证完成后才创建返回 DataFrame。

## 验证

用匿名 fixture 覆盖好/坏通道前后顺序、零点/短/长/X 非零通道、全部不可用、坏通道后的真正截断、负测量 count。保留旧 32 位 count、小时级末点、t0、单点、非有限测量值和原结构拒绝测试。

定向 owner：`tests/test_zfd_format.py`；GUI、Batch 和恢复消费由配套 Plan T2/T6 验证。本补充不声称前台或 Windows frozen 验收完成。
