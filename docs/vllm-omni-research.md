# vLLM-Omni 与 MiniCPM-o 4.5 调查

调查日期：2026-08-06。以下结论只依据 vLLM-Omni 官方仓库的 README、模型 recipe、部署配置、示例代码和全双工设计文档；链接均指向 `vllm-project/vllm-omni` 官方仓库。

## 结论摘要

- vLLM-Omni 已实现 `openbmb/MiniCPM-o-4_5` 的在线和离线推理，模型注册名为 `MiniCPMO45OmniForConditionalGeneration`。普通多模态 Chat 接受文本、图片、音频、视频，输出文本以及可选的 24 kHz 单声道语音。
- 推理是三阶段流水线：Thinker（多模态理解/文本）-> Talker（MiniCPMTTS codec）-> Code2Wav（Token2Wav 波形生成）。
- 在线服务采用 OpenAI-compatible `POST /v1/chat/completions`；官方同时提供 Gradio UI、离线 `Omni.generate` 示例和实验性的 Realtime 全双工音频运行时。
- 全双工不应与普通视频理解混为一谈：官方设计文档明确把原生 Duplex 标为 experimental，并明确“不宣称 video input 或 audio/video synchronization”。教学项目第一阶段应优先使用稳定的 Chat API；实时语音再单独评估 Duplex。

## 官方支持证据

### README 与模型列表

- [README.md](https://github.com/vllm-project/vllm-omni/blob/main/README.md) 将 vLLM-Omni 描述为支持 text/image/audio/video/action 的 omni-modality serving 框架，支持 OpenAI-compatible API、streaming 和 experimental full-duplex realtime audio；支持模型列表中包含 MiniCPM-o 4.5。
- [Supported models](https://github.com/vllm-project/vllm-omni/blob/main/docs/models/supported_models.md) 的 MiniCPM-o 4.5 条目对应 Hugging Face `openbmb/MiniCPM-o-4_5` 和 architecture `MiniCPMO45OmniForConditionalGeneration`。该条目标注 NVIDIA GPU 与 Ascend NPU 支持；未把 AMD 或 Intel 列为该模型的支持硬件。
- [MiniCPM-o 4.5 recipe](https://github.com/vllm-project/vllm-omni/blob/main/recipes/OpenBMB/MiniCPM-o-4_5.md) 明确给出任务边界：text/image/audio/video input -> text + 24 kHz speech；在线 `/v1/chat/completions`、Gradio，以及离线 `Omni.generate`。

## 启动与硬件

### 安装和依赖

- Linux、Python 3.10+ 是 recipe 的环境要求；官方 [online README](https://github.com/vllm-project/vllm-omni/blob/main/examples/online_serving/minicpmo/README.md) 还要求安装 MiniCPM talker 依赖：

  ```bash
  pip install stepaudio2-minicpmo
  ```

- `--trust-remote-code` 必须开启，因为 Hugging Face checkpoint 提供自定义 `MiniCPMO` 配置/模型类。
- Code2Wav 使用 MiniCPM 专用的 `stepaudio2-minicpmo`，不能替换成上游 `stepfun-ai/Step-Audio2` 的同名包；缺包会在首次请求时报错。

### 推荐启动命令

单 GPU 兼容布局（自动加载默认 deploy config）：

```bash
vllm serve openbmb/MiniCPM-o-4_5 \
  --omni \
  --trust-remote-code \
  --host 0.0.0.0 --port 8099
```

官方 recipe：[recipes/OpenBMB/MiniCPM-o-4_5.md](https://github.com/vllm-project/vllm-omni/blob/main/recipes/OpenBMB/MiniCPM-o-4_5.md)。

推荐吞吐布局为 2 GPU：Thinker 在 GPU 0，Talker 和 Code2Wav 共用 GPU 1：

```bash
vllm serve openbmb/MiniCPM-o-4_5 \
  --omni \
  --deploy-config vllm_omni/deploy/minicpmo_4_5_2gpu.yaml \
  --trust-remote-code \
  --host 0.0.0.0 --port 8099
```

还提供 3 GPU 和 8x RTX 4090 配置。8x4090 配置让 Thinker 在 GPU 0-3 做 TP=4，Talker 使用 GPU 4，Code2Wav 使用 GPU 5，GPU 6-7 空闲；其 `max_model_len` 默认限制为 4096，官方提示 8192 在 4090 上会 OOM。

默认单 GPU 配置的 stage memory budgets 是 Thinker 0.55、Talker 0.15、Code2Wav 0.15，默认每 stage `max_num_seqs: 4`；Stage 0/1 使用 CUDA Graph，Stage 2 仍 eager。单 GPU 主要用于降低硬件门槛，生产吞吐应采用多 GPU profile。

部署配置来源：[minicpmo_4_5.yaml](https://github.com/vllm-project/vllm-omni/blob/main/vllm_omni/deploy/minicpmo_4_5.yaml)、[minicpmo_4_5_2gpu.yaml](https://github.com/vllm-project/vllm-omni/blob/main/vllm_omni/deploy/minicpmo_4_5_2gpu.yaml)、[minicpmo_4_5_8x4090.yaml](https://github.com/vllm-project/vllm-omni/blob/main/vllm_omni/deploy/minicpmo_4_5_8x4090.yaml)。

## OpenAI Chat API

端点是 `POST http://<host>:8099/v1/chat/completions`。用户消息使用 OpenAI 多模态 `content` 数组：

```json
{
  "model": "openbmb/MiniCPM-o-4_5",
  "messages": [
    {"role": "user", "content": [
      {"type": "image_url", "image_url": {"url": "https://example/image.jpg"}},
      {"type": "audio_url", "audio_url": {"url": "https://example/audio.wav"}},
      {"type": "video_url", "video_url": {"url": "https://example/video.mp4"}},
      {"type": "text", "text": "请解释这些学习材料。"}
    ]}
  ],
  "modalities": ["text", "audio"],
  "chat_template_kwargs": {"use_tts_template": true}
}
```

字段形状和 URL/data-URL 编码逻辑见官方共享客户端：[openai_chat_completion_client_for_multimodal_generation.py](https://github.com/vllm-project/vllm-omni/blob/main/examples/online_serving/openai_chat_completion_client_for_multimodal_generation.py) 以及 MiniCPM 专用 curl 示例：[run_curl_multimodal_generation.sh](https://github.com/vllm-project/vllm-omni/blob/main/examples/online_serving/minicpmo/run_curl_multimodal_generation.sh)。图片、音频和视频也可以作为 `data:<mime>;base64,...` URL 发送。

### 输出与 TTS

- `modalities: ["text"]` 为纯文本路径，不需要 TTS 模板。
- `modalities: ["text", "audio"]` 触发文本+语音；`chat_template_kwargs.use_tts_template=true` 可显式要求 `<|tts_bos|>`，curl 要把该字段放在请求根部，OpenAI Python SDK 可通过 `extra_body={"chat_template_kwargs": {"use_tts_template": True}}` 传入。
- 文本和音频通常是不同的 `choices`：文本在某 choice 的 `message.content`，音频在另一 choice 的 `message.audio.data`。客户端必须查找实际含 `message.audio.data` 的 choice，不能假设 `choices[0]` 是音频。
- 音频是 Base64 编码的 24 kHz 单声道 WAV，官方在线 README 也说明流式输出会把音频 chunk 保存成 WAV。
- 参考音频/声音克隆通过首个 codec chunk 传递给 Code2Wav；请求结束后会清理临时 prompt WAV 和 prompt feature cache。该机制不是通用 `/v1/audio/speech` TTS API 的替代品。

### 视频限制

默认配置中的 `limit_mm_per_prompt.video.num_frames: 32` 只限制启动时 dummy profiling；如果需要限制实际 URL/文件视频采样，使用请求级 `media_io_kwargs.video.num_frames`。8x4090 配置还把 `max_model_len` 默认压到 4096。

## 示例入口

- [online serving README](https://github.com/vllm-project/vllm-omni/blob/main/examples/online_serving/minicpmo/README.md)：服务启动、curl、Python OpenAI client、Gradio、Realtime CLI/browser。
- [OpenAI Python client](https://github.com/vllm-project/vllm-omni/blob/main/examples/online_serving/minicpmo/openai_chat_completion_client_for_multimodal_generation.py)：支持 `text`、`use_image`、`use_audio`、`use_video`，支持 `--modalities text|text,audio` 和 `--stream`。
- [Gradio launcher](https://github.com/vllm-project/vllm-omni/blob/main/examples/online_serving/minicpmo/run_gradio_demo.sh)：默认连接 `http://localhost:8099/v1`，UI 端口 7862；远程浏览器要用 HTTPS 才能使用麦克风。
- [离线示例](https://github.com/vllm-project/vllm-omni/blob/main/examples/offline_inference/minicpmo/README.md)：支持 text、image、audio、video、两个 audio 和 audio+image+video 混合输入；默认 2 GPU，输出 WAV 为 24 kHz mono。

## 原生全双工边界

- [Experimental Full-Duplex README](https://github.com/vllm-project/vllm-omni/blob/main/vllm_omni/experimental/fullduplex/README.md) 和 [DESIGN.md](https://github.com/vllm-project/vllm-omni/blob/main/vllm_omni/experimental/fullduplex/DESIGN.md) 说明 MiniCPM 原生 Duplex 使用 `/v1/duplex` 或 `/v1/realtime?duplex=1`，是独立的实验性音频实时路径。
- [minicpmo_4_5_duplex.yaml](https://github.com/vllm-project/vllm-omni/blob/main/vllm_omni/deploy/minicpmo_4_5_duplex.yaml) 是单 GPU 的 experimental overlay，限制最多 2 个 live duplex sessions，并设置 idle TTL、断连宽限和恢复 replay TTL。
- 官方设计文档的明确不承诺项：确定性的 VAD 中断、生产级多会话 admission/fairness/capacity/failure recovery、有界长会话 KV，以及 **video input 或 audio/video synchronization**。因此当前 AI 教学产品应把普通 Chat 的视频问答和 Duplex 的实时语音辅导拆成两条能力路径，不能把 Duplex 当成已验证的实时视频课堂。
- 官方 Realtime CLI 示例：[realtime_duplex_demo.py](https://github.com/vllm-project/vllm-omni/blob/main/examples/online_serving/minicpmo/realtime_duplex_demo.py)，典型 URL 为 `ws://localhost:8099/v1/realtime?duplex=1`，需要输入 16 kHz mono PCM16 WAV 和参考音频；输出事件包含实时文本转写与 `response.audio.delta` 音频 chunk。

## 对本教学项目的直接启示

1. 第一阶段用稳定的 `/v1/chat/completions`：题目图片/扫描件、讲义 PDF 转图片、录音和短视频都可作为输入；响应可选择纯文本降低显存/延迟，或文本+24 kHz TTS 做讲解。
2. 课程/学生会话应在应用层保存历史消息，因为官方 Chat API 是一次请求一次完整多模态上下文；不要依赖普通 Chat 的跨请求隐式状态。
3. 语音克隆、连续麦克风和打断要作为明确的实验性功能开关；部署前必须用目标 GPU 做 Realtime Duplex 验证，不能仅凭普通 Chat 成功推断全双工可用。
4. 需要预估额外 `stepaudio2-minicpmo`、FFmpeg/音频依赖、2 GPU 推荐布局和 24 kHz WAV 播放链路；浏览器麦克风页面需 HTTPS 或 localhost 安全上下文。

