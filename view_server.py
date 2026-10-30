# -*- coding: utf-8 -*-
"""Local lottery.db viewer — stdlib only. Port 18081. Light friendly UI."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DB_PATH = Path(__file__).resolve().parent / "lottery.db"
HOST = "127.0.0.1"
PORT = 28081

TYPES = {
    "ssq": "双色球",
    "dlt": "大乐透",
    "d3": "福彩3D",
    "p3": "排列三",
    "p5": "排列五",
}

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

TAB_SUB = {
    "ssq": "每周二、四、日开奖",
    "dlt": "每周一、三、六开奖",
    "d3": "每天开奖",
    "p3": "每天开奖",
    "p5": "每天开奖",
}


def weekday_of(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return WEEKDAYS[d.weekday()]
    except ValueError:
        return None



def ensure_indexes():
    """Lightweight indexes for list/detail lookups."""
    conn = db()
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ssq_period ON ssq(period)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dlt_period ON dlt(period)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_d3_period ON d3(period)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_p3_period ON p3(period)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_p5_period ON p5(period)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ssq_prize_period ON ssq_prize_detail(period)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ssq_region_period ON ssq_prize_region(period)"
        )
        conn.commit()
    finally:
        conn.close()


def db():
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def row_to_draw(kind: str, r: sqlite3.Row) -> dict:
    draw_date = r["draw_date"]
    d = {
        "period": r["period"],
        "draw_date": draw_date,
        "weekday": weekday_of(draw_date),
        "sales_amount": r["sales_amount"] if "sales_amount" in r.keys() else None,
    }
    if kind == "ssq":
        d["reds"] = [r[f"red_{i}"] for i in range(1, 7)]
        d["blues"] = [r["blue"]]
        d["prize_pool"] = r["prize_pool"] if "prize_pool" in r.keys() else None
    elif kind == "dlt":
        d["fronts"] = [r[f"front_{i}"] for i in range(1, 6)]
        d["backs"] = [r["back_1"], r["back_2"]]
        d["prize_pool"] = r["prize_pool"] if "prize_pool" in r.keys() else None
    elif kind in ("d3", "p3"):
        d["nums"] = [r["num_1"], r["num_2"], r["num_3"]]
    elif kind == "p5":
        d["nums"] = [r[f"num_{i}"] for i in range(1, 6)]
    return d


def get_stats(kind: str) -> dict:
    with db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM {kind}").fetchone()[0]
        latest = conn.execute(
            f"SELECT period, draw_date FROM {kind} ORDER BY period DESC LIMIT 1"
        ).fetchone()
    latest_date = latest["draw_date"] if latest else None
    return {
        "type": kind,
        "name": TYPES[kind],
        "subtitle": TAB_SUB.get(kind, ""),
        "total": total,
        "latest_period": latest["period"] if latest else None,
        "latest_date": latest_date,
        "latest_weekday": weekday_of(latest_date),
    }


def get_draws(kind: str, page: int, page_size: int, period: str | None) -> dict:
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    offset = (page - 1) * page_size
    where = ""
    params: list = []
    if period:
        where = "WHERE period LIKE ?"
        params.append(f"%{period}%")
    with db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM {kind} {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM {kind} {where} ORDER BY period DESC LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        latest_period = None
        if not period:
            lr = conn.execute(
                f"SELECT period FROM {kind} ORDER BY period DESC LIMIT 1"
            ).fetchone()
            latest_period = lr["period"] if lr else None
    return {
        "type": kind,
        "name": TYPES[kind],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size) if total else 1,
        "latest_period": latest_period,
        "items": [row_to_draw(kind, r) for r in rows],
    }



def get_ssq_detail(period: str) -> dict:
    period = (period or "").strip()
    if not period:
        raise ValueError("period required")
    with db() as conn:
        draw = conn.execute("SELECT * FROM ssq WHERE period=?", (period,)).fetchone()
        if not draw:
            return {"error": "period not found", "period": period}
        prizes = conn.execute(
            """
            SELECT prize_level, prize_name, bet_count, amount, win_condition, source
            FROM ssq_prize_detail
            WHERE period=?
            ORDER BY prize_level
            """,
            (period,),
        ).fetchall()
        regions = conn.execute(
            """
            SELECT region, bet_count, prize_level, source
            FROM ssq_prize_region
            WHERE period=?
            ORDER BY bet_count DESC, region
            """,
            (period,),
        ).fetchall()
    return {
        "period": period,
        "draw_date": draw["draw_date"],
        "weekday": weekday_of(draw["draw_date"]),
        "reds": [draw[f"red_{i}"] for i in range(1, 7)],
        "blues": [draw["blue"]],
        "sales_amount": draw["sales_amount"],
        "prize_pool": draw["prize_pool"],
        "prizes": [
            {
                "level": r["prize_level"],
                "name": r["prize_name"],
                "bet_count": r["bet_count"],
                "amount": r["amount"],
                "condition": r["win_condition"],
                "source": r["source"],
            }
            for r in prizes
        ],
        "regions": [
            {
                "region": r["region"],
                "bet_count": r["bet_count"],
                "prize_level": r["prize_level"],
                "source": r["source"],
            }
            for r in regions
        ],
        "has_detail": len(prizes) > 0,
    }




def get_ssq_trends(window: int = 50) -> dict:
    """Classic 综合走势图 data: periods oldest_first (top->bottom on chart)."""
    try:
        window = int(window)
    except (TypeError, ValueError):
        window = 50
    window = max(10, min(100, window))

    BLUE_PRIMES = {2, 3, 5, 7, 11, 13}
    # 五行 for blue 1-16 (fixed consistent map)
    WUXING = {
        1: "金", 2: "木", 3: "水", 4: "火", 5: "土",
        6: "金", 7: "木", 8: "水", 9: "火", 10: "土",
        11: "金", 12: "木", 13: "水", 14: "火", 15: "土",
        16: "金",
    }
    WUXING_COLS = ["金", "木", "水", "火", "土"]

    with db() as conn:
        rows = conn.execute(
            """
            SELECT period, draw_date,
                   red_1, red_2, red_3, red_4, red_5, red_6, blue
            FROM ssq
            ORDER BY period DESC
            LIMIT ?
            """,
            (window,),
        ).fetchall()

    asc = list(reversed(rows))
    red_run = [0] * 34
    blue_run = [0] * 17
    periods = []
    for r in asc:
        reds = [int(r[f"red_{j}"]) for j in range(1, 7)]
        red_set = set(reds)
        b = int(r["blue"])
        red_omit = []
        for num in range(1, 34):
            if num in red_set:
                red_run[num] = 0
                red_omit.append(0)
            else:
                red_run[num] += 1
                red_omit.append(red_run[num])
        blue_omit = []
        for num in range(1, 17):
            if num == b:
                blue_run[num] = 0
                blue_omit.append(0)
            else:
                blue_run[num] += 1
                blue_omit.append(blue_run[num])

        size = "大" if b >= 9 else "小"
        oe = "奇" if b % 2 else "偶"
        prime = "质" if b in BLUE_PRIMES else "合"
        road = b % 3
        if 1 <= b <= 4:
            zone = 1
        elif 5 <= b <= 8:
            zone = 2
        elif 9 <= b <= 12:
            zone = 3
        else:
            zone = 4
        wx = WUXING.get(b, "土")

        periods.append(
            {
                "period": r["period"],
                "draw_date": r["draw_date"],
                "weekday": weekday_of(r["draw_date"]),
                "reds": reds,
                "blue": b,
                "red_omit": red_omit,
                "blue_omit": blue_omit,
                "blue_size": size,
                "blue_oe": oe,
                "blue_prime": prime,
                "blue_road": road,
                "blue_zone": zone,
                "blue_wuxing": wx,
            }
        )

    return {
        "window": len(periods),
        "requested": window,
        "order": "oldest_first",
        "wuxing_cols": WUXING_COLS,
        "wuxing_map": {str(k): v for k, v in WUXING.items()},
        "periods": periods,
    }



HTML = '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8"/>\n<meta name="viewport" content="width=device-width, initial-scale=1"/>\n<title>彩票开奖查询 · lottery.db</title>\n<style>\n:root {\n  --bg: #f5f6f8;\n  --card: #ffffff;\n  --border: #e5e7eb;\n  --text: #1f2937;\n  --muted: #6b7280;\n  --accent: #2563eb;\n  --red: #dc2626;\n  --blue: #2563eb;\n  --header-red: #8b1a1a;\n  --omit: #9ca3af;\n  --row-a: #ffffff;\n  --row-b: #eef6ff;\n  --shadow: 0 1px 3px rgba(0,0,0,.06);\n  --radius: 12px;\n}\n* { box-sizing: border-box; }\nbody {\n  margin: 0;\n  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif;\n  background: var(--bg);\n  color: var(--text);\n  min-height: 100vh;\n  line-height: 1.5;\n}\n.wrap { max-width: 1400px; margin: 0 auto; padding: 24px 16px 56px; }\nheader h1 { margin: 0 0 6px; font-size: 1.5rem; font-weight: 700; color: #111827; }\nheader .tip { color: var(--muted); font-size: 0.9rem; margin: 0 0 8px; }\nheader .path { font-size: 0.75rem; color: #9ca3af; font-family: ui-monospace, Consolas, monospace; word-break: break-all; }\n.banner {\n  background: #fffbeb; border: 1px solid #fbbf24; color: #92400e;\n  border-radius: 10px; padding: 10px 14px; font-size: 0.875rem; margin: 14px 0 18px;\n}\n.tabs { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; margin-bottom: 16px; }\n@media (max-width: 720px) { .tabs { grid-template-columns: repeat(2, 1fr); } }\n.tab {\n  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);\n  padding: 12px 8px; cursor: pointer; text-align: center; box-shadow: var(--shadow);\n}\n.tab:hover { border-color: #93c5fd; }\n.tab.active { border-color: var(--accent); background: #eff6ff; box-shadow: 0 0 0 2px #bfdbfe; }\n.tab .name { font-weight: 650; font-size: 0.95rem; }\n.tab .sub { font-size: 0.72rem; color: var(--muted); margin-top: 2px; }\n.stats {\n  display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 16px;\n}\n@media (max-width: 720px) { .stats { grid-template-columns: repeat(2, 1fr); } }\n.stat {\n  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);\n  padding: 12px 14px; box-shadow: var(--shadow);\n}\n.stat .label { font-size: 0.75rem; color: var(--muted); }\n.stat .value { font-size: 1.1rem; font-weight: 700; margin-top: 2px; }\n.toolbar {\n  display: flex; flex-wrap: wrap; gap: 10px; align-items: center;\n  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);\n  padding: 12px 14px; margin-bottom: 14px; box-shadow: var(--shadow);\n}\n.toolbar input[type=text] {\n  flex: 1; min-width: 140px; border: 1px solid var(--border); border-radius: 8px;\n  padding: 8px 12px; font-size: 0.9rem;\n}\n.toolbar button, .btn {\n  border: none; background: var(--accent); color: #fff; border-radius: 8px;\n  padding: 8px 14px; cursor: pointer; font-size: 0.875rem; font-weight: 600;\n}\n.toolbar button:hover, .btn:hover { background: #1d4ed8; }\n.toolbar .meta { color: var(--muted); font-size: 0.8rem; margin-left: auto; }\n.list { display: flex; flex-direction: column; gap: 8px; }\n.card {\n  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);\n  padding: 12px 14px; box-shadow: var(--shadow); display: flex; flex-wrap: wrap; gap: 10px; align-items: center;\n}\n.card.latest { border-color: #fbbf24; background: #fffbeb; }\n.card .period { font-weight: 700; min-width: 88px; }\n.card .date { color: var(--muted); font-size: 0.85rem; min-width: 120px; }\n.balls { display: flex; flex-wrap: wrap; gap: 6px; flex: 1; }\n.ball {\n  width: 30px; height: 30px; border-radius: 50%; display: inline-flex; align-items: center;\n  justify-content: center; font-size: 0.8rem; font-weight: 700; color: #fff;\n}\n.ball.red { background: var(--red); }\n.ball.blue { background: var(--blue); }\n.ball.front { background: #ea580c; }\n.ball.back { background: #16a34a; }\n.badge {\n  font-size: 0.7rem; background: #fbbf24; color: #78350f; padding: 2px 8px;\n  border-radius: 999px; font-weight: 700;\n}\n.detail-btn {\n  margin-left: auto; background: #fff; color: var(--accent); border: 1px solid #93c5fd;\n  border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: 0.8rem; font-weight: 600;\n}\n.detail-btn:hover { background: #eff6ff; }\n.pager {\n  display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: center;\n  margin-top: 16px; color: var(--muted); font-size: 0.85rem;\n}\n.pager button {\n  border: 1px solid var(--border); background: #fff; border-radius: 8px;\n  padding: 6px 12px; cursor: pointer;\n}\n.pager button:disabled { opacity: 0.4; cursor: not-allowed; }\n.pager select { border: 1px solid var(--border); border-radius: 8px; padding: 6px 8px; }\n.skeleton { background: linear-gradient(90deg,#eee,#f5f5f5,#eee); background-size: 200% 100%; animation: sk 1.2s infinite; border-radius: 8px; height: 56px; }\n@keyframes sk { 0%{background-position:200% 0} 100%{background-position:-200% 0} }\n\n/* ===== Classic trend charts ===== */\n.trends-panel {\n  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius);\n  box-shadow: var(--shadow); margin-bottom: 18px; overflow: hidden;\n}\n.trends-panel.hidden { display: none; }\n.trends-head {\n  display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: center;\n  padding: 12px 14px; border-bottom: 1px solid var(--border); background: #fafafa;\n}\n.trends-head h2 {\n  margin: 0; font-size: 1.05rem; color: #b91c1c; font-weight: 700; flex: 1 1 auto;\n}\n.trend-wins { display: flex; gap: 6px; flex-wrap: wrap; }\n.trend-wins button {\n  border: 1px solid var(--border); background: #fff; border-radius: 999px;\n  padding: 4px 12px; cursor: pointer; font-size: 0.8rem;\n}\n.trend-wins button.active { background: #b91c1c; color: #fff; border-color: #b91c1c; }\n.trend-opts { display: flex; gap: 14px; font-size: 0.82rem; color: #374151; }\n.trend-opts label { cursor: pointer; user-select: none; display: flex; align-items: center; gap: 4px; }\n.trends-hint { padding: 6px 14px; font-size: 0.78rem; color: var(--muted); border-bottom: 1px solid var(--border); }\n.trends-note { margin: 0 14px 12px; padding: 8px 12px; font-size: 0.8rem; color: #92400e; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; }\n.trends-body { padding: 0 0 12px; }\n.trends-loading, .trends-error { padding: 24px; text-align: center; color: var(--muted); }\n.trends-error { color: #b91c1c; }\n.zs-block { margin: 12px 14px 18px; }\n.zs-block h3 {\n  margin: 0 0 8px; font-size: 0.95rem; color: #991b1b; font-weight: 700;\n}\n.zs-scroll {\n  overflow: auto; max-height: 640px; border: 1px solid #c4c4c4; position: relative;\n  background: #fff;\n}\n.zs-table {\n  border-collapse: separate; border-spacing: 0; font-size: 12px; min-width: 100%;\n  table-layout: fixed;\n}\n.zs-table th, .zs-table td {\n  border-right: 1px solid #ddd; border-bottom: 1px solid #ddd;\n  text-align: center; padding: 0; height: 28px; vertical-align: middle;\n  white-space: nowrap;\n}\n.zs-table thead th {\n  position: sticky; top: 0; z-index: 5;\n  background: var(--header-red); color: #fff; font-weight: 600;\n  font-size: 11px; height: 30px;\n}\n.zs-table thead tr.sub th { top: 30px; font-size: 11px; }\n.zs-table .sticky-l {\n  position: sticky; z-index: 4;\n}\n.zs-table tbody tr:nth-child(odd) .sticky-l { background: var(--row-a); }\n.zs-table tbody tr:nth-child(even) .sticky-l { background: var(--row-b); }\n.zs-table thead .sticky-l { z-index: 6; background: var(--header-red); }\n.zs-table .c-idx { left: 0; width: 36px; min-width: 36px; }\n.zs-table .c-period { left: 36px; width: 72px; min-width: 72px; }\n.zs-table .c-award { left: 108px; width: 148px; min-width: 148px; text-align: left; padding: 0 6px; }\n.zs-table thead .c-idx { left: 0; }\n.zs-table thead .c-period { left: 36px; }\n.zs-table thead .c-award { left: 108px; }\n.zs-table tbody tr:nth-child(odd) { background: var(--row-a); }\n.zs-table tbody tr:nth-child(even) { background: var(--row-b); }\n.zs-table tbody tr:nth-child(5n) td { border-bottom-color: #999; }\n.zs-table .award-red { color: #dc2626; font-weight: 700; letter-spacing: 0.5px; }\n.zs-table .award-blue { color: #2563eb; font-weight: 700; margin-left: 4px; }\n.zs-num { width: 26px; min-width: 26px; position: relative; }\n.zs-omit { color: var(--omit); font-size: 11px; }\n.zs-hit {\n  display: inline-flex; width: 20px; height: 20px; border-radius: 50%;\n  align-items: center; justify-content: center; color: #fff; font-weight: 700;\n  font-size: 11px; position: relative; z-index: 2;\n}\n.zs-hit.blue { background: #2563eb; }\n.zs-hit.red { background: #dc2626; }\n.zs-side { width: 28px; min-width: 28px; font-size: 11px; font-weight: 650; }\n.zs-side.da { color: #dc2626; }\n.zs-side.xiao { color: #16a34a; }\n.zs-side.ji { color: #16a34a; }\n.zs-side.ou { color: #dc2626; }\n.zs-side.zhi { color: #16a34a; }\n.zs-side.he { color: #dc2626; }\n.zs-road-hit {\n  display: inline-flex; width: 18px; height: 18px; border-radius: 50%;\n  border: 2px solid #dc2626; align-items: center; justify-content: center;\n  font-weight: 700; font-size: 11px; color: #b91c1c;\n}\n.zs-zone-hit {\n  display: inline-flex; width: 18px; height: 18px; border-radius: 50%;\n  background: #2563eb; color: #fff; align-items: center; justify-content: center;\n  font-size: 10px; font-weight: 700; position: relative; z-index: 2;\n}\n.zs-wx-hit {\n  display: inline-flex; min-width: 20px; height: 18px; border-radius: 4px;\n  background: #2563eb; color: #fff; align-items: center; justify-content: center;\n  font-size: 10px; font-weight: 700; padding: 0 3px; position: relative; z-index: 2;\n}\n.zs-svg {\n  position: absolute; left: 0; top: 0; width: 100%; height: 100%;\n  pointer-events: none; z-index: 1; overflow: visible;\n}\n.zs-guide td.zs-num { background-image: linear-gradient(to right, transparent 49%, #e5e7eb 49%, #e5e7eb 51%, transparent 51%); }\n.zs-guide.every5 { box-shadow: inset 0 -2px 0 #9ca3af; }\n\n/* Drawer */\n.drawer-mask {\n  position: fixed; inset: 0; background: rgba(15,23,42,.45); z-index: 40;\n  opacity: 0; pointer-events: none; transition: opacity .2s;\n}\n.drawer-mask.open { opacity: 1; pointer-events: auto; }\n.drawer {\n  position: fixed; top: 0; right: 0; width: min(420px, 100%); height: 100%;\n  background: #fff; z-index: 50; box-shadow: -8px 0 24px rgba(0,0,0,.12);\n  transform: translateX(100%); transition: transform .25s ease; display: flex; flex-direction: column;\n}\n.drawer.open { transform: translateX(0); }\n.drawer-hd {\n  display: flex; align-items: center; justify-content: space-between;\n  padding: 16px 18px; border-bottom: 1px solid var(--border);\n}\n.drawer-hd h3 { margin: 0; font-size: 1.05rem; }\n.drawer-close {\n  border: none; background: #f3f4f6; width: 32px; height: 32px; border-radius: 8px;\n  cursor: pointer; font-size: 1.1rem;\n}\n.drawer-bd { padding: 16px 18px; overflow: auto; flex: 1; }\n.prize-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }\n.prize-table th, .prize-table td { border-bottom: 1px solid var(--border); padding: 8px 6px; text-align: left; }\n.prize-table th { color: var(--muted); font-weight: 600; }\n.region-list { margin-top: 12px; font-size: 0.85rem; }\n.region-list li { margin: 4px 0; }\n</style>\n</head>\n<body>\n<div class="wrap">\n  <header>\n    <h1>彩票开奖查询</h1>\n    <p class="tip">本地 lottery.db · 双色球含开奖明细与综合走势图</p>\n    <div class="path">数据文件：lottery.db</div>\n  </header>\n  <div class="banner">数据仅供查询与统计参考，彩票开奖具有随机性，走势图不能提高中奖概率。</div>\n  <div class="tabs" id="tabs"></div>\n  <div class="stats" id="stats"></div>\n\n  <div class="trends-panel hidden" id="trendsPanel">\n    <div class="trends-head">\n      <h2 id="trendsTitle">双色球 · 蓝球综合走势图</h2>\n      <div class="trend-wins" id="trendWins">\n        <button type="button" data-w="30">近30期</button>\n        <button type="button" data-w="50" class="active">近50期</button>\n        <button type="button" data-w="100">近100期</button>\n      </div>\n      <div class="trend-opts">\n        <label><input type="checkbox" id="optGuide" checked/> 辅助线</label>\n        <label><input type="checkbox" id="optLine" checked/> 带折线</label>\n      </div>\n    </div>\n    <div class="trends-hint" id="trendsHint"></div>\n    <div class="trends-body" id="trendsBody"></div>\n  </div>\n\n  <div class="toolbar">\n    <input type="text" id="q" placeholder="搜索期号，如 2026120" />\n    <button type="button" id="btnSearch">搜索</button>\n    <button type="button" id="btnReset" style="background:#6b7280">重置</button>\n    <span class="meta" id="listMeta"></span>\n  </div>\n  <div class="list" id="list"></div>\n  <div class="pager" id="pager"></div>\n</div>\n\n<div class="drawer-mask" id="drawerMask"></div>\n<aside class="drawer" id="drawer" aria-hidden="true">\n  <div class="drawer-hd">\n    <h3 id="drawerTitle">开奖明细</h3>\n    <button type="button" class="drawer-close" id="drawerClose" aria-label="关闭">×</button>\n  </div>\n  <div class="drawer-bd" id="drawerBody"></div>\n</aside>\n\n<script>\nconst TYPES = {\n  ssq: { name: \'双色球\', sub: \'每周二、四、日开奖\' },\n  dlt: { name: \'大乐透\', sub: \'每周一、三、六开奖\' },\n  d3:  { name: \'福彩3D\', sub: \'每日开奖\' },\n  p3:  { name: \'排列三\', sub: \'每日开奖\' },\n  p5:  { name: \'排列五\', sub: \'每日开奖\' },\n};\n\nlet kind = \'ssq\';\nlet page = 1;\nlet pageSize = 20;\nlet periodQ = \'\';\nlet trendWindow = 50;\nlet trendsLoadedFor = \'\';\nlet lastTrendData = null;\nlet optGuide = true;\nlet optLine = true;\n\nfunction fmtMoney(n) {\n  if (n == null || n === \'\') return \'—\';\n  const x = Number(n);\n  if (!Number.isFinite(x)) return String(n);\n  if (x >= 1e8) return (x / 1e8).toFixed(2) + \' 亿\';\n  if (x >= 1e4) return (x / 1e4).toFixed(2) + \' 万\';\n  return x.toLocaleString(\'zh-CN\');\n}\n\nfunction ballHtml(n, cls) {\n  const s = String(n).padStart(2, \'0\');\n  return `<span class="ball ${cls}">${s}</span>`;\n}\n\nfunction renderTabs() {\n  const el = document.getElementById(\'tabs\');\n  el.innerHTML = Object.entries(TYPES).map(([k, v]) => `\n    <button type="button" class="tab ${k === kind ? \'active\' : \'\'}" data-k="${k}">\n      <div class="name">${v.name}</div>\n      <div class="sub">${v.sub}</div>\n    </button>`).join(\'\');\n  el.querySelectorAll(\'.tab\').forEach(btn => {\n    btn.onclick = () => {\n      kind = btn.dataset.k;\n      page = 1;\n      periodQ = \'\';\n      document.getElementById(\'q\').value = \'\';\n      load();\n    };\n  });\n}\n\nfunction renderStats(s) {\n  const el = document.getElementById(\'stats\');\n  if (!s) { el.innerHTML = \'\'; return; }\n  const items = [\n    [\'总期数\', s.total ?? \'—\'],\n    [\'最新期\', s.latest_period ?? \'—\'],\n    [\'最新开奖日\', s.latest_date ? `${s.latest_date}${s.latest_weekday ? \' · \' + s.latest_weekday : \'\'}` : \'—\'],\n    [\'玩法\', s.name || s.subtitle || kind],\n  ];\n  el.innerHTML = items.map(([label, value]) => `\n    <div class="stat"><div class="label">${label}</div><div class="value">${value}</div></div>`).join(\'\');\n}\n\nfunction blueOf(item) {\n  if (item.blue != null) return item.blue;\n  if (item.blues && item.blues.length) return item.blues[0];\n  return null;\n}\nfunction renderBalls(item) {\n  if (kind === \'ssq\') {\n    const b = blueOf(item);\n    return (item.reds || []).map(n => ballHtml(n, \'red\')).join(\'\') + (b != null ? ballHtml(b, \'blue\') : \'\');\n  }\n  if (kind === \'dlt\') {\n    return (item.fronts || item.reds || []).map(n => ballHtml(n, \'front\')).join(\'\')\n      + (item.backs || []).map(n => ballHtml(n, \'back\')).join(\'\');\n  }\n  const nums = item.digits || item.numbers || item.reds || [];\n  return nums.map(n => ballHtml(n, \'red\')).join(\'\');\n}\n\nfunction renderList(data) {\n  const list = document.getElementById(\'list\');\n  const items = data.items || data.draws || [];\n  if (!items.length) {\n    list.innerHTML = \'<div class="card" style="justify-content:center;color:#6b7280">暂无数据</div>\';\n    return;\n  }\n  list.innerHTML = items.map((it, idx) => {\n    const latest = page === 1 && !periodQ && idx === 0;\n    const detailBtn = kind === \'ssq\'\n      ? `<button type="button" class="detail-btn" data-period="${it.period}">开奖明细</button>`\n      : \'\';\n    return `<div class="card ${latest ? \'latest\' : \'\'}">\n      ${latest ? \'<span class="badge">最新</span>\' : \'\'}\n      <div class="period">${it.period}</div>\n      <div class="date">${it.draw_date || \'\'}${it.weekday ? \' · \' + it.weekday : \'\'}</div>\n      <div class="balls">${renderBalls(it)}</div>\n      ${detailBtn}\n    </div>`;\n  }).join(\'\');\n  list.querySelectorAll(\'.detail-btn\').forEach(btn => {\n    btn.onclick = () => openDrawer(btn.dataset.period);\n  });\n}\n\nfunction renderPager(data) {\n  const pager = document.getElementById(\'pager\');\n  const total = data.total ?? 0;\n  const pages = Math.max(1, Math.ceil(total / pageSize));\n  document.getElementById(\'listMeta\').textContent = `共 ${total} 期 · 第 ${page}/${pages} 页`;\n  pager.innerHTML = `\n    <button type="button" id="prev" ${page <= 1 ? \'disabled\' : \'\'}>上一页</button>\n    <span>跳至</span>\n    <input type="number" id="goto" min="1" max="${pages}" value="${page}" style="width:64px;padding:6px;border:1px solid var(--border);border-radius:8px"/>\n    <button type="button" id="go">Go</button>\n    <button type="button" id="next" ${page >= pages ? \'disabled\' : \'\'}>下一页</button>\n    <select id="ps">\n      ${[10,20,50,100].map(n => `<option value="${n}" ${n===pageSize?\'selected\':\'\'}>${n}/页</option>`).join(\'\')}\n    </select>`;\n  pager.querySelector(\'#prev\').onclick = () => { page--; load(); };\n  pager.querySelector(\'#next\').onclick = () => { page++; load(); };\n  pager.querySelector(\'#go\').onclick = () => {\n    const v = parseInt(pager.querySelector(\'#goto\').value, 10);\n    if (v >= 1 && v <= pages) { page = v; load(); }\n  };\n  pager.querySelector(\'#ps\').onchange = (e) => {\n    pageSize = parseInt(e.target.value, 10); page = 1; load();\n  };\n}\n\nfunction hideTrends() {\n  document.getElementById(\'trendsPanel\').classList.add(\'hidden\');\n}\n\nfunction ensureChronological(periods, order) {\n  const arr = (periods || []).slice();\n  if (order === \'oldest_first\') return arr;\n  if (arr.length >= 2 && String(arr[0].period) > String(arr[arr.length - 1].period)) {\n    return arr.reverse();\n  }\n  return arr;\n}\n\nfunction pad2(n) { return String(n).padStart(2, \'0\'); }\n\nfunction renderBlueTable(periods, wuxingCols) {\n  const nums = Array.from({length: 16}, (_, i) => i + 1);\n  const zoneLabels = [\'1区\', \'2区\', \'3区\', \'4区\'];\n  const wx = wuxingCols || [\'金\',\'木\',\'水\',\'火\',\'土\'];\n\n  let head = `<thead>\n    <tr>\n      <th class="sticky-l c-idx" rowspan="2">序号</th>\n      <th class="sticky-l c-period" rowspan="2">期号</th>\n      <th class="sticky-l c-award" rowspan="2">奖号</th>\n      <th colspan="16">蓝球分布</th>\n      <th rowspan="2" class="zs-side">大小</th>\n      <th rowspan="2" class="zs-side">奇偶</th>\n      <th rowspan="2" class="zs-side">质合</th>\n      <th colspan="3">012路</th>\n      <th colspan="4">四区分布</th>\n      <th colspan="5">五行属性</th>\n    </tr>\n    <tr class="sub">\n      ${nums.map(n => `<th class="zs-num">${pad2(n)}</th>`).join(\'\')}\n      <th class="zs-side">0</th><th class="zs-side">1</th><th class="zs-side">2</th>\n      ${zoneLabels.map(z => `<th class="zs-side">${z}</th>`).join(\'\')}\n      ${wx.map(w => `<th class="zs-side">${w}</th>`).join(\'\')}\n    </tr>\n  </thead>`;\n\n  let body = \'<tbody>\';\n  periods.forEach((p, idx) => {\n    const guide = optGuide ? \'zs-guide\' : \'\';\n    const every5 = optGuide && ((idx + 1) % 5 === 0) ? \'every5\' : \'\';\n    const redsTxt = (p.reds || []).map(pad2).join(\' \');\n    const blueTxt = pad2(p.blue);\n    let cells = \'\';\n    for (let n = 1; n <= 16; n++) {\n      if (n === p.blue) {\n        cells += `<td class="zs-num" data-blue-hit="${idx}" data-col="${n}"><span class="zs-hit blue">${pad2(n)}</span></td>`;\n      } else {\n        const om = (p.blue_omit || [])[n - 1] ?? \'\';\n        cells += `<td class="zs-num"><span class="zs-omit">${om}</span></td>`;\n      }\n    }\n    const sizeCls = p.blue_size === \'大\' ? \'da\' : \'xiao\';\n    const oeCls = p.blue_oe === \'奇\' ? \'ji\' : \'ou\';\n    const prCls = p.blue_prime === \'质\' ? \'zhi\' : \'he\';\n    const road = p.blue_road;\n    let roads = [0,1,2].map(r => r === road\n      ? `<td class="zs-side"><span class="zs-road-hit">${r}</span></td>`\n      : `<td class="zs-side"></td>`).join(\'\');\n    let zones = [1,2,3,4].map(z => z === p.blue_zone\n      ? `<td class="zs-side" data-zone-hit="${idx}" data-zcol="${z}"><span class="zs-zone-hit">${z}</span></td>`\n      : `<td class="zs-side"></td>`).join(\'\');\n    let wxs = wx.map(w => w === p.blue_wuxing\n      ? `<td class="zs-side" data-wx-hit="${idx}" data-wcol="${w}"><span class="zs-wx-hit">${w}</span></td>`\n      : `<td class="zs-side"></td>`).join(\'\');\n\n    body += `<tr class="${guide} ${every5}">\n      <td class="sticky-l c-idx">${idx + 1}</td>\n      <td class="sticky-l c-period">${p.period}</td>\n      <td class="sticky-l c-award"><span class="award-red">${redsTxt}</span><span class="award-blue">${blueTxt}</span></td>\n      ${cells}\n      <td class="zs-side ${sizeCls}">${p.blue_size || \'\'}</td>\n      <td class="zs-side ${oeCls}">${p.blue_oe || \'\'}</td>\n      <td class="zs-side ${prCls}">${p.blue_prime || \'\'}</td>\n      ${roads}${zones}${wxs}\n    </tr>`;\n  });\n  body += \'</tbody>\';\n  return `<div class="zs-block" id="blueBlock">\n    <h3>双色球蓝球综合走势图</h3>\n    <div class="zs-scroll" id="blueScroll">\n      <div style="position:relative;display:inline-block;min-width:100%">\n        <svg class="zs-svg" id="blueSvg"></svg>\n        <table class="zs-table" id="blueTable">${head}${body}</table>\n      </div>\n    </div>\n  </div>`;\n}\n\nfunction renderRedTable(periods) {\n  // Removed: 红球 01-33 分布图易乱，页面只保留蓝球综合走势\n  return \'\';\n}\n\nfunction renderZouShi(data) {\n  const periods = ensureChronological(data.periods || [], data.order);\n  if (!periods.length) return \'<div class="trends-loading">暂无走势数据</div>\';\n  const note = \'<p class="trends-note">红球一期开出6个，分布图易乱，走势以蓝球为主</p>\';\n  return renderBlueTable(periods, data.wuxing_cols) + note;\n}\n\nfunction centerOf(el, relativeTo) {\n  const a = el.getBoundingClientRect();\n  const b = relativeTo.getBoundingClientRect();\n  return { x: a.left + a.width / 2 - b.left, y: a.top + a.height / 2 - b.top };\n}\n\nfunction drawPolyline(svg, points, color, width) {\n  if (points.length < 2) return;\n  const path = points.map((p, i) => (i ? \'L\' : \'M\') + p.x.toFixed(1) + \' \' + p.y.toFixed(1)).join(\' \');\n  const el = document.createElementNS(\'http://www.w3.org/2000/svg\', \'path\');\n  el.setAttribute(\'d\', path);\n  el.setAttribute(\'fill\', \'none\');\n  el.setAttribute(\'stroke\', color);\n  el.setAttribute(\'stroke-width\', String(width || 1.5));\n  el.setAttribute(\'stroke-linejoin\', \'round\');\n  el.setAttribute(\'stroke-linecap\', \'round\');\n  svg.appendChild(el);\n}\n\nfunction bindZouLines(root) {\n  if (!optLine) {\n    root.querySelectorAll(\'.zs-svg\').forEach(s => { s.innerHTML = \'\'; });\n    return;\n  }\n  requestAnimationFrame(() => {\n    // Blue zigzag across periods\n    const blueTable = root.querySelector(\'#blueTable\');\n    const blueSvg = root.querySelector(\'#blueSvg\');\n    if (blueTable && blueSvg) {\n      const wrap = blueSvg.parentElement;\n      blueSvg.setAttribute(\'width\', wrap.scrollWidth);\n      blueSvg.setAttribute(\'height\', wrap.scrollHeight);\n      blueSvg.style.width = wrap.scrollWidth + \'px\';\n      blueSvg.style.height = wrap.scrollHeight + \'px\';\n      blueSvg.innerHTML = \'\';\n      const hits = [...blueTable.querySelectorAll(\'[data-blue-hit]\')]\n        .sort((a, b) => Number(a.dataset.blueHit) - Number(b.dataset.blueHit));\n      const pts = hits.map(td => centerOf(td.querySelector(\'.zs-hit\') || td, wrap));\n      drawPolyline(blueSvg, pts, \'#111827\', 1.6);\n\n      // zone trend\n      const zh = [...blueTable.querySelectorAll(\'[data-zone-hit]\')]\n        .sort((a, b) => Number(a.dataset.zoneHit) - Number(b.dataset.zoneHit));\n      const zpts = zh.map(td => centerOf(td.querySelector(\'.zs-zone-hit\') || td, wrap));\n      drawPolyline(blueSvg, zpts, \'#2563eb\', 1.2);\n\n      // wuxing trend\n      const wh = [...blueTable.querySelectorAll(\'[data-wx-hit]\')]\n        .sort((a, b) => Number(a.dataset.wxHit) - Number(b.dataset.wxHit));\n      const wpts = wh.map(td => centerOf(td.querySelector(\'.zs-wx-hit\') || td, wrap));\n      drawPolyline(blueSvg, wpts, \'#7c3aed\', 1.1);\n    }\n\n      });\n}\n\nasync function loadTrends(force) {\n  const panel = document.getElementById(\'trendsPanel\');\n  const body = document.getElementById(\'trendsBody\');\n  const hint = document.getElementById(\'trendsHint\');\n  panel.classList.remove(\'hidden\');\n  const key = String(trendWindow);\n  if (!force && trendsLoadedFor === key && body.dataset.ready === \'1\') return;\n  body.innerHTML = \'<div class="trends-loading">走势加载中…</div>\';\n  if (hint) hint.textContent = `近 ${trendWindow} 期 · 上旧下新 · 蓝球折线连接各期开出号码`;\n  try {\n    const r = await fetch(\'/api/ssq/trends?\' + new URLSearchParams({ window: trendWindow }));\n    if (!r.ok) throw new Error(\'走势接口异常\');\n    const data = await r.json();\n    if (data.error) throw new Error(data.error);\n    lastTrendData = data;\n    const chron = ensureChronological(data.periods || [], data.order);\n    if (hint) {\n      const oldest = chron[0] ? chron[0].period : \'\';\n      const newest = chron.length ? chron[chron.length - 1].period : \'\';\n      hint.textContent = `近 ${data.window || trendWindow} 期（${oldest} → ${newest}，上旧下新）· 蓝球综合走势 · 蓝圈=开出 · 灰字=遗漏 · 折线串联各期蓝球`;\n    }\n    body.innerHTML = renderZouShi(data);\n    body.dataset.ready = \'1\';\n    trendsLoadedFor = key;\n    bindZouLines(body);\n  } catch (e) {\n    body.dataset.ready = \'0\';\n    body.innerHTML = `<div class="trends-error">走势加载失败：${String(e.message || e)}</div>`;\n  }\n}\n\nasync function load() {\n  try { renderTabs(); } catch (e) { console.warn(\'renderTabs\', e); }\n  try {\n    if (kind === \'ssq\') loadTrends(false); else hideTrends();\n  } catch (e) {\n    console.warn(\'trends\', e);\n    const tb = document.getElementById(\'trendsBody\');\n    if (tb) tb.innerHTML = \'<div class="trends-error">走势图异常：\' + String(e.message || e) + \'</div>\';\n  }\n  const list = document.getElementById(\'list\');\n  const pager = document.getElementById(\'pager\');\n  if (!list) return;\n  list.innerHTML = \'<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>\';\n  try {\n    const statsP = fetch(\'/api/stats?\' + new URLSearchParams({ type: kind })).then(r => r.json());\n    const drawsP = fetch(\'/api/draws?\' + new URLSearchParams({\n      type: kind, page, page_size: pageSize, period: periodQ || \'\'\n    })).then(r => r.json());\n    const [stats, draws] = await Promise.all([statsP, drawsP]);\n    if (stats.error) throw new Error(stats.error);\n    if (draws.error) throw new Error(draws.error);\n    renderStats(stats);\n    renderList(draws);\n    renderPager(draws);\n  } catch (e) {\n    list.innerHTML = `<div class="card" style="color:#b91c1c">加载失败：${String(e.message || e)}</div>`;\n    pager.innerHTML = \'\';\n  }\n}\n\nasync function openDrawer(period) {\n  const mask = document.getElementById(\'drawerMask\');\n  const drawer = document.getElementById(\'drawer\');\n  const title = document.getElementById(\'drawerTitle\');\n  const body = document.getElementById(\'drawerBody\');\n  title.textContent = `开奖明细 · ${period}`;\n  body.innerHTML = \'<div class="skeleton" style="height:120px"></div>\';\n  mask.classList.add(\'open\');\n  drawer.classList.add(\'open\');\n  drawer.setAttribute(\'aria-hidden\', \'false\');\n  try {\n    const r = await fetch(\'/api/ssq/detail?\' + new URLSearchParams({ period }));\n    const data = await r.json();\n    if (data.error) throw new Error(data.error);\n    const b = blueOf(data);\n    let prizeRows = (data.prizes || []).map(p => `\n      <tr>\n        <td>${p.name || p.prize_level || p.level || \'\'}</td>\n        <td>${p.bet_count != null ? p.bet_count : \'—\'}</td>\n        <td>${fmtMoney(p.prize_amount ?? p.amount)}</td>\n      </tr>`).join(\'\');\n    if (!prizeRows) prizeRows = \'<tr><td colspan="3">暂无奖级明细</td></tr>\';\n    let regions = \'\';\n    if (data.regions && data.regions.length) {\n      regions = \'<div class="region-list"><strong>一等奖地区</strong><ul>\' +\n        data.regions.map(x => `<li>${x.region || x.province || \'\'} · ${x.bet_count ?? x.count ?? \'\'} 注</li>`).join(\'\') +\n        \'</ul></div>\';\n    }\n    body.innerHTML = `\n      <div style="margin-bottom:12px">\n        <div style="color:#6b7280;font-size:.85rem;margin-bottom:6px">${data.draw_date || \'\'}${data.weekday ? \' · \' + data.weekday : \'\'}</div>\n        <div class="balls">${(data.reds||[]).map(n=>ballHtml(n,\'red\')).join(\'\')}${b!=null?ballHtml(b,\'blue\'):\'\'}</div>\n        <div style="margin-top:8px;font-size:.85rem;color:#6b7280">销量 ${fmtMoney(data.sales_amount ?? data.sales)} · 奖池 ${fmtMoney(data.prize_pool ?? data.pool)}</div>\n      </div>\n      <table class="prize-table">\n        <thead><tr><th>奖级</th><th>中奖注数</th><th>单注奖金</th></tr></thead>\n        <tbody>${prizeRows}</tbody>\n      </table>\n      ${regions}`;\n  } catch (e) {\n    body.innerHTML = `<div style="color:#b91c1c">加载失败：${String(e.message || e)}</div>`;\n  }\n}\n\nfunction closeDrawer() {\n  document.getElementById(\'drawerMask\').classList.remove(\'open\');\n  const drawer = document.getElementById(\'drawer\');\n  drawer.classList.remove(\'open\');\n  drawer.setAttribute(\'aria-hidden\', \'true\');\n}\n\ndocument.getElementById(\'btnSearch\').onclick = () => {\n  periodQ = document.getElementById(\'q\').value.trim();\n  page = 1;\n  load();\n};\ndocument.getElementById(\'btnReset\').onclick = () => {\n  document.getElementById(\'q\').value = \'\';\n  periodQ = \'\';\n  page = 1;\n  load();\n};\ndocument.getElementById(\'q\').addEventListener(\'keydown\', e => {\n  if (e.key === \'Enter\') document.getElementById(\'btnSearch\').click();\n});\ndocument.getElementById(\'drawerClose\').onclick = closeDrawer;\ndocument.getElementById(\'drawerMask\').onclick = closeDrawer;\ndocument.addEventListener(\'keydown\', e => { if (e.key === \'Escape\') closeDrawer(); });\n\ndocument.getElementById(\'trendWins\').onclick = (e) => {\n  const btn = e.target.closest(\'button[data-w]\');\n  if (!btn) return;\n  trendWindow = parseInt(btn.dataset.w, 10);\n  document.querySelectorAll(\'#trendWins button\').forEach(b => b.classList.toggle(\'active\', b === btn));\n  loadTrends(true);\n};\ndocument.getElementById(\'optGuide\').onchange = (e) => {\n  optGuide = e.target.checked;\n  if (lastTrendData) {\n    const body = document.getElementById(\'trendsBody\');\n    body.innerHTML = renderZouShi(lastTrendData);\n    bindZouLines(body);\n  }\n};\ndocument.getElementById(\'optLine\').onchange = (e) => {\n  optLine = e.target.checked;\n  const body = document.getElementById(\'trendsBody\');\n  if (body) bindZouLines(body);\n};\n\nwindow.addEventListener(\'resize\', () => {\n  const body = document.getElementById(\'trendsBody\');\n  if (body && kind === \'ssq\') bindZouLines(body);\n});\n\nload();\n</script>\n</body>\n</html>\n'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, data, "application/json; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        qs = parse_qs(u.query)

        if path in ("/", "/index.html"):
            html = HTML.replace(
                "数据文件：lottery.db",
                f"数据文件：{DB_PATH}",
            )
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path == "/api/stats":
            kind = qs.get("type", ["ssq"])[0]
            if kind not in TYPES:
                self._json({"error": "unknown type"}, 400)
                return
            try:
                self._json(get_stats(kind))
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return

        if path == "/api/draws":
            kind = qs.get("type", ["ssq"])[0]
            if kind not in TYPES:
                self._json({"error": "unknown type"}, 400)
                return
            try:
                page = int(qs.get("page", ["1"])[0])
                page_size = int(qs.get("page_size", ["20"])[0])
            except ValueError:
                self._json({"error": "bad page"}, 400)
                return
            period = qs.get("period", [None])[0]
            try:
                self._json(get_draws(kind, page, page_size, period))
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return

        if path == "/api/ssq/trends":
            try:
                window = int(qs.get("window", ["50"])[0])
            except ValueError:
                self._json({"error": "bad window"}, 400)
                return
            try:
                self._json(get_ssq_trends(window))
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return

        if path == "/api/ssq/detail":
            period = qs.get("period", [""])[0]
            try:
                self._json(get_ssq_detail(period))
            except ValueError as e:
                self._json({"error": str(e)}, 400)
            except Exception as e:
                self._json({"error": str(e)}, 500)
            return

        self._json({"error": "not found"}, 404)


def main():
    if not DB_PATH.is_file():
        raise SystemExit(f"DB not found: {DB_PATH}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Lottery viewer http://{HOST}:{PORT}  db={DB_PATH}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
