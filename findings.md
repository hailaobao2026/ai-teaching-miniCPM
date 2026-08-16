# Findings

## 2026-08-16 语音输入与回放

- 浏览器模拟麦克风稳定复现：录音后历史出现固定文本“请根据我的语音继续讲解”，且没有语音播放控件。
- 网络捕获证明语音实际已上传：约 0.8 秒模拟录音产生 71,680 个 Base64 字符，以 16 kHz 随 `/api/lesson/stream` 发送；问题不是录音缺失。
- 根因一：`sendLesson` 会把 `userMessage` 自动写入历史，语音调用传入的模型辅助提示因此被误显示成用户输入。
- 根因二：编码完成后原始录音 Blob 被释放，`ChatMessage` 也没有输入类型、音频 URL 或时长字段，前端无法区分或回放语音消息。
- 回放应保留浏览器本地 Blob URL，而传给模型的 Float32 Base64 继续只用于请求；重置题目或组件卸载时需要统一释放 URL。
- 修复后的同一浏览器回路结果：固定文案数量 0、播放控件 1、音频请求仍超过 66,000 个 Base64 字符；播放按钮可切换到停止状态。
- 375px 实测对话面板宽 343px，无横向溢出，语音播放按钮高度不低于 44px。

## 2026-08-16 对话记录时间戳

- 当前 `ChatMessage` 只有 `role/text`，消息时间必须在 `appendHistory` 时生成并保存，不能在渲染时临时生成。
- 原对话列表按最新消息优先排列，导致 AI 回复显示在学生问题上方；改为按发生顺序排列，并在新消息到达时滚动到最新记录。
- 时间戳使用低干扰的消息头元信息，今天/昨天显示相对日期，较早消息显示月日和时间。
- 本次只增强当前教学会话记录，不扩大为服务端永久聊天归档；本地保存记录已有独立 `saved_at`。

## 2026-08-16 引导式教学交互

- 原交互把 `lesson.next_question` 降格为讲解尾注，同时展示锁定的未来步骤，学生不容易判断当轮应该做什么。
- 教学回复正文可能自带问句，而 `next_question` 又是另一句；提示态需要把正文末尾问句收拢，只保留“轮到你”中的一个明确任务。
- 完整解析仍应由学生主动触发，但触发后需要进入总结和掌握反馈，而不是继续沿用提示阶段的步骤反馈。
- 375px 实测页面宽度与视口均为 375px，教学面板宽 343px；快捷动作、步骤反馈和输入区没有溢出，按钮触控高度均达到 44px。

## 2026-08-16 首次提示延迟

- 当前前端讲解请求未显式发送 `tts`，后端 `LessonRequest.tts` 默认 `True`，因此确认题面会请求 `modalities=["text", "audio"]`。
- 真实对照：默认 TTS 会话事件约 0.09 秒、首段文本约 4.4 秒、完整结束约 24.3 秒；`tts=false` 时首段文本约 1.27 秒、完整结束约 3.18 秒。
- 独立朗读 API 应只接收已生成文本，不复用教学会话历史、不携带题图、不提交新的 assistant 内容，避免重复推理和上下文污染。

## 2026-08-16 中小学全科扩展

- 数学假设集中在 Mock 解析器、MiniCPM 系统提示词、练习题库和前端品牌文案；通过 `subject` 作为统一请求维度扩展，避免复制九套 API。
- `subject` 代码：`chinese`、`math`、`english`、`physics`、`chemistry`、`politics`、`history`、`geography`、`biology`；未知代码归一化为数学，Pydantic 请求默认数学。
- 非数学 Mock 不伪造具体事实答案，而是提供提取信息、建立依据、组织答案三步通用引导；真实 MiniCPM 模式注入各科教学侧重点。
- 练习题库当前仍是数学固定 30 题；非数学推荐返回学科化通用巩固题，后续可按教材版本接入各科题库。

## 2026-08-16 多题图片识别

- 用户报告 UUID 图片仅识别第一条；该图片当前不在仓库文件树中，先用同类整页多题夹具复现真实 `/api/recognize` 链路。
- 工作区已有未提交的 `problems[]`、题号切分、PDF 多页聚合及密集长图重试实现，需要先验证边界，避免覆盖已有改动。
- 已确定解析根因：`_split_numbered_problems` 要求题号标点后存在空格，常见 OCR 文本 `1、题目`、`2．题目`、`3.题目` 因此全部合并成一个候选；前端候选卡只预览两行，呈现为只识别第一条。
- 已确定第二个根因：分块重试要求原图最长边严格大于默认 1280；常见 720x1280 截图在整图只返回第一题时不会触发重试，API 因而只能返回一个候选。

## 2026-08-15 参赛差距

- `LessonRequest` 不携带题图；`MiniCPMClient` 虽支持 `image_bytes`，但 `/api/lesson` 和 `/api/lesson/stream` 当前没有传入，导致几何/函数题图在确认后丢失。
- `/api/recognize` 在 MiniCPM 识题异常时记录日志并返回 Mock 结果，前端无法区分真实失败，比赛演示存在误导风险。
- 前端已有 `getUserMedia` 音频经验与图片对象 URL，可通过 Canvas 捕获摄像头帧并复用上传识别链路。
- 现有语音为按住录音 + SSE + TTS；适合先做播放可打断、状态明确，暂不引入不稳定全双工协议。
- 真实 `MiniCPMClient.chat` 的前四个参数按位置传递，测试替身需要同时兼容位置参数与关键字参数。
- WSL/Windows 挂载工作区可能忽略 POSIX `chmod`，生成秘密文件后必须复查实际权限，不能信任 `chmod` 调用本身。

## vLLM-Omni MiniCPM-o 4.5 migration

- 真实推理服务已切换为 vLLM-Omni 的 OpenAI-compatible `POST /v1/chat/completions`，模型为 `openbmb/MiniCPM-o-4_5`。
- 服务启动命令为 `vllm serve openbmb/MiniCPM-o-4_5 --omni --trust-remote-code --host 0.0.0.0 --port 8099`；MiniCPM-o TTS 需额外安装 `stepaudio2-minicpmo`。
- 图像和音频使用 OpenAI 多模态 Data URL；浏览器 16 kHz Float32 PCM 由适配器转换为单声道 PCM16 WAV。
- TTS 请求使用 `modalities=["text", "audio"]` 与 `chat_template_kwargs.use_tts_template=true`；输出为 Base64 24 kHz WAV。
- 全双工 `/v1/realtime` 是 vLLM-Omni 的实验性路径，不纳入当前按轮次课堂 MVP。

## Upstream MiniCPM-o-Demo

- 官方仓库：`OpenBMB/MiniCPM-o-Demo`，主干已核对。
- 架构：Browser -> Gateway (HTTPS/WSS) -> Worker Pool -> PyTorch Backend；每个 Worker 独占一张 GPU。
- Turn-based Chat WebSocket：`/ws/chat`，请求包含 `messages`、`streaming`、`generation`、`tts`、`image`、`omni_mode`、`enable_thinking`；响应为 `prefill_done -> chunk* -> done`，chunk 可含 `text_delta` 和音频数据。
- 输入支持文本、图像、音频和视频；MVP 只启用图片/文本/按轮次音频。
- 依赖约束：Linux、Python 3.10（Docker 可不同）、NVIDIA GPU 建议显存 >28GB；单 Worker 运行约 21.5GB；需要 CUDA/PyTorch 2.8 和 FFmpeg。
- 官方前端位于 `static/`，现有模式包括 `/turnbased`、`/omni`、`/audio_duplex` 等。
- 上游 `core/capabilities.py` 的视频能力声明与 Chat API 文档存在不一致；实现以实际 Chat API 文档和后端行为为准。

## Product baseline

- 初中数学常见代数、函数、因式分解、平面/解析几何。
- 题面识别后必须让学生确认/修改。
- 默认苏格拉底式提示，支持切换完整解析；模型不确定时必须明确标记。
- 首版桌面浏览器、匿名、本地学习记录；固定题集评测识题/步骤/教学闭环/延迟。

## Review follow-ups

- 语音输入已补为浏览器录音 -> 16 kHz PCM Float32 Base64 -> 上游 Chat API；TTS chunk 先解码 PCM 再合并，避免 Base64 直接拼接损坏。
- 教学会话由后端内存编排器持有，浏览器只发送匿名 `session_id`；重新开始时调用删除接口。
- 图片上传限制为 PNG/JPEG/WebP 且最大 8 MB；上游 WebSocket 连接有打开和总时长超时。
- 本地记录剥离 TTS 音频并处理 localStorage 配额/损坏数据。
- 图片识题 prompt 现在要求返回题面和归一化坐标；前端以 canvas 叠加标注，坐标缺失或越界时仅显示原图。
- `/api/lesson/stream` 通过 SSE 转发 MiniCPM-o 文本增量；Mock 也按短片段输出，结束事件携带结构化步骤和音频。
- Mock 固定评测集已覆盖 30/30 题，提示阶段不返回最终答案。

## Remote MiniCPM-o 4.5 verification (2026-08-15)

- 远程 OpenAI 兼容端点为 `https://minicpm45.duckcloud.fun/v1`，`/v1/models` 返回模型 `/tmp/pretrainmodel/MiniCPM-o-4_5`。
- 真实流式 TTS 的音频分片位于 `choices[].delta.content`，并由顶层 `modality: "audio"` 标记；合并后是 24 kHz 单声道 16-bit WAV。
- `chat_template_kwargs.enable_thinking=false` 可稳定去掉 `<think>` 输出；教学提示阶段需要显式注入 stage 护栏，避免语音追问时泄露答案。
- 已实测：文本提示、完整解析 SSE、图片识题 JSON、音频输入提示、TTS；`2x+5=17` 完整解析得到 `x=6`，提示阶段未泄露答案。
- 模型地址与模型名的常规配置来源已收敛为 `config/minicpm.json`；`VLLM_OMNI_URL`、`MINICPM_MODEL` 仅保留为测试/特殊本地部署的显式覆盖。

## Security review follow-up

- 登录/注册不再向响应体返回长期 Bearer token，浏览器仅使用 HttpOnly Cookie；服务端只保存会话 token 的 SHA-256 哈希。
- `config/minicpm.json` 支持可选 `api_key`，远端启用鉴权时请求自动携带 Authorization Bearer。
- 音频输入限制为 60 秒、严格 Base64 校验；前端录音限时并分块转 Base64。
- 图片上传增加 MIME、文件签名、Pillow 格式/尺寸/像素校验；管理端重置密码使用强度规则并在敏感变更后撤销会话。
- FastAPI 文档默认关闭；MySQL 可选端口仅绑定宿主 127.0.0.1；前端 Tailwind 改为本地构建，CSP 移除脚本 unsafe-inline 和 CDN 依赖。
- vLLM 启动脚本对非回环监听强制 `VLLM_API_KEY` 并自动传递 `--api-key`；本地 `.env` 已保存客户端/服务端共享密钥且被 Git 忽略。Compose 默认 `Secure Cookie=true` 和 `HSTS=true`。

## Documentation synchronization (2026-08-15)

- `docs/01` 至 `docs/06` 与索引已同步当前实现：模型配置以 `config/minicpm.json` 为默认来源，环境变量仅作显式覆盖。

## Retry learning decisions (2026-08-15)

- 学生端下一阶段主线是自主学习，错题视图优先呈现待重练错题。
- MVP 判定采用 SymPy 规则化数学等价，支持归一化、分数/小数、根式、坐标、多项式和常见表达。
- 题源固定为 `eval/questions.json` 与现有示例题；同类推荐排除原题和已有错题。
- 完整尝试历史单独建模，错题主记录保留 `helpful` 作为掌握汇总状态。
- 浏览器认证统一描述为 HttpOnly Cookie；Bearer 仅作为脚本/测试兼容，不再出现在登录/注册 JSON 响应。
- 教学、错题本会话均按 `owner_id` 隔离；服务端登录会话只保存 SHA-256 哈希。
- 上传/音频/错误码、远端 API Key 启用步骤、HTTPS/HSTS 与可信代理限流策略已补齐。
- 文档验证基线更新为 `pytest 44/44`、Mock 评测 30/30、React 构建通过。

## GPU dependency install

- vLLM-Omni 0.26 CUDA 官方顺序：uv pip install vllm==0.26.0 --torch-backend=auto，再装 vllm-omni==0.26.0，MiniCPM-o TTS 再装 stepaudio2-minicpmo。
- 不要 pin torch/torchaudio；Python 3.12；锁文件按主机 CUDA 生成且不可跨机复用。
- Code2Wav 必须使用 stepaudio2-minicpmo，不能替换成上游 step-audio2。
