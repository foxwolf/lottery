# -*- coding: utf-8 -*-
"""Update lottery.db (repo root) with latest China lottery draws.
Primary: cwl.gov.cn (ssq, 3d) and sporttery.cn (dlt, pl3, pl5).
Fallback (GitHub Actions / blocked regions): datachart.500.com HTML tables.
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

DB_PATH = Path(__file__).resolve().parent / "lottery.db"
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
CHART500_BASE = "https://datachart.500.com/"
CHART500_SSQ = "ssq/history/newinc/history.php"
CHART500_DLT = "dlt/history/newinc/history.php"
CHART500_D3 = "sd/history/inc/history.php"
CHART500_P3 = "pls/history/inc/history.php"
CHART500_P5 = "plw/history/inc/history.php"


def http_get_bytes(url: str, referer: str, timeout: int = 45, attempts: int = 4) -> bytes:
    last_err: Optional[Exception] = None
    for attempt in range(attempts):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Referer": referer,
                "Accept": "text/html,application/json,text/plain,*/*",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            if attempt + 1 < attempts:
                time.sleep(min(8, 2 ** attempt))
    raise RuntimeError(f"GET failed after {attempts} tries: {url!r}: {last_err}")


def http_get_json(url: str, params: dict, referer: str) -> dict:
    qs = urllib.parse.urlencode(params)
    full = f"{url}?{qs}"
    raw = http_get_bytes(full, referer=referer)
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


def strip_html_cell(val: str) -> str:
    s = re.sub(r"<[^>]+>", "", val or "")
    return s.strip().replace("\xa0", "").replace("&nbsp;", "").strip()


def chart500_period(raw: str) -> str:
    s = str(raw).strip()
    if len(s) == 7 and s.isdigit():
        return s
    if len(s) == 5 and s.isdigit():
        return normalize_pl_period(s)
    return s


def fetch_chart500_rows(chart_path: str, limit: int = 200) -> list[list[str]]:
    """Fetch recent draw rows from datachart.500.com (newest first)."""
    qs = urllib.parse.urlencode({"limit": str(limit), "start": "0", "end": "9999999"})
    url = f"{CHART500_BASE}{chart_path}?{qs}"
    game = chart_path.split("/")[0]
    referer = f"{CHART500_BASE}{game}/history/"
    raw = http_get_bytes(url, referer=referer, timeout=60, attempts=5)
    html = raw.decode("gb2312", errors="replace")
    chunk_m = re.search(r'<tbody id="tdata">(.*?)</tbody>', html, re.S)
    chunk = chunk_m.group(1) if chunk_m else html
    out: list[list[str]] = []
    for row in re.findall(r'<tr class="t_tr\d">.*?</tr>', chunk, re.S):
        cells = [strip_html_cell(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        cells = [c for c in cells if c != ""]
        if not cells:
            continue
        if len(cells) >= 2 and cells[0].isdigit() and len(cells[0]) <= 2 and cells[1].isdigit():
            if len(cells[1]) >= 5:
                cells = cells[1:]
        if not cells[0].isdigit() or len(cells[0]) < 5:
            continue
        out.append(cells)
    if not out:
        raise RuntimeError(f"500.com empty table: {chart_path}")
    return out


def fetch_ssq_rows(issue_count: int = 200) -> tuple[list[dict], str]:
    try:
        return fetch_cwl("ssq", issue_count), CWL_URL + "?name=ssq"
    except Exception as cwl_err:
        rows500 = fetch_chart500_rows(CHART500_SSQ, limit=min(issue_count, 300))
        items: list[dict] = []
        for cells in rows500:
            if len(cells) < 15:
                continue
            period = chart500_period(cells[0])
            reds = [int(cells[i]) for i in range(1, 7)]
            blue = int(cells[7])
            draw_date = cells[14]
            items.append(
                {
                    "code": period,
                    "date": draw_date,
                    "red": ",".join(f"{x:02d}" for x in reds),
                    "blue": str(blue),
                    "sales": cells[8],
                    "poolmoney": cells[13],
                    "prizegrades": [
                        {"type": 1, "typenum": cells[9], "typemoney": cells[10]},
                        {"type": 2, "typenum": cells[11], "typemoney": cells[12]},
                    ],
                }
            )
        if not items:
            raise RuntimeError(f"500.com SSQ parse failed after CWL: {cwl_err}")
        return items, CHART500_BASE + CHART500_SSQ


def remote_ssq_latest_period() -> Optional[str]:
    rows500 = fetch_chart500_rows(CHART500_SSQ, limit=5)
    if not rows500:
        return None
    return chart500_period(rows500[0][0])


def fetch_d3_rows(issue_count: int = 300) -> tuple[list[dict], str]:
    try:
        return fetch_cwl("3d", issue_count), CWL_URL + "?name=3d"
    except Exception as cwl_err:
        rows500 = fetch_chart500_rows(CHART500_D3, limit=min(issue_count, 300))
        items: list[dict] = []
        for cells in rows500:
            if len(cells) < 9:
                continue
            period = chart500_period(cells[0])
            nums = [int(x) for x in cells[1].split() if x.strip().isdigit()]
            if len(nums) != 3:
                continue
            draw_date = cells[8]
            items.append(
                {
                    "code": period,
                    "date": draw_date,
                    "red": ",".join(str(x) for x in nums),
                    "sales": cells[3],
                    "poolmoney": None,
                    "prizegrades": [],
                }
            )
        if not items:
            raise RuntimeError(f"500.com 3D parse failed after CWL: {cwl_err}")
        return items, CHART500_BASE + CHART500_D3


def chart500_to_sporttery_dlt(cells: list[str]) -> Optional[dict]:
    if len(cells) < 14:
        return None
    period = chart500_period(cells[0])
    front = [int(cells[i]) for i in range(1, 6)]
    back = [int(cells[i]) for i in range(6, 8)]
    balls = front + back
    draw_date = cells[-1]
    return {
        "lotteryDrawNum": period,
        "lotteryDrawTime": draw_date,
        "lotteryDrawResult": " ".join(f"{x:02d}" for x in balls),
        "totalSaleAmount": cells[8],
        "poolBalanceAfterdraw": cells[-2],
        "prizeLevelList": [
            {"sort": 101, "stakeCount": cells[9], "stakeAmountFormat": cells[10]},
            {"sort": 301, "stakeCount": cells[11], "stakeAmountFormat": cells[12]},
        ],
    }


def fetch_dlt_rows(pages: int = 2, page_size: int = 100) -> tuple[list[dict], str]:
    limit = min(pages * page_size, 300)
    try:
        return fetch_sporttery("85", pages=pages, page_size=page_size), SPORTTERY_URL + "?gameNo=85"
    except Exception as st_err:
        rows500 = fetch_chart500_rows(CHART500_DLT, limit=limit)
        items: list[dict] = []
        for cells in rows500:
            item = chart500_to_sporttery_dlt(cells)
            if item:
                items.append(item)
        if not items:
            raise RuntimeError(f"500.com DLT parse failed after sporttery: {st_err}")
        return items, CHART500_BASE + CHART500_DLT


def chart500_to_sporttery_p3(cells: list[str]) -> Optional[dict]:
    if len(cells) < 11:
        return None
    period = chart500_period(cells[0])
    nums = [int(x) for x in cells[1].split() if x.strip().isdigit()]
    if len(nums) != 3:
        return None
    return {
        "lotteryDrawNum": period,
        "lotteryDrawTime": cells[-1],
        "lotteryDrawResult": " ".join(str(x) for x in nums),
        "totalSaleAmount": cells[3],
        "prizeLevelList": [
            {"sort": 10, "stakeCount": cells[4], "stakeAmountFormat": cells[5]},
            {"sort": 20, "stakeCount": cells[6], "stakeAmountFormat": cells[7]},
            {"sort": 30, "stakeCount": cells[8], "stakeAmountFormat": cells[9]},
        ],
    }


def fetch_p3_rows(pages: int = 3, page_size: int = 100) -> tuple[list[dict], str]:
    limit = min(pages * page_size, 300)
    try:
        return fetch_sporttery("35", pages=pages, page_size=page_size), SPORTTERY_URL + "?gameNo=35"
    except Exception as st_err:
        rows500 = fetch_chart500_rows(CHART500_P3, limit=limit)
        items = [chart500_to_sporttery_p3(c) for c in rows500]
        items = [x for x in items if x]
        if not items:
            raise RuntimeError(f"500.com P3 parse failed after sporttery: {st_err}")
        return items, CHART500_BASE + CHART500_P3


def chart500_to_sporttery_p5(cells: list[str]) -> Optional[dict]:
    if len(cells) < 5:
        return None
    period = chart500_period(cells[0])
    nums = [int(x) for x in cells[1].split() if x.strip().isdigit()]
    if len(nums) != 5:
        return None
    return {
        "lotteryDrawNum": period,
        "lotteryDrawTime": cells[-1],
        "lotteryDrawResult": " ".join(str(x) for x in nums),
        "totalSaleAmount": cells[3],
        "prizeLevelList": [],
    }


def fetch_p5_rows(pages: int = 3, page_size: int = 100) -> tuple[list[dict], str]:
    limit = min(pages * page_size, 300)
    try:
        return (
            fetch_sporttery("350133", pages=pages, page_size=page_size),
            SPORTTERY_URL + "?gameNo=350133",
        )
    except Exception as st_err:
        rows500 = fetch_chart500_rows(CHART500_P5, limit=limit)
        items = [chart500_to_sporttery_p5(c) for c in rows500]
        items = [x for x in items if x]
        if not items:
            raise RuntimeError(f"500.com P5 parse failed after sporttery: {st_err}")
        return items, CHART500_BASE + CHART500_P5


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
        rows, source = fetch_ssq_rows(200)
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
        return {"ok": True, "inserted": inserted, "periods": periods, "api_latest": rows[0]["code"] if rows else None, "source": source}
    except Exception as e:
        log_crawl(conn, "ssq", source, None, None, 0, "error", str(e), time.time() - t0)
        return {"ok": False, "error": str(e), "source": source}


def update_d3(conn: sqlite3.Connection) -> dict:
    t0 = time.time()
    source = CWL_URL + "?name=3d"
    try:
        existing_max = max_period(conn, "d3")
        rows, source = fetch_d3_rows(300)
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
        rows, source = fetch_dlt_rows(pages=2, page_size=100)
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
        rows, source = fetch_p3_rows(pages=3, page_size=100)
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
        rows, source = fetch_p5_rows(pages=3, page_size=100)
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


def validate_ssq_up_to_date(conn: sqlite3.Connection, summary: dict) -> None:
    ssq = summary.get("ssq") or {}
    if not ssq.get("ok"):
        raise SystemExit(f"SSQ update failed: {ssq.get('error')}")
    local = max_period(conn, "ssq")
    try:
        remote = remote_ssq_latest_period()
    except Exception as e:
        raise SystemExit(f"SSQ remote check failed (500.com): {e}") from e
    if remote and local and remote > local:
        raise SystemExit(
            f"SSQ still behind public draw: db={local} remote={remote} fetch_source={ssq.get('source')}"
        )
    print(f"SSQ validation OK: db={local} remote={remote}")


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
    (Path(__file__).resolve().parent / "_update_summary.json").write_text(
        json.dumps({"before": before, "after": after, "summary": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    validate_ssq_up_to_date(conn, summary)
    conn.close()
    print("DONE")
    refresh_ssq_mingxi(limit=30)



if __name__ == "__main__":
    # after draws update, also refresh recent mingxi when run as script

    main()
