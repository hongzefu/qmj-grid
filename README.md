# qmj-grid

本仓库用于保存 qmj-grid 项目资料及后续实现。目前纳入版本管理的原始资料包括课程作业说明、评分标准、安装指南与主文档 PDF。

## 开发约定

- 所有沟通、计划和提交记录使用中文。
- Python 运行与依赖管理统一使用 [`uv`](https://docs.astral.sh/uv/)；不得直接使用 `python`、`python3` 或 `pip`。
- 每次修改后、提交前必须执行 `uv lock`，并提交依赖变更产生的锁文件。
- 每次提交都必须记录用户指令原文、形式化计划、所有实际命令及结果，确保可复现。
- 详细规则见 [`AGENTS.md`](AGENTS.md)，逐次提交记录见 [`docs/commits/`](docs/commits/)。

## 环境初始化

```bash
which uv
uv sync
```

## 复现与提交检查

每次变更至少执行：

```bash
uv lock
git status --short
git diff --check
```

随后把本次工作的原始需求、形式化计划、命令和结果写入 `docs/commits/<提交名>.md`，并在 Git 提交正文中保留同样的审计信息。

## 当前资料

- `Assignment 1 - Getting Started Guide.pdf`
- `Assignment 1 - Marking Rubric.pdf`
- `FIT5047 Assignment 1 Installation Guide Sem 2 - 2026.docx.pdf`
- `main.pdf`
