# Progress

## 2026-08-16 语音输入与对话回放

- 真实浏览器模拟麦克风复现并确认：旧实现确实把“请根据我的语音继续讲解”写死为可见用户消息，但约 0.8 秒录音的 16 kHz 音频已正常上传。
- MiniCPM 多模态提示改为明确“学生通过附带语音输入并以语音内容为准”，保留真正的 `audio_url` 输入，不再把辅助指令描述成学生原话。
- `ChatMessage` 增加文本/语音类型、本地音频 URL 和时长；语音消息显示类型、时间、时长及播放/停止控制，文字消息保持原样。
- 语音 Blob URL 仅保留在当前浏览器会话，切题、重置或卸载时自动释放；模型请求继续使用重采样后的 Base64，不把大音频写入历史状态。
- 修复 60 秒自动停止可能读取旧 `recording` 状态的问题，录音停止改为检查 `MediaRecorder.state`。
- 验收：同一浏览器失败回路变绿，1440px/375px 无溢出且播放按钮达到 44px；`pytest 82/82`、前端构建与 `git diff --check` 通过。

## 2026-08-16 对话记录时间戳

- `ChatMessage` 新增 ISO `created_at`，学生发送和 AI 完成回复时分别记录真实时间。
- 对话记录显示消息数量、发送者和易读时间；今天/昨天使用相对日期，较早消息显示月日或年份，完整时间通过 `<time>` 语义和悬停标题保留。
- 对话顺序调整为学生提问到 AI 回复的自然时间线，新消息到达后自动滚动到最新记录。
- 验收：前端 TypeScript/Vite 构建与 `git diff --check` 通过；Playwright 在 1440px/375px 验证时间、顺序、滚动及无横向溢出。

## 2026-08-16 学生引导式教学交互

- 三阶段调整为“看懂题目 / 尝试一步 / 总结方法”，题面确认动作改为“题意正确，开始尝试”。
- 提示阶段将 `next_question` 提升为唯一的“轮到你”任务，隐藏锁定步骤，新增快捷求助、主动尝试和当前步骤反馈。
- 总结阶段展示完整步骤、最终答案、一句话总结入口及整题掌握反馈；朗读继续按需生成。
- MiniCPM hint 提示词限制每轮只推进一个小目标、三句话以内并只提出一个具体问题；真实回复末尾问题写入 `next_question`。
- 验收：`pytest 81/81`，前端构建和 `git diff --check` 通过；Playwright 检查 1440px/375px，无横向溢出，学生操作按钮均不低于 44px。

## 2026-08-16 按需语音优化

- 真实基线：默认 TTS 完整约 24.3 秒；`tts=false` 完整约 3.18 秒。
- 红灯测试：`test_lesson_request_defaults_to_text_only` 失败（实际 `tts=True`）；`test_speech_endpoint_generates_audio_without_lesson_context` 失败（接口 405）。
- 修复后首次提示真实复测：会话事件约 0.10 秒、首段文本约 1.40 秒、完整结束约 3.32 秒。
- 独立 `/api/speech` 真实复测：约 6.78 秒返回 24 kHz WAV；不携带教学历史和题图。
- 前端增加按需“朗读/取消/停止”控制；API 失败或 Mock 模式回退浏览器语音合成。
- 验收：`python3 -m pytest -q` 80 passed；前端 TypeScript/Vite 构建与 `git diff --check` 通过。

## 2026-08-16 中小学全科扩展

- 新增 `teaching/subjects.py`：统一九科学科代码、中文标签、教学侧重点和归一化规则。
- `LessonRequest`、`RecognizeResponse`、练习/反馈请求和 `TeachingSession` 增加 `subject`；默认数学兼容旧请求，学科不同时自动隔离会话。
- MiniCPM-o 系统提示词按学科切换；数学保留原确定性 Mock，其他八科提供学科化通用提示、步骤和练习推荐；示例题扩展到九科。
- 前端配置加载学科目录并提供学科选择器，识题、SSE 讲解、反馈和练习推荐携带当前学科；品牌和输入提示更新为全科。
- 年级目录从初一至高三扩展为小学一年级至高中三年级。
- 全科回归：`python3 -m pytest -q` 全量通过；`npm --prefix frontend run build` 通过。

## 2026-08-16 多题图片识别修复

- 已启动诊断；UUID 图片未在仓库中找到，正在以多题长图/API夹具建立红灯测试。
- 红灯命令：`python3 -m pytest -q tests/test_api.py::test_recognition_parser_splits_numbered_problems_without_spaces`；修复前稳定失败，实际 1 项、期望 3 项。
- API 红灯命令：`python3 -m pytest -q tests/test_api.py::test_standard_screenshot_retries_tiles_when_whole_image_returns_one_problem`；修复前 720x1280 截图只调用整图识别一次并返回 1 项。
- 修复后两个红灯与既有 PDF/长图多题回归共 4 项通过；完整后端回归 74/74 通过，前端 TypeScript/Vite 生产构建及 `git diff --check` 通过。

## 2026-08-15 比赛交付包

- 新增真实模型评测脚本、比赛账号一键重置脚本、HTTPS Nginx 模板与公网验证脚本、3 分钟演示分镜。
- 真实 MiniCPM-o 30 题评测：请求错误 0/30，提示护栏 30/30；保守判定 24/30，人工复核 6 个格式差异后语义正确 30/30。完整解析 p50/p95 为 17.60s/77.50s，首事件 p50/p95 为 0.88s/16.97s。
- 真实多模态探测：文本问答成功、图片识题成功、TTS 返回 24kHz WAV。
- 本地 App 真实链路复测：比赛账号登录 200、图片识题 200/source=minicpm/degraded=false、确认后 SSE 讲解 200/source=minicpm；识题 session_id 与讲解 session_id 一致，题图贯穿链路通过。
- 最终回归：`python3 -m pytest -q` 58/58 通过；`frontend npm run build` TypeScript/Vite 构建通过；`git diff --check` 通过。

## 2026-08-15 代码审查修复

- 发现当前 WSL/Windows 挂载盘忽略 `chmod`，`.competition.env` 可能保持 `777`。重置脚本现在写入后校验 owner-only 权限，无效则删除密码并失败；本机改用 `/tmp/ai-teaching-competition.env`，实测权限 `600`。
- 真实评测的多模态探针增加异常捕获，避免 TTS/图片探测异常导致 30 题结果无法写盘。
- HTTPS 验证新增 HSTS 检查，并要求 SSE 最终 lesson 来源为 `minicpm`，避免 Mock 降级被误判为真实链路可用。
- 前端“移除图片”在确认题面前会删除服务端识题会话；确认后仅隐藏预览，保留题图讲解上下文。
- 修正 Docker 比赛密码复制说明和容器端口文档；原始真实评测 JSON 不再被 Git 忽略，且已扫描未包含 API Key、密码或 token。

## 2026-08-15 文档同步

- 已将摄像头拍题、题图短期会话、真实识题显式降级、TTS 打断、比赛评测与部署能力同步到 `docs/01` 至 `docs/07`。
- 数据字典补充 `TeachingSession.image_bytes/image_mime`、30 分钟生命周期和前端运行时状态语义。
- 部署文档更新 58 项测试基线、比赛账号重置、摄像头/语音浏览器验收、真实评测结果和单实例内存边界。
- 文档索引同步当前主流程、容器端口和真实模型评测摘要；本地 Markdown 链接检查与 `git diff --check` 通过。

## 2026-08-15 README 同步

- README 更新为 v0.3.0，补充参赛定位、摄像头拍题、题图贯穿、TTS 打断、比赛交付、真实模型 30 题评测和 HTTPS/账号重置命令。
- 项目结构加入 `deploy/` 与 `eval/`，测试基线更新为 58 项，路线图移除已完成的真实评测事项。
- 清理误留的明文管理员密码示例；README 本地链接检查、敏感信息扫描和 `git diff --check` 通过。

## 2026-08-15 参赛强化

- 对照创新应用赛道要求确认：项目可运行、可展示，教育场景强；短板是题图未贯穿讲解、真实模式降级不可见、视觉入口偏上传、语音不可打断。
- 开始实施参赛强化：优先 P0（题图会话缓存与真实模式显式反馈），同步推进摄像头拍题和 TTS 打断。
- 已实现 `TeachingSession` 30 分钟内存题图缓存；识题返回 `session_id/degraded/degraded_reason`；题面确认后 `/api/lesson` 与 `/api/lesson/stream` 均继续把原图传给 MiniCPM-o。
- 前端已支持摄像头实时取景拍照、显式降级提示、TTS 播放状态与一键打断；切换题目/重置会同步释放摄像头、预览 URL 和音频。
- 新增 3 个 API/会话回归：编辑题面后题图不丢失、真实识题失败可降级并保留题图重试、30 分钟过期清理。
- 完整验收：`python3 -m pytest -q` 58/58 通过；`frontend npm run build` TypeScript 检查与 Vite 构建通过；Uvicorn 冒烟中 `/`、静态 JS/CSS 与 `/api/config` 均 200。

## 2026-08-15

- 默认接入远程 MiniCPM-o 4.5 端点 `https://minicpm45.duckcloud.fun/v1`，Docker 与文档同步更新；显式置空 `VLLM_OMNI_URL` 仍可回到 Mock。
- 修复远程流式 TTS 音频解析、思考输出抑制、教学阶段护栏和浏览器 WebM 录音转 16 kHz Float32 PCM。
- 实测通过：文本提示、SSE 完整解析、图片识题、音频输入提示、TTS WAV；应用 `/api/health`、`/api/config`、`/api/lesson`、`/api/lesson/stream`、`/api/recognize` 均为 MiniCPM 来源。
- 回归：`pytest 31/31`、前端 `npm run build`、静态 JS 语法检查、Docker Compose 配置解析通过。
- 新增 `config/minicpm.json` 与 `teaching/model_config.py`；主应用、验证客户端、Docker 均从同一配置读取。更换地址/模型只需修改 JSON 并重启；回归 `pytest 32/32`。
- 完成第二轮安全修复：登录响应不再暴露 token、会话哈希存储、模型 API Key、60 秒音频限制、Pillow 图片校验、强密码、文档默认关闭、本地 Tailwind/CSP、可信代理限流与 MySQL 本地绑定。最终回归 `pytest 42/42`，前端构建和真实模型请求通过。
- 补齐端到端模型鉴权配置：生成入 `.env` 的共享 API Key，vLLM 公网启动必须 `--api-key`，客户端自动 Bearer；Compose 默认 Secure Cookie/HSTS。实测当前远端匿名仍为 200，需要用该密钥重启远端服务后才生效；本地回归 `pytest 44/44`。
- 同步七份项目文档：模型配置、HttpOnly Cookie、会话哈希与所有者隔离、图片/音频限制、接口响应、API Key、HTTPS/HSTS、可信代理、Compose 与测试基线全部与当前实现一致。复验 `pytest 44/44`、Mock 评测 30/30、前端 TypeScript/Vite 构建通过。
- 修复开发模式登录 `Not Found`：发现 Vite `3000` 代理误指向被 `sub2api` 占用的 `8080`，本项目 Compose 后端在 `8089`；Vite 代理默认改为 `8089`，支持 `MATH_COACH_API_TARGET` 覆盖。实测登录请求从 404 变为预期 401/200 认证链路，前端构建与 `pytest 44/44` 通过。
- 用户本地后端改为 `8081`：Vite 现在从根目录 `.env` 读取 `MATH_COACH_API_TARGET`，无需每次手工注入环境变量；已验证 `3000 -> 8081` 代理连接 MiniCPM 模式，登录路由返回预期 401/200。

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
## 2026-08-15 错题驱动学习闭环

- 已确认产品决策：学生自主学习、错题驱动、最终答案等价判定、三次递进提示、答对一次掌握。
- 已检查现有实现：`notebook_items` 缺少尝试历史；前端已有错题列表和同类推荐，但没有重练提交流。
- 迁移策略：新增独立 `notebook_attempts` 表，避免破坏既有 `notebook_items` 数据。
- 已实现 `teaching/answers.py`、尝试历史表、重练/掌握 API、学生默认进入错题重练页和知识点聚合 UI。
- 回归结果：`pytest 48/48`，前端 `npm run build`、`git diff --check` 通过。
- 旧 SQLite 数据库已自动新增 `notebook_attempts`；真实服务冒烟验证登录、错题反馈、答案等价、掌握列表和清理均返回 200。

## 2026-08-15 PDF 上传预览

- 前端文件选择支持 PNG/JPEG/WebP/PDF；PDF 使用本地 Blob URL 和原生 iframe 预览，并在移除/重选/卸载时释放对象。
- 后端校验 PDF `%PDF-` 签名、8 MB 大小、1-20 页和页面尺寸；使用 pypdfium2 渲染首页为 PNG 后进入既有 MiniCPM 图片识别链路。
- CSP 增加 `frame-src 'self' blob:`，继续禁止 object-src 和外部脚本。
- 浏览器实测：登录后上传 PDF，预览 iframe 可见；全量回归 `pytest 55/55`、前端构建和 `git diff --check` 通过。
