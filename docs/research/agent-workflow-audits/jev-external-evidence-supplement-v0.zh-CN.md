# Jev 外部证据补充 v0

调研日期：2026-09-21

本文件是
[Jev RFC 中文版](../../architecture/rfcs/optional-semantic-assistance-jev-v0.zh-CN.md)
的非规范证据快照。RFC 仍是研究范围、系统边界和决策状态的唯一主文档。
本文件不批准实验、数据出站、支出、实现或产品采用。

## 外部证据没有改变产品方向排序

公开结果显示，Jev 在当前快照和有限候选中的局部判断值得验证。相同材料不能证明
Jev 能估计 Todo 的未来目标贡献、比较分支组合，或归因长轨迹失败。现有证据因此
不支持把 D4 或 D5 提升为 LoopX 的产品优先方向，也不支持 D7 或 D8 已具备模型资格。

对 Q1 的建议是按目标 caller 做有界比较。D4 形状的固定候选测试可以作为可选预筛，
用于发现问题表述、输入或校准缺陷，但其通过或失败都不构成 D7/D8 的研究资格。
owner 可以直接选择获准的 D7/D8 A/B/C 比较，在目标任务中同时测量提供方增量和
完整流程价值。跨任务迁移分数或阈值仍缺少证据。

这是研究建议，不改变 RFC 的 `accepted-for-discussion` 状态。Q1 至 Q7 仍待 owner
决定。

## 证据登记

本轮没有调用 Jev。下列结果来自官方资料或社区报告，均未在 LoopX 中复跑。

| 来源和任务 | 报告结果 | 方法限制 | 对 LoopX 的含义 |
| --- | --- | --- | --- |
| TypeSafe 产品资料 | `jev-1.13.0`；每百万 input tokens 0.042 美元；`state + 全部 questions ≤ 64k`，且 `state + 最长 question ≤ 32k` tokens | 厂商资料会更新；本次访问日期为 2026-09-21 | 可用于估算输入预算和 API 费用；不证明质量或完整流程成本 |
| LangChain 天气 Agent 评估 | 5 条轨迹，每条重复 100 次；500 次二元判断匹配一位人工标注者 | 只有 5 条不同轨迹；连续分数只测稳定性；运行来自 `41d821f-dirty`；未记录实际 Jev 版本 | 支持在小型固定集上研究重复性；不支持通用结果判断 |
| SciFact 重排 | 60 个查询，每个 15 个候选；MRR 从 0.622 升至 0.843 | 抽样 900 对；报告未提供独立留出集 | 支持测试有限候选重排，不支持 D4 产品价值 |
| MetaTool 路由 | 200 个查询各测 random、similar 两种模式，共 400 次判断；5 个相似候选时 193/200 正确，即 96.5% | 固定工具目录；重复模式不是独立查询 | 支持测试小集合 `Choice`，不支持 D7 Todo 价值排序 |
| SkillRetBench | 501 个 Skill，500 个查询；报告的 Hybrid `recall@1` 宏平均为 75.8% | 代码计量前 k 项是否命中任一金标；BM25 38.0% 取自外部基线，未在同批样本重跑；方法在同一评测中迭代 | 可提出竞争与验证的假设，不能视为同样本收益对照 |
| InjecAgent 注入检测 | 1,105 条，其中良性样本 51 条；所选阈值下 precision 和 recall 为 100% | 阈值在同一语料上扫描；属于开发集结果 | 只能提出附加风险信号假设 |
| Shell 风险判断 | 自建 130 条命令；v2 危险拦截 100%，正常放行 98.2% | 查看 v1 错例后修改 criteria，并在同一集合报告 v2 | 说明代码规则与局部问题可以组合；不是样本外安全证明 |
| RouterBench 模型路由 | 825 条；准确率 51.3%；报告中中文切片低于英文 | 汇总未单列语言分母，也未建立同内容翻译对照 | 该配置未显示可靠路由收益；差异不能单独归因于语言 |
| Who&When 失败归因 | 1,403 个步骤；AUROC 为 0.560 | 单一社区实现 | 不支持长轨迹失败归因 |
| judge-audit 路由消融 | 同一批 120 行任务仅增加选项说明，准确率从 66.7% 变为 97.5% | 只有 61 种不同文本；难度标签由作者构造，未运行强弱模型；事后消融 | 问题定义会改变结果，不能把提示收益归因于模型替换 |
| Backnotprop 注入评测 | 误报率固定为 5% 时，精选集检出率 74.4%，真人攻击混合集为 19.9% | 两集合分别含 1,688 和 6,115 条；阈值各自扫描，非冻结阈值迁移实验；有标签争议，本轮未复跑 | 即使分别调阈值，可达效果也依赖分布；不支持跨场景复用阈值 |

`jev-harness-lab` 的摘要称约 22,500 次调用和 2.19 美元，方法章节另称 13,616
次调用和 0.45 美元。本文不使用这两组冲突总量推导平均成本。MetaTool 的分母见
[明细报告](https://github.com/Aitejiu/jev-harness-lab/blob/29ddf8210e3a96f9d383e9b479e3e5c39455c394/eval/results/agent-route-k5-report.md)，
SkillRetBench 的指标与基线读取方式见
[评测代码](https://github.com/Aitejiu/jev-harness-lab/blob/29ddf8210e3a96f9d383e9b479e3e5c39455c394/eval/run_skillretbench.py#L279-L348)。

## 三个实现说明了不同边界

[`browser-use/jev-ultrafast`](https://github.com/browser-use/jev-ultrafast/blob/1231850a0bf1a0c0341fe408ef1668dbbfdfac46/docs/performance.md)
只让 Jev 从当前 DOM 快照的编号候选中选择动作。
[执行器](https://github.com/browser-use/jev-ultrafast/blob/1231850a0bf1a0c0341fe408ef1668dbbfdfac46/jev_ultrafast/browser.py#L88-L106)
再次检查快照是否过期，并在
[执行前检查遮挡和几何信息](https://github.com/browser-use/jev-ultrafast/blob/1231850a0bf1a0c0341fe408ef1668dbbfdfac46/jev_ultrafast/browser.py#L135-L162)。
仓库只报告三对 Google Flights 运行，因此该案例证明实现路径，不证明稳定性能收益。

[`fast-jev-compaction`](https://github.com/tamaratran/fast-jev-compaction/blob/e3f262a7f4d42bd8dd32ced30d26176f7cb545b0/src/compact.ts)
会根据 Jev 分数执行 `drop_result` 或 `drop_call`。它固定保留 pinned 和最近消息，
并在[调用失败或压缩率不足时回退](https://github.com/tamaratran/fast-jev-compaction/blob/e3f262a7f4d42bd8dd32ced30d26176f7cb545b0/hooks/fast-jev.ts)。
实现没有证明被删材料可重新获取，也不识别 LoopX 的验收证据或权威历史。
该案例是 D4 的边界反例，不能作为删除材料的正向依据。

[`pi-jev-auto-mode`](https://github.com/jomatsu/pi-jev-auto-mode/blob/06a56043088124ed650471a8589fddd8139708f4/src/extension.ts)
先执行[确定性策略](https://github.com/jomatsu/pi-jev-auto-mode/blob/06a56043088124ed650471a8589fddd8139708f4/src/policy.ts)，
再把未决调用交给 Jev。缺少引擎、取消、异常或
[无效响应](https://github.com/jomatsu/pi-jev-auto-mode/blob/06a56043088124ed650471a8589fddd8139708f4/src/jev/response.ts)
都会阻止高风险调用。这个案例支持语义判断不能覆盖确定性拒绝，不证明 Jev
可以取得安全 authority。

三个实现的失败策略和动作影响不同，不能归纳成一个已经验证的通用 provider
接口。

## 对 Q1 至 Q7 的增量影响

| 待决问题 | 外部证据带来的变化 | 仍未成立的结论 |
| --- | --- | --- |
| Q1：研究方向 | D4 预筛可选；可以直接开展获准的目标 caller 比较 | D4 结果不能授予或否定 D7/D8 研究资格 |
| Q2、Q3：问题与对照 | 在相同证据、标准和选项含义下比较模型；将问题改写另作消融 | 不能把输入整理或提示优化收益归因于 Jev |
| Q4：模型、数据和支出 | 研究可以固定 `jev-1.13.0`；官方价格只用于预算估算 | 移动别名不能用于长期校准；数据出站仍未获批准 |
| Q5：采用证据 | 在目标任务的独立留出集评价质量与成本，并按来源或时间检查阈值稳定性 | 同数据集调阈值后的最好成绩不证明样本外表现 |
| Q6、Q7：机制与执行 | 社区案例支持按 caller 定义边界和失败行为 | 没有证据要求通用接口，也没有证据支持转移 LoopX authority |

另一项机制类比来自 TypeSafe 的
[特征发现案例](https://docs.typesafe.ai/cookbooks/autoresearch_feature_discovery)：
大模型提出问题，Jev 提取局部语义特征，CatBoost 从标签学习目标，独立留出集评价结果。
该厂商案例使用 `jev-1.12` 和葡萄酒评论，只说明可组合的实现方式。对 LoopX，
局部语义信号能否预测工程结果仍需目标任务数据，不能直接把 Jev 概率当作 Todo
预期价值。它也不构成新增监督模型或通用框架的实施建议。

## 来源

- [TypeSafe Jev 发布说明](https://typesafe.ai/blog/introducing-system-one-models-and-jev)、
  [模型与价格](https://docs.typesafe.ai/models.md)和
  [Jev 1.13 限制](https://docs.typesafe.ai/model-jaggedness/jev-1.13)，访问于
  2026-09-21。官方页面未版本化，后续内容可能变化。
- [LangChain 实验说明](https://www.langchain.com/blog/jev-agent-evals-langsmith)和
  [固定结果文件](https://github.com/danielgshea/jev-as-a-judge/blob/adfea74905f721ea2594e22804c8c8edf1693163/assets/benchmark-jev-luna-terra-sonnet/6d08df72-c878-458c-b7c5-a7824ee6e721/benchmark.json)。
  结果文件记录 `revision_id=41d821f-dirty`，固定仓库链接不等于精确复现。
- [`jev-harness-lab` 固定版本报告](https://github.com/Aitejiu/jev-harness-lab/blob/29ddf8210e3a96f9d383e9b479e3e5c39455c394/docs/REPORT.md)。
- [judge-audit 路由消融](https://github.com/kunko-ai-labs/judge-audit/blob/49876079135c9837f04734987ce5745a233585c6/docs/audit-jev-router-ablation.md)，保留其合成标签和重复文本限制。
- [Backnotprop 注入评测](https://backnotprop.com/blog/jev-guardrails/)与上述 TypeSafe 特征发现页面，访问于 2026-09-21；网页未版本化。
