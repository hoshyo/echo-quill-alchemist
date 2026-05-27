# 端到端工作流

> 阶段总览：state 探测 → 环境校验 → A 章节切片 → B 初版 skill → C 章训练循环（含自适应阈值 + 每 ask_period 章回测）→ G 章间询问 + 末章总结

## 阶段 0 — state 探测（启动第一动作）

Main Agent 启动时**先**检测 `<CWD>/alchemist-temp/state.json`：

| state.json 状态 | 走哪条路径 |
|---|---|
| 不存在 | **全新启动**：进入"前置环境校验" → A → B → C → G |
| 存在且 phase = "done" | 询问用户："上次训练已完成（last_completed_chapter = M）。是新建一次训练，还是只查 final-summary？" |
| 存在且 phase = "paused" | **续跑**：跳过启动参数收集；继续走 A 的 hash 校验路径，B 阶段已完成时跳过；从 state.next_chapter 进入 C |
| 存在且 phase = "training" 且 in_flight ≠ null | **崩溃恢复**：见 G.5 |
| 存在且 phase = "error" | 展示 state.errors，询问用户是修复后续跑、还是新建（旧 alchemist-temp 移到 .bak） |
| schema_version 不匹配 | 直接停下："state.json schema 版本不兼容，请新建训练或迁移" |

`state.json` 的 schema 详见 [directory-layout.md](directory-layout.md)。

## 前置环境校验（仅以下两种入口必须执行）

1. 用户首次输入 `/echo-quill-alchemist` 或同义请求（state.json 不存在）
2. 用户在新会话里续跑（state.json 存在）——新会话仍然要重做环境校验，因为：python 是否还在、URL 是否还可达、目标 skill 路径是否还可写都可能变了

任一项校验不过都停下，不得继续。

### 校验 1：脚本可执行

```powershell
python --version
```

无 Python 则停下提示用户安装 Python 3。

### 校验 2：输入来源可达

- 整本文件：`Test-Path <path>` 必须为 True，文件大小 > 0
- URL 列表：抽样前 3 个 URL 用 WebFetch 真实抓首段（prompt = "提取页面正文首段，至少 50 字"），任一返回 4xx/5xx/DNS 失败/正文 < 50 字 → 停下让用户检查链接（旧的"取 200 字节"无法识别 JS 壳页面、登录墙、反爬验证页）

### 校验 3：目标 skill 落盘路径可写

确认"本 skill 同级目录"（由本 SKILL.md 所在目录的父目录推得）存在且可写。`<novel-slug>-quill/` 已存在则停下询问：
- (A) 覆盖（旧 skill 备份到 `<...>-quill.bak-<timestamp>/`）
- (B) 改用新名
- (C) 取消训练

**不得**默默覆盖。

## 阶段 A — 章节切片（Fetch Source Unit 执行）

主 agent spawn Fetch Source Unit，传入：
- 来源（文件路径 OR URL 列表 OR 用户附件标记）
- 目标输出目录：`<CWD>/alchemist-temp/source/`

Unit 内部流程：

### A.1 整本文件输入

直接调 `scripts/split_chapters.py`：

```powershell
python "<本 skill 安装目录>/scripts/split_chapters.py" `
    --input "<整本文件路径>" `
    --output-dir "<CWD>/alchemist-temp/source"
```

脚本按以下优先级匹配章节标题：
1. 中文：`第[一二三四五六七八九十百千〇零\d]+[章回卷篇]`
2. 英文：`Chapter\s+\d+`、`Chapter\s+[IVXLCM]+`
3. 数字：`^\d+\.?\s+\S`

输出：`chapter-001.md`、`chapter-002.md` ...，文件首行保留章节标题。

### A.2 URL 列表输入

按下列优先级抓取，前者失败回落后者：

1. **WebFetch**（默认）：prompt = "提取页面正文为纯文本，去掉广告 / 导航 / 推荐 / 评论"
2. **PowerShell**：`Invoke-WebRequest -UseBasicParsing -Uri <url>` → 简单 HTML→text 清洗
3. **chrome-devtools MCP 浏览器代理**：启动前**必须**用 push notification 或文字提醒用户："正使用浏览器代理抓取，过程对你可见，可能弹出窗口"

抓取后 Unit 内部分析章节标题模式（取首 3 章对照），调 `split_chapters.py` 切片，或直接按 URL 顺序作为章节序号写入。

### A.3 用户附件输入

用户直接拖入 .txt / .md：按 A.1 处理。

### A.4 失败处理

- WebFetch 失败的 URL：跳过，记录到 `alchemist-temp/logs/fetch-errors.log`，再用回落手段重试
- 三种手段都失败的 URL：彻底跳过
- 全流程结束后：失败章节占比 > 20% **或**连续 ≥ 3 章失败 → Unit 返回错误给主 agent，主 agent 停下提示"建议改用整本文件输入"

### A.5 章节数检查

切片完成后 Unit 返回章数 N：
- N < 3 → 主 agent 停下："章节数太少，最少需要 3 章（1 章初版 + 2 章训练），请检查输入"
- N ≥ 3 → 自适应 K：N=3→K=1；N=4→K=2；N≥5→K=3
- 用户已显式传 K 值则按用户值，但仍校验 N ≥ K+2

## 阶段 B — 初版 skill 生成（Init Skill Unit 执行）

主 agent spawn Init Skill Unit，传入：
- 前 K 章绝对路径列表
- 目标 skill 落盘根目录：`<本 skill 同级目录>/<novel-slug>-quill/`
- 小说元信息（用户提供则原样传；未提供则 Unit 自己从前 3 章总结一句话）

Unit 全量读完前 K 章，**分两阶段**产出（详见 [output-skill-spec.md](output-skill-spec.md)）：

阶段 a（必须先成功落盘并自校验通过）：
```
<目标 skill 落盘根目录>/references/
├── author-profile.json                   # 轻量画像（人物只存索引）
├── character-cards/<slug>.md             # 详细人物卡（每位 1 份）
└── world-bible.md                        # 世界观/术语
```

阶段 b：
```
<目标 skill 落盘根目录>/
├── SKILL.md                              # 续写 skill 主文件 ≤ 8000 字
└── references/
    ├── synopsis.md                       # 三段式滚动概要（主线骨架 / 近期细节 / 活跃伏笔）
    └── style-rules.md                    # 详细风格规则
```

完成后 Unit 返回主 agent：落盘路径 + characters_extracted / character_cards_files_count / domain_terms_extracted / hard_rules_count / synopsis_chars + JSON 校验状态。

**主 Agent 二次校验**（不读正文，不破坏隔离）：
- glob `<TARGET_SKILL>/references/character-cards/*.md`，count == metadata.character_cards_files_count == metadata.characters_extracted
- `Test-Path` 检查 SKILL.md / synopsis.md / author-profile.json / style-rules.md / world-bible.md 都存在
- Read author-profile.json 做 JSON 语法校验；扫 `characters[]` 各元素只能含 5 个允许字段（name/aliases/first_seen_chapter/last_seen_chapter/card_path）
- author-profile.json **不能**有 `rolling_synopsis` 字段（已迁出）
- 任一项不过 → 终止训练（不重试、不补救），把错误展示给用户

## 阶段 C — 章训练循环（i = K+1 ... 末章）

### C.0 主 agent 每章动作清单

- [ ] **章前**：`state.in_flight = {chapter_index: i, started_at: <now>}`、`state.phase = "training"` → write-then-rename 原子写
- [ ] **崩溃恢复检测**：glob `attempts/chapter-<NN3>/attempt-*/`，若任一 attempt 目录下有 `.commit-pending` 标记文件：删除该 attempt 整目录、用 `state.last_known_good.snapshot_dir` 整目录回滚 `<TARGET_SKILL>/`、删除 `attempts/chapter-<NN3>/` 重建空目录、再从 attempt-00 重训
- [ ] **判定本章用什么 threshold**：
  - i ∈ {K+1, K+2}（前两个训练章）：传 `threshold = 1.0`（不可达，强制走 baseline + 收集分数）；Training Unit 也会按"baseline 章不进 attempt-NN 循环"特例处理
  - i ≥ K+3：传 `threshold = state.adaptive_threshold.value`
- [ ] 用 [prompts/unit-training.md](prompts/unit-training.md) 模板构造提示词，填入：当前 i（3 位 padded）、上一章路径、真实本章路径、目标 SKILL.md 路径、attempts 子目录、日志路径、max_attempts、threshold、min_meaningful_improvement、最近 5 条 lesson 路径（若有）、最近一次回测的 summary 路径（若有，供 Summary 写 lesson 红线段时引用）
- [ ] spawn Training Unit（subagent_type: general-purpose），等待返回
- [ ] **章后**：
  - 把 `chapter_index / final_score / attempts_used / threshold_met` 一行追加到 `alchemist-temp/progress.md`
  - i = K+2 时：`state.adaptive_threshold.baseline_scores = [<chapter K+1 final>, <chapter K+2 final>]` → 计算 `state.adaptive_threshold.value = max(median(baseline_scores) + 0.05, params.min_threshold_floor)`、`state.adaptive_threshold.computed_after_chapter = K+2`
  - i ≥ K+3 时：`state.adaptive_threshold.baseline_scores.append(final_score)` 但**不重新计算 value**（防漂移；阈值在 K+2 一次确定后稳定到训练末）
  - `state.last_completed_chapter = i`、`state.in_flight = null`、`state.last_known_good = {snapshot_dir: ".../after-chapter-<NN3>", as_of_chapter: i}` → 原子写
- [ ] **每 ask_period 章末（i ≡ 0 mod ask_period 且 i ≥ K+3 且非末章）**：spawn Regression Unit（详见 C.3）
- [ ] **每 ask_period 章末（含 i = K+ask_period，但跳过 i = K+1 / K+2 这种非整除点）**且非末章 → AskUserQuestion 三选一
- [ ] 否则直接进入 i+1

### C.1 Training Unit 内部时序

详见 [architecture.md "Training Unit 内部时序"](architecture.md) 与 [prompts/unit-training.md](prompts/unit-training.md)。

简版：

```
准备 attempt-00（baseline，不动 skill）
  Execution → generated.md
  Scoring   → score.json + report.md（spawn 3 个独立裁判 sub-agent）
  → score ≥ threshold ? 进入 Summary（标 best=00, decision=accept-implicit）
                      : i ∈ {K+1, K+2} ? 仍直接进入 Summary（baseline 采集章）
                      :                  进入 attempt-01

attempt-NN（NN ≥ 1，最多到 max_attempts）
  ── 事务标记入 ──
  ① 镜像 <TARGET_SKILL>/references/ → attempts/chapter-<NN3>/attempt-<NN2>/references-snapshot/
  ② 复制 <TARGET_SKILL>/SKILL.md → attempts/chapter-<NN3>/attempt-<NN2>/skill-snapshot/SKILL.md
  ③ touch attempts/chapter-<NN3>/attempt-<NN2>/.commit-pending

  Edit     → 改 ≤ 3 处（每处 = 1 次 Edit/Write 工具调用），跳过高分歧（>0.2）维度 → 写 skill-changes.md
  Execution → generated.md
  Scoring   → score.json + report.md
  Commit    → 看 score 与 prev_best：
              ≥ threshold OR new > prev_best + min_meaningful_improvement → accept
              微小提升（new > prev_best 但 < min_meaningful_improvement）  → rollback（防噪声拟合）
              持平 / 下降                                                  → rollback
              rollback 路径：从 references-snapshot/ 整目录恢复 references/
                            从 skill-snapshot/ 恢复 SKILL.md
            → 写 commit-log.md

  ── 事务标记出 ──
  ④ Remove-Item attempts/chapter-<NN3>/attempt-<NN2>/.commit-pending

  → score ≥ threshold OR NN == max_attempts ? 进入 Summary : NN++

Summary
  读所有 attempt 的 score / commit-log / report
  → 提炼"哪类改动有效 / 无效"
  → 写 alchemist-temp/lessons/lesson-<NN3>.md（含"红线"段：来自最近 regression summary 的劣化提醒）
  → 写 attempts/chapter-<NN3>/summary.md
  → patch <TARGET_SKILL>/references/synopsis.md 三段（不再嵌 author-profile.json）
  → append 一行 JSON 到 alchemist-temp/logs/training.jsonl
  → 章末快照：Copy-Item -Recurse <TARGET_SKILL>/ →
              <CWD>/alchemist-temp/snapshots/after-chapter-<NN3>/
```

### C.2.1 Regression Unit（每 ask_period 章一次）

调度时机：每章末 i ≡ 0 mod ask_period 且 i ≥ K+3 且非末章。

主 agent 调度动作：
- 从 logs/training.jsonl 中取所有 threshold_met=true 且 chapter < i 的章节，随机抽 2 个
- 用 [prompts/unit-regression.md](prompts/unit-regression.md) 模板构造提示词，spawn Regression Unit（subagent_type: general-purpose）
- 接收返回的 deltas → 写入 state.regression.history、append 到 logs/regression.jsonl
- 任一 delta < -0.05 → progress.md 加一行 🚨 红色记录、把 `regression/after-chapter-<NN3>/summary.md` 路径塞进下一章 Training Unit 提示词的"最近 regression summary"字段

回测**不动 skill**——纯只读测试。

### C.2.2 Training Unit 返回主 agent 的格式（严格）

```
摘要：<≤ 80 字一句话>
chapter_index: <i>
final_score: <0.xxxx>
best_attempt_id: <NN>
attempts_used: <次数>
threshold_met: true | false
summary_path: <绝对路径>
lesson_path: <绝对路径>
failed_reason: <若未达阈值，一句话说明主要差距维度；否则 "N/A">
```

不允许在返回里贴生成稿 / 评分细节 / skill diff 全文。

## 阶段 G — 章间询问 + 末章总结（主 agent 执行）

### G.1 章间询问（每 5 章一次）

```
question: "已完成第 i 章（共 M 章）。最近 5 章平均分 X.XX，未达阈值章节 P 个。是否继续？"
options:
  - "继续训练（推荐）" → 进入 i+1
  - "暂停训练"        → 输出当前进度后结束本次 skill 调用
  - "先看 progress"   → Read alchemist-temp/progress.md 全文打印 → 再次询问回到此处
```

非询问周期 → 直接进入下一章，不打断用户。

### G.2 末章总结

末章 Training Unit 返回后，主 agent 写 `alchemist-temp/final-summary.md`：

```markdown
# echo-quill-alchemist 训练总结

## 输入
- 小说来源：<file path or URL list>
- 总章节数：M
- 种子章节数：K
- 训练章节数：M - K

## 通过情况
- 达阈值章节数：P / (M-K)
- 平均 final_score：X.XX
- 中位数 final_score：Y.YY
- 最差章节：第 j 章（X.XX，未达阈值）
- 各维度全程平均：style: X.X | plot: X.X | character: X.X | tone: X.X | world: X.X | diction: X.X

## 最终 skill
- 落盘路径：<本 skill 同级目录>/<novel-slug>-quill/
- 用法：用户跟 Claude 说"用 <novel-slug>-quill 续写：<前一章正文>"即可
- 触发关键词（来自 SKILL.md description）：<copy 自 frontmatter>

## 未达阈值章节清单
| 章节 | final_score | top_gaps |
|--|--|--|
| j  | 0.82 | plot, character |
| ...|

## 工作目录
- alchemist-temp 路径：<绝对路径>
- 训练日志：alchemist-temp/logs/training.jsonl
```

输出一句话给用户："训练完成。最终 skill 已落盘：`<path>`。详见 `<final-summary 路径>`。"

### G.3 暂停路径

主 agent 把 `state.phase = "paused"`、`state.updated_at = <now>` 写入 state.json（write-then-rename），然后输出固定回顾格式：

```
本次训练已暂停。
- 已完成章节：<i> / M
- 当前 skill 路径：<目标 skill 落盘路径>
- 工作目录：<alchemist-temp 路径>
- state.json：<alchemist-temp 路径>/state.json
- 续跑方式：开新会话进入同一 <CWD> 后输入 /echo-quill-alchemist —— Main Agent 会自动检测 state.json 续跑，无需手动指定路径
```

然后**结束当前 skill 调用**。

### G.4 失败兜底

任一 Training Unit 返回的 `failed_reason` 显示非常规错误（如"SKILL.md 写入失败"）：

1. 主 agent 把错误原样展示给用户
2. `state.phase = "error"`、`state.errors.append({chapter, error_msg, ts})` → 原子写
3. 提示："本章训练失败，已停止后续。state.json 已记录错误位置。修复底层问题后开新会话进入同一 <CWD>，Main Agent 会自动续跑（崩溃恢复路径会清理本章脏状态）。"
4. **不重试、不跳过、不 spawn 新 Training Unit**

### G.5 崩溃恢复路径（续跑时 in_flight ≠ null）

新会话 Main Agent 检测 state.json 时若 `phase = "training" && in_flight ≠ null`：表示上次会话崩在某章训练中途。

恢复流程：

1. 读 `state.in_flight.chapter_index = i`
2. glob `attempts/chapter-<NN3>/attempt-*/` 找最大 NN，检查是否有 `.commit-pending` 标记
3. 若有 `.commit-pending`：
   - 删除该 attempt 整个目录（连同 references-snapshot、skill-snapshot、各种中间产物）
   - 从 `state.last_known_good.snapshot_dir` 整目录恢复 `<TARGET_SKILL>/`（先删原目录再复制；Copy-Item -Recurse）
   - 删除 `attempts/chapter-<NN3>/` 整目录（这一章彻底重训）
4. 若无 `.commit-pending` 但 in_flight ≠ null（章末写入前崩溃）：
   - 检查 `attempts/chapter-<NN3>/summary.md` 是否存在 → 若存在，仅补写 progress.md / training.jsonl 缺失行 + 更新 state.last_completed_chapter，进入 i+1
   - 若不存在 → 视同步骤 3，整章重训
5. `state.in_flight = null`，重置后进入 C.0 章训练循环
