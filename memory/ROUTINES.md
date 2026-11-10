# 例程提示词备份（更新 2026-11-10）

## 状态总览

| 职责 | 本机 Grok | flywall | GitHub Actions |
|------|-----------|---------|----------------|
| 开奖数据更新并推仓库 | 本机「开奖次日开机更新」**已删除** | **当前负责**：`/opt/foxwolf-lottery`，开奖日周日/二/四 22:00，次日周一/三/五 00:00 与 06:00（Asia/Shanghai，可晚约 15 分钟） | `ssq-next-day-update.yml`、`ssq-draw-notify.yml` 于 2026-11-07 **手动停用**（`disabled_manually`） |
| 选号开奖聊天通知 | **保留** `automation-1792651895824` | 不推聊天 | 原 `ssq-draw-notify.yml` 只能写 Job Summary，不能替代本聊天 |

2026-11-08 22:05，「双色球选号开奖通知」因账号 Grok Bot 用量不足失败，当晚对照未发出；例程仍为启用。

---

## flywall 拉数（当前）

路径：`/opt/foxwolf-lottery`（[foxwolf/lottery](https://github.com/foxwolf/lottery)）

每次：`python3 update_lottery.py`，再 `python3 update_ssq_mingxi.py --limit 30`；核对最新期明细行数不为 0；有变化则 commit/push 到 `main`（说明形如 `chore: local update SSQ {period}`）。不要虚构奖级注数或地区。chinasky / node2 不要在机上跑 update，只同步 GitHub。

---

## （历史）双色球开奖次日开机更新 — 曾迁 Actions，现已暂停

原本机调度：`CRON_TZ=Asia/Shanghai 0,30 8-22 * * 1,3,5`（已废弃，例程 `automation-1792575246828` 已删）  
曾用 Actions 调度：开奖次日 **00:00 与 06:00 Asia/Shanghai** → UTC `0 16 * * 0,2,4` 与 `0 22 * * 0,2,4`  
2026-11-07 起不再用 Actions 自动 commit `lottery.db`。

原提示词（归档，重建本机例程时不必恢复）：

在用户本机更新双色球及相关彩票开奖数据（开奖次日、开机连上后执行），并顺带核对用户关注的选号。

背景：双色球通常周二、周四、周日开奖。用户机器 machineId 以 ListMachines 为准（常见为 hw），项目目录 D:\develop\agent\lottery\（现为 foxwolf/lottery 克隆），数据库 lottery.db。

用户当前关注选号：红球 05、12、16、25、29、33；蓝球 15。娱乐用途，不要承诺能预测或保证中奖。

（拉数现由 flywall 承担；本机不再跑此例程。）

---

## 双色球选号开奖通知（automation-1792651895824）— 本机保留

调度：`CRON_TZ=Asia/Shanghai 0 22 * * 0,2,4`；flexible early 0 late 30

当前保存的提示词（2026-11-10 自例程读出）：

核对用户当前关注的双色球选号是否中奖，并在开奖当晚及时通知。

用户选号（固定直到用户在聊天里改掉）：红球 05、12、16、25、29、33；蓝球 15。娱乐用途，不要承诺能预测或保证中奖。

背景：双色球通常周二、周四、周日晚间开奖；本例程在这三天约 22:00（Asia/Shanghai）运行。用户机器常见为 hw（以 ListMachines 为准），项目目录 D:\develop\agent\lottery\，数据库 lottery.db，已有 update_lottery.py 与 update_ssq_mingxi.py。

每次执行：
1. 在用户本机对该目录跑增量更新（先开奖主数据，必要时再刷双色球明细最近若干期）。
2. 取出库内最新一期双色球开奖号码与期号、开奖日。
3. 与上述选号比对：红球命中几个、蓝球是否命中，并按常见双色球奖级规则给出大致档次（若规则不确定就只报命中个数，不要瞎编奖金）。
4. 把结果发到本对话：必须点名这注选号与开奖号对照，说明是否中奖/几等奖或未中；若当晚官方数据尚未入库，简短说明「暂未查到本期开奖，稍后再试」并尽量再查一次公开源；若最新一期明显是更早一期（不是当晚应出的期），同样说明暂未更新。
5. 不要改动无关文件。

结果接收方：本聊天里的用户。无论是否中奖都要发一条简短通知，不要静默。

补充约定（提示词里未写、备份需记住）：本机离线时尽量改用公开源或仓库已推数据仍发出对照；公网只读站 http://chinasky.xicp.net:28080/ 不替代本聊天通知；开奖主数据更新的权威来源现为 flywall 推送到 GitHub 的 `main`。
