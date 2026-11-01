# lottery 助手记忆备份

导出时间：2026-11-01 23:56（Asia/Shanghai）  
助手：lottery（Grok Bot）  
用途：防止删除助手后丢失约定；娱乐向，不保证预测。

## 用户偏好（相关）

- 聊天用中文。
- 本机机器：`hw`（machineId 以 ListMachines 为准）。
- 项目目录：`D:\develop\agent\lottery\` — **已替换为** [foxwolf/lottery](https://github.com/foxwolf/lottery) 的 `main` 克隆（约 2026-11-01，当时 tip `dbd7e86`）；旧目录备份 `D:\develop\agent\lottery.bak-20261101`（确认无用后可删）。
- 本地查看页：`view_server.py` → 通常 `http://127.0.0.1:28081/`。

## 当前关注选号（守号）

- 红球：`05 12 16 25 29 33`
- 蓝球：`15`
- 仓库内选号文件：`watch_pick.json`
- 筛选背景：优先历史无 5 红重合、尽量少 4 红。
- 要求：开奖结果出来后及时通知并对照。

## 例程与 GitHub Actions

### 本机 Grok 例程

| 名称 | 状态 | 说明 |
|------|------|------|
| 双色球开奖次日开机更新（`automation-1792575246828`） | **已删除**（2026-11-01） | 改由 GitHub Actions `ssq-next-day-update` 负责 |
| 双色球选号开奖通知（`automation-1792651895824`） | **保留** | Actions 无法推本聊天；开奖当晚仍靠本机例程发对照通知 |

### GitHub Actions（[foxwolf/lottery](https://github.com/foxwolf/lottery)）

1. **`ssq-next-day-update.yml`**（开奖次日更新）
   - 调度：Asia/Shanghai **周一/三/五 00:00 与 06:00** 各一次 → UTC `0 16 * * 0,2,4` 与 `0 22 * * 0,2,4`（对应周二/四/日开奖的次日；**不再**每半小时轮询）
   - 行为：`update_lottery.py` + 明细刷新 → 有新数据则 **自动 commit `lottery.db`**（及状态文件）到 `main`
   - 手动：`workflow_dispatch`

2. **`ssq-draw-notify.yml`**（选号开奖通知）
   - 调度：约周日/二/四 22:00 上海时间；更新并写 Job Summary
   - 聊天推送仍依赖本机「双色球选号开奖通知」例程

## 公网部署（node2）

- 主机：内网 `10.168.1.9`（Rocky Linux 8.10），跳板常为 `hw`（约 `10.168.1.210`）
- 路径：`/opt/lottery`（git clone，`origin=https://github.com/foxwolf/lottery.git`）
- 服务：`lottery-view` → `python3.9` 听 `127.0.0.1:28081`；Nginx `listen 28080` 反代
- 公网：花生壳 `chinasky.xicp.net`，映射 **外网 28080 → node2:28080**
- URL：`http://chinasky.xicp.net:28080/`（只读查看页；ISP 常封 80，实测可用口为 28080）
- 注意：node2 直连 GitHub 慢/失败；更新建议经 hw 代理（如 `127.0.0.1:10808`）pull 后 rsync，或隧道。`deploy/` 安装脚本要求 **python3.9+**

## 主要脚本

- `update_lottery.py` — 各玩法开奖增量
- `update_ssq_mingxi.py` — 双色球明细（`--limit`）
- `view_server.py` — Web 查看
- `recommend_ssq.py` / `recommend_ssq_max3.py` — 推荐与少近号筛选
- `scripts/ssq_watch_compare.py` — Actions/例程对照选号
- `lottery.db` — SQLite 开奖库
- `deploy/` — node2 部署（Nginx 28080、systemd、python3.9）

## 近期开奖对照摘要（选号相对）

- **2026124**（2026-10-29）：开奖红 `03 11 17 22 23 29` 蓝 `09` → 中红 **1**（29），蓝未中 → 未中奖
- **2026125**（2026-11-01）：开奖红 `04 06 10 15 26 27` 蓝 `11` → 红命中 **0**、蓝未中 → 未中奖  
  - 形态摘要：奇偶 2:4、质合 0:6（全合）、四区 2:2:0:2（空三区）、和值 88、连号 26-27；与 124 无重号；娱乐结论可继续守号
- 库与 GitHub：2026-11-01 本机 update 补入 2026125 并推送（commit `c17986e`）；随后 node2 rsync 至同 tip，HTTP 28080/28081 均为 200

## 2026-11-01 工作日志要点

1. 评估 GitHub Pages：静态可挂，但现 `view_server.py`+SQLite **不能**直接 Pages；后改为迁内网 + 花生壳。
2. node2 Rocky 8.7→8.10 升级并 reboot 后部署 lottery；公网端口最终定为 **28080**。
3. 本机与 GitHub `lottery.db` 开奖主数据对齐后补 2026125；本机目录改为仓库克隆统一管理。
4. 两条例程意图上架 Actions；次日更新改为 **次日 00:00 与 06:00**（上海）；删除本机「开奖次日开机更新」例程，保留「选号开奖通知」。

## 恢复提示

重建助手时：导入本文件要点到 profile/journal；本机只重建「选号开奖通知」例程（提示词见 `memory/ROUTINES.md`）；开奖次日更新以 Actions 为准（00:00/06:00 上海）；代码与 db 以仓库 `main` 为准，公网站点按需 rsync `/opt/lottery`。
