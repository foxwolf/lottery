#!/bin/bash
# Run as root on 10.168.1.9 after Rocky 8.10 reboot.
# Public: Nginx :28080 → app 127.0.0.1:28081. Oray: 外网28080→本机28080.
set -euo pipefail
REPO_URL="${REPO_URL:-https://github.com/foxwolf/lottery.git}"
OPT_DIR=/opt/lottery
APP_PORT=28081
PUBLIC_PORT=28080

echo "==> packages"
dnf -y install nginx python3 git

echo "==> user lottery"
id lottery &>/dev/null || useradd --system --home "$OPT_DIR" --shell /sbin/nologin lottery

echo "==> clone/update $OPT_DIR"
mkdir -p "$OPT_DIR"
if [[ -d "$OPT_DIR/.git" ]]; then
  git -C "$OPT_DIR" fetch --depth 1 origin main || true
  git -C "$OPT_DIR" reset --hard origin/main || true
else
  TMP=$(mktemp -d)
  git clone --depth 1 "$REPO_URL" "$TMP/lottery"
  rsync -a --delete "$TMP/lottery/" "$OPT_DIR/"
  rm -rf "$TMP"
fi
[[ -f "$OPT_DIR/lottery.db" ]] || { echo "ERROR: lottery.db missing"; exit 1; }

echo "==> patch view_server HOST/PORT env"
python3 - <<'PY'
from pathlib import Path
p = Path("/opt/lottery/view_server.py")
t = p.read_text(encoding="utf-8")
if "LOTTERY_HOST" not in t:
    if "import os" not in t:
        t = t.replace("import json\n", "import json\nimport os\n", 1)
    t = t.replace('HOST = "127.0.0.1"', 'HOST = os.environ.get("LOTTERY_HOST", "127.0.0.1")', 1)
    t = t.replace("PORT = 28081", 'PORT = int(os.environ.get("LOTTERY_PORT", "28081"))', 1)
    p.write_text(t, encoding="utf-8")
    print("patched")
else:
    print("already patched")
PY
chown -R lottery:lottery "$OPT_DIR"
chmod 0755 "$OPT_DIR"
chmod 0644 "$OPT_DIR/lottery.db" || true

echo "==> systemd"
cat >/etc/systemd/system/lottery-view.service <<'UNIT'
[Unit]
Description=Lottery DB read-only viewer (view_server.py)
After=network.target

[Service]
Type=simple
User=lottery
Group=lottery
WorkingDirectory=/opt/lottery
Environment=LOTTERY_HOST=127.0.0.1
Environment=LOTTERY_PORT=28081
ExecStart=/usr/bin/python3 /opt/lottery/view_server.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/lottery
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now lottery-view.service

echo "==> nginx"
cat >/etc/nginx/conf.d/lottery.conf <<'NGX'
upstream lottery_app {
    server 127.0.0.1:28081;
    keepalive 8;
}
server {
    listen 28080;
    listen [::]:28080;
    server_name chinasky.xicp.net _;
    client_max_body_size 1m;
    location / {
        proxy_pass http://lottery_app;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";
        proxy_read_timeout 60s;
        proxy_connect_timeout 5s;
    }
}
NGX
nginx -t
systemctl enable --now nginx
systemctl reload nginx

echo "==> firewalld + SELinux"
if systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-port=${PUBLIC_PORT}/tcp
  firewall-cmd --reload
fi
if command -v getenforce >/dev/null && [[ "$(getenforce)" != "Disabled" ]]; then
  setsebool -P httpd_can_network_connect 1 || true
fi

sleep 1
echo "==> smoke"
systemctl --no-pager -l is-active lottery-view nginx
curl -fsS -o /dev/null -w "app:%{http_code}\n" "http://127.0.0.1:${APP_PORT}/" || echo "app fail"
curl -fsS -o /dev/null -w "nginx:%{http_code}\n" "http://127.0.0.1:${PUBLIC_PORT}/" || echo "nginx fail"
ss -lntp | grep -E ':28080|:28081' || true
echo "Done. Public after Oray: http://chinasky.xicp.net:${PUBLIC_PORT}/"
