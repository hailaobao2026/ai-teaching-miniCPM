# Progress

## 2026-08-06

- 接入登录/注册/RBAC：JSON 用户会话存储、Bearer 鉴权、教学 API 默认需登录、管理员用户管理页；参考 video-platform 角色模型。
- 新增 tests/test_auth.py，回归 19 passed。

- 补全 `scripts/install_vllm_omni.sh`：按官方 CUDA 顺序用 uv 安装 vllm/vllm-omni/stepaudio2-minicpmo，支持 --write-lock/--from-lock、环境检查、导入校验。
- 完善 `requirements-gpu.txt` 注释与 `scripts/start_vllm_omni.sh` 启动参数；同步 README/部署文档。

- 完成 grill-me 需求访谈并确认需求基线。
- 核对 MiniCPM-o-Demo 的目录、WebSocket 协议、部署资源和前端模式。
- 发现当前工作区为空目录且不是 Git 仓库，计划从应用骨架开始。
- 完成 FastAPI 服务、Mock 教学编排、MiniCPM-o `/ws/chat` 适配器和三栏响应式教学工作区。
- 生成 `design-system/minicpm-math-coach/` 作为 UI 设计基线。
- 补齐本地记录查看/恢复面板，并加入 Docker 构建上下文隔离。
- 增加 30 题固定评测集与 Mock 教学护栏评测：30/30 提示不泄露答案，30/30 题可输出完整解析。
- 完成桌面/移动端无头浏览器渲染检查；Docker Compose 配置检查通过；初始测试 5/5、语法检查通过。
- 后台服务已启动于 `http://127.0.0.1:8081`，当前为 Mock 模式。
- 修复图片识题坐标标注：增加 JSON 解析、越界过滤和 canvas 叠加显示。
- 增加 `/api/lesson/stream` SSE，真实 Gateway 文本逐 chunk 转发，Mock 以短片段模拟，前端增量渲染后再显示结构化步骤。
- 扩展 Mock 至固定 30 题评测集，覆盖方程、因式分解、一次函数、平面几何和解析几何。
- 回归测试：`pytest 10/10`，Mock 评测 `30/30` 提示护栏、`30/30` 完整解析；8081 服务已重启并验证 SSE。
- 在 `docs/` 下新增需求设计、概要设计、详细设计、数据字典、接口设计和部署验证文档，并建立文档索引。
- 将真实模型适配从 MiniCPM-o-Demo Gateway/WebSocket 迁移为 vLLM-Omni 的 OpenAI `/v1/chat/completions` SSE 服务；新增 GPU 启动脚本与官方调研记录。
- 适配图片、浏览器录音和 TTS：输入录音转 16 kHz WAV，输出为 24 kHz WAV，并合并流式重复 WAV 头。
