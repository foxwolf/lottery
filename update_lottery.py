# -*- coding: utf-8 -*-
"""Update D:\\develop\\agent\\lottery\\lottery.db with latest China lottery draws.
Sources: cwl.gov.cn (ssq, 3d) and sporttery.cn (dlt, pl3, pl5).
Safe to re-run: INSERT OR IGNORE by period.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(r"D:\develop\agent\lottery\lottery.db")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

CWL_URL = (
    "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
)
SPORTTERY_URL = (
    "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
)


def http_get_json(url: str, params: dict, referer: str) -> dict:
    qs = urllib.parse.urlencode(params)
    full = f"{url}?{qs}"
    req = urllib.request.Request(
        full,
        headers={
            "User-Agent": UA,
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def parse_money(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip().replace(",", "").replace("，", "")
    if not s or s in {"---", "-", "--", "null", "None"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    s = str(val).strip().replace(",", "").replace("，", "")
    if not s or s in {"---", "-", "--", ""}:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_cwl_date(date_str: str) -> str:
    # "2026-10-20(二)" -> "2026-10-20"
    m = re.match(r"(\d{4}-\d{2}-\d{2})", date_str or "")
    if not m:
        raise ValueError(f"bad date: {date_str!r}")
    return m.group(1)


def weekday_of(date_str: str) -> int:
    # Monday=0 .. Sunday=6 (datetime.weekday)
    return datetime.strptime(date_str, "%Y-%m-%d").weekday()


def issue_year_num(period: str) -> tuple[int, int]:
    period = str(period).strip()
    if len(period) >= 7 and period.isdigit():
        return int(period[:4]), int(period[4:])
    if len(period) == 5 and period.isdigit():
        yy = int(period[:2])
        year = 2000 + yy
        return year, int(period[2:])
    raise ValueError(f"unexpected period: {period!r}")


def normalize_dlt_period(draw_num: str) -> str:
    """Prefer 7-digit YYYYNNN to match majority of agent DB rows."""
    s = str(draw_num).strip()
    if len(s) == 7:
        return s
    if len(s) == 5:
        year, num = issue_year_num(s)
        return f"{year}{num:03d}"
    return s


def normalize_pl_period(draw_num: str) -> str:
    """排列三/五: sporttery 26279 -> 2026279."""
    s = str(draw_num).strip()
    if len(s) == 7:
        return s
    if len(s) == 5:
        year, num = issue_year_num(s)
        return f"{year}{num:03d}"
    return s


def red012_count(nums: list[int]) -> str:
    c = [0, 0, 0]
    for n in nums:
        c[n % 3] += 1
    return f"{c[0]},{c[1]},{c[2]}"


def zone_group_count_ssq(reds: list[int]) -> str:
    # historical field is almost always 组六 (6 unique reds always)
    return "组六"


def blue_type_range(blue: int) -> tuple[int, int]:
    btype = 1 if blue % 2 else 0
    # majority historical convention
    brange = 1 if blue <= 8 else 2
    return btype, brange


def d3_form(nums: list[int]) -> tuple[str, str, str, int]:
    a, b, c = nums
    s = a + b + c
    uniq = len(set(nums))
    if uniq == 1:
        ntype = "豹子"
    elif uniq == 2:
        ntype = "组三"
    else:
        ntype = "组六"
    # size: 0-4 small, 5-9 big
    size = "".join("大" if x >= 5 else "小" for x in nums)
    parity = "".join("奇" if x % 2 else "偶" for x in nums)
    return ntype, size, parity, s


def log_crawl(
    conn: sqlite3.Connection,
    lottery_type: str,
    source: str,
    start_period: Optional[str],
    end_period: Optional[str],
    record_count: int,
    status: str,
    error_message: Optional[str],
    duration: float,
) -> None:
    conn.execute(
        """
        INSERT INTO crawl_log(
            lottery_type, source, start_period, end_period,
            record_count, status, error_message, duration_seconds
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            lottery_type,
            source,
            start_period,
            end_period,
            record_count,
            status,
            error_message,
            round(duration, 3),
        ),
    )
    conn.commit()


def fetch_cwl(name: str, issue_count: int = 300) -> list[dict]:
    data = http_get_json(
        CWL_URL,
        {"name": name, "issueCount": str(issue_count), "issueStart": "", "issueEnd": "", "dayStart": "", "dayEnd": ""},
        referer="https://www.cwl.gov.cn/",
    )
    if data.get("state") != 0:
        raise RuntimeError(f"CWL {name} bad state: {data}")
    return data.get("result") or []


def fetch_sporttery(game_no: str, pages: int = 3, page_size: int = 100) -> list[dict]:
    items: list[dict] = []
    for page in range(1, pages + 1):
        data = http_get_json(
            SPORTTERY_URL,
            {
                "gameNo": game_no,
                "provinceId": "0",
                "pageSize": str(page_size),
                "isVerify": "1",
                "pageNo": str(page),
            },
            referer="https://www.lottery.gov.cn/",
        )
        if not data.get("success"):
            raise RuntimeError(f"sporttery {game_no} failed: {data}")
        batch = (data.get("value") or {}).get("list") or []
        if not batch:
            break
        items.extend(batch)
        time.sleep(0.35)
    return items


def max_period(conn: sqlite3.Connection, table: str) -> Optional[str]:
    # Prefer chronological max by draw_date then period
    row = conn.execute(
        f"SELECT period FROM {table} ORDER BY draw_date DESC, period DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def max_draw_date(conn: sqlite3.Connection, table: str) -> Optional[str]:
    row = conn.execute(f"SELECT MAX(draw_date) FROM {table}").fetchone()
    return row[0] if row else None


def update_ssq(conn: sqlite3.Connection) -> dict:
    t0 = time.time()
    source = CWL_URL + "?name=ssq"
    try:
        existing_max = max_period(conn, "ssq")
        rows = fetch_cwl("ssq", 200)
        inserted = 0
        periods = []
        for item in rows:
            period = str(item.get("code", "")).strip()
            if not period:
                continue
            if existing_max and period <= existing_max:
                # periods are YYYYNNN zero-padded; lexical works for same width
                continue
            draw_date = parse_cwl_date(item.get("date", ""))
            reds = [int(x) for x in str(item.get("red", "")).split(",") if x.strip()]
            if len(reds) != 6:
                continue
            reds_sorted = sorted(reds)
            blue = int(str(item.get("blue", "0")).strip())
            btype, brange = blue_type_range(blue)
            year, inum = issue_year_num(period)
            odd = sum(1 for r in reds_sorted if r % 2)
            prizes = {int(p.get("type")): p for p in (item.get("prizegrades") or []) if p.get("type") is not None}

            def prize_count(t: int) -> Optional[int]:
                p = prizes.get(t) or {}
                return parse_int(p.get("typenum"))

            def prize_amt(t: int) -> Optional[float]:
                p = prizes.get(t) or {}
                return parse_money(p.get("typemoney"))

            conn.execute(
                """
                INSERT OR IGNORE INTO ssq(
                    period, issue_year, issue_num, draw_date, weekday,
                    red_1, red_2, red_3, red_4, red_5, red_6,
                    red_sum, red_odd_count, red_even_count,
                    red_min, red_max, red_span,
                    blue, blue_type, blue_range,
                    sales_amount, prize_pool,
                    prize_1_count, prize_1_amount,
                    prize_2_count, prize_2_amount,
                    prize_3_count,
                    red_012_count, red_group_count,
                    red_seq_1, red_seq_2, red_seq_3, red_seq_4, red_seq_5, red_seq_6,
                    updated_at
                ) VALUES (
                    ?,?,?,?,?,
                    ?,?,?,?,?,?,
                    ?,?,?,
                    ?,?,?,
                    ?,?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,
                    ?,?,
                    ?,?,?,?,?,?,
                    CURRENT_TIMESTAMP
                )
                """,
                (
                    period, year, inum, draw_date, weekday_of(draw_date),
                    *reds_sorted,
                    sum(reds_sorted), odd, 6 - odd,
                    min(reds_sorted), max(reds_sorted), max(reds_sorted) - min(reds_sorted),
                    blue, btype, brange,
                    parse_money(item.get("sales")), parse_money(item.get("poolmoney")),
                    prize_count(1), prize_amt(1),
                    prize_count(2), prize_amt(2),
                    prize_count(3),
                    red012_count(reds_sorted), zone_group_count_ssq(reds_sorted),
                    *reds_sorted,
                ),
            )
            if conn.total_changes:
                # total_changes is cumulative; track via rowcount
                pass
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
                periods.append(period)
        conn.commit()
        periods.sort()
        log_crawl(
            conn, "ssq", source,
            periods[0] if periods else existing_max,
            periods[-1] if periods else existing_max,
            inserted, "success", None, time.time() - t0,
        )
        return {"ok": True, "inserted": inserted, "periods": periods, "api_latest": rows[0]["code"] if rows else None}
    except Exception as e:
        log_crawl(conn, "ssq", source, None, None, 0, "error", str(e), time.time() - t0)
        return {"ok": False, "error": str(e)}


def update_d3(conn: sqlite3.Connection) -> dict:
    t0 = time.time()
    source = CWL_URL + "?name=3d"
    try:
        existing_max = max_period(conn, "d3")
        rows = fetch_cwl("3d", 300)
        inserted = 0
        periods = []
        for item in rows:
            period = str(item.get("code", "")).strip()
            if not period:
                continue
            if existing_max and period <= existing_max:
                continue
            draw_date = parse_cwl_date(item.get("date", ""))
            nums = [int(x) for x in str(item.get("red", "")).split(",") if x.strip() != ""]
            if len(nums) != 3:
                continue
            year, inum = issue_year_num(period)
            ntype, size, parity, nsum = d3_form(nums)
            prizes = {int(p.get("type")): p for p in (item.get("prizegrades") or []) if p.get("type") is not None}

            def pc(t):
                return parse_int((prizes.get(t) or {}).get("typenum"))

            def pa(t):
                return parse_money((prizes.get(t) or {}).get("typemoney"))

            # CWL 3D types often empty in list API; leave NULL when empty
            conn.execute(
                """
                INSERT OR IGNORE INTO d3(
                    period, issue_year, issue_num, draw_date, weekday,
                    num_1, num_2, num_3, num_sum, num_type, num_size, num_parity,
                    single_count, single_amount, group3_count, group3_amount,
                    group6_count, group6_amount, sales_amount, prize_pool,
                    updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)
                """,
                (
                    period, year, inum, draw_date, weekday_of(draw_date),
                    nums[0], nums[1], nums[2], nsum, ntype, size, parity,
                    pc(1), pa(1), pc(2), pa(2), pc(3), pa(3),
                    parse_money(item.get("sales")), parse_money(item.get("poolmoney")) or None,
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
                periods.append(period)
        conn.commit()
        periods.sort()
        log_crawl(
            conn, "d3", source,
            periods[0] if periods else existing_max,
            periods[-1] if periods else existing_max,
            inserted, "success", None, time.time() - t0,
        )
        return {"ok": True, "inserted": inserted, "periods": periods, "api_latest": rows[0]["code"] if rows else None}
    except Exception as e:
        log_crawl(conn, "d3", source, None, None, 0, "error", str(e), time.time() - t0)
        return {"ok": False, "error": str(e)}


def _sporttery_prize_map(prize_list: list) -> dict:
    out = {}
    for p in prize_list or []:
        sort = parse_int(p.get("sort")) or 0
        out[sort] = p
        # also key by group if numeric
        g = parse_int(p.get("group"))
        if g is not None:
            out[g] = p
    return out


def update_dlt(conn: sqlite3.Connection) -> dict:
    t0 = time.time()
    source = SPORTTERY_URL + "?gameNo=85"
    try:
        max_date = max_draw_date(conn, "dlt") or "1970-01-01"
        # also collect existing periods for ignore
        existing = {r[0] for r in conn.execute("SELECT period FROM dlt")}
        # also add 5-digit variants
        existing5 = set()
        for p in list(existing):
            if len(p) == 7:
                existing5.add(p[2:])
            elif len(p) == 5:
                existing5.add(p)
        rows = fetch_sporttery("85", pages=2, page_size=100)
        inserted = 0
        periods = []
        for item in rows:
            raw_num = str(item.get("lotteryDrawNum", "")).strip()
            period = normalize_dlt_period(raw_num)
            draw_date = str(item.get("lotteryDrawTime", "")).strip()[:10]
            if not period or not draw_date:
                continue
            if draw_date <= max_date and (period in existing or raw_num in existing or raw_num in existing5 or period[2:] in existing5):
                continue
            if period in existing or raw_num in existing:
                continue
            balls = [int(x) for x in str(item.get("lotteryDrawResult", "")).split() if x.strip()]
            if len(balls) != 7:
                continue
            front = sorted(balls[:5])
            back = sorted(balls[5:])
            year, inum = issue_year_num(period)
            f_odd = sum(1 for x in front if x % 2)
            b_odd = sum(1 for x in back if x % 2)
            pm = _sporttery_prize_map(item.get("prizeLevelList"))

            def sc(sort):
                return parse_int((pm.get(sort) or {}).get("stakeCount"))

            def sa(sort):
                return parse_money((pm.get(sort) or {}).get("stakeAmountFormat")) or parse_money(
                    (pm.get(sort) or {}).get("stakeAmount")
                )

            conn.execute(
                """
                INSERT OR IGNORE INTO dlt(
                    period, issue_year, issue_num, draw_date, weekday,
                    front_1, front_2, front_3, front_4, front_5,
                    front_sum, front_odd_count, front_even_count,
                    front_min, front_max, front_span, front_012_count,
                    back_1, back_2, back_sum, back_odd_count, back_even_count,
                    sales_amount, prize_pool,
                    prize_1_count, prize_1_amount,
                    prize_2_count, prize_2_amount,
                    prize_3_count, prize_3_amount,
                    prize_4_count, prize_4_amount,
                    prize_5_count, prize_5_amount,
                    prize_1_add_count, prize_1_add_amount,
                    prize_2_add_count, prize_2_add_amount,
                    prize_3_add_count, prize_3_add_amount,
                    updated_at
                ) VALUES (
                    ?,?,?,?,?,
                    ?,?,?,?,?,
                    ?,?,?,
                    ?,?,?,?,
                    ?,?,?,?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    ?,?,
                    CURRENT_TIMESTAMP
                )
                """,
                (
                    period, year, inum, draw_date, weekday_of(draw_date),
                    *front,
                    sum(front), f_odd, 5 - f_odd,
                    min(front), max(front), max(front) - min(front), red012_count(front),
                    back[0], back[1], sum(back), b_odd, 2 - b_odd,
                    parse_money(item.get("totalSaleAmount")),
                    parse_money(item.get("poolBalanceAfterdraw")),
                    sc(101), sa(101),
                    sc(301), sa(301),
                    sc(501), sa(501),
                    sc(601), sa(601),
                    sc(701), sa(701),
                    sc(201), sa(201),
                    sc(401), sa(401),
                    # 三等追加 often absent; try sort 551 if present else NULL
                    sc(551), sa(551),
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
                periods.append(period)
                existing.add(period)
        conn.commit()
        periods.sort()
        log_crawl(
            conn, "dlt", source,
            periods[0] if periods else None,
            periods[-1] if periods else None,
            inserted, "success", None, time.time() - t0,
        )
        latest = normalize_dlt_period(rows[0]["lotteryDrawNum"]) if rows else None
        return {"ok": True, "inserted": inserted, "periods": periods, "api_latest": latest}
    except Exception as e:
        log_crawl(conn, "dlt", source, None, None, 0, "error", str(e), time.time() - t0)
        return {"ok": False, "error": str(e)}


def update_p3(conn: sqlite3.Connection) -> dict:
    t0 = time.time()
    source = SPORTTERY_URL + "?gameNo=35"
    try:
        existing_max = max_period(conn, "p3")
        existing = {r[0] for r in conn.execute("SELECT period FROM p3")}
        rows = fetch_sporttery("35", pages=3, page_size=100)
        inserted = 0
        periods = []
        for item in rows:
            raw = str(item.get("lotteryDrawNum", "")).strip()
            period = normalize_pl_period(raw)
            if not period or period in existing:
                continue
            if existing_max and period <= existing_max:
                continue
            draw_date = str(item.get("lotteryDrawTime", "")).strip()[:10]
            nums = [int(x) for x in str(item.get("lotteryDrawResult", "")).split() if x.strip()]
            if len(nums) != 3:
                continue
            year, inum = issue_year_num(period)
            ntype, size, parity, nsum = d3_form(nums)
            pm = _sporttery_prize_map(item.get("prizeLevelList"))

            def sc(sort):
                return parse_int((pm.get(sort) or {}).get("stakeCount"))

            def sa(sort):
                return parse_money((pm.get(sort) or {}).get("stakeAmountFormat")) or parse_money(
                    (pm.get(sort) or {}).get("stakeAmount")
                )

            conn.execute(
                """
                INSERT OR IGNORE INTO p3(
                    period, issue_year, issue_num, draw_date, weekday,
                    num_1, num_2, num_3, num_sum, num_type, num_size, num_parity,
                    single_count, single_amount, group3_count, group3_amount,
                    group6_count, group6_amount, sales_amount
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    period, year, inum, draw_date, weekday_of(draw_date),
                    nums[0], nums[1], nums[2], nsum, ntype, size, parity,
                    sc(10), sa(10), sc(20), sa(20), sc(30), sa(30),
                    parse_money(item.get("totalSaleAmount")),
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
                periods.append(period)
                existing.add(period)
        conn.commit()
        periods.sort()
        log_crawl(
            conn, "p3", source,
            periods[0] if periods else existing_max,
            periods[-1] if periods else existing_max,
            inserted, "success", None, time.time() - t0,
        )
        latest = normalize_pl_period(rows[0]["lotteryDrawNum"]) if rows else None
        return {"ok": True, "inserted": inserted, "periods": periods, "api_latest": latest}
    except Exception as e:
        log_crawl(conn, "p3", source, None, None, 0, "error", str(e), time.time() - t0)
        return {"ok": False, "error": str(e)}


def update_p5(conn: sqlite3.Connection) -> dict:
    t0 = time.time()
    source = SPORTTERY_URL + "?gameNo=350133"
    try:
        existing_max = max_period(conn, "p5")
        existing = {r[0] for r in conn.execute("SELECT period FROM p5")}
        rows = fetch_sporttery("350133", pages=3, page_size=100)
        inserted = 0
        periods = []
        for item in rows:
            raw = str(item.get("lotteryDrawNum", "")).strip()
            period = normalize_pl_period(raw)
            if not period or period in existing:
                continue
            if existing_max and period <= existing_max:
                continue
            draw_date = str(item.get("lotteryDrawTime", "")).strip()[:10]
            nums = [int(x) for x in str(item.get("lotteryDrawResult", "")).split() if x.strip()]
            if len(nums) != 5:
                continue
            year, inum = issue_year_num(period)
            pm = _sporttery_prize_map(item.get("prizeLevelList"))
            p = pm.get(10) or pm.get(1010) or {}
            conn.execute(
                """
                INSERT OR IGNORE INTO p5(
                    period, issue_year, issue_num, draw_date, weekday,
                    num_1, num_2, num_3, num_4, num_5,
                    num_sum, special_num,
                    prize_1_count, prize_1_amount, sales_amount
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    period, year, inum, draw_date, weekday_of(draw_date),
                    *nums,
                    sum(nums), None,
                    parse_int(p.get("stakeCount")),
                    parse_money(p.get("stakeAmountFormat")) or parse_money(p.get("stakeAmount")),
                    parse_money(item.get("totalSaleAmount")),
                ),
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
                periods.append(period)
                existing.add(period)
        conn.commit()
        periods.sort()
        log_crawl(
            conn, "p5", source,
            periods[0] if periods else existing_max,
            periods[-1] if periods else existing_max,
            inserted, "success", None, time.time() - t0,
        )
        latest = normalize_pl_period(rows[0]["lotteryDrawNum"]) if rows else None
        return {"ok": True, "inserted": inserted, "periods": periods, "api_latest": latest}
    except Exception as e:
        log_crawl(conn, "p5", source, None, None, 0, "error", str(e), time.time() - t0)
        return {"ok": False, "error": str(e)}



def refresh_ssq_mingxi(limit: int = 30) -> None:
    """Refresh recent SSQ prize details via update_ssq_mingxi.py logic."""
    try:
        from update_ssq_mingxi import (
            ensure_schema,
            periods_from_db,
            update_from_cjcp,
            update_from_cwl_fallback,
            log_crawl,
            DB_PATH as M_DB,
        )
        import sqlite3, time
        t0 = time.time()
        conn = sqlite3.connect(str(M_DB))
        ensure_schema(conn)
        periods = periods_from_db(conn, limit)
        ok, fail, errs = update_from_cjcp(conn, periods, 0.3)
        update_from_cwl_fallback(conn, max_pages=2, page_size=30, delay=0.2)
        log_crawl(conn, "cjcp+cwl(auto)", periods[-1], periods[0], ok,
                  "success" if ok else "error",
                  "; ".join(errs[:3]) if errs else None,
                  time.time() - t0)
        conn.close()
        print(f"ssq mingxi refreshed: ok={ok} fail={fail}")
    except Exception as e:
        print(f"ssq mingxi refresh skipped: {e}")

def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA busy_timeout=5000")
    summary = {}
    before = {}
    for t in ("ssq", "dlt", "d3", "p3", "p5"):
        before[t] = {
            "count": conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0],
            "max_period": max_period(conn, t),
            "max_date": max_draw_date(conn, t),
        }
    print("BEFORE:", json.dumps(before, ensure_ascii=False, indent=2))

    summary["ssq"] = update_ssq(conn)
    print("SSQ:", summary["ssq"])
    time.sleep(0.4)
    summary["d3"] = update_d3(conn)
    print("D3:", summary["d3"])
    time.sleep(0.4)
    summary["dlt"] = update_dlt(conn)
    print("DLT:", summary["dlt"])
    time.sleep(0.4)
    summary["p3"] = update_p3(conn)
    print("P3:", summary["p3"])
    time.sleep(0.4)
    summary["p5"] = update_p5(conn)
    print("P5:", summary["p5"])

    after = {}
    for t in ("ssq", "dlt", "d3", "p3", "p5"):
        after[t] = {
            "count": conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0],
            "max_period": max_period(conn, t),
            "max_date": max_draw_date(conn, t),
        }
    print("AFTER:", json.dumps(after, ensure_ascii=False, indent=2))
    Path(r"D:\develop\agent\lottery\_update_summary.json").write_text(
        json.dumps({"before": before, "after": after, "summary": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    conn.close()
    print("DONE")
    refresh_ssq_mingxi(limit=30)



if __name__ == "__main__":
    # after draws update, also refresh recent mingxi when run as script

    main()
