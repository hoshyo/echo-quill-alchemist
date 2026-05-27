# 目录与文件约定

工作根目录：`<用户启动 Claude 的当前目录>/alchemist-temp/`。**绝不**写入用户主目录或全局位置。

## 完整目录树

```
<CWD>/alchemist-temp/
├── source/                                  # Fetch Source Unit 切片产物（只读）
│   ├── chapter-001.md
│   ├── chapter-002.md
│   └── ...
│
├── attempts/                                # 章训练详细产物
│   ├── chapter-002/                         # i ≥ K+1 的章节才有；目录名 = 真实章节序号
│   │   ├── attempt-00/                      # baseline，无 Edit
│   │   │   ├── generated.md                 # Execution 输出
│   │   │   ├── score.json                   # Scoring 输出
│   │   │   ├── report.md                    # Scoring 输出（含 3 裁判分歧）
│   │   │   └── judges/                      # 三裁判原始输出
│   │   │       ├── judge-A.json
│   │   │       ├── judge-B.json
│   │   │       └── judge-C.json
│   │   ├── attempt-01/                      # 有 Edit
│   │   │   ├── skill-snapshot/SKILL.md      # 本次 attempt 开始前的 skill 快照
│   │   │   ├── skill-changes.md             # Edit 写的改动摘要
│   │   │   ├── generated.md
│   │   │   ├── score.json
│   │   │   ├── report.md
│   │   │   ├── judges/
│   │   │   └── commit-log.md                # Commit 决策（accept / rollback）
│   │   ├── ...
│   │   └── summary.md                       # Summary 写的本章训练摘要
│   └── ...
│
├── lessons/                                 # 跨章经验传递
│   ├── lesson-002.md                        # 第 2 章 Summary 写给第 3 章 Edit 的经验
│   ├── lesson-003.md
│   └── ...
│
├── snapshots/                               # （可选）章末已采纳 skill 的快照
│   ├── after-chapter-002.md
│   └── ...
│
├── logs/
│   ├── training.jsonl                       # 每章一行（机器可读）
│   ├── chapter-<i>.jsonl                    # 单章详细日志（每次 attempt 一行）
│   └── fetch-errors.log                     # Fetch Source Unit 抓取失败日志
│
├── progress.md                              # Main Agent 视图（人类可读，每章一行）
└── final-summary.md                         # 末章训练完成后写
```

## 目标 skill 落盘路径

```
<本 skill 同级目录>/<novel-slug>-quill/
├── SKILL.md                                 # 续写 skill 主文件 ≤ 8000 字
└── references/
    ├── author-profile.json                  # 作者画像（POV、句长直方图、高频词、忌讳词、人物表、术语表）
    ├── character-cards/
    │   ├── <name-1>.md
    │   ├── <name-2>.md
    │   └── ...
    ├── style-rules.md                       # 详细风格规则
    └── world-bible.md                       # 世界观/术语
```

> "本 skill 同级目录" = 本 SKILL.md 所在目录的父目录（即全局 skills 安装根，类 Unix 上常见的 `~/.agents/skills/`、Windows 上常见的 `<用户主目录>/.agents/skills/`）。Main Agent 在前置环境校验时通过自身 SKILL.md 的绝对路径反推该根目录，**全程不要把任何具体的用户名 / 操作系统路径写死到任何文件**。

## 硬规则

1. **`<CWD>` = 用户启动 Claude 的当前目录**。即 process.cwd()。`alchemist-temp/` 必须建在这里，不得写入用户主目录或 skill 安装目录
2. **多次训练同一小说不要覆盖**：若 `alchemist-temp/` 已存在同名 source/ 内容（按章节文件 hash 判断），询问用户是续跑还是新建（新建则把旧 alchemist-temp 重命名为 `alchemist-temp.bak-<timestamp>`）
3. **每次 attempt 必须先快照**：Edit Module 写新 SKILL.md 之前，把当前 SKILL.md 复制到 `attempts/chapter-<i>/attempt-<NN>/skill-snapshot/`。这是无 git 环境下的回滚物质基础
4. **source/ 切片只读**：Training Unit 内部任何模块都不得修改 source/ 内容
5. **lessons/ 单调追加**：每章 Summary 写一份 lesson，不删旧的
6. **logs/training.jsonl 单调追加**：每章一行；不重写
7. **judges/ 三份分裁判产出独立保留**：用于事后人工 review 分歧

## 文件大小预算

| 文件 | 软上限 | 硬上限 |
|---|---|---|
| 目标 SKILL.md（产出） | 6000 字 | 8000 字 |
| 各 references/*.md | 8000 字 | 16000 字 |
| author-profile.json | 12 KB | 32 KB |
| 单章 generated.md | 上一章字数 ±30% | — |
| lesson-NNN.md | 1500 字 | 3000 字 |
| 滚动故事概要（Summary 维护，存于 lesson 末尾） | 2000 字 | 3000 字 |

超硬上限的文件 → 拆分到子文件，主文件留一句话指引。

## 路径解析约定

提示词模板里出现的占位符：
- `<CWD>` → 用户启动 Claude 的当前目录绝对路径
- `<SKILL_DIR>` → 本 skill 安装目录绝对路径（即 echo-quill-alchemist/）
- `<TARGET_SKILL>` → 目标 skill 落盘根目录（即 `<本 skill 同级目录>/<novel-slug>-quill/`）
- `<RUN>` → `<CWD>/alchemist-temp/`

Main Agent 在 spawn 任何 Unit 前先把这些占位符解析为绝对路径再放进提示词。
