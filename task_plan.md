# MiniCPM-o 4.5 AI 教学项目

## Goal

基于 MiniCPM-o-Demo 的交互参考及 vLLM-Omni 托管的 `openbmb/MiniCPM-o-4_5`，交付一个中文初中数学全模态教学 Web Demo：拍题、题面确认、提示式分步讲解、语音/文字追问、本地学习记录和固定题集评测入口。

## Phases

1. [complete] 建立应用骨架与需求记录
2. [complete] 实现教学工作区与本地 Mock/真实后端适配
3. [complete] 接入 MiniCPM-o Chat WebSocket 协议
4. [complete] 增加评测数据与可靠性边界
5. [complete] 本地启动、测试与交付文档
6. [complete] 修复审查发现的图片标注、流式渲染和 Mock 覆盖遗漏
7. [complete] 输出项目需求、架构、详细设计、数据字典和部署文档
8. [complete] 用 vLLM-Omni OpenAI API 替换 Gateway/WebSocket 模型适配，并补齐 GPU 启动配置
9. [complete] 接入远程 MiniCPM-o 4.5 服务并完成文本、图片、语音输入、TTS、SSE 与教学护栏实测
10. [complete] 将远程地址与模型名提取到 config/minicpm.json 单一配置文件
11. [complete] 安全审查修复：会话哈希、HttpOnly-only 登录、模型鉴权、输入限制、图片校验与部署收敛
12. [complete] 启用端到端模型 API Key 配置与生产 Secure Cookie/HSTS 默认
13. [complete] 同步需求、概要、详细设计、数据字典、接口、部署与文档索引
14. [complete] 实现学生错题驱动重练闭环
15. [complete] 支持 PDF 上传、浏览器预览与首页图片化识别
14. [complete] 实现学生错题驱动重练闭环
15. [complete] 支持 PDF 上传、浏览器预览与首页图片化识别
16. [complete] 扩展为中小学全科教学
17. [complete] 优化首次提示延迟：文字优先、语音按需生成

## 全科扩展目标

- 支持语文、数学、英语、物理、化学、政治、历史、地理、生物九个学科。
- 建立后端统一学科目录与 `subject` 请求契约，识题、讲解、流式讲解和练习推荐均能携带学科。
- 数学保留现有确定性 Mock 解析与错题等价判定；其他学科提供通用教学 Mock，并在真实 MiniCPM 模式下注入学科专属教学约束。
- 前端提供学科选择、学科化输入提示、学科化标题与运行时状态，并保持旧数学请求兼容。
- 增加后端和前端构建回归，更新项目文档中的产品定位。

## 全科扩展验收

- [complete] 新增九科学科目录、学科化模型提示和小学至高中年级选项。
- [complete] `subject` 贯穿识题、教学会话、普通/流式讲解、反馈与练习推荐；默认 `math` 保持兼容。
- [complete] 前端学科选择器、学科化输入提示、全科示例题和 Mock 教学流程。
- [complete] 新增 4 项全科回归测试；后端全量回归通过，前端构建通过。

## 按需语音优化

- [complete] 建立默认讲解禁用 TTS、独立朗读才启用 TTS 的回归测试。
- [complete] 新增不写入教学历史、不携带题图的独立朗读 API。
- [complete] 前端默认文字讲解，并提供朗读/停止按钮与浏览器语音回退。
- [complete] 完整回归、前端构建和真实延迟复测。

## Decisions

- 首版用户：中小学生，聚焦初中数学。
- MVP：Turn-based Chat；全双工仅预留接口。
- 教学流程：拍照/上传 -> 识别确认 -> 提示 -> 分步讲解 -> 语音/文字追问。
- 使用 vLLM-Omni 托管 MiniCPM-o 4.5；教学状态由后端编排器负责。
- 首版桌面 Chrome/Edge；Docker Compose 为主要交付形式。
- 无账号；原始媒体默认会话结束删除；主动保存才写入浏览器本地记录。
- 无 GPU 时使用明确标识的 Mock 模式。
- 学生自主学习 MVP：待重练错题按薄弱知识点聚合展示。
- 重练判定使用 SymPy 规则化等价；答对一次即掌握。
- 每次重练输入、正误、提示层级和时间均持久化；存量错题尝试次数从 0 开始。
- 第 1 次答错给知识点提示，第 2 次给关键步骤，第 3 次展示答案并可标记已理解。
- 学生自主学习 MVP：待重练错题按薄弱知识点聚合展示。
- 重练判定使用 SymPy 规则化等价；答对一次即掌握。
- 每次重练输入、正误、提示层级和时间均持久化；存量错题尝试次数从 0 开始。
- 第 1 次答错给知识点提示，第 2 次给关键步骤，第 3 次展示答案并可标记已理解。

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| 工作区不是 Git 仓库 | 1 | 按空目录新建教学应用骨架，外部 Demo 作为上游运行依赖 |
| `pytest` 收集上游 GPU 测试导致依赖错误 | 1 | 增加项目级 `pytest.ini`，隔离本项目测试；上游测试保留给其专用环境 |
| Mock 扩展后旧提示测试缺少“两边”措辞、4 个题面键未归一化匹配 | 1 | 恢复明确的等式提示，并按实际归一化结果修正模板键；最终评测 30/30 |
| 远程流式 TTS 音频位于 `choices[].delta.content` 且顶层 `modality=audio`，旧解析器漏收 | 1 | 按模态优先解析音频，避免误判为文本 |
| 浏览器把 MediaRecorder WebM 原始字节直接当 Float32 PCM 发送 | 1 | 用 AudioContext 解码并重采样为 16 kHz Float32 Base64 |

## Multi-question Recognition Fix (2026-08-16)

- [complete] 建立整页多题图片只返回第一题的确定性回归测试。
- [complete] 定位模型输出解析、图片分块与 API 聚合中的根因。
- [complete] 实施最小修复并验证后端、前端构建及原始多题链路。

## Competition Upgrade Plan (2026-08-15)

- [complete] P0：服务端教学会话短生命周期缓存题图，并让 `/api/lesson`、`/api/lesson/stream` 继续携带给 MiniCPM-o。
- [complete] P0：真实模式识题失败显式提示降级，不再表现为静默成功。
- [complete] P1：摄像头拍题入口，复用现有识别链路。
- [complete] P1：TTS 可打断与语音状态可视化，保持 Turn-based 边界。
- [complete] P2：补充比赛评测与演示材料；短视频理解待上游协议稳定后另开阶段。

### Competition Decisions

- 原始题图仅保存在内存教学会话中，随会话删除/过期清理，不写入错题本或浏览器记录。
- 识题降级字段必须能区分 `minicpm`、`mock` 与上游失败，前端对失败保持可见。
- 摄像头仅在本机浏览器使用，捕获帧不额外落盘。
- 不宣称全双工；本阶段先提升可感知实时性。

### Competition Verification

- [complete] `python3 -m pytest -q`：58 passed。
- [complete] `frontend npm run build`：TypeScript 与 Vite 构建通过。
- [complete] Uvicorn 冒烟：首页、静态资源与公开配置接口 200。
- [complete] 真实 MiniCPM-o 30 题评测与多模态探测，摘要见 `eval/REAL_MODEL_EVALUATION.md`。
- [complete] 比赛账号重置脚本与本地 App 真实链路复测。
- [complete] HTTPS Nginx 模板、公网验证脚本与 3 分钟演示分镜。
- [pending] 公网域名/DNS/证书由部署者提供后，执行 `scripts/verify_https_demo.py`。
- [pending] 按分镜人工录制旁白成片。
- [complete] 新增脚本静态编译、后端全量回归、前端构建与 diff 检查。
## 学生引导式教学交互优化（2026-08-16）

- [complete] 调整 MiniCPM 提示词：每轮只推进一个小目标，并以一个可回答的问题结束
- [complete] 将三阶段改为“看懂题目 / 尝试一步 / 总结方法”，重构提示与总结交互
- [complete] 增加快捷求助、当前步骤反馈和输入框聚焦行为
- [complete] 运行后端测试、前端构建、差异检查和响应式页面验证

## 对话记录时间戳（2026-08-16）

- [complete] 为每条师生交互消息保存稳定的创建时间
- [complete] 在对话记录中显示易读时间和完整时间语义
- [complete] 完成前端构建、差异检查和响应式页面验证

## 语音输入与对话回放（2026-08-16）

- [complete] 建立真实浏览器录音链路的可重复失败测试并定位根因
- [complete] 将用户语音作为独立消息类型传入教学请求并保留本地回放数据
- [complete] 在对话记录中区分文本/语音输入，提供可访问的播放控制
- [complete] 完成前后端回归、构建、差异检查和响应式页面验证
