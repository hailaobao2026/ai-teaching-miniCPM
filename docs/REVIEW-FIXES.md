# 审查问题修复任务书（供 gpt-5.6-sol 执行）

> 来源：2026-08-16 代码审查（85 tests passed / frontend build passed 的基线之上）。
> 仓库：/mnt/f/work/code/github/hailaobao2026/ai-teaching-miniCPM
> 验收要求：每项修复后跑 `.venv/bin/python -m pytest -q`（当前 85 passed）与
> `cd frontend && npm run build`，全部保持绿色；涉及 DB 的改动不得破坏已有数据兼容。

## 优先级 P0（部署/安全硬伤，建议先做）

### F1. Dockerfile 端口自相矛盾
- 位置：`Dockerfile` 第 48-49 行
- 现状：`EXPOSE 8080` 但 `CMD` 用 `--port 8089`；docker-compose 映射 `8089:8089`
- 修改：`EXPOSE 8089`（与 CMD、compose、healthcheck 统一）

### F2. docker-compose depends_on 兼容性
- 位置：`docker-compose.yml` math-coach 服务的 `depends_on`
- 现状：`condition: service_healthy` + `required: false`，`required` 需 Compose ≥ 2.24；
  mysql 带 `profiles: ["mysql"]`，默认 profile 下依赖未激活服务的行为各版本不一
- 修改：移除 `required: false`（保留 `condition: service_healthy`），并在 README/部署文档注明
  Compose 版本要求；或把 depends_on 移入 mysql profile 场景的说明文档。
  修改后应实测 `docker compose config` 能通过、`docker compose up`（默认 profile，不启 mysql）不报错。

### F3. 匿名兜底放行全部写接口（安全边界）
- 位置：`app.py` `_current_user_required`
- 现状：`MATH_COACH_AUTH_REQUIRED=false` 时，未登录请求以固定 `anonymous` 身份放行
  建会话、写错题本、提交重练等所有写操作
- 修改（二选一，推荐 A）：
  - A：匿名兜底仅放行 GET 类接口（health/config/examples/me 等），POST/PATCH/DELETE
    写接口仍要求真实登录；`MATH_COACH_AUTH_REQUIRED=false` 时在启动日志输出显著警告
  - B：保持行为但启动时打印警告并在 `/api/config` 增加 `auth_required:false` 的醒目提示
- 注意：conftest 默认 `MATH_COACH_AUTH_REQUIRED=false`，改动不能破坏测试（测试里匿名用户
  需要调 recognize/lesson 写接口，见 `tests/test_api.py::test_anonymous_mode_bootstraps_frontend_user`；
  若选 A 需同步调整该测试的预期）。

## 优先级 P1（代码质量，机械性修改）

### F4. 死代码清理
- `frontend/services/lessonService.ts` 的 `createLesson`（无调用者，前端只用 streamLesson）
- `teaching/minicpm_client.py` 的 `MiniCPMClient.image_content` 静态方法（无调用者）
- `app.py` 的 `_render_pdf_first_page`（无调用者）
- `teaching/minicpm_client.py` 的 `ws_url` property（注释自认 transitional alias，确认无测试引用后删除）
- 注意：先 `grep -rn` 确认引用，删完跑测试（`tests/test_api.py` 有 adapter 相关测试，勿误删被引用符号）

### F5. 布尔值用 "1"/"0" 字符串存储（Primitive Obsession）
- 位置：`teaching/auth_store.py`（notebook_items.helpful、notebook_attempts.correct 列定义
  与所有读写处的 `"1" if x else "0"` / `str(x).lower() in {"1","true","yes"}` 转换）
  及 `app.py` `_public_notebook_item`、`teaching/practice.py`
- 风险提示：SQLite 不支持 ALTER COLUMN 改类型，MySQL 支持。**不要直接动 schema**。
- 推荐方案（低风险）：提取统一 helper（如 `bool_to_db` / `db_to_bool`）放在
  `teaching/auth_store.py` 或新文件，替换全部散落转换点；schema 迁移另立任务，不在本次做。

### F6. 重复的规范化函数（Duplicated Code）
- 位置：`teaching/mock_tutor.py::_normalise`、`teaching/practice.py::_normalise`（及其别名
  `normalize_problem`）、`teaching/answers.py::_normalize`——三份"去空白/标点/全半角归一化"
- 修改：提取到共享模块（如 `teaching/text_utils.py` 或并入 practice.py），三个调用方复用；
  保留各自对外 API 签名（`normalize_problem`、`answers_equivalent` 等），保证测试不破

### F7. datetime→ISO 序列化逻辑重复
- 位置：`teaching/auth_store.py` `_row_to_user` / `_row_to_notebook` /
  `_row_to_notebook_attempt` 三处各写一份 naive→UTC→ISO8601 转换；
  `_attach_notebook_attempt_summary` 里还有第四份（app.py 内）
- 修改：提取 `_to_iso(value) -> str` helper 统一替换

### F8. app.py 重复实现 deps.py 已有依赖
- 位置：`app.py` `_current_user_optional` 与 `teaching/deps.py::get_optional_user` 逻辑完全相同
- 修改：app.py 直接 `from teaching.deps import get_optional_user` 复用，删除本地副本；
  `_current_user_required` 的匿名兜底逻辑保留（与 F3 一起处理）

## 优先级 P2（可做可不做，低风险低收益）

### F9. `_attach_notebook_attempt_summary` 重复字段
- `item["latest_attempt_at"]` 与 `item["latest_attempt"]` 赋值同一值；先确认前端用哪个
  （`frontend/types.ts` NotebookItem.latest_attempt），保留用到的，删多余的
- `consecutive_wrong` 统计逻辑（latest_by_item + 第二个循环）写法绕，可简化但注意测试
  （`tests/test_notebook.py` 有覆盖）

### F10. `lesson` 与 `lesson_stream` 降级回退重复
- 两个端点有相同 "MiniCPM 失败 → mock_lesson + 前缀提示" 回退块，可提取共享 helper；
  属重构，收益一般，时间紧可跳过

### F11. 版本号对齐
- `app.py` FastAPI `version="0.2.0"` vs README 徽章 v0.3.0；task_plan 中 "58 passed" 已过时
- 统一为 v0.3.0，更新 task_plan 验收数字为 85

### F12. 前端 `setConfig` 覆盖全局 mode（Spec 偏差）
- `frontend/App.tsx` `sendLesson` 成功后 `setConfig({...prev, mode: latestLesson.source})`，
  单次降级会把全局"当前模式"改成 mock 直到刷新
- 修改：区分"全局配置模式"与"本次响应来源"，降级时仅提示（toast 已存在），不覆盖 config.mode

## 不做项（产品决策，仅记录）

- **P1 多页识别**：需求文档写"PDF 转首页识别"，实现渲染最多 20 页全识别。属于有意的范围扩展
  （支撑整页多题修复），建议更新 docs/01 需求设计记录该决策，不改代码。
- **P5 尝试门槛**：docs 说"先完成一次尝试再进入方法总结"，但后端无尝试字段校验，仅前端
  `hasAttempted` 强制。turn-based MVP 的已知边界，记录即可。
- **双前端并存**（static vanilla + React）：冻结 static 功能迭代是长期策略，不在本次改。

## 验收清单

1. `.venv/bin/python -m pytest -q` → 全部通过（数量≥85，若 F3 调整了测试则说明原因）
2. `cd frontend && npm run build` → 通过
3. `docker compose config`（默认 profile）→ 无报错
4. 手工冒烟：`uvicorn app:app --port 8089` 起服务，首页 /api/config /api/health 200
5. 逐项在文件内标注 F1-F12 完成情况
