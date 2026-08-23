# Q2 Adversarial Search 实验报告

## 1. 实验范围与环境

本项目只实现 Part 2 / Question 2。官方 starter 来自 `commits.7z`，归档 SHA-256 为：

```text
27e195b3f68a3f9a4357f86b7890d14c4665ecd8bc5752e70dedd48f9e3185a5
```

解压后的 starter 版本为 `v1.001`。课程源码中只修改了 `commits/agents/q2Agent.py`，没有修改游戏引擎、ghost、布局或 evaluator。

实验环境：

- Python 3.9.25，由 `uv` 提供和运行。
- Q2 公开布局共 12 张。
- 正式比较均使用 `-f` 固定随机种子。
- `--timeout=30` 是 Pac-Man 整局所有 `getAction` 的累计计算时间上限。
- evaluator 仅运行 Q2：`--q1a --q1b --q1c`。

本地公开布局结果不等同于服务器隐藏实例成绩。

## 2. 第一阶段算法基础

### 2.1 多 Agent Alpha-Beta

Pac-Man 固定为 agent 0，是 maximiser；其余 agent 均动态读取并作为 minimiser。递归使用：

- `getLegalActions(agentIndex)` 获取动作。
- `generateSuccessor(agentIndex, action)` 生成后继。
- `getNumAgents()` 支持任意 ghost 数量。
- `isWin()`、`isLose()`、深度截止和无合法动作作为叶节点条件。

深度按完整轮次计算：Pac-Man 行动后，所有 ghost 依次行动；只有最后一个 ghost 行动完、控制权回到 Pac-Man 时才减少一层剩余深度。max 节点更新 alpha，min 节点更新 beta，满足 `value >= beta` 或 `value <= alpha` 时立即剪枝。

### 2.2 迭代加深与确定性动作选择

每次 `getAction` 按 depth 1、2、3 迭代。只有一层完整搜索结束后才更新最佳动作；若 deadline 在下一层中途触发，则返回上一层完整结果。

动作排序会先生成一次后继，并用完整评估函数排序：Pac-Man 优先高分，ghost 优先低分。上一层根动作在下一层优先展开。最终平局不受排序影响：优先非 `STOP`，再保持 `getLegalActions` 的原始顺序。实现不调用随机函数，因此不会改变 `RandomGhost` 使用的全局随机序列。

### 2.3 整局时间预算

Agent 内部总预算为 24 秒，并留出 0.05 秒保护余量。每回合预算为：

```text
min(0.35 秒, 剩余内部预算 / max(12, ceil(1.5 × 剩余食物数)))
```

`registerInitialState` 会在每局开始时重置累计时间。预算不足 5 毫秒时直接返回合法 fallback。fallback 先以 O(1) 方式选择第一个非 `STOP` 合法动作；只有设置 deadline 且仍有预算时，才用完整评估函数改善 fallback。这样即使深搜索预算耗尽，后续回合也不会继续进行无界评估。

### 2.4 评估函数

最终评估值以游戏原始 score 为基础：

- win：`1_000_000 + score`。
- lose：`-1_000_000 + score`。
- 食物：`-4 × 剩余数量 - 1.5 × 最近食物 Manhattan 距离`。
- 胶囊：`-12 × 剩余数量 - 0.5 × 最近胶囊 Manhattan 距离`。
- 活跃 ghost：距离不超过 1 时减 200，距离为 2 时减 60，更远时减 `10 / distance`。
- scared ghost：若能在 `scaredTimer` 内追上，则增加 `80 / (distance + 1)`。

距离使用 Manhattan distance，避免在大量叶节点执行 BFS。

## 3. 迭代过程与回归分析

| 迭代 | 主要变化 | 关键结果 | 决策 |
|:--|:--|:--|:--|
| 基线 | 官方 `q2Agent.py` 仍调用 `util.raiseNotDefined()` | 无法运行 Q2 | 实现 alpha-beta |
| V1 | 完整评估排序、iterative deepening、24 秒预算 | evaluator 8/12 胜；总分 15235；平均 1269.58 | 保留算法主体 |
| V1 边界检查 | 在 `mediumClassic2` 读取 Agent 内部计时 | 24.008375 秒，超过目标约 8 毫秒 | 必须硬化预算 |
| V2 | 排序改为只看 score、终局和 ghost 距离的廉价键 | contest 得分仍为 2274，耗时 2.978→2.124 秒；但 medium2 得分 1420→21 | 得分严重退化，撤销 |
| V3 | 恢复完整排序；O(1) fallback；保护余量 0.25 秒 | evaluator 7/12 胜；总分 14005；平均 1167.08；medium2 内部计时 23.519567 秒 | 预算安全但过于保守 |
| V4（第一阶段提交版本） | 将保护余量收紧到 0.05 秒 | evaluator 7/12 胜；总分 15386；平均 1282.17；medium2 内部计时 23.718205 秒 | 作为第二阶段优化基线 |

V2 表明“更快完成更深 minimax”不一定提高实际分数。评分环境中的 ghost 是随机控制，但搜索规范要求把 ghost 当 minimiser；更深的最坏情况策略可能对实际随机轨迹过于保守。完整评估排序虽然更贵，却在公开地图上形成了更好的搜索截止位置和实际策略。

V3 到 V4 的比较表明，保护余量过大也会改变可完成的迭代层数。最终 0.05 秒余量结合 O(1) fallback，既避免超过 24 秒，也保留了更多有效搜索。

## 4. 深度与评估函数消融

固定布局 `q2_contestClassic.lay`、固定随机种子：

| 配置 | 得分 | 胜负 | 墙钟时间 |
|:--|--:|:--:|--:|
| better evaluation，depth 1 | 1657 | 胜 | 0.190 秒 |
| better evaluation，depth 2 | 1997 | 胜 | 1.274 秒 |
| better evaluation，depth 3 | 2274 | 胜 | 2.978 秒 |
| score-only evaluation，depth 3 | -43 | 负 | 6.373 秒 |

在该图上，更深搜索持续提高分数；仅使用 GUI score 的评估函数会忽略局部食物、胶囊和 ghost 风险，最终死亡。综合评估函数是主要增益来源。

## 5. 第一阶段 12 图结果

最终命令运行总耗时约 2 分 1 秒，退出码为 0；没有出现 timeout、crash、Traceback 或未捕获异常。

| 布局 | 得分 | 胜率 |
|:--|--:|:--:|
| `q2_mediumClassic.lay` | 2462 | 1/1 |
| `q2_smallClassic.lay` | 1735 | 1/1 |
| `q2_mediumClassic2.lay` | 1550 | 0/1 |
| `q2_originalClassic.lay` | 1790 | 0/1 |
| `q2_trappedClassic.lay` | -501 | 0/1 |
| `q2_contestClassic.lay` | 2274 | 1/1 |
| `q2_testClassic.lay` | 524 | 1/1 |
| `q2_minimaxClassic.lay` | 513 | 1/1 |
| `q2_trickyClassic.lay` | 2340 | 0/1 |
| `q2_dangerClassic.lay` | 77 | 0/1 |
| `q2_capsuleClassic.lay` | 1261 | 1/1 |
| `q2_openClassic.lay` | 1361 | 1/1 |

汇总：

- 7 胜、5 负。
- 总分：15386。
- 平均分：1282.17。
- 相比 V1，总分增加 151（约 0.99%），但胜局减少 1。

`trappedClassic` 是典型的 minimax 必败情形：在最坏情况假设下，延迟死亡会继续承受每步 -1，因此 agent 可能选择更快结束。该结果不表示递归或合法动作错误。

## 6. 正确性与可复现性验证

已完成以下验证：

- Python 3.9.25 实际导入，默认 depth 为 3，默认评估函数为 `betterEvaluationFunction`。
- Ruff 检查通过。
- 内存假树覆盖 1、2、4 个 ghost，验证 agent 轮转、完整轮次深度、max/min 值、剪枝和合法返回。
- 验证 depth 1 已完成、depth 2 中途超时时仍返回 depth 1 结果。
- 验证预算耗尽时不进入深搜索，仍返回合法 fallback。
- 12 张布局的初始状态和所有 Pac-Man 合法一步后继均得到有限数值。
- 评估函数覆盖空食物、空胶囊、无 ghost、ghost 重合和 scared ghost，不发生除零或空列表错误。
- 最终代码下，direct run 与 evaluator 对 `mediumClassic2` 都得到 1550，对 `trickyClassic` 都得到 2340。
- 验证产生的 `__pycache__` 已清理，不纳入提交。

由于迭代加深以墙钟 deadline 为安全边界，在不同机器或高负载下，刚好位于 deadline 附近的更深层可能完成或中断。因此固定 seed 能固定 ghost 随机轨迹，但不能理论上保证跨硬件逐动作完全相同。0.05 秒余量和“只采用完整迭代”的规则降低了这种影响。

## 7. 复现命令

```bash
which uv

cd /data/hongzefu/qmj-grid/commits

uv run --no-project --python 3.9 pacman.py \
  -l layouts/q2_testClassic.lay \
  -p Q2_Agent --timeout=30 -q -f

uv run --no-project --python 3.9 \
  --with pandas --with tqdm --with tabulate \
  evaluator.py --q1a --q1b --q1c

uvx --from ruff ruff check agents/q2Agent.py
```

运行 evaluator 时，在确认提示中输入 `y`。

## 8. 第二阶段：成功率优化

第二阶段采用双轨验证：一组严格使用课程 -f 固定 seed；另一组在同一 12 张地图上使用预先确定的多个 seed。所有候选均保持 getAction(gameState) 接口不变，不修改地图、ghost 或模拟器。

### 8.1 原始多 seed 基线

第一阶段代码在 seeds 0、1、2 的 36 局 paired 基线为：

- 17/36 胜，胜率 47.22%。
- 平均分 849.75。
- 0 timeout、0 error。

### 8.2 候选消融

| 候选 | 关键证据 | 决策 |
|:--|:--|:--|
| 等价 ghost 排序 + evaluation cache | 固定均分 1224.58→1332.00；多 seed 17→18 胜；运行时间下降 | 保留 |
| 生成后继缓存 | 复用迭代加深中的同一状态后继，不改变状态值 | 保留 |
| 削减深搜索预算换 strong fallback | medium2 固定 1994→1415 | 撤销 |
| 全局 maze distance | contest、danger、medium2、open 均明显下降 | 撤销 |
| dangerScale=2.0 | 15 局成功数不变，tricky 均分下降 | 撤销 |
| 全局胶囊权重加倍 | capsule 2/5→4/5 胜，但 medium2 固定 1994→478 | 撤销 |
| 情境胶囊权重 | capsule 没有净增胜局，且大图回归 | 撤销 |
| 提前 endgame 权重 | open 出现 3258 回合循环并由胜转负 | 撤销 |
| 纯 expectimax | trapped 转胜，但 medium/open 由胜转负 | 撤销 |
| 全局 mean/min 混合 | ghostMeanWeight=0.25 仍丢 medium/open | 撤销 |
| alpha-beta 必败门控 expectimax | trapped 固定 -501→532；20 seeds 获得 8 胜，普通状态不触发 | 保留 |
| reactive fallback，不削减深搜索 | 固定 tricky 负→3040/胜；多 seed 大图均分提高 | 保留 |
| 安全直走廊快捷规则 | 固定 original 转胜；多 seed 成功率显著提高 | 保留 |
| cycle guard + 最少访问 fallback | open seed0 从超长失败变为完成清图 | 保留 |
| 全局 depth 2 | 固定与多 seed 胜数未提高，固定均分下降 | 撤销 |
| 每回合分支自适应深度 | 额外开销导致 open/original 固定转负 | 撤销 |
| 每局初始化一次的分支阈值 | 高初始联合分支时使用 depth 2，无每回合开销 | 保留 |

### 8.3 最终新增机制

- **等价 ghost 排序**：同一 ghost node 的 food、capsule 和 Pac-Man 位置不变，因此只计算 score、terminal 和 ghost 风险。254 组真实 sibling 与完整排序一致。
- **evaluation/successor cache**：每次 getAction 缓存状态评估和状态后继，减少 depth 1/2/3 重复工作。
- **forced-loss expectimax**：正常动作始终由严格 alpha-beta 选择；只有完整 alpha-beta 已证明终局级必败时，才在同一已完成深度用均匀 ghost 期望寻找逃生机会。
- **安全走廊快捷规则**：直走/反向且 active ghost 距离大于 6 时，先完成 depth1 alpha-beta 安全搜索；非终局级必败时才采用直走规则。scaredTimer≤1 按 active 处理。
- **cycle guard**：记录自上次吃豆后的访问位置；重复或长期无进展时禁用走廊快捷，预算耗尽时选择较少访问的安全后继。
- **reactive fallback**：深搜索预算耗尽后、总内部时间低于 27 秒时，每回合最多 3ms 枚举一步 ghost 回复。
- **初始化复杂度深度**：仅在每局开始计算一次联合分支；超过 64 时最大深度为 2，否则保持 3。

## 9. 当前最终官方 evaluator 结果

发布安全版运行官方 evaluator，退出码 0，总耗时约 1 分 36 秒，没有 timeout、crash、Traceback 或未捕获异常。

| 布局 | 得分 | 胜率 |
|:--|--:|:--:|
| q2_mediumClassic | 2061 | 1/1 |
| q2_smallClassic | 1735 | 1/1 |
| q2_mediumClassic2 | 755 | 0/1 |
| q2_originalClassic | 3064 | 1/1 |
| q2_trappedClassic | 532 | 1/1 |
| q2_contestClassic | 2650 | 1/1 |
| q2_testClassic | 524 | 1/1 |
| q2_minimaxClassic | 513 | 1/1 |
| q2_trickyClassic | 2457 | 1/1 |
| q2_dangerClassic | 77 | 0/1 |
| q2_capsuleClassic | 1262 | 1/1 |
| q2_openClassic | 1361 | 1/1 |

汇总：**10 胜、2 负，成功率 83.33%**；总分 16991，平均 1415.92。相比第一阶段提交版本，成功数从 7 增至 10，总分从 15386 增至 16991。

## 10. 固定 seed 与最终多 seed 泛化

### 10.1 固定 seed

发布安全版的两次独立完整运行分别为9/12和官方 evaluator 10/12；稳定失败是 danger、medium2，original 会在最后少量 food 附近因墙钟 deadline 出现胜负波动。所有运行均为0 timeout、0 error。

发布硬化前还运行过同一 cs188 seed 三次、共36局，得到28/36胜；该数据用于估计时钟方差，不作为发布版最终口径。

### 10.2 发布安全版多 seed

使用预先确定的整数 seeds 0–4，每个 seed 完整覆盖全部12图，共60局：

- **37/60 胜，胜率61.67%。**
- 平均分1161.12。
- 0 timeout、0 error。

| 布局 | 胜数/5 | 平均分 |
|:--|--:|--:|
| capsule | 3/5 | 795.6 |
| contest | 4/5 | 1593.8 |
| danger | 0/5 | 589.2 |
| medium | 5/5 | 2162.0 |
| medium2 | 0/5 | 1054.8 |
| minimax | 5/5 | 513.2 |
| open | 5/5 | 952.0 |
| original | 1/5 | 2332.4 |
| small | 5/5 | 1615.0 |
| test | 5/5 | 539.6 |
| trapped | 2/5 | -88.4 |
| tricky | 2/5 | 1874.2 |

在相同 seeds0–2 的 paired comparison 中，发布安全版从第一阶段17/36胜、均分849.75，提高到23/36胜、均分1178.42。

### 10.3 优化阶段更大样本

发布硬化前的最优成功率候选曾在seeds0–9、120局中得到77胜（64.17%）、均分约1165.07、0 timeout/error。之后为确保每回合先执行depth1 adversarial safety search、修正scaredTimer=1边界并扩大框架时间余量，发布版采用更保守规则；因此120局数据只作为跨10 seeds的过拟合检查，不冒充最终发布版统计。

## 11. 最终限制

- danger 和 medium2 在 10 seeds 中仍没有清图，是当前最明确瓶颈。
- 搜索使用墙钟 deadline；相同 RNG seed 在不同负载下可能完成不同迭代深度，因此分数和 original 残局存在波动。
- 走廊/cycle fallback 优先成功率，个别 open 轨迹虽然胜利但路径较长、score 较低。
- 所有规则只读取公开 GameState 信息和模拟器稳定机制，不读取 RNG 状态，不使用布局名、坐标或 seed 特判。
