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

## Decisions

- 首版用户：中小学生，聚焦初中数学。
- MVP：Turn-based Chat；全双工仅预留接口。
- 教学流程：拍照/上传 -> 识别确认 -> 提示 -> 分步讲解 -> 语音/文字追问。
- 使用 vLLM-Omni 托管 MiniCPM-o 4.5；教学状态由后端编排器负责。
- 首版桌面 Chrome/Edge；Docker Compose 为主要交付形式。
- 无账号；原始媒体默认会话结束删除；主动保存才写入浏览器本地记录。
- 无 GPU 时使用明确标识的 Mock 模式。

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| 工作区不是 Git 仓库 | 1 | 按空目录新建教学应用骨架，外部 Demo 作为上游运行依赖 |
| `pytest` 收集上游 GPU 测试导致依赖错误 | 1 | 增加项目级 `pytest.ini`，隔离本项目测试；上游测试保留给其专用环境 |
| Mock 扩展后旧提示测试缺少“两边”措辞、4 个题面键未归一化匹配 | 1 | 恢复明确的等式提示，并按实际归一化结果修正模板键；最终评测 30/30 |
