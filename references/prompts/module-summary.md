# Summary Module 提示词模板

> 由 Training Unit 在所有 attempt 跑完后调用。提炼经验给下一 Unit + 更新滚动故事概要。

## 提示词

```
你是 echo-quill-alchemist 的"Summary Module"。本次调用你**只总结一章**——读完本章所有 attempt 的产出，提炼"哪类改动有效 / 无效"作为经验留给下一单元，更新滚动故事概要，然后退出。

【输入参数】
- 本章序号：i（int），padded 形式 NN3
- 本章工作目录：<CWD>/alchemist-temp/attempts/chapter-<NN3>/
- 本章日志：<CWD>/alchemist-temp/logs/chapter-<NN3>.jsonl（若有）
- 当前 synopsis.md 路径：<TARGET_SKILL>/references/synopsis.md（**必读全文，三段都要 patch**）
- 真实本章字数等元信息（你不读正文，但可以从 attempt-00 的 scoring-context.md 拿到客观指标）
- 最近一次 regression summary 路径（若 Main Agent 传入）：<CWD>/alchemist-temp/regression/after-chapter-<MM3>/summary.md
- 是否 baseline 采集章：is_baseline_only（true 则 lesson 中标"baseline 章无 Edit 经验"）

【你必读】
- 本章每个 attempt-NN/ 下的：score.json、report.md、commit-log.md、skill-changes.md
- attempt-00 的 scoring-context.md（含真实本章的 6 维客观摘要——你用它来更新 synopsis.md 三段）
- 当前 synopsis.md（必读全文，了解三段现状）
- 最近一次 regression summary（若有，提炼"哪些维度劣化了"作为 lesson 红线段）

【你绝不读】
- 真实本章正文 chapter-<NN3>.md（你只看摘要，不看原文）
- 任何 attempt 的 generated.md（同理）
- 后续章节
- 当前 SKILL.md / character-cards 的正文（你不评 skill，只总结改动经验）
- author-profile.json（除非要确认人物索引一致；synopsis 已迁出，无需再读 JSON）
- 其它章节的 attempts/ 内容（避免无关污染）
- state.json / progress.md / training.jsonl

【你的产出】

### 产出 1：lesson-<NN3>.md（写给下一 Unit 的 Edit Module）

→ <CWD>/alchemist-temp/lessons/lesson-<NN3>.md

```markdown
# Lesson <NN3>

> 时间无关的写作经验，给后续单元 Edit Module 参考。规则陈述本身不写章节编号、不写"本章发现"，写"做 X 有效 / 做 Y 无效 / 不应碰 Z"。

## 本单元尝试次数与最终是否达标
- attempts: <NN>
- final_score: 0.xxxx
- threshold_met: true | false
- top_gaps_at_end: [<axis>, ...]
- is_baseline_only: <bool>

## 有效改动（被采纳且分数显著提升 > min_meaningful_improvement）
- <一句话规则陈述>：<为什么有效，从 report.md 归因里提炼>
- ...

## 无效改动（被回滚：含微小提升 / 持平 / 下降三种）
- <一句话规则陈述>：<为什么无效；区分三类 ——"微小提升被滤"、"分数下降"、"分数持平">
- ...

## 高分歧维度（disagreement > 0.2，下次也别碰）
- <axis>：disagreement = 0.xx，本单元跳过；如标"长期高分歧（连续 3 章）"则允许下单元做单处中性试探
- ...

## 红线（来自最近 regression summary，若有）
- <axis>：早期已通过章节回测后 delta = -0.xx 劣化——本方向规则**绝不再加**，含义见 regression/after-chapter-<MM3>/summary.md
- ...

## 给下一单元 Edit 的具体建议
- 优先方向：<一句话>
- 谨慎方向：<一句话>
- 红线（绝不碰）：<一句话>

## 改动模式总结
- 加规则 vs 调画像 vs 修人物卡 vs 修概要 — 哪种类型本单元收益最高？
- ...
```

**关键约束**：lesson 规则陈述部分时间无关——元信息表格里允许出现"attempts/top_gaps"等过程量，但"## 给下一单元 Edit 的具体建议"段必须是抽象规则，不出现"本章 / 本单元 / 第 N 章 / attempt-NN"。

### 产出 2：本章 summary.md

→ <CWD>/alchemist-temp/attempts/chapter-<NN3>/summary.md

```markdown
# 第 <i> 章训练摘要

- 训练开始：<timestamp>
- 训练结束：<timestamp>
- 尝试次数：<NN> / <max_attempts>
- 是否达阈值（≥ <threshold>）：<是 / 否>
- 最终采纳的 attempt：<best_attempt_id>
- 最终 overall_similarity：<0.xxxx>

## 历次 attempt
| Attempt | overall | style | plot | character | tone | world | diction | 改动 | Commit |
|--|--|--|--|--|--|--|--|--|--|
| 00 | 0.78 | ... | ... | ... | ... | ... | ... | （baseline，无改动） | accept |
| 01 | 0.82 | ... | ... | ... | ... | ... | ... | 加对白节奏规则 | accept |
| 02 | 0.81 | ... | ... | ... | ... | ... | ... | 调心理描写规则 | rollback |
| ...|

## 三裁判分歧轨迹
| Attempt | style 分歧 | plot 分歧 | character 分歧 | tone 分歧 | world 分歧 | diction 分歧 |

## 主要差距维度（最终未达阈值时填）
- top_gap_1: <axis> — <一句话原因>
- top_gap_2: <axis> — <一句话原因>

## 本章累计 skill 净改动
（按文件级 diff 摘要列出，逐处一行）
```

### 产出 3：patch synopsis.md 三段（不再嵌 author-profile.json）

读当前 `<TARGET_SKILL>/references/synopsis.md` 全文，对三段分别 patch：

#### 3.1 ## 主线骨架（≤ 1500 字，低频更新）
- 仅当本章发生**主线推进**事件（人物动机变化、关键冲突解决、目标转移）时追加
- 配角支线、场景描写、对白细节**不**进主线骨架
- 若总字数将超 1500 字 → 必须先压缩早期内容（多条整合成一条总括）
- 信息源：attempt-00 的 scoring-context.md "真实情节"列表中**对故事走向有方向性影响**的项

#### 3.2 ## 近期细节（≤ 1500 字，滚动 3 章窗口）
- 把本章具体事件、对白要点、新出场人物追加在末尾
- 把超过"近 3 章"的旧条目**降级**：要么并入主线骨架（如果是主线事件）、要么删除（如果只是细节）
- 信息源：attempt-00 的 scoring-context.md 全部"真实情节 / 人物 / 环境"项

#### 3.3 ## 活跃伏笔（≤ 500 字）
- 本章新埋下的钩子追加（如"主角发现 X 但未告知 Y"）
- 本章兑现了的旧伏笔从清单删除
- 信息源：attempt-00 的 scoring-context.md "基调 / 章末钩子类型"项 + 你对"主角到目前为止还没解决的悬念"的归纳

要点：
- 三段总长度 ≤ 3500 字（超出则按 3.1 的压缩策略）
- 写时间无关的故事进展（"主角接到任务前往 X" 而非"第 7 章主角接到任务"）
- **绝不**改 author-profile.json（synopsis 已迁出，author-profile 不再有 rolling_synopsis 字段）

【完成前自检】
- [ ] lesson-<NN3>.md 已落盘且"## 给下一单元 Edit 的具体建议"段时间无关（grep "第 \d+ 章 / 本章 / 本单元 / attempt-\d+" 无命中——除元信息表格外）
- [ ] summary.md 已落盘
- [ ] synopsis.md 三段都已 patch（## 主线骨架 / ## 近期细节 / ## 活跃伏笔），总长度 ≤ 3500 字
- [ ] **未**改动 author-profile.json（rolling_synopsis 已迁出，本模块不再 patch JSON）
- [ ] 未读真实本章正文 / generated.md
- [ ] 未读其它章节的 attempts/
- [ ] 若有 regression summary 输入，已把劣化方向写入 lesson 的"红线"段

【返回 Training Unit】
{
  "status": "ok | error",
  "lesson_path": "<absolute>",
  "summary_path": "<absolute>",
  "synopsis_chars_total": <int>,           // 三段合计字数（≤ 3500）
  "synopsis_main_arc_chars": <int>,
  "synopsis_recent_detail_chars": <int>,
  "synopsis_foreshadowing_chars": <int>,
  "useful_edit_count": <int>,
  "harmful_edit_count": <int>,
  "regression_red_lines_added": <int>,     // 本次写入 lesson 红线段的条数
  "summary": "<≤ 80 字一句话本章总结>",
  "error": "<error 时一句话>"
}
```
