# 完整 Goal 捕获中的归档分类连续性

这是整体路线 R5 / L7 捕获连续性的修复，对应 TS RFC 的 T3 消费迁移。
不改变 D1–D3 验收、provider 默认值、writer fence、权限策略或晋升审批。

合法的 legacy Agent Todo 可以不写 `task_class`，活跃读取已有兼容分类。
归档移动保存了 role，却未保存该分类；捕获选择器随后要求两项都必须显式记录。
因此，一条身份明确的历史依赖就可能阻断 bootstrap 及后续 writer-outbox 捕获。

共享 TS 选择器现在区分已记录的 role/class 与 codec 提供的 legacy 分类。
仅明确记录 Agent role 时可以使用后者；显式 class 始终优先。推断后继的闭包遍历
与 canonical 物化使用同一分类。用户决策仍要求原有授权事实；重复身份、非法归档
状态、矛盾的用户作用域、缺失身份依据，以及 deferred 不等于 done 的语义保持不变。
新的 legacy Agent 归档保存原有读取分类，原始回执元数据不被重写。

验证覆盖基线反例、传递及推断依赖、授权负例、新归档写入、真实 CLI bootstrap
后的 writer 捕获，以及移除展示文件后的 File/SQLite canonical 读取。经授权的本机
只读源演练捕获了 346 条活跃记录、664 条归档依赖／决策和 9 条当前租约；188 个源
租约文件保持不变，已退役的租约仅保留源清单，不进入当前图。没有晋升或改写活跃
Goal，私有源内容不进入仓库。

本次移除一项已证实的完整捕获阻塞。下一边界仍是 L7/L8 的目标 provider 资格验证
及经 review 的整 Goal 切换，包括源连续性、drain、fence、回滚和真实后端证据。
捕获通过不等于后续门槛通过，也不意味着 legacy Python 读取器可以删除。
