# commit8：实现 Q2 MCTS、并行评估与配对报告

## 用户指令原文

用户提供仓库级 AGENTS.md 约束，并要求：

1. 「q2-mcts-plan.md：完整计划（MCTS 设计、并行评估脚本、有限调参、报告与提交规范）。」
2. 「实现」

本次以仓库根目录 q2-mcts-plan.md 作为权威执行源。外部 Claude 链接受
robots/safe-open 限制无法直接读取；仓库内同名文件完整且已由 commit7
记录来源，因此没有依赖外部页面继续执行。

## 形式化计划

1. 保持官方默认 Q2 Alpha-Beta 路径不变，在
   commits/agents/q2Agent.py 中增加 strategy=mcts 可切换分支。
2. 实现 Pac-Man 决策节点、联合 ghost chance 边、惰性扩展、根 PUCT、
   内部 UCB1、渐进加宽、叶值归一化、一步死亡概率修正、风险回传、私有
   RNG、跨回合树复用和 24 秒整局预算。
3. 用实测 ply 成本做预算感知降级；低估的 simulation 数不足时整局回退到
   既有 Alpha-Beta，不读取布局名或坐标。
4. 新增 scripts/q2_eval.py：每个 layout/seed 使用一个专用 spawn 进程，
   进程内重设全局 seed，父进程并发上限 12，并同时记录课程 30 秒 timeout
   和 45 秒进程硬上限。
5. 先做三图冒烟、默认回归、固定 simulation 确定性与定向正确性测试，再按
   计划完成最多两轮有限调参。
6. 用相同脚本、相同 jobs=12 分别重跑最终 MCTS 与 Alpha-Beta：
   固定 cs188 的 12 局，以及整数 seeds 0–4 的 60 局。
7. 将逐 case JSON、协议分离 Markdown、完整对比报告和本审计记录入库；
   默认策略只有在 MCTS 两套口径全面占优时才考虑切换。

## 实现内容

### Q2 Agent

- 默认 strategy=alphabeta；显式 strategy=mcts 才进入新分支。
- DecisionNode 和 ActionEdge 均使用 slots，热路径不以 GameState 为字典键。
- 根节点 PUCT、内部 UCB1；chance 边按私有 RNG 独立均匀采样 ghost 联合
  动作，并用联合动作元组复用 outcome。
- outcome 上限为
  min(mctsMaxOutcomes, 1 + floor(sqrt(visits / mctsWidenC)))。
- win/lose 叶值为 1/0；普通叶值以当前回合根评估为 anchor，经 tanh 映射
  到 0–1。
- 死亡概率使用纯算术计算，复刻 scaredTimer=1 的半速移动、nearestPoint
  吸附、timer 归零和碰撞顺序，零次额外 successor。
- MCTS 只使用 random.Random 私有实例；每局按
  mctsSeed * 1000003 + game_count 重播种，不消费 RandomGhost 的全局随机流。
- 跨回合复用签名匹配后再做 GameState 精确比较；新 root anchor 下通过
  stats epoch 保留状态结构但重置旧尺度统计。
- 正常根扫描对每个 Pac-Man 后继只生成一次；扫描是最多 5 个动作的原子安全
  阶段。根未完全进入树时返回已完整检查的 fallback。
- edge 完整构造成功后才删除 untried 动作，timeout 不会永久丢合法动作。
- 注册与运行共用相同回合预算公式；NaN/Inf 参数在构造时 fail-fast。

### 并行评估

- scripts/q2_eval.py 只接受从 commits/ 目录运行。
- 每个 case 新建 Q2_Agent 和 ghost agents，并在 runGames 前执行
  random.seed(seed)。
- 每个 case 使用独立 spawn 进程；父进程同时维护最多 jobs 个进程。
- 课程框架 timeout 默认 30 秒；父进程硬墙钟上限为
  max(timeout + 15, timeout * 1.5)，默认 45 秒。
- 记录 score、win/loss/draw、agent time、duration、remaining food、
  timeout、crash、异常栈和输出尾部。
- JSON schema v2 分别汇总固定 cs188 与整数 seeds，另保留逐布局、逐 seed
  和全部请求合计。
- 元数据记录基础 Git HEAD、dirty status、uv/Python 版本、uv 复现命令，
  以及 q2Agent.py、q2_eval.py、uv.lock 的 SHA-256。

## 实际运行命令与结果

### 环境、语法与静态检查

    which uv
      -> /home/hongzefu/.local/bin/uv

    uv run --no-project --python 3.9 python -m py_compile agents/q2Agent.py ../scripts/q2_eval.py
      -> exit 0

    uvx --from ruff ruff check agents/q2Agent.py
      -> exit 0，All checks passed!

    uvx --from ruff ruff check --target-version py39 agents/q2Agent.py ../scripts/q2_eval.py
      -> exit 0，All checks passed!

    git diff --check
      -> exit 0

首次 Ruff 检查真实发现 33 个问题，主要是 slots 顺序、脚本 shebang、导入
顺序、Python 版本注解和异常捕获标注；第一次修正后剩 23 个，第二次剩
9 个，最后全部清零。所有失败均发生在静态检查阶段，没有产生运行结果。

### 正确性定向测试

1. 私有 RNG：

       mctsIgnoreClock=1,mctsMaxSims=40,mctsMinPlyBudgetSims=0
       -> action=East
       -> global_rng_unchanged=True
       -> root_visits=41，nodes=18

2. 死亡概率与引擎穷举：

       scaredTimer=0 -> exact=1/3，observed=1/3
       scaredTimer=1 -> exact=1.0，observed=1.0
       scaredTimer=2 -> exact=0.0，observed=0.0

3. 边界：

       mctsMaxNodes=1 -> node_count=1，返回合法 East
       0 ghost -> 返回合法 East
       tree reuse -> exact match=True，stats epoch 1 -> 2

4. 代码审查问题复测：

       partial root immediate-win / safe fallback -> 均返回 East
       deadline before expansion -> untried 3 -> 3，edges=0
       root successor generation -> 3 个合法动作各生成一次
       startup/runtime turn budget -> 均为 0.35
       mctsWidenC=nan -> ValueError: mctsWidenC must be finite
       slow root successor 6ms、turn budget 5.5ms
         -> chosen=East，chosen_is_loss=False，simulation_calls=0

5. 固定 simulation 确定性：

       同一 q2_testClassic 完整单局连续运行两次
       -> 两次均 559 分、胜
       -> 删除 duration_seconds 和 agent_time_seconds 后逐字段相同：true

6. 官方默认无参数回归：

       uv run --no-project --python 3.9 pacman.py -l layouts/q2_testClassic.lay -p Q2_Agent --timeout=30 -q -f
       -> exit 0，524 分，Win，pathLength=111

7. 评估脚本 timeout 冒烟：

       --timeout 1 --layouts q2_originalClassic --agent-args strategy=alphabeta
       -> 结果 JSON/Markdown 正常落盘
       -> status=timeout，timeouts=1，errors=0，脚本按设计 exit 1

### 三图冒烟

    --seeds cs188 --layouts q2_testClassic,q2_trappedClassic,q2_originalClassic --agent-args strategy=mcts --jobs 3

结果：test=563/胜、trapped=532/胜、original=3178/胜，0 timeout、
0 error。独立测量确认 original 的预算估算触发 Alpha-Beta 降级。

### 第 1 轮有限调参：风险轴

统一使用 mctsIgnoreClock=1,mctsMaxSims=200、固定 cs188 的 12 图：

| 候选 | Death | Risk | Outcomes | 完成 | 胜 | 平均分 | Timeout |
|:--|--:|--:|--:|--:|--:|--:|--:|
| A | 1 | 0 | 4 | 12 | 8 | 1110.58 | 0 |
| B | 0 | 0 | 4 | 12 | 5 | 878.75 | 0 |
| C | 1 | 0.25 | 4 | 11 | 5 | 782.55 | 1（original） |
| D | 1 | 0.5 | 2 | 11 | 8 | 1041.09 | 1（original） |
| E | 1 | 0 | 8 | 11 | 7 | 904.36 | 1（tricky） |

决策：关闭死亡修正明显退化；风险最小值混合与更大 outcome 上限没有稳定
收益并出现 timeout。保留 Death=1、Risk=0、Outcomes=4。

### 第 2 轮有限调参：预算轴

| 配置 | Min sims | Scale | 胜/12 | 总分 | 平均分 | Timeout/Error |
|:--|--:|--:|--:|--:|--:|:--:|
| 首版 | 60 | 1.0 | 7 | 12766 | 1063.83 | 0/0 |
| R2-B | 0 | 1.0 | 7 | 11860 | 988.33 | 0/0 |
| R2-C | 120 | 1.0 | 7 | 13649 | 1137.42 | 0/0 |
| R2-D | 60 | 1.25 | 6 | 10622 | 885.17 | 0/0 |

决策：选择 mctsMinPlyBudgetSims=120、mctsTurnBudgetScale=1.0。该配置使
original 快筛转胜，避免禁用降级时 medium2 降到 19 分。

### 最终 72 局 MCTS

    uv run --no-project --python 3.9 python ../scripts/q2_eval.py --seeds cs188,0,1,2,3,4 --agent-args strategy=mcts,mctsMinPlyBudgetSims=120 --jobs 12 --out ../docs/q2-mcts-results.json

结果：

- 固定 cs188：7/12，58.33%，总分 11302，平均 941.83。
- 整数 seeds 0–4：30/60，50.00%，总分 58826，平均 980.43。
- 72 case 合计：37/72，总分 70128，平均 974.00。
- 0 timeout、0 error、0 draw；墙钟 114.286 秒。

### 最终 72 局 Alpha-Beta 配对

    uv run --no-project --python 3.9 python ../scripts/q2_eval.py --seeds cs188,0,1,2,3,4 --agent-args strategy=alphabeta --jobs 12 --out ../docs/q2-alphabeta-results.json

结果：

- 固定 cs188：10/12，83.33%，总分 16004，平均 1333.67。
- 整数 seeds 0–4：37/60，61.67%，总分 70983，平均 1183.05。
- 72 case 合计：47/72，总分 86987，平均 1208.15。
- 0 timeout、0 error、0 draw；墙钟 62.702 秒。

结论：MCTS 在固定口径少 3 胜，在 60 局口径少 7 胜，且运行更慢，所以
保持默认 strategy=alphabeta。MCTS 作为显式实验分支保留。

### 结果快照完整性

    sha256sum commits/agents/q2Agent.py scripts/q2_eval.py uv.lock

结果：

    eaa2fa3cd42408df30b8741baa504175f11dafbf32a6643e3c747a48458f7b49  commits/agents/q2Agent.py
    a8b5eb929441a06cf16d5f95639a1ad5a4d3e16f5d46abf850ee10fa55921795  scripts/q2_eval.py
    f1a0682ce353b609372af7a4093d572249a1dfc54d90ad924ef481f031ec8dd8  uv.lock

两份 schema v2 JSON 中的三项哈希与上述磁盘值完全一致；每份都有 72 个
唯一 case，且 summary 的 timeout/error 均为 0。

## 真实失败、意外与处置

1. 初始只读 shell 命令受运行环境影响失败：

       bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted

   随后所有必要命令通过经审批的沙箱外执行重跑成功。内置 apply_patch
   也曾受同一 bwrap 错误阻断，之后改为在沙箱外启动 apply_patch 并经
   stdin 发送补丁。

2. 外部 Claude 页面读取被 safe-open/robots 拒绝。仓库内
   q2-mcts-plan.md 完整存在，并由 commit7 记录来源，因此改用本地计划。

3. 首次评估脚本冒烟失败：

       TypeError: unsupported operand type(s) for |: 'type' and 'type'

   原因是 Python 3.9 会在运行时求值 Seed = int | str。修复为
   typing.Union 后重跑成功，仍保持 Python 3.9 兼容。

4. 第 1 轮 C、D、E 按设计返回 exit 1，因为各有一个课程框架 timeout。
   JSON 和 Markdown 均先完整落盘，timeout 被正确记录；这些失败是调参
   证据，不是丢失结果。

5. 评估基础设施审查发现早期 JSON 只记录 dirty HEAD，且 Markdown 把
   cs188 与整数 seeds 混为 72 局。随后升级 schema v2，加入文件哈希、
   dirty status、uv 复现命令和两套独立协议汇总，并用最终脚本重跑两份
   72-case 结果。

6. MCTS 审查定向复现了 partial-root fallback、deadline 先 pop、根后继
   重复生成、注册/运行预算括号不一致、NaN 延迟崩溃和慢后继 fallback
   风险。逐项修复并复测通过后，才运行最终结果。

7. 多次把含 Markdown 反引号的长补丁直接放入 JavaScript 模板字符串时，
   编排层分别出现 Unexpected identifier 或 Unexpected token 语法错误。
   这些失败发生在补丁送入 apply_patch 之前，没有修改文件；后续改为避免
   模板反引号并成功应用。

8. 在 commit8.md 创建前执行的只读存在性检查按预期返回：

       rg: docs/commits/commit8.md: No such file or directory
       ls: cannot access 'docs/commits/commit8.md': No such file or directory

   随后由本次补丁创建本文件。

## 当前状态

- 最终建议：官方默认继续使用 Alpha-Beta；MCTS 只作为显式实验分支。
- 最终结果文件、报告和评估脚本均已落盘。
- 本记录创建后仍需执行最终 uv lock、git status、待提交差异/远程检查和
  git commit；这些命令的真实结果写入提交信息，不在此提前伪造。
