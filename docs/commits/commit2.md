# commit2 可复现记录

## 用户指令原文

> 写/data/hongzefu/qmj-grid/README.md
>
> 我只要做Part 2: Adversarial Search\
> 不提交 在本地评估 写用户必须要知道的东西

随后用户补充：

> 前面的指令也要继续执行！

在被明确告知 `commit1` 包含四份课程 PDF、公开发布可能涉及课程资料版权后，用户确认：

> 我支持公开传递为github仓库

“前面的指令”指 `docs/commits/commit1.md` 中保存的仓库初始化、中文回复、`uv`、锁文件、逐提交审计、Git 提交和公开 GitHub 推送规则。

## 形式化计划

1. 只从本地四份 PDF 提取 Part 2 的任务要求、GameState 接口、评分规则、报告要求、evaluator 用法、日志与调试参数。
2. 将“不提交”解释为不向课程自动评分系统提交，只在本地评估；此前要求的 Git 提交与公开 GitHub 推送继续执行。
3. 将 `README.md` 改写为只面向 Part 2 的中文指南，不扩展到 Part 1 实现。
4. 明确当前仓库缺少 starter code，因此暂时无法真实运行 Q2；列出开始实现和评估前必须取得的文件。
5. 将官方裸 `python` 示例改写为符合仓库规则的 `uv run` 命令。
6. 记录 Q2 算法契约、本地评估方法、评分文档冲突、报告与生成式 AI 披露要求。
7. 每次文件修改后执行 `uv lock`，检查 README 差异、Markdown 结构和 Git 状态。
8. 创建 `commit2`，提交正文保留用户原文、形式化计划、命令与结果。
9. 在用户确认四份 PDF 可以公开后，创建公开 GitHub 仓库 `hongzefu/qmj-grid` 并推送 `main`。

## 运行命令与结果

### 1. 上一次公开推送尝试

命令：

```bash
gh repo create hongzefu/qmj-grid --public --source=. --remote=origin --push
gh repo view hongzefu/qmj-grid --json nameWithOwner,visibility,url,defaultBranchRef
git remote -v
git status --short --branch
git log -1 --format=fuller
```

结果：执行环境在真正创建仓库前拒绝了操作，因为 `commit1` 包含四份课程 PDF，而用户当时尚未明确确认允许公开这些资料。GitHub 仓库没有创建，也没有文件被外传。用户随后在获知风险后明确支持公开传递。

### 2. 提取 Part 2 信息

实际使用 `pdftotext -layout ... -` 配合 `rg -n -i -C` 和 `sed -n`，分别检查：

- `main.pdf` 的 Part 2、Question 2、评分、报告和提交说明。
- `Assignment 1 - Marking Rubric.pdf` 的 Q2 performance 与报告评分。
- `Assignment 1 - Getting Started Guide.pdf` 的 GameState、Q2 入口、alpha-beta 要求、evaluator、日志、调试建议和 CLI 参数。
- `FIT5047 Assignment 1 Installation Guide Sem 2 - 2026.docx.pdf` 的官方 Python 版本与环境说明。
- `rg --files | sort` 用于确认当前仓库实际文件。

结果：

- Q2 必须在 `Q2_Agent.getAction` 中以 alpha-beta search 为核心。
- Pac-Man 是 maximiser，所有 ghost 是 minimiser；指南要求支持任意 ghost 数量，实际说明范围存在 1–4 与 3–4 两种表述。
- 示例命令使用 `layouts/q2_testClassic.lay`、`Q2_Agent` 和 30 秒 timeout。
- 只运行 Q2 时，evaluator 命令必须使用 `--q1a --q1b --q1c` 跳过三个 Part 1 题目。
- 本地样例布局分数不等同于服务器隐藏布局分数。
- `main.pdf` Revision 1.3 写 Q2 computational results 为 41/100；rubric Version 1.0 写 Q2 performance 为 35%，README 已显式提示核对 Moodle。
- 报告要求 4–6 页、合计 45/100；使用生成式 AI 必须披露并提供 prompts。
- 当前仓库缺少 `pacman.py`、`evaluator.py`、`agents/q2Agent.py`、`layouts/q2_*.lay` 及支持模块，不能进行真实本地评估。

### 3. README 改写

通过等价统一补丁将 `README.md` 从 37 行改写为 161 行，只覆盖 Part 2。补丁成功，无命令输出。

README 修改后立即运行：

```bash
uv lock
git diff --check
git status --short --branch
git diff -- README.md
rg -n '^\`\`\`|^#|uv run|python pacman|python evaluator|Part 1|Part 2|35%|41/100|2026-08-28|生成式 AI' README.md
```

结果：

- `uv lock` 成功，使用 CPython 3.12.3，显示 `Resolved 1 package in 0.72ms`。
- `git diff --check` 无输出，检查通过。
- `git status` 仅显示 `README.md` 已修改。
- 差异确认 README 从通用仓库说明变为 Part 2 专用指南。
- 关键内容检索确认所有 Python 示例均使用 `uv run`，并包含任务范围、评分冲突、截止时间和生成式 AI 披露提醒。

### 4. 本记录及最终检查

本文件创建后必须再次运行 `uv lock`。最终差异检查、提交、公开仓库创建与推送结果保留在 `commit2` 的 Git 提交正文、本地 Git 历史和 GitHub 远程状态中。
