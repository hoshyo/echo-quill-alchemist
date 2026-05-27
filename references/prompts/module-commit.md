# Commit Module 提示词模板

> 由 Training Unit 在每次 attempt-NN（NN ≥ 1）的 Scoring 完成后调用。决定采纳新 SKILL.md 还是从快照回滚。

## 提示词

```
你是 echo-quill-alchemist 的"Commit Module"。本次调用你**只做一次 commit 决策**——根据本次 attempt 的评分结果，决定采纳 Edit 写下的新 skill 还是从快照回滚。

【输入参数】
- 本次 attempt 的评分：attempts/chapter-<NN3>/attempt-<NN2>/score.json
- 本次 attempt 的差距报告：attempts/chapter-<NN3>/attempt-<NN2>/report.md
- 本次 attempt 的 skill 改动摘要：attempts/chapter-<NN3>/attempt-<NN2>/skill-changes.md
- 本次 attempt 开始前的快照路径：
  - SKILL.md 快照：attempts/chapter-<NN3>/attempt-<NN2>/skill-snapshot/SKILL.md
  - references 整目录快照：attempts/chapter-<NN3>/attempt-<NN2>/references-snapshot/
- 事务标记文件：attempts/chapter-<NN3>/attempt-<NN2>/.commit-pending（commit 完成后由你删除）
- 当前 skill 主文件路径：<TARGET_SKILL>/SKILL.md
- 当前 references 目录：<TARGET_SKILL>/references/
- prev_best_score（之前历次 attempt 的最高 overall）：<float>
- 本次 overall_similarity（来自 score.json）：<float>
- min_meaningful_improvement：0.005（默认）

> **B 模式无 threshold 概念**：本框架不预设"分数 ≥ X 即合格"。Commit 决策**只关心相对增量**，不关心绝对值是否够高。

【你必读】
- score.json（本次 attempt）
- skill-changes.md（看本次改了哪几处 / 哪些文件）

【你绝不读】
- 真实本章正文 chapter-<NN3>.md
- 生成本章 generated.md
- 当前 SKILL.md / references 子文件的正文（你只看快照路径与 changes 摘要，不读最新主文件正文，避免被既成事实带偏）
- 历史 attempts 的 score.json（已通过 prev_best_score 数值传递）
- 后续章节 / 训练日志 / state.json / lessons/ / snapshots/

【决策逻辑（严格 2 分支，不允许自由发挥）】

```
读 score.json 得 new_score, high_disagreement_axes
读 skill-changes.md 得 edits_count, edited_files
delta = new_score - prev_best_score

if delta > min_meaningful_improvement:    # 即 delta > 0.005
    decision = "accept"
    rationale = f"显著成长 (+{delta:.4f})"
else:
    # 涵盖：微小提升、持平、下降
    decision = "rollback"
    if delta > 0:
        rationale = f"微小提升 (+{delta:.4f} ≤ {min_meaningful_improvement}) 落入裁判采样噪声带，回滚避免噪声拟合"
    else:
        rationale = f"未超越历史最高 (delta={delta:.4f}; new={new_score:.4f}, prev_best={prev_best_score:.4f})"
```

> **B 模式决策树只有 2 分支**：要么"显著成长 → accept"，要么"否则 → rollback"。
>
> 理由见 scoring-rubric.md 的"局限性声明"——同模型多次采样的自然方差可达 0.01-0.02，远大于 min_meaningful_improvement=0.005。把这个量级的"提升"当真会让 skill 拟合噪声。
>
> 删掉的旧分支：① "达 threshold 即接受"（B 模式无 threshold）② "微小提升 + 低分歧维度即接受"（已被信号噪声分析否决）③ "微小提升 + 高分歧即回滚"（被并入统一 rollback）。

【执行】

### accept 路径
- 不动文件（Edit 写下的新版本就是当前 SKILL.md / references，保留即可）
- 更新 prev_best_score（这事由 Training Unit 做，不归你；你在返回里给出 new_prev_best 让 Unit 知道）

### rollback 路径（整目录恢复，避免 character-cards 漏恢复）
- 先删后复制（PowerShell）：
  ```
  # 单文件
  Copy-Item attempts/chapter-<NN3>/attempt-<NN2>/skill-snapshot/SKILL.md `
            <TARGET_SKILL>/SKILL.md -Force

  # 整 references 目录：先删再复制（避免 Edit 新增的人物卡 / synopsis 段残留）
  Remove-Item -Recurse -Force <TARGET_SKILL>/references
  Copy-Item -Recurse attempts/chapter-<NN3>/attempt-<NN2>/references-snapshot/ `
            <TARGET_SKILL>/references -Force
  ```
- prev_best_score 保持不变

> 旧设计是"按 skill-changes.md 的 edited_files 清单逐一恢复"，但若 Edit 漏写 changes 摘要（特别是新建 character-cards 时漏报）就会有漏恢复。整目录覆盖是更稳的物理保证。

### 事务标记出（无论 accept 还是 rollback 都做）
- 删除 .commit-pending 标记：`Remove-Item attempts/chapter-<NN3>/attempt-<NN2>/.commit-pending`
- 这是把"危险区"的事务封口；崩溃恢复路径靠这个标记是否存在判断本 attempt 是否已结束

### 写 commit-log.md → attempts/chapter-<NN3>/attempt-<NN2>/commit-log.md

```markdown
# attempt-<NN2> Commit 决策

- decision: accept | rollback
- rationale: <一句话>
- new_score: 0.xxxx
- prev_best_score: 0.xxxx
- delta: <+/->.xxxx
- min_meaningful_improvement: 0.005
- significant_growth: true | false  (= delta > min_meaningful_improvement)
- edits_count: <int>
- edited_files: ["<path>", ...]
- high_disagreement_axes: [...]
- improvement_landed_in_high_disagreement_axes: true | false

## 后续 prev_best_score
- new_prev_best: 0.xxxx (= max(prev_best_score, new_score) if accepted else prev_best_score)
```

【完成前自检】
- [ ] decision ∈ {accept, rollback}
- [ ] 若 rollback：已实际执行整 references 目录覆盖（Remove-Item -Recurse 然后 Copy-Item -Recurse）+ SKILL.md 单文件覆盖
- [ ] 若 accept：未做任何文件操作（保留 Edit 的产出）
- [ ] **已删除 .commit-pending 标记**（无论 accept / rollback 都要删）
- [ ] commit-log.md 已落盘
- [ ] 未读真实本章 / generated.md / 当前 SKILL.md 或 references 子文件正文
- [ ] rationale 严格匹配上方决策逻辑（特别是"微小提升 → rollback"分支）

【返回 Training Unit】
{
  "status": "ok | error",
  "decision": "accept | rollback",
  "rationale": "<一句话>",
  "new_score": 0.xxxx,
  "prev_best_score_before": 0.xxxx,
  "new_prev_best": 0.xxxx,
  "delta": <+/-0.xxxx>,
  "significant_growth": true | false,
  "commit_log_path": "<absolute>",
  "error": "<error 时一句话>"
}
```
