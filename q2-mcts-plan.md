# Q2 MCTS 实现、评估与对比报告计划

## 一、背景与目标

当前 [q2Agent.py](commits/agents/q2Agent.py) 的 Q2 策略是 alpha-beta + 迭代加深（depth 1–3）+ 24 秒整局内部预算 + 多级 fallback/走廊捷径/必败切 expectimax。用户要求：实现 MCTS 策略，在既定评估口径下跑完整评估，生成一份与现有方法的对比报告。

评估口径（与 docs/q2-report.md §9/§10.2 一致）：
1. **固定 seed 12 图**：等价 `-f`（`random.seed('cs188')`），12 张 `q2_*.lay` 各 1 局；
2. **多 seed 60 局**：整数 seeds 0–4，每个 seed 完整覆盖 12 图，每局单独重设全局 seed。

alpha-beta 基线成绩（文档已有）：固定 seed 10/12 胜、总分 16991、平均 1415.92；60 局 37 胜（61.67%）、平均 1161.12。

用户已确认：**有限调参**（首版后最多 2 轮关键参数调优）；报告放**独立新文件** `docs/q2-mcts-report.md`。

## 二、关键约束（调研结论）

- 只允许修改课程文件 `commits/agents/q2Agent.py`；`getAction(gameState)` 签名与 `@log_function` 不可动。仓库其他位置（scripts/、docs/）可新增文件。
- 官方 evaluator 不传 `-a`，因此 `strategy` 默认值必须保持 `'alphabeta'`，官方命令行为逐位不变。`-a strategy=mcts` 切换（所有参数值都是字符串）。
- **RNG 红线**：ghost（RandomGhost）从全局 `random` 流采样，agent 内绝不能调用任何模块级 `random` 函数，MCTS 一律用私有 `random.Random` 实例（`registerInitialState` 里按 `mctsSeed*1000003+局数` 重播种）。
- 性能刻度（实测）：一个完整 ply（1+N 次 generateSuccessor + 1 次 eval）在 smallClassic ≈114us、originalClassic ≈661us；大图真实回合预算仅 ~70ms（预算公式分母被食物数抬高）→ 朴素 MCTS 只有 ~35 次 simulation，必须做惰性扩展等优化。
- `hash(GameState)` 8~40us，热路径禁止用 GameState 当 dict 键；chance 边用 ghost 联合动作元组做键（免费转置合并）。
- `scaredTimer==1` 的 ghost 本 ply 致命（applyAction 半速 → decrementTimer 归零 snap → checkDeath），死亡概率计算必须复刻；ghost 合法动作彼此独立（联合分布可因子分解）。
- 评估运行环境沿用历史口径：`uv run --no-project --python 3.9`，cwd 必须是 `commits/`（`import_by_name("./agents", ...)` 相对路径）。

## 三、实现：q2Agent.py 的 MCTS 分支

设计形态：**Pac-Man 决策点单层树 + 联合 ghost 行动 chance 边 + 惰性扩展 + 评估函数做叶值（无 rollout）+ 一步精确死亡概率修正 + 跨回合树复用**。

### 3.1 数据结构
- `DecisionNode`（`__slots__`）：持有 GameState、legal actions、untried 队列、访问计数、边列表。
- `ActionEdge`：`pac_state = state.generateSuccessor(0, a)`（只生成一次）、缓存 `ghost_legals`（元组）、`outcomes: dict[joint_tuple -> DecisionNode]`、n/w/q 统计。
- outcome 渐进加宽：`max_outcomes = min(mctsMaxOutcomes, 1 + floor(sqrt(visits/mctsWidenC)))`，封顶后在已有 outcomes 中重采。

### 3.2 一次 simulation 四阶段
1. **选择**：根节点用 PUCT（先验 = 各子叶值 softmax，温度 `mctsPriorTemp`），树内部用 UCB1 + value init（子节点创建时用自身叶值初始化 Q，虚拟访问 1 次）；终局叶直接取 1.0/0.0。
2. **扩展（惰性）**：节点有未试动作时只展开一个（顺序：非 STOP > 延续朝向 > legal 顺序），评估后立即回传，本次 simulation 结束。
3. **chance 转移**：按真实均匀分布独立采样各 ghost 动作合成 joint 元组；已存在则零成本复用，否则按加宽准则顺序 apply（每个 ghost 一次 generateSuccessor，中途终局立即停）。
4. **回传**：路径上更新 n/w/q；chance 回传默认均值，可选 `(1-λ)·mean + λ·min`（`mctsRiskLambda`）。

### 3.3 叶值
```
win→1.0, lose→0.0
否则 v = 0.5 + 0.5*tanh((betterEvaluationFunction(s) - anchor)/mctsValueScale)
anchor = 本回合根状态的 eval（每回合一次）；再乘一步死亡修正 v *= (1 - p_death)
```
`_death_prob`：纯算术（零 generateSuccessor），利用 ghost 独立性对每个非 scared（含 timer==1 特判 snap）ghost 数出致命动作占比，`1 - Π(1-lethal/len(legal))`；用到 `Actions.directionToVector`（game.py）、`nearestPoint`（util.py）、`COLLISION_TOLERANCE`（pacman.py:264，已核实存在）。

### 3.4 时间预算与停止
- 完全复用现有 24s 框架（`_TOTAL_SEARCH_BUDGET`、turn_budget 公式、`finally` 记账）；新增 `mctsTurnBudgetScale`（默认 1.0）。
- 循环条件 `now + 1.2*单次simulation耗时EMA < deadline`；`_check_deadline` 保留在生成路径上做硬保险；`_SearchTimeout` 在 MCTS 分支是**软停止**（保留统计量返回动作，anytime）。
- 实验旋钮：`mctsMaxSims`（默认 0=不限）+ `mctsIgnoreClock`（默认 0）→ 无墙钟噪声的可复现配对实验。
- **预算感知降级**：`registerInitialState` 实测 ply 成本（~20 次 generateSuccessor 计时），估算每回合 simulation 数 < `mctsMinPlyBudgetSims`（默认 60）时该局自动走 alpha-beta 分支（不依赖布局名/坐标，合法自适应）。

### 3.5 最终动作选择与树复用
- robust child：按 `(isWin, not isLose, 访问数, Q, 非STOP, legal 顺序)` 取最优。
- 跨回合树复用（`mctsTreeReuse=1`）：回合末记住所选边的 outcomes；下回合用 `(pacman位置, 各ghost(位置,朝向,scaredTimer), numFood)` 签名元组快速匹配 + 一次 `==` 精确校验，命中则继承子树（根 state 替换为框架传入实例）。

### 3.6 现有工程件取舍（MCTS 分支下）
- 关闭：必败 expectimax（MCTS 原生建模随机 ghost）、`_evaluation_cache`/`_successor_cache`（hash 太贵，树即缓存）、初始分支深度阈值。
- 保留：走廊捷径（省预算）、循环守卫、reactive fallback、27s 紧急出口、`_fallback_action`（合并为根先验+超时兜底，只算一次）。
- alpha-beta 分支一字不改。

### 3.7 新增 `__init__` 参数（全部字符串默认值）
`strategy='alphabeta'`、`mctsSeed='20250824'`、`mctsCpuct='1.0'`、`mctsSelect='hybrid'`、`mctsPriorTemp='0.5'`、`mctsValueScale='100'`、`mctsMaxOutcomes='4'`、`mctsWidenC='4'`、`mctsDeathCorrection='1'`、`mctsRiskLambda='0.0'`、`mctsTreeReuse='1'`、`mctsMaxNodes='20000'`、`mctsMaxSims='0'`、`mctsIgnoreClock='0'`、`mctsTurnBudgetScale='1.0'`、`mctsMinPlyBudgetSims='60'`。（v1 不实现 rollout；`mctsRolloutDepth` 若后续调参需要再加。）

## 四、评估脚本：scripts/q2_eval.py（新增，入库）

历史多 seed 脚本在 /tmp 未入库，这次按 AGENTS.md 可复现要求写进仓库根 `scripts/q2_eval.py`：
- 用法：`cd commits && PYTHONPATH=. uv run --no-project --python 3.9 python ../scripts/q2_eval.py --seeds cs188,0,1,2,3,4 --agent-args strategy=mcts --jobs 12 --out <结果json>`（脚本内部 `sys.path` 兜底、校验 cwd）。
- **进程级并行**：60 个 case 彼此独立，用 `multiprocessing`（或逐 case 子进程）并行执行，`--jobs` 默认 12（本机 32 核、当前他人负载约 13，留余量防超订——agent 按墙钟计预算，CPU 超订会削弱棋力）。每个 worker 进程内 `random.seed(seed)` 作用于该进程自己的全局流，case 间确定性互不影响。60 局墙钟预计 5~8 分钟。MCTS 与基线用相同 `--jobs` 跑，保证配对公平。
- 每个 case：新建 agent 实例 → `random.seed(seed)`（cs188 为字符串，其余 int）→ `pacman.runGames`（`-q` 等价参数、`--timeout=30`、不带 `-f`）→ 记录 layout/seed/score/win/耗时/异常；worker 复用进程时 case 之间调用 `GameState.getAndResetExplored()` 防止 explored 集合累积内存。
- 输出：逐局 JSON + markdown 汇总表（每图胜数/平均分、总胜率、总平均分、timeout/error 计数），落到 `docs/` 下的数据文件或报告引用的路径。

## 五、运行协议

1. **冒烟**：`q2_testClassic`、`q2_trappedClassic`、`q2_originalClassic` 各 1 局固定 seed（`-a strategy=mcts`），确认能跑、不超时、original 触发降级逻辑正常。
2. **回归**：默认参数（不传 `-a`）跑固定 seed 12 图，确认 alpha-beta 行为与基线一致（10±1/12 量级）。
3. **MCTS 首版**：固定 seed 12 图快筛 → 完整 60 局。
4. **有限调参（最多 2 轮）**：每轮用固定 seed 12 图 +（必要时）`mctsIgnoreClock=1, mctsMaxSims=200` 的无噪声配对快筛选参（该模式下决策不依赖墙钟，并行跑也零噪声）：
   - 第 1 轮（风险轴）：`mctsDeathCorrection ∈ {0,1}`、`mctsRiskLambda ∈ {0,0.25,0.5}`、`mctsMaxOutcomes ∈ {2,4,8}` 的少量组合；判据：基线满胜的 minimax/test/small/medium/open 不回归。
   - 第 2 轮（预算轴）：`mctsMinPlyBudgetSims ∈ {0,60,120}`、`mctsTurnBudgetScale ∈ {1.0,1.25}`；判据：original/medium2 净收益且 0 timeout。
   - 选定配置跑最终完整 60 局。
5. **基线配对重跑**：同一脚本、同一 `--jobs` 跑 alpha-beta 60 局（并行下约 3~5 分钟），得到与 MCTS 严格同口径的配对数字（文档旧数字一并列出）。
6. **长任务纪律**：预计 >5 分钟的运行一律 `tmux new-session -d` + `tee` 日志 + Monitor（grep 过滤完成/Traceback/timeout 行）；≤5 分钟的用 `run_in_background`。所有 Python 命令走 `uv run`。

## 六、报告：docs/q2-mcts-report.md（新增）

结构：实验范围与口径 → MCTS 设计（变体选择理由、预算算术、死亡修正、树复用）→ 实现要点 → 实验过程（首版结果、调参轮次表、每轮判据与决策）→ **最终对比**（固定 seed 12 图逐图表 + 60 局逐图胜数/平均分表，MCTS vs alpha-beta 配对，含 timeout/error 计数）→ 分图分析（预期改善图 trapped/tricky/capsule 与风险图 original/medium2/danger 的实际表现）→ 结论与默认策略建议（默认保持 `alphabeta`，除非 MCTS 两套口径全面占优，此时在报告中给出切换建议交用户决定）。

## 七、提交（遵守 AGENTS.md + 全局规则）

- 提交前 `uv lock` 确认成功；`git status --short` 核对，只 `git add` 本轮文件：`commits/agents/q2Agent.py`、`scripts/q2_eval.py`、`docs/q2-mcts-report.md`、`docs/commits/commit7.md`（如 lock 变化含 `uv.lock`）。
- commit message 沿用 `commit7：...` 体例，正文含"用户指令原文 / 形式化计划 / 运行命令与结果"，`docs/commits/commit7.md` 同步详版（分节叙述、实测数字、意外与处置、当前状态与下一步）。
- 结尾加 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。

## 八、验证清单

- 官方口径不变性：不传 `-a` 时 `uv run --no-project --python 3.9 pacman.py -l layouts/q2_testClassic.lay -p Q2_Agent --timeout=30 -q -f` 结果与基线一致。
- `-a strategy=mcts` 下 12 图固定 seed 全部正常结束，0 timeout / 0 error / 0 异常栈。
- 同一命令跑两遍（`mctsIgnoreClock=1, mctsMaxSims` 固定时）结果逐位一致（确定性验证）。
- 60 局评估 0 timeout / 0 error；报告中的每个数字都能对应到日志文件。
- `uvx --from ruff ruff check agents/q2Agent.py` 通过（沿用仓库既有检查习惯）。
