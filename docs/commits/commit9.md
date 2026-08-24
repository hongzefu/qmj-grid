# commit9：AGENTS.md 新增「后台任务监听」行缓冲规则

## 用户指令原文

- 「为什么实验2结束后没有唤醒」（在 MotionJEPA 仓库的基准实验中，Monitor 在任务结束时未上报）
- 「把这个问题写入claude md」
- 「全局和本项目的claude md都要！」

## 形式化计划

1. 定位不唤醒的根因：`tail -F log | tr '\r' '\n' | grep --line-buffered` 管道中，`tr` 对管道输出默认 4KB 块缓冲——日志持续增长时事件被后续输出推出、看似正常；任务结束后最后几行（RESULT/EXIT_CODE 等完成标记）永远卡在 `tr` 缓冲区，监听端静默。
2. 规则三处落地：全局 `~/.claude/CLAUDE.md`（Monitor 规范模板改 `stdbuf -oL tr` 并加说明）、MotionJEPA 仓库 `AGENTS.md` 第 7 条、本仓库 `AGENTS.md`（本 commit，新增「后台任务监听」一节，因 CLAUDE.md 只作指向 AGENTS.md 的指针）。

## 运行命令与结果

- 复现证据（MotionJEPA 仓库，2026-08-24）：epoch 基准第 3 轮与冷缓存复测两次，结束时 Monitor 均无事件，人工 `tmux has-session` + `grep` 日志确认任务早已正常结束（`EXIT_CODE=0` 与 `RESULT` 行都在日志里，但从未到达监听端）；中段事件（每 25 步的校验和行）能到达，证明是"结束后无后续输出可推缓冲"的尾部丢失而非过滤器写错。
- 本仓库改动：编辑 `AGENTS.md` 在「Git 与远程仓库」前插入「后台任务监听」一节；无代码/依赖变化，`uv lock` 无需变更（未动 Python 依赖）。
