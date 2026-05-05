# TODOs

记录已识别但**暂未动手**的改进项。每条都应包含：触发场景、范围、为什么没立即做。

---

## Storage / 配置

### 统一文件模式的数据根目录

**现状**：文件模式下数据目录由 4 个独立环境变量控制，各有默认值：

| 变量 | 默认 |
|------|------|
| `SESSIONS_DIR` | `data/ark_sessions` |
| `MEMORY_DIR` | `data/ark_memory` |
| `JOB_RUNS_DIR` | `data/ark_job_runs` |
| `NOTIFICATIONS_DIR` | `data/ark_notifications` |

要把全部数据搬到 `/var/lib/ark` 之类的位置，得分别 export 4 次。

**目标**：引入一个 umbrella 变量 `ARK_DATA_DIR`，4 个 resolver 在专用变量未设时 fallback 到 `$ARK_DATA_DIR/<sub>`。SQLite 模式的 `DB_CONNECTION_STR` 也按同样规则 fallback 到 `$ARK_DATA_DIR/ark.db`。

**优先级**：
```
SESSIONS_DIR > $ARK_DATA_DIR/ark_sessions > data/ark_sessions
MEMORY_DIR   > $ARK_DATA_DIR/ark_memory   > data/ark_memory
... etc
```

**涉及文件**：
- `core/paths.py`（`prepare_agent_data_dir` / `get_memory_base_dir`）
- `plugins/jobs/paths.py`
- `plugins/notifications/paths.py`
- `core/storage/database/config.py`（`_DEFAULT_SQLITE_URL`）
- `.env-sample` 加一行 `ARK_DATA_DIR=`

**为什么暂不做**：
- 当前部署需求不强，shell 脚本里 export 一组变量足够。
- 改动 5 个文件 + 测试，需要慎重（任何路径回退优先级 bug 都会让数据写错位置）。
- 等真正出现"docker volume / 备份 / 多环境部署"这类痛点再做，避免 YAGNI。

**何时触发动手**：
- 用户提运维相关诉求（容器化部署、备份脚本、多 agent 共享一个 data root 等）。
- 或下次有人手动调试时反馈"4 个变量太烦"。
