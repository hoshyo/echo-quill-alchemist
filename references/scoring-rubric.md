# 续写相似度评分细则

> 本文件由 Scoring Module 内部 spawn 的 3 个独立裁判 sub-agent 共同遵守。
>
> 评分模式：**裁判团 / Ensemble**——每个裁判**独立**对全部 6 维各打 0-1 分；3 份分数聚合后加权得 overall。

## 局限性声明（裁判与 Edit Module 必读，影响信号解释）

3 个裁判都是 general-purpose sub-agent 调用，底层是同一个 LLM 多次采样。这是**成本受限下的近似 ensemble，不是真正独立的多评判模型**：
- 三裁判的 score 之间 Pearson 相关大概率 > 0.7
- "中位数抗极端"假设当 1 个裁判极端打分异常时成立，但若**3 个裁判共享同一系统性偏差**（如对短句倾向、对成语偏好），中位数也会系统性错
- 因此：`disagreement` 反映的是同模型采样自然方差 + 提示词敏感度，**不能**等同于"客观真实信号稳定度"
- 工程取舍：把"分歧度阈值"定得偏严（≤ 0.2 才算稳定），减少把噪声当信号的概率

## 评分模式

```
Scoring Agent（Training Unit 启动）
1. 读 真实本章 + 生成本章 + 本文档
2. 提炼对照摘要（含情节 / 人物 / 环境 / 措辞 / 节奏 / 基调 6 个关键点）
   保存到 attempt-<NN>/scoring-context.md
3. spawn 3 个独立裁判 sub-agent（互相不可见）：
   每个裁判读：scoring-context.md + 本文档 + （如需）真实本章 + 生成本章
   每个裁判输出：6 维各打 0-1 分 + 每维一句扣分原因 → judges/judge-{A,B,C}.json
4. 聚合：每维取 3 份分数的中位数 → 加权得 overall
5. top_gaps：按 (1 - dim_median) * weight 降序取前 2 维
6. 汇总写 score.json + report.md
```

## 6 维及权重

| 维度 | 权重 | 评估对象 |
|--|--|--|
| style     | 0.25 | 句长分布、修辞密度、画面感、书面/口语比 |
| plot      | 0.20 | 是否承接前章悬念、是否走在合理情节方向 |
| character | 0.20 | 角色行为、对白、心理是否符合人设 |
| tone      | 0.15 | 紧张/松弛、悲喜、冷暖、章末情绪 |
| world     | 0.10 | 设定、术语、规则的前后一致性 |
| diction   | 0.10 | 高频词、忌讳词、专属词使用 |

```
overall_similarity = sum(dim_median * weight)，结果保留 4 位小数
```

## 字数比例检查（informational，不进评分）

`字数比 = N2 / N1`（生成 / 真实）。仅写入 report.md 顶部信息块：
- `0.7 ≤ ratio ≤ 1.3` → 正常
- `ratio < 0.7` 或 `ratio > 1.3` → 标 ⚠️：Execution 字数偏离设定，plot.2.2 命中率天然受限。Edit Module 解读 plot 维度差距时**应优先认定为 Execution 失误而非 skill 缺陷**

字数差异**不**直接扣 plot 分（避免双重扣分），但作为归因的旁证。

## 各维度打分细则（裁判遵循）

### 1. style（语言风格）— 权重 0.25

**子项**（每子项各占本维 1/4，先各自打 0-1，再平均得本维分）：

- **1.1 句长分布**：把生成稿与真实稿各拆 200 句样本，比较句长直方图（短 < 12 字 / 中 12-25 / 长 > 25）。三档比例差 ≤ 5pp 给 1.0；每超 5pp 扣 0.2
- **1.2 修辞密度**：明喻/暗喻/拟人/排比每千字出现次数差异。差 ≤ 1 次/千字 给 1.0；每超 1 次扣 0.2
- **1.3 画面感**：感官描写（视/听/嗅/味/触）密度。生成稿与真实稿比例差 ≤ 10% 给 1.0；每超 10% 扣 0.2
- **1.4 书面/口语比**：叙述与对白的语体差异（如使用"何/此/乃"等文言虚词的频率）。差 ≤ 10% 给 1.0；每超 10% 扣 0.2

### 2. plot（情节连贯）— 权重 0.20

- **2.1 开场承接**：生成稿首段是否接续前章末段的场景 / 情绪 / 时间线。完美承接 1.0；只承接其中两项 0.7；只承接一项 0.4；完全脱节 0
- **2.2 中段推进**：中段事件是否落在前章伏笔指向的方向。
  - 真实稿写了 N 个关键情节点，生成稿命中 M 个 → score = M / N
  - 方向相同即可，不要求字面相同（"主角去找 A 谈判" vs "主角去找 A 寻求结盟"算命中）
- **2.3 章末钩子**：章末是否抛出新悬念 / 未尽情绪。三档：抛出且与真实稿同方向 1.0；抛出但方向不同 0.5；没抛出 0

### 3. character（人物刻画）— 权重 0.20

- **3.1 行为一致**：本章主要角色（出场 ≥ 2 次）的行动决策是否符合人设。每角色单独评 0-1 取均值
- **3.2 对白一致**：核心角色对白的句式 / 用词 / 语气。同上每角色评 0-1 取均值
- **3.3 心理刻画**：心理描写的视角和深度（POV 主角内心戏密度、配角是否始终外视角等）

### 4. tone（节奏与基调）— 权重 0.15

- **4.1 整章基调**：本章主导情绪（悲/喜/紧张/松弛/温暖/冷峻）。完全一致 1.0；色调相似但强度不同 0.6；完全相反 0
- **4.2 节奏曲线**：本章前/中/后三段的节奏（动作密度、对白密度、内心戏密度）。三段都对 1.0；两段对 0.6；一段对 0.3

### 5. world（世界观一致）— 权重 0.10

- **5.1 设定无错**：是否引入违反前章设定的元素。出现违反扣 0.3 / 处，最低 0
- **5.2 术语正确**：专有名词拼写与用法。每错一处扣 0.2，最低 0
- **5.3 时空连贯**：场景的时间地点切换是否合理

### 6. diction（用词遣句）— 权重 0.10

- **6.1 高频词覆盖**：从前章及种子章节统计的"作者偏好高频实词 Top 30"在生成稿中的命中率。命中率 ≥ 70% 给 1.0；每低 10pp 扣 0.2
- **6.2 忌讳词规避**：作者明显避免的词（"总而言之 / 不可否认 / 值得注意的是" 等 AI 套话）是否被误用。每出现一处扣 0.3
- **6.3 专属词风**：作者特色搭配是否被复现。出现 1+ 处 1.0；0 处 0.5

## 裁判 sub-agent 必读硬规则

```
你是 Scoring Module 的独立裁判 <A | B | C>。三位裁判互相不可见，独立打分。

【你必读】
- scoring-context.md（评分 Agent 提炼好的对照摘要）
- 真实本章 chapter-<i>.md
- 生成本章 generated.md
- 本评分细则

【你绝不读】
- 当前 SKILL.md（你不评 skill 质量，只评两段文本）
- 历史 attempts 的 score.json / report.md / judges/*
- 后续章节
- 训练日志 / progress.md / lessons/

【你的输出】judges/judge-<X>.json：
{
  "judge": "A | B | C",
  "axes": {
    "style":     { "score": 0.xx, "reason": "<一句扣分原因或满分说明>" },
    "plot":      { "score": 0.xx, "reason": "..." },
    "character": { "score": 0.xx, "reason": "..." },
    "tone":      { "score": 0.xx, "reason": "..." },
    "world":     { "score": 0.xx, "reason": "..." },
    "diction":   { "score": 0.xx, "reason": "..." }
  },
  "overall_self_calc": 0.xxxx,
  "notes": "<可选：整体观感一两句>"
}

【自检】
- [ ] 6 维分数都在 [0, 1]
- [ ] 每维有一句话扣分原因或满分说明
- [ ] overall_self_calc = sum(score * weight) 浮点误差 ≤ 1e-4
- [ ] 未读 SKILL.md / 历史 score.json / 后续章节
```

## 聚合规则（评分 Agent 执行）

每维聚合公式：

```
dim_median = median([judge_A.score, judge_B.score, judge_C.score])
dim_weighted = dim_median * weight
overall_similarity = sum(dim_weighted)
disagreement = max(scores) - min(scores)
high_disagreement_axes = [dim for dim where disagreement > 0.2]
top_gaps = 按 (1 - dim_median) * weight 降序，**排除** high_disagreement_axes，取前 2
```

**为什么用中位数而非平均**：抗单个裁判的极端打分（一个裁判给 0 不会拉死整个维度）。

**为什么 top_gaps 排除高分歧维度**：top_gaps 是给 Edit Module 的修改优先级——基于不稳定信号修改 = 噪声拟合。

## 三裁判分歧处理

聚合时计算每维的"分歧度"：

```
dim_disagreement = max(judges) - min(judges)
```

- 任一维 `disagreement > 0.2` → report.md 标 ⚠️ "高分歧维度"，**Edit Module 本轮不动该维度**（信号不稳，避免误改）
- 任一维 `disagreement > 0.4` → report.md 标 🚨 "严重分歧"，建议人工 review

> **为什么 0.2 而不是历史的 0.3**：见局限性声明——同模型多次采样的自然方差通常 ≥ 0.1，把"稳定阈值"卡在 0.2 才能滤掉一半噪声。要打动 Edit 必须 disagreement ≤ 0.2 + delta ≥ min_meaningful_improvement 双闸口同时通过。

分歧不影响 overall 计算（仍用中位数），但影响 Commit Module 的决策（高分歧维度的微小提升不算"显著改进"）。

### 高分歧逃生通道（避免某维永远不收敛）

如果同一维度在连续 3 章里都 disagreement > 0.2 → Summary Module 在 lesson 中标"该维度长期高分歧"，下一章 Edit Module 允许在该维度做**单处小幅试探**（仅 1 条规则、措辞中性），观察 delta 走向。试探仍属于"≤ 3 处"配额内。

## 噪声忽略清单（不计入差异）

下列差异**不**扣任何维度：

- 数字 / 日期格式细节（"二〇二三年" vs "2023 年"）
- 引号样式（"" vs 「」）
- 段落数量差（在总字数差 ≤ 30% 前提下）
- 同义词替换（"望" vs "看"，密度匹配前提下）

## 归因要求（写到 report.md）

每维扣分必须写明**至少一条归因**，四选一：

1. **skill 缺陷**：当前 SKILL.md 没说 / 说得太软 / 规则模糊
2. **skill 误导**：现有条款把 Execution 带偏了
3. **生成失误**：skill 已说清楚但 Execution 没跟上（罕见，反复出现需加例子）
4. **不可避免**：作者真实下一章里有前章无线索的转折——不算 skill 缺陷，写在 report 末尾的 informational 列表

归因只用于 Edit Module 的下一步修补；不影响打分本身。

## report.md 模板

```markdown
# 第 <i> 章 attempt-<NN> 评分报告

## 客观指标（informational）
- 真实字数：N1
- 生成字数：N2
- 字数比：N2/N1 = X.XX
- 字数比是否超 ±30%：是 / 否（超 → ⚠️ Edit Module 解读 plot 时优先归因 Execution 失误）

## 总分
- overall_similarity: 0.xxxx
- top_gaps: [<axis-1>, <axis-2>]

> **B 模式无"通过阈值"概念**：本文件不再判定"达标 / 未达标"；overall_similarity 是给 Commit Module 与 Training Unit 计算 delta 用的纯数字。

## 三裁判一致性
| 维度 | judge-A | judge-B | judge-C | 中位数 | 分歧度 | 标记 |
|--|--|--|--|--|--|--|
| style     | 0.85 | 0.80 | 0.82 | 0.82 | 0.05 |   |
| plot      | 0.70 | 0.65 | 0.75 | 0.70 | 0.10 |   |
| character | 0.40 | 0.85 | 0.80 | 0.80 | 0.45 | 🚨 |
| ...

## 逐维归因
### style: 0.82
- 主要差异：<一句话>
- 归因：skill 缺陷 / skill 误导 / 生成失误 / 不可避免
- 建议改 skill 方向（仅当归因为 skill 问题）：<一句话>

### plot: 0.70
（同上）

...

## informational（不影响打分）
- <真实稿中的"不可避免"转折>

## 给 Edit Module 的指引
- 优先修补 top_gaps 中第 1 维：<axis>，建议加 <一句话规则草案>
- 次优先：<axis>
- 高分歧维度（disagreement > 0.2）本轮**不动**——避免基于不稳定信号改写
- 长期高分歧维度（连续 3 章命中）：lesson 已批准小幅试探（≤ 1 条中性规则）
```

## score.json 字段约束

```json
{
  "chapter": <int>,
  "attempt": <int>,
  "axes": {
    "style":     { "median": 0.xx, "weight": 0.25, "weighted": 0.xxxx, "judges": [0.x, 0.x, 0.x], "disagreement": 0.xx },
    "plot":      { ... },
    "character": { ... },
    "tone":      { ... },
    "world":     { ... },
    "diction":   { ... }
  },
  "overall_similarity": 0.xxxx,
  "top_gaps": ["<axis>", "<axis>"],
  "high_disagreement_axes": ["<axis>", "..."],
  "judges_used": ["A", "B", "C"],
  "notes": "<一句话总评>"
}
```

字段校验：
- 每维 median ∈ [0, 1]
- weighted = median * weight，浮点误差 ≤ 1e-4
- overall_similarity = sum(weighted)，误差 ≤ 1e-4
- high_disagreement_axes = [dim where disagreement > 0.2]（注意：阈值 0.2，不是历史的 0.3）
- top_gaps 排除 high_disagreement_axes（高分歧维度不进 top_gaps，因为信号不稳定）
