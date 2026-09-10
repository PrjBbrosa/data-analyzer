# ZFD 真实样本 corpus

本目录只提交受控 manifest，不提交客户或大二进制 `.zfd`。

## 许可边界

登记的六份文件是实验室/客户测量记录，**不可再分发**，也**不得检入本仓库**。`testdoc/` 被 gitignore。不要把本机 `.state/zfd-robustness/samples.json` 复制成无来源事实，也不要用合成长记录冒充遗失的原始客户小时级文件。

支持 profile 仍是 `zfge2-single-time-f32-v1`。本 manifest 不扩大产品支持范围。

## 环境变量

由 `tests/zfd_corpus.py` 读取，不进仓库根 `conftest.py`：

| 变量 | 含义 |
| --- | --- |
| `TRACELAB_ZFD_CORPUS_ROOT` | 样本根目录。其下必须能用 manifest 的相对路径找到文件。 |
| `TRACELAB_REQUIRE_ZFD_CORPUS=1` | 必需模式。缺 root、缺文件、hash 不符一律 fail，不能 skip 成功。 |

普通开发套件不设这两项：真实样本 case skip，合成与解析边界仍跑。

若本机已有历史 `testdoc` 布局：

```bash
export TRACELAB_ZFD_CORPUS_ROOT="/path/to/testdoc"
```

相对路径：

- `RWS/Axial_000031.zfd` … `RWS/Axial_000035.zfd`
- `wwt/end of travel_1.zfd`

## Manifest 字段

每条样本有稳定 ID、相对路径、SHA-256、profile、期望来源/通道/单位/点数、时间与值证据。值证据是 little-endian float32 解码为 float64 后的受控锚点（首/次/中/末/最小/最大），用来证明 parser 数值，而不是两个消费者互相比较。

原始约一小时客户文件仍缺失时，验收保持 UNKNOWN。
