# 避免租约循环依赖的精确验收声明恢复

来源：#4971。Agent 持有硬租约时误清 owner 已确认 Todo 的原有等待条件，释放租约后
会陷入死锁：stale 验收阻止获取租约，而 update 又要求活动租约。

修复放在现有 TS reviewed-update 边界，保留注册 actor、claim 和排除条件检查。
没有活动租约、也不提交旧执行证明时，同一 claimed Agent 可以带 provider revision
恢复原文本/等待条件，但候选完整工作摘要必须严格等于当前 owner 绑定的摘要。
现有 CAS 与操作回执保证并发和重试；验收标准、绑定、生命周期和租约代次均不改变。
旧的无 schema 租约在共享 TS 读取边界统一补全格式，避免活动性检查误把有效租约当作
非活动租约；deferred reopen 也复用这条规则，不再自行补字段。
执行工作仍须正常获取新租约。不知道原值或涉及其他范围变更时，明确要求 owner
审核并重新绑定，不能猜测恢复。

此项推进原生长程恢复，不改变默认 provider 或 D3 晋升结论。真实 File/SQLite CLI
覆盖获取租约、误改、释放、拒绝重取、恢复、再次获取；provider 用例还覆盖隔离的
真实 PostgreSQL。恢复后 managed frontier 不再投影 stale hold；原 managed Turn 随后完成 Todo、写回与结算，重复恢复和结算只消费一次
配额。#5000 的 Turn
结算及重试策略仍属独立边界；恢复验收声明不等于结算 Turn。

参见[调用方合同](../../../../reference/goal-acceptance-observations.md#restore-an-unintended-textwait-edit-after-lease-release)。
