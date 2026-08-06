# MiniCPM Math Coach 文档

本目录记录 MiniCPM Math Coach 的产品需求、系统设计、接口约定、数据字段和部署验证方式。文档以当前代码实现为准；模型服务以 vLLM-Omni 的官方文档为准，交互产品参考 `upstream/MiniCPM-o-Demo`，权限模型参考 `ai-teaching-video-platform`。

| 文档 | 内容 |
| --- | --- |
| [01-需求设计](01-需求设计.md) | 用户、范围、功能需求、非功能需求和验收标准 |
| [02-概要设计](02-概要设计.md) | 总体架构、模块划分、关键流程和部署拓扑 |
| [03-详细设计](03-详细设计.md) | API、鉴权、会话、识题、流式讲解、音频和前端（React）状态的实现设计 |
| [04-数据字典](04-数据字典.md) | 用户/会话、请求/响应对象、枚举、标注和本地存储字段 |
| [05-接口设计](05-接口设计.md) | HTTP/SSE 接口清单、鉴权头、示例和错误处理 |
| [06-部署与验证](06-部署与验证.md) | 本地、Docker、GPU vLLM-Omni 接入、账号种子和测试清单 |
| [vllm-omni-research](vllm-omni-research.md) | vLLM-Omni MiniCPM-o 4.5 调研记录 |

## 当前基线

- 产品：中文初中数学全模态教学 Web Demo。
- 主流程：登录 -> 上传/输入题目 -> 识别确认 -> 提示引导 -> 分步解析 -> 文字或语音追问。
- 权限：`admin` / `teacher` / `student`；教学 API 默认需 Bearer Token；管理员可管理用户。
- 模型：默认 Mock；设置 `VLLM_OMNI_URL` 后接入 vLLM-Omni 的 MiniCPM-o 4.5 服务。
- 状态：教学会话短期保存在服务端内存；用户账号/登录会话默认保存在 SQLite（`data/math-coach.db`），可选 MySQL；用户主动保存的学习记录在浏览器 `localStorage`。
- 前端：React + Vite + TypeScript（`frontend/`），构建产物由 FastAPI 托管；开发时可用 Vite `:3000` 代理 `/api`。
- 交付：Docker Compose 多阶段构建前后端，默认监听容器端口 `8080`。
- 测试：`pytest -q` 当前 `19 passed`。
