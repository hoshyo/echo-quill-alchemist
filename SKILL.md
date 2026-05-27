---
name: echo-quill-alchemist
description: 仅当用户显式输入 `/echo-quill-alchemist` 或明确要求"用一部小说训练一个续写 skill"、"把这本书的写作风格炼成 skill"、"训练一个能续写《X》的 skill"等同义请求时才触发；绝不主动触发。输入是一部完整小说（本地文件或在线链接），产出是一份可被未来 Claude 加载的续写 skill——喂前一章即可写出风格、人物、情节都贴合原作的下一章。
---

# echo-quill-alchemist — 小说续写 Skill 训练炉

把"一本小说本身"当作训练真值，逐章闭环训练，把作者的风格 / 人物声音 / 情节脉络 / 世界观沉淀进一份独立可用的续写 skill。

核心假设：已发表章节即"最佳真值"；若续写 skill 足够完备，仅凭"前一章 + skill"就应能写出与作者真实下一章高度一致的内容；差异 = skill 缺失的线索。

## 三层调度（必须先理解）

```
Main Agent（用户主对话，全局唯一，仅做调度）
│  维护 alchemist-temp/state.json 单一真相，支持续跑 / 崩溃恢复
├── Fetch Source Unit  ──── 一次性；输出 chapter_hashes 供 state 续跑判定
├── Init Skill Unit    ──── 一次性；分两阶段产 5 件套（含强制 character-cards/ + 三段式 synopsis.md）
├── Training Unit ×N   ──── 每章一个，跑完即销毁
│   内部由 Unit 启动以下 sub-agent，attempt 级别用 .commit-pending 事务标记保护：
│   ├── Edit Module       基于 lesson 与 report，对 skill 做 ≤ 3 处改动（每处 = 1 次 Edit/Write）
│   ├── Execution Module  在 skill + 上一章 + 三段式 synopsis 下生成下一章
│   ├── Scoring Module    精炼对照 → spawn 3 独立裁判 → 每裁判 6 维独立打分 → 中位数聚合
│   ├── Commit Module     据评分 accept / rollback（微小提升默认 rollback 防噪声拟合）
│   └── Summary Module    提炼好/坏修改 → lesson + 章末快照 → 三段式 synopsis 更新
└── Regression Unit    ──── 每 ask_period 章一次（i ≥ K+3）
    用最新 skill 重新生成早期已通过章节，delta < -0.05 写入下一 lesson 红线段；不动 skill
```

**架构硬规则**：
- 没有"孙子 agent"——主 agent 启动 unit，unit 启动 sub-agent，sub-agent 也可以启动 sub-agent，统一称 sub-agent。
- Main Agent 不接触章节正文 / 生成稿 / 评分细节 / skill diff，只做调度、状态管理、用户询问。
- **Unit 自身亦不读章节正文 / SKILL.md / generated.md** —— Unit 是调度器，对内容透明（仅 Copy-Item / Glob / 传路径），读内容是其内部 sub-agent 的事。
- 一个 Unit 完成职责后被 kill，上下文不延续；信息通过文件（state.json / lesson / log / snapshot）传递给下一单元。
- 运行环境无 git。所有回滚 / 历史追溯靠文件快照（每章末镜像到 snapshots/after-chapter-NNN/）。
- **训练目标 = 章间相对成长，不是绝对分数**：每章一律跑 attempt-00 baseline + 1..max_attempts 次 Edit；章末选历史最高分 attempt（受 min_meaningful_improvement = 0.005 噪声闸过滤）；不设"通过 / 未通过"二元判定。可选 `early_exit_score`（默认 1.0 即关闭）仅作算力优化的提前退出。

详细分工见 [references/architecture.md](references/architecture.md)。

## 触发条件（严格）

仅以下情况可触发：
- 用户显式输入 `/echo-quill-alchemist`
- 用户明确表达"用 X 小说训练续写 skill"等同义请求
- 用户在上次输出的"中断恢复提示词"中要求继续

**绝不主动触发**。"我想写小说"、"帮我续写一段"是直接续写需求，不需要训练，不要启动本 skill。

## 启动参数

| 参数 | 必需？ | 默认 | 说明 |
|---|---|---|---|
| 小说来源 | ✅ | — | 二选一：(A) 整本文件路径（.txt/.md，UTF-8）；(B) 按章节顺序排列的 URL 列表 |
| 目标 skill 名 | 可选 | `<novel-slug>-quill` | 从小说标题或文件名 slug 化 |
| 种子章节数 K | 可选 | 自适应 | 总章数 N≥5→K=3；N=4→K=2；N=3→K=1；N<3 拒绝执行 |
| `max_attempts` | 可选 | 5 | 每章固定跑 attempt-00 baseline + 1..max_attempts 次 Edit。**章末选历史最高分 attempt 落盘**，无所谓"达不达标" |
| `min_meaningful_improvement` | 可选 | 0.005 | Commit 决策门槛——新分数超过 prev_best 至少这么多才 accept；否则 rollback。**这是防噪声拟合的核心闸**，落入 LLM 裁判采样自然方差带的"伪提升"被滤掉 |
| `early_exit_score` | 可选 | 1.0 | 仅算力优化：prev_best 达此值即提前停跑（默认 1.0 = 永不触发，跑满 max_attempts）。需要省算力的训练可显式设 0.95 |
| 暂停询问周期 `ask_period` | 可选 | 5 | 每完成 N 章问一次"继续 / 暂停 / 看 progress"；同时是 Regression Unit 的调度周期 |

任一必需项缺失：停下问用户，不得猜测。

> **续跑场景下，启动参数收集被跳过** —— Main Agent 检测到 `<CWD>/alchemist-temp/state.json` 存在，会直接按 state 中的 params 续跑。

> **没有"通过阈值"概念**：本框架不预设"分数 ≥ X 即合格"。续写 skill 训练里"够好"没有客观定义；唯一可观测的是**章间相对成长**（baseline → final）。日志、final-summary 都按成长曲线叙事。

## 工作目录

`<用户启动 Claude 的当前目录>/alchemist-temp/`。布局详见 [references/directory-layout.md](references/directory-layout.md)。

## 入口流程

1. **state 探测**：检测 `<CWD>/alchemist-temp/state.json`：
   - 存在（phase=paused / training+in_flight / error）→ 续跑路径，跳过启动参数收集
   - 不存在 → 全新启动
2. 收集启动参数（仅全新启动）→ 前置环境校验（Python 可用、来源可达、目标 skill 路径可写）
3. spawn **Fetch Source Unit** → 切片到 `alchemist-temp/source/` + 输出 chapter_hashes 写 state
4. 检查总章数：N<3 → 停下；N≥3 → 按公式定 K
5. spawn **Init Skill Unit** → 分两阶段产 5 件套（author-profile.json + character-cards/*.md + world-bible.md → 自校验通过 → SKILL.md + synopsis.md + style-rules.md）。Main Agent 二次校验（glob character-cards 数 + JSON schema）
6. 章训练循环（i = K+1 ... 末章），**所有章节同一流程**（无 baseline 采集章特殊化）：
   - 章前写 state.in_flight；崩溃恢复检测（孤立 .commit-pending → 整章重训）
   - 每章 spawn 新 **Training Unit**：跑 attempt-00 baseline + 1..max_attempts，章末选历史最高分 attempt
   - 章末更新 state.last_known_good；progress.md 记 baseline / final / growth
7. 每 ask_period 章末（i ≥ K+3 且非末章）spawn **Regression Unit** 回测；询问用户继续 / 暂停 / 看 progress
8. 末章后写 `final-summary.md`（成长曲线叙事），state.phase = "done"，输出落盘路径

详见 [references/workflow.md](references/workflow.md)。

## 文档索引

- [references/architecture.md](references/architecture.md) — 三层 agent 边界与职责（含 Regression Unit、自适应阈值）
- [references/workflow.md](references/workflow.md) — 端到端流程（含续跑协议 + 崩溃恢复）
- [references/directory-layout.md](references/directory-layout.md) — 目录与文件约定（含 state.json schema、.commit-pending 事务标记、必选 snapshots/）
- [references/output-skill-spec.md](references/output-skill-spec.md) — 产出 skill 的标准形式（含强分离 character[] schema、三段式 synopsis、禁用词分级）
- [references/scoring-rubric.md](references/scoring-rubric.md) — 6 维评分细则（含局限性声明 + disagreement ≤ 0.2）
- [references/prompts/](references/prompts/) — 各 unit / 模块的提示词模板（9 份：fetch-source / init-skill / training / regression + 5 个 module）
