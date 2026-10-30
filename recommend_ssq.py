# -*- coding: utf-8 -*-
import sqlite3, itertools, statistics, json
from collections import Counter
from pathlib import Path

DB = r'D:\develop\agent\lottery\lottery.db'
USER = (8, 9, 14, 17, 24, 32)
USER_BLUE = 1

# 质数 1-33；1 按合数（双色球常见惯例）
PRIMES = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31}

# 五行常见映射（按号码尾数/区间玩法常见表）
# 采用：金=4,9 | 木=3,8 | 水=1,6 | 火=2,7 | 土=0,5  （尾数）
# 对 1-33：用个位映射
def wuxing(n):
    d = n % 10
    if d in (4, 9):
        return '金'
    if d in (3, 8):
        return '木'
    if d in (1, 6):
        return '水'
    if d in (2, 7):
        return '火'
    return '土'  # 0,5

# 四区：1-8 / 9-16 / 17-24 / 25-33
def zone4(n):
    if 1 <= n <= 8:
        return 0
    if 9 <= n <= 16:
        return 1
    if 17 <= n <= 24:
        return 2
    return 3

con = sqlite3.connect(DB)
rows = con.execute(
    'SELECT period, draw_date, red_1,red_2,red_3,red_4,red_5,red_6, blue FROM ssq ORDER BY period ASC'
).fetchall()
con.close()
N = len(rows)

draws = []
for r in rows:
    reds = tuple(sorted(r[2:8]))
    draws.append({'period': r[0], 'date': r[1], 'reds': reds, 'blue': r[8]})

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
    even = 6 - odd
    prime = sum(1 for x in reds if x in PRIMES)
    composite = 6 - prime  # 1 算合
    r0 = sum(1 for x in reds if x % 3 == 0)
    r1 = sum(1 for x in reds if x % 3 == 1)
    r2 = sum(1 for x in reds if x % 3 == 2)
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
        'odd': odd, 'even': even,
        'prime': prime, 'composite': composite,
        'road': (r0, r1, r2),
        'z4': tuple(z4),
        'wx': dict(wx),
        'big': big, 'sum': s, 'span': span, 'cons': cons, 'z3': z3,
    }

# Historical modes for new dims
odd_c = Counter(struct(d['reds'])['odd'] for d in draws)
prime_c = Counter(struct(d['reds'])['prime'] for d in draws)
road_c = Counter(struct(d['reds'])['road'] for d in draws)
z4_c = Counter(struct(d['reds'])['z4'] for d in draws)
# wuxing: count max element and entropy-ish (how many distinct, max count)
wx_max_c = Counter(max(struct(d['reds'])['wx'].values()) for d in draws)
wx_types_c = Counter(len(struct(d['reds'])['wx']) for d in draws)

print('TOTAL', N)
print('LATEST', draws[-1])
print('odd mode', odd_c.most_common(5))
print('prime mode', prime_c.most_common(5))
print('road mode', road_c.most_common(8))
print('z4 mode', z4_c.most_common(10))
print('wx_max mode', wx_max_c.most_common(5))
print('wx_types mode', wx_types_c.most_common(5))

# sample mean road
roads = [struct(d['reds'])['road'] for d in draws]
mean_road = tuple(round(sum(r[i] for r in roads) / N, 2) for i in range(3))
print('mean road', mean_road)
z4s = [struct(d['reds'])['z4'] for d in draws]
mean_z4 = tuple(round(sum(z[i] for z in z4s) / N, 2) for i in range(4))
print('mean z4', mean_z4)

exp30, exp50, exp100, exp_all = 6 * 30 / 33, 6 * 50 / 33, 6 * 100 / 33, 6 * N / 33
omit_vals = sorted(omission.values())
omit_med = statistics.median(omit_vals)
omit_p25 = omit_vals[len(omit_vals) // 4]
omit_p75 = omit_vals[3 * len(omit_vals) // 4]
print('omit med/p25/p75', omit_med, omit_p25, omit_p75)

latest_reds = set(draws[-1]['reds'])

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
print('top balls', sorted(ball_scores.items(), key=lambda x: -x[1])[:15])

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
print('blue scores', sorted(blue_scores.items(), key=lambda x: -x[1]))
print('blue omit', dict(sorted(blue_omission.items())))
print('USER set struct', struct(USER))

ranked = [b for b, _ in sorted(ball_scores.items(), key=lambda x: -x[1])]
pool = ranked[:18]  # C(18,6)=18564 ok
print('pool', pool)

ultra = {b for b, _ in sorted(omission.items(), key=lambda x: -x[1])[:5]}

def combo_ok(reds):
    st = struct(reds)
    if st['odd'] not in (2, 3, 4):
        return False
    if st['big'] not in (2, 3, 4):
        return False
    if not (80 <= st['sum'] <= 120):
        return False
    if not (20 <= st['span'] <= 28):
        return False
    if st['cons'] > 1:
        return False
    z1, z2, z3 = st['z3']
    if max(z1, z2, z3) >= 5:
        return False
    if min(z1, z2, z3) == 0 and max(z1, z2, z3) >= 4:
        return False
    if sum(1 for x in reds if x in ultra) >= 3:
        return False
    if sum(1 for x in reds if x in latest_reds) >= 3:
        return False
    # 质合：历史众数多为 2/3/4 质
    if st['prime'] not in (2, 3, 4):
        return False
    # 012路：避免 6-0-0 这类极端；每路最多 4，且至少两路非空常见
    r0, r1, r2 = st['road']
    if max(r0, r1, r2) >= 5:
        return False
    if min(r0, r1, r2) == 0 and max(r0, r1, r2) >= 4:
        return False
    # 四区：避免空两区且一区堆积
    if max(st['z4']) >= 4:
        return False
    empty_z = sum(1 for x in st['z4'] if x == 0)
    if empty_z >= 3:
        return False
    # 五行：不要某一行 >=4；尽量覆盖 >=3 行
    wx = st['wx']
    if max(wx.values()) >= 4:
        return False
    if len(wx) < 3:
        return False
    return True

def combo_score(reds):
    st = struct(reds)
    s = sum(ball_scores[b] for b in reds)
    # 奇偶
    if st['odd'] == 3:
        s += 1.5
    elif st['odd'] in (2, 4):
        s += 0.8
    # 大小
    if st['big'] == 3:
        s += 1.5
    elif st['big'] in (2, 4):
        s += 0.8
    # 和值跨度连号
    if 90 <= st['sum'] <= 110:
        s += 1.2
    elif 80 <= st['sum'] <= 120:
        s += 0.5
    if 22 <= st['span'] <= 26:
        s += 1.0
    elif 20 <= st['span'] <= 28:
        s += 0.4
    if st['cons'] == 1:
        s += 0.9
    elif st['cons'] == 0:
        s += 0.6
    if st['z3'] == (2, 2, 2):
        s += 1.0
    # 质合：众数约 3
    if st['prime'] == 3:
        s += 1.2
    elif st['prime'] in (2, 4):
        s += 0.7
    # 012路：贴近 2-2-2
    if st['road'] == (2, 2, 2):
        s += 1.5
    elif sorted(st['road']) == [1, 2, 3]:
        s += 1.0
    elif min(st['road']) >= 1:
        s += 0.5
    # 四区：贴近均值约各 1.5；偏好 1-2-2-1 / 2-1-2-1 / 1-2-1-2 等分散
    z4 = st['z4']
    if max(z4) <= 2 and min(z4) >= 1:
        s += 1.5  # 每区 1 或 2
    elif max(z4) <= 2 and sum(1 for x in z4 if x == 0) == 1:
        s += 0.8
    # 五行：5 行都有最好（不可能 6 球 5 行则最多覆盖 5）；4+ 行且 max<=2
    wx = st['wx']
    if len(wx) >= 4 and max(wx.values()) <= 2:
        s += 1.5
    elif len(wx) >= 4:
        s += 1.0
    elif len(wx) == 3 and max(wx.values()) <= 2:
        s += 0.6
    # vs user
    overlap = len(set(reds) & set(USER))
    if overlap == 6:
        s -= 5.0
    elif overlap >= 5:
        s -= 1.5
    elif overlap <= 3:
        s += 0.3
    return s, st

candidates = []
for comb in itertools.combinations(pool, 6):
    if not combo_ok(comb):
        continue
    sc, st = combo_score(comb)
    candidates.append((sc, comb, st))
candidates.sort(key=lambda x: -x[0])
print('candidates', len(candidates))
if len(candidates) < 10:
    pool = ranked[:22]
    candidates = []
    for comb in itertools.combinations(pool, 6):
        if not combo_ok(comb):
            continue
        sc, st = combo_score(comb)
        candidates.append((sc, comb, st))
    candidates.sort(key=lambda x: -x[0])
    print('expanded', len(candidates), 'pool', pool)

print('TOP8:')
for sc, comb, st in candidates[:8]:
    print(round(sc, 3), comb, 'odd', st['odd'], 'prime', st['prime'],
          'road', st['road'], 'z4', st['z4'], 'wx', st['wx'],
          'sum', st['sum'], 'span', st['span'], 'cons', st['cons'],
          'ov', len(set(comb) & set(USER)))

best_sc, best, best_st = candidates[0]
for sc, comb, st in candidates:
    if tuple(comb) != USER:
        best_sc, best, best_st = sc, comb, st
        break

ranked_blue = sorted(blue_scores.items(), key=lambda x: -x[1])
if ranked_blue[0][0] == USER_BLUE and ranked_blue[1][1] >= ranked_blue[0][1] - 0.3:
    best_blue = ranked_blue[1][0]
else:
    best_blue = ranked_blue[0][0]

full_hits = [d for d in draws if d['reds'] == tuple(best) and d['blue'] == best_blue]
red_only = [d for d in draws if d['reds'] == tuple(best)]

print('RECOMMEND', best, 'BLUE', best_blue)
print('STRUCT', best_st)
print('full', [(d['period'], d['date']) for d in full_hits])
print('red_only', [(d['period'], d['date'], d['blue']) for d in red_only])
print('overlap', sorted(set(best) & set(USER)))
print('out', sorted(set(USER) - set(best)), 'in', sorted(set(best) - set(USER)))

print('--- detail ---')
for b in best:
    print('R%02d omit=%d f30=%d f50=%d f100=%d fall=%d sc=%.3f wx=%s zone=%d road=%d %s' % (
        b, omission[b], f30.get(b, 0), f50.get(b, 0), f100.get(b, 0), f_all[b],
        ball_scores[b], wuxing(b), zone4(b), b % 3,
        '质' if b in PRIMES else '合'))
print('B%02d omit=%d f100=%d fall=%d sc=%.3f' % (
    best_blue, blue_omission[best_blue], blue_f100.get(best_blue, 0),
    blue_f_all[best_blue], blue_scores[best_blue]))

user_sc, user_st = combo_score(USER)
print('USER', user_sc, user_st)

# near-100 modes for reporting
odd100 = Counter(struct(d['reds'])['odd'] for d in draws[-100:]).most_common(3)
prime100 = Counter(struct(d['reds'])['prime'] for d in draws[-100:]).most_common(3)
road100 = Counter(struct(d['reds'])['road'] for d in draws[-100:]).most_common(5)
z4100 = Counter(struct(d['reds'])['z4'] for d in draws[-100:]).most_common(5)

out = {
    'total': N,
    'latest': {'period': draws[-1]['period'], 'date': draws[-1]['date'],
               'reds': list(draws[-1]['reds']), 'blue': draws[-1]['blue']},
    'recommend_red': list(best),
    'recommend_blue': best_blue,
    'struct': {
        'odd_even': '%d:%d' % (best_st['odd'], best_st['even']),
        'prime_composite': '%d:%d (1算合)' % (best_st['prime'], best_st['composite']),
        'road_012': list(best_st['road']),
        'zone4_1_8_9_16_17_24_25_33': list(best_st['z4']),
        'wuxing': best_st['wx'],
        'sum': best_st['sum'], 'span': best_st['span'], 'cons': best_st['cons'],
        'big_small': '%d:%d' % (best_st['big'], 6 - best_st['big']),
        'z3': list(best_st['z3']),
    },
    'hist_modes': {
        'odd_all': odd_c.most_common(3), 'odd_100': odd100,
        'prime_all': prime_c.most_common(3), 'prime_100': prime100,
        'road_all': [(list(k), v) for k, v in road_c.most_common(5)],
        'road_100': [(list(k), v) for k, v in road100],
        'road_mean': list(mean_road),
        'z4_all': [(list(k), v) for k, v in z4_c.most_common(5)],
        'z4_100': [(list(k), v) for k, v in z4100],
        'z4_mean': list(mean_z4),
        'wx_types_all': wx_types_c.most_common(3),
        'wx_max_all': wx_max_c.most_common(3),
    },
    'full_hits': [(d['period'], d['date']) for d in full_hits],
    'red_only_hits': [(d['period'], d['date'], d['blue']) for d in red_only],
    'overlap': sorted(set(best) & set(USER)),
    'removed': sorted(set(USER) - set(best)),
    'added': sorted(set(best) - set(USER)),
    'ball_details': {
        str(b): {
            'omit': omission[b], 'f30': f30.get(b, 0), 'f50': f50.get(b, 0),
            'f100': f100.get(b, 0), 'fall': f_all[b],
            'score': round(ball_scores[b], 3),
            'wuxing': wuxing(b), 'zone4': zone4(b), 'road': b % 3,
            'prime': b in PRIMES,
        } for b in best
    },
    'blue_detail': {
        'omit': blue_omission[best_blue], 'f100': blue_f100.get(best_blue, 0),
        'fall': blue_f_all[best_blue], 'score': round(blue_scores[best_blue], 3),
        'ranked': [(b, round(s, 3)) for b, s in ranked_blue[:5]],
    },
    'user_struct': {
        'odd_even': '%d:%d' % (user_st['odd'], user_st['even']),
        'prime_composite': '%d:%d' % (user_st['prime'], user_st['composite']),
        'road_012': list(user_st['road']),
        'zone4': list(user_st['z4']),
        'wuxing': user_st['wx'],
        'sum': user_st['sum'], 'span': user_st['span'], 'cons': user_st['cons'],
        'score': round(user_sc, 3),
    },
    'weights': {
        'freq': 'f30:1.0 f50:1.2 f100:1.5 fall:0.8 near 6*k/33',
        'omit': 'mid [p25,p75+2] +2; omit0 -1.5; top10%% cold -1.2',
        'struct_hard': 'odd2-4 big2-4 sum80-120 span20-28 cons<=1 prime2-4; road max<=4; z4 max<=3; wx types>=3 max<=3',
        'struct_soft': 'odd3+1.5 prime3+1.2 road222+1.5 z4每区1-2+1.5 wx4+且max<=2 +1.5',
        'wuxing_map': '尾数: 金49 木38 水16 火27 土05; 1算合数',
        'zone4': '1-8/9-16/17-24/25-33',
        'blue': 'f100+fall near expected; mid omit',
    },
    'top5': [{'score': round(sc, 3), 'reds': list(c),
              'odd': st['odd'], 'prime': st['prime'], 'road': list(st['road']),
              'z4': list(st['z4']), 'wx': st['wx']} for sc, c, st in candidates[:5]],
}
Path(r'D:\develop\agent\lottery\recommend_analysis.json').write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print('WROTE OK')
