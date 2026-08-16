# MiniCPM-o-4_5 全模态 vLLM-Omni 客户端

针对 `vllm serve` 启动的 MiniCPM-o-4_5 全模态服务的验证客户端代码，
参考 [OpenBMB/MiniCPM-o-Demo](https://github.com/OpenBMB/MiniCPM-o-Demo)
与 vLLM-Omni 官方示例编写。

## 1. 远程服务配置

默认 OpenAI 兼容地址与模型来自项目根目录的 `config/minicpm.json`，当前值为：

```text
BASE_URL = https://minicpm45.duckcloud.fun/v1
MODEL    = /tmp/pretrainmodel/MiniCPM-o-4_5
```

如需覆盖，可在启动前设置环境变量，或给脚本传参：

```bash
export MINICPM_BASE_URL="https://minicpm45.duckcloud.fun/v1"
export MINICPM_MODEL="/tmp/pretrainmodel/MiniCPM-o-4_5"
python chat_client.py --base-url "$MINICPM_BASE_URL" --model "$MINICPM_MODEL"
```

若服务后续启用鉴权，可设置 `MINICPM_API_KEY`；当前服务接受 `EMPTY` 占位密钥。
本地 vLLM 服务仍可通过 `--base-url http://127.0.0.1:8099/v1`，或兼容旧参数
`--host 127.0.0.1 --port 8099` 访问。

## 2. 客户端依赖与准备

```bash
cd tests/miniCPMclient
pip install -r requirements.txt
# 可选：克隆参考 Demo（已提供示例视频/参考音频路径，可自行替换）
git clone --depth 1 https://github.com/OpenBMB/MiniCPM-o-Demo /tmp/MiniCPM-o-Demo
```

## 3. 场景与用法

| 场景 | 脚本 | 说明 |
|---|---|---|
| 聊天推理 | `chat_client.py` | 纯文本问答，非流式 |
| 流式推理 | `streaming_client.py` | 文本逐字流式；`--audio` 语音分片流式 |
| 半双工实时语音 | `half_duplex_voice_client.py` | Realtime WebSocket，语音进语音出 |
| 语音与音频模式 | `audio_client.py` | 音频输入 -> 文本+语音输出 |
| 单图对话 | `single_image_client.py` | 单张图片理解 |
| 多图对话 | `multi_image_client.py` | 多张图片比较/联合理解 |
| 视频对话 | `video_client.py` | 视频理解 |

### 3.1 聊天推理（文本，非流式）

```bash
python chat_client.py --prompt "你好，介绍一下你自己"
```

### 3.2 流式推理

```bash
# 纯文本流式
python streaming_client.py --prompt "写一首关于夏天的五言绝句"
# 文本 + 语音分片流式（audio_chunk_*.wav 自动合并为 audio_stream.wav）
python streaming_client.py --prompt "请用语音说：你好，世界" --audio
```

### 3.3 半双工实时语音对话（Realtime WebSocket）

一问一答：输入 16kHz PCM16 mono WAV（其他采样率自动重采样），
模型流式返回文字转写与 24kHz 语音，输出保存到 `output_realtime/`。

> 注意：脚本在 `tests/miniCPMclient` 目录下，请先切换到该目录再运行；
> 否则会报 `python: can't open file 'half_duplex_voice_client.py'`。

```bash
cd tests/miniCPMclient
# 准备测试音频（本地已有资源，未克隆 /tmp/MiniCPM-o-Demo 也能跑）
cp /home/vllm-omni/tests/assets/minicpmo_4_5/response_required_16k.wav single_turn.wav
cp /home/vllm-omni/tests/assets/minicpmo_4_5/response_required_16k.wav q1.wav
cp /tmp/pretrainmodel/MiniCPM-o-4_5/assets/haimianbaobao.wav q2.wav
cp output/audio_stream.wav q3.wav

# 单轮对话
python half_duplex_voice_client.py --input-wav ./single_turn.wav

# 多轮对话（同一连接内连续多段音频）
python half_duplex_voice_client.py \
    --input-wav ./q1.wav --input-wav ./q2.wav --input-wav ./q3.wav \
    --verbose
```

协议事件流（客户端 -> 服务端）：
`session.update` -> `input_audio_buffer.append`（base64 PCM16@16k）
-> `input_audio_buffer.commit`（开始生成）-> `input_audio_buffer.commit(final=true)`。

服务端事件：`transcription.delta`（回复文字）、`response.audio.delta`
（base64 PCM16@24k 语音分片）、`transcription.done`、`response.audio.done`。

> 半双工 = 说完一轮等一轮回复；如需全双工（边说边听、可打断），需用
> `minicpmo_4_5_duplex.yaml` 部署并连接 `ws://.../v1/realtime?duplex=1`
> （见 vllm-omni `examples/online_serving/minicpmo/realtime_duplex_demo.py`）。

> 服务端限制：OpenAI 风格 `/v1/realtime`（半双工）要求模型实现 vLLM 的
> `SupportsRealtime` 接口（`buffer_realtime_audio`）。当前 vllm-omni 的
> MiniCPM-o-4.5 尚未实现，提交音频后服务端会返回
> `processing_error`（`MiniCPMO45OmniForConditionalGeneration has no
> attribute 'buffer_realtime_audio'`）。MiniCPM-o-4.5 的实时语音验证请改用
> duplex 部署（`vllm_omni/deploy/minicpmo_4_5_duplex.yaml`）与官方示例
> `vllm-omni/examples/online_serving/minicpmo/realtime_duplex_demo.py`。

### 3.4 语音与音频模式（音频输入 -> 文本 + 语音输出）

```bash
# 非流式：音频理解 + 语音回复（保存 audio_0.wav）
python audio_client.py \
    --audio /tmp/MiniCPM-o-Demo/assets/ref_audio/ref_en_dlc_1.wav \
    --prompt "这段音频说了什么？请用语音回答"
# 流式
python audio_client.py --audio ./question.ogg --stream
```

### 3.5 单图对话

```bash
python single_image_client.py --image ./cat.png --prompt "描述这张图片"
# 本地文件自动转 base64 data URL；http(s) URL 直接使用
python single_image_client.py --image https://.../photo.jpg --audio
```

### 3.6 多图对话

```bash
python multi_image_client.py -i ./a.jpg -i ./b.jpg \
    --prompt "这两张图片有什么异同？"
```

### 3.7 视频对话

```bash
python video_client.py \
    --video /tmp/MiniCPM-o-Demo/assets/samples/compile.mp4 \
    --prompt "这个视频里发生了什么？"
python video_client.py --video https://.../demo.mp4 --audio
```

## 4. 请求格式要点（OpenAI 兼容 /v1/chat/completions）

- 多模态内容：`image_url` / `audio_url` / `video_url` + `text` 混合在
  `messages[].content` 中，本地文件用 `data:<mime>;base64,...`。
- 输出模态：`modalities=["text"]` 或 `["text","audio"]`。
- 语音模板：`extra_body={"chat_template_kwargs": {"use_tts_template": true}}`。
- 非流式语音：`choice.message.audio.data`（base64 WAV，24kHz）。
- 流式：每个 chunk 带 `modality` 字段，`text` 为文本增量，
  `audio` 的 `delta.content` 为 base64 WAV 分片。

## 5. 目录结构

```
tests/miniCPMclient/
├── config.py                     # 服务地址/模型/默认媒体/提示词
├── utils.py                      # 媒体编码、音频重采样、响应打印与保存
├── chat_client.py                # 聊天推理
├── streaming_client.py           # 流式推理
├── half_duplex_voice_client.py   # 半双工实时语音对话
├── audio_client.py               # 语音与音频模式
├── single_image_client.py        # 单图对话
├── multi_image_client.py         # 多图对话
├── video_client.py               # 视频对话
├── requirements.txt
└── README.md
```
