# lottery 内网部署说明（Rocky 8 / node2）

目标机：`10.168.1.9`（node2）。对外只读查看页。  
公网地址（花生壳由用户配置）：**http://chinasky.xicp.net:28080/**  
（运营商常封 80，故公网用 **28080**，不是 80。）

## 架构

```
浏览器 → chinasky.xicp.net:28080
       → 花生壳 → node2:28080 (Nginx)
       → 反代 → 127.0.0.1:28081 (python3 view_server.py)
       → 读 /opt/lottery/lottery.db
```

- 应用默认只绑 **127.0.0.1:28081**（不直接暴露）。
- Nginx 监听 **28080**（可选另开 80 仅内网，见 `nginx-lottery.conf` 注释）。
- API 仅 `GET`，只读。

## 本目录文件

| 文件 | 用途 |
|------|------|
| `view_server.py` | 已打补丁：支持 `LOTTERY_HOST` / `LOTTERY_PORT` |
| `PATCH_NOTES.md` | 补丁说明与 sed 备用 |
| `lottery-view.service` | systemd 单元 |
| `nginx-lottery.conf` | Nginx：`listen 28080` → `127.0.0.1:28081` |
| `deploy.sh` | Rocky 8 一键安装脚本（需 root） |
| `view_server.py.upstream` | 上游原文备份 |

## 前置条件

1. Rocky 升到 8.10 并 **reboot** 完成。
2. root 可登录；本脚本 **不要** 写死密码。
3. 花生壳：**外网 28080 → 本机 28080**（用户在 Oray 改，本仓库不碰）。
4. 仓库：https://github.com/foxwolf/lottery （含 `lottery.db`）。

## 部署步骤（公司工作环境 / 运维）

1. 把整个 `lottery-deploy/` 拷到 node2（例如 `/root/lottery-deploy/`）。
2. `cd /root/lottery-deploy && bash deploy.sh`
3. 本机验收：
   - `curl -I http://127.0.0.1:28081/`
   - `curl -I http://127.0.0.1:28080/`
4. 用户在花生壳映射好后访问：`http://chinasky.xicp.net:28080/`

## 常用命令

```bash
systemctl status lottery-view nginx
journalctl -u lottery-view -f
nginx -t && systemctl reload nginx
```

更新数据：在 `/opt/lottery` 跑仓库自带更新脚本后，一般无需重启（SQLite 只读查询）；若替换整个 `lottery.db`，可 `systemctl restart lottery-view`。

## 注意 / Gotchas

1. **绑定**：应用务必 `127.0.0.1`；公网只开 Nginx 的 **28080**。不要把 `LOTTERY_HOST=0.0.0.0` 暴露到公网（除非另有 ACL）。
2. **firewalld**：`deploy.sh` 会 `firewall-cmd --permanent --add-port=28080/tcp`。若未跑 firewalld，检查云安全组/物理 ACL。
3. **SELinux**：需 `httpd_can_network_connect=1`，否则 Nginx 反代本机 28081 会 502。脚本已尝试 `setsebool -P`。
4. **用户权限**：服务用户 `lottery`；`lottery.db` 需可读。若 SQLite 自动建 `-wal`/`-shm`，`/opt/lottery` 需对 `lottery` 可写；只读挂载则改 service 去掉 `ProtectSystem` 限制或预先 `chmod`。
5. **80 端口**：公网不用 80；若要内网 `http://10.168.1.9/`，取消 nginx 配置里 `listen 80` 注释并放行 firewalld `http`。
6. **不要** 把 root 密码、Oray 账号提交进 Git；本包无密钥。
7. kubelet/Docker 与本站无关，可忽略。

## 回滚

```bash
systemctl disable --now lottery-view
rm -f /etc/nginx/conf.d/lottery.conf
systemctl reload nginx
# 可选: userdel lottery; rm -rf /opt/lottery
```
