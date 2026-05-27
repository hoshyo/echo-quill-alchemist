# EchoQuill-Alchemist.skill

把"一本小说本身"当作训练真值，逐章闭环训练，把作者的风格 / 人物声音 / 情节脉络 / 世界观沉淀成一份**独立可用**的续写 skill——喂前一章即可写出风格、人物、情节都贴合原作的下一章。

## 安装

```bash
npx skills add hoshyo/echo-quill-alchemist
```

## 触发

```
/echo-quill-alchemist
```

或同义请求："用这本小说训练一个续写 skill"、"把《X》风格炼成 skill"、"训练一个能续写 X 的 skill"。

**不会主动触发**——只有用户显式调用才启动训练流程。

## 输入

二选一（用户启动时必给）：
- **整本文件**：.txt / .md，UTF-8（推荐，最稳）
- **章节 URL 列表**：按章节顺序排列；自动按 WebFetch → PowerShell → 浏览器代理逐级降级抓取

可选参数：
- 目标 skill 名（默认从小说名 slug 化）
- 种子章节数 K（默认自适应：N≥5→3、N=4→2、N=3→1）
- 单章最大尝试数 `max_attempts`（默认 5）
- 噪声闸 `min_meaningful_improvement`（默认 0.005）—— Commit 决策门槛：新分超过 prev_best 至少这么多才 accept，否则回滚防噪声拟合
- 提前退出分 `early_exit_score`（默认 1.0 = 关闭，永远跑满 max_attempts）—— 仅算力优化用
- 询问周期 `ask_period`（默认 5）—— 每 N 章问一次是否继续，同时是回测 Regression Unit 的调度周期

> **没有"通过阈值"概念**：本框架不预设"分数 ≥ X 即合格"。续写 skill 训练里"够好"没有客观定义；唯一可观测的是**章间相对成长**（baseline → final）。每章一律跑 attempt-00 baseline + 1..max_attempts 次 Edit，章末选历史最高分 attempt 落盘——所有日志、final-summary 都按成长曲线叙事。

## 产出

落盘到 `<本 skill 同级目录>/<novel-slug>-quill/`：

```
<novel-slug>-quill/
├── SKILL.md                              # 主续写 skill ≤ 8000 字
└── references/
    ├── author-profile.json               # 轻量画像（POV、句长直方图、高频词、忌讳词、人物**索引**、术语表）—— 不含长文本
    ├── synopsis.md                       # 三段式滚动故事概要（主线骨架 / 近期细节 / 活跃伏笔，总 ≤ 3500 字）
    ├── character-cards/<slug>.md         # 详细人物卡（每位 1 份独立 .md，必有；详细 tags / speech / behavior 都在这里，不在 JSON）
    ├── style-rules.md                    # 详细风格规则
    └── world-bible.md                    # 世界观/术语
```

**强分离硬规则**：`author-profile.json` 的 `characters[]` 数组只存 5 字段索引（name / aliases / first_seen_chapter / last_seen_chapter / card_path）；详细人物数据**唯一物理真相**在 `character-cards/<slug>.md`。`synopsis.md` 替代旧版嵌在 JSON 里的 rolling_synopsis 字段，避免 2000 字中文嵌 JSON 的转义事故。

未来 Claude 装载这份产出即可续写——它**不接触本训练流程的任何中间产物**。

## 架构（三层 Agent）

```
Main Agent（用户主对话，全局唯一，仅做调度）
│  维护 alchemist-temp/state.json 单一真相，支持续跑 / 崩溃恢复；自身不读章节正文 / skill 文件
├── Fetch Source Unit  ───── 一次性，抓原文 / 接附件 / 切片 + 输出 chapter_hashes 写 state
├── Init Skill Unit    ───── 一次性，分两阶段产 5 件套（强制 character-cards/ + 三段式 synopsis）
├── Training Unit ×N   ───── 每章一个，跑完即销毁；自身不 Read 章节 / SKILL.md（仅 Copy-Item 与传路径）
│   内部由 Unit 启动 sub-agent，attempt 级别用 .commit-pending 事务标记保护：
│   ├── Edit Module       根据上一单元 lesson，对 skill 做 ≤ 3 处改动（每处 = 1 次 Edit/Write）
│   ├── Execution Module  在 skill + 上一章 + 三段式 synopsis 下生成下一章
│   ├── Scoring Module    评分 Agent 精炼对照 → spawn 3 个独立裁判 → 每个裁判对 6 维独立打分 → 中位数聚合
│   ├── Commit Module     2 分支决策：delta > 0.005 → accept；其余 → rollback（防噪声拟合）
│   └── Summary Module    分阶段隔离：先写 lesson（不读情节）→ 再读 scoring-context 写 synopsis 三段
└── Regression Unit    ───── 每 ask_period 章一次（i ≥ K+3）
    用最新 skill 重生成早期已通过章节，delta < -0.05 写入下一 lesson 红线段；不动 skill；自身不读章节正文
```

**关键防御机制**：

- **章末整快照** `snapshots/after-chapter-NNN/` + **attempt 级 `.commit-pending` 事务标记** + **state.json 单一真相** = 任何节点崩溃都能定位"最后一致状态"重训该章
- **数据真相单一化**：人物详情只在 .md 卡，故事概要独立成 synopsis.md，author-profile 只是轻量索引
- **信号防噪**：三裁判同模型局限明示 + 分歧 ≤ 0.2 才稳定 + delta ≤ 0.005 默认 rollback + Regression Unit 反向回测早期章节
- **训练目标 = 章间相对成长**：每章 baseline → final 的增量是唯一指标；不设"达标 / 未达标"二元判定

详见 [SKILL.md](SKILL.md) 与 `references/` 下的：
- [architecture.md](references/architecture.md) — 三层 agent 边界与职责（含 Regression Unit、Unit 自身隔离硬规则）
- [workflow.md](references/workflow.md) — 端到端流程（含续跑协议 + 崩溃恢复）
- [directory-layout.md](references/directory-layout.md) — alchemist-temp/ 目录约定（含 state.json schema、`.commit-pending` 事务标记、必选 snapshots/）
- [output-skill-spec.md](references/output-skill-spec.md) — 产出 skill 的标准形式（强分离 character[] schema、三段式 synopsis、禁用词分级）
- [scoring-rubric.md](references/scoring-rubric.md) — 6 维评分细则（含局限性声明 + disagreement ≤ 0.2）
- [prompts/](references/prompts/) — 9 份提示词模板（fetch-source / init-skill / training / regression + 5 个 module）

## 工作目录

`<用户启动 Claude 的当前目录>/alchemist-temp/`。无 git 环境也能跑——所有回滚靠文件快照（章末整目录镜像到 `snapshots/after-chapter-NNN/`）+ attempt 级 `.commit-pending` 事务标记。

## 续跑 / 崩溃恢复

中途暂停或会话崩溃后，开新会话进入**同一 `<CWD>`** 输入 `/echo-quill-alchemist`，Main Agent 会：

1. 检测 `alchemist-temp/state.json` 自动判定续跑（无需手动指定路径）
2. 比对 source 章节 hash 确认还是同一本书
3. 若上次崩在某章训练中途（孤立 `.commit-pending`）→ 自动从 `last_known_good` 整目录回滚该章重训
4. 从 `state.next_chapter` 继续推进

## 使用产出 skill

训练完成后，未来任意 Claude 会话只需安装到本机 skill 目录，让 Claude 装载即可：

```
请用 <novel-slug>-quill 续写：
<前一章正文>
```
