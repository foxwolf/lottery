# -*- coding: utf-8 -*-
"""Fetch SSQ prize detail (开奖明细) into lottery.db.

Primary: https://www.cjcp.cn/kaijiang/ssq{period}.html
  (detail pages linked from ssqmingxi.html)
Fallback/regions: cwl.gov.cn findDrawNotice prizegrades + content.
CI fallback: datachart.500.com (via ssq draw row / history.php) for 一/二等奖;
  三至六等奖仅写入固定单注奖金（不臆造注数）；一等奖地域仍依赖 cwl/cjcp。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).resolve().parent / "lottery.db"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
CJCP_PERIOD_URL = "https://www.cjcp.cn/kaijiang/ssq{period}.html"
CWL_URL = (
    "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
)

LEVEL_NAMES = {
    1: "一等奖",
    2: "二等奖",
    3: "三等奖",
    4: "四等奖",
    5: "五等奖",
    6: "六等奖",
    7: "福运奖",
}
NAME_TO_LEVEL = {v: k for k, v in LEVEL_NAMES.items()}
WIN_COND = {
    1: "6+1",
    2: "6+0",
    3: "5+1",
    4: "5+0 / 4+1",
    5: "4+0 / 3+1",
    6: "2+1 / 1+1 / 0+1",
    7: "3+0",
}
# 三至六等奖及福运奖单注奖金为规则固定值（仅 fallback 补全奖级行，注数仍为空）
FIXED_GRADE_AMOUNT = {3: 3000.0, 4: 200.0, 5: 10.0, 6: 5.0, 7: 5.0}


def http_get_bytes(
    url: str, referer: str, timeout: int = 45, attempts: int = 4
) -> bytes:
    last_err: Optional[Exception] = None
    for attempt in range(attempts):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Referer": referer,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            if attempt + 1 < attempts:
                time.sleep(min(8, 2**attempt))
    raise RuntimeError(f"GET failed after {attempts} tries: {url!r}: {last_err}")


def http_get_json(url: str, params: dict, referer: str) -> dict:
    qs = urllib.parse.urlencode(params)
    raw = http_get_bytes(f"{url}?{qs}", referer)
    return json.loads(raw.decode("utf-8"))


def parse_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    s = str(val).strip().replace(",", "").replace("注", "").replace("元", "")
    if not s or s in {"---", "-", "--", ""}:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_money(val: Any) -> Optional[float]:
    if val is None:
        return None
    s = str(val).strip().replace(",", "").replace("元", "")
    if not s or s in {"---", "-", "--", ""}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ssq_prize_detail (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          period TEXT NOT NULL,
          prize_level INTEGER NOT NULL,
          prize_name TEXT NOT NULL,
          bet_count INTEGER,
          amount REAL,
          win_condition TEXT,
          source TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(period, prize_level)
        );
        CREATE INDEX IF NOT EXISTS idx_ssq_prize_detail_period
          ON ssq_prize_detail(period);
        CREATE TABLE IF NOT EXISTS ssq_prize_region (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          period TEXT NOT NULL,
          prize_level INTEGER NOT NULL DEFAULT 1,
          region TEXT NOT NULL,
          bet_count INTEGER,
          source TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(period, prize_level, region)
        );
        CREATE INDEX IF NOT EXISTS idx_ssq_prize_region_period
          ON ssq_prize_region(period);
        """
    )


def upsert_detail(
    conn: sqlite3.Connection,
    period: str,
    level: int,
    bet_count: Optional[int],
    amount: Optional[float],
    source: str,
) -> None:
    conn.execute(
        """
        INSERT INTO ssq_prize_detail
          (period, prize_level, prize_name, bet_count, amount, win_condition, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(period, prize_level) DO UPDATE SET
          prize_name=excluded.prize_name,
          bet_count=excluded.bet_count,
          amount=excluded.amount,
          win_condition=excluded.win_condition,
          source=excluded.source,
          updated_at=CURRENT_TIMESTAMP
        """,
        (
            period,
            level,
            LEVEL_NAMES[level],
            bet_count,
            amount,
            WIN_COND.get(level),
            source,
        ),
    )


def parse_cjcp_period_html(html: str, period: str) -> list[dict]:
    m = re.search(r'<tbody[^>]*id=["\']info["\'][^>]*>(.*?)</tbody>', html, re.S | re.I)
    block = m.group(1) if m else ""
    if not block:
        m2 = re.search(r"(一等奖[\s\S]{0,2500}?六等奖[\s\S]{0,400}?)</tbody>", html)
        block = m2.group(1) if m2 else html

    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S | re.I):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)
        if len(cells) < 3:
            continue
        name = re.sub(r"<[^>]+>", "", cells[0]).strip()
        level = NAME_TO_LEVEL.get(name)
        if not level:
            continue
        bet = parse_int(re.sub(r"<[^>]+>", "", cells[1]))
        amt = parse_money(re.sub(r"<[^>]+>", "", cells[2]))
        rows.append(
            {
                "period": period,
                "prize_level": level,
                "prize_name": name,
                "bet_count": bet,
                "amount": amt,
            }
        )
    return rows


def fetch_cjcp_period(period: str) -> list[dict]:
    url = CJCP_PERIOD_URL.format(period=period)
    raw = http_get_bytes(url, "https://www.cjcp.cn/kaijiang/ssqmingxi.html")
    html = raw.decode("gb18030", errors="replace")
    rows = parse_cjcp_period_html(html, period)
    if not rows:
        raise ValueError(f"no prize rows parsed for {period}")
    return rows


def parse_regions(content: str) -> list[tuple[str, int]]:
    if not content:
        return []
    out = []
    for m in re.finditer(r"([\u4e00-\u9fff]{2,8})(\d+)注", content):
        region, n = m.group(1), int(m.group(2))
        if region.startswith("共"):
            continue
        out.append((region, n))
    return out


def fetch_cwl_batch(page_no: int, page_size: int = 30) -> list[dict]:
    return (
        http_get_json(
            CWL_URL,
            {
                "name": "ssq",
                "issueCount": "",
                "issueStart": "",
                "issueEnd": "",
                "dayStart": "",
                "dayEnd": "",
                "pageNo": str(page_no),
                "pageSize": str(page_size),
                "week": "",
                "systemType": "PC",
            },
            "https://www.cwl.gov.cn/ygkj/wqkjgg/ssq/",
        ).get("result")
        or []
    )


def upsert_regions(
    conn: sqlite3.Connection, period: str, regions: list[tuple[str, int]], source: str
) -> None:
    conn.execute(
        "DELETE FROM ssq_prize_region WHERE period=? AND prize_level=1", (period,)
    )
    for region, n in regions:
        conn.execute(
            """
            INSERT OR REPLACE INTO ssq_prize_region
              (period, prize_level, region, bet_count, source)
            VALUES (?, 1, ?, ?, ?)
            """,
            (period, region, n, source),
        )


def periods_from_db(conn: sqlite3.Connection, limit: Optional[int]) -> list[str]:
    sql = "SELECT period FROM ssq ORDER BY period DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in conn.execute(sql)]


def update_from_cjcp(
    conn: sqlite3.Connection, periods: list[str], delay: float
) -> tuple[int, int, list[str]]:
    ok = 0
    fail = 0
    errors: list[str] = []
    for i, period in enumerate(periods, 1):
        try:
            rows = fetch_cjcp_period(period)
            for row in rows:
                upsert_detail(
                    conn,
                    period,
                    row["prize_level"],
                    row["bet_count"],
                    row["amount"],
                    "cjcp",
                )
            conn.commit()
            ok += 1
            if i % 10 == 0 or i == len(periods):
                print(f"  cjcp {i}/{len(periods)} ok={ok} fail={fail} last={period}")
        except Exception as e:
            fail += 1
            errors.append(f"{period}: {e}")
            print(f"  cjcp FAIL {period}: {e}")
        time.sleep(delay)
    return ok, fail, errors


def update_from_cwl_fallback(
    conn: sqlite3.Connection, max_pages: int, page_size: int, delay: float
) -> tuple[int, int]:
    filled_periods = 0
    region_periods = 0
    for page in range(1, max_pages + 1):
        try:
            items = fetch_cwl_batch(page, page_size)
        except Exception as e:
            print(f"  cwl page {page} FAIL: {e}")
            break
        if not items:
            break
        for item in items:
            period = str(item.get("code") or "").strip()
            if not period:
                continue
            prizes = item.get("prizegrades") or []
            changed = False
            for p in prizes:
                try:
                    level = int(p.get("type"))
                except (TypeError, ValueError):
                    continue
                if level < 1 or level > 6:
                    continue
                bet = parse_int(p.get("typenum"))
                amt = parse_money(p.get("typemoney"))
                if bet is None and amt is None:
                    continue
                existing = conn.execute(
                    "SELECT source FROM ssq_prize_detail WHERE period=? AND prize_level=?",
                    (period, level),
                ).fetchone()
                if existing and existing[0] == "cjcp":
                    continue
                upsert_detail(conn, period, level, bet, amt, "cwl")
                changed = True
            regions = parse_regions(item.get("content") or "")
            if regions:
                upsert_regions(conn, period, regions, "cwl")
                region_periods += 1
            if changed:
                filled_periods += 1
        conn.commit()
        print(f"  cwl page {page}: got {len(items)} periods")
        time.sleep(delay)
    return filled_periods, region_periods


def detail_source(conn: sqlite3.Connection, period: str, level: int) -> Optional[str]:
    row = conn.execute(
        "SELECT source FROM ssq_prize_detail WHERE period=? AND prize_level=?",
        (period, level),
    ).fetchone()
    return row[0] if row else None


def should_skip_detail_upsert(conn: sqlite3.Connection, period: str, level: int) -> bool:
    src = detail_source(conn, period, level)
    return bool(src and src == "cjcp")


def fill_fixed_lower_grades(
    conn: sqlite3.Connection, period: str, source: str
) -> None:
    """Insert fixed-amount rows for grades 3–7 when missing (no bet counts)."""
    for level in (3, 4, 5, 6, 7):
        if should_skip_detail_upsert(conn, period, level):
            continue
        existing = conn.execute(
            "SELECT 1 FROM ssq_prize_detail WHERE period=? AND prize_level=?",
            (period, level),
        ).fetchone()
        if existing:
            continue
        upsert_detail(
            conn,
            period,
            level,
            None,
            FIXED_GRADE_AMOUNT.get(level),
            source,
        )


def update_from_ssq_draw(conn: sqlite3.Connection, periods: list[str]) -> int:
    """Copy 一/二等奖 from ssq table (filled by update_lottery / 500.com)."""
    filled = 0
    for period in periods:
        row = conn.execute(
            """
            SELECT prize_1_count, prize_1_amount, prize_2_count, prize_2_amount
            FROM ssq WHERE period=?
            """,
            (period,),
        ).fetchone()
        if not row:
            continue
        p1c, p1a, p2c, p2a = row
        if all(v is None for v in (p1c, p1a, p2c, p2a)):
            continue
        changed = False
        for level, bet, amt in (
            (1, p1c, p1a),
            (2, p2c, p2a),
        ):
            if bet is None and amt is None:
                continue
            if should_skip_detail_upsert(conn, period, level):
                continue
            upsert_detail(conn, period, level, bet, amt, "chart500")
            changed = True
        if changed:
            fill_fixed_lower_grades(conn, period, "chart500")
            filled += 1
            conn.commit()
    return filled


def update_from_chart500(
    conn: sqlite3.Connection, periods: list[str], delay: float
) -> tuple[int, int, list[str]]:
    """Fetch 一/二等奖 from datachart.500.com for periods still missing detail."""
    from update_lottery import CHART500_SSQ, chart500_period, fetch_chart500_rows

    need = [
        p
        for p in periods
        if not conn.execute(
            "SELECT 1 FROM ssq_prize_detail WHERE period=? AND prize_level=1",
            (p,),
        ).fetchone()
    ]
    if not need:
        return 0, 0, []

    ok = 0
    fail = 0
    errors: list[str] = []
    try:
        rows500 = fetch_chart500_rows(
            CHART500_SSQ, limit=min(max(len(need) + 15, 30), 300)
        )
    except Exception as e:
        return 0, len(need), [f"chart500 batch: {e}"]

    by_period: dict[str, list[str]] = {}
    for cells in rows500:
        if len(cells) < 14:
            continue
        db_period = chart500_period(cells[0])
        by_period[db_period] = cells

    for period in need:
        cells = by_period.get(period)
        if not cells:
            fail += 1
            errors.append(f"{period}: not in chart500 batch")
            continue
        try:
            bet1 = parse_int(cells[9] if len(cells) > 9 else None)
            amt1 = parse_money(cells[10] if len(cells) > 10 else None)
            bet2 = parse_int(cells[11] if len(cells) > 11 else None)
            amt2 = parse_money(cells[12] if len(cells) > 12 else None)
            if bet1 is None and amt1 is None and bet2 is None and amt2 is None:
                raise ValueError("no grade 1/2 data in row")
            for level, bet, amt in ((1, bet1, amt1), (2, bet2, amt2)):
                if bet is None and amt is None:
                    continue
                if should_skip_detail_upsert(conn, period, level):
                    continue
                upsert_detail(conn, period, level, bet, amt, "chart500")
            fill_fixed_lower_grades(conn, period, "chart500")
            conn.commit()
            ok += 1
        except Exception as e:
            fail += 1
            errors.append(f"{period}: {e}")
            print(f"  chart500 FAIL {period}: {e}")
        time.sleep(max(0.15, delay * 0.5))
    return ok, fail, errors


def latest_ssq_period(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT MAX(period) FROM ssq").fetchone()
    return row[0] if row and row[0] else None


def period_prize_detail_count(conn: sqlite3.Connection, period: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM ssq_prize_detail WHERE period=?", (period,)
    ).fetchone()[0]


def validate_latest_prize_detail(conn: sqlite3.Connection) -> None:
    latest = latest_ssq_period(conn)
    if not latest:
        raise SystemExit("validate: no ssq periods in database")
    n = period_prize_detail_count(conn, latest)
    if n <= 0:
        raise SystemExit(
            f"validate: latest SSQ period {latest} has no ssq_prize_detail rows "
            "(cjcp/cwl/chart500 all failed or skipped)"
        )
    print(f"validate OK: latest={latest} prize_detail_rows={n}")


def log_crawl(
    conn: sqlite3.Connection,
    source: str,
    start: str,
    end: str,
    count: int,
    status: str,
    error: Optional[str],
    duration: float,
) -> None:
    conn.execute(
        """
        INSERT INTO crawl_log
          (lottery_type, source, start_period, end_period, record_count, status, error_message, duration_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("ssq_mingxi", source, start, end, count, status, error, duration),
    )
    conn.commit()


def main() -> None:
    ap = argparse.ArgumentParser(description="Update SSQ prize detail")
    ap.add_argument("--limit", type=int, default=120, help="最近 N 期 (0=全部)")
    ap.add_argument("--delay", type=float, default=0.35)
    ap.add_argument("--cwl-pages", type=int, default=5)
    ap.add_argument("--skip-cjcp", action="store_true")
    ap.add_argument("--skip-cwl", action="store_true")
    ap.add_argument("--skip-chart500", action="store_true")
    ap.add_argument(
        "--no-validate-latest",
        action="store_true",
        help="do not fail when latest period lacks prize detail",
    )
    args = ap.parse_args()

    t0 = time.time()
    conn = sqlite3.connect(str(DB_PATH))
    ensure_schema(conn)

    limit = None if args.limit == 0 else args.limit
    periods = periods_from_db(conn, limit)
    if not periods:
        print("no ssq periods in db")
        return

    print(f"cjcp periods: {len(periods)} ({periods[-1]} .. {periods[0]})")
    cjcp_ok = cjcp_fail = 0
    errors: list[str] = []
    if not args.skip_cjcp:
        cjcp_ok, cjcp_fail, errors = update_from_cjcp(conn, periods, args.delay)

    cwl_filled = cwl_regions = 0
    if not args.skip_cwl:
        print(f"cwl fallback/regions: up to {args.cwl_pages} pages")
        cwl_filled, cwl_regions = update_from_cwl_fallback(
            conn, args.cwl_pages, 30, max(0.2, args.delay * 0.5)
        )

    ssq_draw_filled = update_from_ssq_draw(conn, periods)
    print(f"ssq draw sync (chart500 columns): filled={ssq_draw_filled}")

    chart_ok = chart_fail = 0
    chart_errors: list[str] = []
    if not args.skip_chart500:
        print("chart500 fallback for periods missing grade-1 detail")
        chart_ok, chart_fail, chart_errors = update_from_chart500(
            conn, periods, args.delay
        )
        if chart_errors:
            errors.extend(chart_errors[:10])

    detail_count = conn.execute("SELECT COUNT(*) FROM ssq_prize_detail").fetchone()[0]
    period_count = conn.execute(
        "SELECT COUNT(DISTINCT period) FROM ssq_prize_detail"
    ).fetchone()[0]
    print(
        f"done: cjcp_ok={cjcp_ok} cjcp_fail={cjcp_fail} "
        f"cwl_filled={cwl_filled} cwl_regions={cwl_regions} "
        f"ssq_draw_filled={ssq_draw_filled} chart500_ok={chart_ok} chart500_fail={chart_fail} "
        f"detail_rows={detail_count} periods_with_detail={period_count}"
    )

    latest = latest_ssq_period(conn)
    latest_rows = period_prize_detail_count(conn, latest) if latest else 0
    status = "success" if latest and latest_rows > 0 else "error"
    err_msg = "; ".join(errors[:8]) if errors else None
    if chart_errors and len(err_msg or "") < 400:
        extra = "; ".join(chart_errors[:3])
        err_msg = f"{err_msg}; {extra}" if err_msg else extra

    log_crawl(
        conn,
        "cjcp+cwl+chart500",
        periods[-1],
        periods[0],
        period_count,
        status,
        err_msg,
        time.time() - t0,
    )

    if not args.no_validate_latest:
        validate_latest_prize_detail(conn)

    conn.close()
    if status != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()