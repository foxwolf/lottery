#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare watch_pick.json against latest SSQ draw; write markdown + optional state."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "lottery.db"
PICK_PATH = ROOT / "watch_pick.json"
TZ8 = timezone(timedelta(hours=8))


def prize_level(red_hits: int, blue_hit: bool) -> str:
    if red_hits == 6 and blue_hit:
        return "一等奖"
    if red_hits == 6:
        return "二等奖"
    if red_hits == 5 and blue_hit:
        return "三等奖"
    if red_hits == 5 or (red_hits == 4 and blue_hit):
        return "四等奖"
    if red_hits == 4 or (red_hits == 3 and blue_hit):
        return "五等奖"
    if blue_hit and red_hits <= 2:
        return "六等奖"
    return "未中奖"


def load_pick() -> dict:
    data = json.loads(PICK_PATH.read_text(encoding="utf-8"))
    red = [f"{int(x):02d}" for x in data["red"]]
    blue = f"{int(data['blue']):02d}"
    return {"red": red, "blue": blue, "raw": data}


def latest_ssq(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        """
        SELECT period, draw_date, red_1, red_2, red_3, red_4, red_5, red_6, blue
        FROM ssq ORDER BY period DESC LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    period, draw_date, *reds, blue = row
    reds_fmt = [f"{int(x):02d}" for x in reds]
    return {
        "period": str(period),
        "draw_date": str(draw_date),
        "red": reds_fmt,
        "blue": f"{int(blue):02d}",
    }


def compare(pick: dict, draw: dict) -> dict:
    hits = sorted(set(pick["red"]) & set(draw["red"]))
    blue_hit = pick["blue"] == draw["blue"]
    level = prize_level(len(hits), blue_hit)
    return {
        "red_hits": len(hits),
        "hit_reds": hits,
        "blue_hit": blue_hit,
        "level": level,
    }


def render_md(pick: dict, draw: dict, cmp: dict, mode: str, skipped: bool = False) -> str:
    now = datetime.now(TZ8).strftime("%Y-%m-%d %H:%M:%S Asia/Shanghai")
    lines = [
        f"# 双色球对照（{mode}）",
        "",
        f"- 生成时间：{now}",
        f"- 期号：**{draw['period']}**（开奖日 {draw['draw_date']}）",
        f"- 开奖红：{' '.join(draw['red'])}　蓝：**{draw['blue']}**",
        f"- 守号红：{' '.join(pick['red'])}　蓝：**{pick['blue']}**",
        f"- 红球命中 **{cmp['red_hits']}**（{(' '.join(cmp['hit_reds']) if cmp['hit_reds'] else '无')}），"
        f"蓝球{'命中' if cmp['blue_hit'] else '未中'} → **{cmp['level']}**",
        "",
        "_娱乐核对，不构成投注建议。_",
    ]
    if skipped:
        lines.insert(2, f"- 状态：本期已在 `_next_day_notified.json` 记录过，本次仅更新库/摘要，不重复当作「首次次日通知」。")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["next-day", "draw-notify"], required=True)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--state", type=Path, default=ROOT / "_next_day_notified.json")
    ap.add_argument("--update-state", action="store_true",
                    help="next-day: write state when this period not yet recorded")
    args = ap.parse_args()

    pick = load_pick()
    conn = sqlite3.connect(str(DB_PATH))
    draw = latest_ssq(conn)
    conn.close()
    if not draw:
        raise SystemExit("no ssq rows in lottery.db")

    cmp = compare(pick, draw)
    skipped = False
    if args.mode == "next-day" and args.state.exists():
        try:
            st = json.loads(args.state.read_text(encoding="utf-8"))
            if str(st.get("ssq_period")) == draw["period"]:
                skipped = True
        except Exception:
            pass

    md = render_md(pick, draw, cmp, args.mode, skipped=skipped)
    out = args.out
    if out is None:
        out = ROOT / ("_draw_notify.md" if args.mode == "draw-notify" else "_next_day_summary.md")
    out.write_text(md, encoding="utf-8")
    print(md)

    # machine-readable sidecar for workflows
    payload = {
        "mode": args.mode,
        "period": draw["period"],
        "draw_date": draw["draw_date"],
        "draw_red": draw["red"],
        "draw_blue": draw["blue"],
        "pick_red": pick["red"],
        "pick_blue": pick["blue"],
        "red_hits": cmp["red_hits"],
        "hit_reds": cmp["hit_reds"],
        "blue_hit": cmp["blue_hit"],
        "level": cmp["level"],
        "already_notified": skipped,
    }
    (out.with_suffix(".json")).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if args.mode == "next-day" and args.update_state and not skipped:
        state = {
            "routine": "ssq-next-day-boot-update",
            "ssq_period": draw["period"],
            "draw_date": draw["draw_date"],
            "notified_at": datetime.now(TZ8).isoformat(),
            "source": "github-actions-next-day",
            "level": cmp["level"],
            "red_hits": cmp["red_hits"],
            "blue_hit": cmp["blue_hit"],
        }
        args.state.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"updated state {args.state}")


if __name__ == "__main__":
    main()
