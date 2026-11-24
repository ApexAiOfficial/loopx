## 动机

我按 exact head `29334935c8b7b723cc98aabce4ff754c1263644b` 复核了两阶段 `checkpoint-context` 协议，重点判断它是否真正兑现 PR/文档对 File/SQLite 的本地原子新鲜度承诺：最终 decision-basis 比较完成后，任何参与的 canonical writer 都不能在 checkpoint append 前提交新状态。typed receipt、stale/replaced 分类和 host/CLI 接入本身方向正确，但真实 provider writer 仍在该原子边界之外。

## 改动思路

当前提交路径是：`read_checkpoint_context` 生成 receipt，`checkpoint_commit_guard` 在 `_source_guard` 内重读 `_source_facts`，然后把它掌握的 shadow-maintenance、legacy Todo 与 state-file locks 保持到 refresh run append。这个方案只在所有 authoritative writer 都参加同一锁协议时成立。

实际 promoted Todo 更新不是这样：`provider_update.py` 先通过 `effect_runtime_result("coordination.local_authority.todo_update", request)` 提交 canonical provider mutation，随后才调用 `settle_canonical_todo_projection(...)`。后者会等 shadow lock，但 canonical commit 已经发生，所以 projection lock 无法成为 provider transaction fence。

## 具体改动

- PR 新增 TS/Python typed checkpoint receipt、读取/提交两阶段 API、CLI/MCP/host 适配与本地持久化。
- exact-head 验证：三组 TS recovery/host 测试 25/25 通过；四组 Python focused recovery 测试 60/60 通过；`git diff --check origin/main...HEAD` 通过。
- `loopx pr-review --check-result` 对本轮结构化结果返回契约有效，verdict 为 `REQUEST_CHANGES`。
- 按 packet 的 `wait_for_ci=false`，本次没有使用远端 CI 状态作为判断证据。
- 这些用例证明 receipt 机械、直接文件替换和已纳入 `_source_guard` 的锁竞争能被检测；它们没有通过 production public provider update 入口制造 canonical commit，因此不能覆盖下面的竞态。

## 对主干的风险

**[P1] `checkpoint_commit_guard` 没有 fence canonical provider 写入。**

存在合法交错：checkpoint 完成最终 `_source_facts` 读取 → File/SQLite provider update 提交 canonical Todo/acceptance mutation → projection settlement 等待 shadow-maintenance lock → checkpoint 使用旧 basis append → projection settlement 恢复。receipt 对旧 snapshot 内部自洽，却已经不新鲜；系统不会报 stale，也会持久化错误 continuation basis。这直接违背 PR 声明的 local atomic-freshness guarantee，属于 correctness blocker。

最小修复应位于 authoritative provider boundary，而不是再增加 projection lock：要么让 append 持有真正的 provider transaction/write fence，要么把 append 原子绑定到 provider-owned revision/CAS；若某个 promoted provider 暂时不能提供该边界，则 checkpoint 应 fail closed。请增加 File 与 SQLite 的 production-path concurrency regression：在最终 basis read 后暂停 checkpoint，通过真实 public provider update 入口提交 mutation，并证明 append 被拒绝且要求 reread。

future-facing pass 的结论也是同一件事：freshness 应由 canonical provider revision/transaction 单点拥有，receipt 携带并验证它；不要让每个 projection/legacy writer 继续扩张成一套易漂移的全局锁协议。PostgreSQL 可以按 PR 明示的范围另行验证，但不能据此豁免本地 provider 竞态。

## 我的整体评价

两阶段 receipt 是有价值的机制，API/host 覆盖也较完整；但当前 exact head 的核心原子性承诺仍被真实 canonical writer 绕开。现有绿测不能证明最关键的生产交错，因此我继续请求修改。修复 provider-owned fence/CAS 并加入 File/SQLite 真实 writer 负例后，再基于新 exact head 复核。

English verdict: REQUEST_CHANGES - head `29334935c8b7b723cc98aabce4ff754c1263644b`; the final checkpoint guard still does not fence the production canonical provider commit, so a local File/SQLite write can land after the last basis read and before append.
