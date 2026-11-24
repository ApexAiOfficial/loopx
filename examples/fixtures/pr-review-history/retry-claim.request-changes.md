## 动机

针对 exact head `a0c5335d4e7743346c9595d644c40b158addec7f` 重新评审。此 PR 要补现有 typed-repeat fuse 的盲区：Agent 连续自报 `advanced`、更换身份标识，但实际改动可能只是与 Goal 验收无关的 churn。默认关闭、先观察再考虑干预，是一个有用且可回退的 stage-0 切片；这仍不证明 Jev 在真实长程 Goal 上的净收益。此前在同一 head 上的 APPROVE 未覆盖下面的重试反例，本次结论以新证据为准。

## 改动思路

显式 wrapper 在真实 `refresh-state` 前后采集限定文件，独立 consumer 评估并写 typed receipt；Goal 的 `off` 不读取，`shadow` 只显示，带固定 contract revision 的 `assist` 才把连续 drift 接入已有 `autonomous_replan_obligation`。这个职责切分、类型化 verdict 和 TypeScript writeback 校验方向正确。新外部证据不应重新定义已有的 Agent/Turn/ACK 历史范围；#4902 已把这类历史规则收敛到 `replan_history.ts`，这里应复用同一选择语义。

## 具体改动

### 关键代码讲解

- `context.py:15` 在 `off` 下提前返回；`receipt.py:356` 读取和规范化本机 Goal runtime 回执。模型没有直接写 Todo/Goal 的权限，但 `assist` 策略可据此生成 `required` 义务，文档应继续直说这个间接控制效果。
- `external_progress_review.py:167` 形成 drift streak 与 `progress_window`；`autonomous_replan_obligation.py:658` 将其放在 typed-repeat 之后、monitor/periodic 之前；`replan_semantics.ts` 决定 writeback 是否真正 ACK。
- `build_constructed.py:247` 生成构造样本，`sentinel_matrix.py:81` 与比较器读取已提交的逐轮快照和录制响应，以便无模型密钥重放。这些资产中真实提交样本和 provider response 有独立的复现价值。

## 对主干的风险

**[P1] 修复同一逻辑 Turn 的 typed claim 遗漏与错误 ACK。** [`external_progress_review_trigger` 的去重](https://github.com/loopx-project/loopx/blob/a0c5335d4e7743346c9595d644c40b158addec7f/loopx/control_plane/work_items/external_progress_review.py#L226-L230) 在检查该 row 是否有 typed observation 之前就把 Turn 放入 `seen_turns`；稍后构造 [`progress_window`](https://github.com/loopx-project/loopx/blob/a0c5335d4e7743346c9595d644c40b158addec7f/loopx/control_plane/work_items/external_progress_review.py#L267-L277) 时，较早的同 Turn typed row 已被跳过。精确 head 上的最小反例是：`t2` 的较新 retry 无 observation、较早 retry 已声明 `hypothesis-2/evidence-t2`，`t1` 已声明 `hypothesis-1/evidence-t1`，两 Turn 都有 completed drift receipt。trigger 返回 `run_count=2`，但 window 只含 `t1`；将已有的 `hypothesis-2/evidence-t2` 送入真实的 Python→TypeScript `semantic_delta_from_writeback`，得到 `accepted=true`、`new_hypothesis`，旧 claim 因而可解除本应阻止重放的义务。请让外部触发器复用 #4902 的逻辑 Turn/ACK 范围语义，或至少在同一选择边界保留被计数 Turn 的所有 typed claims；不要只在文案或模型规则上补丁。增加该反例的 trigger + 真实 writeback 回归，断言旧 claim 被拒、新证据仍可结清，并覆盖 off/shadow/现有触发器不变。

**[P2] 消除构造 fixture 的双重来源。** [`build_constructed.py`](https://github.com/loopx-project/loopx/blob/a0c5335d4e7743346c9595d644c40b158addec7f/packages/loopx-jev/tests/fixtures/sentinel/build_constructed.py#L247-L261) 可确定性生成 37 份已提交的 `constructed/` 快照，约 2,613 行；当前 sentinel 测试直接读取快照，并未证明生成器输出与它们仍相同。两处都可编辑会让生成规则和冻结样本悄悄分叉，也使这次 175 文件的 diff 更难审查。请确立一个来源：可在重放/测试时生成临时快照并移除已提交副本，或保留冻结快照、把生成器作为校验器并逐字节/摘要对照；选择哪种都要保持 16-case matrix、request recording keys 和 expected summary 不变。无需为缩小行数删真实提交样本、负例或 provider response。

**非阻塞后续建议：** 回执现在写入 [`<runtime-root>/goals/<goal-id>/progress-review/receipts`](https://github.com/loopx-project/loopx/blob/a0c5335d4e7743346c9595d644c40b158addec7f/loopx/capabilities/progress_review/receipt.py#L46-L54)。这足够限定本机试点，不能据此宣称已支持 PostgreSQL/跨主机共享权威。要扩大到共享 Goal 时，应另行设计带 Goal/tenant/actor 准入、版本或 fence、幂等重放及保留/恢复规则的 receipt ingestion，让 status 与 writeback 读取同一可信来源；不必把这项未来工作塞进本地 stage-0 PR。

### 语义与 CI 对齐

#4902 的历史规则 TypeScript owner 与本 PR 的 Python scanner 在“先去重还是先保留 typed claim”上出现了可观察分歧，上述 ACK 是该分歧的结果，并非模型准确率问题。RFC 的 M0 讨论收录也不等于 `assist` 的真实 Goal 采用决定。精确 head 的 37 个相关 Python 测试、16-case replay smoke、`git diff --check` 通过；新增反例在生产 trigger 和 TypeScript outcome 边界复现。未把仍在运行的全量 CI、打包前端旅程或真实 Goal 效果报告为已通过。

## 我的整体评价

**REQUEST_CHANGES。** 保留默认关闭和现有 replan 义务的架构，但先修复可重放旧 claim 的 P1，再收敛构造 fixture 的双重来源。修复后请在新 exact head 重跑焦点测试、离线录制重放、File/SQLite 真实 readback 与适用 CI；真实 Goal 的 shadow/assist 准入仍按独立阶段判断。本意见要求修复具体的历史语义和可验证的维护重复，并不要求为了 TS 迁移重写整个 planner，也不以文件数本身否定实验。

English verdict: REQUEST_CHANGES - exact head a0c5335d4e7743346c9595d644c40b158addec7f allows an older typed claim from a retried logical turn to acknowledge an external drift obligation because the Python scan drops it from progress_window; consolidate constructed fixture source of truth while preserving replay. Focused tests and 16-case smoke passed, and a new production-trigger/TypeScript-outcome counterexample reproduced the blocker.
