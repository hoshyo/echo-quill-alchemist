# 端到端工作流

> 阶段总览：环境校验 → A 章节切片 → B 初版 skill → C 章训练循环 → G 章间询问 + 末章总结

## 前置环境校验（仅本次 skill 调用最开始执行一次）

仅在以下两种入口必须执行：
1. 用户首次输入 `/echo-quill-alchemist` 或同义请求
2. 用户在新会话里要求"接着上次的训练继续"——新会话等同于首次触发

任一项校验不过都停下，不得继续。

### 校验 1：脚本可执行

```powershell
python --version
```

无 Python 则停下提示用户安装 Python 3。

### 校验 2：输入来源可达

- 整本文件：`Test-Path <path>` 必须为 True，文件大小 > 0
- URL 列表：每个 URL 先 WebFetch 探活（仅取 200 字节）。任一返回 4xx/5xx/DNS 失败 → 停下让用户检查链接

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

Unit 全量读完前 K 章，产出（详见 [output-skill-spec.md](output-skill-spec.md)）：

```
<目标 skill 落盘根目录>/
├── SKILL.md                              # 续写 skill 主文件 ≤ 8000 字
└── references/
    ├── author-profile.json               # 作者画像
    ├── character-cards/<name>.md         # 主要人物卡（每位 1 份）
    ├── style-rules.md                    # 详细风格规则
    └── world-bible.md                    # 世界观/术语
```

完成后 Unit 返回主 agent：落盘路径 + 提取到的人物数 / 术语数 / 硬规则数。

主 agent 仅 Read 目标 SKILL.md 的前 30 行确认 frontmatter 正确（不读后续正文，避免污染）。

## 阶段 C — 章训练循环（i = K+1 ... 末章）

### C.0 主 agent 每章动作清单

- [ ] 用 [prompts/unit-training.md](prompts/unit-training.md) 模板构造提示词，填入：当前 i、上一章路径、真实本章路径、目标 SKILL.md 路径、attempts 子目录、日志路径、max_attempts、threshold、最近 5 条 lesson 路径（若有）
- [ ] spawn Training Unit（subagent_type: general-purpose），等待返回
- [ ] 把 `chapter_index / final_score / attempts_used / threshold_met` 一行追加到 `alchemist-temp/progress.md`
- [ ] 仅当 i mod 5 == 0 且非末章 → AskUserQuestion 三选一
- [ ] 否则直接进入 i+1

### C.1 Training Unit 内部时序

详见 [architecture.md "Training Unit 内部时序"](architecture.md) 与 [prompts/unit-training.md](prompts/unit-training.md)。

简版：

```
准备 attempt-00（baseline，不动 skill）
  Execution → generated-00.md
  Scoring   → score-00.json + report-00.md（spawn 3 个独立裁判 sub-agent）
  → score ≥ threshold ? 走采纳路径直接进入 Summary
                     : 进入 attempt-01

attempt-NN（NN ≥ 1，最多到 max_attempts）
  快照当前 SKILL.md 到 attempts/chapter-<i>/attempt-<NN>/skill-snapshot/
  Edit     → 改 ≤ 3 维 → 写新 SKILL.md + skill-changes.md
  Execution → generated-NN.md
  Scoring   → score-NN.json + report-NN.md
  Commit    → 看 score 与 prev_best：
              new > prev_best → 采纳，prev_best = new
              new ≤ prev_best → 从快照回滚 SKILL.md
            → 写 commit-log.md
  → score ≥ threshold OR NN == max_attempts ? 进入 Summary : NN++

Summary
  读所有 attempt 的 score / commit-log / report
  → 提炼"哪类改动有效 / 无效"
  → 写 alchemist-temp/lessons/lesson-<i>.md
  → 写 attempts/chapter-<i>/summary.md
  → append 一行 JSON 到 alchemist-temp/logs/training.jsonl
```

### C.2 Training Unit 返回主 agent 的格式（严格）

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

主 agent 输出固定回顾格式：

```
本次训练已暂停。
- 已完成章节：<i> / M
- 当前 skill 路径：<目标 skill 落盘路径>
- 工作目录：<alchemist-temp 路径>
- 续跑方式：开新会话输入 /echo-quill-alchemist 并附上"接着 <alchemist-temp 路径> 的进度继续训练"
```

然后**结束当前 skill 调用**。

### G.4 失败兜底

任一 Training Unit 返回的 `failed_reason` 显示非常规错误（如"SKILL.md 写入失败"）：

1. 主 agent 把错误原样展示给用户
2. 提示："本章训练失败，已停止后续。当前 skill 状态可能停留在中间快照。可以 Read `<目标 skill>/SKILL.md` 检查。修复后重新输入 `/echo-quill-alchemist` 并指定 `<alchemist-temp 路径>`。"
3. **不重试、不跳过、不 spawn 新 Training Unit**
