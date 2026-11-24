# shared-goal-authority 的交付记录有了自己的账本目录

对共享 Goal authority 模型是非规范性的：它不新增任何 runtime 不变量。它放宽了账本
检查附加的一个条件——账本目录原本必须指向一份"附录 A 就是执行账本"的 RFC——并把本 RFC
后续的交付记录指向这里的文件。

- **这笔成本是 maintainer 量出来的，不是本条目量的。** #4677 在 2026-09-17 以
  `origin/main = d8e7af141` 为基线普查了全部 open PR：34 个 head 里 19 个
  `mergeStateStatus=DIRTY`，其中三个（`#3820`、`#4061`、`#4672`）撞在同一份文件上。
  本条目不重新度量任何 head：GitHub 是惰性计算可合并性的，不在每个 PR 上强制触发一次
  计算，就得不到当天的复核数字。
- **记录为什么在这份文件里相撞。** 本 RFC 的交付记录是附录 C 内部的带日期小节——
  `Provider-first terminal lifecycle checkpoint (2026-09-07)`、
  `Cross-RFC semantic and presentation conformance checkpoint (2026-09-12)`、
  `Next delivery and parallel provider work`。它们位于一份 3,125 行英文文件与一份
  2,474 行中文文件的末尾，于是两个记录交付的分支按构造就会插在同一位置。
- **约定早就有，但这份 RFC 用不上。** `examples/docs-governance-smoke.py` 里的
  `check_rfc_ledger_entries` 要求账本目录所指向的 RFC 含字面标题
  `Appendix A: Execution ledger`。而本 RFC 的附录 A 是 `What This Evidence Proves`，
  因此要改成一条一个文件，就得把附录 A–C 在两份语言文件里一起重新编号——那是一次很大的
  机械 diff，本身就会逼这个改动本想帮的那些在途分支重做一遍。现在检查在英文文档里接受
  `Appendix <字母>: Execution ledger`，本 RFC 的附录 D 就是那个指针。
- **已有记录原样保留**，理由与 2026-09-18 语义词表那一轮记录的一样：它们是没人再编辑的
  只追加历史，所以从来不是后来分支相撞的对象——撞的是它们前面那个共享插入点。
- **这次没有做的事。** 它不解决任何已经存在的冲突，受影响的分支仍各自 rebase 一次；
  它不会让账本条目变成可评审证据——条目仍然是"某次改动测到了什么、没有确立什么"的
  非规范性记录；它也不新增托管文档导航项——那边的检查要求每个导航项都有对应文件，
  而不是每个文件都要有导航项。
