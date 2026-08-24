# commit6 可复现记录

## 用户指令原文

> 写claude md 全部读agents md

## 形式化计划

1. 在仓库根目录新增 `CLAUDE.md`。
2. 内容不重复既有约定，只要求：开始任何工作前必须完整阅读 `AGENTS.md` 全文并严格遵守。
3. 冲突时以 `AGENTS.md` 为准。
4. 按 `AGENTS.md` 要求：改动后运行 `uv lock`，补写本可复现记录，再提交。

## 运行命令与结果

```
$ uv lock
Resolved 1 package in 0.66ms（成功，uv.lock 无变化）

$ git status --short
?? CLAUDE.md
?? docs/commits/commit6.md
```

本次为纯文档改动，未涉及代码与依赖变化，无需运行 Q2 评测。

## 当前状态与下一步

`CLAUDE.md` 已生效，Claude Code 会在会话开始即加载它并被指向 `AGENTS.md`。后续规则新增仍统一写入 `AGENTS.md`，不在 `CLAUDE.md` 内分叉。
