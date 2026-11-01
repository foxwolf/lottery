# lottery

本机双色球/彩票工具备份：本地查看页、增量更新脚本、SQLite 开奖库，以及 Grok Bot「lottery」助手的记忆/例程备份。

娱乐用途，不构成投注建议，不保证预测。

## 目录

- `update_lottery.py` — 各玩法开奖增量更新
- `update_ssq_mingxi.py` — 双色球明细刷新（`--limit`）
- `view_server.py` — 本地 Web 查看（默认 `http://127.0.0.1:28081/`）
- `recommend_ssq.py` / `recommend_ssq_max3.py` — 推荐与少近号筛选
- `lottery.db` — SQLite 开奖库
- `memory/` — 助手记忆与例程提示词备份

## 本机路径

原目录：`D:\develop\agent\lottery\`

## 守号（备份时点）

红 `05 12 16 25 29 33`，蓝 `15`


## GitHub Actions（替代/备份本机例程）

| Workflow | 对应例程 | cron（UTC） | 上海时间含义 |
|----------|----------|-------------|--------------|
| `ssq-next-day-update.yml` | 开奖次日更新 | `0 16 * * 0,2,4` / `0 22 * * 0,2,4` | 周一/三/五 00:00 与 06:00（开奖次日） |
| `ssq-draw-notify.yml` | 选号开奖通知 | `0 14 * * 0,2,4` | 周日/二/四 22:00 |

行为概要：

1. 跑 `update_lottery.py`（及明细 `--limit 30`）。
2. 有新增则 **commit + push** `lottery.db`（及 `_update_summary.json` / 状态文件）到 `main`。
3. 用 `watch_pick.json` 对照最新一期，写入 Job Summary；开奖通知另写 `_draw_notify.md`。
4. Actions **不能**聊天推送；需要的话仍由 Grok Bot 例程通知。Actions 稳定后可暂停本机两条例程。

守号改号：编辑仓库根目录 `watch_pick.json`。

说明：GitHub cron 可能有数分钟延迟或偶发漏跑；公网 node2 同步不在本 workflow 内（见 `deploy/`）。
