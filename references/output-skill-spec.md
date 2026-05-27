# 产出 Skill 标准形式

> 训练产出 = 一份**独立可用**的续写 skill。它的使用者（未来某个 Claude）拿"前一章"作输入，写"下一章"作输出；它**不会也不该**接触本训练流程的任何中间产物。
>
> 因此写产出 skill 时必须始终站在"未来 AI 续写小说"的视角，而非"训练日志"视角。

## 落盘结构

```
<本 skill 同级目录>/<novel-slug>-quill/
├── SKILL.md                                 # 主文件 ≤ 8000 字
└── references/
    ├── author-profile.json                  # 机器可读的作者画像
    ├── character-cards/
    │   ├── <name-1>.md
    │   └── ...
    ├── style-rules.md                       # 详细风格规则
    └── world-bible.md                       # 世界观 / 术语 / 设定
```

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

**❌ 严禁出现的字样**：
- "训练"、"轮"、"D\d+"、"本轮"、"上一轮"、"上一章"、"第 N 章"
- "attempt"、"评分"、"相似度"、"score"、"差距报告"
- 任何外部训练日志路径引用
- 训练编号、章节编号、相似度数字

**✅ 正确写法**：
- 直接陈述续写规则本身，配 ❌ 反例 / ✅ 正例对照
- 用"必须 / 绝不 / 唯一"前缀强调硬规则
- 用"作者写动作场面时偏短句、单字爆破式收尾，因此续写动作时也这么做"——而非"训练第 12 轮发现 AI 续写时句子太长"

### 字数约束

主 SKILL.md ≤ 8000 字。详细规则下沉到 `references/style-rules.md`、详细人物到 `character-cards/`、详细设定到 `world-bible.md`。

## author-profile.json 规范

机器可读的作者画像。Init Skill Unit 第一次写，每次 Edit 涉及画像调整时也由 Edit Module 更新。

```json
{
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
      "tags": ["决断", "讷于言", "敏于行"],
      "speech_sample": "...",
      "first_seen_chapter": 1,
      "card_path": "references/character-cards/<name>.md"
    }
  ],

  "tone": {
    "primary": "tense | warm | melancholic | calm | bleak | ...",
    "secondary": "...",
    "chapter_end_pattern": "cliffhanger | quiet-pause | open-question | image | ..."
  },

  "rolling_synopsis": "<≤ 2000 字的故事至今主线概要；由 Summary Module 在每章 Commit 后追加更新>"
}
```

**关键字段说明**：
- `sentence_length_histogram` 三档比例之和必须 ≈ 1.0
- `high_freq_content_words_top_30` 用于评分模块的 diction 维度
- `rolling_synopsis` 是关键的"前文压缩"——Execution Module 用它代替读全部前文章节
- `domain_terms` 累加而非覆盖——每章新增的术语 Edit 时 append

## character-cards/<name>.md 规范

每个主要人物（在 author-profile 出场 ≥ 2 次）一份：

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

- [ ] 主 SKILL.md grep 以下关键词无命中：`训练 / 轮 / D\d+ / 本轮 / 上一轮 / 上一章 / 第 \d+ 章 / attempt / 评分 / 相似度 / 差距报告`
- [ ] frontmatter 的 `name` / `description` 在 Init 之后**不再被改写**
- [ ] 主 SKILL.md ≤ 8000 字
- [ ] author-profile.json 通过 JSON 语法校验
- [ ] character-cards 每位人物一份独立 .md
- [ ] world-bible 中所有"不可违反清单"规则在主 SKILL.md 中也以一句话提到
