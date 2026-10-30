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
