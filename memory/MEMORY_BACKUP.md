# lottery 助手记忆备份

导出时间：2026-11-10 16:10（Asia/Shanghai）  
上次备份：2026-11-01 23:56  
助手：lottery（Grok Bot）  
用途：防止删除助手后丢失约定；娱乐向，不保证预测。

## 用户偏好（相关）

- 聊天用中文。
- 本机机器：`hw`（machineId 以 ListMachines 为准）。
- 项目目录：`D:\develop\agent\lottery\` — 已替换为 [foxwolf/lottery](https://github.com/foxwolf/lottery) 的 `main` 克隆（约 2026-11-01，当时 tip `dbd7e86`）；旧目录备份 `D:\develop\agent\lottery.bak-20261101`（确认无用后可删）。
- 本地查看页：`view_server.py` → 通常 `http://127.0.0.1:28081/`。
- 约束：**不要在 node2 / chinasky 上跑 `update`**，只从 GitHub `main` pull/rsync。拉数由 flywall 完成后推仓库，再同步查看站。

## 当前关注选号（守号）

- 红球：`05 12 16 25 29 33`
- 蓝球：`15`
- 仓库内选号文件：`watch_pick.json`
- 筛选背景：优先历史无 5 红重合、尽量少 4 红。
- 要求：开奖结果出来后及时通知并对照。

## 拉数与例程（2026-11-07 起）

托管 GitHub Actions runner 访问中福彩 / 彩经网常 **403**（体彩接口也曾 567），会出现假绿或缺明细。用户已要求暂停 Actions 拉数，改由 **flywall 那台机器**执行更新并推到 GitHub。

### 本机 Grok 例程

| 名称 | 状态 | 说明 |
|------|------|------|
| 双色球开奖次日开机更新（`automation-1792575246828`） | **已删除**（2026-11-01） | 不再使用；拉数不在本机跑 |
| 双色球选号开奖通知（`automation-1792651895824`） | **保留、已启用** | 开奖当晚向本聊天推对照通知。调度：`CRON_TZ=Asia/Shanghai 0 22 * * 0,2,4`，flexible 最早不早于 22:00、最晚约 30 分钟 |

2026-11-08 22:05 该通知例程因 Cursor 账号 Grok Bot **用量不足**失败，当晚对照未发出。例程本身仍为启用。

### flywall（当前拉数与推送）

- 仓库路径：`/opt/foxwolf-lottery`
- 动作：`python3 update_lottery.py`，再 `python3 update_ssq_mingxi.py --limit 30`；有变化则 commit 并 push 到 `foxwolf/lottery` `main`（说明形如 `chore: local update SSQ {period}`）
- 定时（Asia/Shanghai，最早不早于整点，最晚约 15 分钟）：
  - 开奖日周日/二/四 **22:00**：拉数推送
  - 次日周一/三/五 **00:00**：次日零点更新
  - 次日周一/三/五 **06:00**：次日早晨更新
- flywall 不负责聊天通知。
- 在 flywall 上 cwl / 彩经网可访问（2026-11-07 实测无 403）。

### GitHub Actions（已暂停）

仓库内仍有工作流文件，但 2026-11-07 已手动停用（`disabled_manually`），避免与 flywall 争写 `lottery.db`：

1. **`ssq-next-day-update.yml`** — 原调度：上海周一/三/五 00:00 与 06:00（UTC `0 16` / `0 22` on `0,2,4`）
2. **`ssq-draw-notify.yml`** — 原调度：约周日/二/四 22:00 上海时间；只能写 Job Summary，不能聊天推送

恢复拉数前需先在仓库 Actions 里重新启用，并与 flywall 定时错开，避免双边同时改库。

## 公网部署（node2 / chinasky）

- 主机：内网 `10.168.1.9`（Rocky Linux 8.10），跳板常为 `hw`（约 `10.168.1.210`）
- 路径：`/opt/lottery`（git clone，`origin=https://github.com/foxwolf/lottery.git`）
- 服务：`lottery-view` → `python3.9` 听 `127.0.0.1:28081`；Nginx `listen 28080` 反代
- 公网：花生壳 `chinasky.xicp.net`，映射 **外网 28080 → node2:28080**
- URL：`http://chinasky.xicp.net:28080/`（只读查看页；ISP 常封 80，实测可用口为 28080）
- 同步：只从 GitHub `main` pull/rsync（必要时经 hw 代理 `127.0.0.1:10808` clone 后再覆盖）；**不要在 node2 跑 update**。协作由「公司工作环境」SSH 执行。
- `deploy/` 安装脚本要求 **python3.9+**
- 截至 2026-11-07：已同步到 `d088f08`；本地 28080/28081 与公网查看页均为 200（从本环境直连公网偶发 Pingora 500，以机上核对为准）。

## 主要脚本与数据链路

- `update_lottery.py` — 各玩法开奖增量；SSQ 在官方源失败时可回退 `datachart.500.com`；最新期号滞后则失败退出（PR #1）
- `update_ssq_mingxi.py` — 双色球开奖明细：彩经网 cjcp → 中福彩 cwl → 从 `ssq` 表/500.com 回退；最新期无明细行则失败退出（PR #2）。三至六等奖注数、一等奖地区仍依赖 cjcp/cwl，不要虚构。
- `view_server.py` — Web 查看；`/api/ssq/detail?period=` 读奖级表，无数据时页面显示「暂无奖级明细」
- `recommend_ssq.py` / `recommend_ssq_max3.py` — 推荐与少近号筛选
- `scripts/ssq_watch_compare.py` — 例程/原 Actions 对照选号
- `lottery.db` — SQLite 开奖库（`ssq`、`ssq_prize_detail`、`ssq_prize_region` 等）
- `deploy/` — node2 部署（Nginx 28080、systemd、python3.9）

相关合并：

- PR #1 squash `771d898`：开奖号 500.com 备用 + SSQ 滞后 fail-fast
- PR #2 squash `0f48d15`：开奖明细 500.com 回退 + 缺最新期明细 fail-fast

## 近期开奖对照摘要（选号相对）

选号一直是红 `05 12 16 25 29 33`、蓝 `15`。

- **2026124**（2026-10-29）：开奖红 `03 11 17 22 23 29` 蓝 `09` → 中红 **1**（29），蓝未中 → 未中奖
- **2026125**（2026-11-01）：开奖红 `04 06 10 15 26 27` 蓝 `11` → 红命中 **0**、蓝未中 → 未中奖  
  - 形态摘要：奇偶 2:4、质合 0:6（全合）、四区 2:2:0:2（空三区）、和值 88、连号 26-27；与 124 无重号；娱乐结论可继续守号
- **2026126**（2026-11-03）：开奖红 `09 10 13 22 29 32` 蓝 `12` → 中红 **1**（29），蓝未中 → 未中奖
- **2026127**（2026-11-05）：开奖红 `13 14 19 25 29 32` 蓝 `12` → 中红 **2**（25、29），蓝未中 → 未中奖  
  - 相对 126：奇偶 4:2、质合 3:3、012 路 0:3:3、四区 0-2-1-3、和值 132、跨度 19、连号 13-14；重号 13/29/32；蓝 12 连挂两期

截至本备份时，仓库 `main` 仍为 [`d088f08`](https://github.com/foxwolf/lottery/commit/d088f0838641a4dde2906970e323cd3fec02c696)（2026-11-07 08:08 上海时间，`chore: local update SSQ 2026127`）：ssq max=**2026127**；126/127 开奖明细各 7 条（cjcp，127 三至六等奖注数 812 / 46987 / 993523 / 6819834）；127 一等奖地区上海、天津、河北各 1 注（cwl）；3D / 排列3 / 排列5 已补 2026296。周日 2026-11-08 应有下一期，备份时仓库尚未见到更新提交。

## 2026-11-01 之后工作日志要点

1. 2026-11-01：GitHub Pages 不适用现有 `view_server.py`+SQLite；查看站迁 node2 + 花生壳，公网端口定为 **28080**。本机目录改为仓库克隆。次日更新一度改由 Actions（00:00 与 06:00 上海），删除本机「开奖次日开机更新」，保留「选号开奖通知」。
2. 2026-11-04：Actions 因 cwl/sporttery 对托管 runner 403/567 假绿，库一度停在 2026125；合入 PR #1 后验证拉到 2026126。
3. 2026-11-05/06：2026126、2026127 有开奖号但缺开奖明细（cjcp 在 Actions 上 403，脚本曾 exit 0，workflow 还有 `continue-on-error`）。合入 PR #2（`0f48d15`）后先用 500.com 回填奖级行；完整注数/地区仍要 cjcp/cwl。
4. 2026-11-07：用户暂停两个 Actions 拉数工作流；改由 flywall 拉数并推送。flywall 推送 `d088f08`，补全 126/127 明细与一等奖地区。按用户要求，chinasky `/opt/lottery` 从 GitHub 同步到该提交（只 sync，不在机上 update）。

## 恢复提示

重建助手时：导入本文件要点到 profile/journal；本机只重建「选号开奖通知」例程（提示词见 `memory/ROUTINES.md`）。拉数以 **flywall** 定时为准（不要默认再开 Actions，除非用户要求）。代码与 db 以仓库 `main` 为准；公网站点按需从 GitHub 同步 `/opt/lottery`，不要在 node2 补数。
