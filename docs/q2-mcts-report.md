# Q2 MCTS 实现与 Alpha-Beta 配对评估报告

## 1. 实验范围、数据源与统计口径

本报告评估 `commits/agents/q2Agent.py` 中新增的可切换 MCTS 策略，并与原有
Alpha-Beta 发布策略比较。默认构造参数仍是 `strategy='alphabeta'`；
只有显式传入 `-a strategy=mcts` 才进入 MCTS 路径。

最终数据来自：

- [q2-mcts-results.json](q2-mcts-results.json)：最终 MCTS 配置
  `strategy=mcts,mctsMinPlyBudgetSims=120`。
- [q2-alphabeta-results.json](q2-alphabeta-results.json)：本次配对重跑的
  `strategy=alphabeta`。
- `/tmp/q2-mcts-v1-fixed.json`：MCTS 首版固定 seed 结果。
- `/tmp/q2-tune-r1-{a,b,c,d,e}.json`：第 1 轮风险参数实验。
- `/tmp/q2-tune-r2-{b,c,d}.json`：第 2 轮预算参数实验；首版结果同时作为
  第 2 轮的默认参数对照。
- [q2-report.md](q2-report.md)：此前已经记录的 Alpha-Beta 历史基线。

最终两个 JSON 各有 72 个 case，但报告严格拆成两种口径，绝不把 72 局总数
冒充 60 局结果：

1. **固定 seed 12 局**：seed 是字符串 `"cs188"`，等价课程命令的 `-f`；
   12 张 `q2_*.lay` 各运行 1 局。
2. **整数 seeds 0–4 共 60 局**：5 个整数 seed 分别完整覆盖 12 张布局；
   每个 case 都启动一个新的专用进程，并在该进程内执行
   `random.seed(seed)`，case 之间不存在进程或 Python 全局状态复用。

最终配对重跑均使用 Python 3.9.25、uv 0.10.2、`--timeout=30`、
`--jobs 12` 和同一评估脚本。平均分均按相应口径内的完成局计算；最终两组
实验全部完成，所以分母分别是 12 和 60。表中平均分保留两位小数，总分和
胜局数保留精确整数。

两个最终 JSON 都是 schema v2，记录的 Git 基础提交为
`763219429e27a11b05d615147ece5682c5f60e90`，且工作树当时不干净。为避免
把基础提交误当成实际算法快照，两份文件同时记录并一致核验了：

- `commits/agents/q2Agent.py` SHA-256：
  `eaa2fa3cd42408df30b8741baa504175f11dafbf32a6643e3c747a48458f7b49`；
- `scripts/q2_eval.py` SHA-256：
  `a8b5eb929441a06cf16d5f95639a1ad5a4d3e16f5d46abf850ee10fa55921795`；
- `uv.lock` SHA-256：
  `f1a0682ce353b609372af7a4093d572249a1dfc54d90ad924ef481f031ec8dd8`。

因此本次配对确实使用相同 Agent、评估脚本和锁文件；最终提交则把这些工作树
内容固化为可复现版本。

## 2. MCTS 设计与当前实现

### 2.1 决策节点、chance 边与惰性扩展

树只在 Pac-Man 决策点建立 `DecisionNode`。每条 `ActionEdge` 表示：

1. Pac-Man 执行一个合法动作；
2. 所有 ghost 各自按真实的均匀分布独立采样动作；
3. 联合 ghost 动作元组映射到下一轮 Pac-Man 决策节点。

`ActionEdge` 只生成一次 Pac-Man 后继，并缓存各 ghost 的合法动作集合。
联合动作元组直接作为 `outcomes` 的键，热路径不使用开销较高的
`hash(GameState)`。节点有未尝试动作时，每次 simulation 只扩展一个动作；
顺序优先非 `STOP`、延续当前方向，再保持原合法动作顺序。这里没有随机
rollout，首次扩展后直接以叶值回传。

chance outcome 使用渐进加宽：

```text
limit = min(mctsMaxOutcomes,
            1 + floor(sqrt(edge_visits / mctsWidenC)))
```

默认 `mctsMaxOutcomes=4`、`mctsWidenC=4`。达到上限后，如果新采样的
联合动作尚未建节点，就从已有 outcome 中重采，避免低预算下过多
`generateSuccessor`。

### 2.2 选择、叶值与回传

默认 `mctsSelect='hybrid'`：

- 根节点使用 PUCT；先验是动作初始叶值经温度
  `mctsPriorTemp=0.5` 的 softmax。
- 树内部使用 UCB1。
- 探索系数 `mctsCpuct=1.0`。

叶值被限制在 `[0, 1]`：

```text
win  -> 1
lose -> 0
v = 0.5 + 0.5 * tanh((evaluation(state) - root_anchor) / 100)
```

`root_anchor` 是当前回合根状态的 `betterEvaluationFunction` 值，
`mctsValueScale=100`。默认风险系数 `mctsRiskLambda=0`，因此 chance
边按样本均值回传；实验中也测试了
`(1-lambda) * mean + lambda * minimum`。

最终动作使用 robust child，依次比较终局胜负、访问数、Q 值、是否非
`STOP` 和原合法动作顺序。即使搜索被墙钟截止，已经完成的统计仍可用于
返回合法动作。

### 2.3 一步死亡概率修正

默认 `mctsDeathCorrection=1`。对 Pac-Man 动作后的状态，代码不再生成
额外 ghost 后继，而是直接计算每个 ghost 合法动作中会碰撞的比例，并利用
ghost 独立性得到：

```text
p_death = 1 - product(1 - lethal_i / legal_i)
v_corrected = v * (1 - p_death)
```

实现显式处理 `scaredTimer==1`：ghost 本步按 0.5 倍速度移动，timer
随后归零并用 `nearestPoint` 对齐，因此仍可能致命；timer 大于 1 的 ghost
本步不计为致命。碰撞阈值复用游戏引擎的
`COLLISION_TOLERANCE=0.7`。这项修正不消耗额外
`generateSuccessor`，适合低 simulation 预算。

### 2.4 24 秒整局预算与自适应 Alpha-Beta 降级

MCTS 复用原策略的 24 秒整局内部预算：

- 总预算 `24.0s`，保护余量 `0.05s`；
- 单回合上限 `0.35s`，最小搜索预算 `0.005s`；
- 预计剩余回合数为
  `max(12, ceil(1.5 * remaining_food))`；
- 默认 `mctsTurnBudgetScale=1.0`；
- simulation 耗时使用 EMA；若
  `now + 1.2 * simulation_ema >= deadline` 就软停止。

每局开始时，代码用大约 20 次后继生成实测一个 Pac-Man 加全部 ghost 的
ply 成本，并估计：

```text
estimated_simulations = initial_turn_budget / (2 * measured_ply_cost)
```

最终配置把 `mctsMinPlyBudgetSims` 从默认 60 调到 120。如果估计值小于
120，该局从一开始就使用完整的既有 Alpha-Beta 路径。因此最终
`strategy=mcts,mctsMinPlyBudgetSims=120` 是一个预算感知混合策略，而
不是每张图都强制运行纯 MCTS；降级依据实测成本，不读取布局名、坐标或
环境 seed。

### 2.5 跨回合树复用与 stats epoch

选择动作后，只保留该动作已经生成的 ghost outcomes。下一回合先用
`(Pac-Man 位置, ghost 的位置/方向/scaredTimer, 剩余食物数)` 做廉价签名
筛选，再用完整 `GameState ==` 精确核验，避免对每个候选状态做哈希。

根状态变化后，新的 `root_anchor` 会改变所有非终局叶值，旧回合的
`n/w/q` 因而不能直接沿用。实现每次真正建立或恢复 MCTS 根节点时都递增
`_mcts_stats_epoch`：

- 匹配成功时保留树拓扑、缓存的 Pac-Man 后继、ghost 合法动作与 outcome；
- 节点第一次在新 epoch 被访问时，按新 anchor 惰性重算叶值；
- 同时重置节点和已有边的 `n/w/q/minimum`，防止混合不同尺度的统计。

这使树复用节省状态生成，但不会把上一回合相对旧 anchor 的数值统计错误地
带入当前回合。

### 2.6 RNG 隔离与默认兼容性

MCTS 只使用私有 `random.Random`；每局在 `registerInitialState` 中按
`mctsSeed * 1_000_003 + game_count` 重播种。它不会调用模块级
`random`，因此不会消费 `RandomGhost` 的全局随机流。评估脚本对每个
case 新建 agent，并在 `runGames` 前设置该 worker 的全局环境 seed。

默认 `strategy='alphabeta'`，官方 evaluator 不传 `-a` 时仍进入原
Alpha-Beta、迭代加深、forced-loss expectimax 和 fallback 路径。MCTS
模式下保留走廊快捷、循环守卫、reactive fallback 和紧急合法动作出口。

最终 MCTS 参数为：

```text
strategy=mcts
mctsSeed=20250824
mctsCpuct=1.0
mctsSelect=hybrid
mctsPriorTemp=0.5
mctsValueScale=100
mctsMaxOutcomes=4
mctsWidenC=4
mctsDeathCorrection=1
mctsRiskLambda=0
mctsTreeReuse=1
mctsMaxNodes=20000
mctsMaxSims=0
mctsIgnoreClock=0
mctsTurnBudgetScale=1.0
mctsMinPlyBudgetSims=120
```

### 2.7 Anytime 安全加固

代码审查后又对低预算边界做了定向加固：

- 根节点最多 5 个 Pac-Man 后继会原子扫描一次，同时产生安全 fallback 和
  MCTS 先验缓存；正常搜索不再为 simple fallback 重复生成同一批后继。
- 若 deadline 到来时根动作尚未全部进入树，最终返回已经完整检查的
  fallback，不让部分展开的首个 edge 覆盖已知安全或立即获胜动作。
- 内部节点只有在 edge 完整构造成功后才从未尝试队列删除动作，因此搜索
  timeout 不会让树复用后的节点永久丢失合法动作。
- 注册阶段与实际回合共用同一个预算公式；所有浮点实验参数先用有限性检查
  拒绝 NaN/Inf，避免在热路径中延迟崩溃。

## 3. 评估脚本与公平性

当前 `scripts/q2_eval.py` 使用 `spawn` 进程级并行，最多同时运行 12 个
专用 case 进程。每个 layout/seed case：

1. 新建 `Q2_Agent` 和 ghost agents；
2. 在该专用进程内单独执行 `random.seed(seed)`；
3. 调用一次 `pacman.runGames`，使用 `NullGraphics` 和 30 秒预算；
4. 记录 score、胜负、墙钟时间、agent 时间、timeout、crash 和异常；
5. case 前后调用 `GameState.getAndResetExplored()`，随后该专用进程退出。

课程框架仍执行 30 秒整局 agent 预算。父进程另设
`max(timeout + 15, timeout * 1.5)=45s` 的硬墙钟上限：超过 45 秒就终止
该 case 进程并记录 `WorkerProcessTimeout`；进程提前退出但没有返回结构化
结果则记录 `WorkerProcessError`。这层硬上限负责回收失去响应的子进程，
不替代课程的 30 秒 agent timeout。

一 case 一进程和 45 秒硬上限适用于本次两份最终重跑；`/tmp` 首版与调参
文件没有重跑，仍按其原始记录作为历史证据，不用来证明当前评估脚本的进程
隔离行为。

MCTS 与 Alpha-Beta 最终实验的并发上限都是 12 个专用 case 进程。两份
结果在相邻时间段生成，硬件、脚本、布局、seed 和并发口径一致；这比直接
拿新 MCTS 数据与旧报告数字比较更公平。旧报告数据仍单独列出，用于展示
历史波动，不能冒充本次配对基线。

## 4. MCTS 首版

首版使用默认 MCTS 参数，即 `mctsMinPlyBudgetSims=60`，固定
`cs188`、12 图并行运行：

| 完成 | 胜/总局 | 总分 | 平均分 | 中位数 | Timeout | Error | 墙钟时间 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12 | 7/12 | 12766 | 1063.83 | 1028.00 | 0 | 0 | 26.575s |

首版输掉 capsule（-81）、danger（-169）、medium2（755）、
original（1933）和 tricky（1301）；trapped 已得到 532 分并获胜。这说明
chance 建模能在部分短图正常工作，但固定 seed 下仍未稳定解决 capsule、
tricky 和大图预算问题。

## 5. 第 1 轮调参：风险轴

第 1 轮统一使用 `mctsIgnoreClock=1,mctsMaxSims=200`，从而固定每回合
simulation 数，比较死亡修正、风险混合和 outcome 上限。表中 C、D、E
各有 1 个 timeout，所以其总分和平均分只统计 11 个完成 case。

| 候选 | Death correction | Risk lambda | Max outcomes | 完成 | 胜/12 | 完成局总分 | 完成局平均分 | Timeout | Timeout 布局 |
|:--|:--:|--:|--:|--:|--:|--:|--:|--:|:--|
| A | 1 | 0 | 4 | 12 | 8 | 13327 | 1110.58 | 0 | — |
| B | 0 | 0 | 4 | 12 | 5 | 10545 | 878.75 | 0 | — |
| C | 1 | 0.25 | 4 | 11 | 5 | 8608 | 782.55 | 1 | original |
| D | 1 | 0.5 | 2 | 11 | 8 | 11452 | 1041.09 | 1 | original |
| E | 1 | 0 | 8 | 11 | 7 | 9948 | 904.36 | 1 | tricky |

关键观察：

- 关闭死亡修正的 B 从 A 的 8 胜降到 5 胜，capsule、minimax 和 tricky
  都输，支持保留一步死亡概率修正。
- 加入最坏值权重的 C/D 没有形成稳定净收益；D 虽有 8 胜，但 minimax
  从胜变负，并且 original timeout。
- 把 outcome 上限扩大到 8 的 E 没有改善 small，且 tricky timeout。
- 计划要求 minimax、test、small、medium、open 不回归。严格来说没有
  候选完全满足：A 仍输 small；B 输 minimax 和 small；C 输 medium 和
  minimax；D 输 minimax；E 输 small。A 是唯一同时达到 8 胜且 0 timeout
  的候选，因此只保留 A 的默认风险设置，继续用预算降级解决剩余回归，而
  不宣称第 1 轮已经全面通过门槛。

## 6. 第 2 轮调参：预算轴

第 2 轮恢复真实墙钟预算。首版默认配置
`mctsMinPlyBudgetSims=60,mctsTurnBudgetScale=1.0` 作为对照，再测试
禁止降级、提高降级阈值和扩大回合预算：

| 配置 | Min ply sims | Budget scale | 胜/12 | 总分 | 平均分 | Timeout/Error | original | medium2 |
|:--|--:|--:|--:|--:|--:|:--:|:--|:--|
| 首版/默认 | 60 | 1.0 | 7 | 12766 | 1063.83 | 0/0 | 1933，负 | 755，负 |
| R2-B | 0 | 1.0 | 7 | 11860 | 988.33 | 0/0 | 716，负 | 19，负 |
| R2-C | 120 | 1.0 | 7 | 13649 | 1137.42 | 0/0 | 3178，胜 | 755，负 |
| R2-D | 60 | 1.25 | 6 | 10622 | 885.17 | 0/0 | 3178，胜 | 755，负 |

禁用降级的 R2-B 使 medium2 从 755 降到 19，说明在低 simulation 预算的
大图上强行运行 MCTS 会明显退化。R2-D 虽让 original 获胜，但 medium 和
small 转负，总体降到 6 胜。R2-C 在 0 timeout/error 下保持 7 胜，取得本轮
最高总分和平均分，并让 original 从负转胜；medium2 虽未获胜，但没有像
R2-B 那样崩到 19 分。因此最终选择
`mctsMinPlyBudgetSims=120,mctsTurnBudgetScale=1.0`。

同一 R2-C 配置在单独 12 图快筛中为 7/12、总分 13649；在最终重跑的
72-case 文件中，固定 `cs188` 子集仍为 7/12，但总分变为 11302。两者
ghost seed 相同，胜数一致，分数差异仍说明墙钟截止会让不同并发负载下完成
不同数量的 simulations。固定 seed 单次分数不能替代 60 局泛化比较。

## 7. 历史基线、本次配对基线与最终 MCTS

| 数据来源 | 口径 | 胜/总局 | 胜率 | 总分 | 平均分 | Timeout/Error |
|:--|:--|--:|--:|--:|--:|:--:|
| 旧报告 Alpha-Beta | 固定 cs188，12 局 | 10/12 | 83.33% | 16991 | 1415.92 | 0/0 |
| 本次配对 Alpha-Beta | 固定 cs188，12 局 | 10/12 | 83.33% | 16004 | 1333.67 | 0/0 |
| 最终 MCTS | 固定 cs188，12 局 | 7/12 | 58.33% | 11302 | 941.83 | 0/0 |
| 旧报告 Alpha-Beta | 整数 seeds 0–4，60 局 | 37/60 | 61.67% | 69667 | 1161.12 | 0/0 |
| 本次配对 Alpha-Beta | 整数 seeds 0–4，60 局 | 37/60 | 61.67% | 70983 | 1183.05 | 0/0 |
| 最终 MCTS | 整数 seeds 0–4，60 局 | 30/60 | 50.00% | 58826 | 980.43 | 0/0 |

旧报告 60 局总分 69667 由该报告的 12 行“每图平均分 × 5”精确求和；旧报告
正文展示的平均分 1161.12 是四舍五入值。

固定 `cs188` 上，MCTS 比本次配对 Alpha-Beta 少 3 胜，胜率低 25 个
百分点，总分低 4702，平均分低 391.83。整数 seeds 0–4 上，MCTS 少
7 胜，胜率低 11.67 个百分点，总分低 12157，平均分低 202.62。旧报告与
本次配对 Alpha-Beta 的 60 局都为 37/60，说明 Alpha-Beta 的胜数结论在
两次记录间稳定；MCTS 两套口径都没有达到基线。

## 8. 固定 cs188：12 图逐图配对

| 布局 | MCTS 得分 | MCTS | Alpha-Beta 得分 | Alpha-Beta | MCTS 分差 |
|:--|--:|:--:|--:|:--:|--:|
| q2_capsuleClassic | -108 | 负 | 1262 | 胜 | -1370 |
| q2_contestClassic | 2257 | 胜 | 2650 | 胜 | -393 |
| q2_dangerClassic | -169 | 负 | 77 | 负 | -246 |
| q2_mediumClassic | 2277 | 胜 | 2061 | 胜 | +216 |
| q2_mediumClassic2 | 755 | 负 | 755 | 负 | 0 |
| q2_minimaxClassic | 516 | 胜 | 513 | 胜 | +3 |
| q2_openClassic | 1429 | 胜 | 1361 | 胜 | +68 |
| q2_originalClassic | 3178 | 胜 | 3178 | 胜 | 0 |
| q2_smallClassic | 261 | 负 | 1735 | 胜 | -1474 |
| q2_testClassic | 561 | 胜 | 524 | 胜 | +37 |
| q2_trappedClassic | 532 | 胜 | 532 | 胜 | 0 |
| q2_trickyClassic | -187 | 负 | 1356 | 胜 | -1543 |
| **合计** | **11302** | **7/12** | **16004** | **10/12** | **-4702** |

Alpha-Beta 只输 danger 和 medium2；MCTS 还输 capsule、small 和 tricky。
MCTS 只在 medium、minimax、open 和 test 上取得正分差，其中最大的
medium 也只有 +216，无法抵消 capsule、small、tricky 三图合计 -4387。

## 9. 整数 seeds 0–4：60 局逐图配对

每个布局各 5 局。平均分差定义为 MCTS 平均分减本次配对 Alpha-Beta
平均分。

| 布局 | MCTS 胜/5 | MCTS 平均分 | Alpha-Beta 胜/5 | Alpha-Beta 平均分 | 胜数差 | 平均分差 |
|:--|--:|--:|--:|--:|--:|--:|
| q2_capsuleClassic | 3/5 | 656.6 | 3/5 | 795.6 | 0 | -139.0 |
| q2_contestClassic | 4/5 | 1759.2 | 4/5 | 1593.8 | 0 | +165.4 |
| q2_dangerClassic | 0/5 | 428.8 | 1/5 | 779.0 | -1 | -350.2 |
| q2_mediumClassic | 2/5 | 1701.2 | 4/5 | 2015.0 | -2 | -313.8 |
| q2_mediumClassic2 | 0/5 | 836.8 | 0/5 | 1141.4 | 0 | -304.6 |
| q2_minimaxClassic | 5/5 | 516.0 | 5/5 | 513.2 | 0 | +2.8 |
| q2_openClassic | 4/5 | 281.8 | 5/5 | 974.0 | -1 | -692.2 |
| q2_originalClassic | 1/5 | 2300.0 | 1/5 | 2306.6 | 0 | -6.6 |
| q2_smallClassic | 3/5 | 1086.6 | 5/5 | 1615.0 | -2 | -528.4 |
| q2_testClassic | 5/5 | 529.6 | 5/5 | 539.6 | 0 | -10.0 |
| q2_trappedClassic | 2/5 | -89.0 | 2/5 | -88.4 | 0 | -0.6 |
| q2_trickyClassic | 1/5 | 1757.6 | 2/5 | 2011.8 | -1 | -254.2 |
| **合计/总体** | **30/60** | **980.43** | **37/60** | **1183.05** | **-7** | **-202.62** |

按 seed 汇总同样显示 MCTS 的劣势不是由单个 seed 偶然造成：

| Seed | MCTS 胜/12 | MCTS 平均分 | Alpha-Beta 胜/12 | Alpha-Beta 平均分 | 胜数差 | 平均分差 |
|--:|--:|--:|--:|--:|--:|--:|
| 0 | 6/12 | 865.92 | 8/12 | 963.00 | -2 | -97.08 |
| 1 | 7/12 | 1123.92 | 9/12 | 1422.08 | -2 | -298.17 |
| 2 | 6/12 | 1131.33 | 8/12 | 1363.75 | -2 | -232.42 |
| 3 | 5/12 | 740.50 | 7/12 | 1224.00 | -2 | -483.50 |
| 4 | 6/12 | 1040.50 | 5/12 | 942.42 | +1 | +98.08 |

MCTS 在 seeds 0–3 上每个 seed 都少 2 胜，平均分也全部较低；只有 seed 4
多 1 胜且平均高 98.08。四个 seed 方向一致的退化远大于一个 seed 的收益，
因此整体结论不是由单一异常轨迹造成。

## 10. Timeout、Error 与运行开销

最终结果：

- MCTS：固定 12 局和整数 60 局均为 0 timeout、0 error、0 draw。
- 本次配对 Alpha-Beta：固定 12 局和整数 60 局也均为
  0 timeout、0 error、0 draw。
- 作为 JSON 完整性核对，MCTS 72 局合计 37 胜、总分 70128、平均
  974.00；Alpha-Beta 72 局合计 47 胜、总分 86987、平均 1208.15。
  该 72 局数字只用于核对，
  不替代前面的两套正式口径。

最终 72-case 并行运行中：

| 策略 | 并发上限 12 的墙钟时间 | 各 case duration 求和 |
|:--|--:|--:|
| MCTS | 114.286s | 1276.360s |
| Alpha-Beta | 62.702s | 588.803s |

MCTS 不仅多 seed 成绩较低，运行开销也更高。

调参阶段的 timeout 只出现在固定 200 simulations 的第 1 轮：

- R1-C：original timeout；
- R1-D：original timeout；
- R1-E：tricky timeout；
- 首版、R1-A、R1-B 和全部第 2 轮配置均为 0 timeout/error。

`mctsIgnoreClock=1` 只忽略 MCTS 自己的逐回合 deadline，课程框架的整局
30 秒限制仍生效，因此固定 simulation 实验依然能够 timeout。这也是最终
配置保留真实墙钟停止条件的原因。最终重跑中 30 秒框架 timeout 和 45 秒
父进程硬 timeout 都没有触发，两个策略均为 0 timeout/error。

## 11. 分图分析

### 11.1 预期改善图

- **trapped**：固定 seed 下两者都为 532 分胜利；整数 seeds 中两者都是
  2/5，平均分仅差 -0.6。MCTS 对随机 ghost 的 chance 建模没有带来可测
  净收益。
- **tricky**：固定 seed 下 MCTS 为 -187/负，Alpha-Beta 为 1356/胜；
  整数 seeds 中 MCTS 为 1/5、平均 1757.6，Alpha-Beta 为 2/5、平均
  2011.8。首版和调参阶段偶尔出现的高分没有转化为最终稳定优势。
- **capsule**：固定 seed MCTS 为 -108/负，Alpha-Beta 为 1262/胜；整数
  seeds 虽同为 3/5，MCTS 平均仍低 139.0。死亡修正在第 1 轮消融中必要，
  但不足以让最终 chance 搜索稳定超过 Alpha-Beta。

### 11.2 大图与风险图

- **original**：固定 seed 两者同为 3178 分胜利；整数 seeds 同为 1/5，
  平均仅差 -6.6。提高降级阈值使这张图基本与 Alpha-Beta 持平，但没有
  形成额外胜局。
- **medium2**：两者都是 0/5；MCTS 平均 836.8，Alpha-Beta 为 1141.4。
  预算降级避免了 R2-B 的 19 分极端退化，但没有解决清图失败。
- **danger**：MCTS 为 0/5、平均 428.8，Alpha-Beta 为 1/5、平均 779.0；
  胜率和分数都退化，仍是两种策略共同的困难图。

### 11.3 稳定图与新增回归

- **minimax**：两种策略都为 5/5，MCTS 平均高 2.8，是最稳定的持平图。
- **contest**：两者都为 4/5，MCTS 平均高 165.4，是最终多 seed 中最明确
  的正向分数结果，但没有新增胜局。
- **test**：两者都为 5/5，MCTS 平均只低 10.0，基本持平。
- **open/small**：MCTS 分别从 5/5 降到 4/5 和 3/5，平均低 692.2 和
  528.4；small 固定 seed 也从 Alpha-Beta 的胜利变成 261/负，是主要回归。
- **medium**：MCTS 为 2/5，Alpha-Beta 为 4/5，说明退化并不只集中在
  最大地图。

## 12. 可复现命令

所有 Python 命令都从 starter 的 `commits/` 目录经 `uv` 运行：

```bash
cd /data/hongzefu/qmj-grid/commits

PYTHONPATH=. uv run --no-project --python 3.9 python \
  ../scripts/q2_eval.py \
  --seeds cs188,0,1,2,3,4 \
  --agent-args strategy=mcts,mctsMinPlyBudgetSims=120 \
  --jobs 12 \
  --out ../docs/q2-mcts-results.json

PYTHONPATH=. uv run --no-project --python 3.9 python \
  ../scripts/q2_eval.py \
  --seeds cs188,0,1,2,3,4 \
  --agent-args strategy=alphabeta \
  --jobs 12 \
  --out ../docs/q2-alphabeta-results.json
```

固定 simulation 的第 1 轮候选使用：

```text
strategy=mcts,mctsIgnoreClock=1,mctsMaxSims=200,...
```

评估脚本会同时生成逐 case JSON 和同名 Markdown 汇总，并在发现 timeout
或 error 时保留结果文件后返回非零退出码。

## 13. 结论与默认策略建议

最终 MCTS 的 72 个 case 全部正常完成，证明死亡修正、chance outcome、
epoch 安全树复用、预算降级和专用进程评估都能在硬预算内工作；但正确运行
不等于性能超过基线。

最终两套配对结果是：

- 固定 cs188：MCTS 7/12、平均 941.83；Alpha-Beta 10/12、平均 1333.67；
- 整数 seeds 0–4：MCTS 30/60、平均 980.43；Alpha-Beta 37/60、平均
  1183.05；
- MCTS 在 60 局中少 7 胜、平均低 202.62，并且运行墙钟更长。

因此当前证据不支持改变官方默认行为。**最终建议保持
`strategy='alphabeta'`，MCTS 继续作为显式
`-a strategy=mcts,mctsMinPlyBudgetSims=120` 的实验分支。**
只有在后续更多 seeds 上同时改善胜率、平均分和运行稳定性后，才应重新考虑
切换默认策略。
