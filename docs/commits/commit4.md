# commit4 可复现记录

## 用户指令原文

用户要求执行已确认计划：

> PLEASE IMPLEMENT THIS PLAN:

计划要求：只在 `commits/agents/q2Agent.py` 实现得分优化版多 Agent alpha-beta；使用综合评估、iterative deepening、动态 ghost、确定性 tie breaking 和 24 秒内部预算；运行单图、12 图 evaluator、深度/评估消融与超时验证；形成独立 `commit4` 并推送 private 远程。

用户补充：

> policy必只能动agents/q2Agent.py

在验证过程中，用户又要求：

> 把你的迭代结果也写入报告

## 形式化计划

1. 只修改课程源码 `commits/agents/q2Agent.py`；外层仅增加中文实验报告和本提交审计记录。
2. 保留原始 `scoreEvaluationFunction`，新增综合评估函数并设为默认。
3. 实现支持任意 ghost 数量的 alpha-beta；最后一个 ghost 行动后才推进完整轮次深度。
4. 采用 depth 1→2→3 迭代加深、完整迭代提交、动作排序、稳定平局规则和合法 fallback。
5. 维护整局 24 秒内部预算，并给每回合分配动态 deadline；预算耗尽后快速返回合法动作。
6. 使用 Python 3.9、内存假树、评估边界、代表地图、全部 12 图 evaluator 和消融实验验证。
7. 根据真实结果迭代，但保留所有失败和退化尝试，不伪造结果。
8. 将算法、迭代、回归和最终成绩写入 `docs/q2-report.md`。
9. 每次文件变化后运行 `uv lock`；提交前检查源码范围、报告、凭据、缓存、private 远程和 Git 状态。

## 运行命令与结果

### 1. 实现与补丁过程

目标实现包括：

- `betterEvaluationFunction`：胜负、score、食物、胶囊、active/scared ghost。
- `_SearchTimeout` 和每节点 deadline 检查。
- 动态多 ghost alpha-beta、完整轮次深度和 `alpha >= beta` 剪枝。
- depth 1→2→3 iterative deepening。
- 不调用随机函数的动作排序与 tie breaking。
- 24 秒整局预算、动态单回合预算和合法 fallback。

真实失败：

- 两次 `apply_patch` 更新 `commits/agents/q2Agent.py` 均因环境内部 `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted` 失败，未修改文件。
- 第一次自动生成的全文件 `git apply --unidiff-zero` 因原始文件没有末尾换行而返回 `patch does not apply`；工作区 blob 与 commit3 blob 均为 `ed253209c798e53fd3fcf0138f0aefd3c0261df5`，确认失败未产生修改。
- 加入预算保护时，两次 `apply_patch` 再次因同一 bwrap 问题失败；第一次手工小补丁又因区块行数错误返回 `error: corrupt patch at line 12`，也未修改文件。
- 一次编排 `uv lock` 与检查命令的 JavaScript 因括号错误返回 `SyntaxError: missing ) after argument list`，脚本在任何 shell 命令执行前终止；随后使用修正后的编排重新执行成功。

成功处理：读取 commit3 基线自动生成行数准确的统一补丁，并显式保留原文件无末尾换行标记后应用成功。后续调整均使用唯一文本锚点生成统一补丁，避免覆盖其他文件。

### 2. 锁文件、静态检查和 Python 版本

每次源码、报告或审计文件变化后均实际执行：

```bash
uv lock
```

所有调用均成功，使用外层项目的 CPython 3.12.3 解析依赖，显示 `Resolved 1 package`；`uv.lock` 最终没有差异。

实际执行：

```bash
uvx --from ruff ruff check agents/q2Agent.py
uv run --no-project --python 3.9 python -B -VV
uv run --no-project --python 3.9 python -B -c 'import agents.q2Agent as q; ...'
git diff --check -- commits/agents/q2Agent.py
```

结果：

- Ruff：`All checks passed!`。
- Python：`Python 3.9.25`。
- 导入成功，默认 depth 为 3，默认评估函数为 `betterEvaluationFunction`。
- Q2 文件空白检查通过。

### 3. 内存正确性测试

使用 `uv run --no-project --python 3.9 python -B -` 从 stdin 运行不落盘假树测试。结果分别显示：

```text
in-memory alpha-beta tests passed
optimized in-memory alpha-beta tests passed
```

覆盖内容：

- 1、2、4 个 ghost 的动态轮转。
- depth 1 和 depth 2 的完整轮次语义。
- 已知 max/min 数值和 alpha-beta 深层剪枝。
- 同分优先非 `STOP`，再保持合法动作顺序。
- depth 1 完成、depth 2 中途超时时返回 depth 1 结果。
- 总预算耗尽时不进入深搜索，仍返回合法 fallback。
- 无合法动作时返回 `Directions.STOP`。
- `registerInitialState` 重置整局预算。

### 4. 评估函数边界测试

使用 Python 3.9 从 stdin 初始化全部 `layouts/q2_*.lay`，断言布局数为 12，并在每个初始状态和每个 Pac-Man 合法一步后继上调用综合评估函数。另覆盖空食物、空胶囊、无 ghost、ghost 重合、scared ghost 和 terminal sentinel。

结果：

```text
evaluation edge tests passed for 12 layouts
```

所有值均为有限数值，无除零、空列表或写死 ghost 数量错误。

### 5. 第一版真实地图与 evaluator

代表地图命令形式：

```bash
uv run --no-project --python 3.9 pacman.py \
  -l layouts/q2_testClassic.lay \
  -p Q2_Agent --timeout=30 -q -f
```

第一版代表结果：

- test：524，胜，0.807 秒。
- capsule：1261，胜，1.141 秒。
- trapped：-501，负，正常结束。
- original：726，负，8.878 秒。
- medium2：1420，负，26.959 秒。
- danger：77，负，5.104 秒。

官方 evaluator 命令：

```bash
uv run --no-project --python 3.9 \
  --with pandas --with tqdm --with tabulate \
  evaluator.py --q1a --q1b --q1c
```

在交互提示输入 `y`。第一次完整结果为 8/12 胜、总分 15235、平均 1269.58，退出码 0，无 timeout/crash/异常。

### 6. 深度与评估函数消融

在 `q2_contestClassic.lay` 固定种子运行：

- better evaluation，depth 1：1657，胜，0.190 秒。
- better evaluation，depth 2：1997，胜，1.274 秒。
- better evaluation，depth 3：2274，胜，2.978 秒。
- score-only evaluation，depth 3：-43，负，6.373 秒。

综合评估和更深搜索在该布局上均提供明确收益。

### 7. 时间预算与排序迭代

使用 Python 3.9 直接调用 `pacman.runGames`，在结束后读取 Agent 内部计时。

第一版 medium2：

```text
INTERNAL_SEARCH_TIME=24.008375
PACMAN_TURNS=840
WITHIN_INTERNAL_BUDGET=False
```

虽然框架未超时，但超过内部目标约 8 毫秒。

随后尝试廉价动作排序：contest 保持 2274 分，耗时从 2.978 降到 2.124 秒；但 medium2 降到 21 分，内部计算 7.896453 秒、199 回合。该策略得分严重退化，已撤销。

恢复完整排序并把 fallback 改为预算耗尽后 O(1) 返回。保护余量 0.25 秒时：

- medium2 压力测试：1551 分，内部 23.519567 秒。
- 完整 evaluator：7/12 胜、总分 14005、平均 1167.08。

保护过于保守，因此最终改为 0.05 秒：

```text
INTERNAL_SEARCH_TIME=23.718205
PACMAN_TURNS=470
WITHIN_INTERNAL_BUDGET=True
```

同次 medium2 得分 1550。最终 direct run 与 evaluator 对 medium2 都得到 1550，对 tricky 都得到 2340。

固定 depth 1 对 tricky 和 medium2 分别只得到 1617 和 360，明显低于 iterative deepening，故未采用固定浅层策略。

### 8. 最终 evaluator

最终 evaluator 退出码 0，总耗时约 2 分 1 秒：

| layout | score | win |
|:--|--:|:--:|
| q2_mediumClassic | 2462 | 是 |
| q2_smallClassic | 1735 | 是 |
| q2_mediumClassic2 | 1550 | 否 |
| q2_originalClassic | 1790 | 否 |
| q2_trappedClassic | -501 | 否 |
| q2_contestClassic | 2274 | 是 |
| q2_testClassic | 524 | 是 |
| q2_minimaxClassic | 513 | 是 |
| q2_trickyClassic | 2340 | 否 |
| q2_dangerClassic | 77 | 否 |
| q2_capsuleClassic | 1261 | 是 |
| q2_openClassic | 1361 | 是 |

汇总：7 胜、5 负、总分 15386、平均 1282.17；相比第一版总分增加 151。没有出现 timeout、crash、Traceback 或未捕获异常。

### 9. 报告和运行产物

用户要求的迭代结果已写入 `docs/q2-report.md`，其中区分最终方案和被撤销实验，并记录算法、时间预算、消融、完整结果和局限性。

真实运行产生过：

```text
commits/__pycache__
commits/agents/__pycache__
commits/logs/__pycache__
```

这些目录经只读定位后被精确删除。删除内容仅为本次 Python 3.9 验证生成的 `.pyc` 缓存；starter 源文件没有删除或改写。

### 10. 提交前最终检查

实际执行：

```bash
uv lock
git status --short --branch
git diff --name-status HEAD
git diff --check
git diff --name-only HEAD -- commits
git diff -- uv.lock
find commits -type d -name __pycache__ -print
gh repo view hongzefu/qmj-grid --json nameWithOwner,visibility,url
rg -n --hidden -g '!.git/**' -g '!*.pdf' -g '!*.7z' '<常见凭据特征>' .
```

结果：

- `uv lock` 成功，显示 `Resolved 1 package in 0.59ms`。
- 最终待提交文件为 `commits/agents/q2Agent.py`、`docs/q2-report.md` 和 `docs/commits/commit4.md`。
- `git diff --check` 无输出，检查通过。
- `git diff --name-only HEAD -- commits` 只输出 `commits/agents/q2Agent.py`，满足课程源码单文件修改限制。
- `git diff -- uv.lock` 无输出，锁文件没有变化。
- 凭据扫描无命中。
- GitHub 返回 `visibility: PRIVATE`。
- 最终 evaluator 重新产生三个 `__pycache__`；确认路径后再次精确删除，未删除任何源码。
- 两次使用 `apply_patch` 追加本节均因环境内部的 `bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted` 失败；随后使用自动生成的等价统一补丁完成更新。

最终提交前检查与提交、推送结果保留在 Git 提交正文和 Git 历史中，因为提交结果无法在提交前写入本文件。
