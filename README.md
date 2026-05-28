# Echo-Quill Alchemist · 回声炼金术士

把一本小说的语感"提炼"成一份 DPO 训练数据 + 一个可复用的风格条件续写引擎，全程通过对话驱动。

你不需要懂 ROUGE、双塔裁判、DPO 是什么；你跟 Claude 说"用这本书炼金"，剩下的它替你跑。

---

## 这是什么

Echo-Quill Alchemist 是一个本地系统，把任意小说切成 `(上文, 真实续写)` 片段，每片对照原作做：

- **Best-of-N 候选** —— 让大模型生成 4 个续写
- **困难负样本 (Hard Negative)** —— 强制再生成一个故意"风格毁容"的续写
- **双塔裁判** —— 用本地 MiniLM 余弦相似度 + ROUGE-L F1 给所有候选打分，**剥夺大模型主观打分权**
- **强制 DPO 配对** —— `最佳 vs 困难负` 至少出一对，差距够大的 `最佳 vs 最差` 再加一对，每片至少产 1 条偏好对
- **风格规则蒸馏** —— 在线提取并维护带 `lifespan / hit_count` 生命周期的风格规则池
- **WebSocket 全息观测台** —— 暗黑风 React 仪表盘实时显示规则热力图、竞技场、日志流

跑完之后，`core/data/dpo.jsonl` 是产出的训练数据；同时一个 `/infer` 端点可以拿当前规则池和高分 DPO 例子做风格条件续写。

外面包了一层 **Anthropic Skill**：你只跟 Claude 说自然语言，Claude 调度装依赖、起服务、推流、推理、停服全过程。

---

## 快速开始

### 安装方式

```bash
npx skills add hoshyo/echo-quill-alchemist
```

### 推荐方式 —— 跟 Claude 说话

```
你 ▸  用 echo-quill 训练 D:/novels/三体.txt

Claude ▸ [doctor.py] 检查环境... 发现你 CC Switch 已切到
        llm.xxx.com，会用这个 relay 跑约 300 chunks × 6 次调用 ≈
        1800 次模型请求。继续吗？

你 ▸  好，开始

Claude ▸ [start_services] [open_dashboard] [train.py ...]
        浏览器已打开 http://localhost:5173 —— 看仪表盘进度即可
```

```
你 ▸  用刚训练好的风格写一段：他推开门，屋里很暗。

Claude ▸ [infer.py --context "..."]
        →（输出风格化续写）
```

### 也可以手跑脚本

如果你不想通过 Claude，直接 CLI 也能用：

```bash
# 1) 体检
python scripts/doctor.py

# 2) 装依赖（首次会拉 torch + MiniLM 约 2GB）
python scripts/install_deps.py

# 3) 起服务（自动读 ~/.claude/settings.json 或 .env 里的凭据）
python scripts/start_services.py

# 4) 推一本小说
python scripts/train.py --path /path/to/novel.txt --chunk_size 500

# 5) 用学到的风格续写
python scripts/infer.py --context "夜半，他推开窗。"

# 6) 收摊
python scripts/stop_services.py
```

---

## 它会做什么 · 单 chunk 流水

```
入炉 (context, truth)
   │
   ├─ 阶段 generation
   │     ├─ Best-of-N 4 个常规候选        (LLM 并行)
   │     └─ 1 个 Hard Negative           (LLM 并行)
   │
   ├─ 阶段 judging
   │     for each candidate:
   │       semantic = MiniLM(candidate, truth)
   │       rouge    = ROUGE-L(candidate, truth)
   │       composite = 0.6 * semantic + 0.4 * rouge
   │     按 composite 降序排
   │
   ├─ 阶段 dpo （强制至少 1 对）
   │     emit DPOPair(best,  hard_negative)               ← 永远产出
   │     if best.composite − worst.composite ≥ 0.05:
   │       emit DPOPair(best, worst_normal)               ← 差距大才追加
   │     append → core/data/dpo.jsonl
   │
   ├─ 阶段 rules
   │     - 老规则：truth 命中 → hit_count++ , lifespan +1（封顶）
   │              未命中 → lifespan -1，归零裁汰
   │     - 让 LLM 从 truth 提取 ≤5 条新规则，去重并入池
   │
   └─ idle, 等待下一片
```

整个过程通过 WebSocket 推到仪表盘，无轮询。

---

## 架构

```
echo-quill-alchemist/
│
├── SKILL.md                  ← 自然语言入口（瘦路由：意图 → 脚本表）
├── scripts/                  ← Skill 调度的脚本（厚逻辑都在这）
│   ├── _paths.py               共享路径常量
│   ├── doctor.py               JSON 系统体检（永远先跑）
│   ├── detect_provider.py      凭据解析：CC Switch / .env / shell env
│   ├── install_deps.py         pip + npm 幂等安装
│   ├── ensure_env.py           .env 校验/生成
│   ├── start_services.py       后台拉起 + 写 PID 到 .echo-quill.state.json
│   ├── stop_services.py        从 state 杀进程，端口兜底
│   ├── open_dashboard.py       跨平台浏览器
│   ├── train.py                推流入口（包 core/scripts/feeder.py）
│   └── infer.py                调 /infer，吐风格化续写
│
├── references/               ← 按需加载的深度文档
│   ├── architecture.md         双塔/DPO/规则寿命/线协议细节
│   ├── workflow-train.md       训练剧本 + 成本估算 + 决策流
│   ├── workflow-infer.md       推理流程 + 调参建议
│   └── troubleshooting.md      已踩过的坑及修法
│
├── core/                     ← 实际系统（被 SKILL.md 包装的内核）
│   ├── backend/                FastAPI + WebSocket
│   │   ├── models.py             Pydantic 黑盒（StyleRule、Candidate、DPOPair…）
│   │   ├── engine.py             DualTowerJudge + LLMClient + Alchemist
│   │   ├── auth_resolver.py      凭据解析器（shell > .env > ~/.claude/settings.json）
│   │   └── server.py             /trigger_training /infer /state /healthz /ws
│   ├── frontend/               Vite + React + Zustand 仪表盘
│   │   └── src/
│   │       ├── App.tsx           三栏暗黑 UI
│   │       └── store.ts          WebSocket 状态机
│   ├── scripts/feeder.py       内部推流器（外层 train.py 包装）
│   └── data/
│       ├── dpo.jsonl             所有 DPO 偏好对（持久产物）
│       └── logs/                 backend.log / frontend.log
│
├── .env.example              ← 显式覆盖凭据用（多数情况不需要）
├── .echo-quill.state.json    ← 运行时 PID 注册表（运行时生成）
└── LICENSE
```

### 三个不可妥协的设计原则

1. **大模型不当裁判**。所有质量分 = MiniLM 余弦 + ROUGE-L F1 的加权和，永远不要回到"让 LLM 打 0-10 分"
2. **每片必出 DPO**。Hard Negative 是强制兜底，所以即使候选都很烂也有一对偏好可学
3. **状态都有寿命**。`StyleRule` 的 `lifespan/hit_count` 是必填字段，仪表盘的 logs/dpo 列表都有上限，禁止无界增长

---

## 模型与凭据

### 默认行为：什么都不用配

后端启动时按这个顺序找凭据，第一个找到的赢：

| 优先级 | 来源 | 何时用得上 |
|:-:|---|---|
| 1 | shell 环境变量 | 你显式 export 了 |
| 2 | 项目根 `.env` | 你想给本项目锁定到指定 provider |
| 3 | `~/.claude/settings.json` 的 `env` 块 | **CC Switch / Claude Code 当前 profile** |

如果你已经在用 [CC Switch](https://github.com/farion1231/cc-switch) 之类工具管理 Claude Code 的多 endpoint 配置，**Echo-Quill 直接复用，无需任何额外配置**。CC Switch 切换 profile 后，重启后端即可：

```bash
python scripts/stop_services.py --backend
python scripts/start_services.py --backend
```

### 支持的认证方式

- **`ANTHROPIC_AUTH_TOKEN`** → `Authorization: Bearer <token>` （Claude Code / 第三方 relay 风格）
- **`ANTHROPIC_API_KEY`** → `x-api-key: <key>` （Anthropic 官方 SDK 风格，sk-ant-…）
- **`ANTHROPIC_BASE_URL`** → 自托管 / 反代 endpoint（如 `https://your-relay.example.com`）
- **`OPENAI_API_KEY` + `OPENAI_BASE_URL`** → OpenAI 或兼容协议

后端启动行会清楚告诉你用了哪个：

```
[server] alchemist ready (provider=anthropic, creds=shell_env,
         base=https://xxx.com, key=sk-L…abc)
```

---

## 仪表盘

打开 `http://localhost:5173`，看到三栏：

- **左 · Style Rules** —— 风格规则热力图：每条规则一条 lifespan 进度条 + hit_count 橙色标签
- **中 · Arena** —— 竞技场：当前片段的上文预览 + 所有常规候选（按 composite 降序）+ 红框 HARD NEG
- **右 · Logs** —— 实时日志流，chunk 入炉/出炉/相变都在这里

顶栏 4 个指示器：WS 连接状态、当前 phase、已处理 chunks、累积 DPO 对数。

---

## 推理 ≠ 微调模型

重要澄清：本系统**不会**给你训练出一个权重被改过的模型。`core/data/dpo.jsonl` 是给下游训练器（TRL / LLaMA-Factory 等）准备的偏好数据。

直到你接上真正的微调流程之前，`/infer` 做的是 **prompt 时风格 RAG**：

```
top-K 风格规则 (按 hit_count) + top-N 高分 DPO chosen 例子
        │
        ▼
    LLM 系统提示词 + 用户上文
        │
        ▼
    风格化续写
```

这已经能产出明显贴近原作语感的续写。但如果你期望"模型权重永久学会了这个风格"，请把 `dpo.jsonl` 接到正经的 DPO 训练流程上。

---

## 系统要求

- Python 3.10+
- Node.js 18+ / npm
- ~3 GB 磁盘（`torch` + MiniLM 缓存 + node_modules）
- 一个能调通 Anthropic Messages API 或 OpenAI Chat Completions 的 endpoint

首次启动会从 HuggingFace 下载 `all-MiniLM-L6-v2`（约 90MB），需要联网。之后离线可用。

---

## 故障排查

第一步永远是：

```bash
python scripts/doctor.py
```

它输出的 JSON 是系统当前状态的真值。`references/troubleshooting.md` 里收录了已踩过的坑：MiniLM 下载卡住、端口占用、CC Switch 切换后凭据未刷新、Windows 后台进程日志缓冲、自托管 relay 路径不兼容、等等。

---

## 许可

见 [LICENSE](./LICENSE)。
