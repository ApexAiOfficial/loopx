# L7：整 Goal 迁移前的原生 drain 决策

本阶段删除 Python drainer 对已证明历史的第二次解释，并修复游标副作用之前的
字节变化识别。它服务于既有整 Goal 路径：捕获旧写入、排空候选、验证精确谱系、
围住旧 writer、迁移已审阅快照、核对 canonical 消费端。
恢复已提交事务不能变成再次写入，也不等于获得 provider 晋升批准。

配套 [TS 检查点](../typescript-control-plane-migration-v0/2026-09-23-shadow-drain-planning.zh-CN.md)
记录规则归属、锁顺序及传输限制。真实 CLI 崩溃恢复使用完整源人口的可丢弃副本，
另行核对 File／SQLite canonical 读回。验证不晋升活跃 Goal、不改它的 writer fence
或 registry，也不能替代经过审阅的 cohort 迁移、持续混合写资格或 SQLite D2。

剩余 **5–8 个完整 PR 包**仍是条件估算：

| 交付包 | 数量 | 尚需可观察结果 |
| --- | --- | --- |
| L2/L3 调用方接入与执行围栏 | 1–2 | 所有已发布调用方使用合格所有者，拒绝陈旧 writer。 |
| L5/D1 消费与投影闭环 | 1 | CLI、打包客户端及投影一致消费 canonical 状态。 |
| L6 SQLite D2 | 1–2 | 既有贡献者负责的容量、崩溃、恢复及真实经过时间的持续验证。 |
| L7 连续性与 L8 整 Goal 迁移 | 1–2 | 混合 writer 连续性、审阅后的 cohort 迁移及带围栏导出／回滚。 |
| L9 默认值与有限 Python 退役 | 1 | 新 Goal 默认、接入流程、兼容指引，以及最后调用方迁走后删除旧 writer。 |

本 PR 推进 L7，并实际退役一组 Python 规则，但不因此把完整交付包机械减一。
SQLite 至少十天的 soak 需要真实经过时间，不能用更多合成事务替代。
PostgreSQL 仍有独立的服务、凭据、租户及运行资格路径；provider 无关的晋升与
canonical 读取合同可复用。
