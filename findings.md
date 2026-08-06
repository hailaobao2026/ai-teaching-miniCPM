# Findings

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

## GPU dependency install

- vLLM-Omni 0.26 CUDA 官方顺序：uv pip install vllm==0.26.0 --torch-backend=auto，再装 vllm-omni==0.26.0，MiniCPM-o TTS 再装 stepaudio2-minicpmo。
- 不要 pin torch/torchaudio；Python 3.12；锁文件按主机 CUDA 生成且不可跨机复用。
- Code2Wav 必须使用 stepaudio2-minicpmo，不能替换成上游 step-audio2。

