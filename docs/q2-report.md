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

## 2. 最终算法

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
| V4（最终） | 将保护余量收紧到 0.05 秒 | evaluator 7/12 胜；总分 15386；平均 1282.17；medium2 内部计时 23.718205 秒 | 总分最高且低于 24 秒 |

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

## 5. 最终 12 图结果

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
