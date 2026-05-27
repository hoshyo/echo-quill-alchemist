# 三层 Agent 架构

> 主 SKILL.md 的"三层调度"是骨架，本文是肉。读完本文再看 [workflow.md](workflow.md)。

## 调度全景

```
┌────────────────────────────────────────────────────────────────────┐
│ Main Agent（用户主对话）                                            │
│  - 收集启动参数 / 章节循环调度 / 用户暂停询问                        │
│  - 维护 alchemist-temp/state.json 单一真相（write-then-rename 原子写）│
│  - 不读任何章节正文、生成稿、评分细节、skill diff                    │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Fetch Source Unit（一次性）                                    │  │
│  │  - 抓原文 / 切片 / 输出 chapter_hashes 给 Main Agent 写 state  │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Init Skill Unit（一次性）                                      │  │
│  │  - 读前 K 章 → 产 5 件套：SKILL.md / author-profile.json       │  │
│  │    / synopsis.md / character-cards/*.md / style-rules.md       │  │
│  │    / world-bible.md                                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Training Unit（每章一个，跑完被 kill）                         │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ ┌────────┐│  │
│  │  │ Edit     │ │Execution │ │ Scoring  │ │ Commit │ │Summary ││  │
│  │  │ Module   │ │ Module   │ │ Module   │ │ Module │ │Module  ││  │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────┘ └────────┘│  │
│  │   Scoring 内部再 spawn 3 个独立裁判 sub-agent，每个对 6 维打分│  │
│  │   Edit 前后由 Unit 维护 .commit-pending 事务标记 + 全 references快照│
│  │   章末由 Unit 镜像 TARGET_SKILL → snapshots/after-chapter-NNN/ │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ Regression Unit（每 ask_period 章一次；i ≥ K+3 才有意义）     │  │
│  │  - 用最新 SKILL.md 回测随机抽 2 个已通过早期章节               │  │
│  │  - 仅跑 Execution + Scoring，不动 skill                        │  │
│  │  - delta < -0.05 → 标记并写入下一 lesson 的"红线"段           │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

## Main Agent 完整职责

只做以下 11 件事，**其余一切**委托给 Unit。所有"决策"动作落地为 `state.json` 的字段更新（write-then-rename 原子写）：

1. **续跑探测（启动第一动作）**：检测 `<CWD>/alchemist-temp/state.json`：
   - 存在 → 解析 schema_version、phase、in_flight、last_completed_chapter、last_known_good。**跳过启动参数收集**，按 state 续跑
   - 不存在 → 走全新启动路径
2. **收集启动参数**（仅全新启动）：小说来源、可选 skill 名、可选 K、可选 max_attempts、可选 `min_threshold_floor`（替代旧 `threshold`，是阈值兜底下限）、可选询问周期。任一必需项缺失则停下问用户
3. **前置环境校验**（全新启动 OR 续跑入新会话时各执行一次）：
   - `python --version` 可用
   - 来源可达：本地文件 `Test-Path` 为 True 且非空；URL 列表用 WebFetch 抽样 3 个 URL 真实抓首段（≥ 50 字才算可达）
   - 目标 skill 路径可写；**全新启动**时同名已存在三选一询问（覆盖备份 / 改名 / 取消）；**续跑**时直接用 state.target_skill_path
4. **spawn Fetch Source Unit**（全新启动一次性）→ 接收章节清单 + chapter_hashes → 写入 state.source.fingerprint。续跑时跳过：把当前 source/ 重新 hash，与 state 中 hash 对比，不一致则停下询问用户
5. **判定 K**（全新启动）：N<3 拒绝；N=3→K=1；N=4→K=2；N≥5→K=3；用户已显式传 K 则按用户值，仍校验 N≥K+2
6. **spawn Init Skill Unit**（全新启动一次性）→ 接收返回 metadata。**Main Agent 二次校验**（不读正文）：
   - glob `<TARGET_SKILL>/references/character-cards/*.md` 文件数 == metadata.characters_extracted
   - `Test-Path` 检查 `synopsis.md` / `author-profile.json` / `style-rules.md` / `world-bible.md` 都存在
   - Read `author-profile.json`（小文件，安全）做 JSON 语法校验；确认 `characters[]` 元素只含 `name/aliases/first_seen_chapter/last_seen_chapter/card_path` 五字段，无 tags/speech_sample 等详细字段；确认无 `rolling_synopsis` 字段
   - 任一项不过 → 直接终止，展示错误
7. **章训练循环**（i = K+1 ... 末章）：
   - 进入新章：把 `state.in_flight = {chapter_index: i, started_at: <now>}`，原子写入 state.json
   - **续跑入此处**：检测 attempts/chapter-NNN/ 下有无孤立 `.commit-pending`：有 → 删除该 attempt 整个目录、从 state.last_known_good 整体恢复 TARGET_SKILL、删除该 chapter 整个 attempts 目录后从 attempt-00 重训
   - 构造 Training Unit 提示词（带最新自适应阈值）→ spawn → 接收一句话摘要 + 元数据
   - 写一行到 progress.md；append 到 logs/training.jsonl
   - 章末：`state.last_completed_chapter = i`，`state.in_flight = null`，`state.last_known_good = {snapshot_dir: ".../after-chapter-NNN", as_of_chapter: i}`
8. **自适应阈值计算**：前两个训练章节（i = K+1, K+2）只跑 baseline（不强制 Edit）→ 收集 baseline 分数到 state.adaptive_threshold.baseline_scores。从 i = K+3 起：`adaptive_value = max(median(baseline_scores) + 0.05, min_threshold_floor)`，写入 state.adaptive_threshold.value。Training Unit 提示词里传 `threshold = state.adaptive_threshold.value`
9. **Regression 调度**：每 ask_period 章末（i ≡ 0 mod ask_period 且 i ≥ K+3）spawn 一次 Regression Unit。Unit 返回 deltas → 任一 chapter delta < -0.05 → append 一行红色记录到 progress.md，并写一份 `regression/after-chapter-NNN/summary.md`，路径由下一 Summary Module 读取后融入 lesson 的"红线"段
10. **每 ask_period 章询问**：AskUserQuestion 三选一"继续 / 暂停 / 看 progress"。非询问轮自动续跑。暂停 → `state.phase = "paused"`，写入并终止本次 skill 调用
11. **末章总结**：写 `alchemist-temp/final-summary.md`，`state.phase = "done"`，输出落盘路径给用户

**严禁**：
- ❌ Read 任何 `chapter-NNN.md` 正文、`generated.md`、`score.json`、`report.md`、训练中的 SKILL.md
- ❌ 自己 spawn 评分 sub-agent / 改 skill sub-agent
- ❌ 自己执行章节生成、评分、skill 改写
- ❌ 章间向用户长篇汇报本章细节（用户能看 progress.md）
- ❌ 失败时重试或 spawn 新 Unit；硬错误直接展示错误并 `state.phase = "error"` 后停下
- ❌ 把 state.json 的细节（如 baseline_scores、regression history）原样贴给用户——用户看 progress.md
- ❌ 自身记忆累积超过 5 章的 Unit 返回 metadata —— 章间主动遗忘，需要时 Read state.json 重新取

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
- **分两阶段**降低单点失败成本：
  - **阶段 a**：产 author-profile.json（轻量索引版，无 rolling_synopsis）+ character-cards/*.md（每位 1 份独立 .md，**必须创建**）+ world-bible.md。落盘后 **Unit 内部自校验**：glob *.md 数量 = characters[] 长度，json 通过校验。失败 → 报错退出
  - **阶段 b**：基于阶段 a 产物再产 SKILL.md + style-rules.md + synopsis.md（三段式初版）
- 产出（5 件套）：
  - `<目标 skill>/SKILL.md` — 续写 skill 主文件（≤ 8000 字）
  - `<目标 skill>/references/author-profile.json` — 轻量画像（POV、句长直方图、高频词、忌讳词、人物**索引**、术语表，**不含** rolling_synopsis）
  - `<目标 skill>/references/synopsis.md` — 三段式滚动概要（主线骨架 / 近期细节 / 活跃伏笔）
  - `<目标 skill>/references/character-cards/<slug>.md` — 详细人物卡（每位 1 份独立 .md）
  - `<目标 skill>/references/style-rules.md` — 详细风格规则
  - `<目标 skill>/references/world-bible.md` — 世界观/术语
- 返回 Main Agent：落盘路径 + characters_extracted / character_cards_files_count / domain_terms_extracted / hard_rules_count / synopsis_chars + JSON 校验状态

详见 [prompts/unit-init-skill.md](prompts/unit-init-skill.md)。

## Training Unit 职责

每章一个，串行跑完五模块；上下文不延续到下一章。

### Unit 内部时序

```
attempt-00（先 baseline，无 Edit）
  Execution Module → generated.md
  Scoring Module   → score.json + report.md
  → 若 score ≥ threshold（自适应值）：进入 Summary（标 best_attempt=00, decision=accept-implicit）
  → 否则进入 attempt-01

  特例：i ∈ {K+1, K+2}（前两个训练章）—— 仅作为自适应阈值的 baseline 采集，
       即使 attempt-00 未达阈值也直接进入 Summary，不进 attempt-NN 循环

attempt-NN（NN ≥ 1）
  ── 进入"危险区"前事务标记 ──
  ① mkdir attempts/chapter-<NN3>/attempt-<NN2>/
  ② Copy-Item -Recurse <TARGET_SKILL>/references/ → attempt-<NN2>/references-snapshot/
  ③ Copy <TARGET_SKILL>/SKILL.md → attempt-<NN2>/skill-snapshot/SKILL.md
  ④ touch attempt-<NN2>/.commit-pending           ← 事务标记入

  Edit Module      → 写新 SKILL.md / 改 author-profile / 改 character-cards
                     （改动 ≤ 3 处，每处 = 1 次 Edit/Write 工具调用）+ skill-changes.md
  Execution Module → generated.md
  Scoring Module   → score.json + report.md
  Commit Module    → 看 score 与 prev_best_score：
                     ≥ threshold OR new > prev_best + min_meaningful_improvement → accept
                     微小提升（< min_meaningful_improvement）OR 持平 OR 下降 → rollback
                     rollback 路径：从 references-snapshot/ 整目录恢复
                                    + 从 skill-snapshot/ 恢复 SKILL.md
                  → commit-log.md
  ⑤ Remove-Item .commit-pending                   ← 事务标记出

  → 若 score ≥ threshold OR NN == max_attempts：进入 Summary
  → 否则 NN++，回到顶

Summary Module → lesson-<i>.md（写给下一 Unit 的 Edit Module）
              + patch <TARGET_SKILL>/references/synopsis.md 三段（不再嵌 author-profile）
              + （成功路径）章末快照：Copy-Item -Recurse <TARGET_SKILL>/ →
                <CWD>/alchemist-temp/snapshots/after-chapter-<NN3>/
返回 Main Agent：一句话摘要 + 元数据
```

### 五模块职责一览

| 模块 | 输入 | 产出 | 关键约束 |
|---|---|---|---|
| Edit | 当前 SKILL.md / author-profile.json / synopsis.md / character-cards/、最近 5 条 lesson、上一 attempt 的 report | 新 SKILL.md / patched references/、skill-changes.md（## 处 1/2/3 编号） | 单次改动 ≤ 3 处（1 处 = 1 次 Edit/Write 工具调用）；只动 top_gaps；高分歧维度（disagreement > 0.2）本轮不动；不读真实本章 / 生成稿 |
| Execution | 当前 SKILL.md / author-profile.json / synopsis.md（三段必读） / 上一章正文 | generated.md | 字数与上一章 ±30%；不读真实本章 / 后续章节 / 历史 attempts |
| Scoring | 真实本章、生成本章、scoring-rubric、author-profile.json | score.json、report.md；spawn 3 个独立裁判 sub-agent，每个对 6 维独立打分，中位数聚合 | 裁判不读 SKILL.md / synopsis / character-cards / 历史分数；裁判之间互相不可见。注意：3 裁判是同模型多次采样的近似 ensemble，不是真独立 |
| Commit | score.json、attempt 的 references-snapshot/ 与 skill-snapshot/、prev_best_score | commit-log.md（accept / rollback）；rollback 时从 references-snapshot 整目录恢复 + SKILL.md 单文件恢复；删除 .commit-pending | 微小提升（< min_meaningful_improvement = 0.005）默认 rollback；与 Edit 是配对 |
| Summary | 本章所有 attempts 的 score / commit-log / scoring-context；当前 synopsis.md；regression Unit 写入的"红线" | lesson-<i>.md、本章 summary.md、patched synopsis.md（三段）；触发章末 snapshots/ 镜像 | 提炼"哪类改动有效 / 无效"；无论采纳/拒绝都要分析；synopsis 改动不再 patch JSON |

各模块详细提示词见 [prompts/](prompts/) 目录下对应文件。

## Regression Unit 职责

每 ask_period 章末由 Main Agent spawn 一次（i ≥ K+3 才有意义；早于此训练样本太少，回测无意义）。

- 输入：当前最新的 `<TARGET_SKILL>/`、随机抽取的 2 个已通过早期章节路径、原始 baseline 分数（来自 logs/training.jsonl）
- 内部时序：对每个被抽中的章节
  - spawn Execution Module（用最新 SKILL.md + 上一章 + synopsis 重新生成）
  - spawn Scoring Module（同样 3 裁判聚合）
  - 计算 `delta = new_score - original_final_score`
- 输出：
  - `<CWD>/alchemist-temp/regression/after-chapter-<NN3>/replay-chapter-<MM3>/`（每章一份 generated.md / score.json / report.md）
  - `<CWD>/alchemist-temp/regression/after-chapter-<NN3>/summary.md`（汇总 deltas）
  - append 一行到 `<CWD>/alchemist-temp/logs/regression.jsonl`
- 任一 delta < -0.05 → 在 summary.md 顶部标 🚨；下一章 Summary Module 必须把这条写入 lesson 的"红线（绝不碰）"段
- **不动 skill**——纯只读测试

详见 [prompts/unit-regression.md](prompts/unit-regression.md)。

## 信息隔离硬规则（避免上下文污染影响客观性）

| Agent | 禁读 |
|---|---|
| Main Agent | 章节正文、generated.md、score.json、report.md、训练中的 SKILL.md / synopsis.md / character-cards 内容（可读 author-profile.json 做 schema 校验）|
| Training Unit 自身 | 真实本章正文（仅传路径给 Scoring Module） |
| Edit Module | 真实本章正文、generated.md（只读 report） |
| Execution Module | 真实本章正文、后续章节、历史 attempts、训练日志 |
| Scoring Module 裁判 sub-agent | SKILL.md / synopsis.md / character-cards、历史 score.json / report.md、后续章节、其它裁判的产出 |
| Commit Module | 真实本章正文、generated.md、当前 SKILL.md 正文（只读 score.json + skill-changes.md + 快照路径） |
| Summary Module | 真实本章正文、generated.md（只读 score / commit-log / report / scoring-context） |
| Regression Unit | 与 Training Unit 同；额外禁读：当前章节训练状态（避免被"现在还在训第 i 章"信息污染早期章回测） |

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
