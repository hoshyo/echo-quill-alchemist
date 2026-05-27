# EchoQuill-Alchemist.skill

把"一本小说本身"当作训练真值，逐章闭环训练，把作者的风格 / 人物声音 / 情节脉络 / 世界观沉淀成一份**独立可用**的续写 skill——喂前一章即可写出风格、人物、情节都贴合原作的下一章。

## 安装

```bash
npx skills add hoshyo/echo-quill-alchemist
```

## 触发

```
/echo-quill-alchemist
```

或同义请求："用这本小说训练一个续写 skill"、"把《X》风格炼成 skill"、"训练一个能续写 X 的 skill"。

**不会主动触发**——只有用户显式调用才启动训练流程。

## 输入

二选一（用户启动时必给）：
- **整本文件**：.txt / .md，UTF-8（推荐，最稳）
- **章节 URL 列表**：按章节顺序排列；自动按 WebFetch → PowerShell → 浏览器代理逐级降级抓取

可选参数：目标 skill 名、种子章节数 K（默认自适应：N≥5→3、N=4→2、N=3→1）、单章最大尝试数（默认 5）、通过阈值（默认 0.85）。

## 产出

落盘到 `<本 skill 同级目录>/<novel-slug>-quill/`：

```
<novel-slug>-quill/
├── SKILL.md                              # 主续写 skill ≤ 8000 字
└── references/
    ├── author-profile.json               # 作者画像（POV、句长直方图、高频词、忌讳词、人物表、术语表、滚动故事概要）
    ├── character-cards/<name>.md         # 主要人物卡
    ├── style-rules.md                    # 详细风格规则
    └── world-bible.md                    # 世界观/术语
```

未来 Claude 装载这份产出即可续写——它**不接触本训练流程的任何中间产物**。

## 架构（三层 Agent）

```
Main Agent（用户主对话，全局唯一，仅做调度）
├── Fetch Source Unit  ───── 一次性，抓原文 / 接附件 / 切片
├── Init Skill Unit    ───── 一次性，读前 K 章产 skill 初版
└── Training Unit ×N   ───── 每章一个，跑完即销毁
    内部由 Unit 启动 sub-agent：
    ├── Edit Module       根据上一单元 lesson，对 skill 做 ≤ 3 维改动
    ├── Execution Module  在 skill + 上一章 + 滚动故事概要下生成下一章
    ├── Scoring Module    评分 Agent 精炼对照 → spawn 3 个独立裁判 → 每个裁判对 6 维独立打分 → 中位数聚合
    ├── Commit Module     据评分采纳 / 从快照回滚
    └── Summary Module    提炼好/坏改动 → 写 lesson 给下一单元 + 更新滚动故事概要
```

详见 [SKILL.md](SKILL.md) 与 `references/` 下的：
- [architecture.md](references/architecture.md) — 三层 agent 边界与职责
- [workflow.md](references/workflow.md) — 端到端流程
- [directory-layout.md](references/directory-layout.md) — alchemist-temp/ 目录约定
- [output-skill-spec.md](references/output-skill-spec.md) — 产出 skill 的标准形式
- [scoring-rubric.md](references/scoring-rubric.md) — 6 维评分细则（裁判团模式）
- [prompts/](references/prompts/) — 8 份提示词模板

## 工作目录

`<用户启动 Claude 的当前目录>/alchemist-temp/`。无 git 环境也能跑——所有回滚靠文件快照。

## 使用产出 skill

训练完成后，未来任意 Claude 会话只需安装到本机 skill 目录，让 Claude 装载即可：

```
请用 <novel-slug>-quill 续写：
<前一章正文>
```
