# MiniCPM Math Coach · 初中数学全模态教学 Web Demo

基于 [OpenBMB/MiniCPM-o-Demo](https://github.com/OpenBMB/MiniCPM-o-Demo) 的交互思路，将 MiniCPM-o 4.5 接入可登录的数学课堂：识题确认 → 苏格拉底提示 → 分步解析 → 文字/语音追问。推理服务推荐使用 [vLLM-Omni](https://github.com/vllm-project/vllm-omni)。

![Version](https://img.shields.io/badge/version-v0.2.0-green.svg)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)
![React](https://img.shields.io/badge/React-19-61dafb.svg)
![Vite](https://img.shields.io/badge/Vite-6-646cff.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688.svg)
![SQLite](https://img.shields.io/badge/SQLite-default-003B57.svg)
![MySQL](https://img.shields.io/badge/MySQL-optional-4479a1.svg)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED.svg)

> 教学应用层负责 **登录鉴权 / RBAC / 课堂编排 / SSE 流式讲解**；模型推理默认走 **vLLM-Omni OpenAI 兼容接口**。未配置上游时自动进入明确标注的 **Mock 演示模式**。前端为 React + Vite 深色侧栏工作台（参考 genai-craft 风格），账号存储支持 **SQLite（默认）** 与 **MySQL**。

### 演示截图

![桌面端工作区](README.assets/math-coach-desktop.png)

**工作区**：题面输入 / 拍照识题 / 例题 · 引导步骤 · 语音追问

![流式讲解](README.assets/math-coach-stream.png)

**流式讲解**：`/api/lesson/stream` SSE 增量文本 + 步骤卡片 + 最终答案

![移动端布局](README.assets/math-coach-mobile.png)

**移动端**：顶栏切换当前学习 / 本地记录 / 管理后台

### 演示视频

> 可按下面路径本地自测完整流程；若你有录屏，可替换为 GIF/视频链接。

1. 启动后端 + 前端（或 Docker 一体托管）
2. 使用演示管理员 `teacher@demo.local` / `demo123` 登录
3. 选择例题或上传题图 → 确认题面 → 查看提示 → 完整解析
4. 按住麦克风追问；管理员侧栏进入用户管理

### 项目介绍

本项目把 MiniCPM-o 的多模态能力封装为「可登录的数学课堂 Web」：

- 学生/教师登录后使用识题、提示引导、完整解析与语音追问
- 管理员可查看统计并调整用户角色/状态
- 无 GPU 时用 Mock 保证产品链路可演示；有 GPU 时通过 `VLLM_OMNI_URL` 接入真实模型
- 前端与后端可分开发联调，生产由 FastAPI 托管 React 构建产物

### 核心能力一览

#### 登录与权限
- 角色：`admin` / `teacher` / `student`
- 公开注册仅支持学生、教师；管理员由环境变量种子初始化
- 教学接口默认要求 `Authorization: Bearer <token>`
- 管理员后台：用户统计、角色/状态管理

#### 数学课堂（Turn-based）
- 文本粘贴、拍照/上传识题、内置例题
- 题面可编辑确认后才进入讲解
- 默认苏格拉底提示，可请求完整、可核验分步解析
- SSE 流式输出；结束后补齐 steps / final_answer / 可选 TTS
- 浏览器本地保存学习记录（不上传原图）

#### 模型与部署
- Mock 模式：无需 GPU、无需模型权重
- 真实模式：`VLLM_OMNI_URL` → vLLM-Omni `POST /v1/chat/completions`
- Docker 多阶段构建（Node 构建前端 + Python 运行后端）
- 数据库：`MATH_COACH_DB_BACKEND=sqlite|mysql`

### 技术栈

- 前端：React 19 + Vite 6 + TypeScript + Tailwind CDN
- 后端：Python FastAPI + Uvicorn
- 鉴权存储：SQLAlchemy + SQLite / MySQL（PyMySQL）
- 推理：vLLM-Omni 托管 MiniCPM-o 4.5（OpenAI compatible）
- 交付：Docker + docker-compose（可选 MySQL profile）

### 快速开始

#### 前置依赖
- Python 3.10+（Web 应用；Docker 使用 3.11）
- Node.js 20+（前端开发 / 构建）
- 可选：NVIDIA GPU + Python 3.12 + vLLM-Omni（真实推理）

#### 开发模式
```bash
# 1) 后端
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8080

# 2) 前端（另开终端）
cd frontend
npm install
npm run dev
```

打开 http://127.0.0.1:3000  
Vite 已将 `/api` 代理到 `http://127.0.0.1:8080`。

**演示账号**（密码均为 `demo123`）：

| 角色 | 邮箱 |
| --- | --- |
| 管理员 | `teacher@demo.local` |
| 教师 | `math.teacher@demo.local` |
| 学生 | `student@demo.local` |

#### 生产构建（FastAPI 一体托管）
```bash
cd frontend
npm install
npm run build          # 输出 frontend/dist
cd ..
source .venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8080
```

打开 http://127.0.0.1:8080  
若 `frontend/dist` 不存在，会回退到旧的 `static/` 页面。

#### Docker 部署
```bash
# Mock + SQLite + 登录鉴权
docker compose up --build -d

# 接入 GPU 上的 vLLM-Omni
VLLM_OMNI_URL=http://gpu-host:8099 docker compose up --build -d

# 使用 MySQL
MATH_COACH_DB_BACKEND=mysql docker compose --profile mysql up --build -d
```

容器默认：
- 端口 `8080`
- SQLite：`/app/data/math-coach.db`（卷 `math_coach_data`）
- 健康检查：`GET /api/health`

### 环境变量

完整示例见 [`.env.example`](.env.example)。

#### 基础
| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MATH_COACH_ALLOWED_ORIGINS` | 本地 8080/3000 | CORS 白名单 |
| `MATH_COACH_AUTH_REQUIRED` | `true` | 教学接口是否强制登录 |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | 演示管理员 | 种子管理员 |
| `SEED_DEMO_ACCOUNTS` | `true` | 是否创建演示教师/学生 |
| `DEMO_*` | 见 `.env.example` | 演示教师/学生账号 |

#### 数据库
| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MATH_COACH_DB_BACKEND` | `sqlite` | `sqlite` 或 `mysql` |
| `MATH_COACH_SQLITE_PATH` | `data/math-coach.db` | SQLite 文件路径 |
| `MATH_COACH_MYSQL_HOST/PORT/USER/PASSWORD/DATABASE` | - | MySQL 分段配置 |
| `MATH_COACH_MYSQL_DSN` | - | 可选完整 DSN 覆盖 |
| `MATH_COACH_AUTH_DB` | `data/auth-db.json` | 兼容旧路径，用于推导数据目录 |

#### 模型 / 上游
| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `VLLM_OMNI_URL` | 空 | 配置后进入真实 MiniCPM 模式 |
| `MINICPM_MODEL` | `openbmb/MiniCPM-o-4_5` | 模型名 |
| `VLLM_OMNI_TLS_VERIFY` | `true` | HTTPS 证书校验 |
| `MINICPM_GATEWAY_URL` | - | 旧别名，兼容保留 |

### 项目结构

```text
ai-teaching-miniCPM/
├── app.py                 # FastAPI 入口（API + 托管 frontend/dist）
├── teaching/              # 鉴权、编排、Mock、MiniCPM 客户端
│   ├── auth_store.py      # SQLite / MySQL 账号与会话
│   ├── orchestrator.py    # 教学会话
│   ├── minicpm_client.py  # vLLM-Omni OpenAI 适配
│   └── mock_tutor.py      # Mock 演示逻辑
├── frontend/              # React + Vite + TypeScript
│   ├── App.tsx
│   ├── components/        # AuthModal、Icons
│   ├── services/          # api / auth / admin / lesson
│   └── dist/              # 构建产物（npm run build）
├── static/                # 旧版 HTML 回退页
├── scripts/               # vLLM-Omni 安装/启动、Mock 评测
├── tests/                 # pytest
├── docs/                  # 设计与部署文档
├── Dockerfile             # Node 构建前端 + Python 运行时
├── docker-compose.yml     # Web + 可选 MySQL profile
└── requirements.txt
```

### API 概览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查（mode / auth / db_backend） |
| GET | `/api/config` | 公开配置、年级、演示账号标签 |
| POST | `/api/auth/register` `/login` | 注册 / 登录 |
| GET | `/api/auth/me` | 当前用户 |
| POST | `/api/auth/logout` | 退出 |
| PATCH | `/api/me/profile` | 更新昵称/年级 |
| GET | `/api/examples` | 示例题 |
| POST | `/api/recognize` | 识题（文本或图片） |
| POST | `/api/lesson` | 一轮讲解 |
| POST | `/api/lesson/stream` | **SSE 流式讲解** |
| POST | `/api/feedback` | 反馈 |
| DELETE | `/api/session/{id}` | 删除会话 |
| GET | `/api/admin/stats` | 管理统计 |
| GET/PATCH | `/api/admin/users` | 用户列表 / 角色状态 |

受保护接口需：

```http
Authorization: Bearer <token>
```

### 验证状态（摘录）

- 登录 / RBAC / 管理后台：pytest 覆盖
- 识题 → 提示 → 完整解析 → 会话删除：pytest 覆盖
- SSE 事件契约（`session` / `text_delta` / `lesson`）：pytest 覆盖
- 前端 `npm run build` 通过
- 当前基线：`pytest -q` → **19 passed**

## 课堂用法速查

### 1）登录拿 Token

```bash
curl -s http://127.0.0.1:8080/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"teacher@demo.local","password":"demo123"}'
```

### 2）文本讲解（非流式）

```bash
curl -s http://127.0.0.1:8080/api/lesson \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "problem": "解方程：2x + 5 = 17。",
    "message": "给我一个提示",
    "stage": "hint"
  }'
```

### 3）流式讲解（SSE）

```bash
curl -N http://127.0.0.1:8080/api/lesson/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "problem": "解方程：2x + 5 = 17。",
    "message": "请给完整解析",
    "stage": "explain"
  }'
```

### 4）接入真实 MiniCPM-o

```bash
# GPU 主机
./scripts/install_vllm_omni.sh --write-lock
source .venv-vllm-omni/bin/activate
./scripts/start_vllm_omni.sh   # 默认 :8099

# Web 主机
export VLLM_OMNI_URL=http://127.0.0.1:8099
export MINICPM_MODEL=openbmb/MiniCPM-o-4_5
uvicorn app:app --host 0.0.0.0 --port 8080
```

安装顺序（见 `requirements-gpu.txt`）：`vllm==0.26.0` → `vllm-omni==0.26.0` → `stepaudio2-minicpmo==0.1.1`。需要 Linux + NVIDIA + Python 3.12。

---

## 文档

| 文档 | 路径 |
|------|------|
| 文档索引 | [docs/README.md](docs/README.md) |
| 需求设计 | [docs/01-需求设计.md](docs/01-需求设计.md) |
| 概要设计 | [docs/02-概要设计.md](docs/02-概要设计.md) |
| 详细设计 | [docs/03-详细设计.md](docs/03-详细设计.md) |
| 数据字典 | [docs/04-数据字典.md](docs/04-数据字典.md) |
| 接口设计 | [docs/05-接口设计.md](docs/05-接口设计.md) |
| 部署与验证 | [docs/06-部署与验证.md](docs/06-部署与验证.md) |
| vLLM-Omni 调研 | [docs/vllm-omni-research.md](docs/vllm-omni-research.md) |

过程文档：`task_plan.md` / `progress.md` / `findings.md`

---

## 测试

```bash
# 后端
source .venv/bin/activate
pip install -r requirements.txt
pytest -q

# 前端类型检查 + 构建
cd frontend && npm install && npm run build
```

主要覆盖：
- 健康检查 / Mock 讲解护栏（提示阶段不直接给答案）
- 会话归属与删除
- MiniCPM 适配器 payload / SSE / 音频合并
- 登录注册、RBAC、管理员改角色/禁用账号

建议联调冒烟：
1. 演示管理员登录 → 管理后台可见
2. 学生注册/登录 → 例题提示 → 完整解析
3. 上传题图识题 → 确认题面 → 流式讲解
4. 配置 `VLLM_OMNI_URL` 后顶部模式徽标变为 MiniCPM 已连接

---

## 架构速览

```text
Browser (React SPA)
    │  JSON + Bearer / SSE
    ▼
FastAPI (app.py)
    ├─ AuthStore  ── SQLite / MySQL
    ├─ Orchestrator（教学会话，内存）
    ├─ Mock Tutor（无上游）
    └─ MiniCPM Client ──► vLLM-Omni :8099
                              └─ MiniCPM-o 4.5
```

本地开发：

```text
Vite :3000  ──proxy /api──►  FastAPI :8080
```

生产 / Docker：

```text
Browser ──► FastAPI :8080  (托管 frontend/dist + /api)
```

---

## 技术交流群

欢迎加入技术交流群，分享教学 AI 落地与全模态课堂心得：

![技术交流群](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/Obsidian/20260802145421_15_2.jpg)

## 作者联系

- **作者**: hailaobao
- **微信**: laohaibao2025
- **邮箱**: [Ujfgtujghedte@gmail.com](mailto:Ujfgtujghedte@gmail.com)

![微信二维码](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/Screenshot_20260123_095617_com.tencent.mm.jpg)

## 打赏

如果这个项目对你有帮助，欢迎请我喝杯咖啡 ☕

![微信支付](https://mypicture-1258720957.cos.ap-nanjing.myqcloud.com/image-20250914152855543.png)

## 项目统计

### 版本信息

- **当前版本**: v0.2.0
- **主要语言**: Python（后端） / TypeScript（前端）
- **推理引擎**: vLLM-Omni + MiniCPM-o 4.5（可选 Mock）

### 版本历史

- **v0.1.0** — Mock 教学链路、静态前端、识题/讲解/语音骨架
- **v0.2.0** (2026-08) — 登录 RBAC、管理员后台、SQLite/MySQL、React 前端改造、Docker 多阶段构建、文档齐套

---

## 🎉 致谢

感谢以下项目与产品线对本项目提供的支持：

1. [OpenBMB/MiniCPM-o-Demo](https://github.com/OpenBMB/MiniCPM-o-Demo) — 全模态交互产品参考  
2. [vllm-project/vllm-omni](https://github.com/vllm-project/vllm-omni) — MiniCPM-o 在线服务与 OpenAI 兼容接口  
3. [ai-teaching-video-platform](https://github.com/hailaobao2026/ai-teaching-video-platform) — 登录鉴权 / RBAC 形态参考  
4. genai-craft — 前端深色侧栏工作台结构参考  

## 路线图

### 已完成

- [x] 登录 / 注册 / Bearer 鉴权 / 角色权限
- [x] 管理员用户统计与角色/状态管理
- [x] 文本 / 拍照识题 / 例题入口
- [x] 提示式讲解 + 完整解析 + 会话编排
- [x] SSE 流式讲解与前端增量渲染
- [x] React + Vite 前端与后端一体托管
- [x] SQLite / MySQL 双数据库后端
- [x] Docker 多阶段构建与 Compose 交付
- [x] Mock 回归测试与设计文档

### 进行中 / 计划

- [ ] 真实 GPU 上 30 题识题/步骤/延迟评测
- [ ] 标注框质量与无坐标降级体验优化
- [ ] Half / Full-duplex 实时课堂能力评估
- [ ] 多实例会话共享（Redis 等）
- [ ] 生产级可观测性（指标、日志、告警）

### 已知边界

1. 标注依赖模型返回归一化坐标；未返回时不凭空画框  
2. 默认 SQLite 适合单机；多实例请切换共享 MySQL  
3. 首版为 Turn-based，不承诺全双工实时课堂  
4. 不保证竞赛/大学高等数学题的正确解析  

## License

本项目文档与示例代码默认用于教学演示与二次开发；第三方依赖（vLLM-Omni、MiniCPM 等）请遵循各自开源协议。
