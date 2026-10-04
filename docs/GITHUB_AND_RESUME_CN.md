# GitHub、作品集与简历使用说明

## 仓库简介

中文版本：

> 面向海外创作者营销的 AI 工作台：可解释筛选、英文外联草稿、人工审批、内容合规审核、FTS5 知识检索，以及可重复的成本与质量评测。支持零成本 mock 和 DeepSeek API。

英文版本：

> An AI-assisted creator operations workbench with deterministic eligibility rules, explainable ranking, human-approved outreach, delivery review, FTS5 retrieval, and repeatable quality/cost evaluation. Runs locally in mock mode or with DeepSeek.

建议 GitHub topics：`fastapi`、`sqlite`、`llm`、`rag`、`deepseek`、`human-in-the-loop`、`creator-marketing`、`ai-agent`。

## README 顶部建议展示

1. 一张项目总览截图；
2. 一张匹配页截图，必须同时看到合格和被排除候选人；
3. 一张 pending 外联草稿与“人工批准”按钮截图；
4. 一张内容审核风险标签截图；
5. 一张日志与 20 案例评测结果截图；
6. 60–90 秒无剪辑 GIF 或视频，按“导入 → 匹配 → 批准 → 审核”走一遍。

截图前检查：

- 右上角显示的是 `mock` 还是 `deepseek`，说明要与截图一致；
- 不出现 API Key、真实邮箱、真实客户或创作者信息；
- 浏览器缩放为 100%，窗口宽度一致；
- 把无关标签页、通知和本地绝对路径裁掉；
- DeepSeek 结果必须明确标注运行日期、模型和评测集规模。

## Pinned repository 文案

> Built an AI-assisted creator-operations demo with rule-based eligibility, LLM explanations, English outreach drafts, human approval, text-risk review, model telemetry, and a 20-case regression set. FastAPI + SQLite + DeepSeek/mock.

## 简历项目标题

**Creator Ops Agent｜海外创作者合作智能工作台**

FastAPI · SQLite/FTS5 · Pydantic · DeepSeek API · pytest

## 中文简历 bullet 草稿

仅在你实际理解实现、能解释取舍与验证后使用；按真实参与程度调整措辞。当前存在已知缺陷，不声称生产就绪或有效的 100% 质量指标。

- 设计并实现海外创作者营销 Agent 工作流，将 Brief、CSV 清洗去重、硬条件筛选、可解释排序、英文外联草稿、人工审批与交付审核串联为可运行的 FastAPI/SQLite 全栈应用。
- 集成 mock/DeepSeek 双模式模型客户端、FTS5 检索、Pydantic 结构化校验、单次重试和运行日志；外联仅生成待人工确认草稿，无真实发送能力。
- 建立 20 个固定流程回归案例及 84 项第一版自动测试（2026-10-04）；复查并修复旧状态、生成期间输入变化、评测盲点与重试用量漏记，使用 Top-1、标签精确率/召回率及完全一致率验证回归，明确与真实模型质量的区别。

## 英文简历 bullets

- Built a full-stack creator-operations workflow with FastAPI and SQLite, covering brief intake, CSV validation/deduplication, deterministic eligibility, explainable ranking, English outreach drafts, human approval, and delivery review.
- Implemented interchangeable mock/DeepSeek model execution with FTS5 retrieval, strict Pydantic output validation, one-retry failure handling, and privacy-conscious telemetry for tokens, latency, and estimated cost.
- Created a 20-case workflow regression set and 84 V1 automated tests (2026-10-04); fixed stale-state, in-flight input changes, evaluation blind spots, and retry-usage accounting, without claiming real-world model accuracy.

## 面试时避免的表述

不要说：

- “我训练了一个 Agent 模型”——这里是模型应用和工作流，不是训练；
- “准确率 100%”——当前指标有明显盲点，连自建满分也不能证明排序与审核质量；
- “已经用于真实公司业务”——除非真的上线并获得授权；
- “系统会自动联系创作者”——当前明确不会发送；
- “所有代码都是我手写的”——更好的说法是你负责设计、取舍、验证，并合理使用 AI coding tools。

同样不要把尚未理解或亲自验证的步骤说成个人独立贡献。可以如实说明 AI 辅助开发，再展示你真正掌握的一条功能链路与一个边界问题。

## 发布前清单

- [ ] 发布包与Git排除 `data/*.db` 和第二版数据库，保留本地历史，不需要删除数据库；
- [ ] 确认 `.env`、API Key 和编辑器缓存均未被 Git 跟踪；
- [ ] 运行 `.venv/bin/python -m pytest -q` 并记录结果；
- [ ] 从全新 clone 按 README 启动一次；
- [ ] 检查所有演示人物与邮箱仍为虚构内容；
- [ ] 添加截图、短视频和清楚的架构说明；
- [ ] 如果展示真实 DeepSeek 指标，记录日期、模型和价格来源。
