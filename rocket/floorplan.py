"""射点配置図の DXF を、床に光らせるための線分と塗りつぶし(文字・矢印)に分解する。

ezdxf の描画アドオンで DXF を描かせ、その出力(線・パス・塗り)を受け取って
numpy の配列にする。座標はモデル空間の mm のまま返す。
"""
import numpy as np
import ezdxf
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.backend import BackendInterface
from ezdxf.addons.drawing.config import Configuration, LinePolicy


def _hex(c):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


class Capture(BackendInterface):
    def __init__(self):
        self.segs = []     # (x0, y0, x1, y1, r, g, b, lw)
        self.fills = []    # ([(x, y)...] の輪郭の列, (r, g, b))

    def configure(self, config):
        self.config = config

    def set_background(self, color):
        pass

    def _seg(self, a, b, p):
        r, g, bb = _hex(p.color[:7])
        self.segs.append((a.x, a.y, b.x, b.y, r, g, bb, p.lineweight))

    def draw_point(self, pos, properties):
        pass

    def draw_line(self, start, end, properties):
        self._seg(start, end, properties)

    def draw_solid_lines(self, lines, properties):
        for s, e in lines:
            self._seg(s, e, properties)

    def draw_path(self, path, properties):
        for sp in path.sub_paths():
            pts = list(sp.flattening(distance=20))
            for a, b in zip(pts[:-1], pts[1:]):
                self._seg(a, b, properties)

    def draw_filled_polygon(self, points, properties):
        pts = [(v.x, v.y) for v in points.vertices()]
        if len(pts) >= 3:
            self.fills.append(([pts], _hex(properties.color[:7])))

    def draw_filled_paths(self, paths, properties):
        rings = []
        for p in paths:
            for sp in p.sub_paths():      # 1つのパスに複数の輪郭が入っていることがある
                pts = [(v.x, v.y) for v in sp.flattening(distance=8)]
                if len(pts) >= 3:
                    rings.append(pts)
        if rings:
            self.fills.append((rings, _hex(properties.color[:7])))

    def draw_image(self, image_data, properties):
        pass

    def clear(self):
        pass

    def enter_entity(self, entity, properties):
        pass

    def exit_entity(self, entity):
        pass

    def finalize(self):
        pass


def load(path):
    doc = ezdxf.readfile(path)
    doc.styles.get("JP").dxf.font = "ipag.ttf"
    cap = Capture()
    cfg = Configuration(line_policy=LinePolicy.ACCURATE)
    Frontend(RenderContext(doc), cap, config=cfg).draw_layout(doc.modelspace(), finalize=True)
    return np.array(cap.segs, dtype=np.float64), cap.fills


def triangulate(rings):
    """フォントの輪郭(穴あき・重なりあり)を三角形に。
    輪郭で区切られた各領域の巻き数(向き付きで数える)が 0 でなければ塗る(nonzero 規則)。"""
    from shapely.geometry import LinearRing, Polygon
    from shapely.ops import polygonize, unary_union
    from shapely import constrained_delaunay_triangles
    rs = []
    for r in rings:
        if len(r) < 3:
            continue
        lr = LinearRing(r)
        poly = Polygon(r)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.area <= 0:
            continue
        rs.append((lr, poly, 1 if lr.is_ccw else -1))
    if not rs:
        return []
    faces = list(polygonize(unary_union([lr for lr, _, _ in rs])))
    filled = []
    for f in faces:
        pt = f.representative_point()
        w = sum(sgn for _, poly, sgn in rs if poly.contains(pt))
        if w != 0:
            filled.append(f)
    if not filled:
        return []
    geom = unary_union(filled)
    tris = []
    for poly in getattr(geom, "geoms", [geom]):
        if poly.geom_type != "Polygon" or poly.area <= 0:
            continue
        for t in constrained_delaunay_triangles(poly).geoms:
            tris.append(list(t.exterior.coords)[:3])
    return tris
