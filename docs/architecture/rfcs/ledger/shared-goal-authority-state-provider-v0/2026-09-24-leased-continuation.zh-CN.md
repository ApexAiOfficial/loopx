# 显式带租约接力：补齐 canonical CLI 的实际调用路径

对应 #4574 G1/G2 和 shared authority L2/L3。原 handoff caller 拒绝所有
hard-lease Todo，虽然 metadata update 和原子 claim/lease transfer 已具备执行
证明；prepare/adopt 已提交的结果也没有主动投递 Markdown。

本次复用已有所有者：源 Agent 凭当前证明准备上下文，原子转移 claim 与 lease，
接收 Agent 凭新证明接收上下文。transfer 只重绑定转移前仍有效的 note；adopt
记录上下文接收回执，不改变 claim/lease。回执重试仍需验证当前执行权和验收条件。
Python 保留宿主 IO、投影投递；上下文闭合 schema、claim/lease 规则由 TS 所有。
无租约路径保持兼容，不新增 capability 或第二套所有权协议。

[操作合同](../../cross-session-memory-substrate-v0.zh-CN.md#带租约的接力与显示恢复)
覆盖参数、重试和读回。这是已有 CLI 工作流，不涉及新 UI 控件；原 Todo 显示
消费者继续读取同一记录 schema。自动派工、启动宿主、独立结果验收和外部 effect
fencing 仍由相应边界负责，不据此宣布 manager handoff RFC 完成。

## 距离本地默认的交付节奏

仍按条件化的 **5–8 个完整交付包** 规划，并集成已有在审前置 PR。本次关闭
L2/L3 的一个实际调用路径及其显示缺口，不能扣掉整个 L2/L3 或 L5 包。
SQLite 是长期本地默认候选，File 是参考/显式选择；新 Goal 默认、已有 Goal
迁移与删除全部 Python 是三个不同结果。

| 交付包 | 估计 | 完成标准 |
| --- | --- | --- |
| 剩余 CLI/Turn/Chat 调用方及真实 effect | 1–2 | 闭合命令矩阵、当前执行证明和外部 effect 边界；最后调用方迁移后删除对应 Python 业务规则。 |
| 消费者与永久投影集成 | 1 | 全量读回、分页、显示恢复与受影响的打包入口通过；旧/缺失 Markdown 不成为权威。 |
| SQLite D2，沿用贡献者 #4224/#4931 | 1–2 | 容量/receipt/scan 预算、崩溃/恢复/升级、平台覆盖、消费者延迟和至少十天真实经过的 soak。 |
| 捕获与整 Goal 迁移 | 1–2 | 持续混合 writer、event-only 覆盖、drain/fence/readback、cohort 演练与可恢复 export/rollback。 |
| 默认选择与旧 writer 退场 | 1 | 新 Goal 创建/设置/安装选择已资格化 profile；保留显式选择；迁移窗口结束后删除旧业务 writer。 |

这些是完整交付包，不是再合任意五个小 PR 就切换。加速测试不能替代实际经过
时间。PostgreSQL 复用 typed command 语义和真实后端 conformance，但服务认证、
tenant 隔离、部署、恢复/故障切换与容量仍需中期资格化。永久 Markdown renderer、
导入导出、宿主适配器不属于应删除的重复业务所有者。
