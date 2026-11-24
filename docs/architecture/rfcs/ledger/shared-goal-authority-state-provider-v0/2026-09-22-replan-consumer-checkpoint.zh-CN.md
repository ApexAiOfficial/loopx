# Replan 消费侧检查点与默认路径估算

历史 replan 决策族已由旧路径与 canonical 消费侧共享 TS 规则；四项语义修复与
隔离真实读后核对见 [TS 检查点](../typescript-control-plane-migration-v0/2026-09-22-replan-history-policy.zh-CN.md)。
这推进 T3，不新增 provider 持久性、完整捕获或晋升资格声明。

仍估计需要 **5–8 个完整交付包**：剩余 caller/executor fence 1–2、消费侧和投影
恢复 1、SQLite 持久性资格 1–2、整 Goal 捕获及迁移 1–2、默认 onboarding 和受控
删除 1。相关类别可以在一个完整包中重叠，不能把各自最大值当作独立承诺相加。
本次历史触发 slice 没有独自清空其中一个完整包；SQLite 长程资格原有负责人
（#4224）及实际 soak 时间仍是依赖，不能用 PR 数量抵扣。

完整捕获还遇到归档依赖 role/class 不完整的门禁。活动读模型一致不能消除这个
阻塞。既有 Goal 迁移仍需精确源资格、旧 writer fence 及回滚验收；本次没有晋升
活动 Goal。PostgreSQL 继续独立资格化并显式选择，本次不修改其事务、连接、
选择、数据库 schema 或迁移合同。
