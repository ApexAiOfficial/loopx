# 完整源捕获由一个 TS 边界组装

面向总路线图 G2/R5、shared authority L7：迁移快照必须先证明输入完整且身份无歧义，才能作为晋升输入。本次关闭源快照组装边界，不代表事件 writer 连续性、D2/D3、既有 Goal 迁移或默认 provider 已完成。

`coordination/source_projection.ts` 统一拥有 Todo 分区和完整 coordination 快照的身份、严格字段、Unicode 顺序、当前图的 lease 成员关系和带摘要的读取清单。TS 在源锁内复核时重建同一结构；Todo 分区折叠复用相同的当前图成员规则。Python 保留源 IO、Markdown/归档格式适配和精确字节证据；整批传输，不逐条调用 RPC。

语义变化：

- 缺失或非数组的 Todo 集合、非法行、缺少 ID 均拒绝，不再静默变为空证据。
- 重复 Todo/lease 身份拒绝；lease 的身份和显式 Goal 归属在过滤历史记录之前校验，不能因为即将丢弃就跳过。
- 继续拒绝浮点数；新增共同安全整数范围检查。Python 在 JSON 传输前拒绝，TS 解码再次检查，避免数字先舍入、再参与摘要。
- 合法语义保持：归档依赖仍是记录；只有 active 分区中的 Todo 才保留 lease 边。当前 Todo 的已释放或过期 lease 保留代次历史，不能按活跃时间过滤。查询生成的 succession evaluation 不持久化；未知机器字段拒绝。

持久化 schema、源锁顺序、authority 选择和写权限不变，2 MiB RPC 上限不变。新增一次组装调用是迁移/旧路径捕获成本，不宣称加速。Python 传输随最后一个旧捕获调用方退役；仍有真实调用方的导入导出、精确字节复核保留。

验证使用独立设计的拒绝反例、跨真实 provider 的复杂混合 fixture、隔离源副本上的 CLI 和回读。未通过或缺失的耐久性证据继续阻止晋升。

## 剩余默认切换交付

仍按 **5–8 个交付 PR** 规划，另需 review/集成当前已开的前置 PR。估计取决于集成结果，不按字段迁移或 PR 数量扣减，也不为凑数拆分。

| 交付包 | PR 数 | 完成条件 |
| --- | --- | --- |
| 公开调用方覆盖 | 1–2 | 核对 CLI/Turn/Chat mutation 和真实外部副作用调用方；区分旧锁和 canonical CAS，不增加无调用方的 executor 框架。 |
| 消费与展示闭环 | 1 | 集成在审的展示恢复、完整源汇总、快照分页；验证过时/缺失展示、完整数据和受影响的打包客户端。 |
| SQLite D2 | 1–2 | 沿 contributor 负责的 #4224，在同一 profile 关闭容量、崩溃/恢复/升级、lag、运行时/OS、持续 soak 缺口。 |
| 捕获连续性与整 Goal 演练 | 1–2 | 同一确切版本完成混合 writer/事件源、重启重放、drain、旧 writer fence、canonical 回读、带 fence 的导出回退。本次组装收敛只是前置，不等于完整 L7。 |
| 默认切换与有边界退役 | 1 | 新 Goal 创建、设置、安装选择已合格本地 profile；最后调用方和迁移窗口关闭后删除旧业务 writer。 |

File 保持显式参考 profile，SQLite 是长期本地默认候选。PostgreSQL 已有实现和受限工厂，但服务鉴权、部署/恢复/failover、容量资格仍是独立中期工作。provider conformance 通过，不等于默认资格或活跃 Goal 的切换授权。

实测代价：同一 1,018 条记录的已解析输入、7 次 warm 组装，中位数从约 35 ms 增至 186 ms；新增一个整批 RPC，不能宣称加速。合法快照语义摘要和 File/SQLite 回读一致。隔离副本上的实际 bootstrap 也通过，188 个源 lease 文件完整核验、仅 9 条当前图 lease 进入快照。保留此前的 schema/清单兼容，未放宽预算或启动 D2 长程实验。
