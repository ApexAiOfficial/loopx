# 用户完成更新进入 canonical 事务

| 字段 | 证据与边界 |
| --- | --- |
| 目标／来源 | #4574 R5、TS T1/T2、shared-authority local-default L2。新的本地默认必须先覆盖实际 caller，再做 D2/D3 资格化和旧 writer 退出。 |
| 已复现缺口 | 固定 main `0d90d6f66` 上，用户 `todo update --status done` 在 File／SQLite 都先执行声明的验证命令，再因旧 writer fence 被拒绝。已有 canonical complete owner；在 Python 重建其决策会复制 authority。 |
| 交付操作 | 既有 update facade 将用户完成交给 TS terminal owner，共用编辑解码／物化，保留合并字段编辑、原始和候选权限、完成策略、精确租约释放、CAS、业务回执及投影意图。Agent update-done 仍拒绝。 |
| 语义修复 | terminal 的关联 successor 存在性／自环检查提前到验证效果之前。用户验证续提绑定签发时 provider revision，沿用 registry witness 并刷新时钟；过期显式证明不能重新获取租约。仅有 update 委托不能通过清除 owner 关闭他人的 Todo。完成后新备注保留完成时间，不重跑验证，也不依赖已退休的私有声明。 |
| 调用闭合 | 既有 Chat 用户完成动作使用审阅时 canonical basis 和操作身份。验证失败不产生成功回执；显示投影中断和 action 响应丢失均恢复原操作。共享 review plan 与打包前端保留重试按钮。CLI／API 名称及 provider 选择器不变。 |
| 复用／退出 | 从普通 update 提取实际编辑 decoder／materializer，复用 terminal 准入／CAS／outbox 和公开 authoring 规则；共用 Python 验证效果执行与失败投影，删除 terminal 传输层中的重复代码块。Python adapter、私有命令执行和永久 Markdown 渲染仍有 caller，不新增未使用的原生 CLI 框架。 |
| 验证 | 固定基线真实 CLI 反例；File、SQLite、NoKV、隔离 PostgreSQL 上完整 legacy／native 合成图；新鲜／过期／越权／畸形／不写入、revision 改变、不可变回放和委托反例。源码 CLI／Chat、安装后的 wheel／HTTP、打包浏览器恢复覆盖用户入口。只读冻结全图保留全部既有 Todo／lease，并比较 provider 完整 head 及基线普通编辑。 |
| 剩余边界 | 闭合一个 L2 操作，不代表全部 event／Monitor caller 或 executor-held 外部效果 fence 完成。D1 消费者、SQLite D2 容量／soak、D3 集成切换仍由原有 owner 推进；核对已合入 #4315 修复，不重复计算实现。新 Goal 默认与已有 Goal 分组迁移是独立变化，原生 TS 分发不是前置条件。 |
| 兼容／回滚 | 普通 v0–v2 update 请求及既有 terminal receipt 身份保持；旧 wire 拒绝 v3 完成 envelope。降级前处理新操作的待恢复投影，保留历史回执与投影／导入导出职责，不恢复陈旧 Markdown authority。 |

[操作参考](../../../../reference/canonical-todo-completion-update.md)记录公开命令、
类型化所有权及有界退出合同。
