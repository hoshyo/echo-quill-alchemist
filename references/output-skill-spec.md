# 产出 Skill 标准形式

> 训练产出 = 一份**独立可用**的续写 skill。它的使用者（未来某个 Claude）拿"前一章"作输入，写"下一章"作输出；它**不会也不该**接触本训练流程的任何中间产物。
>
> 因此写产出 skill 时必须始终站在"未来 AI 续写小说"的视角，而非"训练日志"视角。

## 落盘结构

```
<本 skill 同级目录>/<novel-slug>-quill/
├── SKILL.md                                 # 主文件 ≤ 8000 字
└── references/
    ├── author-profile.json                  # 机器可读的作者画像（轻量索引；无故事概要）
    ├── synopsis.md                          # 滚动故事概要（三段式：主线骨架 / 近期细节 / 活跃伏笔）
    ├── character-cards/
    │   ├── <name-1>.md                      # 详细人物卡（每位 1 份独立 .md，必有）
    │   └── ...
    ├── style-rules.md                       # 详细风格规则
    └── world-bible.md                       # 世界观 / 术语 / 设定
```

**硬规则**：`character-cards/<slug>.md` 是详细人物数据的**唯一物理真相**——`author-profile.json` 的 `characters[]` 数组只能存"轻量索引"（见下文 schema），**绝不能**把 tags / speech_sample / behavior 等详细字段直接塞 JSON。Init / Edit / Summary 等任何模块写入时若发现 characters[] 增/删/改名，**必须**同步增/删/改对应 .md 文件，否则视为约束违反。

## 主 SKILL.md 规范

### Frontmatter

```yaml
---
name: <novel-slug>-quill
description: 仅当用户明确要求"用 <novel-slug>-quill 续写"、"按《<小说名>》风格写下一章"、"接续这本小说"等同义请求时才触发；输入是上一章正文，产出是风格、人物、情节都贴合原作的下一章。
---
```

`description` 必须包含触发关键词（小说名、续写关键词），用于 Claude 自动激活。

### 正文结构（建议章节）

```markdown
# <novel-slug>-quill — 续写 <小说名>

## 用法
（一句话告诉使用者：喂上一章正文，写下一章）

## 作者画像（载入即用）
- 视角：<第一/第三人称、限知/全知>
- 文体：<句长偏好、修辞密度、节奏特征>
- 用词：<高频词样本 / 忌讳词列表>
- 主题与基调：<冷暖、悲喜、明暗>
（详细数据见 references/author-profile.json）

## 主要人物
- <人物 1>：<3 标签 + 1 句说话样本>
- <人物 2>：...
（详细见 references/character-cards/）

## 世界观要点
（短列表，详细见 references/world-bible.md）

## 续写硬规则
（5-15 条，每条用"必须 / 绝不 / 唯一"开头，配 ❌ 反例 / ✅ 正例对照）

## 续写自检
- [ ] 第一段是否承接上一章末段的场景 / 情绪 / 时间线
- [ ] 主要人物的对白是否符合 character-cards 中的语气
- [ ] 句长直方图是否落在 author-profile.json 的目标区间
- [ ] 章末是否抛出与作者节奏一致的钩子
- [ ] 未引入违反 world-bible 的设定 / 术语
```

### 主 SKILL.md 写作硬规则（严禁违反）

禁用词分两类：

**❌ 强禁词（任意命中即违反）——训练流程元叙事**
- `训练`、`轮`、`D\d+`、`本轮`、`上一轮`
- `attempt`、`评分`、`相似度`、`score`、`差距报告`
- `第 \d+ 章`（含中英文数字，如"第三章"、"第 12 章"、"Chapter 7"）
- 任何外部训练日志路径引用
- 训练编号、相似度数字

**⚠️ 限定禁词（语境敏感）**
- 像"上一章"、"前一章"、"前文"作为**普通续写词汇**允许（产出 skill 的"用法"段必须告诉使用者输入是什么，绕不开）
- 但"上一章 AI 续写时…"这种**带训练叙事色彩**的句子仍禁
- 自检判定：grep 命中"上一章 / 前一章" → 看上下文，是普通指代写允许；混着"训练 / 轮 / attempt / 评分"任一强禁词出现 → 仍违反

**✅ 正确写法**：
- 直接陈述续写规则本身，配 ❌ 反例 / ✅ 正例对照
- 用"必须 / 绝不 / 唯一"前缀强调硬规则
- 用"作者写动作场面时偏短句、单字爆破式收尾，因此续写动作时也这么做"——而非"训练第 12 轮发现 AI 续写时句子太长"

### 字数约束

主 SKILL.md ≤ 8000 字。详细规则下沉到 `references/style-rules.md`、详细人物到 `character-cards/`、详细设定到 `world-bible.md`。

## author-profile.json 规范

机器可读的作者画像 —— **只存轻量索引与统计画像，不嵌任何长 markdown 文本**。Init Skill Unit 第一次写，每次 Edit 涉及画像调整时也由 Edit Module 更新。

```json
{
  "schema_version": 1,
  "novel_title": "<原书标题>",
  "novel_slug": "<slug>",
  "extracted_from": ["chapter-001.md", "chapter-002.md", "chapter-003.md"],
  "extracted_at": "<ISO 8601>",

  "voice": {
    "person": "first | second | third",
    "knowledge": "limited | omniscient | mixed",
    "pov_switches": "stable | per-chapter | per-scene"
  },

  "sentence_length_histogram": {
    "short_lt_12": 0.42,
    "mid_12_25":   0.43,
    "long_gt_25":  0.15,
    "samples": 200
  },

  "rhetoric_density_per_kilo_chars": {
    "simile":      2.1,
    "metaphor":    1.4,
    "personification": 0.7,
    "parallelism": 0.3
  },

  "high_freq_content_words_top_30": [
    {"word": "...", "freq_per_10k_chars": 12.3},
    "..."
  ],

  "forbidden_words": [
    "总而言之", "不可否认", "值得注意的是", "综上所述",
    "..."
  ],

  "domain_terms": [
    {"term": "...", "category": "place | person | org | spell | item | other", "first_seen_chapter": 1, "definition": "..."}
  ],

  "characters": [
    {
      "name": "...",
      "aliases": ["..."],
      "first_seen_chapter": 1,
      "last_seen_chapter": 7,
      "card_path": "references/character-cards/<slug>.md"
    }
  ],

  "tone": {
    "primary": "tense | warm | melancholic | calm | bleak | ...",
    "secondary": "...",
    "chapter_end_pattern": "cliffhanger | quiet-pause | open-question | image | ..."
  },

  "synopsis_path": "references/synopsis.md"
}
```

**关键字段说明**：
- `sentence_length_histogram` 三档比例之和必须 ≈ 1.0
- `high_freq_content_words_top_30` 用于评分模块的 diction 维度
- `domain_terms` 累加而非覆盖——每章新增的术语 Edit 时 append
- **`characters[]` 是轻量索引**：只允许 `name / aliases / first_seen_chapter / last_seen_chapter / card_path` 五字段；详细数据（tags / speech_sample / behavior_pattern / relations / arc）**只能**写入 `card_path` 指向的 .md 文件
- **`synopsis_path` 取代旧的内嵌 `rolling_synopsis` 字段**：故事概要单独成 markdown，避免 2000 字中文嵌 JSON 时的转义事故

## synopsis.md 规范（三段式滚动故事概要）

Execution Module 必读全文；Summary Module 每章末尾 patch 三段。代替旧的 `author-profile.json.rolling_synopsis` 字段。

```markdown
# <小说名> 滚动故事概要

> 写"故事走到哪里"，不写章节编号。续写者读它来定位"现在该写什么走向"。

## 主线骨架（≤ 1500 字）
（故事开篇至今的核心因果链。低频更新——只有"主线推进"事件才进，配角支线不进。）
- <事件 1：人物 + 动作 + 后果>
- <事件 2：...>
- ...

## 近期细节（≤ 1500 字，最近 3 个训练章节滚动窗口）
（最近 3 章发生的具体事件、对白要点、新出场人物，超出 3 章的事件**必须降级**——要么并入"主线骨架"，要么丢弃。）
- <近期事件 A>
- <近期事件 B>
- ...

## 活跃伏笔（≤ 500 字）
（已埋下、尚未兑现的钩子。续写时优先考虑兑现其中之一。）
- <伏笔 1>：埋于何处（章节范围，不写具体编号；如"开篇阶段"、"近期"），尚未兑现
- <伏笔 2>：...
- 已兑现的从清单移除
```

**字数预算硬规则**：三段合计 ≤ 3500 字。超出 → Summary Module 必须先压缩"主线骨架"早期内容（如把 5 条整合成 1 条总括），再追加新内容。

**为什么三段**：
- 主线骨架低频更新 → 长程叙事方向稳定
- 近期细节滚动窗口 → 短程伏笔、对白回声不丢
- 活跃伏笔显式管理 → 防止"埋了但忘了兑现"

## character-cards/<name>.md 规范

每个主要人物（在 author-profile 出场 ≥ 2 次）一份。**这是详细人物数据的唯一物理真相**——author-profile.json 的 characters[] 只有索引，所有 tags / speech / behavior 都在此 .md。文件名 = 人物名 slug（拉丁字母小写、中文保留、空格转 `-`）。

```markdown
# <人物名>

## 别名 / 称呼
- 第三人称叙述里：...
- 对白中其他角色称之为：...

## 性格三标签
- <标签 1>
- <标签 2>
- <标签 3>

## 说话方式
- 句式偏好：<短句 / 长句 / 反问 / 文白>
- 高频口头禅 / 用词：<列表>
- 情绪激动时的语言变化：...

## 行为模式
- 面对冲突：<决策倾向>
- 面对亲密关系：<...>
- 独处场景：<...>

## 对白样本
- "<样本 1>"
- "<样本 2>"

## 与他人的关系
- <对方 A>：<关系性质 + 关键事件>
- <对方 B>：...

## 至今的弧光（Summary Module 维护）
- 章 1-K：<状态>
- 章 K+1：<变化>
- ...
```

## style-rules.md 规范

详细的风格规则——每条规则配反例 / 正例对照。SKILL.md 主文件只写 5-15 条最关键的硬规则；其余下沉到此文件。

## world-bible.md 规范

```markdown
# <小说名> 世界观与设定

## 时空背景
（一段话）

## 关键设定
（一句话 + 链接到首次出现章节）

## 术语表
| 术语 | 类别 | 首现 | 定义 |
|--|--|--|--|

## 已建立的物理 / 社会规则
- <规则 1>：<陈述句>
- ...

## 不可违反清单（红线）
（这些规则违反 = 世界观崩坏，续写时绝不触碰）
```

## 自检清单（写产出 skill 的任何 Unit / 模块都要跑）

- [ ] 主 SKILL.md grep 强禁词无命中：`训练 / 轮 / D\d+ / 本轮 / 上一轮 / 第 \d+ 章 / 第[一二三四五六七八九十百千]+章 / attempt / 评分 / 相似度 / score / 差距报告`
- [ ] 主 SKILL.md 中"上一章 / 前一章 / 前文"若出现，上下文是**普通续写词汇**（指代输入），未与训练叙事词同句
- [ ] frontmatter 的 `name` / `description` 在 Init 之后**不再被改写**
- [ ] 主 SKILL.md ≤ 8000 字
- [ ] author-profile.json 通过 JSON 语法校验
- [ ] author-profile.json 的 `characters[]` 数组中**没有任何元素**包含 `tags / speech_sample / behavior / relations` 等详细字段（只允许 name / aliases / first_seen_chapter / last_seen_chapter / card_path）
- [ ] author-profile.json **不再包含** `rolling_synopsis` 字段（已迁出至 synopsis.md）
- [ ] `character-cards/*.md` 文件数 == `len(author-profile.characters[])`
- [ ] 每个 `characters[i].card_path` 指向的文件实际存在
- [ ] `references/synopsis.md` 存在且三段（主线骨架 / 近期细节 / 活跃伏笔）齐全，总字数 ≤ 3500
- [ ] world-bible 中所有"不可违反清单"规则在主 SKILL.md 中也以一句话提到
