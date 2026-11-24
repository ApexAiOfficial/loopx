# L7：由单一 TS 所有者投递捕获的源事务

#4574 R5 在整 Goal 迁移前需要完整、可恢复的捕获。原来 Python 解释 prepared
记录、判断是否提交、组装 partition，再把完整投影送给 TS；TS 又读取同一持久
记录并重新证明源状态。现在 `coordination.runtime_shadow.commit_entry` 只接收
Goal／partition／sequence／lineage 身份及 prepared／marker 精确字节哈希，
由 TS 读取投影并负责从源状态判定到候选提交的事务。

[TS 检查点](../typescript-control-plane-migration-v0/2026-09-24-native-entry-delivery.zh-CN.md)
说明删除的 Python 规则和传输边界。变化只涉及包内部请求；持久 outbox、history、
receipt、cursor schema 不变。Python 与 TS 必须一起升级，不增加旧请求回退分支。

## 本次交付

- committed marker 保留原有持久含义。没有 marker 时，TS 持有既有 primary lock，
  判断写入是否落地，并持锁直到候选提交。出现后续源事务、未知源字节或无法区分
  before／after 时继续阻止投递。
- 响应丢失后，即使本地 outbox 已清理，也能重放；前提是完整 lineage 校验通过，
  receipt 与选定字节证据精确一致。operation id 相同本身不够。
- TS 源证据模块共享 lease 身份／排序与磁盘校验；Python 保留有界 drain 调度、
  旧 flock 忙碌检测和 receipt 证明后的清理。
- 回归覆盖 marker 丢失、字节变化、外来 lease、旧 lineage、并发选择、非法 UTF-8
  和损坏历史。原有 native／imported 复杂 fixture 改走实际投递 API，再验证各
  provider 的晋升恢复合同。

授权只读源演练包含 1,018 条 Todo、188 个 lease 文件，其中 9 条属于当前图。
可丢弃副本通过真实 CLI 写入、进程中断、原生投递、清理和重放，最终恰好读回
1,019 条 Todo。请求参数实测由原来的 1,618,597 字节降至 554 字节；1,734,347
字节的 prepared 记录仍被完整读取和校验。这证明传输量下降，不代表延迟改善或
容量无限，也没有提高 RPC 上限。另用 File／SQLite 消费副本验证完整读回与
Markdown 缺失后的 CLI 读取；不将它们称为真实 Goal 晋升。

## 剩余默认切换计划

除整合在途前置外，仍保留有条件的 **5–8 个完整 PR 包**。本次缩小 L7 缺口，
没有完成持续 mixed-writer／event-source 验收矩阵，不能机械减掉一个交付包。

| 交付包 | 预计 PR | 剩余验收 |
| --- | --- | --- |
| L2/L3 实际 caller 迁移 | 1–2 | 盘点 CLI／Turn／Chat 写入和真实 effect 边界；最后调用者迁移时删除对应 Python 规则。 |
| L5/D1 消费与展示 | 1 | 整合投影恢复、完整摘要和分页，验证受影响的打包客户端交互及过期／缺失展示。 |
| L6 SQLite D2 | 1–2 | 延续 contributor-owned #4224：容量、崩溃／恢复／升级、consumer lag、运行时／OS 与真实经过时间的 soak。 |
| L7 捕获与 L8 迁移 | 1–2 | 持续 mixed-writer、event-only 源覆盖、drain／fence／读回，以及经审阅的 cohort 导出／回滚。 |
| L9 默认值与退役 | 1 | 新 Goal 创建／设置／安装选择合格 profile；保留显式选择，最终 caller 与迁移窗口关闭后退役业务 writer。 |

整合在审 #4961（展示恢复）、#4964（摘要所有者）、#4922（快照分页）、#4931
（SQLite 读证明）、#4960（Node 运行时）和 #4967（完整源组装），不重复建设。
本次投递切片独立基于 main，不堆叠上述未合入代码。

Event-only writer 仍明确未绑定。本次不改变 D1–D3、SQLite 时间资格、存量 Goal
分组批准或新 Goal 默认选择。PostgreSQL 复用捕获和恢复合同，但认证、部署、
恢复／故障切换和容量仍需独立资格。永久 Markdown 渲染／导入／导出适配器不等于
应删除的旧业务 writer。
