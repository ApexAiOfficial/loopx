# RSI-Harness 对 LoopX 的设计与采用价值

English summary: adopt explicit ownership, evidence limits and bounded I/O as
design principles. Do not import a second configuration authority or equate
schema validation with measured improvement. The delivered slice streams the
existing Codex usage producer through its opening byte extent, preserving full
accounting, model binding and replay rather than sampling usage.

- 调研日期：2026-09-24。
- 上游版本：[737bf1f](https://github.com/CosmosMind-ai/RSI-Harness/tree/737bf1f5a5a56f0c49bbd5180e71d651113038ac)，MIT，package version 0.1.0。
- LoopX 对照基线：`e07ee86a42b75d93b2a448607412010c66a8de1f`。
- 性质：外部设计研究与一个已实现的采用切片，不授予 runtime、provider、能力或权限晋升。
- 来源：源码、契约、测试、公开 issue；没有调用真实模型，没有访问用户会话库，没有安装上游到默认 Agent 环境。

## 结论与架构位置

RSIH 把 Pi 的配置组织成可分发的 Genome；GEE 用一个普通 Genome 分析历史，协助
用户生成另一个 Genome。当前开源交付的主要价值是**配置组合、分发与证据驱动的个性化**。
它没有交付包含独立评测、等预算对照和效果晋升的完整自改进控制器。

```text
RSIH: Pi runtime → Genome 配置适配 → harness-rsi skill/tools → 候选 Genome
LoopX: Goal/权限/预算 → 任务与恢复规则 → host/provider 执行 → 独立验收与结果
```

两者可互补，但 Genome 的字段覆盖、安装成功或结构校验都不能替代 LoopX 的执行授权、
任务验收、单次结算和多 Agent 隔离。历史高频行为也不直接构成偏好或正确做法。

## 已确认的设计与边界

| 机制与源码 | 已确认的行为 | 对 LoopX 的判断 |
| --- | --- | --- |
| [组件加载](https://github.com/CosmosMind-ai/RSI-Harness/blob/737bf1f5a5a56f0c49bbd5180e71d651113038ac/src/harness/genome-bundle.ts) | 12 类组件分别允许特定字段；越界拒绝；契约文本随 bundle 携带 | 借鉴字段归属和分发完整性。LoopX 已有 capability/extension/profile owners，应复用而非引入平行 Genome authority |
| [补丁合并](https://github.com/CosmosMind-ai/RSI-Harness/blob/737bf1f5a5a56f0c49bbd5180e71d651113038ac/src/harness/genome.ts) | 缺省继承、null 删除、对象递归合并、数组整体替换 | 三态语义值得用于审查现有配置。不能把 null/省略/空集合当作同一操作；不能直接套到 LoopX 的权限集合或 provider 选择 |
| [settings 投影](https://github.com/CosmosMind-ai/RSI-Harness/blob/737bf1f5a5a56f0c49bbd5180e71d651113038ac/src/harness/settings-layer.ts) | 记录 managedKeys，释放旧配置拥有的键，保留非托管键 | 适合单一宿主配置适配。读改写是共享文件，未提供 LoopX 多写者所需的事务、租约或 CAS |
| [种子更新](https://github.com/CosmosMind-ai/RSI-Harness/blob/737bf1f5a5a56f0c49bbd5180e71d651113038ac/src/harness/genome-loader.ts) | 比较种子/当前副本摘要；用户修改过的副本不自动覆盖 | 有价值，LoopX 的 project-skill delivery 已有 source/installed digest、locally_modified 拒绝覆盖和回读；无需复制一个更新器 |
| [Pi 配置面测试](https://github.com/CosmosMind-ai/RSI-Harness/blob/737bf1f5a5a56f0c49bbd5180e71d651113038ac/test/pi-surface.test.ts) | 从所安装 Pi 的声明文件提取 settings/keybinding，与本地清单双向比较 | 很好的依赖升级守卫。它证明字段覆盖，不证明字段运行效果、零行为差异或跨版本兼容 |
| [session sources](https://github.com/CosmosMind-ai/RSI-Harness/blob/737bf1f5a5a56f0c49bbd5180e71d651113038ac/config/genomes/harness-rsi/extension/session-sources.ts) | 来源显式选择；按记录类型识别用户输入；区分字节截断、prompt 数限制、文本截断、损坏和跳过 | 借鉴“来源 + 完整性 + 解释范围”。不扫描所有账户/历史，也不将缺失记录解释成没有发生过 |
| [GEE 方法](https://github.com/CosmosMind-ai/RSI-Harness/blob/737bf1f5a5a56f0c49bbd5180e71d651113038ac/config/genomes/harness-rsi/skills/genome-authoring/pattern-to-component.md) | 先看目标场景、再把重复模式映射为 skill/tool/MCP/memory；配置可以留空 | 有利于控制规则膨胀。LoopX 可沿 self-repair 与 Reward Memory 候选生命周期采用，不能由出现频率自动授予长期权威 |
| [Genome 切换](https://github.com/CosmosMind-ai/RSI-Harness/blob/737bf1f5a5a56f0c49bbd5180e71d651113038ac/src/cli/supervisor.ts) | 区分运行内可变项与必须重启的启动参数；交互模式由 supervisor 重启并恢复 session | 借鉴“声明配置不等于已生效配置”。同一 agentDirectory 的单个请求文件不适合直接承担并发 Agent 切换 |

`resources.isolate` 只关闭 Pi 自动发现的一部分资源，保留明确声明的资源和上下文文件。
这能减少不相关的 prompt 内容，却不是进程、文件系统或凭据隔离。
`settings` 又是覆盖语义投影的低层入口，所以“组件字段互斥”也不等于最终有效设置
没有优先级关系。采用时必须检查最终值及其 owner。

## 实测与不能推断的结论

在固定上游 commit、Node 24.21.0、无真实模型凭据的进程环境中：

- `npm ci --ignore-scripts` 后执行 `npm run check`：161 项测试通过，0 失败，0 跳过；构建通过。
- 构建产物的 `genome validate`：paperlab 的 4 个组件、harness-rsi 的 7 个组件通过。
- 临时目录中依次写入两个不同 session 的 switch request，再读取两次：第一次得到后写入
  的请求，第二次为空。它证明共享文件可覆盖前一请求；不证明两个隔离目录也会冲突。
- [tsconfig.base.json](https://github.com/CosmosMind-ai/RSI-Harness/blob/737bf1f5a5a56f0c49bbd5180e71d651113038ac/tsconfig.base.json)
  设置 `noCheck: true`、`strict: false`。因此 `typecheck` 成功不应解释为完整语义类型检查通过。

源码中的 GEE 先确认方案再写文件，主要依赖 instructions/skill 的交互约定；不能把这当作
独立、不可绕过的写入权限实现。generated tool、extension、MCP 也仍需各自的执行信任边界。
目录可分享不代表已完成脱敏；当前 README 明确列出了缺失的发布前脱敏检查。

[公开 issue #2](https://github.com/CosmosMind-ai/RSI-Harness/issues/2) 询问论文 Table 3 的
adaptation split、搜索预算和最终 Genome，调研时尚无回复。当前仓库不包含对应的 benchmark、
训练或评测实现；本次没有复现论文，也不能据此判断效果提升、优于 LoopX 或自改进收益。

## 采用决策

| 路径 | 当前决定 | 理由与下一项有效证据 |
| --- | --- | --- |
| 将 RSIH 作为核心依赖或替换 LoopX runtime | 不采用 | 会把 Pi 专属配置层带入 provider-neutral 控制面；没有已证明需要的独立 caller contract |
| 直接复制 Genome/生成器/共享 settings | 不采用 | 与现有配置和候选治理重叠；共享写入不满足多 Agent 隔离；没有独立收益证据 |
| 新增可选 RSIH host adapter | 暂缓 | 先有使用该宿主的真实需求，再验证 run/session、取消、恢复、权限、安装/卸载及 feature-off parity；现有 Pi 适配仍有自己的 owner |
| 把历史模式转成改进候选 | 保留设计价值 | 复用 self-repair、Reward Memory、change-quality；需要来源范围、反例、候选 diff、等预算对照与回滚，不能只增加一份 prompt |
| 历史读取成本与证据边界 | 本次采用 | 已找到现有生产调用：Codex rollout 用量读取。改为完整流式扫描，不增加新扫描能力或会话导入 |

这对应 [总体 roadmap](../../architecture/rfcs/loopx-overall-roadmap-v0.md) 的 S7 用量正确性
和 S12 可维护交付；长期候选治理属于 S6/S11。File/SQLite/PostgreSQL 的 canonical authority
迁移继续由既有 RFC 管理，本次不引入新 provider 或扩大 promotion 范围。

## 本次 LoopX 改动与验收

原 `codex_session_usage` 会读取整份文本再建立行列表，记账不需要的长工具输出也占用
整份内存。新的私有 JSONL reader 位于原 quota adapter 中，保留 Python 的宿主文件 I/O
职责；用量校验、基线、重复结算规则继续使用既有 owner，无需为了文件读取另建 TS 协议。

区别在于读取目的：RSIH 为工作区发现读取有限头部，允许返回不完整的历史样本；LoopX
要找最新累计用量，必须扫描打开时的完整文件范围。不能截取前若干 MiB 后把旧数值记为最新。

- 打开时固定字节范围，逐条解码；新追加内容留到下一次观察，防止追逐增长中的文件。
- 保留最终未完成 JSON 的容忍；补充最终 UTF-8 字符写到一半的处理。
- 中间损坏、其他编码错误、读取范围内提前 EOF 均拒绝记账；有效 JSON 字符串里的 Unicode
  分隔符不再被 `splitlines()` 当作新记录。
- 不改变累计到增量转换、model/snapshot 绑定、usage booking lock 或 run-index commit point。

同一合成文件 33,763,653 字节、4,096 条约 8 KiB 工具记录和末尾用量事件，单进程
`tracemalloc` 对照：基线峰值 68,092,110 字节，改后 46,898 字节，两个 observation 相同。
单次耗时约 0.067 / 0.069 秒；这是受控内存测量，不是速度提升、真实模型性能或 RSS 声明。
内存仍随最大单条记录和末尾模型兼容元数据增长，不声称任意输入下固定内存。

回归覆盖真实文件、开读后追加、读取中截断、Unicode、损坏与重放；独立 CLI 演练使用
隔离 registry/runtime，将大文件记账、重复读取和新增用量写入真实 run index 并回读。
原始轨迹、私有记录和一次性测量脚本不作为公开 fixture 或产品依赖。
