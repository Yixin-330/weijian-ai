# 未见后端

当前阶段提供四层能力：

1. 已有的知乎 OAuth、额度闸门、导入快照和证据适配器；
2. 可运行的 FastAPI 骨架，以及用于前后端联调的确定性演示闭环；
3. 可切换的 MySQL 持久化实现和 Alembic 迁移链；
4. Redis/arq 异步队列，以及 manual/cron 共用的世界调度器。

演示闭环不伪装成真实 Agent。它使用已审核的 v2 事件 Fixture，通过真实写入接口执行“理解校准 → 手动 tick → 同岛相遇 → 有限事件 → 相处记录更新 → 带回问题”。事件回放标记为 `source_mode=fixture`，没有合适候选时保持静默。

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

当前 head 为 `0006_m2_matching`。M0 迁移链将旧的情感阶段迁移为
非推断性的关系探索状态，建立 `encounter_decisions` 与 `messages`，并把实际相遇
次数与内部投影版本分开：相遇只记录发生了什么，私密决定和真人连接分别管理。
已有的 `shared_experiences` 与事件日志会保留，不会因迁移而丢失。

M1 增量迁移为 `evidence` 增加幂等键与可重算内容，为 `memories` 增加版本链，
并建立 `agent_context_snapshots`。历史证据会获得 `legacy:{id}` 幂等键和可识别的
占位文本；原始平台内容仍以导入快照为准，不会为了补列重新调用知乎接口。

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
- `GET /api/v1/meta/domain-contract`
- `POST /api/v1/onboarding`
- `POST /api/v1/demo/bootstrap`
- `GET /api/v1/users/{user_id}/world`
- `POST /api/v1/users/{user_id}/evidence`
- `GET /api/v1/users/{user_id}/evidence/{evidence_id}`
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

`meta/domain-contract` 是前端和测试读取的运行时词表，包含三座岛的规范 ID、相遇
状态、事件动作、关系探索状态、用户私密决定和真人连接状态。关系接口中的
`status` 只表示这一对生命体能否继续探索（`active / ended / blocked`），不再
表达“注意、在意、连接候选”等模型推断的情感等级。

M1 同时公开证据来源、理解类型/状态与上下文用途。证据写入接口只追加且要求
`ingestion_key`；同一用户以同一键重试会得到同一记录，以同一键提交不同事实会
返回冲突。平台证据必须绑定一次导入快照，应用内证据不能伪装成平台快照；敏感
证据即使请求授权用于社交，也会在写入边界自动降为仅私有探索。

## M1 理解与行动闭环

当前可以通过生命体页持续输入想法、生成候选理解、逐条校准、编辑、删除和调整
社交授权。编辑会创建替代理解，旧版本标记为 `superseded`；删除理解会将其标记
为 `deleted` 并从后续决策中排除，原始证据和历史审计的删除是另一项数据操作。

- `POST /api/v1/users/{user_id}/understandings/derive`：显式聚合证据，确定性生成候选；
- `POST /api/v1/understandings/{id}/changes`：`edit/delete/permission`，必须携带 `expected_version`；
- `GET /api/v1/understandings/{id}/history?user_id=...`：查看包括前身理解在内的修正历史；
- `POST /api/v1/users/{user_id}/memory-consent`：修改私人探索与社交推荐授权；
- `POST /api/v1/users/{user_id}/context-snapshots?purpose=exploration`：生成当前授权下的快照；
- `GET /api/v1/users/{user_id}/context-snapshots/{id}`：读取当时的不可变快照。

理解分数读取时按 30 天半衰期计算，不执行批量刷新；“只是最近”14 天后不再进入
上下文。候选生成仅产出 `topic`，被动信号不会形成立场。长期晋升合取规则仍由
`promotion.py` 维护，本阶段不自动确认推断出的长期特质；用户的明确校准可以确认
理解，四问中明确选择的关注保持原有确认语义。

manual/cron 共用的 tick 已改为从 `AgentContextSnapshot` 读取理解；每条新 tick
保存 `context_snapshot_id`，用于解释与回放。社交快照额外要求总体授权、逐条授权
且证据不敏感；用户明确重新授权某条理解时，不改写证据最初的授权记录。

本阶段采用固定议题和确定性规则，读取路径不调用 LLM。M2 已实现真实用户生命体
召回与配对；独立对话生成和 OAuth 导入的完整产品流程仍属后续里程碑，相遇执行器继续使用 fixture。

## M2 相遇与参与边界

- `GET/POST /api/v1/users/{user_id}/exploration`：读取或更新参与开关、社交节奏、跨岛许可、演示伙伴许可与排除议题。
- `POST /api/v1/encounters/{encounter_id}/decisions`：保存当前用户的 `observe_again/invite/distance/end/block` 决定；要求 `Idempotency-Key`，不会自动创建真人聊天。
- 默认只召回同岛真实生命体，跨岛和演示伙伴均须明确许可；无候选正常等待，不强行配对。
- 双方均须满足当前授权与参与条件；每次从至多 120 个初筛对象中保留至多 30 个候选，用确定性规则选择并保存双方社交上下文快照。
- 参与者相遇后冷却 10 分钟，同一对生命体冷却 24 小时；保持距离抑制 48 小时，结束和屏蔽持续抑制。
- 手动与 cron 使用相同调度与匹配逻辑。MySQL 在事务中锁定调度保护行，避免并发复用参与者；事务内不调用网络或 LLM。

迁移 0006 新增参与状态、配对排除、私密决定与调度保护表，并保存 tick/相遇的匹配解释。
开发环境可运行 `python -m app.verify_matching` 验证真实 MySQL 并发与幂等；它会保留带有 M2 验证标识的审计数据，并暂停新建测试用户。
完整范围和验收记录见 `docs/M2相遇召回与配对交付说明.md`（项目根目录）。

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
