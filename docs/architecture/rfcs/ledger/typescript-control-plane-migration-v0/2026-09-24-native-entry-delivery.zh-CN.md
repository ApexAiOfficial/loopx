# T1/T4：原生 outbox 单条投递

原来 drainer 对源状态判断两次：Python 先判断 primary 字节并运输重组后的
partition，TS 再在自己的锁内校验同一结论。因此，每个 Todo 捕获事务都要把
整个 Goal 的 Todo 图再次送过 effect RPC。

`shadow_entry_delivery.ts` 负责严格的身份／字节证据选择与 receipt 重放；
`shadow_entry_evidence.ts` 负责持久 partition 解码和源锁；既有 shadow 事务
所有者继续负责 lineage、连续性、CAS 与 receipt。marker 缺失时在 primary lock
内得出结论，并持锁直到提交。原有 resolved 事务断言保留为内部语义边界，不是
第二种 RPC 格式。旧请求 schema 从活动 RPC 合同退役，持久 entry／receipt
schema 不变。

删除 Python 的投影／摘要构造器、源读取器和 prepared-entry 判定规则。宿主
特有的旧 flock 探针保留，但不能决定事务是否提交。有界调度和 receipt 证明后的
清理保留当前所有者。默认关闭的 capture 不增加 primary effect。用户操作不变，
沿用 `primary_writer_busy`、`outbox_source_unproved` 的 drain 反馈。

原生入口拒绝调用方传入的 resolution／projection／source path、重复 lease
身份和非法 UTF-8。`TextDecoder` 开启 fatal 校验，不先把非法字节替换成其他
字符再解析 JSON。精确字节哈希与语义 partition 摘要继续承担不同职责。

不新增 capability、provider、持久 ACK 或晋升权限，归属既有 coordination
capture 所有者和内建本地 outbox profile。无需前端／设置／Lark 配置变更，因为
这些入口不构造包内部投递请求；本次也不宣称重新资格化它们的端到端传输。完整
阶段证据和后续包见[shared-authority 检查点](../shared-goal-authority-state-provider-v0/2026-09-24-native-entry-delivery.zh-CN.md)。
