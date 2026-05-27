# 目录与文件约定

工作根目录：`<用户启动 Claude 的当前目录>/alchemist-temp/`。**绝不**写入用户主目录或全局位置。

## 完整目录树

```
<CWD>/alchemist-temp/
├── state.json                               # 全局状态单一真相（Main Agent 原子写入；续跑入口）
│
├── source/                                  # Fetch Source Unit 切片产物（只读）
│   ├── chapter-001.md
│   ├── chapter-002.md
│   └── ...
│
├── attempts/                                # 章训练详细产物
│   ├── chapter-004/                         # 目录名一律 chapter-NNN（3 位 padded），与 source/ 文件名同字号
│   │   ├── attempt-00/                      # baseline，无 Edit；NN 一律 2 位 padded
│   │   │   ├── generated.md                 # Execution 输出
│   │   │   ├── scoring-context.md           # Scoring Agent 写的对照摘要（裁判必读）
│   │   │   ├── score.json                   # Scoring 输出
│   │   │   ├── report.md                    # Scoring 输出（含 3 裁判分歧）
│   │   │   └── judges/                      # 三裁判原始输出
│   │   │       ├── judge-A.json
│   │   │       ├── judge-B.json
│   │   │       └── judge-C.json
│   │   ├── attempt-01/                      # 有 Edit
│   │   │   ├── .commit-pending              # 事务标记：Edit 完成后立即写空文件，Commit 完成后删
│   │   │   ├── references-snapshot/         # 整个 <TARGET_SKILL>/references/ 镜像（含 author-profile / synopsis / character-cards/ / style-rules / world-bible）
│   │   │   ├── skill-snapshot/SKILL.md      # 主 SKILL.md 快照
│   │   │   ├── skill-changes.md             # Edit 写的改动摘要（## 处 1 / 处 2 / 处 3 编号）
│   │   │   ├── generated.md
│   │   │   ├── scoring-context.md
│   │   │   ├── score.json
│   │   │   ├── report.md
│   │   │   ├── judges/
│   │   │   └── commit-log.md                # Commit 决策（accept / rollback）
│   │   ├── ...
│   │   └── summary.md                       # Summary 写的本章训练摘要
│   └── ...
│
├── lessons/                                 # 跨章经验传递
│   ├── lesson-004.md                        # 文件名采用 lesson-NNN.md（3 位 padded，对应 chapter-NNN）
│   ├── lesson-005.md
│   └── ...
│
├── snapshots/                               # 【必选】每章 Commit 完成后的整个 TARGET_SKILL 镜像
│   └── after-chapter-NNN/                   # 包含 SKILL.md + references/ 全套
│       ├── SKILL.md
│       └── references/...
│
├── regression/                              # Regression Unit 产物（每 5 章一次）
│   ├── after-chapter-005/
│   │   ├── replay-chapter-002/              # 用最新 skill 回测早期已通过章节
│   │   │   ├── generated.md
│   │   │   ├── score.json
│   │   │   └── report.md
│   │   └── summary.md                       # 本次回测的 delta 总结（写入下一 lesson 的"红线"段）
│   └── ...
│
├── logs/
│   ├── training.jsonl                       # 每章一行（机器可读）
│   ├── chapter-NNN.jsonl                    # 单章详细日志（每次 attempt 一行）
│   ├── regression.jsonl                     # 回测日志（每次回测一行）
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
    ├── author-profile.json                  # 作者画像（POV、句长直方图、高频词、忌讳词、人物索引、术语表）—— 轻量 JSON，无长文本
    ├── synopsis.md                          # 三段式滚动故事概要（主线骨架 / 近期细节 / 活跃伏笔）
    ├── character-cards/                     # 详细人物卡（必有，每位 1 份独立 .md）
    │   ├── <slug-1>.md
    │   ├── <slug-2>.md
    │   └── ...
    ├── style-rules.md                       # 详细风格规则
    └── world-bible.md                       # 世界观/术语
```

> "本 skill 同级目录" = 本 SKILL.md 所在目录的父目录（即全局 skills 安装根，类 Unix 上常见的 `~/.agents/skills/`、Windows 上常见的 `<用户主目录>/.agents/skills/`）。Main Agent 在前置环境校验时通过自身 SKILL.md 的绝对路径反推该根目录，**全程不要把任何具体的用户名 / 操作系统路径写死到任何文件**。

## 硬规则

1. **`<CWD>` = 用户启动 Claude 的当前目录**。即 process.cwd()。`alchemist-temp/` 必须建在这里，不得写入用户主目录或 skill 安装目录
2. **章节序号格式严格统一**：路径中一律 3 位 padded（`chapter-004` / `attempt-01` / `lesson-007.md` / `after-chapter-012/`）；JSON 字段 `chapter_index` / `attempt` 一律 int。任何提示词模板里 `<i>` 占位符填的都是 padded 字符串（如 `004`）
3. **state.json 是状态单一真相**：Main Agent 每章训练前/后必须 `Write` 一次 `<CWD>/alchemist-temp/state.json`；写法是 write-then-rename（先写 `state.json.tmp`，再 rename 覆盖 `state.json`）；其他 Unit / Module **绝不**直接改 state.json，只读
4. **多次训练同一小说不要覆盖**：续跑时按 `state.json.source.fingerprint.chapter_hashes` 与新切片的 hash 比对——一致即续跑、不一致就询问用户是新建（旧 alchemist-temp 重命名为 `alchemist-temp.bak-<timestamp>`）还是中止
5. **每次 attempt 的事务原子性**：Edit Module 改写 `<TARGET_SKILL>/` 任何文件**之前**，必须先：
   - 把整个 `<TARGET_SKILL>/references/` 目录镜像复制到 `attempts/chapter-NNN/attempt-NN/references-snapshot/`
   - 把 `<TARGET_SKILL>/SKILL.md` 复制到 `attempts/chapter-NNN/attempt-NN/skill-snapshot/SKILL.md`
   - 在 `attempts/chapter-NNN/attempt-NN/.commit-pending` 写一个空文件作为事务标记
   Commit Module 落盘 commit-log.md 后**立即** `Remove-Item .commit-pending`。续跑时遇到孤立的 `.commit-pending` 即知该 attempt 中断，必须从 `state.last_known_good` 整体回滚该章重训
6. **每章 Commit 完成后必须章末快照**：Training Unit 在 Summary 落盘后，把当前 `<TARGET_SKILL>/` 全量镜像复制到 `<CWD>/alchemist-temp/snapshots/after-chapter-NNN/`；同时由 Main Agent 把 `state.last_known_good` 指向该路径
7. **source/ 切片只读**：Training Unit 内部任何模块都不得修改 source/ 内容
8. **lessons/ 单调追加**：每章 Summary 写一份 lesson，不删旧的
9. **logs/training.jsonl 单调追加**：每章一行；不重写
10. **judges/ 三份分裁判产出独立保留**：用于事后人工 review 分歧

## state.json schema

由 Main Agent 维护。其它 Unit / Module 仅读不写。

```json
{
  "schema_version": 1,
  "run_id": "<ISO 8601 timestamp>-<8-char uuid>",
  "created_at": "<ISO 8601>",
  "updated_at": "<ISO 8601>",

  "source": {
    "type": "file | url-list | attachment",
    "fingerprint": {
      "chapter_count": 30,
      "chapter_hashes": ["sha256:abc...", "sha256:def...", "..."]
    }
  },

  "params": {
    "K": 3,
    "max_attempts": 5,
    "min_threshold_floor": 0.85,
    "min_meaningful_improvement": 0.005,
    "ask_period": 5
  },

  "target_skill_path": "<absolute>",

  "phase": "fetch | init | training | regression | paused | done | error",
  "last_completed_chapter": 7,
  "next_chapter": 8,
  "in_flight": null,

  "adaptive_threshold": {
    "value": 0.78,
    "computed_after_chapter": 5,
    "baseline_scores": [0.71, 0.74, 0.69]
  },

  "last_known_good": {
    "snapshot_dir": "<CWD>/alchemist-temp/snapshots/after-chapter-007/",
    "as_of_chapter": 7
  },

  "regression": {
    "next_check_after_chapter": 10,
    "history": [
      {"checked_after_chapter": 5, "checked_chapters": [4, 5], "deltas": [{"chapter": 4, "delta": -0.02}, {"chapter": 5, "delta": 0.01}]}
    ]
  },

  "ask_user": {
    "due_at_chapter": 10,
    "last_asked_at_chapter": 5
  },

  "errors": []
}
```

`in_flight` 在章训练循环开始前写入 `{"chapter_index": <int>, "started_at": "<ISO>"}`，章末 Summary 完成后置回 `null`。续跑时见到非 null `in_flight` → 走"该章中断恢复"路径。

## 文件大小预算

| 文件 | 软上限 | 硬上限 |
|---|---|---|
| 目标 SKILL.md（产出） | 6000 字 | 8000 字 |
| 各 references/*.md（含 style-rules / world-bible / synopsis） | 8000 字 | 16000 字 |
| `synopsis.md` 三段总和 | 3500 字 | 4500 字（超出强制压缩） |
| `character-cards/<slug>.md` 单文件 | 2000 字 | 4000 字 |
| author-profile.json | 8 KB | 16 KB（已不含 rolling_synopsis 后大幅缩水） |
| 单章 generated.md | 上一章字数 ±30% | — |
| lesson-NNN.md | 1500 字 | 3000 字 |
| state.json | 4 KB | 16 KB |

超硬上限的文件 → 拆分到子文件，主文件留一句话指引。`synopsis.md` 超硬上限时必须先压缩"主线骨架"早期内容（多条整合成一条总括），再追加新内容。

## 路径解析约定

提示词模板里出现的占位符：
- `<CWD>` → 用户启动 Claude 的当前目录绝对路径
- `<SKILL_DIR>` → 本 skill 安装目录绝对路径（即 echo-quill-alchemist/）
- `<TARGET_SKILL>` → 目标 skill 落盘根目录（即 `<本 skill 同级目录>/<novel-slug>-quill/`）
- `<RUN>` → `<CWD>/alchemist-temp/`

Main Agent 在 spawn 任何 Unit 前先把这些占位符解析为绝对路径再放进提示词。
