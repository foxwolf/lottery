# -*- coding: utf-8 -*-
import sqlite3, itertools, statistics, json, sys
from collections import Counter
from pathlib import Path
import numpy as np

sys.stdout.reconfigure(line_buffering=True)

DB = r'D:\develop\agent\lottery\lottery.db'
OLD1 = (5, 11, 16, 18, 27, 28)
OLD1_BLUE = 8
OLD2 = (8, 9, 14, 17, 24, 32)
OLD2_BLUE = 1
PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31}

def wuxing(n):
    d = n % 10
    if d in (4, 9): return 'jin'
    if d in (3, 8): return 'mu'
    if d in (1, 6): return 'shui'
    if d in (2, 7): return 'huo'
    return 'tu'

WX_CN = {'jin': '金', 'mu': '木', 'shui': '水', 'huo': '火', 'tu': '土'}

def zone4(n):
    if n <= 8: return 0
    if n <= 16: return 1
    if n <= 24: return 2
    return 3

con = sqlite3.connect(DB)
rows = con.execute(
    'SELECT period, draw_date, red_1,red_2,red_3,red_4,red_5,red_6, blue FROM ssq ORDER BY period ASC'
).fetchall()
con.close()
N = len(rows)
draws = []
hist = np.zeros((N, 34), dtype=np.uint8)  # index 1..33
for i, r in enumerate(rows):
    reds = tuple(sorted(r[2:8]))
    draws.append({'period': r[0], 'date': r[1], 'reds': reds, 'blue': r[8]})
    for x in reds:
        hist[i, x] = 1

print('TOTAL', N, 'LATEST', draws[-1]['period'], draws[-1]['reds'], draws[-1]['blue'], flush=True)

def overlap_stats(reds):
    v = np.zeros(34, dtype=np.uint8)
    for x in reds:
        v[x] = 1
    ov = hist @ v  # shape (N,)
    # ov[i] is overlap with draw i; values use indices 1..33 only so OK
    c = Counter(int(x) for x in ov.tolist())
    return int(ov.max()), c

mx, c = overlap_stats(OLD1)
print('OLD1', OLD1, 'max', mx, 'c4', c.get(4,0), 'c5', c.get(5,0), 'c6', c.get(6,0), flush=True)

# Frequency / omission scoring setup
def freq_window(k):
    c = Counter()
    for d in draws[-k:]:
        for x in d['reds']:
            c[x] += 1
    return c

f_all = freq_window(N)
f30 = freq_window(30)
f50 = freq_window(50)
f100 = freq_window(100)
omission = {}
for ball in range(1, 34):
    omit = N
    for i in range(N - 1, -1, -1):
        if ball in draws[i]['reds']:
            omit = N - 1 - i
            break
    omission[ball] = omit

blue_omission = {}
for b in range(1, 17):
    omit = N
    for i in range(N - 1, -1, -1):
        if draws[i]['blue'] == b:
            omit = N - 1 - i
            break
    blue_omission[b] = omit
blue_f100 = Counter(d['blue'] for d in draws[-100:])
blue_f_all = Counter(d['blue'] for d in draws)

def struct(reds):
    reds = sorted(reds)
    odd = sum(1 for x in reds if x % 2 == 1)
    prime = sum(1 for x in reds if x in PRIMES)
    road = (
        sum(1 for x in reds if x % 3 == 0),
        sum(1 for x in reds if x % 3 == 1),
        sum(1 for x in reds if x % 3 == 2),
    )
    z4 = [0, 0, 0, 0]
    for x in reds:
        z4[zone4(x)] += 1
    wx = Counter(wuxing(x) for x in reds)
    big = sum(1 for x in reds if x > 16)
    s = sum(reds)
    span = reds[-1] - reds[0]
    cons = 0
    i = 0
    while i < 5:
        if reds[i + 1] == reds[i] + 1:
            cons += 1
            while i < 5 and reds[i + 1] == reds[i] + 1:
                i += 1
        i += 1
    z3 = (
        sum(1 for x in reds if 1 <= x <= 11),
        sum(1 for x in reds if 12 <= x <= 22),
        sum(1 for x in reds if 23 <= x <= 33),
    )
    return {
        'odd': odd, 'even': 6 - odd, 'prime': prime, 'composite': 6 - prime,
        'road': road, 'z4': tuple(z4), 'wx': dict(wx),
        'big': big, 'sum': s, 'span': span, 'cons': cons, 'z3': z3,
    }

exp30, exp50, exp100, exp_all = 6 * 30 / 33, 6 * 50 / 33, 6 * 100 / 33, 6 * N / 33
omit_vals = sorted(omission.values())
omit_med = statistics.median(omit_vals)
omit_p25 = omit_vals[len(omit_vals) // 4]
omit_p75 = omit_vals[3 * len(omit_vals) // 4]
latest_reds = set(draws[-1]['reds'])
ultra = {b for b, _ in sorted(omission.items(), key=lambda x: -x[1])[:5]}

def ball_score(b):
    def freq_comp(cnt, exp, weight):
        diff = abs(cnt.get(b, 0) - exp)
        return weight * max(0, 1 - diff / (exp * 0.8 + 1))
    s = 0
    s += freq_comp(f30, exp30, 1.0)
    s += freq_comp(f50, exp50, 1.2)
    s += freq_comp(f100, exp100, 1.5)
    s += freq_comp(f_all, exp_all, 0.8)
    om = omission[b]
    if om == 0:
        s -= 1.5
    elif omit_p25 <= om <= omit_p75 + 2:
        s += 2.0
    elif om < omit_p25:
        s += 0.5
    elif om <= omit_vals[int(0.9 * len(omit_vals))]:
        s += 1.0
    else:
        s -= 1.2
    if f_all[b] < exp_all and om >= omit_med:
        s += 0.4
    if f30.get(b, 0) >= exp30 + 2 and om <= 2:
        s -= 1.0
    return s

ball_scores = {b: ball_score(b) for b in range(1, 34)}

def blue_score(b):
    expb100 = 100 / 16
    expball = N / 16
    s = 0
    diff100 = abs(blue_f100.get(b, 0) - expb100)
    s += 1.5 * max(0, 1 - diff100 / (expb100 * 0.8 + 1))
    diffall = abs(blue_f_all.get(b, 0) - expball)
    s += 0.8 * max(0, 1 - diffall / (expball * 0.8 + 1))
    om = blue_omission[b]
    bom_vals = sorted(blue_omission.values())
    bp25, bp75 = bom_vals[len(bom_vals) // 4], bom_vals[3 * len(bom_vals) // 4]
    if om == 0:
        s -= 1.0
    elif bp25 <= om <= bp75 + 3:
        s += 2.0
    elif om > bom_vals[int(0.9 * len(bom_vals))]:
        s -= 0.8
    else:
        s += 0.6
    return s

blue_scores = {b: blue_score(b) for b in range(1, 17)}

def combo_ok(reds):
    st = struct(reds)
    if st['odd'] not in (2, 3, 4): return False
    if st['big'] not in (2, 3, 4): return False
    if not (80 <= st['sum'] <= 120): return False
    if not (20 <= st['span'] <= 28): return False
    if st['cons'] > 1: return False
    z1, z2, z3 = st['z3']
    if max(z1, z2, z3) >= 5: return False
    if min(z1, z2, z3) == 0 and max(z1, z2, z3) >= 4: return False
    if sum(1 for x in reds if x in ultra) >= 3: return False
    if sum(1 for x in reds if x in latest_reds) >= 3: return False
    if st['prime'] not in (2, 3, 4): return False
    r0, r1, r2 = st['road']
    if max(r0, r1, r2) >= 5: return False
    if min(r0, r1, r2) == 0 and max(r0, r1, r2) >= 4: return False
    if max(st['z4']) >= 4: return False
    if sum(1 for x in st['z4'] if x == 0) >= 3: return False
    wx = st['wx']
    if max(wx.values()) >= 4: return False
    if len(wx) < 3: return False
    return True

def combo_score(reds):
    st = struct(reds)
    s = sum(ball_scores[b] for b in reds)
    if st['odd'] == 3: s += 1.5
    elif st['odd'] in (2, 4): s += 0.8
    if st['big'] == 3: s += 1.5
    elif st['big'] in (2, 4): s += 0.8
    if 90 <= st['sum'] <= 110: s += 1.2
    elif 80 <= st['sum'] <= 120: s += 0.5
    if 22 <= st['span'] <= 26: s += 1.0
    elif 20 <= st['span'] <= 28: s += 0.4
    if st['cons'] == 1: s += 0.9
    elif st['cons'] == 0: s += 0.6
    if st['z3'] == (2, 2, 2): s += 1.0
    if st['prime'] == 3: s += 1.2
    elif st['prime'] in (2, 4): s += 0.7
    if st['road'] == (2, 2, 2): s += 1.5
    elif sorted(st['road']) == [1, 2, 3]: s += 1.0
    elif min(st['road']) >= 1: s += 0.5
    z4 = st['z4']
    if max(z4) <= 2 and min(z4) >= 1: s += 1.5
    elif max(z4) <= 2 and sum(1 for x in z4 if x == 0) == 1: s += 0.8
    wx = st['wx']
    if len(wx) >= 4 and max(wx.values()) <= 2: s += 1.5
    elif len(wx) >= 4: s += 1.0
    elif len(wx) == 3 and max(wx.values()) <= 2: s += 0.6
    for old in (OLD1, OLD2):
        ov = len(set(reds) & set(old))
        if ov == 6: s -= 8.0
        elif ov >= 5: s -= 3.0
        elif ov >= 4: s -= 1.0
        elif ov <= 2: s += 0.2
    return s, st

# ---- numpy batch scan all C(33,6) ----
print('Building all combos...', flush=True)
all_combs = np.array(list(itertools.combinations(range(1, 34), 6)), dtype=np.uint8)
n_all = len(all_combs)
print('n_all', n_all, flush=True)

BATCH = 8000
global_min = 99
min_idx = []
le3_idx = []
# Also track best for max==4 with c5==0: minimize c4
best4 = []  # list of (c4, -struct_later, idx) collected coarsely

# For each batch: build (B, 34) matrix
ov_max_hist = Counter()
n_le3 = 0
n_max4_c5_0 = 0
min_c4_among_no5 = 10**9

for start in range(0, n_all, BATCH):
    chunk = all_combs[start:start + BATCH]
    B = len(chunk)
    mat = np.zeros((B, 34), dtype=np.uint8)
    for j in range(6):
        mat[np.arange(B), chunk[:, j]] = 1
    # hist (N,34) @ mat.T (34,B) -> (N,B)
    ov = hist.astype(np.uint16) @ mat.T.astype(np.uint16)
    mx = ov.max(axis=0)  # (B,)
    for t, mxi in enumerate(mx.tolist()):
        ov_max_hist[mxi] += 1
        if mxi < global_min:
            global_min = mxi
            min_idx = [start + t]
            print('NEW global_min', global_min, 'comb', all_combs[start + t].tolist(), flush=True)
        elif mxi == global_min:
            if len(min_idx) < 200:
                min_idx.append(start + t)
        if mxi <= 3:
            n_le3 += 1
            le3_idx.append(start + t)
        if mxi == 4:
            # check c5
            col = ov[:, t]
            c5 = int((col == 5).sum())
            c4 = int((col == 4).sum())
            if c5 == 0:
                n_max4_c5_0 += 1
                if c4 < min_c4_among_no5:
                    min_c4_among_no5 = c4
                    best4 = [(c4, start + t)]
                    print('NEW best4 c4=', c4, 'comb', all_combs[start + t].tolist(), flush=True)
                elif c4 == min_c4_among_no5:
                    if len(best4) < 500:
                        best4.append((c4, start + t))
    if start % (BATCH * 10) == 0:
        print('progress', start, '/', n_all, 'global_min', global_min, 'n_le3', n_le3,
              'min_c4_no5', min_c4_among_no5, 'n_max4_c5_0', n_max4_c5_0, flush=True)

print('DONE global_min', global_min, 'n_at_min_cap', len(min_idx), 'n_le3', n_le3, flush=True)
print('ov_max_hist', dict(sorted(ov_max_hist.items())), flush=True)
print('n_max4_c5_0', n_max4_c5_0, 'min_c4_among_no5', min_c4_among_no5, 'best4_n', len(best4), flush=True)

# Choose candidate pool
if n_le3 > 0:
    mode = 'max_ov_le3'
    cand_indices = le3_idx
    print('MODE', mode, 'n', len(cand_indices), flush=True)
else:
    mode = 'max_ov4_no5_min_c4'
    cand_indices = [idx for c4, idx in best4]
    print('MODE', mode, 'n', len(cand_indices), 'min_c4', min_c4_among_no5, flush=True)
    # If too few at absolute min c4, also take c4 <= min+2 for structure room
    if len(cand_indices) < 20:
        # rescan quickly for c4 <= min+2 among no5 — from best4 we only kept min
        # Expand: second pass only storing those
        print('Expanding pool c4<=min+2...', flush=True)
        expanded = []
        limit_c4 = min_c4_among_no5 + 2
        for start in range(0, n_all, BATCH):
            chunk = all_combs[start:start + BATCH]
            B = len(chunk)
            mat = np.zeros((B, 34), dtype=np.uint8)
            for j in range(6):
                mat[np.arange(B), chunk[:, j]] = 1
            ov = hist.astype(np.uint16) @ mat.T.astype(np.uint16)
            mx = ov.max(axis=0)
            for t, mxi in enumerate(mx.tolist()):
                if mxi != 4:
                    continue
                col = ov[:, t]
                if int((col == 5).sum()) != 0:
                    continue
                c4 = int((col == 4).sum())
                if c4 <= limit_c4:
                    expanded.append((c4, start + t))
        expanded.sort()
        cand_indices = [idx for c4, idx in expanded[:2000]]
        print('expanded', len(expanded), 'using', len(cand_indices), flush=True)

# Score candidates with structure filter
scored = []
for idx in cand_indices:
    comb = tuple(int(x) for x in all_combs[idx].tolist())
    if comb in (OLD1, OLD2):
        continue
    if not combo_ok(comb):
        continue
    sc, st = combo_score(comb)
    mx, counts = overlap_stats(comb)
    scored.append((sc, comb, st, mx, dict(counts)))

# If structure filter emptied the strict pool, relax structure on the hist-constraint pool
if not scored:
    print('No struct-ok in hist pool; relaxing struct hard filters...', flush=True)
    for idx in cand_indices:
        comb = tuple(int(x) for x in all_combs[idx].tolist())
        if comb in (OLD1, OLD2):
            continue
        st = struct(comb)
        # soft gates only
        if st['cons'] > 2: continue
        if not (70 <= st['sum'] <= 130): continue
        sc, st = combo_score(comb)
        mx, counts = overlap_stats(comb)
        scored.append((sc, comb, st, mx, dict(counts)))

scored.sort(key=lambda x: -x[0])
print('scored', len(scored), flush=True)
for sc, comb, st, mx, counts in scored[:10]:
    print('TOP', round(sc,3), comb, 'mx', mx,
          'c3', counts.get(3,0), 'c4', counts.get(4,0), 'c5', counts.get(5,0), 'c6', counts.get(6,0),
          'odd', st['odd'], 'prime', st['prime'], 'road', st['road'], 'z4', st['z4'],
          'wx', {WX_CN[k]:v for k,v in st['wx'].items()},
          'sum', st['sum'], 'span', st['span'], 'cons', st['cons'], flush=True)

if not scored:
    # last resort: take best hist candidate without struct
    print('FALLBACK raw hist pool', flush=True)
    raw = []
    for idx in cand_indices[:500]:
        comb = tuple(int(x) for x in all_combs[idx].tolist())
        sc, st = combo_score(comb)
        mx, counts = overlap_stats(comb)
        raw.append((sc, comb, st, mx, dict(counts)))
    raw.sort(key=lambda x: -x[0])
    scored = raw

best_sc, best, best_st, best_mx, best_counts = scored[0]

ranked_blue = sorted(blue_scores.items(), key=lambda x: -x[1])
best_blue = ranked_blue[0][0]
if best_blue in (OLD1_BLUE, OLD2_BLUE):
    for b, s in ranked_blue:
        if b not in (OLD1_BLUE, OLD2_BLUE):
            best_blue = b
            break
if ranked_blue[0][0] not in (OLD1_BLUE, OLD2_BLUE):
    best_blue = ranked_blue[0][0]

wx_cn = {WX_CN[k]: v for k, v in best_st['wx'].items()}

# nearest examples at max overlap
near = []
sbest = set(best)
for d in draws:
    ov = len(sbest & set(d['reds']))
    if ov == best_mx:
        near.append({
            'period': d['period'], 'date': d['date'],
            'reds': list(d['reds']), 'blue': d['blue'],
            'hit': sorted(sbest & set(d['reds'])),
        })

out = {
    'disclaimer': 'Entertainment only. Filters do NOT raise true win probability. Any fixed bet has same jackpot odds.',
    'mode': mode,
    'impossible_max_ov_le3': n_le3 == 0,
    'global_min_max_overlap_over_all_C33_6': global_min,
    'n_le3_universe': n_le3,
    'n_max4_c5_0_universe': n_max4_c5_0,
    'min_c4_among_max4_no5': min_c4_among_no5 if n_le3 == 0 else None,
    'ov_max_hist_universe': {str(k): v for k, v in sorted(ov_max_hist.items())},
    'total': N,
    'latest': {'period': draws[-1]['period'], 'date': draws[-1]['date'],
               'reds': list(draws[-1]['reds']), 'blue': draws[-1]['blue']},
    'recommend_red': list(best),
    'recommend_blue': best_blue,
    'score': round(best_sc, 3),
    'hist_max_overlap': best_mx,
    'hist_overlap_counts': {str(k): best_counts.get(k, 0) for k in range(0, 7)},
    'struct': {
        'odd_even': '%d:%d' % (best_st['odd'], best_st['even']),
        'prime_composite': '%d:%d' % (best_st['prime'], best_st['composite']),
        'road_012': list(best_st['road']),
        'zone4': list(best_st['z4']),
        'wuxing': wx_cn,
        'sum': best_st['sum'], 'span': best_st['span'], 'cons': best_st['cons'],
        'big_small': '%d:%d' % (best_st['big'], 6 - best_st['big']),
    },
    'overlap_old1_051116182728': sorted(set(best) & set(OLD1)),
    'overlap_old2_080914172432': sorted(set(best) & set(OLD2)),
    'blue_detail': {
        'omit': blue_omission[best_blue],
        'f100': blue_f100.get(best_blue, 0),
        'fall': blue_f_all[best_blue],
        'score': round(blue_scores[best_blue], 3),
        'ranked': [(b, round(s, 3)) for b, s in ranked_blue[:6]],
    },
    'nearest_count': len(near),
    'nearest_examples': near[:8],
    'top5': [
        {
            'score': round(sc, 3), 'reds': list(c), 'max_ov': mx,
            'c4': counts.get(4, 0), 'c5': counts.get(5, 0), 'c6': counts.get(6, 0),
            'odd': st['odd'], 'prime': st['prime'],
            'road': list(st['road']), 'z4': list(st['z4']),
            'wx': {WX_CN[k]: v for k, v in st['wx'].items()},
            'sum': st['sum'], 'span': st['span'], 'cons': st['cons'],
        }
        for sc, c, st, mx, counts in scored[:5]
    ],
    'old1_ref': {'reds': list(OLD1), 'max': overlap_stats(OLD1)[0],
                 'counts': {str(k): overlap_stats(OLD1)[1].get(k,0) for k in range(7)}},
}

Path(r'D:\develop\agent\lottery\recommend_max3.json').write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print('RECOMMEND', list(best), 'BLUE', best_blue, flush=True)
print('MAX_OV', best_mx, 'COUNTS', {k: best_counts.get(k,0) for k in range(7)}, flush=True)
print('STRUCT', out['struct'], flush=True)
print('OV_OLD1', out['overlap_old1_051116182728'], 'OV_OLD2', out['overlap_old2_080914172432'], flush=True)
print('WROTE OK', flush=True)
