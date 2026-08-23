# FIT5047 Assignment 1：只做 Part 2 Adversarial Search

本仓库只关注 **Part 2 / Question 2（Adversarial Search）**：实现一个基于 alpha-beta search 的 Pac-Man 控制器，并且只在本地评估。这里的“不提交”是指不向课程自动评分系统提交；Git 仍按 [`AGENTS.md`](AGENTS.md) 的规则记录，并同步到公开 GitHub 仓库。

## 当前最重要的状态

**现在还不能运行或评估 Q2。** 当前仓库只有四份课程 PDF、项目说明和 `uv` 元数据，尚未包含课程 starter code。至少需要先取得并放入官方 starter repository 中的以下内容：

- `pacman.py`
- `evaluator.py`
- `agents/q2Agent.py`
- `layouts/q2_*.lay`
- starter code 的其余支持模块和目录

不要自己凭空重建环境文件；应使用课程平台邀请的官方仓库及其最新版本。拿到 starter code 后，Part 2 只需要修改课程指定的 Q2 文件，主要入口是 `agents/q2Agent.py` 中 `Q2_Agent.getAction`。作业说明强调不要修改未要求修改的代码。

## Q2 必须实现什么

每次游戏环境调用 `Q2_Agent.getAction(gameState)` 时，控制器都要从当前 `GameState` 开始执行一次 adversarial search，并返回 Pac-Man 当前要执行的一个合法动作。

核心约束：

- 核心算法必须是 **alpha-beta search**，可以在此基础上自行优化。
- Pac-Man 是 maximiser，通常对应 agent index `0`。
- 所有 ghost 都是 minimiser，依次处理其 agent index。
- 主说明写评估地图有 3–4 个 ghost；Getting Started Guide 写会遇到 1–4 个 ghost，并要求算法支持任意 ghost 数量。因此实现时不要写死 ghost 数量。
- Part 2 直接使用完整的 `GameState`，不需要实现 Part 1 的 `getStartState`、`isGoalState` 或自定义 `getSuccessors`。
- 搜索深度不受规范硬性限制，但每个游戏/评估实例只有 30 秒；更深不一定更好。
- 返回值必须是当前状态下 Pac-Man 的合法动作。

常用 `GameState` 接口：

- `getLegalActions(agentIndex)`：返回指定 agent 的合法动作。
- `generateSuccessor(agentIndex, action)`：生成执行动作后的新状态。
- `getPacmanPosition()`：Pac-Man 坐标。
- `getGhostStates()`：ghost 状态，包括 scared timer。
- `getScore()`：当前游戏分数。
- `getCapsules()`：胶囊位置。
- `getNumFood()`：剩余食物数量。
- `getFood()`：食物网格。

实现时必须明确以下递归语义，否则很容易产生隐藏错误：

1. 一个 Pac-Man 节点后面依次展开所有 ghost。
2. 最后一个 ghost 行动后才进入下一轮 Pac-Man，并在此时推进“一整轮”的深度。
3. 赢、输、达到深度上限、没有合法动作或时间预算不足时返回评估值。
4. maximiser 更新 `alpha`，minimiser 更新 `beta`；满足剪枝条件时立即停止展开当前节点。
5. 叶节点评估不仅要看当前分数，还应合理考虑食物、胶囊、ghost 距离、scared ghost 和立即死亡风险；具体设计及取舍需要用本地实验支持。

## `uv` 环境要求

本仓库禁止直接运行 `python`、`python3` 或 `pip`。所有 Python 命令都必须通过 `uv`。

官方安装指南推荐 Python 3.9，但当前文档仓库的 `pyproject.toml` 暂时声明 `>=3.12`。加入 starter code 后，应先根据官方代码兼容性把 `requires-python` 调整为 Python 3.9 范围，再用 `uv` 建立环境；不要假设当前 3.12 配置就是评分环境。

官方 `evaluator.py` 还需要 `pandas`、`tqdm` 和 `tabulate`。starter code 加入后，建议在一次单独、可审计的变更中执行：

```bash
which uv
uv python install 3.9
uv python pin 3.9
uv add pandas tqdm tabulate
uv lock
uv sync
```

如果 starter repository 自带依赖声明，应优先使用官方声明，并只补充缺少的 evaluator 依赖。任何依赖变更后都要再次执行 `uv lock`。

## 只运行一个 Q2 地图

课程说明给出的 Q2 示例，在本仓库规则下应写为：

```bash
uv run pacman.py \
  -l layouts/q2_testClassic.lay \
  -p Q2_Agent \
  --timeout=30
```

建议开发时先查看实际 starter code 支持的参数：

```bash
uv run pacman.py --help
```

常用本地调试参数：

- `-t`：文本界面，能保留整局历史，适合无图形环境。
- `-q`：最简文本输出，适合批量运行。
- `-n <次数>`：同一布局运行多局；Part 2 不应只看单局结果。
- `-f`：固定随机种子，便于复现问题。
- `-c`：Getting Started Guide 明确建议测试时使用它来处理超时和异常；以实际 starter code 的 `--help` 行为为准。
- `-o <日志文件名>`：生成日志；应检查实际参数格式，日志默认位于 `logs/`。

一个可复现的文本模式示例：

```bash
uv run pacman.py \
  -l layouts/q2_testClassic.lay \
  -p Q2_Agent \
  --timeout=30 \
  -t \
  -f
```

先在小地图验证递归轮次、合法动作、终止条件和剪枝，再测试更大地图。调试时应记录布局、随机种子、运行次数、最终分数、胜负、耗时和异常。

## 只运行 evaluator 的 Q2

`evaluator.py` 的 `--q1a`、`--q1b`、`--q1c` 和 `--q2` 参数表示“跳过该题”，不是“只运行该题”。因此只评估 Q2 时应跳过三个 Part 1 题目：

```bash
uv run evaluator.py --q1a --q1b --q1c
```

运行后必须检查 `logs/` 中的日志，确认程序确实完成、没有吞掉超时或异常，并保存每次实验使用的代码版本和命令。样例布局的本地分数与服务器隐藏布局分数不会相同，只能用于比较版本和发现退化。

## 本地评估应记录什么

至少为每个 `layouts/q2_*.lay` 记录：

- 地图名与 ghost 数量。
- 搜索深度、评估函数版本和其他参数。
- 运行次数与是否固定随机种子。
- 每局最终 score、胜负和耗时。
- 平均值、中位数、最差值、胜率、超时数和异常数。
- 与上一个版本或简单基线的差异。
- 日志文件路径及对应 Git commit。

不要只优化单一地图或单一随机轨迹。服务器会在 20 个隐藏实例上评估，每个实例时限 30 秒。

## 评分信息与文档冲突

- `main.pdf` Revision 1.3 写明：Q2 computational results 为 **41/100**。
- `Assignment 1 - Marking Rubric.pdf` Version 1.0 的 Q2 performance 行写的是 **35%**。
- 主说明同时写 report 为 **45/100**；rubric 将 report 分为 description and analysis 25% 与 communication skills 20%，合计 45%。

Q2 的运行成绩按 GUI 的原始 score 与课程 baseline 的 score 比较，并截断到 `[0, 1]`。由于两份文件对 Q2 权重不一致，最终权重必须以 Moodle 上最新文件或教学团队答复为准，不能自行假定 35 或 41 哪个最终有效。

## 报告与学术诚信

即使只做 Part 2，主说明仍要求 4–6 页报告，应该说明：

- 学到了什么、尝试了什么、哪些有效、哪些无效。
- alpha-beta 设计、伪代码、数据结构、复杂度和剪枝策略。
- 深度、tie breaking、评估函数等细节选择。
- 有明确目标和指标的数值实验、基线比较、结果分析和局限性。
- 引用所有外部来源，并把相关工作与自己的实现联系起来。

Getting Started Guide 明确要求：如果使用生成式 AI，必须披露使用情况，并随提交材料提供所用 prompts。本项目已经使用生成式 AI 帮助整理需求和 README，因此若后续进行课程提交，必须如实披露。

## 时间与范围提醒

- 作业说明中的截止时间是 **2026-08-28 11:55pm（Melbourne local time）**；提交前仍应在 Moodle 核对最新时间。
- 当前决定是只完成 Q2、只做本地评估，不实现 Q1a、Q1b 或 Q1c，也不向课程自动评分系统提交。
- 公开 GitHub 仓库不等于课程指定的私有提交仓库；不要误把公开推送当作课程提交。
- 课程说明、评分表、安装指南和主说明 PDF 均保存在仓库根目录，遇到冲突时应核对版本并询问教学团队。

## 仓库协作规则

所有回复与计划使用中文；所有 Python/依赖操作只用 `uv`；每次文件变更后执行 `uv lock`；每个 Git 提交都记录用户原文、形式化计划、实际命令和结果。详细要求见 [`AGENTS.md`](AGENTS.md)，提交审计记录见 [`docs/commits/`](docs/commits/)。
