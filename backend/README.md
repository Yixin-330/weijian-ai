# 未见后端

当前阶段提供四层能力：

1. 已有的知乎 OAuth、额度闸门、导入快照和证据适配器；
2. 可运行的 FastAPI 骨架，以及用于前后端联调的确定性演示闭环；
3. 可切换的 MySQL 持久化实现和 Alembic 迁移链；
4. Redis/arq 异步队列，以及 manual/cron 共用的世界调度器。

演示闭环不伪装成真实 Agent。它使用已审核的 v2 事件 Fixture，通过真实写入接口执行“理解校准 → 手动 tick → 同岛相遇 → 有限事件 → 关系变化 → 带回问题”。事件回放标记为 `source_mode=fixture`，没有合适候选时保持静默。

未配置 `WJ_DATABASE_URL` 时使用进程内实现；配置后自动切换为 SQLAlchemy + MySQL。两种 Adapter 共享同一个 Experience 接口，前端 HTTP 契约不变。

## 安装

需要 Python 3.11 或更高版本：

```powershell
cd backend
uv pip install -e ".[storage,test]"
```

复制 `.env.example` 为 `.env` 后填写本机连接信息即可。`.env` 已被 Git 忽略，进程环境变量优先于文件内容；不要把真实密码写入 `.env.example`。

## MySQL 迁移

先创建一个空的 MySQL 8 数据库和最小权限应用账号，再设置连接地址：

```powershell
$env:WJ_DATABASE_URL="mysql+pymysql://weijian:你的密码@127.0.0.1:3306/weijian?charset=utf8mb4"
python -m alembic upgrade head
python -m app.seed_islands --version v2
python -m alembic current
```

岛屿发布命令会校验版本化 fixture，并在一次事务中幂等写入 `islands` 与
`island_fixtures`。同一版本内容哈希发生变化时会拒绝覆盖，必须创建新版本。

应用不会在启动时执行 `create_all`，也不会自动修改生产数据库。所有结构变化都必须新增并人工审查 Alembic revision；由于运行时只映射热表，`--autogenerate` 被刻意禁用，以免误生成删除其余表的迁移。

## 本地运行

```powershell
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

- 健康检查：`GET http://127.0.0.1:8000/health`
- 就绪检查：`GET http://127.0.0.1:8000/ready`

MySQL、Redis 或活动岛屿 fixture 不可用时，就绪检查返回 503；liveness
健康检查保持独立。响应中的 `storage`、`queue`、`islands` 分别表示三项依赖。

## Redis 与世界 Worker

配置 Redis 后，`POST /api/v1/world/ticks` 只负责投递任务并返回 `202`。前端使用返回的 `job_id` 查询 `/api/v1/world/tick-jobs/{job_id}`，完成后再读取世界状态。

```powershell
$env:WJ_REDIS_URL="redis://127.0.0.1:6379/0"
$env:WJ_TICK_QUEUE_NAME="weijian:ticks"
$env:WJ_TICK_CRON_MINUTES="10"
python -m arq app.worker.WorkerSettings
```

manual 和 cron 都生成结构化 `TickCommand` 并投递 `execute_world_tick`。Redis job ID 负责减少重复投递，MySQL `(user_id, idempotency_key)` 唯一约束负责最终正确性。

运行测试：

```powershell
python -m pytest -q
```

## 当前 HTTP 接口

- `GET /health`
- `GET /ready`
- `GET /api/v1/islands`
- `POST /api/v1/onboarding`
- `POST /api/v1/demo/bootstrap`
- `GET /api/v1/users/{user_id}/world`
- `GET /api/v1/lifeforms/{lifeform_id}`
- `GET /api/v1/lifeforms/{lifeform_id}/understandings?user_id=...`
- `POST /api/v1/memories/{memory_id}/calibrations`
- `POST /api/v1/understandings/{understanding_id}/calibrations`
- `POST /api/v1/users/{user_id}/next-action`
- `POST /api/v1/world/ticks`
- `GET /api/v1/world/tick-jobs/{job_id}`
- `GET /api/v1/world/ticks/{tick_id}`
- `GET /api/v1/world/ticks/{tick_id}/encounter`
- `GET /api/v1/encounters/{encounter_id}`
- `GET /api/v1/relationships/{relationship_id}`

手动 tick 使用 `X-Demo-Admin-Token`，并要求 `Idempotency-Key`。cron 和手动入口最终都必须调用同一个世界 tick 模块。

产品界面使用 `understandings` 命名，底层暂时复用 `memories` 表；两个校准
路径行为相同，旧路径用于兼容。用户校准后调用 `next-action`，不需要把演示
管理员 Token 暴露给浏览器。当前 MVP 用路径中的 `user_id` 做视角隔离；上线前
必须替换为真实登录会话中的用户身份。

网页端有两个入口：`/demo` 保留预计算演示，`/demo/start` 提供“四问 → 生命体
诞生 → 候选理解校准 → 下一步行动”的真实交互链路。

## 四问创建生命体

`POST /api/v1/onboarding` 将四个可调整的初始答案收敛成一次原子写入：
用户、生命体、应用内输入证据、当前关注候选理解和 1—3 条明确选择的长期关注会一起创建。
该入口要求 `Idempotency-Key`；使用同一个键重试会返回同一个世界，不会重复创建。

```json
{
  "current_question": "AI 陪伴会让真实关系变得更近，还是更远？",
  "long_term_topics": ["ai_and_loneliness", "intimacy_and_autonomy"],
  "exploration_style": "inquire",
  "social_pace": "shared_experiences",
  "allow_memory_inference": true,
  "allow_social_recommendation": false
}
```

`current_question` 只形成候选理解；用户明确选择的长期议题直接标记为已确认。
探索倾向可以在后续行为中缓慢调整，社交节奏只能由用户明确修改，不从被动行为推断。

## 依赖方向

```text
HTTP 路由
  → Experience interface
    → 无 DATABASE_URL：进程内确定性 Adapter
    → 有 DATABASE_URL：SQLAlchemy MySQL Adapter
      → Alembic 管理结构版本
  → IslandCatalog interface
    → 无 DATABASE_URL：版本化文件 Fixture Adapter
    → 有 DATABASE_URL：MySQL Adapter（显式幂等发布）
    → WorldScheduler interface
      → 无 REDIS_URL：进程内即时 Adapter
      → 有 REDIS_URL：Redis/arq Adapter
        → manual 与 cron 共用 execute_world_tick
    → Fixture 相遇执行器（当前 MVP）
    → 下一步：可选 LLM 提议器（输出仍须通过动作白名单校验）
```

MySQL 初始表结构位于 `migrations/0001_core.sql`，对应 revision `0001_core`。MySQL 始终是事实来源；Redis 只承担队列、缓存、锁和限流。
