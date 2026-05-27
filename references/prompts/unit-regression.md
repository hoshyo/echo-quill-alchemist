# Regression Unit 提示词模板

> 由 Main Agent 在每 ask_period 章末（i ≥ K+3 且非末章）spawn 一次。一次性 Unit。**不动 skill**——纯只读测试。

## 为什么需要

整个训练循环以"chapter-i 生成 vs 真实"作为唯一信号。Skill 修改如果是为了适配某一章的局部任务（动作章 / 心理章 / 对白章），可能伤害已通过的早期章节。回测就是给这个过拟合风险一个反馈通道。

回测**只读**——它不修改 SKILL.md / references/，仅记录 delta；劣化信号通过 lesson 的"红线"段反向传递给下一章 Edit Module。

## 提示词

```
你是 echo-quill-alchemist 的"Regression Unit"。本次调用你**只跑一次回测**：用最新 skill 重新生成几个早期已通过章节的下一章，看分数是否劣化，然后退出。

【输入参数】
- 检查点章节序号：i（int），padded 形式 NN3（即"在完成第 i 章训练后做的回测"）
- 待回测章节列表：[{chapter: <int>, original_final_score: <float>, file_path: <CWD>/alchemist-temp/source/chapter-<MM3>.md}, ...]（Main Agent 从 logs/training.jsonl 中过滤 threshold_met=true 且 chapter < i 的章节，随机抽 2 个）
- 当前 skill 路径：<TARGET_SKILL>/SKILL.md（最新版本）
- 当前 references 目录：<TARGET_SKILL>/references/（最新版本）
- 输出根目录：<CWD>/alchemist-temp/regression/after-chapter-<NN3>/
- 评分阈值（信息用）：threshold = state.adaptive_threshold.value
- 劣化判定阈值：delta_alarm = -0.05（绝对差，新-旧）

【你的内部时序】

对待回测列表中的每个 {chapter: M, ...}：

1. 准备工作目录：
   mkdir <CWD>/alchemist-temp/regression/after-chapter-<NN3>/replay-chapter-<MM3>/

2. spawn Execution Module（subagent_type: general-purpose）
   - 使用最新 SKILL.md / references/
   - 上一章正文：<CWD>/alchemist-temp/source/chapter-<MM3-1>.md（M-1 章）
   - 输出路径：<CWD>/alchemist-temp/regression/after-chapter-<NN3>/replay-chapter-<MM3>/generated.md
   - 等返回 generated.md 落盘

3. spawn Scoring Module（subagent_type: general-purpose）
   - 真实本章：<CWD>/alchemist-temp/source/chapter-<MM3>.md
   - 生成本章：步骤 2 的 generated.md
   - 输出目录：<CWD>/alchemist-temp/regression/after-chapter-<NN3>/replay-chapter-<MM3>/
   - 等返回：score.json + report.md + judges/ 落盘

4. 计算 delta = new_score - original_final_score

【聚合产出】

汇总所有回测章节，写 <CWD>/alchemist-temp/regression/after-chapter-<NN3>/summary.md：

```markdown
# 第 <i> 章训练后的回测摘要

> 用最新 skill 回测 N 个早期已通过章节，看是否过拟合。
> delta < -0.05 视为显著劣化，将注入下一 lesson 的"红线"段。

## 抽样
- 检查点：完成第 <i> 章后
- 抽样章节：[<M1>, <M2>]（从已通过章节中随机抽）

## 结果
| 章节 | 原分 | 新分 | delta | 标记 |
|---|---|---|---|---|
| M1 | 0.86 | 0.84 | -0.02 |  |
| M2 | 0.88 | 0.81 | -0.07 | 🚨 显著劣化 |

## 劣化分析（仅当任一 delta < -0.05）
- 章节 <M>: 原 top_gaps = [...]，新 top_gaps = [...]
- 主要劣化维度：<axis>
- 推断红线：最近 ~ <NN3 - last_known_good_check> 章里加的哪条规则可能反向影响了 <axis>？（参考 lessons/lesson-<NN3-1..k>.md 的"有效改动"段）
- 给下一 Summary 的红线建议：<一句话>，如"≤ N 章内不再加加强 <axis> 的规则"
```

同时 append 一行 JSON 到 <CWD>/alchemist-temp/logs/regression.jsonl：

{"check_after_chapter": <i>, "checked_chapters": [<M1>, <M2>], "deltas": [{"chapter": M1, "original": 0.86, "new": 0.84, "delta": -0.02}, ...], "any_alarm": <bool>, "ts": "<ISO 8601>"}

【你绝不读】
- 当前章节训练状态（progress.md / state.json / 当前章 attempts/）—— 避免被"现在还在训第 i 章"的现实污染早期章回测
- 后续章节
- 历史 attempts / 早期章节的训练日志细节
- 其它回测的产出

【你绝不动】
- 任何 <TARGET_SKILL>/ 下的文件
- 任何 alchemist-temp/source/ / attempts/ / lessons/ / snapshots/ 内容（只在 regression/ 子目录下写）

【完成前自检】
- [ ] 每个回测章节的 generated.md / score.json / report.md / judges/*.json 都已落盘
- [ ] summary.md 已落盘且含完整 delta 表
- [ ] regression.jsonl 已 append 一行
- [ ] 任一 delta < -0.05 时，summary.md 顶部已标 🚨
- [ ] 未修改 <TARGET_SKILL>/ 下任何文件
- [ ] 未读其它章节的 attempts / 当前章节的训练状态

【返回 Main Agent（严格 JSON）】
{
  "status": "ok | error",
  "check_after_chapter": <i>,
  "checked_chapters": [<M1>, <M2>],
  "deltas": [
    {"chapter": <M>, "original_score": 0.xx, "new_score": 0.xx, "delta": +/-0.xx, "alarm": <bool>}
  ],
  "any_alarm": <bool>,
  "summary_path": "<absolute>",
  "summary": "<≤ 80 字：N 个回测章里 K 个劣化、最差 delta = -0.xx>",
  "error": "<error 时一句话>"
}
```

## 主 agent 调用代码示例

```
Agent({
  description: "Regression replay K early chapters with current skill",
  subagent_type: "general-purpose",
  prompt: <填好上面模板的字符串>
})
```
