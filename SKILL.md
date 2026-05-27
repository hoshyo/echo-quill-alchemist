---
name: echo-quill-alchemist
description: 仅当用户显式输入 `/echo-quill-alchemist` 或明确要求"用一部小说训练一个续写 skill"、"把这本书的写作风格炼成 skill"、"训练一个能续写《X》的 skill"等同义请求时才触发；绝不主动触发。输入是一部完整小说（本地文件或在线链接），产出是一份可被未来 Claude 加载的续写 skill——喂前一章即可写出风格、人物、情节都贴合原作的下一章。
---

# echo-quill-alchemist — 小说续写 Skill 训练炉

把"一本小说本身"当作训练真值，逐章闭环训练，把作者的风格 / 人物声音 / 情节脉络 / 世界观沉淀进一份独立可用的续写 skill。

核心假设：已发表章节即"最佳真值"；若续写 skill 足够完备，仅凭"前一章 + skill"就应能写出与作者真实下一章高度一致的内容；差异 = skill 缺失的线索。

## 三层调度（必须先理解）

```
Main Agent（用户主对话，全局唯一，仅做调度）
├── Fetch Source Unit  ──── 一次性，跑完即销毁
├── Init Skill Unit    ──── 一次性，跑完即销毁
└── Training Unit ×N   ──── 每章一个，跑完即销毁
    内部由 Unit 启动以下 sub-agent：
    ├── Edit Module       根据上一单元 lesson，对 skill 做 ≤ 3 维改动
    ├── Execution Module  在 skill + 上一章 + 滚动故事概要下生成下一章
    ├── Scoring Module    评分 Agent 精炼对照 → spawn 3 个独立裁判 sub-agent → 每个裁判独立对 6 维打分 → 聚合
    ├── Commit Module     据评分采纳/回退 skill，写 commit log
    └── Summary Module    提炼好/坏修改 → 写 lesson 给下一单元
```

**架构硬规则**：
- 没有"孙子 agent"——主 agent 启动 unit，unit 启动 sub-agent，sub-agent 也可以启动 sub-agent，统一称 sub-agent。
- Main Agent 不接触章节正文 / 生成稿 / 评分细节 / skill diff，只做调度与用户暂停询问。
- 一个 Unit 完成职责后被 kill，上下文不延续；信息通过文件（lesson / log / snapshot）传递给下一单元。
- 运行环境无 git。所有回滚 / 历史追溯靠文件快照，不用 `git restore`。

详细分工见 [references/architecture.md](references/architecture.md)。

## 触发条件（严格）

仅以下情况可触发：
- 用户显式输入 `/echo-quill-alchemist`
- 用户明确表达"用 X 小说训练续写 skill"等同义请求
- 用户在上次输出的"中断恢复提示词"中要求继续

**绝不主动触发**。"我想写小说"、"帮我续写一段"是直接续写需求，不需要训练，不要启动本 skill。

## 启动参数

| 参数 | 必需？ | 默认 | 说明 |
|---|---|---|---|
| 小说来源 | ✅ | — | 二选一：(A) 整本文件路径（.txt/.md，UTF-8）；(B) 按章节顺序排列的 URL 列表 |
| 目标 skill 名 | 可选 | `<novel-slug>-quill` | 从小说标题或文件名 slug 化 |
| 种子章节数 K | 可选 | 自适应 | 总章数 N≥5→K=3；N=4→K=2；N=3→K=1；N<3 拒绝执行 |
| 单章最大尝试数 | 可选 | 5 | 某章尝试到此仍未达阈值则带 warning 推进 |
| 通过阈值 | 可选 | 0.85 | overall 达此值即通过 |
| 暂停询问周期 | 可选 | 5 | 每完成 N 章问一次"继续 / 暂停 / 看 progress" |

任一必需项缺失：停下问用户，不得猜测。

## 工作目录

`<用户启动 Claude 的当前目录>/alchemist-temp/`。布局详见 [references/directory-layout.md](references/directory-layout.md)。

## 入口流程

1. 收集启动参数 → 前置环境校验（Python 可用、来源可达、目标 skill 路径可写）
2. spawn **Fetch Source Unit** → 切片到 `alchemist-temp/source/`
3. 检查总章数：N<3 → 停下；N≥3 → 按公式定 K
4. spawn **Init Skill Unit** → 读前 K 章，产 skill 初版 + author-profile.json
5. 章训练循环（i = K+1 ... 末章）：每章 spawn 一个新 **Training Unit**，等其返回一句话摘要
6. 每 5 章询问用户是否暂停；末章后写 `final-summary.md` 并输出落盘路径

详见 [references/workflow.md](references/workflow.md)。

## 文档索引

- [references/architecture.md](references/architecture.md) — 三层 agent 边界与职责
- [references/workflow.md](references/workflow.md) — 端到端流程
- [references/directory-layout.md](references/directory-layout.md) — 目录与文件约定
- [references/output-skill-spec.md](references/output-skill-spec.md) — 产出 skill 的标准形式
- [references/scoring-rubric.md](references/scoring-rubric.md) — 6 维评分细则
- [references/prompts/](references/prompts/) — 各 unit / 模块的提示词模板（8 份）
