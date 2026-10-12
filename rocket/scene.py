"""夜の射点の動画シーンを Blender (EEVEE) で組み立てる。

    /opt/bpyenv/bin/python rocket/scene.py --still 4.0 10.5        # テスト静止画(秒で指定)
    /opt/bpyenv/bin/python rocket/scene.py --save out/scene.blend  # .blend を保存

寸法は geometry.py、床に描く図面は 1_射点配置図.dxf (drawings.py の出力) から読む。
本番の連番レンダーは render.py が、このモジュールの build() を呼んで行う。
"""
import argparse
import math
import os
import sys
import time

import bpy
import bmesh
import numpy as np
from mathutils import Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import geometry as G  # noqa: E402
import floorplan  # noqa: E402
import timeline as TLN  # noqa: E402

M = 0.001                    # mm → m
FPS = TLN.FPS
T_END = TLN.T_END            # 本編の長さ [s]
PLAN_DXF = os.path.join(HERE, "out", "drawings", "1_射点配置図.dxf")
FONT_JP = "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf"
FONT_EN = "/usr/share/fonts/opentype/inter/Inter-Light.otf"

CYAN = (0.25, 1.0, 0.92, 1.0)
WHITE_PAINT = (0.80, 0.81, 0.82, 1.0)

_mz, _ma = math.radians(17), math.radians(-32)    # 月の高度・方位(北から東を正)
MOON_DIR = (math.sin(_ma) * math.cos(_mz), math.cos(_ma) * math.cos(_mz), math.sin(_mz))
TI = G.LAUNCH["t_ignition"]
TL = G.LAUNCH["t_liftoff"]
T_CUT = TLN.T_CUT            # 海上のカメラへ切り替える時刻
T_TITLE = TLN.T_TITLE


def F(t):
    """秒 → フレーム番号(1 始まり)。"""
    return int(round(t * FPS)) + 1


def rise_m(t):
    return G.rocket_rise(t) * M


# ===========================================================================
# ノードを組む道具
# ===========================================================================
class NB:
    def __init__(self, tree):
        self.t = tree

    def node(self, typ, inputs=None, **attrs):
        n = self.t.nodes.new(typ)
        for k, v in attrs.items():
            setattr(n, k, v)
        for k, v in (inputs or {}).items():
            self.set(n.inputs[k], v)
        return n

    def set(self, sock, v):
        if isinstance(v, bpy.types.NodeSocket):
            self.t.links.new(v, sock)
        elif v is not None:
            sock.default_value = v

    def math(self, op, a, b=None, c=None, clamp=False):
        n = self.t.nodes.new("ShaderNodeMath")
        n.operation = op
        n.use_clamp = clamp
        self.set(n.inputs[0], a)
        if b is not None:
            self.set(n.inputs[1], b)
        if c is not None:
            self.set(n.inputs[2], c)
        return n.outputs[0]

    def vec(self, op, a, b=None, scale=None):
        n = self.t.nodes.new("ShaderNodeVectorMath")
        n.operation = op
        self.set(n.inputs[0], a)
        if b is not None:
            self.set(n.inputs[1], b)
        if scale is not None:
            self.set(n.inputs[3], scale)
        out = n.outputs[1] if op in ("LENGTH", "DOT_PRODUCT", "DISTANCE") else n.outputs[0]
        return out

    def xyz(self, x, y, z):
        n = self.node("ShaderNodeCombineXYZ")
        for i, v in enumerate((x, y, z)):
            self.set(n.inputs[i], v)
        return n.outputs[0]

    def sep(self, v):
        n = self.node("ShaderNodeSeparateXYZ")
        self.set(n.inputs[0], v)
        return n.outputs

    def mix_shader(self, fac, a, b):
        n = self.node("ShaderNodeMixShader")
        self.set(n.inputs[0], fac)
        self.set(n.inputs[1], a)
        self.set(n.inputs[2], b)
        return n.outputs[0]

    def add_shader(self, a, b):
        n = self.node("ShaderNodeAddShader")
        self.set(n.inputs[0], a)
        self.set(n.inputs[1], b)
        return n.outputs[0]

    def emission(self, color, strength):
        n = self.node("ShaderNodeEmission")
        self.set(n.inputs["Color"], color)
        self.set(n.inputs["Strength"], strength)
        return n.outputs[0]

    def transparent(self):
        return self.node("ShaderNodeBsdfTransparent").outputs[0]

    def mix_rgb(self, fac, a, b):
        n = self.node("ShaderNodeMix", data_type="RGBA")
        self.set(n.inputs[0], fac)
        self.set(n.inputs[6], a)
        self.set(n.inputs[7], b)
        return n.outputs[2]


def new_mat(name, method="DITHERED"):
    m = bpy.data.materials.new(name)
    m.node_tree.nodes.clear()
    m.surface_render_method = method
    return m, NB(m.node_tree)


def output(b, shader):
    out = b.node("ShaderNodeOutputMaterial")
    b.set(out.inputs["Surface"], shader)


# ===========================================================================
# アニメーションの道具
# ===========================================================================
def fcurves(id_data):
    ad = id_data.animation_data
    if ad is None or ad.action is None:
        return []
    act = ad.action
    if hasattr(act, "fcurves") and len(act.fcurves):
        return list(act.fcurves)
    out = []
    for layer in getattr(act, "layers", []):
        for strip in layer.strips:
            for cb in strip.channelbags:
                out += list(cb.fcurves)
    return out


def key(target, path, pairs, index=-1, interp=None, id_data=None):
    """pairs = [(秒, 値), ...] でキーを打つ。"""
    for t, v in pairs:
        if index >= 0:
            getattr(target, path)[index] = v
        else:
            setattr(target, path, v)
        target.keyframe_insert(path, index=index, frame=F(t))
    if interp:
        idd = id_data or target.id_data
        for fc in fcurves(idd):
            if fc.data_path.endswith(path) and (index < 0 or fc.array_index == index):
                for kp in fc.keyframe_points:
                    kp.interpolation = interp


CTRL = None
CTRL_NAMES = ["scan_r", "line_glow", "wire_on", "build_h", "cut_glow", "dissolve", "env",
              "lights", "blink", "flame", "title", "fill"]


def make_ctrl():
    """全マテリアルが読む制御値(キーで動かす)をまとめたノードグループ。"""
    global CTRL
    ng = bpy.data.node_groups.new("CTRL", "ShaderNodeTree")
    out = ng.nodes.new("NodeGroupOutput")
    for i, name in enumerate(CTRL_NAMES):
        ng.interface.new_socket(name, in_out="OUTPUT", socket_type="NodeSocketFloat")
        v = ng.nodes.new("ShaderNodeValue")
        v.name = name
        v.outputs[0].default_value = 0.0
        ng.links.new(v.outputs[0], out.inputs[i])
    CTRL = ng
    return ng


def ctrl_key(name, pairs, interp=None):
    sock = CTRL.nodes[name].outputs[0]
    key(sock, "default_value", pairs, interp=interp, id_data=CTRL)


def ctrl_node(b):
    n = b.node("ShaderNodeGroup")
    n.node_tree = CTRL
    return n.outputs


# ===========================================================================
# マテリアル
# ===========================================================================
def reveal_mask(b, c, pos=None):
    """図面が「マス目ごとに」溶ける進み具合。戻り値 (現れた=1, 境目の光)。"""
    if pos is None:
        pos = b.node("ShaderNodeNewGeometry").outputs["Position"]
    xs, ys, _ = b.sep(pos)
    cell = 7.0
    cx = b.math("FLOOR", b.math("DIVIDE", xs, cell))
    cy = b.math("FLOOR", b.math("DIVIDE", ys, cell))
    wn = b.node("ShaderNodeTexWhiteNoise", noise_dimensions="2D")
    b.set(wn.inputs["Vector"], b.xyz(cx, cy, 0.0))
    h = wn.outputs["Value"]
    r = b.math("DIVIDE", b.vec("LENGTH", b.xyz(b.math("MULTIPLY", cx, cell), b.math("MULTIPLY", cy, cell), 0.0)), 260.0)
    v = b.math("ADD", b.math("MULTIPLY", h, 0.65), b.math("MULTIPLY", b.math("MINIMUM", r, 1.0), 0.35))
    k = b.math("MULTIPLY", c["dissolve"], 1.08)
    d = b.math("SUBTRACT", k, v)
    revealed = b.math("GREATER_THAN", d, 0.0)
    edge = b.math("MULTIPLY", revealed, b.math("LESS_THAN", d, 0.022))
    return revealed, edge


def proc_wire(b, n_mer=16, ring=2.0, width=0.07):
    """回転体用のワイヤー(経線と緯線を座標から描く。三角形の辺より疎で見やすい)。"""
    pos = b.node("ShaderNodeNewGeometry").outputs["Position"]
    loc = b.node("ShaderNodeObjectInfo").outputs["Location"]
    x, y, z = b.sep(b.vec("SUBTRACT", pos, loc))
    a = b.math("DIVIDE", b.math("ARCTAN2", y, x), 2 * math.pi / n_mer)
    da = b.math("ABSOLUTE", b.math("SUBTRACT", b.math("FRACT", a), 0.5))
    dz = b.math("ABSOLUTE", b.math("SUBTRACT", b.math("FRACT", b.math("DIVIDE", z, ring)), 0.5))
    l1 = b.math("GREATER_THAN", da, 0.5 - width * 0.6)
    l2 = b.math("GREATER_THAN", dz, 0.5 - width * 0.5)
    return b.math("MAXIMUM", l1, l2)


def mat_build(name, color, rough=0.5, metal=0.0, emis=None, emis_ctrl=None, emis_str=0.0, spec=0.5,
              wire="mesh"):
    """建物・機体のマテリアル: 積み上げの高さより下は実体、上は光のワイヤー。"""
    m, b = new_mat(name)
    c = ctrl_node(b)
    pos = b.node("ShaderNodeNewGeometry").outputs["Position"]
    z = b.sep(pos)[2]
    solid = b.math("LESS_THAN", z, c["build_h"])
    dist = b.math("ABSOLUTE", b.math("SUBTRACT", z, c["build_h"]))
    band = b.math("MULTIPLY", b.math("SUBTRACT", 1.0, b.math("DIVIDE", dist, 0.5), clamp=True), c["cut_glow"])
    if wire == "mesh":
        wire = b.node("ShaderNodeWireframe", use_pixel_size=True, inputs={"Size": 1.3}).outputs[0]
    else:
        wire = proc_wire(b, *wire)
    wv = b.math("MULTIPLY", wire, c["wire_on"])
    above = b.mix_shader(wv, b.transparent(), b.emission(CYAN, 6.0))
    bsdf = b.node("ShaderNodeBsdfPrincipled", inputs={
        "Base Color": color, "Roughness": rough, "Metallic": metal})
    try:
        bsdf.inputs["Specular IOR Level"].default_value = spec
    except KeyError:
        pass
    if emis is not None:
        b.set(bsdf.inputs["Emission Color"], emis)
        s = emis_str if emis_ctrl is None else b.math("MULTIPLY", c[emis_ctrl], emis_str)
        b.set(bsdf.inputs["Emission Strength"], s)
    sh = b.mix_shader(solid, above, bsdf.outputs[0])
    sh = b.add_shader(sh, b.emission(CYAN, b.math("MULTIPLY", band, 40.0)))
    output(b, sh)
    return m


def mat_env(name, color, rough=0.8, bump=0.0, sea=False):
    """地面・海・丘: 図面が溶けたマス目から現れる。"""
    m, b = new_mat(name)
    c = ctrl_node(b)
    revealed, edge = reveal_mask(b, c)
    bsdf = b.node("ShaderNodeBsdfPrincipled", inputs={"Base Color": color, "Roughness": rough})
    if sea:
        tc = b.node("ShaderNodeTexCoord").outputs["Object"]
        tm = b.node("ShaderNodeValue")
        tm.name = "wave_time"
        key(tm.outputs[0], "default_value", [(0, 0.0), (T_END + 4, 3.0)], interp="LINEAR", id_data=m.node_tree)
        n1 = b.node("ShaderNodeTexNoise", noise_dimensions="4D",
                    inputs={"Scale": 0.09, "Detail": 6.0, "Roughness": 0.55})
        b.set(n1.inputs["Vector"], b.vec("MULTIPLY", tc, (1.0, 2.2, 1.0)))
        b.set(n1.inputs["W"], tm.outputs[0])
        bp = b.node("ShaderNodeBump", inputs={"Strength": 0.35, "Distance": 0.3})
        b.set(bp.inputs["Height"], n1.outputs["Fac"])
        b.set(bsdf.inputs["Normal"], bp.outputs[0])
        bsdf.inputs["Specular IOR Level"].default_value = 0.6
    elif bump > 0:
        n1 = b.node("ShaderNodeTexNoise", inputs={"Scale": 0.6, "Detail": 8.0})
        b.set(n1.inputs["Vector"], b.node("ShaderNodeNewGeometry").outputs["Position"])
        bp = b.node("ShaderNodeBump", inputs={"Strength": bump})
        b.set(bp.inputs["Height"], n1.outputs["Fac"])
        b.set(bsdf.inputs["Normal"], bp.outputs[0])
        col = b.mix_rgb(b.math("MULTIPLY", n1.outputs["Fac"], 0.5), color,
                        tuple(min(1, x * 1.6) for x in color[:3]) + (1,))
        b.set(bsdf.inputs["Base Color"], col)
    sh = b.mix_shader(revealed, b.transparent(), bsdf.outputs[0])
    sh = b.add_shader(sh, b.emission(CYAN, b.math("MULTIPLY", edge, 1.2)))
    output(b, sh)
    return m


def mat_lines():
    """床の図面の線: 中心からの走査で現れ、マス目ごとに溶けて消える。"""
    m, b = new_mat("plan_lines")
    c = ctrl_node(b)
    pos = b.node("ShaderNodeNewGeometry").outputs["Position"]
    xs, ys, _ = b.sep(pos)
    r = b.vec("LENGTH", b.xyz(xs, ys, 0.0))
    front = b.math("SUBTRACT", c["scan_r"], r)
    shown = b.math("GREATER_THAN", front, 0.0)
    hot = b.math("MULTIPLY", shown, b.math("SUBTRACT", 1.0, b.math("DIVIDE", front, 6.0), clamp=True))
    revealed, edge = reveal_mask(b, c)
    vis = b.math("MULTIPLY", shown, b.math("SUBTRACT", 1.0, revealed))
    col = b.node("ShaderNodeAttribute", attribute_name="Col").outputs["Color"]
    col = b.mix_rgb(hot, col, (0.85, 1.0, 1.0, 1.0))
    s = b.math("MULTIPLY", c["line_glow"], b.math("ADD", 3.0, b.math("MULTIPLY", hot, 9.0)))
    s = b.math("ADD", s, b.math("MULTIPLY", edge, 6.0))
    sh = b.mix_shader(vis, b.transparent(), b.emission(col, s))
    output(b, sh)
    return m


def mat_void():
    """最初の暗闇の床(走査の輪が光る)。"""
    m, b = new_mat("void_floor")
    c = ctrl_node(b)
    pos = b.node("ShaderNodeNewGeometry").outputs["Position"]
    xs, ys, _ = b.sep(pos)
    r = b.vec("LENGTH", b.xyz(xs, ys, 0.0))
    d = b.math("ABSOLUTE", b.math("SUBTRACT", r, c["scan_r"]))
    ring = b.math("SUBTRACT", 1.0, b.math("DIVIDE", d, 2.5), clamp=True)
    fade = b.math("SUBTRACT", 1.0, b.math("DIVIDE", c["scan_r"], 250.0), clamp=True)
    ring = b.math("MULTIPLY", ring, b.math("ADD", 0.25, fade))
    revealed, edge = reveal_mask(b, c)
    bsdf = b.node("ShaderNodeBsdfPrincipled", inputs={"Base Color": (0.004, 0.006, 0.01, 1), "Roughness": 0.35})
    sh = b.add_shader(bsdf.outputs[0], b.emission(CYAN, b.math("MULTIPLY", ring, 5.0)))
    sh = b.mix_shader(revealed, sh, b.transparent())
    sh = b.add_shader(sh, b.emission(CYAN, b.math("MULTIPLY", edge, 1.5)))
    output(b, sh)
    return m


def mat_emit(name, color, strength, ctrl_name=None, ctrl_scale=None, method="DITHERED"):
    m, b = new_mat(name, method)
    s = strength
    if ctrl_name:
        c = ctrl_node(b)
        v = c[ctrl_name]
        if ctrl_scale:
            v = b.math("MULTIPLY_ADD", v, ctrl_scale[0], ctrl_scale[1])
        s = b.math("MULTIPLY", v, strength)
    output(b, b.emission(color, s))
    return m


def mat_flame(name):
    """噴射炎: 根元が白く、先へ行くほど橙で透ける円錐。"""
    m, b = new_mat(name, "BLENDED")
    m.use_backface_culling = False
    z = b.sep(b.node("ShaderNodeTexCoord").outputs["Object"])[2]
    u = b.math("MULTIPLY", z, -1.0, clamp=True)
    lw = b.node("ShaderNodeLayerWeight", inputs={"Blend": 0.35})
    core = b.math("SUBTRACT", 1.0, lw.outputs["Facing"], clamp=True)
    ramp = b.node("ShaderNodeValToRGB")
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = 0.0, (1.0, 0.92, 0.75, 1)
    els[1].position, els[1].color = 1.0, (0.55, 0.08, 0.01, 1)
    e = els.new(0.18)
    e.color = (1.0, 0.70, 0.30, 1)
    e = els.new(0.5)
    e.color = (1.0, 0.36, 0.07, 1)
    b.set(ramp.inputs[0], u)
    fall = b.math("POWER", b.math("SUBTRACT", 1.0, u, clamp=True), 1.6)
    s = b.math("MULTIPLY", fall, b.math("MULTIPLY_ADD", core, 9.0, 1.5))
    alpha = b.math("MULTIPLY", b.math("POWER", b.math("SUBTRACT", 1.0, u, clamp=True), 1.1),
                   b.math("MULTIPLY_ADD", core, 0.6, 0.4))
    sh = b.mix_shader(alpha, b.transparent(), b.emission(ramp.outputs[0], b.math("MULTIPLY", s, 2.2)))
    output(b, sh)
    return m


def mat_smoke():
    m, b = new_mat("smoke")
    glow = b.node("ShaderNodeAttribute", attribute_name="glow").outputs["Fac"]
    shade = b.node("ShaderNodeAttribute", attribute_name="shade").outputs["Fac"]
    c = ctrl_node(b)
    nz = b.node("ShaderNodeTexNoise", inputs={"Scale": 0.35, "Detail": 4.0})
    b.set(nz.inputs["Vector"], b.node("ShaderNodeNewGeometry").outputs["Position"])
    bp = b.node("ShaderNodeBump", inputs={"Strength": 0.7, "Distance": 1.5})
    b.set(bp.inputs["Height"], nz.outputs["Fac"])
    base = b.mix_rgb(shade, (0.50, 0.50, 0.52, 1), (0.86, 0.86, 0.88, 1))
    bsdf = b.node("ShaderNodeBsdfPrincipled", inputs={"Roughness": 1.0})
    bsdf.inputs["Specular IOR Level"].default_value = 0.1
    b.set(bsdf.inputs["Base Color"], base)
    b.set(bsdf.inputs["Normal"], bp.outputs[0])
    b.set(bsdf.inputs["Emission Color"], (1.0, 0.42, 0.12, 1))
    b.set(bsdf.inputs["Emission Strength"], b.math("MULTIPLY", glow, b.math("MULTIPLY", c["flame"], 9.0)))
    lw = b.node("ShaderNodeLayerWeight", inputs={"Blend": 0.5})
    alpha = b.math("SUBTRACT", 1.0, b.math("POWER", lw.outputs["Facing"], 2.0), clamp=True)
    sh = b.mix_shader(alpha, b.transparent(), bsdf.outputs[0])
    output(b, sh)
    return m


def mat_text(name, color, strength):
    """画面の文字(カウントダウン・タイトル): 'fade' の値で現れる。"""
    m, b = new_mat(name, "BLENDED")
    v = b.node("ShaderNodeValue")
    v.name = "fade"
    v.outputs[0].default_value = 0.0
    sh = b.mix_shader(v.outputs[0], b.transparent(), b.emission(color, strength))
    output(b, sh)
    return m


# ===========================================================================
# メッシュの道具
# ===========================================================================
class MeshBuf:
    def __init__(self):
        self.v, self.f, self.mi = [], [], []

    def add(self, verts, faces, mat=0):
        base = len(self.v)
        self.v += [tuple(p) for p in verts]
        self.f += [[i + base for i in face] for face in faces]
        self.mi += [mat] * len(faces)

    def box(self, x0, y0, z0, x1, y1, z1, mat=0):
        v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        self.add(v, f, mat)

    def strut(self, p0, p1, t, mat=0):
        p0, p1 = Vector(p0), Vector(p1)
        d = (p1 - p0).normalized()
        ref = Vector((0, 0, 1)) if abs(d.z) < 0.9 else Vector((1, 0, 0))
        u = d.cross(ref).normalized() * t / 2
        w = d.cross(u).normalized() * t / 2
        v = [p0 - u - w, p0 + u - w, p0 + u + w, p0 - u + w,
             p1 - u - w, p1 + u - w, p1 + u + w, p1 - u + w]
        f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        self.add(v, f, mat)

    def revolve(self, prof, cx=0.0, cy=0.0, z0=0.0, n=40, mat_fn=None, tilt=None):
        """(r, h) の外形を回転させる。mat_fn(h) → マテリアル番号。"""
        rings = []
        for r, h in prof:
            ring = []
            for k in range(n):
                a = 2 * math.pi * k / n
                p = Vector((r * math.cos(a), r * math.sin(a), h))
                if tilt is not None:
                    p = tilt @ p
                ring.append((cx + p.x, cy + p.y, z0 + p.z))
            rings.append(ring)
        base = len(self.v)
        for ring in rings:
            self.v += ring
        for i in range(len(rings) - 1):
            hm = (prof[i][1] + prof[i + 1][1]) / 2
            mat = mat_fn(hm) if mat_fn else 0
            for k in range(n):
                a = base + i * n + k
                b_ = base + i * n + (k + 1) % n
                self.f.append([a, b_, b_ + n, a + n])
                self.mi.append(mat)

    def cylinder(self, cx, cy, z0, z1, r, n=32, mat=0, cap=True):
        prof = ([(0, z0)] if cap else []) + [(r, z0), (r, z1)] + ([(0, z1)] if cap else [])
        self.revolve(prof, cx, cy, 0.0, n, lambda h: mat)

    def to_object(self, name, mats, parent=None, smooth=False, coll=None):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.v, [], self.f)
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-4)
        bm.to_mesh(me)
        bm.free()
        # remove_doubles で面の数は変わらない(縮退面は残る)ので、番号はそのまま
        me.validate()
        for m in mats:
            me.materials.append(m)
        if self.mi and len(me.polygons) == len(self.mi):
            me.polygons.foreach_set("material_index", self.mi)
        if smooth:
            me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
        ob = bpy.data.objects.new(name, me)
        (coll or bpy.context.scene.collection).objects.link(ob)
        if parent:
            ob.parent = parent
        return ob


def empty(name, loc=(0, 0, 0), parent=None, coll=None):
    ob = bpy.data.objects.new(name, None)
    ob.location = loc
    (coll or bpy.context.scene.collection).objects.link(ob)
    if parent:
        ob.parent = parent
    return ob


def collection(name):
    c = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(c)
    return c


# ===========================================================================
# シーンの部品
# ===========================================================================
def build_floor_plan(coll):
    """1_射点配置図.dxf を床に光の線として敷く。"""
    segs, fills = floorplan.load(PLAN_DXF)
    segs = segs.copy()
    segs[:, :4] *= M
    z = 0.08
    a, b = segs[:, 0:2], segs[:, 2:4]
    d = b - a
    ln = np.linalg.norm(d, axis=1)
    ok = ln > 1e-4
    a, b, d, ln, cols, lw = a[ok], b[ok], d[ok], ln[ok], segs[ok, 4:7], segs[ok, 7]
    nrm = np.stack([-d[:, 1], d[:, 0]], 1) / ln[:, None]
    w = np.maximum(lw * 0.5, 0.16)[:, None] / 2       # 線の太さ [m] (紙の 1mm = 床の 0.5m)
    v = np.concatenate([a - nrm * w, b - nrm * w, b + nrm * w, a + nrm * w], 1).reshape(-1, 2)
    n = len(a)
    verts = np.column_stack([v, np.full(len(v), z)])
    faces = np.arange(4 * n).reshape(n, 4)
    vcols = np.repeat(cols, 4, axis=0)
    # 文字・矢印の塗り
    tv, tc = [], []
    for rings, col in fills:
        for tri in floorplan.triangulate(rings):
            for p in tri:
                tv.append((p[0] * M, p[1] * M, z))
                tc.append(col)
    tv = np.array(tv).reshape(-1, 3)
    tf = np.arange(len(tv)).reshape(-1, 3) + len(verts)
    me = bpy.data.meshes.new("plan_lines")
    allv = np.vstack([verts, tv])
    me.vertices.add(len(allv))
    me.vertices.foreach_set("co", allv.astype(np.float32).ravel())
    nq, nt = len(faces), len(tf)
    me.loops.add(nq * 4 + nt * 3)
    me.loops.foreach_set("vertex_index", np.concatenate([faces.ravel(), tf.ravel()]).astype(np.int32))
    me.polygons.add(nq + nt)
    starts = np.concatenate([np.arange(nq) * 4, nq * 4 + np.arange(nt) * 3]).astype(np.int32)
    sizes = np.concatenate([np.full(nq, 4), np.full(nt, 3)]).astype(np.int32)
    me.polygons.foreach_set("loop_start", starts)
    me.update()
    allc = np.vstack([vcols, np.array(tc).reshape(-1, 3)])
    attr = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
    rgba = np.column_stack([allc, np.ones(len(allc))]).astype(np.float32)
    attr.data.foreach_set("color", rgba.ravel())
    me.materials.append(mat_lines())
    ob = bpy.data.objects.new("plan_lines", me)
    coll.objects.link(ob)
    # 暗闇の床
    me2 = bpy.data.meshes.new("void")
    me2.from_pydata([(-900, -900, 0.04), (900, -900, 0.04), (900, 900, 0.04), (-900, 900, 0.04)], [], [(0, 1, 2, 3)])
    me2.materials.append(mat_void())
    ob2 = bpy.data.objects.new("void_floor", me2)
    coll.objects.link(ob2)
    return ob


def build_rocket(root, coll):
    pw = (16, 2.5, 0.08)
    mats = [mat_build("rk_white", WHITE_PAINT, 0.32, wire=pw),
            mat_build("rk_dark", (0.05, 0.05, 0.055, 1), 0.45, wire=pw),
            mat_build("rk_gray", (0.35, 0.36, 0.37, 1), 0.4, wire=pw),
            mat_build("rk_nozzle", (0.08, 0.07, 0.065, 1), 0.3, 0.9, wire=pw)]
    zb = G.Z_BASE * M
    mb = MeshBuf()

    def core_mat(h):
        st = h / M
        if G.ST["s1_top"] <= st <= G.ST["interstage_top"]:
            return 1
        if st < 1800:
            return 2
        return 0
    prof = [(r * M, h * M) for r, h in G.core_profile()]
    mb.revolve(prof, 0, 0, zb, 64, core_mat)
    sprof = [(r * M, h * M) for r, h in G.srb_profile()]
    for sx, sy in G.SRB_CENTERS:
        mb.revolve(sprof, sx * M, sy * M, zb, 40,
                   lambda h: 2 if h < G.SRB_ST["skirt_top"] * M else 0)
        for za in G.SRB_ATTACH:   # 結合ブレース
            s = 1 if sx > 0 else -1
            mb.strut((s * (G.CORE_R - 100) * M, 0, zb + za * M),
                     (s * (G.SRB_X - G.SRB_R + 100) * M, 0, zb + za * M - 0.6), 0.35, 2)
    rocket = mb.to_object("rocket", mats, root, smooth=True, coll=coll)
    # ノズル
    nb = MeshBuf()
    N = G.CORE_NOZZLE
    nprof = [(r * M, -d * M) for r, d in G.nozzle_profile(N["throat_r"], N["exit_r"], N["length"])]
    for ex, ey in G.CORE_ENGINES:
        nb.revolve(nprof, ex * M, ey * M, zb + N["top"] * M, 28, lambda h: 3)
    SN = G.SRB_NOZZLE
    sprof_n = [(r * M, -d * M) for r, d in G.nozzle_profile(500, SN["exit_r"], SN["length"], 8)]
    from mathutils import Matrix
    for sx, sy in G.SRB_CENTERS:
        tilt = Matrix.Rotation(math.radians(SN["cant_deg"]) * (-1 if sx > 0 else 1), 3, "Y")
        nb.revolve(sprof_n, sx * M, sy * M, zb + G.SRB_ST["bottom"] * M, 24, lambda h: 3, tilt=tilt)
    nb.to_object("nozzles", mats, root, smooth=True, coll=coll)
    return rocket


def build_flames(root, coll):
    """噴射炎の円錐(上端が原点、-z へ長さ 1)。スケールで長さと有無を決める。"""
    m = mat_flame("flame")
    zb = G.Z_BASE * M
    flames = []

    def cone(name, x, y, z, r0, r1):
        mb = MeshBuf()
        prof = [(0, 0.0), (r0, 0.0)] + [(r0 + (r1 - r0) * (k / 8) ** 0.7, -k / 8) for k in range(1, 9)] + [(0, -1.0)]
        mb.revolve(prof, 0, 0, 0, 24, lambda h: 0)
        ob = mb.to_object(name, [m], root, smooth=True, coll=coll)
        ob.location = (x, y, z)
        ob.scale = (0.001, 0.001, 0.001)
        ob.visible_shadow = False
        flames.append(ob)
        return ob
    N = G.CORE_NOZZLE
    for i, (ex, ey) in enumerate(G.CORE_ENGINES):
        cone(f"flame_core{i}", ex * M, ey * M, zb + (N["top"] - N["length"]) * M, N["exit_r"] * M * 0.95, 2.0)
    SN = G.SRB_NOZZLE
    for i, (sx, sy) in enumerate(G.SRB_CENTERS):
        ob = cone(f"flame_srb{i}", sx * M, sy * M, zb + (G.SRB_ST["bottom"] - SN["length"]) * M,
                  SN["exit_r"] * M * 0.95, 3.4)
        ob.rotation_euler = (0, math.radians(SN["cant_deg"]) * (-1 if sx > 0 else 1), 0)
    return flames


def build_ml(root, coll):
    steel = mat_build("ml_steel", (0.045, 0.047, 0.05, 1), 0.55, 0.3)
    deck = mat_build("ml_deck", (0.11, 0.11, 0.115, 1), 0.7, 0.2)
    Ml = G.ML
    hw, hd = Ml["w"] / 2 * M, Ml["d"] / 2 * M
    z0, z1 = Ml["z_bottom"] * M, Ml["z_deck"] * M
    ox, oy = 6.4, 3.6   # 排気孔の開口
    mb = MeshBuf()
    mb.box(-hw, -hd, z0, hw, -oy, z1)
    mb.box(-hw, oy, z0, hw, hd, z1)
    mb.box(-hw, -oy, z0, -ox, oy, z1)
    mb.box(ox, -oy, z0, hw, oy, z1)
    a = Ml["pedestal"] / 2 * M
    for px, py in Ml["pedestals"]:
        mb.box(px * M - a, py * M - a, 0, px * M + a, py * M + a, z0)
    # 保持柱
    for x, y in [(-G.SRB_X, 1.0e3), (-G.SRB_X, -1.0e3), (G.SRB_X, 1.0e3), (G.SRB_X, -1.0e3)]:
        mb.box(x * M - 0.45, y * M - 0.45, z1, x * M + 0.45, y * M + 0.45, G.Z_BASE * M - 0.5, 1)
    for x, y in [(-1.9, -1.9), (1.9, -1.9), (-1.9, 1.9), (1.9, 1.9)]:
        mb.box(x - 0.4, y - 0.4, z1, x + 0.4, y + 0.4, G.Z_BASE * M, 1)
    # デッキ上の手すり・機器
    for sx in (-1, 1):
        mb.box(sx * hw - 0.15, -hd, z1, sx * hw + 0.15, hd, z1 + 1.1, 1)
    mb.box(9.0, 6.0, z1, 13.5, 10.5, z1 + 3.0, 1)
    mb.box(-13.5, 6.0, z1, -9.0, 10.5, z1 + 2.2, 1)
    return mb.to_object("ml", [steel, deck], root, coll=coll)


def lattice(mb, x0, y0, x1, y1, h, panel, col_t, brace_t, mat=0, taper=None, levels=None):
    """格子塔(4本柱 + 各段の水平材 + 4面の X ブレース)。"""
    lv = levels or G.lattice_levels(h, panel)

    def corners(z):
        if taper is None:
            return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w = taper(z) / 2
        return [(cx - w, cy - w), (cx + w, cy - w), (cx + w, cy + w), (cx - w, cy + w)]
    for a, b in zip(lv[:-1], lv[1:]):
        ca, cb = corners(a), corners(b)
        for k in range(4):
            mb.strut((*ca[k], a), (*cb[k], b), col_t, mat)
            j = (k + 1) % 4
            mb.strut((*cb[k], b), (*cb[j], b), brace_t * 1.3, mat)
            mb.strut((*ca[k], a), (*cb[j], b), brace_t, mat)
            mb.strut((*ca[j], a), (*cb[k], b), brace_t, mat)


def build_tower(root, coll):
    steel = mat_build("tower_steel", (0.16, 0.17, 0.19, 1), 0.55, 0.4)
    red = mat_emit("beacon_red", (1.0, 0.05, 0.02, 1), 60.0, "blink")
    T = G.TOWER
    cx, w = T["cx"] * M, T["w"] * M
    x0, x1, y0, y1 = cx - w / 2, cx + w / 2, -w / 2, w / 2
    h = T["h"] * M
    mb = MeshBuf()
    lattice(mb, x0, y0, x1, y1, h, T["panel"] * M, T["column"] * M, 0.32)
    # 各段の床(格子の中)
    for z in G.lattice_levels(T["h"], T["panel"])[1::2]:
        mb.box(x0 + 0.5, y0 + 0.5, z * M - 0.15, x1 - 0.5, y1 - 0.5, z * M + 0.05)
    # エレベーターのシャフト
    mb.box(x0 + 1.5, y1 - 4.0, 0, x0 + 4.5, y1 - 1.0, h + 1.0)
    # 頂部のクレーン
    cr = h + 2.0
    mb.box(x1 - 1.0, -0.6, h, x1, 0.6, cr)
    mb.box(x0 - T["crane_len"] * M + 6.0, -0.5, cr - 1.2, x1, 0.5, cr)
    mb.strut((x0 - T["crane_len"] * M + 7.5, 0, cr - 1.2), (x0 - T["crane_len"] * M + 7.5, 0, cr - 9), 0.05)
    mb.strut((cx, 0, cr), (cx, 0, cr + T["beacon_h"] * M), 0.25)
    tower = mb.to_object("tower", [steel], root, coll=coll)
    # 航空障害灯(赤)
    beacons = []
    bm = MeshBuf()
    bm.revolve([(0, -0.5), (0.5, -0.3), (0.5, 0.3), (0, 0.5)], cx, 0, cr + T["beacon_h"] * M + 0.4, 12, lambda h: 0)
    beacons.append(bm.to_object("beacon_tower", [red], root, coll=coll))
    # アクセスアーム(塔の西面のヒンジで回る)
    arms = []
    for i, (name, z, x_tip, aw) in enumerate(G.ARMS):
        hinge = empty(f"arm_hinge{i}", (G.ARM_ROOT_X * M, aw / 2 * M, 0), root, coll)
        mb = MeshBuf()
        zt, zb_ = z * M, z * M - G.ARM_DEPTH * M
        xt = x_tip * M - G.ARM_ROOT_X * M      # ヒンジからの相対(負)
        yl, yr = -aw * M, 0.0
        for yy in (yl, yr):
            mb.strut((xt, yy, zt), (0, yy, zt), 0.3)
            mb.strut((xt, yy, zb_), (0, yy, zb_), 0.3)
            n = 6
            for k in range(n + 1):
                xa = xt * (1 - k / n)
                mb.strut((xa, yy, zb_), (xa, yy, zt), 0.22)
                if k < n:
                    xb = xt * (1 - (k + 1) / n)
                    if k % 2 == 0:
                        mb.strut((xa, yy, zb_), (xb, yy, zt), 0.18)
                    else:
                        mb.strut((xa, yy, zt), (xb, yy, zb_), 0.18)
        mb.box(xt, yl, zb_ - 0.1, 0, yr, zb_ + 0.1)          # 床
        if name.startswith("フェアリング"):
            mb.box(xt, yl - 0.3, zt, xt + 3.2, yr + 0.3, zt + 3.0)  # ホワイトルーム
        ob = mb.to_object(f"arm{i}", [steel], hinge, coll=coll)
        arms.append(hinge)
    return tower, arms, beacons


def build_lightning(roots, coll):
    steel = mat_build("lt_steel", (0.2, 0.2, 0.21, 1), 0.5, 0.5)
    red = bpy.data.materials["beacon_red"]
    L = G.LIGHTNING
    for i, (x, y) in enumerate(G.LIGHTNING_TOWERS):
        mb = MeshBuf()
        lattice(mb, x * M - 1, y * M - 1, x * M + 1, y * M + 1, L["h"] * M, 7.0, 0.35, 0.16,
                taper=lambda z: G.lightning_width(z / M) * M)
        mb.strut((x * M, y * M, L["h"] * M), (x * M, y * M, (L["h"] + L["mast_h"]) * M), L["mast_d"] * M)
        mb.to_object(f"lightning{i}", [steel], roots[i], coll=coll)
        bm = MeshBuf()
        bm.revolve([(0, -0.4), (0.4, -0.2), (0.4, 0.2), (0, 0.4)], x * M, y * M, L["h"] * M + 3.0, 10, lambda h: 0)
        bm.to_object(f"beacon_l{i}", [red], roots[i], coll=coll)
    # 架空地線(4辺)
    wm = MeshBuf()
    top = (L["h"] + L["mast_h"]) * M
    for a, b in G.CATENARY:
        pts = G.catenary(G.LIGHTNING_TOWERS[a], G.LIGHTNING_TOWERS[b], top / M, G.CATENARY_SAG)
        for p, q in zip(pts[:-1], pts[1:]):
            wm.strut(tuple(c * M for c in p), tuple(c * M for c in q), 0.08)
    wm.to_object("catenary", [steel], roots[-1], coll=coll)


def build_light_towers(roots, coll):
    pole = mat_build("pole", (0.25, 0.25, 0.26, 1), 0.5, 0.5)
    lamp = mat_emit("lamp_panel", (1.0, 0.93, 0.82, 1), 45.0, "lights")
    red = bpy.data.materials["beacon_red"]
    LT = G.LIGHT
    spots = []
    for i, (x, y) in enumerate(G.LIGHT_TOWERS):
        x, y = x * M, y * M
        h = LT["h"] * M
        mb = MeshBuf()
        mb.revolve([(0, 0), (LT["pole_d"] / 2 * M, 0), (LT["pole_d"] / 3 * M, h - 3.2), (0, h - 3.2)], x, y, 0, 16,
                   lambda hh: 0)
        az, el = G.light_aim(i)
        head = MeshBuf()
        hw, hh, hd = LT["head_w"] / 2 * M, LT["head_h"] / 2 * M, LT["head_d"] / 2 * M
        head.box(-hd, -hw, -hh, hd, hw, hh, 0)
        head.box(hd, -hw + 0.3, -hh + 0.3, hd + 0.08, hw - 0.3, hh - 0.3, 1)   # 発光面(ロケット側)
        ob = mb.to_object(f"lightpole{i}", [pole], roots[i], coll=coll)
        hob = head.to_object(f"lighthead{i}", [pole, lamp], roots[i], coll=coll)
        hob.location = (x, y, h - hh)
        hob.rotation_euler = (0, -el, az)
        bm = MeshBuf()
        bm.revolve([(0, -0.3), (0.3, -0.15), (0.3, 0.15), (0, 0.3)], x, y, h + 0.6, 10, lambda q: 0)
        bm.to_object(f"beacon_p{i}", [red], roots[i], coll=coll)
        # スポットライト
        ld = bpy.data.lights.new(f"spot{i}", "SPOT")
        ld.energy = 0.0
        ld.color = (1.0, 0.92, 0.80)
        ld.spot_size = math.radians(56)
        ld.spot_blend = 0.35
        ld.shadow_soft_size = 1.2
        lo = bpy.data.objects.new(f"spot{i}", ld)
        coll.objects.link(lo)
        lo.location = (x + math.cos(az) * 1.0, y + math.sin(az) * 1.0, h - hh)
        target = Vector((0, 0, 33.0))
        lo.rotation_euler = (target - Vector(lo.location)).to_track_quat("-Z", "Y").to_euler()
        spots.append(lo)
    return spots


def build_tanks_buildings(roots_tank, roots_bld, coll):
    white = mat_build("tank_white", (0.62, 0.63, 0.64, 1), 0.45, wire=(24, 2.5, 0.05))
    concrete = mat_build("bld_concrete", (0.30, 0.30, 0.29, 1), 0.85)
    window = mat_emit("windows", (1.0, 0.82, 0.55, 1), 6.0, "lights")
    W = G.WATER_TANK
    k = 0
    for (x, y) in G.WATER_TANKS:
        mb = MeshBuf()
        r, h = W["d"] / 2 * M, W["h"] * M
        prof = [(0, 0), (r, 0), (r, h)] + [(r * math.cos(a / 8 * math.pi / 2), h + 1.8 * math.sin(a / 8 * math.pi / 2))
                                           for a in range(1, 9)]
        mb.revolve(prof, 0, 0, 0, 40, lambda q: 0)
        ob = mb.to_object(f"watertank{k}", [white], roots_tank[k], smooth=True, coll=coll)
        ob.location = (x * M, y * M, 0)
        k += 1
    S = G.SPHERE
    for name, x, y in G.SPHERES:
        mb = MeshBuf()
        r = S["d"] / 2 * M
        zc = S["leg_h"] * M + r
        prof = [(r * math.sin(math.pi * i / 16), zc - r * math.cos(math.pi * i / 16)) for i in range(17)]
        mb.revolve(prof, 0, 0, 0, 32, lambda q: 0)
        for j in range(6):
            a = 2 * math.pi * j / 6
            px, py = 0.8 * r * math.cos(a), 0.8 * r * math.sin(a)
            mb.strut((px, py, 0), (px, py, zc), 0.6)
        ob = mb.to_object(f"sphere{k}", [white], roots_tank[k], smooth=True, coll=coll)
        ob.location = (x * M, y * M, 0)
        k += 1
    for j, (name, x, y, w, d, h) in enumerate(G.BUILDINGS):
        mb = MeshBuf()
        x, y, w, d, h = x * M, y * M, w * M, d * M, h * M
        mb.box(x - w / 2, y - d / 2, 0, x + w / 2, y + d / 2, h, 0)
        # 窓(南面と西面に点々と)
        nwin = int(w / 3.2)
        for q in range(nwin):
            if (q * 7 + j * 3) % 5 in (0, 2):
                continue
            wx = x - w / 2 + 1.6 + q * 3.2
            for zz in ([h * 0.35] if h < 9 else [h * 0.3, h * 0.68]):
                mb.box(wx, y - d / 2 - 0.05, zz, wx + 1.4, y - d / 2 + 0.01, zz + 1.2, 1)
        mb.to_object(f"building{j}", [concrete, window], roots_bld[j], coll=coll)


def build_ground(coll):
    """地面(段丘の上)・射点の床・道路・排煙溝・法面・海・丘。"""
    from shapely.geometry import Polygon, LineString, box
    from shapely import constrained_delaunay_triangles
    ground_m = mat_env("ground", (0.035, 0.04, 0.032, 1), 0.9, bump=0.3)
    apron_m = mat_env("apron", (0.22, 0.22, 0.21, 1), 0.75, bump=0.15)
    road_m = mat_env("road", (0.05, 0.05, 0.05, 1), 0.6)
    slope_m = mat_env("slope", (0.12, 0.115, 0.10, 1), 0.95, bump=0.5)
    sea_m = mat_env("sea", (0.004, 0.012, 0.022, 1), 0.08, sea=True)
    hill_m = mat_env("hill", (0.012, 0.016, 0.012, 1), 0.95, bump=0.2)
    trench_m = mat_env("trench", (0.14, 0.135, 0.12, 1), 0.9)

    def poly_mesh(name, poly, z, mat):
        tris = constrained_delaunay_triangles(poly)
        mb = MeshBuf()
        for t in tris.geoms:
            c = list(t.exterior.coords)[:3]
            mb.add([(p[0], p[1], z) for p in c], [(0, 1, 2)])
        return mb.to_object(name, [mat], coll=coll)

    bank = [(x * M, y * M) for x, y in G.BANK_TOP]
    E = 700.0
    land = Polygon([(-E, bank[0][1])] + bank + [(E, bank[-1][1]), (E, E), (-E, E)])
    tw = G.TRENCH["w"] / 2 * M + G.TRENCH["wall"] * M
    trench_open = box(-tw, G.TRENCH["y_outlet"] * M - 12, tw, G.TRENCH["y_cover"] * M)
    apron = Polygon([(x * M, y * M) for x, y in G.APRON]).difference(trench_open)
    roads = None
    for rd in G.ROADS:
        g = LineString([(x * M, y * M) for x, y in rd]).buffer(G.ROAD_W / 2 * M, cap_style=2, join_style=2)
        roads = g if roads is None else roads.union(g)
    roads = roads.difference(apron).difference(trench_open)
    land = land.difference(trench_open).difference(apron).difference(roads)
    for i, p in enumerate(getattr(land, "geoms", [land])):
        poly_mesh(f"ground{i}", p, 0.0, ground_m)
    for i, p in enumerate(getattr(apron, "geoms", [apron])):
        poly_mesh(f"apron{i}", p, 0.02, apron_m)
    for i, p in enumerate(getattr(roads, "geoms", [roads])):
        poly_mesh(f"road{i}", p, 0.01, road_m)
    # 法面(段丘の肩 → 海岸線)
    top = LineString(bank)
    coast = LineString([(x * M, y * M) for x, y in G.COAST_LINE])
    mb = MeshBuf()
    n = 120
    prev = None
    for i in range(n + 1):
        u = i / n
        p = top.interpolate(u, normalized=True)
        q = coast.interpolate(u, normalized=True)
        cur = [(p.x, p.y, 0.0), (q.x, q.y, G.SEA_LEVEL * M - 1.0)]
        if prev:
            mb.add([prev[0], cur[0], cur[1], prev[1]], [(0, 3, 2, 1)])
        prev = cur
    for side, xs in ((-1, -E), (1, E)):
        pass
    mb.to_object("slope", [slope_m], coll=coll)
    # 排煙溝(開いている部分)
    T = G.TRENCH
    w = T["w"] / 2 * M
    yc, yo = T["y_cover"] * M, T["y_outlet"] * M
    fc, fo = T["floor_deflector"] * M + 2.0, T["floor_outlet"] * M
    mb = MeshBuf()
    mb.add([(-w, yc, fc), (w, yc, fc), (w, yo, fo), (-w, yo, fo)], [(0, 1, 2, 3)])
    for s in (-1, 1):
        mb.add([(s * w, yc, fc), (s * w, yc, 0), (s * w, yo, 0), (s * w, yo, fo)], [(0, 1, 2, 3)])
        mb.add([(s * w, yc, 0), (s * tw, yc, 0), (s * tw, yo, 0), (s * w, yo, 0)], [(0, 1, 2, 3)])
    mb.add([(-w, yc, fc), (w, yc, fc), (w, yc, 0), (-w, yc, 0)], [(0, 1, 2, 3)])
    mb.add([(-tw, yo, 0), (tw, yo, 0), (tw, yo - 10, G.SEA_LEVEL * M - 1), (-tw, yo - 10, G.SEA_LEVEL * M - 1)],
           [(0, 1, 2, 3)])
    mb.to_object("trench", [trench_m], coll=coll)
    # 海
    mb = MeshBuf()
    sz = G.SEA_LEVEL * M
    mb.add([(-3000, -3000, sz), (3000, -3000, sz), (3000, -60, sz), (-3000, -60, sz)], [(0, 1, 2, 3)])
    sea = mb.to_object("sea", [sea_m], coll=coll)
    # 丘
    for i, (hx, hy, hr, hh) in enumerate(G.HILLS):
        n = 48
        xs = np.linspace(-1, 1, n)
        X, Y = np.meshgrid(xs, xs)
        R = np.sqrt(X ** 2 + Y ** 2)
        rng = np.random.default_rng(i + 3)
        bumps = sum(rng.uniform(0.04, 0.10) * np.sin(X * rng.uniform(4, 9) + rng.uniform(0, 6))
                    * np.cos(Y * rng.uniform(3, 8) + rng.uniform(0, 6)) for _ in range(4))
        Z = np.clip(np.exp(-(R * 1.6) ** 2) * (1 + bumps) - 0.02, -0.05, None) * hh * M
        verts = np.column_stack([hx * M + X.ravel() * hr * M, hy * M + Y.ravel() * hr * M, Z.ravel() - 1.0])
        faces = [(r * n + c, r * n + c + 1, (r + 1) * n + c + 1, (r + 1) * n + c)
                 for r in range(n - 1) for c in range(n - 1)]
        mb = MeshBuf()
        mb.add(verts.tolist(), faces)
        mb.to_object(f"hill{i}", [hill_m], smooth=True, coll=coll)
    return sea


def build_world():
    w = bpy.data.worlds.new("night")
    bpy.context.scene.world = w
    nt = w.node_tree
    nt.nodes.clear()
    b = NB(nt)
    c = ctrl_node(b)
    tc = b.node("ShaderNodeTexCoord").outputs["Generated"]
    d = b.vec("NORMALIZE", tc)
    zz = b.sep(d)[2]
    up = b.math("MAXIMUM", zz, 0.0)
    sky = b.mix_rgb(b.math("POWER", up, 0.45), (0.016, 0.030, 0.065, 1), (0.003, 0.006, 0.018, 1))
    vor = b.node("ShaderNodeTexVoronoi", inputs={"Scale": 420.0, "Randomness": 1.0})
    b.set(vor.inputs["Vector"], d)
    star = b.math("SUBTRACT", 1.0, b.math("DIVIDE", vor.outputs["Distance"], 0.07), clamp=True)
    star = b.math("POWER", star, 6.0)
    nz = b.node("ShaderNodeTexNoise", inputs={"Scale": 9.0, "Detail": 2.0})
    b.set(nz.inputs["Vector"], d)
    star = b.math("MULTIPLY", star, b.math("POWER", nz.outputs["Fac"], 3.0))
    star = b.math("MULTIPLY", star, b.math("GREATER_THAN", zz, 0.02))
    star = b.math("MULTIPLY", star, 45.0)
    # 月(北の低い空)
    mdir = MOON_DIR
    md = b.vec("DOT_PRODUCT", d, mdir)
    moon = b.math("GREATER_THAN", md, math.cos(math.radians(0.55)))
    halo = b.math("POWER", b.math("MAXIMUM", md, 0.0), 1500.0)
    star = b.math("ADD", star, b.math("ADD", b.math("MULTIPLY", moon, 25.0), b.math("MULTIPLY", halo, 0.25)))
    col = b.node("ShaderNodeMix", data_type="RGBA")
    b.set(col.inputs[0], b.math("MINIMUM", star, 1.0))
    b.set(col.inputs[6], sky)
    b.set(col.inputs[7], (0.85, 0.9, 1.0, 1))
    bg = b.node("ShaderNodeBackground")
    b.set(bg.inputs["Color"], col.outputs[2])
    b.set(bg.inputs["Strength"], b.math("MULTIPLY", c["env"], b.math("ADD", 1.0, b.math("MULTIPLY", star, 1.0))))
    out = b.node("ShaderNodeOutputWorld")
    b.set(out.inputs["Surface"], bg.outputs[0])


def build_particles(coll):
    """光の粒(Geometry Nodes): 渦を巻いて昇る。"""
    me = bpy.data.meshes.new("swirl")
    ob = bpy.data.objects.new("swirl", me)
    coll.objects.link(ob)
    ng = bpy.data.node_groups.new("Swirl", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    fade_s = ng.interface.new_socket("Fade", in_out="INPUT", socket_type="NodeSocketFloat")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    b = NB(ng)
    gin = b.node("NodeGroupInput")
    gout = b.node("NodeGroupOutput")
    idx = b.node("GeometryNodeInputIndex").outputs[0]
    t = b.node("GeometryNodeInputSceneTime").outputs["Seconds"]

    def rnd(seed):
        n = b.node("FunctionNodeRandomValue", data_type="FLOAT")
        b.set(n.inputs["ID"], idx)
        b.set(n.inputs["Seed"], seed)
        return [o for o in n.outputs if o.type == "VALUE" and o.enabled][0]
    H = 100.0
    r1, r2, r3, r4, r5 = (rnd(s) for s in (1, 2, 3, 4, 5))
    speed = b.math("MULTIPLY_ADD", r2, 0.10, 0.07)
    h01 = b.math("FRACT", b.math("MULTIPLY_ADD", t, speed, r1))
    h = b.math("MULTIPLY", h01, H)
    rad = b.math("MULTIPLY", b.math("MULTIPLY_ADD", h01, -30.0, 40.0), b.math("MULTIPLY_ADD", r3, 0.5, 0.5))
    rad = b.math("ADD", rad, 3.0)
    ang = b.math("MULTIPLY_ADD", b.math("MULTIPLY_ADD", h01, 0.9, 0.7), t, b.math("MULTIPLY", r4, 6.2832))
    x = b.math("MULTIPLY", rad, b.math("COSINE", ang))
    y = b.math("MULTIPLY", rad, b.math("SINE", ang))
    pts = b.node("GeometryNodePoints", inputs={"Count": 2600})
    b.set(pts.inputs["Position"], b.xyz(x, y, h))
    ico = b.node("GeometryNodeMeshIcoSphere", inputs={"Radius": 0.16, "Subdivisions": 1})
    inst = b.node("GeometryNodeInstanceOnPoints")
    b.set(inst.inputs["Points"], pts.outputs[0])
    b.set(inst.inputs["Instance"], ico.outputs["Mesh"])
    taper = b.math("SINE", b.math("MULTIPLY", h01, math.pi))
    sc = b.math("MULTIPLY", b.math("MULTIPLY", gin.outputs["Fade"], taper), b.math("MULTIPLY_ADD", r5, 1.4, 0.4))
    b.set(inst.inputs["Scale"], sc)
    sm = b.node("GeometryNodeSetMaterial")
    b.set(sm.inputs["Geometry"], inst.outputs[0])
    sm.inputs["Material"].default_value = mat_emit("particle", (0.35, 1.0, 0.95, 1), 14.0)
    b.set(gout.inputs[0], sm.outputs[0])
    ob.visible_shadow = False
    mod = ob.modifiers.new("Swirl", "NODES")
    mod.node_group = ng
    item = getattr(mod.properties.inputs, fade_s.identifier)
    key(item, "value", [(0, 0.0), (4.6, 0.0), (5.4, 1.0), (8.4, 1.0), (9.4, 0.0)], id_data=ob)
    return ob


# --- 噴煙(点群を毎フレーム Python で計算し、Geometry Nodes で球を並べる) ---
_RNG = np.random.default_rng(11)
SMOKE = {}


def _init_smoke():
    r = _RNG
    nA, nB, nC = 1300, 1000, 1700
    SMOKE["A"] = dict(birth=TI + 0.25 + (T_END + 0.5 - TI) * r.random(nA) ** 1.5,
                      ang=np.radians(-90 + r.normal(0, 32, nA)), v0=18 + 16 * r.random(nA),
                      up=r.random(nA), dx=r.normal(0, 1, nA), shade=r.random(nA))
    SMOKE["B"] = dict(birth=TL - 0.25 + (T_END + 0.5 - TL) * r.random(nB) ** 1.7,
                      ang=r.uniform(0, 2 * np.pi, nB), v0=12 + 10 * r.random(nB),
                      up=r.random(nB), shade=r.random(nB))
    SMOKE["C"] = dict(birth=np.sort(TL + 0.3 + (T_END + 0.2 - TL - 0.3) * r.random(nC)),
                      jx=r.normal(0, 1.3, nC), jy=r.normal(0, 1.3, nC), up=r.random(nC), shade=r.random(nC))


def smoke_state(t):
    P, R, GL, SH = [], [], [], []
    a = SMOKE["A"]                       # 排煙溝の出口から南へ
    age = t - a["birth"]
    k = age > 0
    if k.any():
        ag = age[k]
        dist = a["v0"][k] * 1.3 * (1 - np.exp(-ag / 1.3)) + 2.5 * ag
        x = dist * np.cos(a["ang"][k]) + a["dx"][k] * (1.5 + 3 * ag)
        y = G.TRENCH["y_outlet"] * M + dist * np.sin(a["ang"][k])
        z = -4.0 + 3.0 * ag ** 0.85 + 4.0 * a["up"][k] * ag
        P.append(np.column_stack([x, y, z]))
        R.append(np.minimum(2.2 + 3.0 * ag ** 0.7, 15))
        GL.append(np.exp(-ag * 1.3))
        SH.append(a["shade"][k])
    b = SMOKE["B"]                       # 移動発射台のまわりから横へ
    age = t - b["birth"]
    k = age > 0
    if k.any():
        ag = age[k]
        dist = 14 + b["v0"][k] * 1.0 * (1 - np.exp(-ag / 1.0)) + 1.8 * ag
        x = dist * np.cos(b["ang"][k])
        y = dist * np.sin(b["ang"][k]) * 0.85
        z = 2.0 + 2.6 * ag ** 0.8 + 3 * b["up"][k] * ag
        P.append(np.column_stack([x, y, z]))
        R.append(np.minimum(1.8 + 2.3 * ag ** 0.7, 10))
        GL.append(np.exp(-ag * 1.6))
        SH.append(b["shade"][k])
    c = SMOKE["C"]                       # 上昇する機体の後ろに残る柱
    age = t - c["birth"]
    k = age > 0
    if k.any():
        ag = age[k]
        ze = np.array([(G.Z_BASE - 3000) * M + rise_m(bb) for bb in c["birth"][k]])
        keep = ze > 16
        ag, ze = ag[keep], ze[keep]
        if len(ag):
            z = ze - 14 * (1 - np.exp(-ag / 0.45)) - 0.8 * ag
            x = c["jx"][k][keep] * (1 + 0.8 * ag) + 1.6 * ag
            y = c["jy"][k][keep] * (1 + 0.8 * ag) + 0.6 * ag
            P.append(np.column_stack([x, y, z]))
            R.append(np.minimum(1.4 + 2.6 * ag ** 0.6, 11))
            GL.append(np.exp(-ag * 2.8))
            SH.append(c["shade"][k][keep])
    if not P:
        return np.zeros((0, 3)), np.zeros(0), np.zeros(0), np.zeros(0)
    return np.vstack(P), np.concatenate(R), np.concatenate(GL), np.concatenate(SH)


def build_smoke(coll):
    _init_smoke()
    me = bpy.data.meshes.new("smoke_pts")
    ob = bpy.data.objects.new("smoke", me)
    coll.objects.link(ob)
    ng = bpy.data.node_groups.new("SmokeInst", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    b = NB(ng)
    gin, gout = b.node("NodeGroupInput"), b.node("NodeGroupOutput")
    m2p = b.node("GeometryNodeMeshToPoints")
    b.set(m2p.inputs["Mesh"], gin.outputs[0])
    ico = b.node("GeometryNodeMeshIcoSphere", inputs={"Radius": 1.0, "Subdivisions": 3})
    # 球を雲のようにでこぼこにする(法線方向にノイズで押し出す)
    nz = b.node("ShaderNodeTexNoise", inputs={"Scale": 1.6, "Detail": 3.0, "Roughness": 0.6})
    npos = b.node("GeometryNodeInputPosition").outputs[0]
    b.set(nz.inputs["Vector"], npos)
    off = b.vec("SCALE", b.node("GeometryNodeInputNormal").outputs[0],
                scale=b.math("MULTIPLY", b.math("SUBTRACT", nz.outputs["Fac"], 0.5), 0.55))
    sp = b.node("GeometryNodeSetPosition")
    b.set(sp.inputs["Geometry"], ico.outputs["Mesh"])
    b.set(sp.inputs["Offset"], off)
    smooth = b.node("GeometryNodeSetShadeSmooth")
    b.set(smooth.inputs["Geometry"], sp.outputs[0])
    rad = b.node("GeometryNodeInputNamedAttribute", data_type="FLOAT")
    rad.inputs["Name"].default_value = "puff_r"
    rr = b.node("FunctionNodeRandomValue", data_type="FLOAT_VECTOR")
    rr.inputs["Max"].default_value = (6.28, 6.28, 6.28)
    inst = b.node("GeometryNodeInstanceOnPoints")
    b.set(inst.inputs["Points"], m2p.outputs[0])
    b.set(inst.inputs["Instance"], smooth.outputs[0])
    b.set(inst.inputs["Scale"], [o for o in rad.outputs if o.enabled][0])
    b.set(inst.inputs["Rotation"], [o for o in rr.outputs if o.enabled and o.type == "VECTOR"][0])
    real = b.node("GeometryNodeRealizeInstances")
    b.set(real.inputs[0], inst.outputs[0])
    sm = b.node("GeometryNodeSetMaterial")
    b.set(sm.inputs["Geometry"], real.outputs[0])
    sm.inputs["Material"].default_value = mat_smoke()
    b.set(gout.inputs[0], sm.outputs[0])
    mod = ob.modifiers.new("SmokeInst", "NODES")
    mod.node_group = ng

    def update(scene, *args):
        t = (scene.frame_current - 1) / FPS
        P, R, GLw, SH = smoke_state(t)
        me = ob.data
        me.clear_geometry()
        n = len(P)
        if n == 0:
            P, R, GLw, SH = np.array([[0, 0, -500.0]]), np.array([0.001]), np.zeros(1), np.zeros(1)
            n = 1
        me.vertices.add(n)
        me.vertices.foreach_set("co", P.astype(np.float32).ravel())
        for name, arr in (("puff_r", R), ("glow", GLw), ("shade", SH)):
            at = me.attributes.get(name) or me.attributes.new(name, "FLOAT", "POINT")
            at.data.foreach_set("value", arr.astype(np.float32))
        me.update()
    bpy.app.handlers.frame_change_pre.append(update)
    return ob


# ===========================================================================
# 画面の文字
# ===========================================================================
def text_obj(name, body, font, size, loc, parent, coll, color=CYAN, strength=4.0, align="CENTER", spacing=1.0):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.font = bpy.data.fonts.load(font, check_existing=True)
    cu.size = size
    cu.align_x = align
    cu.align_y = "CENTER"
    cu.space_character = spacing
    ob = bpy.data.objects.new(name, cu)
    coll.objects.link(ob)
    ob.parent = parent
    ob.location = loc
    m = mat_text(f"txt_{name}", color, strength)
    cu.materials.append(m)
    ob.visible_shadow = False
    return ob, m


def fade_key(m, pairs):
    sock = m.node_tree.nodes["fade"].outputs[0]
    key(sock, "default_value", pairs, interp="LINEAR", id_data=m.node_tree)


# ===========================================================================
# 組み立て
# ===========================================================================
def build(res=(1920, 1080), samples=16):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end = 1, F(T_END) - 1
    make_ctrl()

    c_draw, c_build, c_env, c_fx, c_ui = (collection(n) for n in ("Drawing", "Build", "Env", "FX", "UI"))
    build_floor_plan(c_draw)

    # --- 設備ごとの根(立ち上げのスケール用) ---
    groups = {}

    def root(name, xy):
        r = empty(f"root_{name}", (0, 0, 0), coll=c_build)
        r.scale = (1, 1, 0.002)
        groups[name] = (r, math.hypot(*xy) * M)
        return r
    rk_root = root("rocket", (0, 0))
    rocket_rig = empty("RocketRig", (0, 0, 0), rk_root, c_build)
    build_rocket(rocket_rig, c_build)
    flames = build_flames(rocket_rig, c_fx)
    build_ml(root("ml", (0, 1)), c_build)
    tower, arms, beacons = build_tower(root("tower", (G.TOWER["cx"], 0)), c_build)
    lroots = [root(f"lightning{i}", xy) for i, xy in enumerate(G.LIGHTNING_TOWERS)]
    build_lightning(lroots, c_build)
    lt_roots = [root(f"light{i}", xy) for i, xy in enumerate(G.LIGHT_TOWERS)]
    spots = build_light_towers(lt_roots, c_build)
    troots = [root(f"tank{i}", xy) for i, xy in enumerate(G.WATER_TANKS + [(x, y) for _, x, y in G.SPHERES])]
    broots = [root(f"bld{i}", (x, y)) for i, (_, x, y, *_r) in enumerate(G.BUILDINGS)]
    build_tanks_buildings(troots, broots, c_build)
    build_ground(c_env)
    build_world()
    build_particles(c_fx)
    build_smoke(c_fx)

    # --- 光源 ---
    moon = bpy.data.lights.new("moon", "SUN")
    moon.energy = 0.35
    moon.color = (0.62, 0.72, 1.0)
    moon.angle = math.radians(1.5)
    mo = bpy.data.objects.new("moon", moon)
    c_env.objects.link(mo)
    mo.rotation_euler = (Vector(MOON_DIR) * -1).to_track_quat("-Z", "Y").to_euler()
    key(moon, "energy", [(8.8, 0.0), (10.9, 0.35)])
    fill = bpy.data.lights.new("fill", "SUN")
    fill.energy = 0.0
    fill.color = (0.55, 0.85, 1.0)
    fo = bpy.data.objects.new("fill", fill)
    c_env.objects.link(fo)
    fo.rotation_euler = (math.radians(62), 0, math.radians(-25))
    key(fill, "energy", [(4.5, 0.0), (5.5, 1.6), (8.8, 1.6), (10.5, 0.0)])
    flame_light = bpy.data.lights.new("flame_light", "POINT")
    flame_light.color = (1.0, 0.55, 0.22)
    flame_light.shadow_soft_size = 4.0
    fl = bpy.data.objects.new("flame_light", flame_light)
    c_fx.objects.link(fl)
    fl.parent = rocket_rig
    fl.location = (0, 0, G.Z_BASE * M - 9.0)
    trench_light = bpy.data.lights.new("trench_light", "POINT")
    trench_light.color = (1.0, 0.5, 0.2)
    trench_light.shadow_soft_size = 6.0
    tlo = bpy.data.objects.new("trench_light", trench_light)
    c_fx.objects.link(tlo)
    tlo.location = (0, G.TRENCH["y_outlet"] * M - 8, 4.0)

    # =======================================================================
    # タイムライン
    # =======================================================================
    ctrl_key("scan_r", [(0.0, 0.0), (0.25, 0.0), (2.9, 250.0)])
    ctrl_key("line_glow", [(0.0, 0.0), (0.2, 1.0), (8.6, 1.0), (10.8, 0.6)])
    ctrl_key("wire_on", [(3.0, 0.0), (3.4, 1.0), (8.6, 1.0), (9.3, 0.0)])
    ctrl_key("build_h", [(5.2, -1.0), (8.5, 118.0), (8.6, 2000.0)], interp="LINEAR")
    ctrl_key("cut_glow", [(5.0, 0.0), (5.3, 1.0), (8.5, 1.0), (8.6, 0.0)])
    ctrl_key("dissolve", [(8.6, 0.0), (10.9, 1.0)])
    ctrl_key("env", [(8.8, 0.0), (10.9, 1.0)])
    ctrl_key("lights", [(10.0, 0.0), (10.9, 1.0)])
    blink = [(0.0, 0.0), (10.4, 0.0)]
    t = 10.6
    while t < T_END + 1:
        blink += [(t, 1.0), (t + 0.45, 0.0)]
        t += 1.1
    ctrl_key("blink", blink, interp="CONSTANT")

    # 立ち上がり(線 → ワイヤー)
    for name, (r, dist) in groups.items():
        t0 = 3.1 + 0.9 * min(dist / 110.0, 1.0)
        key(r, "scale", [(0, (1, 1, 0.002)), (t0, (1, 1, 0.002)), (t0 + 1.3, (1, 1, 1.0))])

    # 照明塔の点灯
    for i, lo in enumerate(spots):
        ton = TLN.LIGHT_ON[i]
        key(lo.data, "energy", [(0, 0.0), (ton, 0.0), (ton + 0.06, 2.6e5 * 1.3), (ton + 0.12, 1.2e5),
                                (ton + 0.3, 2.6e5)], interp="LINEAR")

    # アクセスアームの離脱
    for i, hinge in enumerate(arms):
        t0 = 11.0 + 0.25 * (2 - i)
        key(hinge, "rotation_euler", [(t0, (0, 0, 0)), (t0 + 1.4, (0, 0, -math.radians(G.ARM_SWING_DEG)))])

    # 点火・炎・上昇
    rng = np.random.default_rng(5)
    flame_frames = range(F(TI) - 1, F(T_END) + 2)
    for ob in flames:
        srb = "srb" in ob.name
        t_on = TL - 0.12 if srb else TI
        L = 34.0 if srb else 22.0
        ob.scale = (0.001, 0.001, 0.001)
        ob.keyframe_insert("scale", frame=F(t_on) - 1)
        for f in flame_frames:
            tt = (f - 1) / FPS
            if tt < t_on:
                continue
            grow = min((tt - t_on) / 0.35, 1.0)
            j = 1 + rng.normal(0, 0.06)
            ob.scale = (j * (0.6 + 0.4 * grow), j * (0.6 + 0.4 * grow), L * grow * (1 + rng.normal(0, 0.05)))
            ob.keyframe_insert("scale", frame=f)
    pairs = [(0, 0.0), (TI - 0.05, 0.0)]
    tl_pairs = [(0, 0.0), (TI, 0.0)]
    for f in flame_frames:
        tt = (f - 1) / FPS
        if tt < TI:
            continue
        base = 0.35 if tt < TL else 1.0
        v = base * min((tt - TI) / 0.3, 1.0) * (1 + rng.normal(0, 0.1))
        pairs.append((tt, v))
        tl_pairs.append((tt, v * (1.0 if tt < TL + 2.0 else max(0.25, 1 - (tt - TL - 2) / 2.5))))
    ctrl_key("flame", pairs, interp="LINEAR")
    key(flame_light, "energy", [(t, v * 2.5e5) for t, v in pairs], interp="LINEAR")
    key(trench_light, "energy", [(t, v * 2.5e5) for t, v in tl_pairs], interp="LINEAR")
    rise_pairs = [(0, (0, 0, 0)), (TL, (0, 0, 0))]
    tt = TL
    while tt <= T_END + 0.1:
        tt += 1 / FPS
        rise_pairs.append((tt, (0, 0, rise_m(tt))))
    key(rocket_rig, "location", rise_pairs, interp="LINEAR")

    # =======================================================================
    # カメラ
    # =======================================================================
    shake = empty("CamShake", (0, 0, 0), coll=c_ui)
    cd = bpy.data.cameras.new("cam_main")
    cd.lens = 35
    cd.clip_start, cd.clip_end = 0.5, 5000
    cam = bpy.data.objects.new("cam_main", cd)
    c_ui.objects.link(cam)
    cam.parent = shake
    tgt = empty("CamTarget", (0, 0, 0), coll=c_ui)
    shots = [
        (0.0, (42.5, -2.5, 420.0), (42.5, -2.0, 0.0)),
        (3.0, (36.0, -12.0, 360.0), (33.0, -2.0, 0.0)),
        (5.0, (82.0, -158.0, 112.0), (6.0, 0.0, 26.0)),
        (8.5, (40.0, -70.0, 30.0), (0.0, 0.0, 38.0)),
        (11.0, (100.0, -215.0, 20.0), (2.0, 4.0, 38.0)),
        (15.5, (74.0, -165.0, 13.0), (0.0, 0.0, 40.0)),
        (T_CUT, (70.0, -158.0, 12.0), (0.0, 0.0, 40.0 + rise_m(T_CUT) * 0.6)),
    ]
    key(cam, "location", [(t, p) for t, p, _ in shots])
    key(tgt, "location", [(t, q) for t, _, q in shots])
    bake_look_at(cam, tgt, 0.0, T_CUT + 0.1)
    sh = [(0, (0, 0, 0)), (TI - 0.05, (0, 0, 0))]
    for f in range(F(TI), F(T_CUT) + 1, 2):
        tt = (f - 1) / FPS
        amp = 0.05 if tt < TL else 0.16 * max(0.3, 1 - (tt - TL) / 2.0)
        sh.append((tt, tuple(rng.normal(0, amp, 3))))
    key(shake, "location", sh, interp="LINEAR")

    cd2 = bpy.data.cameras.new("cam_sea")
    cd2.lens = 32
    cd2.clip_start, cd2.clip_end = 0.5, 6000
    cam2 = bpy.data.objects.new("cam_sea", cd2)
    c_ui.objects.link(cam2)
    tgt2 = empty("SeaTarget", (0, 0, 0), coll=c_ui)
    key(cam2, "location", [(T_CUT, (-28.0, -330.0, -5.6)), (T_END, (-20.0, -312.0, -5.2))], interp="LINEAR")
    sea_t = []
    tt = T_CUT
    while tt <= T_END + 0.05:
        z = (G.Z_BASE * M + rise_m(tt)) * 0.55 + 32
        sea_t.append((tt, (0.0, 0.0, z)))
        tt += 0.25
    key(tgt2, "location", sea_t)
    bake_look_at(cam2, tgt2, T_CUT - 0.1, T_END + 0.1)
    sc.camera = cam
    mk = sc.timeline_markers.new("main", frame=1)
    mk.camera = cam
    mk = sc.timeline_markers.new("sea", frame=F(T_CUT))
    mk.camera = cam2

    # =======================================================================
    # 画面の文字: カウントダウン(主カメラ)とタイトル(海上カメラ)
    # =======================================================================
    d = 2.0
    hud = empty("HUD", (0, 0, -d), cam, c_ui)
    lab, ml = text_obj("cd_label", "COUNTDOWN", FONT_EN, 0.024, (-0.93, -0.36, 0), hud, c_ui, spacing=1.6,
                       strength=2.5, align="LEFT")
    bar = MeshBuf()
    bar.box(-0.93, -0.385, 0, -0.55, -0.382, 0.001)
    bob = bar.to_object("cd_bar", [ml], hud, coll=c_ui)
    counts = [(f"T−{3 - i}", t) for i, t in enumerate(TLN.COUNTS)] + [("IGNITION", TI), ("LIFTOFF", TL)]
    fade_key(ml, [(12.3, 0.0), (12.5, 1.0), (17.2, 1.0), (17.5, 0.0)])
    for i, (s, t0) in enumerate(counts):
        t1 = counts[i + 1][1] if i + 1 < len(counts) else 17.4
        ob, m = text_obj(f"cd{i}", s, FONT_EN, 0.075 if i < 3 else 0.05, (-0.935, -0.44, 0), hud, c_ui,
                         spacing=1.2, strength=4.0, align="LEFT")
        fp = 1.0 / FPS
        fade_key(m, [(0, 0.0), (t0 - fp, 0.0), (t0, 1.0), (t1 - 2 * fp, 1.0), (t1 - fp, 0.0)])
    tl = empty("TitleHUD", (0, 0, -d), cam2, c_ui)
    t1o, m1 = text_obj("title_jp", "夜 の 射 点", FONT_JP, 0.12, (0.90, 0.02, 0), tl, c_ui,
                       color=(0.85, 1.0, 1.0, 1), strength=3.0, spacing=1.0, align="RIGHT")
    t2o, m2 = text_obj("title_en", "NIGHT  LAUNCH", FONT_EN, 0.03, (0.90, -0.075, 0), tl, c_ui, spacing=2.2,
                       strength=2.5, align="RIGHT")
    fade_key(m1, [(0, 0.0), (T_TITLE, 0.0), (T_TITLE + 0.8, 1.0)])
    fade_key(m2, [(0, 0.0), (T_TITLE + 0.4, 0.0), (T_TITLE + 1.2, 1.0)])

    # =======================================================================
    # レンダー設定
    # =======================================================================
    r = sc.render
    r.engine = "BLENDER_EEVEE"
    r.resolution_x, r.resolution_y = res
    r.resolution_percentage = 100
    r.film_transparent = False
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    e = sc.eevee
    e.taa_render_samples = samples
    e.use_shadows = False          # ソフトウェア描画では影が一番重い(夜景なので省く)
    e.shadow_ray_count = 1
    e.shadow_step_count = 4
    e.use_raytracing = False
    e.clamp_surface_indirect = 10.0
    sc.view_settings.view_transform = "AgX"
    try:
        sc.view_settings.look = "AgX - Punchy"
    except TypeError:
        pass
    sc.view_settings.exposure = 0.6
    # 光のにじみ(コンポジターのグレア)
    ng = bpy.data.node_groups.new("Comp", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    b = NB(ng)
    rl = b.node("CompositorNodeRLayers")
    gl = b.node("CompositorNodeGlare")
    gl.inputs["Type"].default_value = "Bloom"
    gl.inputs["Quality"].default_value = "Medium"
    gl.inputs["Threshold"].default_value = 1.0
    gl.inputs["Strength"].default_value = 0.55
    gl.inputs["Size"].default_value = 0.6
    b.set(gl.inputs["Image"], rl.outputs["Image"])
    go = b.node("NodeGroupOutput")
    b.set(go.inputs[0], gl.outputs[0])
    sc.compositing_node_group = ng
    r.use_compositing = True
    return sc


def bake_look_at(cam, tgt, t0, t1):
    """カメラの向きを、注視点への向きから毎フレーム計算してキーにする。
    真下を見るときは北(+Y)を画面の上にする。"""
    from mathutils import Matrix
    fc_c = {fc.array_index: fc for fc in fcurves(cam) if fc.data_path == "location"}
    fc_t = {fc.array_index: fc for fc in fcurves(tgt) if fc.data_path == "location"}
    prev = None
    for f in range(F(t0), F(t1) + 1):
        p = Vector([fc_c[i].evaluate(f) for i in range(3)])
        q = Vector([fc_t[i].evaluate(f) for i in range(3)])
        fwd = (q - p).normalized()
        w = min(max((-fwd.z - 0.80) / 0.17, 0.0), 1.0)
        w = w * w * (3 - 2 * w)
        up = (Vector((0, 0, 1)) * (1 - w) + Vector((0, 1, 0)) * w).normalized()
        cz = -fwd
        cx = up.cross(cz).normalized()
        cy = cz.cross(cx)
        rot = Matrix((cx, cy, cz)).transposed()
        e = rot.to_euler("XYZ", prev) if prev else rot.to_euler("XYZ")
        prev = e
        cam.rotation_euler = e
        cam.keyframe_insert("rotation_euler", frame=f)
    for fc in fcurves(cam):
        if fc.data_path == "rotation_euler":
            for kp in fc.keyframe_points:
                kp.interpolation = "LINEAR"


def render_still(sc, t, path):
    sc.frame_set(F(t))
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--still", nargs="*", type=float, default=[])
    ap.add_argument("--save", default=None)
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--samples", type=int, default=16)
    ap.add_argument("--outdir", default=os.path.join(HERE, "out", "test"))
    a = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
    rx, ry = (int(v) for v in a.res.split("x"))
    t0 = time.time()
    sc = build((rx, ry), a.samples)
    print(f"build {time.time() - t0:.1f}s")
    if a.save:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(a.save))
    os.makedirs(a.outdir, exist_ok=True)
    for t in a.still:
        t1 = time.time()
        render_still(sc, t, os.path.join(a.outdir, f"still_{t:05.2f}.png"))
        print(f"still t={t} {time.time() - t1:.1f}s", flush=True)
