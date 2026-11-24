# T3 归档捕获区分兼容解码与授权

既有 `todos/archive_capture.ts` 仅在源明确记录 Agent role 时接纳 legacy 读取分类。
Python 复用现有 Markdown 分类器，只传紧凑分类结果，不传源正文；身份准入、授权
矛盾和依赖闭包仍由 TS 决定。结果携带已选 class，Python 不再在准入后独立决定分类。
不新增 capability、provider、CLI 参数或前端状态 owner。受影响入口为
`todo archive-completed`、shadow bootstrap 与 writer-outbox 捕获，沿用通用 CLI 错误展示。

相关简化是让推断后继索引与记录选择共用一个分类解析规则，归档写入复用既有
Markdown 规范化。正文分类器仍属于 legacy 兼容代码；后续 T3 退役需要活跃读取
的等价性验证，不混入本次准入修复。本次没有增加根据正文判断授权的规则。

完整源证据和剩余晋升边界见配套的[authority 检查点](../shared-goal-authority-state-provider-v0/2026-09-23-archive-classification-continuity.zh-CN.md)。
内部 request v2 / result v1 要求 Python 与 TS 成套升级，已持久化的历史回执不变。
合成负例保留用户角色缺失拒绝、显式分类优先、deferred 不算完成以及重复身份阻断。
