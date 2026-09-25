# HEAD HDF 时间基准事实

日期：2026-09-25。官方软件对照：**未完成**。下面的采样率是已落地规则对文件头的结果，不是 HEAD Companion / ArtemiS 验收。

## 已读头部

| 文件 | SHA-256 | scan mode | 槽数 | delta | scan 数 | 规则结果 |
| --- | --- | --- | --- | --- | --- | --- |
| `20260924_LS6_直驱#1 gear_running_outdoor.hdf` | `26f46c89cef10ce9514e7d5e11d14738db19b386e0c98bf70bc079215e965f22` | simultaneous | 12，全部 factor=1，FLOAT32 | `4.16666666666667e-5` s | 1,732,800 | dt = delta，24 kHz，覆盖时长 72.2 s。数据区 83,174,400 字节，无尾部 |
| `260417-ripple-PK2C-电机加热-1.hdf` | `2b99856e1c8b636e604c70416287c9b7b6ea3fcc03626e8ed8b9dba5b4ea4af6` | synchronised multiple | 259，含 1 个 UINT32 | `3.86100386100386e-6` s | 49,500 | scan 周期 1 ms；24 kHz 与 1 kHz，覆盖时长 49.5 s。尾部是 `; xmlAppendix_utf16` |

两份文件都是 version 4 / release 6 / Intel / Time data / `idx order: 1` / `data org: a1b1 a2b2` / 单一线性秒轴。

## 发布验收还缺什么

- HEAD Companion 或 ArtemiS 上的逐通道 fs、样本数和起止时间，以及软件版本。
- 一份真实 FLOAT32 48 kHz + 24 kHz + CAN 混合文件。factor=48 的 UINT32 槽还不是这条证据。
- 在记录 `official_software` 与 `official_evidence_sha256` 之前，manifest 里的 `official_time_basis` 保持 `pending`。
