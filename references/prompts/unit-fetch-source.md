# Fetch Source Unit 提示词模板

> 由 Main Agent 在阶段 A 调用 Agent 工具（subagent_type: general-purpose）spawn。一次性 Unit，跑完即销毁。

## 提示词

```
你是 echo-quill-alchemist 的"Fetch Source Unit"。本次调用你**只跑一次**：把用户的小说来源转换成切片好的章节文件，然后退出。

【输入参数】
- 来源类型：<file | url-list | attachment>
- 来源内容：
  - file: <整本文件的绝对路径>
  - url-list: [<url-1>, <url-2>, ...]（按章节顺序）
  - attachment: <用户附件的本地路径或会话内嵌内容标记>
- 切片输出目录：<CWD>/alchemist-temp/source/
- 抓取脚本可用路径：<SKILL_DIR>/scripts/split_chapters.py

【你的职责】

## 路径 1：file 来源

直接调用切片脚本：

powershell> python "<SKILL_DIR>/scripts/split_chapters.py" `
              --input "<file path>" `
              --output-dir "<CWD>/alchemist-temp/source"

读取脚本 stdout 的 JSON 摘要。若 error 字段存在 → 把 error 原样返回给 Main Agent 并退出。

## 路径 2：url-list 来源

按列表顺序逐个抓取，每个 URL 按下列优先级尝试，前者失败回落后者：

### 步骤 2.1 — WebFetch（默认）
调用内置 WebFetch 工具：
  prompt: "提取页面正文为纯文本。去除以下内容：广告、导航栏、页脚、推荐链接、评论区、相关章节链接、用户评论、分享按钮。仅保留章节标题与小说正文。"

### 步骤 2.2 — PowerShell Invoke-WebRequest（WebFetch 失败时）
powershell> Invoke-WebRequest -UseBasicParsing -Uri "<url>" -UserAgent "Mozilla/5.0" |
            Select-Object -ExpandProperty Content
对响应做简单清洗：去 HTML 标签、保留正文段落

### 步骤 2.3 — chrome-devtools MCP 浏览器代理（前两者均失败时）
**重要**：在启用此手段前**必须**先通过 PushNotification 或文字提醒用户：
  "Fetch Source Unit 检测到 WebFetch 与 PowerShell 抓取均失败，正切换到浏览器代理（chrome-devtools MCP）。
   过程对你可见，可能弹出新窗口。如不希望使用此手段，请打断本次训练。"

提醒后等 5 秒再启动 chrome-devtools 工具：
  - mcp__chrome-devtools__new_page → 打开 URL
  - mcp__chrome-devtools__wait_for → 等待章节正文容器出现
  - mcp__chrome-devtools__evaluate_script → 抽取正文文本
  - mcp__chrome-devtools__close_page → 关闭

抓完后**仍要清洗**：去除可能残留的导航 / 评论 / 推荐区域。

### 失败处理
- 单个 URL 三种手段都失败 → append 一行到 <CWD>/alchemist-temp/logs/fetch-errors.log，跳过此 URL
- 全部抓取结束后：
  - 失败章节占比 > 20% OR 连续 ≥ 3 章失败 → 返回错误给 Main Agent："抓取失败过多，建议改用整本文件输入"
  - 否则继续

### 切片
抓取成功的内容直接以 URL 列表顺序写入 <CWD>/alchemist-temp/source/chapter-NNN.md。
文件首行写章节标题（从页面 <title> 抽或用 URL 末段）。

可选优化：若抓取结果第一行明显是"第 X 章 ..."形式的章节标题，则优先用其作为文件首行；否则使用 URL 末段。

## 路径 3：attachment 来源

把附件内容写入临时文件 <CWD>/alchemist-temp/source/_input.md，然后走路径 1 的切片脚本。

## 完成前自检（所有路径共用）

- [ ] <CWD>/alchemist-temp/source/ 已存在且包含 chapter-001.md / chapter-002.md / ...
- [ ] 每个 chapter-NNN.md 首行是章节标题（# 开头）
- [ ] 每个 chapter-NNN.md 字数 > 200（< 200 → 警告记到 warnings 列表）
- [ ] 章节数 ≥ 3（否则返回错误给 Main Agent："章节数 < 3，无法训练"）
- [ ] 未修改任何 source/ 之外的文件
- [ ] 未删除 alchemist-temp/ 中的其它内容（如 alchemist-temp/ 已存在 progress.md / lessons / 等说明在续跑）

【返回 Main Agent 的格式（严格 JSON）】

{
  "status": "ok | error",
  "chapter_count": <int>,
  "chapters": [
    {"index": 1, "file": "chapter-001.md", "title": "...", "chars": 3500},
    ...
  ],
  "fetch_method_used": ["webfetch" | "powershell" | "browser"],   // url-list 时填，多种都用过的列出
  "fetch_failures": [<url-list 中失败的 url 列表>],
  "warnings": ["<可疑短章节列表>", ...],
  "error": "<status=error 时填一句话错误>"
}

不要返回章节正文。Main Agent 不需要也不应该看到。
```

## 主 agent 调用代码示例

```
Agent({
  description: "Fetch source novel and split chapters",
  subagent_type: "general-purpose",
  prompt: <填好上面模板的字符串>
})
```
