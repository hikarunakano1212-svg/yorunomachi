"""八重洲マップ生成: Overture Maps(OSM 由来)の建物・道路データから、ゲーム用の地図を作る。

    python tools/fetch_overture.py theme=buildings/type=building 139.7620,35.6745,139.7780,35.6860 tools/data/bld.json
    python tools/fetch_overture.py theme=transportation/type=segment 139.7600,35.6730,139.7800,35.6875 tools/data/road.json
    python tools/build_map.py

出力:
    assets/map/yaesu.json   建物・道路網・歩行者網・線路・首都高・街路樹/街灯/信号などの配置
    assets/map/ground.webp  路面テクスチャ(R=車道, G=白線, B=黄線/歩道)
    assets/map/minimap.png  ミニマップ用の地図画像

座標系: 東京ミッドタウン八重洲付近を原点に、x=東, z=南(m)。three.js では -Z が北。
"""
import json
import math
import os
import random
from collections import defaultdict

import shapely
from PIL import Image, ImageDraw, ImageFilter
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, shape
from shapely.ops import unary_union

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'tools', 'data')
OUT = os.path.join(ROOT, 'assets', 'map')
LAT0, LON0 = 35.6800, 139.7690
HALF = 450                       # ゲーム範囲の半径(m)
TEX = 4096                       # 路面テクスチャ解像度
KX = math.cos(math.radians(LAT0)) * 111320
KZ = 110540
AREA = box(-HALF, -HALF, HALF, HALF)
random.seed(8)

# データに高さが無い主要ビルの補正(公開されている高さ)
OVERRIDE = {
    '東京ミッドタウン八重洲': {'tower': 240, 'podium': 46, 'inset': 16},
    'グラントウキョウノースタワー': {'tower': 205, 'podium': 42, 'inset': 10},
    'グランルーフ': {'h': 14, 'mh': 9, 'style': 'granroof'},
}

# 車道幅(m) — 実際の八重洲の道路幅に近づけた値
WIDTH = {'trunk': 24, 'primary': 20, 'secondary': 16, 'tertiary': 11, 'residential': 7,
         'unclassified': 7, 'living_street': 5.5, 'service': 5}
PED = {'footway', 'pedestrian', 'path', 'steps', 'cycleway'}


def proj(g):
    return shapely.transform(g, lambda a: (a - [LON0, LAT0]) * [KX, -KZ])


def flags_of(r):
    f = set()
    for v in r.get('flags') or []:
        f.update(v)
    return f


def level_of(r):
    lv = r.get('level') or [0]
    return min(lv) if min(lv) < 0 else max(lv)


def r1(v):
    return round(v, 1)


def flat(coords):
    out = []
    for x, z in coords:
        out += [r1(x), r1(z)]
    return out


def main():
    blds = json.load(open(os.path.join(DATA, 'bld.json')))
    roads = json.load(open(os.path.join(DATA, 'road.json')))

    # ------------------------------------------------------------ 道路(地上・車道)
    drive, peds, rails, express = [], [], [], []
    for r in roads:
        g = proj(shape(r['g']))
        if g.geom_type != 'LineString' or not g.intersects(AREA.buffer(60)):
            continue
        f, lv, c = flags_of(r), level_of(r), r.get('class')
        if r.get('subtype') == 'rail':
            if c == 'standard_gauge' and 'is_tunnel' not in f and lv >= 0:
                rails.append(g)
            continue
        if c == 'motorway' and ('is_tunnel' not in f) and lv >= 0:
            express.append(g)
            continue
        if lv != 0 or 'is_tunnel' in f or 'is_indoor' in f:
            continue
        if c in WIDTH:
            ow = r.get('oneway_denied') == 'backward'
            # 上下線が別々の道路(一方通行)は片側分の幅
            w = round(WIDTH[c] * 0.55, 1) if ow and WIDTH[c] >= 11 else WIDTH[c]
            drive.append({'g': g, 'w': w, 'c': c, 'name': r.get('name') or '', 'ow': ow})
        elif c in PED:
            peds.append(g)

    # 端点を 1m 格子でスナップしてグラフ化
    def graph(lines):
        key = lambda p: (round(p[0]), round(p[1]))
        nodes, index, edges = [], {}, []
        def nid(p):
            k = key(p)
            if k not in index:
                index[k] = len(nodes)
                nodes.append([r1(p[0]), r1(p[1])])
            return index[k]
        for item in lines:
            g = item['g'] if isinstance(item, dict) else item
            cs = list(g.coords)
            a, b = nid(cs[0]), nid(cs[-1])
            if a == b:
                continue
            e = {'a': a, 'b': b, 'pts': flat(cs), 'len': r1(g.length)}
            if isinstance(item, dict):
                e.update(w=item['w'], c=item['c'], name=item['name'])
                if item.get('ow'):
                    e['ow'] = 1
            edges.append(e)
        # 最大の連結成分だけ残す
        adj = defaultdict(list)
        for i, e in enumerate(edges):
            adj[e['a']].append(i)
            adj[e['b']].append(i)
        seen, best = set(), []
        for s in range(len(nodes)):
            if s in seen or s not in adj:
                continue
            comp, stack = [], [s]
            seen.add(s)
            while stack:
                n = stack.pop()
                comp.append(n)
                for ei in adj[n]:
                    e = edges[ei]
                    for m in (e['a'], e['b']):
                        if m not in seen:
                            seen.add(m)
                            stack.append(m)
            if len(comp) > len(best):
                best = comp
        keep = set(best)
        edges = [e for e in edges if e['a'] in keep]
        remap = {}
        new_nodes = []
        for i in sorted(keep):
            remap[i] = len(new_nodes)
            new_nodes.append(nodes[i])
        for e in edges:
            e['a'], e['b'] = remap[e['a']], remap[e['b']]
        return new_nodes, edges

    # 範囲外に出る道路は範囲内の部分だけ(ワールドの端は壁)
    clipped = []
    inner = AREA.buffer(-4)
    for d in drive:
        g = d['g'].intersection(inner)
        for part in getattr(g, 'geoms', [g]):
            if part.geom_type == 'LineString' and part.length > 2:
                clipped.append({**d, 'g': part})
    rnodes, redges = graph(clipped)
    ped_lines = []
    for g in peds:
        g = g.intersection(inner)
        for part in getattr(g, 'geoms', [g]):
            if part.geom_type == 'LineString' and part.length > 1:
                ped_lines.append(part)
    pnodes, pedges = graph(ped_lines)
    print(f'車道: ノード {len(rnodes)} / 区間 {len(redges)}   歩道網: ノード {len(pnodes)} / 区間 {len(pedges)}')

    road_poly = unary_union([LineString(unflat(e['pts'])).buffer(e['w'] / 2, cap_style='round') for e in redges])
    walk_poly = unary_union([LineString(unflat(e['pts'])).buffer(e['w'] / 2 + 4.5) for e in redges]).difference(road_poly)

    # ------------------------------------------------------------ 線路(高架)・首都高(高架)
    rail_lines = [g.intersection(AREA) for g in rails]
    corridor = unary_union([g.buffer(3.2) for g in rail_lines if not g.is_empty]).buffer(9).buffer(-9)
    # 線路の下をくぐる道路は切り欠いてガード下にする
    under_roads = unary_union([LineString(unflat(e['pts'])).buffer(e['w'] / 2 + 1.5) for e in redges if e['w'] >= 7])
    underpass = corridor.intersection(under_roads)
    corridor_solid = corridor.difference(under_roads.buffer(0.5))
    express_lines = [g.intersection(AREA.buffer(40)) for g in express]

    # ------------------------------------------------------------ 建物
    buildings = []
    for b in blds:
        g = proj(shape(b['g'])).intersection(AREA)
        for poly in getattr(g, 'geoms', [g]):
            if poly.geom_type != 'Polygon' or poly.area < 14:
                continue
            poly = shapely.geometry.polygon.orient(poly.simplify(0.35), 1.0)
            if poly.is_empty or poly.geom_type != 'Polygon':
                continue
            h = b.get('height') or (b.get('num_floors') and b['num_floors'] * 3.9)
            if not h:  # 高さ不明: 八重洲の典型的なビル(面積から推定)
                a_ = poly.area
                h = random.uniform(11, 18) if a_ < 90 else random.uniform(22, 34) if a_ < 400 else random.uniform(32, 48)
            mh = b.get('min_height') or 0
            in_rail = poly.representative_point().within(corridor)
            if in_rail:           # ホームの屋根(高架上)
                mh, h = 7.5, 12
            name = b.get('name') or ''
            ov = OVERRIDE.get(name)
            if ov:  # データに高さが無い有名ビル: 低層部 + 塔
                if 'tower' in ov:
                    tower = poly.buffer(-ov['inset'], join_style='mitre')
                    if tower.geom_type == 'MultiPolygon':
                        tower = max(tower.geoms, key=lambda q: q.area)
                    if not tower.is_empty and tower.area > 200:
                        tower = shapely.geometry.polygon.orient(tower.simplify(0.35), 1.0)
                        buildings.append({'p': flat(list(tower.exterior.coords)[:-1]), 'h': ov['tower'], 'mh': 0, 'n': name,
                                          's': 'glass', 'f': []})
                    h = ov['podium']
                else:
                    h = ov['h']
            r_ = random.random()
            style = 'glass' if h >= 90 or (h >= 60 and r_ < 0.3) else ('grid' if r_ < 0.55 else 'office') if h >= 40 else 'mixed'
            if '駅舎' in name or ('東京駅' in name and h < 60):
                style = 'brick'
            if in_rail:
                style = 'canopy'
            if ov and ov.get('style'):
                style = ov['style']
                mh = ov.get('mh', mh)
            ext = list(poly.exterior.coords)[:-1]
            # 道路に面した壁(店舗・看板を付ける面)
            fronts = []
            for i in range(len(ext)):
                a, c = ext[i], ext[(i + 1) % len(ext)]
                ln = math.dist(a, c)
                if ln < 3:
                    continue
                mx, mz = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
                nx, nz = (c[1] - a[1]) / ln, -(c[0] - a[0]) / ln  # 反時計回りの外向き法線
                probe = Point(mx + nx * 7, mz + nz * 7)
                if road_poly.distance(probe) < 3:
                    fronts.append(i)
            buildings.append({'p': flat(ext), 'h': r1(h), 'mh': r1(mh), 'n': name, 's': style, 'f': fronts})
    print(f'建物 {len(buildings)} 棟 (ガラス {sum(b["s"] == "glass" for b in buildings)})')

    # ------------------------------------------------------------ 街路樹・街灯・信号・ガードレール・自販機
    lamps, trees, fences, signals, vendings, signs = [], [], [], [], [], []
    deg = defaultdict(list)
    for i, e in enumerate(redges):
        deg[e['a']].append(i)
        deg[e['b']].append(i)
    junction_r = {}
    for n, es in deg.items():
        if len(es) >= 3:
            junction_r[n] = max(redges[i]['w'] for i in es) / 2 + 3
    near_junction = unary_union([Point(rnodes[n]).buffer(r + 4) for n, r in junction_r.items()]) if junction_r else Polygon()
    bld_union = unary_union([Polygon(unflat(b['p'])) for b in buildings]).buffer(0.8)
    blocked = unary_union([bld_union, corridor_solid])

    def along(line, step, off, jitter=0.0):
        L = line.length
        t = step / 2
        while t < L:
            p = line.interpolate(t)
            q = line.interpolate(min(L, t + 0.5))
            dx, dz = q.x - p.x, q.y - p.y
            ln = math.hypot(dx, dz) or 1
            nx, nz = -dz / ln, dx / ln
            yield p.x + nx * off, p.y + nz * off, math.atan2(-dx, -dz), (nx, nz)
            t += step + random.uniform(-jitter, jitter)

    for e in redges:
        line = LineString(unflat(e['pts']))
        w = e['w']
        for side in (-1, 1):
            for x, z, yaw, (nx, nz) in along(line, 30 if w >= 14 else 36, side * (w / 2 + 1.0)):
                pt = Point(x, z)
                if pt.within(road_poly) or pt.within(blocked):
                    continue
                # 街灯の腕は車道側(=法線の逆向き)へ
                lamps.append([r1(x), r1(z), r1(math.atan2(nx * side, nz * side))])
            if w >= 14:
                for x, z, yaw, _ in along(line, 11, side * (w / 2 + 2.4), 1.5):
                    pt = Point(x, z)
                    if pt.within(road_poly) or pt.within(blocked) or pt.within(near_junction):
                        continue
                    trees.append([r1(x), r1(z), r1(random.uniform(0.8, 1.2))])
            if w >= 10:
                off = side * (w / 2 + 0.45)
                seg = line.parallel_offset(abs(off), 'left' if off > 0 else 'right') if line.length > 6 else None
                if seg is not None and not seg.is_empty:
                    seg = seg.difference(near_junction)
                    for part in getattr(seg, 'geoms', [seg]):
                        if part.geom_type != 'LineString':
                            continue
                        cs = list(part.coords)
                        for i in range(len(cs) - 1):
                            a, c = cs[i], cs[i + 1]
                            if math.dist(a, c) > 0.5 and not LineString([a, c]).intersects(blocked):
                                fences.append([r1(a[0]), r1(a[1]), r1(c[0]), r1(c[1])])
    # 信号機: 3本以上の車道が交わる交差点で、各流入路の左手前に
    for n, es in deg.items():
        if len(es) < 3 or max(redges[i]['w'] for i in es) < 10:
            continue
        nx0, nz0 = rnodes[n]
        R = junction_r[n]
        for i in es:
            e = redges[i]
            cs = unflat(e['pts'])
            if e['b'] == n:
                cs = cs[::-1]
            line = LineString(cs)
            if line.length < R + 3:
                continue
            p = line.interpolate(R + 1)
            q = line.interpolate(R + 2)
            dx, dz = p.x - q.x, p.y - q.y            # 交差点へ向かう向き
            ln = math.hypot(dx, dz) or 1
            dx, dz = dx / ln, dz / ln
            lx, lz = dz, -dx                           # 進行方向の左(左側通行)
            off = e['w'] / 2 + 1.2
            sx, sz = p.x + lx * off, p.y + lz * off
            if Point(sx, sz).within(blocked):
                continue
            # 灯器は交差点へ向かってくる車の方を向く
            signals.append([r1(sx), r1(sz), r1(math.atan2(dx, dz)), r1(min(e['w'] / 2, 7)), n])
    # 自販機: 細い道沿いの建物の壁際
    for b in buildings:
        if b['s'] != 'mixed' or not b['f'] or random.random() > 0.35:
            continue
        ext = unflat(b['p'])
        i = random.choice(b['f'])
        a, c = ext[i], ext[(i + 1) % len(ext)]
        ln = math.dist(a, c)
        t = random.uniform(0.2, 0.8)
        nx, nz = (c[1] - a[1]) / ln, -(c[0] - a[0]) / ln
        x, z = a[0] + (c[0] - a[0]) * t + nx * 1.4, a[1] + (c[1] - a[1]) * t + nz * 1.4
        if Point(x, z).within(road_poly):
            continue
        vendings.append([r1(x), r1(z), r1(math.atan2(-nx, -nz))])
    # 通り名の青看板(主要道路の交差点付近)
    for n, es in deg.items():
        named = [redges[i] for i in es if redges[i]['name'] and redges[i]['w'] >= 14]
        if len(es) >= 3 and named and random.random() < 0.6:
            e = named[0]
            signs.append({'x': rnodes[n][0], 'z': rnodes[n][1], 't': e['name']})
    print(f'街灯 {len(lamps)} / 街路樹 {len(trees)} / 柵 {len(fences)} / 信号 {len(signals)} / 自販機 {len(vendings)}')

    # ------------------------------------------------------------ 路面テクスチャ
    img = Image.new('RGB', (TEX, TEX), (0, 0, 0))
    d = ImageDraw.Draw(img)
    S = TEX / (2 * HALF)
    px = lambda p: ((p[0] + HALF) * S, (p[1] + HALF) * S)

    def fill_poly(g, color):
        # 穴あきポリゴンはマスク経由で描く(穴で他の図形を消さないように)
        mask = Image.new('L', (TEX, TEX), 0)
        md_ = ImageDraw.Draw(mask)
        for pg in getattr(g, 'geoms', [g]):
            if pg.geom_type != 'Polygon' or pg.is_empty:
                continue
            md_.polygon([px(c) for c in pg.exterior.coords], fill=255)
            for hole in pg.interiors:
                md_.polygon([px(c) for c in hole.coords], fill=0)
        img.paste(Image.new('RGB', (TEX, TEX), color), (0, 0), mask)

    fill_poly(walk_poly, (0, 0, 255))
    fill_poly(road_poly, (255, 0, 0))

    WHITE, YELLOW = (255, 255, 0), (255, 0, 255)
    marks = []  # 路面標示のポリゴン [x1,z1,x2,z2,x3,z3,x4,z4, 色(0=白,1=黄)]

    def seg_quad(a, b2, width, color):
        dx, dz = b2[0] - a[0], b2[1] - a[1]
        ln = math.hypot(dx, dz)
        if ln < 0.05:
            return
        nx, nz = -dz / ln * width / 2, dx / ln * width / 2
        marks.append([r1(a[0] + nx), r1(a[1] + nz), r1(b2[0] + nx), r1(b2[1] + nz), r1(b2[0] - nx), r1(b2[1] - nz),
                      r1(a[0] - nx), r1(a[1] - nz), 1 if color == YELLOW else 0])

    def line(cs, width, color, dash=None):
        ls = LineString(cs).difference(near_junction)
        for part in getattr(ls, 'geoms', [ls]):
            if part.geom_type != 'LineString' or part.length < 1:
                continue
            if not dash:
                d.line([px(c) for c in part.coords], fill=color, width=max(1, int(width * S)))
                pc = list(part.coords)
                for k in range(len(pc) - 1):
                    seg_quad(pc[k], pc[k + 1], width, color)
                continue
            on, off = dash
            t = 0
            while t < part.length:
                a, b2 = part.interpolate(t), part.interpolate(min(part.length, t + on))
                d.line([px((a.x, a.y)), px((b2.x, b2.y))], fill=color, width=max(1, int(width * S)))
                seg_quad((a.x, a.y), (b2.x, b2.y), width, color)
                t += on + off

    for e in redges:
        cs = unflat(e['pts'])
        ls = LineString(cs)
        w = e['w']
        if ls.length < 4:
            continue
        if e.get('ow'):
            lanes = max(1, round(w / 3.3))
            for k in range(1, lanes):
                off = ls.parallel_offset(abs(w / 2 - w * k / lanes), 'left' if k < lanes / 2 else 'right') if abs(w / 2 - w * k / lanes) > 0.1 else ls
                if not off.is_empty:
                    for part in getattr(off, 'geoms', [off]):
                        line(list(part.coords), 0.15, WHITE, (5, 5))
        elif w >= 14:
            line(cs, 0.15, YELLOW)                         # 中央線(黄・追越し禁止)
            for s in (-1, 1):
                for k in ([0.5] if w < 20 else [1 / 3, 2 / 3]):
                    off = ls.parallel_offset(w / 2 * k, 'left' if s > 0 else 'right')
                    if not off.is_empty:
                        for part in getattr(off, 'geoms', [off]):
                            line(list(part.coords), 0.15, WHITE, (5, 5))  # 車線境界(破線)
        elif w >= 10:
            line(cs, 0.15, WHITE, (5, 5))
        if w >= 6:
            for s in ('left', 'right'):
                off = ls.parallel_offset(w / 2 - 0.35, s)
                if not off.is_empty:
                    for part in getattr(off, 'geoms', [off]):
                        line(list(part.coords), 0.15, WHITE)          # 車道外側線
    # 横断歩道と停止線
    for n, es in deg.items():
        if n not in junction_r:
            continue
        R = junction_r[n]
        for i in es:
            e = redges[i]
            if e['w'] < 7:
                continue
            cs = unflat(e['pts'])
            if e['b'] == n:
                cs = cs[::-1]
            ls = LineString(cs)
            if ls.length < R + 8:
                continue
            p, q = ls.interpolate(R + 1.5), ls.interpolate(R + 2.5)
            dx, dz = q.x - p.x, q.y - p.y
            ln = math.hypot(dx, dz) or 1
            dx, dz = dx / ln, dz / ln                   # 交差点から離れる向き
            nx, nz = -dz, dx
            half = e['w'] / 2 - 0.4
            k = -half
            while k < half:                             # しま模様(道路と平行な帯)
                a = (p.x + nx * k, p.y + nz * k)
                b2 = (p.x + nx * k + dx * 4, p.y + nz * k + dz * 4)
                c2 = (b2[0] + nx * 0.45, b2[1] + nz * 0.45)
                a2 = (a[0] + nx * 0.45, a[1] + nz * 0.45)
                d.polygon([px(a), px(b2), px(c2), px(a2)], fill=WHITE)
                marks.append([r1(v) for v in (*a, *b2, *c2, *a2)] + [0])
                k += 0.9
            # 停止線: 交差点へ向かう車線(=離れる向きの右側)
            sp = (p.x + dx * 5.5, p.y + dz * 5.5)
            a = (sp[0], sp[1])
            b2 = (sp[0] - nx * half, sp[1] - nz * half)
            d.line([px(a), px(b2)], fill=WHITE, width=max(1, int(0.45 * S)))
            seg_quad(a, b2, 0.45, WHITE)
            # 進行方向の矢印(停止線の 6m 手前、各車線の中央)
            if e['w'] >= 10:
                lanes = max(1, round((e['w'] if e.get('ow') else e['w'] / 2) / 3.3))
                span = half if e.get('ow') else half
                for li in range(lanes):
                    off = (li + 0.5) * (span * (2 if e.get('ow') else 1)) / lanes - (half if e.get('ow') else 0)
                    cx0, cz0 = sp[0] + dx * 6 - nx * off, sp[1] + dz * 6 - nz * off
                    # 軸(交差点へ向かう向き = -d)
                    tail = (cx0 + dx * 2.5, cz0 + dz * 2.5)
                    head = (cx0 - dx * 0.8, cz0 - dz * 0.8)
                    seg_quad(tail, head, 0.18, WHITE)
                    tip = (cx0 - dx * 2.2, cz0 - dz * 2.2)
                    l1 = (head[0] + nx * 0.45, head[1] + nz * 0.45)
                    r1_ = (head[0] - nx * 0.45, head[1] - nz * 0.45)
                    marks.append([r1(v) for v in (*l1, *tip, *tip, *r1_)] + [0])
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    os.makedirs(OUT, exist_ok=True)
    img.save(os.path.join(OUT, 'ground.webp'), quality=88)

    # ------------------------------------------------------------ ミニマップ
    M = 1024
    mm = Image.new('RGB', (M, M), (12, 13, 22))
    md = ImageDraw.Draw(mm)
    ms = M / (2 * HALF)
    mp = lambda p: ((p[0] + HALF) * ms, (p[1] + HALF) * ms)

    def mfill(g, color):
        for pg in getattr(g, 'geoms', [g]):
            if pg.geom_type == 'Polygon' and not pg.is_empty:
                md.polygon([mp(c) for c in pg.exterior.coords], fill=color)
    mfill(walk_poly, (34, 36, 50))
    mfill(corridor, (28, 34, 58))
    mfill(road_poly, (70, 74, 96))
    for b in buildings:
        md.polygon([mp(c) for c in unflat(b['p'])], fill=(22, 23, 34) if b['s'] != 'canopy' else (40, 48, 80),
                   outline=(48, 50, 70))
    for g in rail_lines:
        for part in getattr(g, 'geoms', [g]):
            if part.geom_type == 'LineString':
                md.line([mp(c) for c in part.coords], fill=(70, 100, 170), width=1)
    mm.save(os.path.join(OUT, 'minimap.png'))

    # 縁石: 車道の外周(建物や高架に重なる所は除く)
    curbs = []
    edge = road_poly.boundary.difference(blocked.buffer(0.3)).intersection(AREA.buffer(-3))
    for part in getattr(edge, 'geoms', [edge]):
        if part.geom_type != 'LineString':
            continue
        cs = list(part.simplify(0.15).coords)
        for i in range(len(cs) - 1):
            if math.dist(cs[i], cs[i + 1]) > 0.3:
                curbs.append([r1(cs[i][0]), r1(cs[i][1]), r1(cs[i + 1][0]), r1(cs[i + 1][1])])
    print(f'縁石 {len(curbs)} 区間')

    def polys(g):
        return [flat(list(pg.exterior.coords)[:-1]) for pg in getattr(g, 'geoms', [g])
                if pg.geom_type == 'Polygon' and pg.area > 4]

    data = {
        'origin': [LAT0, LON0], 'half': HALF,
        'buildings': buildings,
        'roads': {'nodes': rnodes, 'edges': redges},
        'walks': {'nodes': pnodes, 'edges': pedges},
        'rails': [flat(list(p.coords)) for g in rail_lines for p in getattr(g, 'geoms', [g]) if p.geom_type == 'LineString'],
        'corridor': polys(corridor_solid), 'underpass': polys(underpass),
        'express': [flat(list(p.coords)) for g in express_lines for p in getattr(g, 'geoms', [g]) if p.geom_type == 'LineString'],
        'landmarks': [{'n': b['n'], 'h': b['h'], 'c': [r1(v) for v in Polygon(unflat(b['p'])).centroid.coords[0]]}
                      for b in buildings if b['n']],
        'marks': marks,
        'curbs': curbs,
        'lamps': lamps, 'trees': trees, 'fences': fences, 'signals': signals, 'vendings': vendings, 'signs': signs,
    }
    with open(os.path.join(OUT, 'yaesu.json'), 'w') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    print('出力:', {n: f'{os.path.getsize(os.path.join(OUT, n)) / 1e6:.2f}MB' for n in os.listdir(OUT)})


def unflat(a):
    return [(a[i], a[i + 1]) for i in range(0, len(a), 2)]


if __name__ == '__main__':
    main()
