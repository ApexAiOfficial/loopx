## 动机

复审精确 head `HEAD_OID`。缺失 checkpoint 的原 Turn 不能凭过期 Todo、依赖结果或验收条件补交“继续”判断；同时补交不得生成新 Turn、重做业务副作用或重复扣额度。这个 PR 的完整目标是在读取时给判断依据一份 typed receipt，提交前在真实本地 provider 边界重验并持久化。

## 改动思路

CLI/MCP 的 `checkpoint-context` 从 Goal 状态、canonical Todo/依赖、完整 acceptance 与 Agent vision 生成 receipt；Agent 判断期间不持锁。`refresh-state` 只对原 Turn 的缺失 checkpoint 走补交路径，native commit 接管 index/source 锁凭据，在 File 的真实 writer lock 或 SQLite `BEGIN IMMEDIATE` 中完成最终比较与同步 append。旧 receipt 要求重读；已提交的精确重试读回原结果。该边界复用已有 provider fence，不新增第二个 Todo/配额决策 owner。

## 具体改动

相对当前主干，44 个文件（+1934/-82）覆盖 typed read/commit、Python source IO 与 CLI/MCP/host 适配、File/SQLite fence、index/锁序、协议文档和真实进程测试。上次批准的 `c6fd71b` 到本 head，checkpoint 决策与 fence 核心文件内容未变；新增的 exact-head 改动是把 `read_checkpoint_context` 的 registry read 正式登记进语义扫描 manifest，并合入当前主干。

### 关键代码讲解

- `checkpoint_read_context.ts` 将选中 Todo、传递依赖、完整验收、Goal prose/vision 与 source 身份纳入版本化 basis；无关 Todo 变化不误判为 stale。
- `checkpoint_commit.ts` 在原 Turn 的 settlement admission 后接管锁，于最终 provider head 中重验 receipt，再同步写 JSON、Markdown 与 index；不确定写入要求先读回。
- `file_authority_store.ts` 的 `withCheckpointHead` 复用 `commitAuthority` 的 writer lock；`sqlite_authority_store.ts` 在同一连接的 `BEGIN IMMEDIATE` 到 `ROLLBACK` 之间不 `await`。
- Python `checkpoint_context_io.py` 负责 source 读取与锁交接，不复制 TypeScript 的新鲜度判断；新 manifest 行登记了它的 registry read。

## 对主干的风险

此前提出的 provider-commit 竞态在上个已批准 head 已由真实 fence 闭合，本 head 未改动该核心。当前最值得盯的是外部 run 文件不能随 SQLite 事务回滚，因此代码对不确定 append 明确报错并要求原 Turn 读回，不能盲重试；PostgreSQL 不在本 PR 的承诺范围。复核时，File/SQLite 进程竞争、stale/替换 receipt、精确 replay 和不重复 spend 等 52 个 checkpoint Python 用例通过；16 个 TS 用例、TypeScript typecheck 与 diff check 通过。registry census 首跑因隔离工作树缺少 Node 解析依赖出现 2 个环境失败；安装锁定依赖后全 6 个 census 用例通过，新增 manifest 读取点得到验证。按本 Goal 的 `wait_for_ci=false` 未查询远端 CI。

### 语义与 CI 对齐

复用既有 checkpoint/authority 词汇，新增 receipt 只证明提交时采用的判断依据，不冒称模型内部推理或跨 provider 事务。语义扫描 manifest 的新行与实际调用点一致；没有以放宽检查来消除失败。

## 我的整体评价

**APPROVE。** 当前精确 head 没有发现新的阻断项；先前真实 File/SQLite writer 竞态的修复及其回归在新主干上仍成立。future-facing 检查的结论是继续把新鲜度留在 typed basis 与 provider fence，不引入通用事务框架。此评审不是自合并或生产数据迁移授权，最终合并资格仍由维护者按未变 head 判断。

English verdict: VERDICT - head `HEAD_OID` retains the validated File/SQLite checkpoint fence; the only new read-site manifest change passes after installing isolated Node parser dependencies. 62 unique Python cases, 16 TS cases, typecheck and diff check pass.
