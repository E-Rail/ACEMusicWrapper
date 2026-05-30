# AI 虚拟乐队合作者

## 一、创意背景

在学习论文中的 AI 音乐生成原理，并亲自体验 AI 音乐工具后，我觉得目前很多 AI 音乐工具更像是一个自动作曲机器：用户先输入提示词，然后AI 直接生成一首完整的音乐作品。

这种方式虽然高效，但也存在一个问题，用户很难像真正参与音乐创作一样，对音乐中的细节进行持续沟通和调整，例如，用户可能只想让鼓点更轻一点、贝斯更有律动感，或者让副歌部分的人声更有爆发力，但现有工具往往会重新生成整首歌，导致原来满意的部分也被改变。

---

## 二、核心创意

在乐队开始排练之前，系统首先通过大语言模型识别用户将要排练或创作的歌曲。AI 可以自动在网络上搜集相关资料，例如歌曲风格、乐队背景、常见编曲方式、和弦走向、节奏特点等。同时，系统还可以识别音乐中的不同音轨（可以人工提供音频 然后使用一些专业软件分离），例如鼓、贝斯、吉他、键盘、人声等，为后续的分轨修改和协作创作做准备。

在这个系统中，AI 不再是一个单一的音乐生成工具，而是被设计成几个不同的**虚拟乐手**：

- **AI 鼓手**：喜欢复杂节奏，擅长设计律动感强的鼓点；
- **AI 贝斯手**：偏爱低沉、稳定的声音，负责支撑整首歌的节奏基础；
- **AI 吉他手**：喜欢摇滚风格创作；
- **AI 键盘手**：擅长 ambient 氛围音色、jazz chord 和和声铺底；
- **AI 主唱**：可以根据歌词情绪调整唱腔，例如温柔、克制、爆发或沙哑。

用户可以像和真实乐队成员排练一样，与这些 AI 乐手进行对话。

例如用户可以说：

> 鼓手收一点，不要太满。主唱副歌部分更有爆发力……

此时，系统不会重新生成整首歌，而是分别理解用户对不同乐手的要求，并针对对应音轨进行局部修改。

---

## 三、结合 AI 音乐生成原理

这个创意可以结合论文中提到的 AI 音乐生成技术，尤其是 **分轨生成、局部重绘、条件控制生成和 masked generative framework**。

### 1. 分轨生成

AI 可以将音乐拆分为不同音轨，例如：

- 鼓轨；
- 贝斯轨；
- 吉他轨；
- 键盘轨；
- 人声轨；
- 和声轨；
- 氛围音效轨。

这样用户就可以单独调整某一个声部，而不是每次都重新生成整首歌。

例如，如果用户只想让鼓点更简单，AI 就只修改鼓轨；如果用户喜欢当前的吉他，就可以锁定吉他轨，不让它发生变化。

---

### 2. 局部重绘

局部重绘的核心思想是：AI 不需要重新生成全部内容，而是只修改用户指定的部分。

例如：

- 用户想修改前奏，AI 就只重绘 intro 部分；
- 用户想增强副歌，AI 就只修改 chorus；
- 用户想让 bridge 更有张力，AI 就只调整 bridge；
- 用户想改变主唱音色，AI 就只改变 vocal timbre。

这种方式可以保留用户已经满意的内容，同时对不满意的地方进行精准优化。

---

### 3. Masked Generative Framework

这个创意还可以使用 masked generative framework。用户可以把想修改的部分"遮住"，让 AI 只在被遮住的区域重新生成音乐。

例如：

```text
保留：主歌吉他、贝斯、鼓点  
修改：副歌人声和键盘和声  
不变：整体速度、调性、歌曲结构
```

## 四、重要性与必要性

### 1. 乐队排练前的智能准备

在真实乐队排练之前，AI 可以先帮助乐队对歌曲进行系统化分析，从而提高排练效率。它可以完成以下准备工作：

- 识别歌曲结构；
- 分析和弦走向；
- 拆分不同音轨；
- 总结每个乐器的演奏特点；
- 给出针对性的排练建议。

例如，AI 可以提醒鼓手注意某些段落中的节奏变化，提示贝斯手在哪些地方需要和底鼓保持紧密配合，也可以帮助吉他手提前分析和弦转换中的难点。

这种功能的重要性在于，乐队可以在正式排练之前先预览整体效果。如果发现某首歌对队员来说难度过大，或者整体改编效果不理想，就可以提前调整曲目、降低难度或重新安排编曲，避免在排练当天浪费大量时间。

同时，现实中的乐队排练往往面临时间难以协调的问题。如果排练当天有乐手临时缺席，AI 虚拟乐手也可以暂时顶替缺席成员，例如代替鼓手、贝斯手或键盘手完成伴奏，使排练能够顺利进行下去。

因此，这一系统不仅可以提高排练前的准备质量，也能增强乐队排练的稳定性和灵活性。

---

### 2. 个人用户的虚拟组队创作

对于没有乐队的个人用户来说，这个工具可以让他们体验组乐队的感觉，像真正的乐队主创一样，与不同性格和风格的 AI 乐手共同完成作品。

用户可以先提出一个创作想法，例如：

> 我想做一首有夏天傍晚感觉的音乐，主歌比较松弛，副歌突然变得明亮。

随后，不同 AI 乐手可以分别给出自己的创作方案：

- AI 鼓手设计轻快但不过分复杂的节奏；
- AI 贝斯手加入稳定的律动；
- AI 吉他手设计清爽的 riff；
- AI 键盘手加入具有氛围感的 pad；
- AI 主唱根据歌词调整情绪表达。

在这个过程中，用户可以像真实排练一样不断提出修改意见。这降低了个人音乐创作的门槛。即使用户不会演奏所有乐器，也可以通过与 AI 乐手协作，完成一首具有完整乐队质感的作品。

---

### 3. 音乐教育与编曲学习

这个系统还可以用于音乐学习。用户不仅可以听到 AI 修改后的音乐效果，还可以看到 AI 对修改原因的解释，从而理解背后的编曲逻辑。

例如，用户可以向 AI 贝斯手提问：

> 为什么这里贝斯要跟着底鼓走？


通过这种方式，AI 不只是一个音乐生成工具，也可以成为一个音乐学习助手。它能够帮助用户理解：

- 不同乐器之间如何配合；
- 节奏、和声和旋律如何共同塑造风格；
- 为什么某些编曲方式会让音乐更有推动力；
- 如何根据情绪和主题调整演奏方式。

---

## 五、项目实现概览

基于上述创意，本项目目前已实现了一个完整的 **ACE-Step Composer** — 一个基于 Gradio 的 AI 音乐生成工具。该工具打通了从用户 prompt 到最终音频文件的全流程。

> 🎬 Demo 视频见 GitHub: [https://github.com/E-Rail/ACEMusicWrapper](https://github.com/E-Rail/ACEMusicWrapper)

### 技术架构

```
[用户提示词]
       |
       |--> Bing 网页搜索 (music_context_search) ---------- 搜集歌曲 BPM、调性、风格等参考素材
       |--> 参考音频搜索 (wider_reference_audio) ----------- 网易云/QQ音乐/iTunes/Bing 多平台级联
       |
       v
[大语言模型 (OpenAI 兼容, 默认 DeepSeek)] --------------- 基于搜索素材生成 3 个结构化候选方案
       |
       v
3 个候选方案 (JSON)
       |--> normalize_candidate() --------------------------- 字段填充默认值、类型检查 (BPM/时长钳制到 120)
       |--> sanitize_source_candidates() ------------------- 检测翻唱/改编意图, 强制 cover 任务类型, 安全占位歌词
       |
       v
用户选择一个候选方案 -> Render
       |
       |--> resolve_reference() ---------------------------- 获取/压缩/编码参考音频 (ffprobe + ffmpeg)
       |--> ace_payload() ---------------------------------- 构建多模态 API payload (文本 + 可选 base64 音频)
       |
       v
[ACE Music Generation API]
       |
       |--> hosted_ace() (SSE 流式) ----------------------- 用于 api.acemusic.ai 云端 API
       |    - httpx.stream("POST") 接收 SSE 数据块
       |    - 心跳检测 (每 ~2s 的 "." chunk)
       |    - 实时进度显示 ("Generating… 5 heartbeat(s) (10s elapsed)")
       |
       |--> native_ace() (轮询式) -------------------------- 用于自部署 ACE 服务器
       |    - /release_task 创建任务 -> /query_result 轮询
       |    - POLL_INTERVAL=5s, MAX_POLLS=120 (最长 10 分钟)
       |
       v
输出: .mp3 文件 + 渲染日志
```

### 核心功能

| 模块 | 功能说明 |
|------|----------|
| **网页搜索** | 通过 Bing (cn/global) 和 Baidu 抓取歌曲相关信息 (风格、BPM、调性等), 为 LLM 提供真实世界数据背景 |
| **参考音频发现** | 多平台级联搜索: 提示词中的直接 URL → 网易云音乐 (歌曲/MV) → QQ音乐 → iTunes 跨国家预览 → Bing 音频链接 |
| **LLM 候选生成** | 严格 JSON 输出格式, 生成 3 个候选方案 (含标题、概念、prompt、歌词、BPM、调性、编曲计划、task_type 等) |
| **翻唱/改编检测** | 自动识别中文改编意图 (如 "孤勇者改成钢琴曲"), 提取源曲名称和改编目标, 强制 cover 任务类型 |
| **参考音频处理** | 使用 `ffprobe` 探测时长, `ffmpeg` 压缩为 96kbps 44.1kHz 立体声 mp3, base64 编码后嵌入 API 请求 |
| **SSE 流式渲染** | 使用 `httpx.stream()` 接收 ACE 的 SSE 流, 实时显示生成进度, 支持瞬态断线自动重试 |

### 关键设计决策

1. **JSON 强约束 LLM 协议**: 系统 prompt 要求 LLM 严格输出 `{"candidates":[...]}` 格式, `json_object()` 函数处理 markdown code fence 和截断 JSON。

2. **App 主导的翻唱策略**: 对于翻唱/改编类 prompt, app 在 `sanitize_source_candidates()` 中覆盖 LLM 生成的候选方案, 强制使用安全占位歌词 (避免著作权风险), 并将 task_type 设为 cover。

3. **多平台音频源集成**: 每个音乐平台有独立的 API 封装 (网易云 `netease_song_url`/`netease_mv_url`, QQ音乐 `qq_song_url`/`qq_mv_url`), 处理各自的认证和响应解析逻辑。

4. **SSE 流式渲染**: ACE 生成耗时较长 (20-120 秒), 使用 `httpx.stream()` 配合 `"stream": True` 接收 SSE 数据流。ACE 服务器在生成期间每约 2 秒发送一次心跳数据块 (content="."), 维持长连接活跃, 客户端实时解析并展示生成进度。

5. **双模式 ACE 调用**: 云端 API (`api.acemusic.ai`) 使用 SSE 流式渲染 (`hosted_ace`), 自部署 ACE 服务器使用轮询模式 (`native_ace`, `/release_task` + `/query_result`, `POLL_INTERVAL=5s`, 最长 10 分钟)。

### 数据流详解

**阶段一：信息搜集**

`music_context_search(prompt)` 和 `wider_reference_audio(prompt)` 并行执行:

- **搜索阶段** (`music_context_search`): 对 prompt 进行分词, 提取源曲名称和编辑目标, 生成多组搜索 query, 调用 `bing_search()` 和 `page_context_windows()` 抓取歌曲风格、BPM、编曲特点等文本描述, 去重后返回最多 8 条摘要。
- **参考音频阶段** (`wider_reference_audio`): 按优先级逐级尝试 — 直接从 prompt 中提取音频 URL → 搜索网易云音乐 (歌曲播放链接 / MV 播放链接) → 搜索 QQ 音乐 → 跨国家 iTunes 预览 → Bing 音频文件链接。找到的第一个可用 URL 即为 `audio_hint`。

**阶段二：LLM 候选生成**

`generate_candidates()` 将搜索摘要和参考音频提示传入 `llm_messages()`, 构建包含严格 JSON schema 和示例的系统 prompt。LLM 返回 3 个候选方案, 每个包含: title, concept, prompt, lyrics (带段落标记 [Intro]/[Verse]/[Chorus] 等), bpm, key_scale, time_signature, audio_duration, vocal_language, small_edit_instructions, composition_plan, ace_task_type。

`normalize_candidate()` 对 LLM 输出进行字段填充默认值和类型校验 (BPM/时长钳制到 120/240 上限)。`sanitize_source_candidates()` 根据 prompt 判断是否为翻唱/改编任务, 若是则覆盖候选方案: 强制 `ace_task_type = "cover"`, 替换歌词为安全占位, 补充源曲保留提示。

**阶段三：渲染准备**

用户选择候选方案后, `render()` 执行:

1. `resolve_reference()`: 从候选的 `reference_audio_url` 字段、prompt 中的直接 URL、或重新执行 `wider_reference_audio()` 获取参考音频 URL。`encode_reference()` 下载音频, `probe_audio_duration()` 用 `ffprobe` 探测时长, `compress_reference_audio()` 用 `ffmpeg` 压缩为 96kbps 44.1kHz 立体声 mp3 (可选截断到 `audio_duration`), 最后 base64 编码。

2. `ace_payload()`: 构建多模态 API payload。若无参考音频, `messages[].content` 为纯文本 (含 prompt、歌词、BPM、调性等)。若有参考音频, `content` 变为 `[{type: "text", ...}, {type: "input_audio", input_audio: {data: "<base64>", format: "mp3"}}]`。同时设置 `task_type`, `instruction`, `audio_cover_strength: 1.0` 等封面相关字段。

**阶段四：音乐生成**

`render()` 根据 `ace_base` 的 hostname 选择调用路径:

- `api.acemusic.ai` → `hosted_ace()`: SSE 流式生成器, 逐行解析 `data: <JSON>\n\n` 格式的 SSE chunk。识别三种类型: 心跳块 (content=".") 更新进度计数器; 文本块累积歌词/元信息; 音频块 (delta.audio[0].audio_url.url) 提取并保存为 mp3 文件。`save_audio_item()` 处理 data: URL 和普通 URL 两种格式。

- 其他 → `native_ace()`: 向 `/release_task` 提交任务获取 task_id, 每 5 秒轮询 `/query_result`, 直到任务完成或超时 (最多 120 次)。

**阶段五：输出与展示**

`render()` 是 Gradio 的生成器函数, 在每个阶段 yield `(log_markdown, audio_filepath_or_None)`。Gradio 实时刷新 UI, 显示进度日志 ("Generating… N heartbeat(s) (Xs elapsed)") 和最终的音频播放器。

### 技术栈

| 组件 | 技术选型 |
|------|----------|
| **Web 框架** | Gradio (gr.Blocks, gr.themes.Soft()) |
| **HTTP 客户端** | httpx (支持流式 SSE 请求) |
| **LLM 接口** | OpenAI 兼容 API (OpenRouter + DeepSeek V4 Flash 默认) |
| **音频处理** | ffprobe (时长探测), ffmpeg (压缩/转码) |
| **音乐生成** | ACE-Step API (`acemusic/acestep-v1.5-turbo`) |
| **搜索引擎** | Bing CN/Global HTML 抓取, Baidu 移动版 |
| **音乐平台** | 网易云音乐, QQ音乐, iTunes/Apple Music API |

### UI 布局

```
+---------------------------------------------------------------+
|  # ACE-Step Composer                                         |
+---------------------------------------------------------------+
|  左侧 (38%)                         |  右侧 (62%)              |
|                                     |                          |
|  [Keys 面板]                        |  [Candidates 面板]        |
|   LLM base URL                      |   选项卡1/2/3:            |
|   LLM API key                       |   显示候选方案的详细 Markdown |
|   ACE base URL                      |   (标题,概念,task_type,  |
|   ACE API key                       |   BPM,调性,歌词,编曲计划)  |
|                                     |                          |
|  [Compose 面板]                     |  [Progress 面板]          |
|   Prompt (多行输入)                  |   渲染日志 (实时更新)     |
|   LLM model (下拉框,支持自定义输入)    |   音频播放器              |
|   ACE model (下拉框)                |                          |
|   Candidate 选择器                  |                          |
|   [Fetch models] [Generate]         |                          |
|   [Render with ACE]                |                          |
+---------------------------------------------------------------+
```

### 当前项目的局限与后续方向

当前实现聚焦于**整曲生成**阶段, 尚未实现原始创意中的分轨编辑功能。后续可在以下方向扩展:

1. **分轨拆分**: 集成音频分离工具 (如 Spleeter/Demucs), 将 ACE 生成的完整音频拆分为鼓、贝斯、钢琴、人声等独立轨。

2. **局部重绘 (repaint)**: 利用 ACE 的 `repaint` task_type, 对特定段落/音轨进行局部修改, 而非整曲重生成。

3. **虚拟乐手人格系统**: 为不同乐手分配不同的系统 prompt 和修改策略, 实现原始创意中描述的 AI 鼓手/贝斯手/吉他手等角色。

4. **音乐教育功能**: 在修改音轨时输出编曲逻辑解释, 帮助用户理解乐器配合、和声走向等音乐理论知识。

---