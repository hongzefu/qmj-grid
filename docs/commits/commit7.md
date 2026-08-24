# commit7：新增 Q2 MCTS 实现与对比评估计划文档

## 用户指令原文

按时间顺序：

1. 「现在实现的q2策略是什么 是否可以改成monte carlo tree search 一样在使用预先确定的整数 seeds 0–4，每个 seed 完整覆盖全部12图，共60局和固定seed12图上评估 先告诉我是否可行」
2. 「generateSuccessor 在这个框架里很慢（深拷贝状态），每回合约 0.35 秒预算大概只够几百到一两千次状态展开 为什么」
3. 「实现mcts 跑完生成报告 对比现在的方法」
4. （规划过程中追问）「为什么要跑20-40分钟？ 60局不能并行吗」
5. 「把计划写入md 不要执行」
6. 「写在仓库内的主目录」

## 形式化计划

本次提交只做一件事：把已完成的 MCTS 实现与评估计划写入仓库主目录 `q2-mcts-plan.md`，**不执行**计划中的任何实现、评估或调参步骤。计划本身的内容概要：

- 在 `commits/agents/q2Agent.py` 增加 `strategy=mcts` 可切换分支（默认保持 `alphabeta`，官方 evaluator 行为逐位不变）；MCTS 形态为 Pac-Man 决策点建树 + ghost 联合动作 chance 边 + 惰性扩展 + 评估函数做叶值（无 rollout）+ 一步精确死亡概率修正 + 跨回合树复用；私有 `random.Random` 实例，绝不触碰全局 random 流。
- 新增入库评估脚本 `scripts/q2_eval.py`，进程级并行（`--jobs` 默认 12），两套口径：固定 seed（cs188）12 图、整数 seeds 0–4 × 12 图共 60 局；基线 alpha-beta 用同脚本同并发配对重跑。
- 有限调参最多 2 轮（风险轴、预算轴），快筛用 `mctsIgnoreClock=1 + mctsMaxSims` 的无墙钟噪声模式。
- 最终产出独立对比报告 `docs/q2-mcts-report.md`。

规划期间的关键调研结论（已写入计划）：`generateSuccessor` 单次实测 30~105us（smallClassic~originalClassic），评估函数 16~68us、状态哈希 8~40us；大图真实回合预算仅约 70ms，朴素 MCTS 只有约 35 次 simulation，惰性扩展等优化是必需项；本机 32 核、当时他人负载约 13，故并发上限定为 12。

## 运行命令与结果

```text
cp /home/hongzefu/.claude/plans/mcts-joyful-swan.md /data/hongzefu/qmj-grid/q2-mcts-plan.md
  → 成功

git status --short
  → 仅 ?? q2-mcts-plan.md，工作区无其他在途改动

uv lock
  → Resolved 1 package，成功
```

纯文档提交，未修改任何代码，无需运行游戏测试。

## 当前状态与下一步

- 计划已入库（`q2-mcts-plan.md`），MCTS 尚未实现，`commits/agents/q2Agent.py` 保持 commit5 的 alpha-beta 发布版不变。
- 下一步（待用户确认后执行）：按 `q2-mcts-plan.md` 实施——实现 MCTS 分支 → 冒烟与回归 → 首版评估 → 最多 2 轮调参 → 完整 60 局配对对比 → 生成 `docs/q2-mcts-report.md`。
