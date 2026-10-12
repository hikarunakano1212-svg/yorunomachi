"""射点配置図・射点立面図・ロケット外形図を DXF で書き出し、プレビュー PNG を作る。

    python rocket/drawings.py

モデル空間に実寸(mm)で描き、図枠と文字を尺度倍して置く(図面を CAD で測ると実寸になる)。
寸法はすべて geometry.py から読む。
"""
import math
import sys
from pathlib import Path

import ezdxf
from ezdxf.enums import TextEntityAlignment
from shapely.geometry import LineString, MultiLineString, Polygon, Point, box
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).parent))
import geometry as G  # noqa: E402

OUT = Path(__file__).parent / "out" / "drawings"
DATE = "2026-10-12"
PROJECT = "架空大型ロケット 射点計画"
FICTION = "架空の機体・射場のイメージで、実在の図面ではない。"

PAPER = (594, 420)                 # A2 横
FRAME = (20, 10, 584, 410)         # 図枠(とじ代 20)
TB = (404, 10, 584, 74)            # 表題欄
BG = "#0a1730"                     # プレビューの背景(濃紺)

# 画層: (RGB, 線の太さ 1/100mm, 線種)
LAYERS = {
    "外形線": ((70, 242, 226), 50, "Continuous"),
    "細線": ((44, 196, 204), 25, "Continuous"),
    "隠れ線": ((34, 160, 180), 25, "DASHED"),
    "中心線": ((84, 164, 236), 18, "CENTER"),
    "寸法": ((96, 204, 255), 18, "Continuous"),
    "文字": ((176, 255, 246), 25, "Continuous"),
    "図枠": ((64, 224, 212), 70, "Continuous"),
    "図枠細線": ((40, 160, 172), 25, "Continuous"),
    "ハッチ": ((28, 118, 140), 13, "Continuous"),
    "海": ((44, 136, 196), 18, "Continuous"),
    "グリッド": ((24, 84, 110), 13, "Continuous"),
    "架空地線": ((84, 164, 236), 18, "DASHDOT"),
}

ALIGN = {
    "BL": TextEntityAlignment.BOTTOM_LEFT, "BC": TextEntityAlignment.BOTTOM_CENTER,
    "BR": TextEntityAlignment.BOTTOM_RIGHT, "ML": TextEntityAlignment.MIDDLE_LEFT,
    "MC": TextEntityAlignment.MIDDLE_CENTER, "MR": TextEntityAlignment.MIDDLE_RIGHT,
    "TL": TextEntityAlignment.TOP_LEFT, "TC": TextEntityAlignment.TOP_CENTER,
    "TR": TextEntityAlignment.TOP_RIGHT,
}


def text_width(s, h):
    """文字列のおおよその幅(プレビューのフォントで測った値: 全角=1.38h、半角=0.70h)。"""
    return sum(1.38 * h if ord(c) > 0x2000 else 0.70 * h for c in s)


def fmt(v):
    """寸法の数字: 3桁区切り。"""
    return f"{int(round(v)):,}"


class Sheet:
    def __init__(self, fname, title, number, scale, origin, notes):
        self.fname, self.title, self.number, self.K = fname, title, number, scale
        self.notes = notes
        self.doc = ezdxf.new("R2018", setup=True)
        self.doc.units = ezdxf.units.MM
        self.doc.header["$INSUNITS"] = 4
        self.doc.header["$MEASUREMENT"] = 1
        self.doc.header["$LTSCALE"] = scale * 1.4
        self.doc.header["$LWDISPLAY"] = 1
        for name, (rgb, lw, lt) in LAYERS.items():
            ly = self.doc.layers.add(name)
            ly.rgb = rgb
            ly.color = 4
            ly.dxf.lineweight = lw
            ly.dxf.linetype = lt
        self.doc.styles.add("JP", font="msgothic.ttc")
        ds = self.doc.dimstyles.new("TEAL")
        ds.dxf.dimtxsty = "JP"
        for k, v in dict(dimtxt=2.2, dimasz=1.8, dimexo=1.0, dimexe=1.2, dimgap=0.7,
                         dimscale=scale, dimdec=0, dimtad=1, dimtih=0, dimtoh=0,
                         dimclrd=0, dimclre=0, dimclrt=0, dimzin=8, dimlunit=2,
                         dimdsep=ord(".")).items():
            ds.set_dxf_attrib(k, v)
        self.msp = self.doc.modelspace()
        self.ox, self.oy = -origin[0] * scale, -origin[1] * scale
        self.texts = []          # 重なり確認用: (文字列, 紙の上の bbox)
        self.window = None       # 図形を切り取る範囲(モデル座標の Polygon)

    # --- 座標 -------------------------------------------------------------
    def P(self, px, py):
        """紙の座標(mm) → モデル座標。"""
        return (self.ox + px * self.K, self.oy + py * self.K)

    def to_paper(self, x, y):
        return ((x - self.ox) / self.K, (y - self.oy) / self.K)

    def set_window(self, px0, py0, px1, py1, holes=()):
        poly = box(*self.P(px0, py0), *self.P(px1, py1))
        for h in holes:
            poly = poly.difference(box(*self.P(h[0], h[1]), *self.P(h[2], h[3])))
        self.window = poly

    # --- 図形 -------------------------------------------------------------
    def _emit(self, pts, layer, closed=False):
        if len(pts) >= 2:
            self.msp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": layer})

    def line(self, pts, layer="外形線", closed=False, clip=True):
        pts = [tuple(p[:2]) for p in pts]
        if closed:
            pts = pts + [pts[0]]
        if clip and self.window is not None:
            geom = LineString(pts)
            if not self.window.contains(geom):
                geom = geom.intersection(self.window)
                for g in getattr(geom, "geoms", [geom]):
                    if isinstance(g, LineString) and not g.is_empty:
                        self._emit(list(g.coords), layer)
                return
        self._emit(pts, layer)

    def geom(self, g, layer):
        """shapely の線(複数可)を書く。"""
        for s in getattr(g, "geoms", [g]):
            if isinstance(s, LineString) and not s.is_empty and s.length > 1:
                self.line(list(s.coords), layer)
            elif hasattr(s, "geoms"):
                self.geom(s, layer)

    def rect(self, x0, y0, x1, y1, layer="外形線"):
        self.line([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer, closed=True)

    def circle(self, c, r, layer="外形線"):
        if self.window is not None and not self.window.contains(Point(c).buffer(r)):
            self.line(circle_pts(c, r), layer)
            return
        self.msp.add_circle(c, r, dxfattribs={"layer": layer})

    def hatch(self, polys, pattern="ANSI31", scale=1.0, angle=0.0, layer="ハッチ"):
        h = self.msp.add_hatch(dxfattribs={"layer": layer})
        h.set_pattern_fill(pattern, scale=scale * self.K * 0.5, angle=angle)
        for poly in polys:
            h.paths.add_polyline_path([tuple(p[:2]) for p in poly], is_closed=True)

    def solid(self, pts, layer="外形線"):
        h = self.msp.add_hatch(dxfattribs={"layer": layer})
        h.set_solid_fill(color=4)
        h.dxf.color = 256
        h.paths.add_polyline_path(pts, is_closed=True)

    # --- 文字 -------------------------------------------------------------
    def text(self, s, pos, h=3.0, align="MC", layer="文字", rot=0.0, check=True):
        """pos はモデル座標、h は紙の上の文字高さ(mm)。"""
        t = self.msp.add_text(s, height=h * self.K, rotation=rot,
                              dxfattribs={"layer": layer, "style": "JP"})
        t.set_placement(pos, align=ALIGN[align])
        if check:
            px, py = self.to_paper(*pos)
            w = text_width(s, h)
            ax = {"L": 0, "C": -w / 2, "R": -w}[align[1]]
            ay = {"B": 0, "M": -h / 2, "T": -h}[align[0]]
            if abs(rot - 90) < 1:
                bb = (px - ay - h, py + ax, px - ay, py + ax + w)
            else:
                bb = (px + ax, py + ay, px + ax + w, py + ay + h)
            self.texts.append((s, bb))
        return t

    def ptext(self, s, px, py, h=3.0, align="MC", **kw):
        return self.text(s, self.P(px, py), h, align, **kw)

    def label(self, s, anchor, dx, dy, h=2.8, side=None, dot=True):
        """引出線つきの名前。anchor から紙の上で (dx, dy) mm 離れた位置に書く。"""
        K = self.K
        bend = (anchor[0] + dx * K, anchor[1] + dy * K)
        side = side or ("R" if dx >= 0 else "L")
        w = text_width(s, h) + 1.0
        end = (bend[0] + (w if side == "R" else -w) * K, bend[1])
        self.line([anchor, bend, end], "細線", clip=False)
        if dot:
            self.solid(circle_pts(anchor, 0.45 * K, 10), "細線")
        mid = ((bend[0] + end[0]) / 2, bend[1] + 0.6 * K)
        self.text(s, mid, h, "BC")

    # --- 寸法 -------------------------------------------------------------
    def dim(self, p1, p2, off, vertical=False, text=None):
        """p1-p2 の水平/垂直寸法。off は寸法線までの紙の上の距離(mm、符号で側を指定)。"""
        K = self.K
        if vertical:
            base = (p1[0] + off * K, p1[1])
            angle = 90
        else:
            base = (p1[0], p1[1] + off * K)
            angle = 0
        d = self.msp.add_linear_dim(base=base, p1=p1, p2=p2, angle=angle, dimstyle="TEAL",
                                    text=text if text else "<>",
                                    dxfattribs={"layer": "寸法",
                                                "true_color": ezdxf.rgb2int(LAYERS["寸法"][0])})
        d.render()
        # 寸法のブロックの中身にも色を付ける(BYBLOCK を解決しない読み手のため)
        blk = d.dimension.get_geometry_block()
        if blk is not None:
            for e in blk:
                e.dxf.layer = "寸法"
                e.dxf.true_color = ezdxf.rgb2int(LAYERS["寸法"][0])

    def level(self, x, z, s, side="L", h=2.6):
        """高さの記号(▽)と高さの文字。"""
        K = self.K
        tri = [(x, z), (x - 1.3 * K, z + 2.2 * K), (x + 1.3 * K, z + 2.2 * K)]
        self.line(tri, "寸法", closed=True, clip=False)
        L = text_width(s, h) + 3
        x1 = x - L * K if side == "L" else x + L * K
        self.line([(x - 2 * K if side == "R" else x + 2 * K, z), (x1, z)], "寸法", clip=False)
        tx = x - 2.0 * K if side == "L" else x + 2.0 * K
        self.text(s, (tx, z + 0.8 * K), h, "BR" if side == "L" else "BL")

    def centerline(self, p0, p1):
        self.line([p0, p1], "中心線", clip=False)

    # --- 図枠・表題欄 ------------------------------------------------------
    def frame(self):
        P = self.P
        self.line([P(0, 0), P(594, 0), P(594, 420), P(0, 420)], "図枠細線", closed=True, clip=False)
        x0, y0, x1, y1 = FRAME
        self.line([P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)], "図枠", closed=True, clip=False)
        # 区域の目盛
        for i in range(8):
            xa = x0 + (x1 - x0) * i / 8
            if i:
                self.line([P(xa, y1), P(xa, y1 + 4)], "図枠細線", clip=False)
                self.line([P(xa, y0), P(xa, y0 - 4)], "図枠細線", clip=False)
            xm = x0 + (x1 - x0) * (i + 0.5) / 8
            self.ptext(str(i + 1), xm, y1 + 5, 2.5, check=False)
            self.ptext(str(i + 1), xm, y0 - 5, 2.5, check=False)
        for j in range(6):
            ya = y0 + (y1 - y0) * j / 6
            if j:
                self.line([P(x0, ya), P(x0 - 4, ya)], "図枠細線", clip=False)
                self.line([P(x1, ya), P(x1 + 4, ya)], "図枠細線", clip=False)
            ym = y0 + (y1 - y0) * (j + 0.5) / 6
            self.ptext("FEDCBA"[j], x0 - 6, ym, 2.5, check=False)
            self.ptext("FEDCBA"[j], x1 + 5, ym, 2.5, check=False)
        # 中心マーク
        for (a, b) in [((297, 0), (297, y0)), ((297, 420), (297, y1)),
                       ((0, 210), (x0, 210)), ((594, 210), (x1, 210))]:
            self.line([P(*a), P(*b)], "図枠", clip=False)
        self.title_block()
        self.notes_box()

    def title_block(self):
        P = self.P
        x0, y0, x1, y1 = TB
        self.line([P(x0, y0), P(x1, y0), P(x1, y1), P(x0, y1)], "図枠", closed=True, clip=False)
        rows = [62, 48, 38, 28]
        for r in rows:
            self.line([P(x0, r), P(x1, r)], "図枠細線", clip=False)
        lab = 20
        self.line([P(x0 + lab, 28), P(x0 + lab, y1)], "図枠細線", clip=False)
        H = 2.4
        self.ptext("件名", x0 + lab / 2, 68, H)
        self.ptext(PROJECT, x0 + lab + 4, 68, 3.5, "ML")
        self.ptext("図名", x0 + lab / 2, 55, H)
        self.ptext(self.title, x0 + lab + 4, 55, 6.0, "ML")
        # 図番・尺度・用紙 / 単位・日付・版
        cells = [(x0 + lab, 80), (x0 + 100, 116), (x0 + 136, 180)]
        row_a = [("図番", self.number), ("尺度", f"1:{self.K}"), ("用紙", "A2")]
        row_b = [("単位", "mm"), ("作成日", DATE), ("版", "A")]
        for (cx0, cx1), (k1, v1), (k2, v2) in zip(
                [(x0 + lab, x0 + 80), (x0 + 80, x0 + 130), (x0 + 130, x1)], row_a, row_b):
            if cx0 != x0 + lab:
                self.line([P(cx0, 28), P(cx0, 48)], "図枠細線", clip=False)
            self.ptext(k1, cx0 + 2, 43, H, "ML")
            self.ptext(v1, cx0 + 14, 43, 3.2, "ML")
            self.ptext(k2, cx0 + 2, 33, H, "ML")
            self.ptext(v2, cx0 + 14, 33, 3.2, "ML")
        self.line([P(x0 + 12, 28), P(x0 + 12, 48)], "図枠細線", clip=False) if False else None
        # 作成・照査・承認
        self.ptext("作成", x0 + lab / 2, 23.5, H)
        self.ptext("照査", x0 + lab / 2, 14.5, H)
        self.line([P(x0, 19), P(x0 + 70, 19)], "図枠細線", clip=False)
        self.line([P(x0 + 70, 10), P(x0 + 70, 28)], "図枠細線", clip=False)
        self.ptext("承認", x0 + 76, 23.5, H)
        self.line([P(x0 + 82, 10), P(x0 + 82, 28)], "図枠細線", clip=False)
        self.line([P(x0 + 112, 10), P(x0 + 112, 28)], "図枠細線", clip=False)
        # 架空であることの印
        sx, sy = x0 + 146, 19
        self.line([P(sx - 30, sy - 7), P(sx + 30, sy - 7), P(sx + 30, sy + 7), P(sx - 30, sy + 7)],
                  "外形線", closed=True, clip=False)
        self.ptext("架 空 / 実在しない", sx, sy + 2.2, 3.4)
        self.ptext("CONCEPT IMAGE ONLY", sx, sy - 3.4, 2.2)

    def notes_box(self):
        x0, x1 = TB[0], TB[2]
        if not self.notes:
            self.notes_top = TB[3]
            return
        y = 80
        lines = []
        for i, n in enumerate(self.notes, 1):
            lines += wrap(f"{i}. {n}", 2.6, x1 - x0 - 8, indent="   ")
        h = 9 + len(lines) * 4.4 + 3
        P = self.P
        self.line([P(x0, y), P(x1, y), P(x1, y + h), P(x0, y + h)], "図枠細線", closed=True, clip=False)
        self.ptext("特記事項", x0 + 4, y + h - 5, 3.2, "ML")
        self.line([P(x0, y + h - 9), P(x1, y + h - 9)], "図枠細線", clip=False)
        for k, s in enumerate(lines):
            self.ptext(s, x0 + 4, y + h - 13.5 - k * 4.4, 2.6, "ML")
        self.notes_top = y + h

    def save(self):
        OUT.mkdir(parents=True, exist_ok=True)
        path = OUT / f"{self.fname}.dxf"
        self.doc.saveas(path)
        return path


def wrap(s, h, width, indent=""):
    out, cur = [], ""
    for c in s:
        if text_width(cur + c, h) > width:
            out.append(cur)
            cur = indent + c
        else:
            cur += c
    if cur:
        out.append(cur)
    return out


def circle_pts(c, r, n=48):
    return [(c[0] + r * math.cos(2 * math.pi * i / n), c[1] + r * math.sin(2 * math.pi * i / n))
            for i in range(n + 1)]


def rot(p, ang, about=(0, 0)):
    c, s = math.cos(ang), math.sin(ang)
    x, y = p[0] - about[0], p[1] - about[1]
    return (about[0] + x * c - y * s, about[1] + x * s + y * c)


def offset_line(pts, d):
    """折れ線を左右に d だけずらした2本(道路の縁)。"""
    ls = LineString(pts)
    return ls.offset_curve(d, join_style=2), ls.offset_curve(-d, join_style=2)


def table(S, x0, x1, top, title, rows, col=46, rh=5.0, h=2.5):
    """右欄の表。top から下へ描き、下端の y を返す。"""
    P = S.P
    hh = 8 + rh * len(rows)
    y0 = top - hh
    S.line([P(x0, y0), P(x1, y0), P(x1, top), P(x0, top)], "図枠細線", closed=True, clip=False)
    S.ptext(title, x0 + 4, top - 4, 3.0, "ML")
    S.line([P(x0, top - 8), P(x1, top - 8)], "図枠細線", clip=False)
    if col:
        S.line([P(x0 + col, y0), P(x0 + col, top - 8)], "図枠細線", clip=False)
    for i, row in enumerate(rows):
        yy = top - 8 - rh * (i + 0.5)
        if isinstance(row[0], str):
            S.ptext(row[0], x0 + 3, yy, h, "ML")
        else:
            row[0](x0 + 3, yy)
        S.ptext(row[1], x0 + col + 3, yy, h, "ML")
    return y0


def north_arrow(S, px, py, r=7):
    K = S.K
    nx, ny = S.P(px, py)
    r = r * K
    S.circle((nx, ny), r, "細線")
    S.solid([(nx, ny + r * 1.25), (nx - r * 0.35, ny - r * 0.6), (nx, ny - r * 0.25)], "外形線")
    S.line([(nx, ny + r * 1.25), (nx + r * 0.35, ny - r * 0.6), (nx, ny - r * 0.25)], "外形線", clip=False)
    S.text("N", (nx, ny + r * 1.25 + 1.5 * K), 3.5, "BC")


def scale_bar(S, px, py, step_m, n):
    K = S.K
    bx, by = S.P(px, py)
    st = step_m * 1000
    for i in range(n):
        x0 = bx + i * st
        if i % 2 == 0:
            S.solid([(x0, by), (x0 + st, by), (x0 + st, by + 1.2 * K), (x0, by + 1.2 * K)], "細線")
        else:
            S.line([(x0, by), (x0 + st, by), (x0 + st, by + 1.2 * K), (x0, by + 1.2 * K)], "細線",
                   closed=True, clip=False)
        S.text(str(i * step_m), (x0, by - 1.0 * K), 2.2, "TC")
    S.text(f"{n * step_m} m", (bx + n * st, by - 1.0 * K), 2.2, "TC")


def view_title(S, px, py, name, scale):
    S.ptext(name, px, py, 6, "ML")
    S.ptext(scale, px + text_width(name, 6) + 7, py - 0.6, 3.6, "ML")


def legend_row(S, layer, kind="line"):
    def draw(px, py):
        a, b = S.P(px, py), S.P(px + 14, py)
        if kind == "hatch":
            S.line([S.P(px, py - 1.5), S.P(px + 14, py - 1.5), S.P(px + 14, py + 1.5), S.P(px, py + 1.5)],
                   "外形線", closed=True, clip=False)
            S.line([S.P(px + 1, py - 0.7), S.P(px + 13, py - 0.7), S.P(px + 13, py + 0.7), S.P(px + 1, py + 0.7)],
                   "細線", closed=True, clip=False)
        elif kind == "slope":
            S.line([a, b], "細線", clip=False)
            for k in range(8):
                L = 2.4 if k % 2 == 0 else 1.2
                S.line([S.P(px + 1 + k * 1.7, py), S.P(px + 1 + k * 1.7, py - L)], "ハッチ", clip=False)
        else:
            S.line([a, b], layer, clip=False)
    return draw


# ===========================================================================
# 1. 射点配置図 S=1:500
# ===========================================================================
def plan_sheet():
    notes = [
        FICTION,
        "寸法の単位は mm、座標の原点はロケットの中心(X=0, Y=0)とする。",
        "X は東、Y は北を正とする。グリッドは 20 m 間隔。",
        "機体・設備の寸法と位置は形状モジュール rocket/geometry.py の値による。",
    ]
    S = Sheet("1_射点配置図", "射点配置図", "LP-001", 500, (212, 214), notes)
    K = S.K
    S.frame()

    # グリッド(ラベルは枠の内側の余白に)
    S.set_window(31, 12, 400, 398)
    for v in range(-80000, 80001, 20000):
        S.line([(v, -100000), (v, 100000)], "グリッド")
        S.line([(-100000, v), (100000, v)], "グリッド")
    for v in range(-80000, 80001, 40000):
        s = (f"{v // 1000:+d}" if v else "0").replace("-", "−")
        S.text("X" + s, (v, S.P(0, 403)[1]), 2.4, "MC", layer="寸法")
        S.text("Y" + s, (S.P(25.5, 0)[0], v), 2.4, "MC", layer="寸法")
    S.set_window(22, 12, 400, 408)

    # 海岸線・段丘の肩・法面の記号・海
    S.line(G.COAST_LINE, "外形線")
    S.line(G.BANK_TOP, "細線")
    coast = LineString(G.COAST_LINE)
    top = LineString(G.BANK_TOP)
    n = 140
    for i in range(n + 1):
        p = top.interpolate(i / n, normalized=True)
        q = coast.interpolate(coast.project(Point(p.x, p.y - 8000)))
        f = 1.0 if i % 2 == 0 else 0.5
        S.line([(p.x, p.y), (p.x + (q.x - p.x) * f, p.y + (q.y - p.y) * f)], "ハッチ")
    keep_out = [box(-66000, -101000, -54000, -93000), box(-3000, -104000, 30000, -88000)]
    for j, yy in enumerate(range(-93000, -104000, -4000)):
        for xx in range(-90000 + (j % 2) * 6000, 92000, 12000):
            wave = [(xx + t * 600, yy + 450 * math.sin(t / 10 * 2 * math.pi)) for t in range(11)]
            if any(k.intersects(LineString(wave)) for k in keep_out):
                continue
            S.line(wave, "海")
    S.text("海", (-60000, -97000), 5, "MC", layer="海")
    # 立面図の視方向(海から北を見る)
    vx, vy = 0, -92000
    S.solid([(vx, vy), (vx - 1.5 * K, vy - 4 * K), (vx + 1.5 * K, vy - 4 * K)], "外形線")
    S.line([(vx, vy - 4 * K), (vx, vy - 10 * K)], "外形線")
    S.text("立面図 視方向", (vx + 2.5 * K, vy - 7 * K), 2.6, "ML")

    # 射点の床・道路・レール
    S.line(G.APRON, "外形線", closed=True)
    for road in G.ROADS:
        for edge in offset_line(road, G.ROAD_W / 2):
            S.geom(edge, "細線")
    for rx in G.RAILS_X:
        S.line([(rx, G.ML["d"] / 2), (rx, 100000)], "細線")
    S.line([(0, 82000), (0, 92000)], "細線")
    S.solid([(0, 94000), (-0.9 * K, 90000), (0.9 * K, 90000)], "細線")
    S.text("至 組立棟", (11500, 89000), 2.8, "ML")

    # 排煙溝(覆蓋部は破線)
    T = G.TRENCH
    hw = T["w"] / 2
    north = G.ML["d"] / 2 - 4000
    for x in (-hw, hw):
        S.line([(x, north), (x, T["y_cover"])], "隠れ線")
        S.line([(x, T["y_cover"]), (x, T["y_outlet"])], "外形線")
        sx = x + math.copysign(T["wall"], x)
        S.line([(sx, T["y_cover"]), (sx, T["y_outlet"])], "細線")
    S.line([(-hw, north), (hw, north)], "隠れ線")
    S.line([(-hw - T["wall"], T["y_cover"]), (hw + T["wall"], T["y_cover"])], "細線")
    S.line([(-hw - T["wall"], T["y_outlet"]), (hw + T["wall"], T["y_outlet"])], "外形線")
    for y in range(int(T["y_cover"]) - 6000, int(T["y_outlet"]), -6000):   # 床の勾配の目地
        if not -56000 < y < -46000:
            S.line([(-hw + 1500, y), (hw - 1500, y)], "ハッチ")
    S.solid([(0, -66000), (-1.0 * K, -62000), (1.0 * K, -62000)], "細線")
    S.line([(0, -56000), (0, -62000)], "細線")
    S.text("流下", (0, -55000), 2.4, "BC")
    dy0, dy1 = T["deflector_y"]
    S.line([(-hw, dy0), (hw, dy0), (hw, dy1), (-hw, dy1)], "隠れ線", closed=True)

    # 移動発射台
    M = G.ML
    S.rect(-M["w"] / 2, -M["d"] / 2, M["w"] / 2, M["d"] / 2, "外形線")
    for (cx, cy, w, d) in M["holes"]:
        S.rect(cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2, "細線")
    for (px, py) in M["pedestals"]:
        a = M["pedestal"] / 2
        S.rect(px - a, py - a, px + a, py + a, "隠れ線")

    # ロケット(上から)
    S.circle((0, 0), G.FAIRING_R, "外形線")
    S.circle((0, 0), G.CORE_R, "隠れ線")
    for c in G.SRB_CENTERS:
        S.circle(c, G.SRB_R, "外形線")
        S.circle(c, G.SRB_SKIRT_R, "細線")
    S.centerline((-14000, 0), (14000, 0))
    S.centerline((0, -14000), (0, 14000))

    # アンビリカルタワーとアクセスアーム
    Tw = G.TOWER
    tx0, tx1 = Tw["cx"] - Tw["w"] / 2, Tw["cx"] + Tw["w"] / 2
    ty0, ty1 = Tw["cy"] - Tw["w"] / 2, Tw["cy"] + Tw["w"] / 2
    S.rect(tx0, ty0, tx1, ty1, "外形線")
    c = Tw["column"]
    for (qx, qy) in [(tx0, ty0), (tx1 - c, ty0), (tx0, ty1 - c), (tx1 - c, ty1 - c)]:
        S.rect(qx, qy, qx + c, qy + c, "細線")
    S.line([(tx0, ty0), (tx1, ty1)], "細線")
    S.line([(tx0, ty1), (tx1, ty0)], "細線")
    x0, x1, y0, y1 = G.arm_points(G.ARMS[0])
    S.rect(x0, y0, x1, y1, "外形線")
    hinge = (x1, y1)
    ang = -math.radians(G.ARM_SWING_DEG)
    swung = [rot(p, ang, hinge) for p in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]]
    S.line(swung, "隠れ線", closed=True)
    r = math.dist(hinge, (x0, 0))
    a0 = math.atan2(0 - hinge[1], x0 - hinge[0])
    S.line([(hinge[0] + r * math.cos(a0 + ang * i / 20), hinge[1] + r * math.sin(a0 + ang * i / 20))
            for i in range(21)], "中心線")
    swung_mid = rot((x0, 0), ang, hinge)

    # 避雷塔と架空地線
    for (x, y) in G.LIGHTNING_TOWERS:
        a = G.LIGHTNING["base_w"] / 2
        S.rect(x - a, y - a, x + a, y + a, "外形線")
        S.line([(x - a, y - a), (x + a, y + a)], "細線")
        S.line([(x - a, y + a), (x + a, y - a)], "細線")
        S.circle((x, y), G.LIGHTNING["top_w"] / 2, "細線")
    for i, j in G.CATENARY:
        S.line([G.LIGHTNING_TOWERS[i], G.LIGHTNING_TOWERS[j]], "架空地線")

    # 照明塔(灯具はロケットへ向ける)
    for i, (x, y) in enumerate(G.LIGHT_TOWERS):
        S.circle((x, y), G.LIGHT["pole_d"] / 2, "外形線")
        az, _ = G.light_aim(i)
        hw_, hd = G.LIGHT["head_w"] / 2, G.LIGHT["head_d"] / 2
        pts = [rot(p, az) for p in [(-hd, -hw_), (hd, -hw_), (hd, hw_), (-hd, hw_)]]
        S.line([(x + p[0], y + p[1]) for p in pts], "細線", closed=True)
        tip = rot((14000, 0), az)
        S.line([(x, y), (x + tip[0], y + tip[1])], "中心線")

    # 水タンク・推進薬タンク
    for (x, y) in G.WATER_TANKS:
        S.circle((x, y), G.WATER_TANK["d"] / 2, "外形線")
        S.circle((x, y), G.WATER_TANK["d"] / 2 - 700, "細線")
        S.centerline((x - 9500, y), (x + 9500, y))
        S.centerline((x, y - 9500), (x, y + 9500))
    for (_, x, y) in G.SPHERES:
        r = G.SPHERE["d"] / 2
        S.circle((x, y), r, "外形線")
        for k in range(6):
            a = 2 * math.pi * k / 6
            S.circle((x + r * 0.8 * math.cos(a), y + r * 0.8 * math.sin(a)), 400, "細線")
        S.centerline((x - r - 2000, y), (x + r + 2000, y))
        S.centerline((x, y - r - 2000), (x, y + r + 2000))

    # 建屋(二重線の中に名前)
    for (name, x, y, w, d, h) in G.BUILDINGS:
        S.rect(x - w / 2, y - d / 2, x + w / 2, y + d / 2, "外形線")
        S.rect(x - w / 2 + 900, y - d / 2 + 900, x + w / 2 - 900, y + d / 2 - 900, "細線")
        S.text(name, (x, y), 2.6, "MC")

    # --- 名前(引出線) ---
    L = S.label
    L("ロケット(機体中心 X=0, Y=0)", (-1900, 1900), -44, 44)
    L("移動発射台(ML)", (-M["w"] / 2 + 1500, M["d"] / 2 - 1500), -22, 10)
    L("固体ロケットブースター", (-G.SRB_X - 900, -900), -32, -12)
    L("排煙溝(覆蓋部)", (-hw, -16000), -24, -6)
    L("排煙溝", (-hw, -56000), -22, -6)
    L("排煙溝出口", (hw, T["y_outlet"]), 20, -4)
    L("偏向板", (-hw, dy1 - 1000), -20, 8)
    L("アンビリカルタワー", (tx1, ty1), 14, 18)
    L("アクセスアーム", ((x0 + x1) / 2, y0), 22, -18)
    L("アーム離脱後の位置", swung_mid, 2, 19)
    xn, yn = G.LIGHTNING_TOWERS[3]
    L("避雷塔(4基)", (xn, yn + G.LIGHTNING["base_w"] / 2), 0, 30)
    L("架空地線", (0, G.LIGHTNING_TOWERS[0][1]), -24, -7)
    L("照明塔(4基)", (G.LIGHT_TOWERS[1][0] + 800, G.LIGHT_TOWERS[1][1]), 6, 10)
    L("水タンク(音響抑制用)", (G.WATER_TANKS[1][0] + 2500, G.WATER_TANKS[1][1] + 7000), 4, 26)
    for name, x, y in G.SPHERES:
        L(name, (x, y + G.SPHERE["d"] / 2), 0, 9, side="R" if x > 0 else "L")
    L("ML 移動レール", (G.RAILS_X[0], 60000), -16, 4)
    L("射点の床", (-30000, -24000), -6, -8)
    L("周回道路", (-54000 + G.ROAD_W / 2, -30000), 8, -4)
    L("海岸線", (-70000, -86500), -8, -4)
    L("法面", (60000, -81000), 6, 6)

    # --- 寸法 ---
    S.dim((-M["w"] / 2, -M["d"] / 2), (M["w"] / 2, -M["d"] / 2), -7)
    S.dim((0, 0), (Tw["cx"], 0), -36)
    S.dim((-M["w"] / 2, -M["d"] / 2), (-M["w"] / 2, M["d"] / 2), -7, vertical=True)
    S.dim((tx0, ty1), (tx1, ty1), 6)
    lt = G.LIGHTNING_TOWERS
    S.dim(lt[0], lt[1], -7)
    S.dim(lt[1], lt[3], 16, vertical=True)
    S.dim((0, 0), (0, T["y_outlet"]), -46, vertical=True)

    # --- 右欄: 図の名前・縮尺・方位・凡例・座標表 ---
    x0r, x1r = TB[0], TB[2]
    view_title(S, x0r + 2, 398, "射点配置図", "S=1:500")
    scale_bar(S, x0r + 6, 382, 10, 5)
    north_arrow(S, x1r - 14, 382)
    legend = [
        (legend_row(S, "外形線"), "外形線(設備の外形)"),
        (legend_row(S, "隠れ線"), "隠れ線(覆蓋下の排煙溝・ML 台座)"),
        (legend_row(S, "中心線"), "中心線・アームの軌跡"),
        (legend_row(S, "架空地線"), "架空地線(避雷塔の頂部を結ぶ)"),
        (legend_row(S, "", "hatch"), "建屋"),
        (legend_row(S, "", "slope"), "法面(段丘の斜面)"),
    ]
    y = table(S, x0r, x1r, 366, "凡例", legend, col=20, rh=6.0)
    rows = [("機体中心", "X=0, Y=0")]
    rows.append(("アンビリカルタワー", f"X={fmt(Tw['cx'])}, Y={fmt(Tw['cy'])}"))
    for k, (x, yy) in enumerate(G.LIGHTNING_TOWERS, 1):
        rows.append((f"避雷塔 {k}", f"X={fmt(x)}, Y={fmt(yy)}".replace("-", "−")))
    for k, (x, yy) in enumerate(G.LIGHT_TOWERS, 1):
        rows.append((f"照明塔 {k}", f"X={fmt(x)}, Y={fmt(yy)}".replace("-", "−")))
    for k, (x, yy) in enumerate(G.WATER_TANKS, 1):
        rows.append((f"水タンク {k}", f"X={fmt(x)}, Y={fmt(yy)}".replace("-", "−")))
    for name, x, yy in G.SPHERES:
        rows.append((name, f"X={fmt(x)}, Y={fmt(yy)}".replace("-", "−")))
    rows.append(("排煙溝出口", f"X=0, Y={fmt(T['y_outlet'])}".replace("-", "−")))
    table(S, x0r, x1r, y - 6, "主要設備の位置(中心座標)", rows, col=46, rh=4.6, h=2.4)
    return S


# ===========================================================================
# 立面図の陰線処理(物ごとに手前から描き、手前の物の影に入った線を消す)
# ===========================================================================
class Elevation:
    def __init__(self):
        self.items = []   # (depth, lines, silhouette, layer の辞書)

    def add(self, depth, lines, sil=None, layer="外形線"):
        self.items.append((depth, [(l, layer) if not isinstance(l, tuple) else l for l in lines], sil))

    def draw(self, S):
        occ = None
        for depth, lines, sil in sorted(self.items, key=lambda it: it[0]):
            for pts, layer in lines:
                g = LineString(pts)
                if occ is not None:
                    g = g.difference(occ)
                S.geom(g, layer)
            if sil is not None:
                sil = sil.buffer(-40)          # 輪郭線そのものは消さない
                occ = sil if occ is None else unary_union([occ, sil])


def profile_outline(prof, cx=0.0, z0=0.0, sx=1.0):
    """(r, h) の外形を左右対称の閉じた輪郭(x, z)に。"""
    right = [(cx + r * sx, z0 + h) for r, h in prof]
    left = [(cx - r * sx, z0 + h) for r, h in reversed(prof)]
    return right + left


def lattice_lines(x0, x1, z0, z1, levels, taper=None):
    """格子塔の正面(柱2本 + 各段の水平材 + X ブレース)。taper(z)->幅 なら先細り。"""
    def xs(z):
        if taper is None:
            return x0, x1
        c = (x0 + x1) / 2
        w = taper(z - z0) / 2
        return c - w, c + w
    out = []
    zz = [z0 + l for l in levels]
    out.append([(xs(z)[0], z) for z in (zz[0], zz[-1])])
    out.append([(xs(z)[1], z) for z in (zz[0], zz[-1])])
    for a, b in zip(zz[:-1], zz[1:]):
        la, ra = xs(a)
        lb, rb = xs(b)
        out.append([(la, b), (rb, b)])
        out.append([(la, a), (rb, b)])
        out.append([(ra, a), (lb, b)])
    return out


def rocket_front(cx=0.0, z0=None, view="front"):
    """機体の立面(正面: SRB は左右、側面: SRB は手前)。Elevation に入れる (depth, lines, sil) の列。"""
    z0 = G.Z_BASE if z0 is None else z0
    items = []
    core = profile_outline(G.core_profile(), cx, z0)
    core_lines = [core + [core[0]]]
    for st in [G.ST["s1_top"], G.ST["interstage_top"], G.ST["s2_top"]] + G.JOINTS:
        core_lines.append([(cx - G.CORE_R, z0 + st), (cx + G.CORE_R, z0 + st)])
    core_lines.append([(cx - G.FAIRING_R, z0 + G.ST["fairing_cyl_top"]),
                       (cx + G.FAIRING_R, z0 + G.ST["fairing_cyl_top"])])
    if view == "side":   # フェアリングの分割線
        core_lines.append(([(cx, z0 + G.ST["adapter_top"]), (cx, z0 + G.ST["tip"] - 200)], "細線"))
    items.append((-G.CORE_R, core_lines, Polygon(core)))
    # 1段エンジンのノズル
    N = G.CORE_NOZZLE
    prof = G.nozzle_profile(N["throat_r"], N["exit_r"], N["length"])
    engines = [0.0] if view == "front" else [y for _, y in G.CORE_ENGINES]
    for ex in engines:
        pts = [(cx + ex + r, z0 + N["top"] - d) for r, d in prof]
        pts = pts + [(cx + ex - r, z0 + N["top"] - d) for r, d in reversed(prof)]
        items.append((-G.CORE_R + 100 + abs(ex), [pts], Polygon(pts)))
    # SRB
    srbs = [(-G.SRB_X, -G.SRB_R), (G.SRB_X, -G.SRB_R)] if view == "front" else [(0.0, -G.SRB_X - G.SRB_R)]
    for sx_, depth in srbs:
        o = profile_outline(G.srb_profile(), cx + sx_, z0)
        ls = [o + [o[0]], [(cx + sx_ - G.SRB_R, z0 + G.SRB_ST["skirt_top"]),
                           (cx + sx_ + G.SRB_R, z0 + G.SRB_ST["skirt_top"])],
              [(cx + sx_ - G.SRB_R, z0 + G.SRB_ST["cyl_top"]), (cx + sx_ + G.SRB_R, z0 + G.SRB_ST["cyl_top"])]]
        for seg in (6500, 11500, 16500):
            ls.append(([(cx + sx_ - G.SRB_R, z0 + seg), (cx + sx_ + G.SRB_R, z0 + seg)], "細線"))
        if view == "front":
            for za in G.SRB_ATTACH:
                s = 1 if sx_ > 0 else -1
                ls.append(([(cx + s * G.CORE_R, z0 + za), (cx + s * (G.SRB_X - G.SRB_R), z0 + za - 600)], "細線"))
        SN = G.SRB_NOZZLE
        cant = math.radians(SN["cant_deg"]) * (1 if sx_ > 0 else -1 if view == "front" else 0)
        noz = []
        for (r, d) in G.nozzle_profile(500, SN["exit_r"], SN["length"], 8):
            noz.append((r, -d))
        npts = [(r, h) for r, h in noz] + [(-r, h) for r, h in reversed(noz)]
        npts = [rot(p, cant) for p in npts]
        npts = [(cx + sx_ + x, z0 + G.SRB_ST["bottom"] + y) for x, y in npts]
        items.append((depth + 50, [npts], Polygon(npts)))
        items.append((depth, ls, Polygon(o)))
    return items


# ===========================================================================
# 2. 射点立面図(南から) S=1:400
# ===========================================================================
def elevation_sheet():
    notes = [
        FICTION,
        "南(海側)から見た立面図。高さは射点地盤面 GL±0 を基準とする。",
        "後列の避雷塔 2基は前列と重なるため省略。架空地線は一点鎖線。",
        "機体・設備の寸法は形状モジュール rocket/geometry.py の値による。",
    ]
    S = Sheet("2_射点立面図", "射点立面図(南から)", "LP-002", 400, (300, 98), notes)
    K = S.K
    # 特記事項は左下に置くので、表題欄の上の箱は使わない
    S.notes, notes_here = [], notes
    S.frame()
    S.set_window(64, 64, 582, 400, holes=[(TB[0] - 2, 0, 600, TB[3] + 2)])
    E = Elevation()
    xl, xr = -95000, 95000

    # 地盤・段丘・海
    E.add(-90000, [[(xl, 0), (xr, 0)], [(xl, G.SEA_LEVEL), (xr, G.SEA_LEVEL)]],
          Polygon([(xl, -40000), (xr, -40000), (xr, 0), (G.TRENCH["w"] / 2 + 1500, 0),
                   (G.TRENCH["w"] / 2 + 1500, G.TRENCH["floor_outlet"]),
                   (-G.TRENCH["w"] / 2 - 1500, G.TRENCH["floor_outlet"]),
                   (-G.TRENCH["w"] / 2 - 1500, 0), (xl, 0)]))
    ticks = []
    for i, x in enumerate(range(xl, xr, 2500)):
        if abs(x) < G.TRENCH["w"] / 2 + 1500:
            continue
        ticks.append(([(x, 0), (x, -8000 if i % 2 == 0 else -4000)], "ハッチ"))
    E.add(-91000, ticks)
    waves = []
    for j, zz in enumerate((-10500, -13500)):
        for xx in range(xl + 3000 + j * 4000, 40000, 8000):
            waves.append(([(xx + t * 400, zz + 300 * math.sin(t / 10 * 2 * math.pi)) for t in range(11)], "海"))
    E.add(-95000, waves)
    tw = G.TRENCH["w"] / 2
    E.add(-70000, [[(-tw - 1500, 0), (-tw - 1500, G.TRENCH["floor_outlet"]),
                    (tw + 1500, G.TRENCH["floor_outlet"]), (tw + 1500, 0)],
                   ([(-tw, 0), (-tw, G.TRENCH["floor_outlet"])], "細線"),
                   ([(tw, 0), (tw, G.TRENCH["floor_outlet"])], "細線")])

    # 推進薬タンク(球)
    for name, x, y in G.SPHERES:
        r = G.SPHERE["d"] / 2
        zc = G.SPHERE["leg_h"] + r
        c = circle_pts((x, zc), r, 64)
        legs = []
        for k in (-0.8, -0.35, 0.35, 0.8):
            legs.append([(x + k * r, 0), (x + k * r, zc - r * math.sqrt(1 - k * k))])
        E.add(y - r, [c] + legs, Polygon(c))
        E.add(y - r + 1, [([(x - r - 1500, zc), (x + r + 1500, zc)], "中心線")])

    # 避雷塔(前列)・架空地線
    L = G.LIGHTNING
    for (x, y) in G.LIGHTNING_TOWERS[:2]:
        lv = G.lattice_levels(L["h"], 7000)
        lines = lattice_lines(x - L["base_w"] / 2, x + L["base_w"] / 2, 0, L["h"], lv, taper=G.lightning_width)
        lines.append([(x, L["h"]), (x, L["h"] + L["mast_h"])])
        E.add(y - L["base_w"] / 2, lines)
    wire = [(p[0], p[2]) for p in G.catenary((-44000, 0), (44000, 0), L["h"] + L["mast_h"], G.CATENARY_SAG)]
    E.add(-36000, [(wire, "架空地線")])

    # 照明塔
    LT = G.LIGHT
    for i, (x, y) in enumerate(G.LIGHT_TOWERS):
        pole = [(x - LT["pole_d"] / 2, 0), (x - LT["pole_d"] / 3, LT["h"] - LT["head_h"]),
                (x + LT["pole_d"] / 3, LT["h"] - LT["head_h"]), (x + LT["pole_d"] / 2, 0)]
        hw_ = LT["head_w"] / 2
        az, el = G.light_aim(i)
        k = abs(math.cos(az))   # 正面から見た灯具の幅(向きで縮む)
        head = [(x - hw_ * max(k, 0.35), LT["h"] - LT["head_h"]), (x + hw_ * max(k, 0.35), LT["h"] - LT["head_h"]),
                (x + hw_ * max(k, 0.35), LT["h"]), (x - hw_ * max(k, 0.35), LT["h"])]
        lamps = []
        for j in range(1, 4):
            zz = LT["h"] - LT["head_h"] * j / 4
            lamps.append(([(head[0][0], zz), (head[1][0], zz)], "細線"))
        E.add(y - 1000, [head + [head[0]]] + lamps, Polygon(head))
        E.add(y - 800, [pole + [pole[0]]], Polygon(pole))

    # 建屋
    for (name, x, y, w, d, h) in G.BUILDINGS:
        b = [(x - w / 2, 0), (x + w / 2, 0), (x + w / 2, h), (x - w / 2, h)]
        win = [([(x - w / 2 + 1500, h * 0.62), (x + w / 2 - 1500, h * 0.62)], "細線")]
        E.add(y - d / 2, [b + [b[0]]] + win, Polygon(b))

    # 水タンク
    for (x, y) in G.WATER_TANKS:
        W = G.WATER_TANK
        r, h = W["d"] / 2, W["h"]
        body = [(x - r, 0), (x + r, 0), (x + r, h)] + \
               [(x + r * math.cos(a / 12 * math.pi), h + 1800 * math.sin(a / 12 * math.pi)) for a in range(1, 12)] + \
               [(x - r, h)]
        rings = [([(x - r, z), (x + r, z)], "細線") for z in (5000, 10000, 15000)]
        E.add(y - r, [body + [body[0]]] + rings, Polygon(body))

    # 移動発射台
    M = G.ML
    ml = [(-M["w"] / 2, M["z_bottom"]), (M["w"] / 2, M["z_bottom"]), (M["w"] / 2, M["z_deck"]),
          (-M["w"] / 2, M["z_deck"])]
    ml_lines = [ml + [ml[0]], ([(-M["w"] / 2, M["z_deck"] - 900), (M["w"] / 2, M["z_deck"] - 900)], "細線")]
    for px in sorted({p[0] for p in M["pedestals"]}):
        a = M["pedestal"] / 2
        ml_lines.append([(px - a, 0), (px - a, M["z_bottom"]), (px + a, M["z_bottom"]), (px + a, 0)])
    for hx in (-G.SRB_X, G.SRB_X):
        for dx in (-1200, 1200):
            ml_lines.append([(hx + dx, M["z_deck"]), (hx + dx, G.Z_BASE - 300)])
    ped = [Polygon([(px - M["pedestal"] / 2, 0), (px + M["pedestal"] / 2, 0),
                    (px + M["pedestal"] / 2, M["z_bottom"]), (px - M["pedestal"] / 2, M["z_bottom"])])
           for px in {p[0] for p in M["pedestals"]}]
    E.add(-M["d"] / 2, ml_lines, unary_union([Polygon(ml)] + ped))

    # ロケット
    for it in rocket_front():
        E.add(*it)

    # アンビリカルタワー・アーム
    Tw = G.TOWER
    tx0, tx1 = Tw["cx"] - Tw["w"] / 2, Tw["cx"] + Tw["w"] / 2
    tl = lattice_lines(tx0, tx1, 0, Tw["h"], G.lattice_levels(Tw["h"], Tw["panel"]))
    tl.append([(tx0 + Tw["column"], 0), (tx0 + Tw["column"], Tw["h"])])
    tl.append([(tx1 - Tw["column"], 0), (tx1 - Tw["column"], Tw["h"])])
    cr = Tw["h"] + 2000
    tl += [[(tx1, Tw["h"]), (tx1, cr), (tx1 - Tw["w"] - Tw["crane_len"] + 6000, cr),
            (tx1 - Tw["w"] - Tw["crane_len"] + 6000, cr - 1200), (tx0, cr - 1200)],
           ([(tx0 - Tw["crane_len"] + 6000 + 1500, cr - 1200), (tx0 - Tw["crane_len"] + 6000 + 1500, cr - 9000)], "細線"),
           [(Tw["cx"], cr), (Tw["cx"], cr + Tw["beacon_h"])]]
    E.add(-Tw["w"] / 2, tl)
    for name, z, x_tip, w in G.ARMS:
        a = [(x_tip, z - G.ARM_DEPTH), (tx0, z - G.ARM_DEPTH), (tx0, z), (x_tip, z)]
        lines = [a + [a[0]]]
        n = 6
        for k in range(n):
            xa = x_tip + (tx0 - x_tip) * k / n
            xb = x_tip + (tx0 - x_tip) * (k + 1) / n
            lines.append(([(xa, z - G.ARM_DEPTH), (xb, z)] if k % 2 == 0 else [(xa, z), (xb, z - G.ARM_DEPTH)], "細線"))
        if name.startswith("フェアリング"):
            wr = [(x_tip, z), (x_tip + 3200, z), (x_tip + 3200, z + 3000), (x_tip, z + 3000)]
            lines.append(wr + [wr[0]])
        E.add(-w / 2, lines, Polygon(a))

    E.draw(S)
    # 中心線
    S.centerline((0, -3000), (0, G.Z_BASE + G.ROCKET_LENGTH + 4000))

    # 高さの記号(左)
    lx = -97000 - 6 * K
    levels = [(0, "GL±0"), (G.SEA_LEVEL, f"海面 GL−{fmt(-G.SEA_LEVEL)}"),
              (G.ML["z_deck"], f"ML デッキ +{fmt(G.ML['z_deck'])}"),
              (G.LIGHT["h"], f"照明塔 +{fmt(G.LIGHT['h'])}"),
              (G.Z_BASE + G.ROCKET_LENGTH, f"機体先端 +{fmt(G.Z_BASE + G.ROCKET_LENGTH)}"),
              (G.TOWER["h"], f"タワー頂部 +{fmt(G.TOWER['h'])}"),
              (G.LIGHTNING["h"] + G.LIGHTNING["mast_h"],
               f"避雷針 +{fmt(G.LIGHTNING['h'] + G.LIGHTNING['mast_h'])}")]
    for z, s in levels:
        S.level(xl - 2000, z, s, side="L", h=2.4)
        S.line([(xl - 2000 - 1.0 * K, z), (xl + 1000, z)], "寸法", clip=False)

    # 寸法(右側に高さ、下に幅)
    Tw = G.TOWER
    S.dim((tx1, 0), (tx1, Tw["h"]), 12, vertical=True)
    S.dim((tx1, 0), (tx1, G.Z_BASE), 4, vertical=True)
    S.dim((tx1, G.Z_BASE), (tx1, G.Z_BASE + G.ROCKET_LENGTH), 4, vertical=True)
    x1 = G.LIGHTNING_TOWERS[1][0]
    S.dim((x1, 0), (x1, G.LIGHTNING["h"]), 16, vertical=True)
    S.dim((-44000, G.LIGHTNING["h"] + G.LIGHTNING["mast_h"]), (44000, G.LIGHTNING["h"] + G.LIGHTNING["mast_h"]), 8)
    S.dim((0, 33000), (G.TOWER["cx"], 33000), 0)

    # 名前
    Lb = S.label
    Lb("ロケット", (-G.FAIRING_R + 300, G.Z_BASE + 60000), -22, 8)
    Lb("固体ロケットブースター", (-G.SRB_X - G.SRB_R, G.Z_BASE + 14000), -14, 18)
    Lb("移動発射台(ML)", (-G.ML["w"] / 2 + 2000, 6000), -18, 20)
    Lb("アンビリカルタワー", (tx1, 70000), 46, 4)
    am = (tx0 + G.ARMS[1][2]) / 2
    zm = (G.ARMS[0][1] + G.ARMS[1][1] - G.ARM_DEPTH) / 2
    S.text("アクセスアーム(3段)", (am, zm), 2.4, "MC")
    S.line([(am, zm - 2.0 * K), (am, G.ARMS[0][1])], "細線", clip=False)
    S.line([(am, zm + 2.0 * K), (am, G.ARMS[1][1] - G.ARM_DEPTH)], "細線", clip=False)
    Lb("ホワイトルーム", (G.ARMS[2][2] + 1600, G.ARMS[2][1] + 3000), -2, 10, side="L")
    Lb("旋回クレーン", (tx0 - 3000, Tw["h"] + 2000), -8, 7, side="L")
    Lb("航空障害灯", (Tw["cx"], Tw["h"] + 2000 + Tw["beacon_h"]), 10, 5)
    Lb("避雷塔", (-44000 - 400, 70000), -10, 10)
    Lb("架空地線", (-22000, G.LIGHTNING["h"] + G.LIGHTNING["mast_h"] - 6500), 2, 9)
    Lb("照明塔", (G.LIGHT_TOWERS[0][0], 25000), -12, 10)
    Lb("水タンク", (G.WATER_TANKS[0][0] + 3000, 12000), 0, 30, side="R")
    Lb("排煙溝出口", (-tw - 1500, -3000), -10, -9)
    Lb("液体酸素タンク", (62000 - 3000, G.SPHERE["leg_h"] + G.SPHERE["d"] - 300), -0.5, 30, side="L")
    Lb("射点設備棟", (G.BUILDINGS[0][1] + 6000, G.BUILDINGS[0][5]), 2, 22)

    # 図の名前と特記事項(左下)
    view_title(S, 30, 398, "射点立面図(南から)", "S=1:400")
    nx0, ny0, nx1 = 24, 13, 296
    lines = []
    for i, n in enumerate(notes_here, 1):
        lines += wrap(f"{i}. {n}", 2.6, nx1 - nx0 - 8, indent="   ")
    h = 9 + len(lines) * 4.4 + 2
    P = S.P
    S.line([P(nx0, ny0), P(nx1, ny0), P(nx1, ny0 + h), P(nx0, ny0 + h)], "図枠細線", closed=True, clip=False)
    S.ptext("特記事項", nx0 + 4, ny0 + h - 5, 3.2, "ML")
    S.line([P(nx0, ny0 + h - 9), P(nx1, ny0 + h - 9)], "図枠細線", clip=False)
    for k, s in enumerate(lines):
        S.ptext(s, nx0 + 4, ny0 + h - 13.5 - k * 4.4, 2.6, "ML")
    return S


# ===========================================================================
# 3. ロケット外形図・断面図 S=1:250
# ===========================================================================
def rocket_sheet():
    notes = [
        FICTION,
        "寸法の単位は mm。機体の高さ方向の位置は1段後部スカート下端(機体下端)を 0 とする。",
        "外板・タンクの板厚は図示のため誇張している。",
        "機体の寸法は形状モジュール rocket/geometry.py の値による。",
    ]
    S = Sheet("3_ロケット外形図", "ロケット外形図・断面図", "RK-001", 250, (0, 0), notes)
    K = S.K
    S.frame()
    base_y = 92                             # 機体下端の紙の上の高さ
    z0 = base_y * K
    views = {"front": 84 * K, "side": 166 * K, "section": 246 * K}

    def E_draw(items):
        E = Elevation()
        for it in items:
            E.add(*it)
        E.draw(S)

    # --- 正面図 ---
    cx = views["front"]
    E_draw(rocket_front(cx, z0, "front"))
    S.hatch([[(cx - G.CORE_R, z0 + G.ST["s1_top"]), (cx + G.CORE_R, z0 + G.ST["s1_top"]),
              (cx + G.CORE_R, z0 + G.ST["interstage_top"]), (cx - G.CORE_R, z0 + G.ST["interstage_top"])]],
            "ANSI31", 0.5)
    S.centerline((cx, z0 - 5000), (cx, z0 + G.ST["tip"] + 3000))
    for sx_ in (-G.SRB_X, G.SRB_X):
        S.centerline((cx + sx_, z0 - 4000), (cx + sx_, z0 + G.SRB_ST["tip"] + 2000))
    # 縦の寸法(段ごと)
    xs = cx - G.SRB_X - G.SRB_SKIRT_R
    stations = [0, G.ST["s1_top"], G.ST["interstage_top"], G.ST["s2_top"], G.ST["fairing_cyl_top"], G.ST["tip"]]
    for a, b in zip(stations[:-1], stations[1:]):
        S.dim((cx - G.CORE_R, z0 + a), (cx - G.CORE_R, z0 + b), (xs - (cx - G.CORE_R)) / K - 6, vertical=True)
    S.dim((cx - G.CORE_R, z0), (cx - G.CORE_R, z0 + G.ST["tip"]), (xs - (cx - G.CORE_R)) / K - 16, vertical=True)
    S.dim((cx + G.SRB_X + G.SRB_R, z0 + G.SRB_ST["bottom"]), (cx + G.SRB_X + G.SRB_R, z0 + G.SRB_ST["tip"]),
          6, vertical=True)
    S.dim((cx - G.CORE_R, z0 + 30000), (cx + G.CORE_R, z0 + 30000), 0)
    S.dim((cx - G.FAIRING_R, z0 + 56000), (cx + G.FAIRING_R, z0 + 56000), 0)
    S.dim((cx - G.SRB_X - G.SRB_R, z0 - 4000), (cx + G.SRB_X + G.SRB_R, z0 - 4000), -2)
    S.dim((cx - G.SRB_X, z0 + 9000), (cx, z0 + 9000), 0)
    # 切断線 A, B, C
    cuts = [("A", 15000), ("B", 45000), ("C", 56500)]
    for ch, st in cuts:
        y = z0 + st
        w = G.SRB_X + G.SRB_R + 1300 if ch == "A" else G.FAIRING_R + 2000
        S.line([(cx - w, y), (cx - w + 1500, y)], "外形線", clip=False)
        S.line([(cx + w, y), (cx + w - 1500, y)], "外形線", clip=False)
        S.line([(cx - w + 1500, y), (cx + w - 1500, y)], "中心線", clip=False)
        for s in (-1, 1):
            x = cx + s * w
            S.line([(x, y + 3200), (x, y + 1400)], "外形線", clip=False)
            S.solid([(x, y + 150), (x - 0.7 * K, y + 1500), (x + 0.7 * K, y + 1500)], "外形線")
            S.text(ch, (x + s * 1.8 * K, y + 1.6 * K), 3.0, "MC")
    # 名前
    Lb = S.label
    Lb("フェアリング", (cx + G.FAIRING_R - 600, z0 + 62000), 12, 4)
    Lb("2段", (cx + G.CORE_R, z0 + 48500), 12, 0)
    Lb("段間部", (cx + G.CORE_R, z0 + 39000), 12, 0)
    Lb("1段", (cx + G.CORE_R, z0 + 30000), 12, 3)
    Lb("SRB", (cx + G.SRB_X + G.SRB_R - 300, z0 + 24000), 16, 10)
    Lb("SRB ノズル", (cx + G.SRB_X + 900, z0 - 2200), 12, 3)
    S.text("正面図", (cx, z0 - 26 * K), 4.0, "MC")
    S.text("(南から)", (cx, z0 - 31 * K), 2.6, "MC")

    # --- 側面図 ---
    cx = views["side"]
    E_draw(rocket_front(cx, z0, "side"))
    S.centerline((cx, z0 - 5000), (cx, z0 + G.ST["tip"] + 3000))
    S.text("側面図", (cx, z0 - 26 * K), 4.0, "MC")
    S.text("(東から)", (cx, z0 - 31 * K), 2.6, "MC")
    S.dim((cx - G.CORE_ENGINES[1][1], z0 - 4000), (cx + G.CORE_ENGINES[1][1], z0 - 4000), -5)

    # --- 縦断面図 ---
    cx = views["section"]
    shell = profile_outline(G.core_profile(), cx, z0)
    S.line(shell, "外形線", closed=True)
    inner = profile_outline([(max(r - 120, 0), h) for r, h in G.core_profile()][1:-1], cx, z0)
    S.line(inner, "細線", closed=True)
    for st in [G.ST["s1_top"], G.ST["interstage_top"], G.ST["s2_top"]]:
        S.line([(cx - G.CORE_R, z0 + st), (cx + G.CORE_R, z0 + st)], "細線")
    tank_label = []
    for name, b, t, r, dh in G.TANKS:
        n = 16
        bot = [(cx + r * math.cos(math.pi * i / n), z0 + b + dh - dh * math.sin(math.pi * i / n)) for i in range(n + 1)]
        top = [(cx - r * math.cos(math.pi * i / n), z0 + t - dh + dh * math.sin(math.pi * i / n)) for i in range(n + 1)]
        poly = bot[::-1][::-1]
        outline = [(cx + r, z0 + b + dh)] + [(cx + r, z0 + t - dh)] + \
                  [(cx + r * math.cos(math.pi * i / n), z0 + t - dh + dh * math.sin(math.pi * i / n)) for i in range(n + 1)] + \
                  [(cx - r, z0 + b + dh)] + \
                  [(cx - r * math.cos(math.pi * i / n), z0 + b + dh - dh * math.sin(math.pi * i / n)) for i in range(n + 1)]
        S.line(outline, "外形線", closed=True)
        tank_label.append((name, (cx + r, z0 + (b + t) / 2)))
        if "酸素" in name:
            S.hatch([outline], "DOTS", 2.0)
    # 2段エンジン
    N2 = G.S2_NOZZLE
    top2 = z0 + G.ST["interstage_top"] + 600
    prof = G.nozzle_profile(N2["throat_r"], N2["exit_r"], N2["length"])
    noz = [(cx + r, top2 - d) for r, d in prof] + [(cx - r, top2 - d) for r, d in reversed(prof)]
    S.line(noz, "外形線", closed=True)
    S.rect(cx - 600, top2, cx + 600, top2 + 900, "細線")
    # 1段エンジン(断面の奥に見える)
    N = G.CORE_NOZZLE
    prof = G.nozzle_profile(N["throat_r"], N["exit_r"], N["length"])
    noz = [(cx + r, z0 + N["top"] - d) for r, d in prof] + [(cx - r, z0 + N["top"] - d) for r, d in reversed(prof)]
    S.line(noz, "外形線", closed=True)
    S.rect(cx - 800, z0 + N["top"], cx + 800, z0 + N["top"] + 1800, "細線")
    S.line([(cx, z0 + N["top"] + 1800), (cx, z0 + G.TANKS[0][1])], "細線")
    # ペイロードと分離部
    PA = G.PAYLOAD_ADAPTER
    S.line([(cx - PA["r_bottom"], z0 + PA["bottom"]), (cx - PA["r_top"], z0 + PA["top"]),
            (cx + PA["r_top"], z0 + PA["top"]), (cx + PA["r_bottom"], z0 + PA["bottom"])], "外形線")
    PL = G.PAYLOAD
    pw = PL["w"] / 2
    S.rect(cx - pw, z0 + PL["bottom"], cx + pw, z0 + PL["top"], "外形線")
    S.line([(cx - pw, z0 + PL["top"] - 1600), (cx - pw - 1, z0 + PL["top"] - 1600)], "細線")
    for k in range(1, 5):
        S.line([(cx - pw + 400, z0 + PL["bottom"] + k * 1800), (cx + pw - 400, z0 + PL["bottom"] + k * 1800)], "細線")
    S.hatch([[(cx - pw, z0 + PL["bottom"]), (cx + pw, z0 + PL["bottom"]),
              (cx + pw, z0 + PL["top"]), (cx - pw, z0 + PL["top"])]], "ANSI37", 1.6)
    S.centerline((cx, z0 - 5000), (cx, z0 + G.ST["tip"] + 3000))
    for name, (x, y) in tank_label:
        Lb(name, (x, y), 9, 5)
    Lb("2段エンジン", (cx + 900, top2 - 1600), 9, -1)
    Lb("1段エンジン(2基)", (cx + 900, z0 + N["top"] - N["length"] + 600), 9, -6)
    Lb("衛星(ペイロード)", (cx + pw, z0 + 59000), 9, 8)
    Lb("衛星分離部", (cx + 1800, z0 + 52000), 9, 1)
    S.text("縦断面図", (cx, z0 - 26 * K), 4.0, "MC")
    S.text("(東西の面で切断)", (cx, z0 - 31 * K), 2.6, "MC")

    # --- 横断面 A-A, B-B, C-C と下面図 ---
    def section(ch, cxy, st, srb):
        x, y = cxy
        S.circle((x, y), G.CORE_R, "外形線")
        r_in = G.CORE_R - 120
        S.circle((x, y), r_in, "細線")
        if ch == "C":
            S.circle((x, y), G.FAIRING_R, "外形線")
            S.circle((x, y), G.FAIRING_R - 140, "細線")
            pw = G.PAYLOAD["w"] / 2
            S.rect(x - pw, y - pw, x + pw, y + pw, "外形線")
            S.hatch([[(x - pw, y - pw), (x + pw, y - pw), (x + pw, y + pw), (x - pw, y + pw)]], "ANSI37", 1.6)
            S.line([(x, y + G.FAIRING_R + 600), (x, y + pw)], "外形線")
            S.line([(x, y - G.FAIRING_R - 600), (x, y - pw)], "外形線")
        if srb:
            for sx_ in (-G.SRB_X, G.SRB_X):
                c = (x + sx_, y)
                S.circle(c, G.SRB_R, "外形線")
                S.circle(c, G.SRB_R - 80, "細線")
                star = []
                for k in range(10):
                    a = math.pi / 2 + k * math.pi / 5
                    rr = 620 if k % 2 == 0 else 300
                    star.append((c[0] + rr * math.cos(a), c[1] + rr * math.sin(a)))
                S.line(star, "外形線", closed=True)
                S.hatch([circle_pts(c, G.SRB_R - 80, 48), star], "ANSI31", 0.4)
                s = 1 if sx_ > 0 else -1
                S.line([(x + s * G.CORE_R, y + 500), (c[0] - s * G.SRB_R, y + 500)], "細線")
                S.line([(x + s * G.CORE_R, y - 500), (c[0] - s * G.SRB_R, y - 500)], "細線")
                S.centerline((c[0], y - G.SRB_R - 1200), (c[0], y + G.SRB_R + 1200))
        w = (G.SRB_X + G.SRB_R + 1500) if srb else G.FAIRING_R + 1500
        S.centerline((x - w, y), (x + w, y))
        S.centerline((x, y - G.FAIRING_R - 1500), (x, y + G.FAIRING_R + 1500))
        S.text(f"断面 {ch}-{ch}", (x, y - G.FAIRING_R - 3.5 * K), 3.4, "TC")

    sx = 352 * K
    section("C", (sx, 336 * K), 56500, False)
    section("B", (sx, 276 * K), 45000, False)
    section("A", (sx, 212 * K), 15000, True)
    Lb("固体推進薬", (sx + G.SRB_X + 700, 212 * K + 600), 5, 9)
    Lb("液体水素", (sx - 1500, 212 * K - 1200), -10, -11)
    Lb("フェアリング分割線", (sx, 336 * K + G.FAIRING_R + 300), 8, 4)
    S.dim((sx - G.SRB_X - G.SRB_R, 212 * K + 3000), (sx + G.SRB_X + G.SRB_R, 212 * K + 3000), 3)

    # 下面図
    bx, by = sx, 140 * K
    S.circle((bx, by), G.CORE_R, "外形線")
    for (ex, ey) in G.CORE_ENGINES:
        S.circle((bx + ex, by + ey), G.CORE_NOZZLE["exit_r"], "外形線")
        S.circle((bx + ex, by + ey), G.CORE_NOZZLE["throat_r"], "細線")
    for sx_ in (-G.SRB_X, G.SRB_X):
        S.circle((bx + sx_, by), G.SRB_SKIRT_R, "外形線")
        S.circle((bx + sx_, by), G.SRB_NOZZLE["exit_r"], "細線")
    S.centerline((bx - 7500, by), (bx + 7500, by))
    S.centerline((bx, by - 4000), (bx, by + 4000))
    S.dim((bx, by - G.CORE_ENGINES[1][1]), (bx, by + G.CORE_ENGINES[1][1]), -26, vertical=True)
    S.text("下面図", (bx, by - G.FAIRING_R - 3.5 * K), 3.4, "TC")
    S.text("(下から見上げる)", (bx, by - G.FAIRING_R - 8.5 * K), 2.4, "TC")
    Lb("1段ノズル出口", (bx + 300, by - 1250 - 900), 14, -14)

    # --- 主要諸元 ---
    x0, x1 = TB[0], TB[2]
    top = S.notes_top + 8
    rows = G.SPECS
    rh = 6.5
    P = S.P
    h = 9 + rh * len(rows)
    S.line([P(x0, top), P(x1, top), P(x1, top + h), P(x0, top + h)], "図枠細線", closed=True, clip=False)
    S.ptext("主要諸元(架空)", x0 + 4, top + h - 4.5, 3.2, "ML")
    S.line([P(x0, top + h - 9), P(x1, top + h - 9)], "図枠細線", clip=False)
    S.line([P(x0 + 30, top), P(x0 + 30, top + h - 9)], "図枠細線", clip=False)
    for i, (k, v) in enumerate(rows):
        yy = top + h - 9 - rh * (i + 0.5)
        S.ptext(k, x0 + 4, yy, 2.6, "ML")
        S.ptext(v, x0 + 33, yy, 2.6, "ML")
        if i:
            S.line([P(x0, top + h - 9 - rh * i), P(x1, top + h - 9 - rh * i)], "図枠細線", clip=False)
    view_title(S, 30, 398, "ロケット外形図・断面図", "S=1:250")
    return S


# ===========================================================================
# プレビュー
# ===========================================================================
def preview(S, path_png, dpi=150):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from ezdxf.addons.drawing.config import Configuration, BackgroundPolicy, ColorPolicy

    doc = S.doc
    style = doc.styles.get("JP")
    font_saved = style.dxf.font
    style.dxf.font = "ipag.ttf"              # プレビューだけ手元の日本語フォントで描く
    fig = plt.figure(figsize=(594 / 25.4, 420 / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ctx = RenderContext(doc)
    cfg = Configuration(background_policy=BackgroundPolicy.CUSTOM, custom_bg_color=BG,
                        color_policy=ColorPolicy.COLOR, lineweight_scaling=0.8)
    Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=True)
    x0, y0 = S.P(0, 0)
    x1, y1 = S.P(594, 420)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    fig.set_size_inches(594 / 25.4, 420 / 25.4)
    fig.patch.set_facecolor(BG)
    fig.savefig(path_png, dpi=dpi, facecolor=BG)
    plt.close(fig)
    style.dxf.font = font_saved


def check_overlaps(S):
    bad = []
    T = S.texts
    for i in range(len(T)):
        for j in range(i + 1, len(T)):
            a, b = T[i][1], T[j][1]
            if a[0] < b[2] - 0.2 and b[0] < a[2] - 0.2 and a[1] < b[3] - 0.2 and b[1] < a[3] - 0.2:
                bad.append((T[i][0], T[j][0]))
    return bad


def main(only=None):
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in (plan_sheet, elevation_sheet, rocket_sheet):
        if only and fn.__name__ != only:
            continue
        S = fn()
        dxf = S.save()
        png = dxf.with_suffix(".png")
        preview(S, png)
        ov = check_overlaps(S)
        print(dxf.name, "文字の重なり:", ov if ov else "なし")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
