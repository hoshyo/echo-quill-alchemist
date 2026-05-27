# 三层 Agent 架构

> 主 SKILL.md 的"三层调度"是骨架，本文是肉。读完本文再看 [workflow.md](workflow.md)。

## 调度全景

```
┌────────────────────────────────────────────────────────────────────┐
│ Main Agent（用户主对话）                                            │
│  - 收集启动参数 / 章节循环调度 / 用户暂停询问                        │
│  - 不读任何章节正文、生成稿、评分细节、skill diff                    │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Fetch Source Unit（一次性）                                    │  │
│  │  - 抓原文（WebFetch / curl / browser-proxy）或接附件           │  │
│  │  - 分析章节标题模式 → 调 split_chapters.py 切片              │  │
│  │  - 落盘到 alchemist-temp/source/chapter-NNN.md                 │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Init Skill Unit（一次性）                                      │  │
│  │  - 读前 K 章 → 产 SKILL.md 初版 + author-profile.json          │  │
│  │  - 退出                                                       │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Training Unit（每章一个，跑完被 kill）                         │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ ┌────────┐│  │
│  │  │ Edit     │ │Execution │ │ Scoring  │ │ Commit │ │Summary ││  │
│  │  │ Module   │ │ Module   │ │ Module   │ │ Module │ │Module  ││  │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────┘ └────────┘│  │
│  │   Scoring 内部再 spawn 3 个独立裁判 sub-agent，每个对 6 维打分│  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

## Main Agent 完整职责

只做以下 8 件事，**其余一切**委托给 Unit：

1. **收集启动参数**：小说来源、可选 skill 名、可选 K、可选 max_attempts、可选 threshold、可选询问周期。任一必需项缺失则停下问用户
2. **前置环境校验**（仅本次 skill 调用最开始执行一次）：
   - `python --version` 可用
   - 来源可达：本地文件 `Test-Path` 为 True 且非空；URL 列表每个先 WebFetch 探活 200 字节
   - 目标 skill 路径可写；同名已存在则三选一询问（覆盖备份 / 改名 / 取消）
3. **spawn Fetch Source Unit**（一次性）→ 等其返回章节切片清单（章数、标题、字数）
4. **判定 K**：N<3 拒绝；N=3→K=1；N=4→K=2；N≥5→K=3；用户已显式传 K 则按用户值，仍校验 N≥K+2
5. **spawn Init Skill Unit**（一次性，传前 K 章路径）→ 等其返回 SKILL.md 落盘路径
6. **章训练循环（i = K+1 ... 末章）**：构造 Training Unit 提示词 → spawn → 接收一句话摘要 + 元数据 → 写一行到 progress.md
7. **每 N 章询问**（默认 N=5）：AskUserQuestion 三选一"继续 / 暂停 / 看 progress"。非询问轮自动续跑
8. **末章总结**：写 `alchemist-temp/final-summary.md`，输出落盘路径给用户

**严禁**：
- ❌ Read 任何 `chapter-NNN.md` 正文、`generated.md`、`score.json`、`report.md`、训练中的 SKILL.md
- ❌ 自己 spawn 评分 sub-agent / 改 skill sub-agent
- ❌ 自己执行章节生成、评分、skill 改写
- ❌ 章间向用户长篇汇报本章细节（用户能看 progress.md）
- ❌ 失败时重试或 spawn 新 Unit；硬错误直接展示错误并停下

## Fetch Source Unit 职责

- 输入：用户给定的整本文件路径 OR URL 列表 OR 用户附件
- 抓取手段优先级：
  1. WebFetch（默认）
  2. PowerShell `Invoke-WebRequest` / `curl.exe`（WebFetch 失败时）
  3. chrome-devtools MCP 浏览器代理（前两者失败时；启动前**必须**提示用户"正使用浏览器代理抓取，过程可能可见"）
- 抓完后简单分析章节标题模式 → 调 `scripts/split_chapters.py` 切片
- 落盘到 `alchemist-temp/source/chapter-NNN.md`
- 返回 Main Agent：章节数 + 各章标题 + 各章字数 + 抓取方式 + 失败章节列表

详见 [prompts/unit-fetch-source.md](prompts/unit-fetch-source.md)。

## Init Skill Unit 职责

- 输入：前 K 章绝对路径 + 目标 skill 落盘路径
- 全量读完前 K 章
- 产出：
  - `<目标 skill>/SKILL.md` — 续写 skill 主文件（≤ 8000 字）
  - `<目标 skill>/references/author-profile.json` — 作者画像（POV、句长直方图、高频词、忌讳词、人物表、术语表）
  - `<目标 skill>/references/character-cards/<name>.md` — 主要人物卡（每位 1 份）
  - `<目标 skill>/references/style-rules.md` — 详细风格规则
  - `<目标 skill>/references/world-bible.md` — 世界观/术语
- 返回 Main Agent：落盘路径 + 提取到的人物数 / 术语数 / 硬规则数

详见 [prompts/unit-init-skill.md](prompts/unit-init-skill.md)。

## Training Unit 职责

每章一个，串行跑完五模块；上下文不延续到下一章。

### Unit 内部时序

```
attempt-00（先 baseline，无 Edit）
  Execution Module → generated.md
  Scoring Module   → score.json + report.md
  → 若 score ≥ threshold：跳到 Commit（采纳）→ Summary → 退出
  → 否则进入 attempt-01

attempt-NN（NN ≥ 1）
  快照当前 SKILL.md 到 attempt-<NN>/skill-snapshot/
  Edit Module      → 写新 SKILL.md（≤ 3 维改动）+ skill-changes.md
  Execution Module → generated.md
  Scoring Module   → score.json + report.md
  Commit Module    → 据评分采纳或从 skill-snapshot 回滚 → commit-log.md
  → 若 score ≥ threshold OR NN == max_attempts：进入 Summary
  → 否则 NN++，回到顶
Summary Module → lesson-<i>.md（写给下一 Unit 的 Edit Module）
返回 Main Agent：一句话摘要 + 元数据
```

### 五模块职责一览

| 模块 | 输入 | 产出 | 关键约束 |
|---|---|---|---|
| Edit | 当前 SKILL.md、最近 5 条 lesson、上一 attempt 的 report | 新 SKILL.md、skill-changes.md | 单次改动 ≤ 3 处；只动 top_gaps；不读真实本章 / 生成稿 |
| Execution | 当前 SKILL.md、上一章正文、滚动故事概要 | generated.md | 字数与上一章 ±30%；不读真实本章 / 后续章节 / 历史 attempts |
| Scoring | 真实本章、生成本章、scoring-rubric | score.json、report.md；spawn 3 个独立裁判 sub-agent，每个对 6 维独立打分，聚合（中位数）后加权 | 裁判 sub-agent 不读 SKILL.md / 历史分数；裁判之间互相不可见 |
| Commit | score.json、当前 SKILL.md、attempt skill-snapshot | commit-log.md（accept / rollback） | 与 Edit 是配对：Edit 提改动 → Scoring 给分 → Commit 决策 |
| Summary | 本章所有 attempts 的 score / commit-log | lesson-<i>.md、本章 summary.md | 提炼"哪类改动有效 / 无效"；无论采纳/拒绝都要分析 |

各模块详细提示词见 [prompts/](prompts/) 目录下对应文件。

## 信息隔离硬规则（避免上下文污染影响客观性）

| Agent | 禁读 |
|---|---|
| Main Agent | 章节正文、generated.md、score.json、report.md、训练中的 SKILL.md |
| Training Unit 自身 | 真实本章正文（仅传路径给 Scoring Module） |
| Edit Module | 真实本章正文、generated.md（只读 report） |
| Execution Module | 真实本章正文、后续章节、历史 attempts、训练日志 |
| Scoring Module 裁判 sub-agent | SKILL.md、历史 score.json / report.md、后续章节、其它裁判的产出 |
| Commit Module | 真实本章正文、generated.md（只读 score.json + skill 快照） |
| Summary Module | 真实本章正文、generated.md（只读 score / commit-log / report） |

**违反隔离 = 训练失效**。每个模块的提示词都会显式列禁读清单 + 自检。

## Lesson 经验传递机制

- 每章 Summary Module 写一份 `alchemist-temp/lessons/lesson-<i>.md`
- 下一 Unit 的 Edit Module 启动时读"最近 5 条 lesson"
- Lesson 内容：哪类改动有效（被 Commit 采纳且分数提升）、哪类无效（被回滚或分数下降）、归因（哪一维差距、应该改什么不该改什么）
- Lesson 保持时间无关：不写"第 N 章"、"本轮"，写规则陈述

## 失败兜底

| 失败点 | Main Agent 行为 |
|---|---|
| Fetch Source Unit 抓取失败率 > 20% 或连续 ≥ 3 章 | 停下提示"建议改用整本文件输入" |
| Init Skill Unit 写 SKILL.md 失败 | 展示错误，停下 |
| Training Unit 返回硬错误 | 展示错误，停止后续章节训练，提示用户 Read 当前 SKILL.md 检查 |
| 章训练子 Unit 自身陷入死循环或超时 | 主 agent 不强制 kill；返回错误后停下 |

**绝不**：重试、跳过、用 max_attempts 上调或 threshold 下调来绕过。
