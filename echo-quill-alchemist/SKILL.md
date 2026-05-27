---
name: echo-quill-alchemist
description: 仅当用户显式输入 `/echo-quill-alchemist` 或明确要求"基于一部小说训练一个续写 skill"、"用整本小说炼一个续写器"、"把这本书的写作风格炼成 skill"等同义请求时才触发；绝不在其他场景自动调用。用户输入是一部完整小说（单文件）或一组章节链接，最终产出是一份可直接被 Claude 加载的"续写小说 skill"——给它喂前一章它就能写出风格、人物、情节走向都贴合原作的下一章。运行流程：（1）按章节拆分原文 → （2）spawn 子 agent 用前 3 章生成 skill 初版 → （3）从第 2 章起逐章训练：用当前 skill + 上一章生成本章 → 与真实本章六维打分 → 不达标则改 skill → 仅当评分上升才采纳改动，否则回滚 → 直到综合相似度 ≥ 0.85 或单章尝试达 5 次上限 → 推进下一章 → 全部章节完成即得最终 skill。**架构上采用三层 agent 分工**：主 agent 仅做参数收集 + 章节循环调度 + 用户暂停询问；每章训练交给一个一次性的"章训练子 agent"；它再 spawn"生成孙子 agent / 评分孙子 agent / 改 skill 孙子 agent"完成盲生成、独立打分、定向改写。运行环境无 git，回滚靠文件快照而非 `git restore`。
---

# echo-quill-alchemist — 小说续写 Skill 训练炉

本 skill 把"一本小说本身"当作训练真值，通过"章节级闭环训练"把作者的写作风格 / 人物声音 / 情节脉络 / 世界观沉淀进一份可被未来 Claude 直接加载的续写 skill。

核心假设：
1. 已发表的章节本身即为"最佳真值"——下一章作者真实写下的字就是答案；
2. 若一份续写 skill 足够完备，AI 仅凭"前一章 + skill"就能写出与作者真实下一章高度一致的内容；
3. "AI 生成的续写"与"作者真实下一章"的差异 = skill 缺失的风格 / 设定 / 人物刻画线索。

## 核心定位（必须先理解，否则会走偏）

**最终产物 = 一份独立可用的续写 skill**。skill 的使用者（未来某个 Claude）会拿"前一章"作输入，写"下一章"作输出；它**不会**也**不该**接触本训练流程的任何中间产物。

因此**写 skill 时必须始终站在"未来 AI 续写小说"的视角**：
- ✅ 正确思路："作者写动作场面时偏短句、单字爆破式收尾，skill 里写一条规则让 AI 续写动作时也这么做"
- ❌ 错误思路："训练第 12 轮发现 AI 续写时句子太长，skill 里加一条 'AI 续写 12 章时应注意句长'"

**绝不要**把训练编号、章节编号、相似度数字、训练历史叙事写进最终 skill 正文。skill 是"时间无关的写作规则陈述"，不是训练日志。

---

## 调度模型（三层 agent 架构）

> **本节是阅读后续所有内容的前提**。读完本节再去看后续阶段，要把"主 agent 应该..."这种含糊指代替换为本节定义的具体角色。

### 三层 agent 分工

```
┌──────────────────────────────────────────────────────────────┐
│ 主 agent（user 主对话）                                       │
│ ─ 做参数收集 + 章节循环调度 + 询问用户是否暂停                 │
│ ─ **不**接触章节正文 / 生成稿 / 评分细节 / skill diff           │
│                                                                │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ 章训练子 agent（每章一次性，跑完关闭）                     │ │
│ │ ─ 承担本文档"工作流程"中"章训练循环"的全部操作员角色：     │ │
│ │   阶段 C/D/E/F + 5 次内部尝试 + 文件级棘轮回滚              │ │
│ │                                                          │ │
│ │ ┌──────────────┐ ┌──────────────┐ ┌────────────────────┐│ │
│ │ │ 生成孙子      │ │ 评分孙子      │ │ 改 skill 孙子      ││ │
│ │ │（盲生成下一章）│ │（独立六维打分）│ │（定向修补 skill）  ││ │
│ │ └──────────────┘ └──────────────┘ └────────────────────┘│ │
│ └──────────────────────────────────────────────────────────┘ │
│ ─ 主 agent 拿到一句话摘要后判断：是否已是末章 / 用户是否要暂停  │
│ ─ 未暂停且未到末章 → 主 agent 启动**新一个**章训练子 agent      │
└──────────────────────────────────────────────────────────────┘
```

### 主 agent 的完整职责（极简，全部职责仅以下几条）

主 agent 在整个 skill 调用期间只做下面 8 件事，**其余一切**都委托给章训练子 agent：

1. **收集启动参数**：小说来源（整本文件路径 / 章节链接列表）、可选的目标 skill 名（缺省自动生成）、可选的"种子章节数"（默认 3）、可选的"单章最大尝试数"（默认 5）、可选的"通过阈值"（默认 0.85）。任一必需项缺失则停下问用户。
2. **执行一次前置环境校验**：仅本次 skill 调用最开始时执行（参见前置环境校验小节），后续章节循环不再重复。
3. **阶段 A：章节切片**——若输入是整本文件，调用 `scripts/split_chapters.py` 按章节标题拆分到 `$RUN/chapters/chapter-NNN.md`；若输入是 URL 列表，逐一 WebFetch 后写入对应文件。
4. **阶段 B：spawn 初始化子 agent**——见"初始化子 agent 提示词模板"，让它读前 K 章（K = 种子章节数，默认 3）一次性生成 skill 初版。
5. **章节循环（i = K+1 ... 末章）**：构造章训练子 agent 提示词（模板见下方），spawn 它（subagent_type: general-purpose）；接收返回的一句话摘要 + 本章最终相似度 + 本章尝试次数 + 本章日志路径；**不读**生成稿 / 评分细节 / skill diff。
6. **每 N 章询问用户是否暂停**（N = 5，可由用户启动时调整）：调用 AskUserQuestion 三选一"继续 / 暂停 / 仅看 progress"。**非询问轮次**自动续跑，不打断用户。
7. **末章训练完成后输出最终摘要**：训练总耗章数、平均相似度、未达阈值的章节清单、最终 skill 落盘路径。
8. **失败兜底**：若某子 agent 返回"硬错误"（如脚本拆章失败、URL 全部抓取失败、skill 文件写入失败），把错误原样展示给用户并停下；不重试、不 spawn 新子 agent。

**主 agent 严禁做的事**：
- ❌ 读 `$RUN/chapters/*.md`（除了让脚本访问；主 agent 不亲自 Read 章节正文，避免上下文污染影响后续章节判断）
- ❌ 读 `$RUN/attempts/*/generated.md`（生成稿是孙子 agent 的产物，主 agent 看了没用且会污染上下文）
- ❌ 读训练中的 SKILL.md 来"复核"孙子 agent 的改动
- ❌ 自己 spawn 生成 / 评分 / 改 skill 孙子 agent（这是章训练子 agent 的职责）
- ❌ 自己执行章节生成、评分、skill 改写
- ❌ 在每章之间向用户长篇汇报本章细节（用户能在 `progress.md` 里看到）

### 章训练子 agent 的完整职责

后续从"工作流程"小节开始描述的"章训练循环"内所有动作，**主语全部默认是"章训练子 agent"**。后续行文为避免冗长，仍会出现"主 agent"字样，**遇到时一律按"章训练子 agent"理解**——除非该段落显式标注"由主 agent 执行（不下放）"。

显式归属主 agent 的段落仅有：
- 前置环境校验
- 阶段 A（章节切片调度）
- 阶段 B（初始化子 agent 调度）
- 阶段 G.1 / G.2 / G.3（章间询问 + 末章总结）
- 本节本身

### 初始化子 agent 提示词模板（主 agent 阶段 B 构造时使用）

```
你是 echo-quill-alchemist 的"初始化子 agent"。你**只跑一次**：读前 K 章原文，产出 skill 初版，然后退出。

【输入参数】
- 章节文件清单：<chapter-001.md ... chapter-00K.md 的绝对路径>
- 目标 skill 落盘路径：<C:\Users\Admin\.agents\skills\<novel-slug>-quill\>
- 小说元信息：<标题、作者、体裁；若用户未提供，从前 3 章自行总结一句话>

【你的职责】
1. 全量读完前 K 章
2. 提取并固化以下要素到一份 SKILL.md：
   a. 叙事视角（第一/第二/第三人称；上帝视角 vs 限知；POV 是否切换）
   b. 文体特征（句长分布、对话密度、修辞偏好、节奏快慢、画面感强弱）
   c. 用词偏好（高频词、忌讳词、专属术语、方言/书面语倾向）
   d. 主要人物（姓名、关系、性格三标签、说话方式样本 1-2 句）
   e. 世界观/设定（时空背景、特殊规则、专有名词表）
   f. 情节结构（章节长度、章末钩子模式、伏笔回收节奏）
   g. 主题与情绪基调（悲喜、冷暖、紧张/松弛）
3. 最后给出"续写时的硬规则"小节（5-10 条），每条用"必须"/"绝不"开头
4. 把 SKILL.md 写到 <目标 skill 落盘路径>/SKILL.md（含 YAML frontmatter，name = <novel-slug>-quill，description 要描述"接续 <小说名> 风格写下一章"，包含触发关键词）

【SKILL.md 写作硬规则】
- 不得出现"训练"、"轮次"、"评分"、"相似度"、"D\d+"、"本轮"、"上一轮"等字样
- 不得引用任何外部训练日志 / 中间产物路径
- 不得出现章节编号引用（如"参考第 3 章"）；要把章节里的写法**抽象成规则**，不引用原文位置
- 用规则陈述句而非过程叙事；想强调时用"硬规则"前缀 + 反例 / 正例对比

【返回给主 agent 的一句话摘要（≤ 80 字）】
- 已落盘 SKILL.md 路径
- 提取到的人物数、术语数、硬规则数
```

### 章训练子 agent 提示词模板（主 agent 在阶段 C 循环里构造）

```
你是 echo-quill-alchemist 的"章训练子 agent"。本次调用你**只训一章**完整流程，跑完返回一句话摘要给主 agent，然后退出（你的上下文不会延续到下一章）。

【输入参数】
- 当前训练章节序号：i（i ≥ K+1，K 为种子章节数）
- 上一章正文路径：$RUN/chapters/chapter-<i-1>.md（你**可以**读，作为生成输入）
- 真实本章正文路径：$RUN/chapters/chapter-<i>.md（你**绝不**亲自读，仅传给评分孙子 agent；详见下方禁读清单）
- 当前 skill 路径：<目标 skill 落盘路径>/SKILL.md（你**可以**读，但每次改动前必须先快照）
- 本章工作目录：$RUN/attempts/chapter-<i>/（attempt-00 / attempt-01 / ... 子目录由你自己创建）
- 本章日志路径：$RUN/logs/chapter-<i>.jsonl
- 单章最大尝试数：max_attempts（默认 5）
- 通过阈值：threshold（默认 0.85）
- 上一章训练摘要（若 i ≥ K+2）：$RUN/attempts/chapter-<i-1>/summary.md（仅可读 summary，不读 generated.md）

【你的职责】（严格按"工作流程"小节"章训练循环"执行）
1. 阶段 C：spawn 一个"生成孙子 agent"（subagent_type: general-purpose），喂当前 skill + 上一章 → 生成 chapter-<i>'.md，落到 $RUN/attempts/chapter-<i>/attempt-00/generated.md
2. 阶段 D：spawn 一个"评分孙子 agent"（与 Phase C 为两次独立调用），喂真实 chapter-<i>.md + 生成 chapter-<i>'.md → 产出 score.json + report.md，落到同一目录
3. 阶段 E 迭代（最多 max_attempts 次循环，含上面 attempt-00）：
   3.1 若本次 score >= threshold → 收尾，跳到阶段 F
   3.2 否则 spawn 一个"改 skill 孙子 agent"，喂 report.md + 当前 SKILL.md → 产出新版 SKILL.md
   3.3 改动落盘前先把当前 SKILL.md 完整复制到 $RUN/attempts/chapter-<i>/attempt-<NN>/skill-snapshot/SKILL.md（NN 是即将进行的下一次 attempt 编号）
   3.4 写入新 SKILL.md → 重新 spawn 生成孙子 + 评分孙子 → 得到新 score
   3.5 比较 new_score vs prev_best_score：
       - new_score > prev_best_score → **采纳**新 SKILL.md，prev_best_score 更新为 new_score
       - new_score <= prev_best_score → **回滚**：从 attempt-<NN>/skill-snapshot/SKILL.md 把当前 SKILL.md 还原回快照内容，prev_best_score 不变
   3.6 attempt 计数 +1，回到 3.1；若已尝试 max_attempts 次仍未达 threshold，**强制收尾**进入阶段 F 并在 summary 中标 warning="未达阈值"
4. 阶段 F：写本章 summary.md（含每次 attempt 分数、是否回滚、最终采纳的版本编号、warning 标记）；append 一行 JSON 到 $RUN/logs/chapter-<i>.jsonl

【你不做的事】
- 不调 AskUserQuestion（主 agent 的活）
- 不前置环境校验（主 agent 已做过）
- 不进入下一章（你只训这一章就退出）
- **绝不亲自读 chapter-<i>.md（真实本章正文）**——读了你就被污染，无法保持评分客观；这份正文只通过文件路径传给评分孙子 agent

【返回给主 agent 的格式】（严格遵守，主 agent 靠这格式做下一步决策）
- 一句话本章摘要（≤ 80 字）
- chapter_index: <i>
- final_similarity: <0.xxx>
- best_attempt_id: <NN>
- attempts_used: <次数>
- threshold_met: true | false
- summary_path: <绝对路径>
- failed_reason: <若 attempts_used == max_attempts 仍 < threshold，写一句话说明主要差距维度；否则 "N/A">

不允许在返回里贴生成稿 / 评分细节 / skill diff 全文（这些已写入 $RUN，主 agent 不读）。
```

---

## 触发条件（严格）

**只有下列情况可触发**：
- 用户显式输入 `/echo-quill-alchemist`
- 用户消息中明确出现"用这本小说训练一个续写 skill"、"基于这部小说炼一个写作 skill"、"把这部小说的风格沉淀成 skill"、"训练一个能续写《X》的 skill"等同义表述
- 用户在上一次本 skill 输出的"中断恢复提示词"中要求继续

**绝不主动触发**。哪怕用户提到"我想写小说"、"帮我续写一段"也不要擅自启动本 skill（那是直接续写需求，不需要训练）。

---

## 输入参数（启动前必须齐备）

| 参数 | 必需？ | 说明 |
|---|---|---|
| 小说来源 | ✅ | 二选一：（A）一份整本小说文件路径（.txt / .md，UTF-8）；（B）按章节顺序排列的 URL 列表 |
| 目标 skill 名 | 可选 | 缺省自动生成 `<novel-slug>-quill`；novel-slug 由小说标题或文件名小写化 + 连字符化得到 |
| 种子章节数 K | 可选 | 默认 3；用前 K 章生成初版 skill，从第 K+1 章开始训练循环 |
| 单章最大尝试数 | 可选 | 默认 5；某章尝试 max_attempts 次仍未达阈值则强制推进并标 warning |
| 通过阈值 | 可选 | 默认 0.85；综合相似度达到此值即通过 |
| 暂停询问周期 N | 可选 | 默认 5；每完成 N 章问一次用户是否暂停 |

任一必需项缺失：停下问用户，不得猜测。

---

## 目录与文件约定

本 skill 运行时建立 `$RUN`：

```
$RUN = <novel 输入文件所在目录>/.echo-quill/run-<YYYYMMDD-HHMM>/
├── chapters/
│   ├── chapter-001.md          # 拆分/抓取后的章节正文
│   ├── chapter-002.md
│   └── ...
├── attempts/
│   ├── chapter-002/            # 仅 i >= K+1 的章节才有 attempts 目录
│   │   ├── attempt-00/
│   │   │   ├── skill-snapshot/SKILL.md   # 本次尝试开始前的 skill 快照
│   │   │   ├── generated.md              # 本次生成的下一章
│   │   │   ├── score.json                # 六维分数 + 综合
│   │   │   └── report.md                 # 评分细节 + 归因
│   │   ├── attempt-01/
│   │   ├── ...
│   │   └── summary.md          # 本章训练摘要
│   └── ...
├── logs/
│   ├── training.jsonl          # 每次 attempt 一行（机器可读）
│   └── chapter-<i>.jsonl       # 单章日志（章训练子 agent append）
├── progress.md                 # 主 agent 视图（人类可读）
└── final-summary.md            # 训练全结束后的总览（主 agent 写）

目标 skill 落盘路径：C:\Users\Admin\.agents\skills\<novel-slug>-quill\
├── SKILL.md                    # 训练得到的最终 skill；训练过程中持续被改写
└── (可选) references/...       # 改 skill 孙子 agent 若觉得有必要可分文件
```

**硬规则**：
- `$RUN` 必须建在小说输入文件**所在目录**的 `.echo-quill/` 子目录下；不得写入用户主目录或全局位置
- 同一小说多次训练按时间戳区分子目录，**不要覆盖**上一次
- 每次 attempt 必须先把当前 SKILL.md 复制到 `attempt-<NN>/skill-snapshot/`，再写新 SKILL.md——这是"非 git 棘轮回滚"的物质基础
- **本运行环境无 git**——所有回滚 / 历史追溯依靠文件快照而非 `git restore`

---

## 工作流程（A → B → C 循环 → G）

> 阶段总览：环境校验 → A 章节切片 → B 初版 skill → C 章训练循环（含 D / E / F 三相）→ G 章间询问 + 末章总结

### 前置环境校验（仅在本次 skill 调用最开始时执行一次）

仅在以下两种入口必须执行校验：
1. 用户首次输入 `/echo-quill-alchemist`（或同义请求）
2. 用户在新会话里要求"接着上次的训练继续"——此时是新会话，等同于首次触发

任何一项校验不通过都停下，不得继续。

#### 校验 1：脚本可执行

```bash
python --version    # 或 python3 --version
```

主 agent 用 PowerShell 执行 `python --version` 验证 Python 在 PATH 中可用。无 Python 则停下告知用户："本 skill 的章节切片功能依赖 Python 3，请安装 Python 后再启动。"

#### 校验 2：输入文件 / URL 列表可达

- 整本文件输入：`Test-Path <path>` 必须返回 True，文件大小 > 0
- URL 列表输入：对每个 URL 执行一次 WebFetch（仅取首屏 200 字节用于探活）。任一 URL 返回 4xx / 5xx / DNS 失败 → 停下让用户检查链接

#### 校验 3：目标 skill 落盘路径可写

确认 `C:\Users\Admin\.agents\skills\` 存在且可写。`<novel-slug>-quill\` 子目录若**已存在**：停下询问用户"目标路径已有同名 skill，三选一：(A) 覆盖（旧 skill 备份到 `<...>-quill.bak-<timestamp>\`） (B) 改用新名 (C) 取消训练"。**不得**默默覆盖。

校验全部通过后，继续阶段 A。

### 阶段 A — 章节切片（由主 agent 直接执行）

#### A.1 整本文件输入

```bash
python C:\Users\Admin\.agents\skills\echo-quill-alchemist\scripts\split_chapters.py \
    --input "<整本文件路径>" \
    --output-dir "<$RUN/chapters>"
```

脚本会按以下优先级匹配章节标题：
1. 中文："第[一二三四五六七八九十百千〇零\d]+[章回卷篇]"
2. 英文："Chapter\s+\d+"、"Chapter\s+[IVXLCM]+"
3. 数字："^\d+\.?\s+\S"

每个章节输出为 `chapter-001.md`、`chapter-002.md`...，文件首行保留原章节标题。

脚本输出到 stdout 一份 JSON 摘要（章节数、各章字数）。主 agent 解析此摘要，把"章节数"作为后续循环的上限。

**若拆分得到的章节数 < K + 2**（种子章节用掉 K 章后剩余 < 2 章，无法训练）→ 主 agent 停下告知用户"章节数太少（< K+2），训练循环至少需要 1 章训练数据，请检查输入或减小 K"。

#### A.2 URL 列表输入

主 agent 对列表中的每个 URL 调用 WebFetch（prompt: "提取页面正文为纯文本，去掉广告 / 导航 / 推荐链接 / 评论区"），把结果写入 `$RUN/chapters/chapter-NNN.md`，文件首行加一行 `# <从页面 title 抽取的章节标题或 URL 末段>`。

WebFetch 失败的 URL：跳过并记录到 `$RUN/logs/fetch-errors.log`。结束后若**失败章节占比 > 20%**或**失败章节连续 ≥ 3 章**→ 停下告知用户"章节抓取失败过多，建议改用整本文件输入"。

### 阶段 B — 初版 skill 生成（由主 agent 调度，初始化子 agent 执行）

#### 【硬规则】必须 spawn 子 agent 执行，主 agent 不亲自写初版 skill

主 agent 在阶段 A 已经知道章节文件存在，但**不应**自己 Read 任何章节正文。原因：阶段 C 循环中主 agent 需要客观判断章训练子 agent 返回的相似度数字；一旦主 agent 读过章节正文，对生成质量就有先验判断，会在（潜意识层面）倾向某一方向。

主 agent 在阶段 B 唯一的动作清单：

- [ ] 用上方"初始化子 agent 提示词模板"构造提示词（填入前 K 章路径 + 目标 skill 落盘路径）
- [ ] 调用 Agent 工具（subagent_type: general-purpose），等待完成
- [ ] 子 agent 完成后，**仅** Read 目标 SKILL.md 的前 30 行确认 frontmatter 正确（不读后续正文，避免污染）

#### 备选：若 Agent 工具不可用

极端情况下（运行环境禁用了 Agent 工具），可以退化为"主 agent 直接读前 K 章 + 强制隔离声明"：

1. 主 agent 在 `$RUN/notes/phase-b-fallback.md` 写一段："Agent 工具不可用，主 agent 已读章节 1-K，后续阶段 C 的相似度判断带先验偏差。"
2. 主 agent 自己产出初版 SKILL.md
3. 在 `progress.md` 显式标"本次训练 Phase B 未使用子 agent，盲度打折"

**备选模式仅在 Agent 工具确实不可用时使用**，不能作为常规流程。

### 阶段 C — 章训练循环（i = K+1 ... 末章）

> 主 agent 对每一章 i：构造章训练子 agent 提示词 → spawn → 等待返回 → 写一行到 progress.md → 判断是否到询问周期 → 进入下一章。

#### 主 agent 在阶段 C 的唯一动作清单（每章）

- [ ] 用上方"章训练子 agent 提示词模板"构造提示词，填入：当前章节序号 i、上一章路径、真实本章路径、SKILL.md 路径、attempts 子目录、日志路径、max_attempts、threshold、上一章 summary 路径（若 i ≥ K+2）
- [ ] 调用 Agent 工具（subagent_type: general-purpose），等待完成
- [ ] 子 agent 返回后：把 `chapter_index / final_similarity / attempts_used / threshold_met` 一行追加到 `$RUN/progress.md`
- [ ] **仅当 i 是询问周期的整数倍**（即 i mod N == 0，N 默认 5）：调用 AskUserQuestion 询问"继续 / 暂停 / 仅看 progress"
- [ ] 非询问轮次：直接进入下一章（i++）

#### 章训练子 agent 内部流程（章训练子 agent 自己执行，下文"主 agent"指章训练子 agent）

##### 阶段 C.1 — 生成孙子 agent

提示词必须至少包含：

```
你是 echo-quill-alchemist 的生成孙子 agent。仅凭"前一章正文 + 续写 skill"写出"下一章"。

【输入】
- 当前 skill：<目标 skill 落盘路径>/SKILL.md（必读全文）
- 前一章正文：$RUN/chapters/chapter-<i-1>.md（必读全文）
- 输出路径：$RUN/attempts/chapter-<i>/attempt-<NN>/generated.md

【绝对禁止访问】
- 真实本章正文 $RUN/chapters/chapter-<i>.md（任何形式：Read / Glob / Grep / 找替代路径）
- 后续章节 $RUN/chapters/chapter-<j>.md（j > i）
- 历史 attempts 目录下的任何 generated.md / score.json / report.md（这些是别的尝试，不是你的输入）
- 训练日志 $RUN/logs/*

【输出要求】
- 字数与前一章相近（±30% 内）
- 不带任何元注释（如"以下是续写"、"作者注："）；纯小说正文
- 第一行可以是章节标题（按 skill 中章节命名规则）；其后是正文

【完成前自检】
- [ ] 未读真实本章 chapter-<i>.md
- [ ] 未读后续章节
- [ ] 未读其它 attempt 目录
- [ ] 输出文件已落盘到指定路径

【返回章训练子 agent】一句话摘要（写了多少字 + 主要情节走向，≤ 100 字）+ generated.md 绝对路径
```

##### 阶段 C.2 — 评分孙子 agent

提示词必须至少包含：

```
你是 echo-quill-alchemist 的评分孙子 agent。基于"真实本章 vs 生成本章"做客观六维打分，绝不被任何一方表达风格带偏。

【输入文件】
- 真实本章：$RUN/chapters/chapter-<i>.md
- 生成本章：$RUN/attempts/chapter-<i>/attempt-<NN>/generated.md
- 评分细则：C:\Users\Admin\.agents\skills\echo-quill-alchemist\references\scoring-rubric.md（必读）

【绝对禁止访问】
- 当前 skill SKILL.md（你不评估 skill 质量，只评估两段文本的相似度）
- 历史 attempts 的 score.json / report.md（避免被上次分数锚定）
- 后续章节 chapter-<j>.md（j > i）
- 训练日志 / progress.md / summary.md

【六维评分轴】
1. 语言风格 (style)        权重 0.25 — 句长分布、修辞、画面感、节奏
2. 情节连贯 (plot)         权重 0.20 — 续写是否承接前章悬念、是否走在合理情节方向上
3. 人物刻画 (character)    权重 0.20 — 角色行为 / 对白 / 动机是否符合人设
4. 节奏与基调 (tone)       权重 0.15 — 紧张/松弛、悲喜、冷暖
5. 世界观一致 (world)      权重 0.10 — 设定 / 术语 / 规则是否前后一致
6. 用词遣句 (diction)      权重 0.10 — 高频词、忌讳词、专属词使用

每轴打 0.0-1.0，按权重加权得 overall_similarity。

【输出】
1. score.json（机器可读）→ $RUN/attempts/chapter-<i>/attempt-<NN>/score.json
2. report.md（含每轴具体差异 + 归因到 skill 缺陷点）→ 同目录 report.md

【完成前自检】
- [ ] 未读 SKILL.md
- [ ] 未读其它 attempt 的 score.json / report.md
- [ ] 未读后续章节
- [ ] 六轴均给出 0.0-1.0 数值；overall_similarity 严格按权重公式计算

【返回章训练子 agent】一段 ≤ 5 行摘要：overall_similarity + 各轴分数 + 排名前 2 的差距维度 + report.md 路径
```

`score.json` 结构：

```json
{
  "chapter": <i>,
  "attempt": <NN>,
  "axes": {
    "style":     { "score": 0.85, "weight": 0.25, "weighted": 0.2125 },
    "plot":      { "score": 0.70, "weight": 0.20, "weighted": 0.140 },
    "character": { "score": 0.80, "weight": 0.20, "weighted": 0.160 },
    "tone":      { "score": 0.75, "weight": 0.15, "weighted": 0.1125 },
    "world":     { "score": 0.95, "weight": 0.10, "weighted": 0.095 },
    "diction":   { "score": 0.85, "weight": 0.10, "weighted": 0.085 }
  },
  "overall_similarity": 0.8050,
  "top_gaps": ["plot", "tone"],
  "notes": "..."
}
```

##### 阶段 C.3 — 改 skill 孙子 agent（仅当 overall_similarity < threshold 时触发）

提示词必须至少包含：

```
你是 echo-quill-alchemist 的改 skill 孙子 agent。基于一份"差距报告"对当前 SKILL.md 做**最小修补**——只改与差距相关的部分，不重写整份 skill。

【输入】
- 当前 skill：<目标 skill 落盘路径>/SKILL.md（必读全文）
- 差距报告：$RUN/attempts/chapter-<i>/attempt-<NN-1>/report.md（必读）

【绝对禁止访问】
- 真实本章正文 chapter-<i>.md（你不该见到答案，只该看 report 转述的差距）
- 生成本章 generated.md（同理）
- 历史 attempts 目录的快照
- 后续章节

【改写硬规则】
- 单次改动 ≤ 3 处（计为：每个 Edit 算 1 处；新增整段也算 1 处）
- 优先修补 report.md 中"top_gaps"指向的维度；其它维度本次不动
- 改动必须是规则陈述（"必须 / 绝不 / 应该"），不写训练叙事
- 严禁出现"训练第 N 轮"、"上一轮发现"、"D\d+"、"评分"、"相似度"、"attempt"等字样
- 改动后整份 SKILL.md 仍要符合 YAML frontmatter + 正文 markdown 结构
- 不得改 frontmatter 的 name / description（保持 skill 身份稳定）

【输出】
- 直接覆盖 <目标 skill 落盘路径>/SKILL.md
- 同时把"本次改动摘要（每处一行，≤ 50 字）"写入 $RUN/attempts/chapter-<i>/attempt-<NN>/skill-changes.md

【完成前自检】
- [ ] 未读真实本章正文
- [ ] 未读 generated.md
- [ ] SKILL.md 正文 grep "训练 / 轮 / D\d+ / 相似度 / attempt / 评分" 无命中
- [ ] frontmatter 的 name / description 未被修改

【返回章训练子 agent】一句话摘要：本次改了哪 ≤ 3 处 + skill-changes.md 路径
```

##### 阶段 C.4 — 棘轮回滚（章训练子 agent 自己执行）

每次 `attempt-<NN>` 完成评分后，章训练子 agent 自己做以下判断：

```
prev_best_score = 历次 attempt 的最高 overall_similarity（含 attempt-00）
new_score       = 本次 attempt 的 overall_similarity

if new_score >= threshold:
    # 达标，直接收尾，跳到阶段 F
    accepted = true
    break
elif new_score > prev_best_score:
    # 改 skill 起到了正面作用 → 采纳
    accepted = true
    prev_best_score = new_score
    （SKILL.md 已是改 skill 孙子写下的新版，不动）
else:
    # 改坏了 → 回滚
    accepted = false
    cp $RUN/attempts/chapter-<i>/attempt-<NN>/skill-snapshot/SKILL.md  →  <目标 skill 落盘路径>/SKILL.md
    （prev_best_score 保持原值；进入下一次 attempt 时，改 skill 孙子读到的是回滚后的 skill）

if attempts_used >= max_attempts:
    # 强制收尾
    break
```

注意：
- `attempt-00` 没有"前一次"可比，prev_best_score 直接初始化为 attempt-00 的 overall_similarity
- 每次写新 SKILL.md 之前**必须**已经把当前 SKILL.md 复制到当次 attempt 的 `skill-snapshot/`；这是物理回滚的保证
- 章训练子 agent 自己做 cp / 覆盖；不要 spawn 第四个孙子 agent 来做这点小事

##### 阶段 C.5 — 写 summary（章训练子 agent）

把本章 summary.md 写到 `$RUN/attempts/chapter-<i>/summary.md`：

```markdown
# 第 <i> 章训练摘要

- 训练开始：<timestamp>
- 训练结束：<timestamp>
- 尝试次数：<attempts_used> / <max_attempts>
- 是否达阈值（≥ <threshold>）：<是 / 否>
- 最终采纳的 attempt：<NN>
- 最终 overall_similarity：<0.xxx>

## 历次 attempt
| Attempt | overall | style | plot | character | tone | world | diction | 改动 | 是否采纳 |
|--|--|--|--|--|--|--|--|--|--|
| 00 | 0.78 | ... | ... | ... | ... | ... | ... | （初次生成） | 是 |
| 01 | 0.82 | ... | ... | ... | ... | ... | ... | 加了对白节奏规则 | 是 |
| 02 | 0.81 | ... | ... | ... | ... | ... | ... | 调整心理描写规则 | 否（回滚） |
| ... |

## 主要差距维度（最终未达阈值时填）
- top_gap_1: <axis> — <一句话原因>
- top_gap_2: <axis> — <一句话原因>

## 本章累计 skill 净改动（最终采纳的版本相对训练前）
（按文件级 diff 摘要列出，逐处一行）
```

同时 append 一行 JSON 到 `$RUN/logs/training.jsonl`：

```json
{"chapter": 7, "attempts_used": 3, "final_similarity": 0.872, "threshold_met": true, "best_attempt": 2, "ts": "2026-05-27T15:42:11"}
```

### 阶段 G — 章间询问 + 末章总结（主 agent 执行）

#### G.1 章间询问（每 N 章一次，N 默认 5）

主 agent 在某章训练子 agent 返回后判断：

- 若刚训完的 i 是末章 → 跳到 G.2
- 若 `i mod N == 0` 且不是末章 → 调用 AskUserQuestion：

```
question: "已完成第 i 章（共 M 章）。最近 N 章平均相似度 X.X%，未达阈值章节 P 个。是否继续？"
options:
  - "继续训练（推荐）" — 进入第 i+1 章
  - "暂停训练" — 输出当前进度后结束本次 skill 调用
  - "先看 progress" — Read $RUN/progress.md 全文打印；再次询问回到此处
```

- 否则（非询问周期且非末章）→ 直接进入下一章，不打断用户

#### G.2 末章总结

末章训练子 agent 返回后，主 agent 写 `$RUN/final-summary.md`：

```markdown
# echo-quill-alchemist 训练总结

## 输入
- 小说来源：<file path or URL list>
- 总章节数：M
- 种子章节数：K
- 训练章节数：M - K

## 通过情况
- 达阈值章节数：P / (M-K)
- 平均 overall_similarity：X.X%
- 中位数 overall_similarity：Y.Y%
- 最差章节：第 j 章（X.X%，未达阈值）
- 各维度全程平均分：
  - style: X.X | plot: X.X | character: X.X | tone: X.X | world: X.X | diction: X.X

## 最终 skill
- 落盘路径：<C:\Users\Admin\.agents\skills\<novel-slug>-quill\>
- 用法：用户跟 Claude 说"用 <novel-slug>-quill 续写：<前一章正文>"即可
- 触发关键词（来自 SKILL.md description）：<copy 自 frontmatter>

## 未达阈值章节清单（若有）
| 章节 | overall | top_gaps |
|--|--|--|
| j  | 0.82 | plot, character |
| ...|

（这些章节的差距已沉淀到 skill 中，但仍未达 0.85；建议人工 review report.md）

## 工作目录
- $RUN: <绝对路径>
- 训练日志：$RUN/logs/training.jsonl
```

写完后输出一句话给用户："训练完成。最终 skill 已落盘：`<path>`。详见 `<final-summary 路径>`。"

#### G.3 暂停路径（用户选了"暂停训练"）

主 agent 输出固定回顾格式：

```
本次训练已暂停。
- 已完成章节：<i> / M
- 当前 skill 路径：<目标 skill 落盘路径>
- 工作目录：$RUN
- 续跑方式：开新会话输入 /echo-quill-alchemist 并附上"接着 <$RUN> 的进度继续训练"
```

然后**结束当前 skill 调用**。

#### G.4 失败兜底

若任一章训练子 agent 返回的 `failed_reason` 显示出非常规错误（如"SKILL.md 写入失败"、"评分孙子 agent 拒绝执行"）：
1. 主 agent 把错误原样展示给用户
2. 主 agent 提示："本章训练失败，已停止后续章节训练。当前 skill 状态可能停留在中间快照。可以 Read `<目标 skill 落盘路径>/SKILL.md` 检查当前状态。修复问题后重新输入 `/echo-quill-alchemist` 并指定 `$RUN`。"
3. **不重试、不跳过、不 spawn 新章训练子 agent**

---

## Skill 写作规范（**硬规则**）

最终落盘的 SKILL.md 是给"未来 Claude 续写小说"读的，不是给训练流程读的。以下规范贯穿初版生成 + 每次改写：

### ❌ 错误措辞（严禁写入最终 SKILL.md）

```
训练第 12 轮发现 AI 续写时短句不够多 ...
本章训练把节奏规则补到了对白部分 ...
基于差距报告，加强了世界观描述的规则 ...
attempt-03 采纳了对话节奏规则 ...
```

### ✅ 正确措辞

直接陈述续写规则本身，配反例 / 正例。例：

错误写法：
> 训练第 5 章发现生成的对话太书面化，加了一条规则。

正确写法：
> **对白必须口语化**：避免书面书写常用的副词/连词链（"然而 / 因而 / 进而"）；高情绪场面下允许半句、破折号断句。
> ❌ 错误："然而，他终于意识到了自己的错误，因而决定向她道歉。"
> ✅ 正确："他攥紧了拳头。'对不起'——他说。"

### 强调规则的措辞工具

- **硬规则** 前缀
- **绝不 / 必须 / 唯一** 等限定词
- ❌ 反例 + ✅ 正例对照
- 节首"本节是本 skill 最重要的约束之一"等强调语

### 自检（每次孙子 agent 写完 SKILL.md 必做）

- 全文 grep "训练" / "轮" / "D\d+" / "本轮" / "上一轮" / "上一章" / "第 \d+ 章" / "attempt" / "评分" / "相似度" / "差距报告"——若有命中，删除或改写为时间无关的规则陈述
- frontmatter 的 `name` / `description` 不得在训练中被改写
- 整份 SKILL.md 字数 ≤ 8000（超出则把详细规则分到 `references/` 子文件，主 SKILL.md 用一句话指向）

---

## Plan 契约（生成稿 / 真实章节通用结构暗示）

无显式 plan 模板（小说本身就是结构化文本）。两条暗示：

1. 生成孙子 agent 输出的 `generated.md` 第一行必须是章节标题，与真实本章风格一致（"第 N 章 标题" 或 "Chapter N: Title"）
2. 评分孙子 agent 在做"情节连贯"轴评分时，要把生成稿的"开场如何承接前章 / 中段是否合理推进 / 章末钩子是否符合作者节奏"作为三个子项分别打分再平均

---

## 禁止事项

- **不得修改用户的小说原文**（`$RUN/chapters/` 在切片后只读）
- **主 agent 不得 Read 任何章节正文 / 生成稿 / 评分细节**（仅可读 progress.md 和 final-summary.md，及在用户选"先看 progress"时的 progress.md）
- **生成孙子 agent 不得读真实本章 / 后续章节 / 历史 attempts**
- **评分孙子 agent 不得读 SKILL.md / 历史 score.json / 历史 report.md / progress.md**（保持评分客观）
- **改 skill 孙子 agent 不得读真实本章正文 / 生成稿**（只读差距报告）
- **不得在 SKILL.md 正文出现训练叙事字样**（见上方硬规则）
- **不得在未征求用户同意的情况下覆盖已存在的同名目标 skill 目录**
- **不得**主动触发本 skill；只能由用户显式调用
- **不得**用尝试上限上调 / 阈值下调来绕过差距问题——遇到难章节，让它带 warning 推进，留人工 review
- **不得**让一个章训练子 agent 跨多章工作（每章必须新 spawn）

---

## 自检清单

> 自检清单按 agent 角色分组：A 组由主 agent 自检；B 组由章训练子 agent 自检（在它返回主 agent 之前）。

### A 组 — 主 agent 自检

- [ ] **前置环境校验已完成**：python 可用、输入文件 / URL 可达、目标 skill 路径可写
- [ ] **阶段 A**：章节切片成功（脚本退出码 0 或 URL 失败率 ≤ 20%），章节数 ≥ K + 2
- [ ] **阶段 B**：通过 Agent 工具 spawn 初始化子 agent 执行（或显式标注备选模式 + 原因）；目标 SKILL.md 已落盘 + frontmatter 正确
- [ ] **阶段 C**：每章通过 spawn 章训练子 agent 执行；未自己读章节正文 / 生成稿 / 评分细节 / SKILL.md 正文
- [ ] **每 N 章**通过 AskUserQuestion 询问"继续 / 暂停 / 仅看 progress"
- [ ] **末章**已写 final-summary.md 并向用户输出落盘路径
- [ ] 主 agent 上下文未读入任何章节正文、生成稿、score.json、report.md（"仅看 progress"路径除外，且只读 progress.md 一份）

### B 组 — 章训练子 agent 自检（每章各自完成；返回主 agent 前打勾）

- [ ] 已通过 Agent 工具 spawn 生成孙子 agent（或显式标注备选模式）；attempt-00 / generated.md 落盘
- [ ] 已通过 Agent 工具 spawn 评分孙子 agent（与生成孙子为两次独立调用）；score.json + report.md 落盘
- [ ] 评分孙子 agent 提示词未包含历史分数；评分孙子未读 SKILL.md / 历史 score.json
- [ ] 当 score < threshold 时已通过 spawn 改 skill 孙子 agent 进行修补；改 skill 孙子未读真实本章 / 生成稿
- [ ] 每次 attempt 之前已把当前 SKILL.md 复制到 attempt-<NN>/skill-snapshot/
- [ ] 棘轮规则正确执行：new_score > prev_best_score 才采纳；否则从 skill-snapshot 回滚 SKILL.md
- [ ] attempts_used ≤ max_attempts；超出已强制收尾并标 warning
- [ ] summary.md 已写齐；training.jsonl 已 append 一行
- [ ] 章训练子 agent 在写完 summary 后立即返回主 agent，未尝试调用 AskUserQuestion，未尝试自驱进入下一章
- [ ] **返回主 agent 的格式严格遵循约定**：摘要 ≤ 80 字 + chapter_index + final_similarity + best_attempt_id + attempts_used + threshold_met + summary_path + failed_reason；未在返回里贴生成稿 / 评分细节 / skill diff 全文
- [ ] **章训练子 agent 自身未亲自读真实本章 chapter-<i>.md**（仅把路径传给评分孙子 agent）
