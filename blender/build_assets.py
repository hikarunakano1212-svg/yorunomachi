"""夜ノ街 — Blender(bpy) アセット生成スクリプト

使い方:
    pip install bpy==4.5.14
    python blender/build_assets.py            # assets/models/*.glb を生成
    python blender/build_assets.py --preview  # blender/previews/*.png も出力

Blender 本体から実行する場合:
    blender -b -P blender/build_assets.py

モデルは Blender の +Y 方向を「前」として作る。glTF 書き出し時に
Y-up へ変換されるので、three.js 側では -Z が前になる。
部位ごとにオブジェクト名を付けておき、three.js 側で名前から参照する
(Body=塗装色を差し替え, Wheel_*=回転, Light_*=発光 など)。
"""

import math
import os
import sys

import bpy  # bpy を先に import しないと bmesh が見つからない
import bmesh
from mathutils import Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "models")
PREVIEW = os.path.join(ROOT, "blender", "previews")


# ---------------------------------------------------------------- 基本ユーティリティ

_materials = {}


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _materials.clear()  # ファイルを初期化するとマテリアルも消えるのでキャッシュも捨てる


def mat(name, color, rough=0.5, metal=0.0, emit=None, emit_strength=0.0, alpha=1.0):
    if name in _materials:
        return _materials[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1.0)
        b.inputs["Emission Strength"].default_value = emit_strength
    if alpha < 1.0:
        b.inputs["Alpha"].default_value = alpha
        m.blend_method = "BLEND"
    _materials[name] = m
    return m


def link(obj):
    bpy.context.collection.objects.link(obj)
    return obj


def box(name, size, loc, material, bevel=0.0, segments=2, parent=None):
    """面取り付きの箱。size は (幅X, 奥行Y, 高さZ)。"""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= size[0]
        v.co.y *= size[1]
        v.co.z *= size[2]
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=bm.edges[:] + bm.verts[:], offset=bevel,
                        segments=segments, affect="EDGES", profile=0.5)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = link(bpy.data.objects.new(name, me))
    obj.location = loc
    me.materials.append(material)
    if bevel > 0:
        for p in me.polygons:
            p.use_smooth = True
    if parent:
        obj.parent = parent
    return obj


def taper_box(name, bottom, top, height, loc, material, top_offset_y=0.0, bevel=0.03):
    """上面が絞られた箱(車のキャビン用)。bottom/top は (幅, 奥行)。"""
    bm = bmesh.new()
    bx, by = bottom[0] / 2, bottom[1] / 2
    tx, ty = top[0] / 2, top[1] / 2
    vs = [
        bm.verts.new((-bx, -by, 0)), bm.verts.new((bx, -by, 0)),
        bm.verts.new((bx, by, 0)), bm.verts.new((-bx, by, 0)),
        bm.verts.new((-tx, -ty + top_offset_y, height)), bm.verts.new((tx, -ty + top_offset_y, height)),
        bm.verts.new((tx, ty + top_offset_y, height)), bm.verts.new((-tx, ty + top_offset_y, height)),
    ]
    for f in [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]:
        bm.faces.new([vs[i] for i in f])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if bevel > 0:
        bmesh.ops.bevel(bm, geom=bm.edges[:], offset=bevel, segments=2, affect="EDGES", profile=0.5)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = link(bpy.data.objects.new(name, me))
    obj.location = loc
    me.materials.append(material)
    for p in me.polygons:
        p.use_smooth = True
    return obj


def cylinder(name, radius, depth, loc, material, verts=16, rot=(0, 0, 0), parent=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=verts,
                          radius1=radius, radius2=radius, depth=depth)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = link(bpy.data.objects.new(name, me))
    obj.location = loc
    obj.rotation_euler = rot
    me.materials.append(material)
    for p in me.polygons:
        p.use_smooth = abs(p.normal.z) < 0.5
    if parent:
        obj.parent = parent
    return obj


def sphere(name, radius, loc, material, scale=(1, 1, 1), seg=16):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=seg // 2, radius=radius)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = link(bpy.data.objects.new(name, me))
    obj.location = loc
    obj.scale = scale
    me.materials.append(material)
    for p in me.polygons:
        p.use_smooth = True
    return obj


def join(objs, name):
    """同じ役割の部品を1つのメッシュにまとめる(描画コール削減)。"""
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    bpy.ops.object.join()
    o = bpy.context.view_layer.objects.active
    o.name = name
    o.data.name = name
    return o


def root(name):
    e = link(bpy.data.objects.new(name, None))
    return e


def export(name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{name}.glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_apply=True,
                              export_yup=True, export_lights=False, export_cameras=False)
    print(f"  -> {os.path.relpath(path, ROOT)} ({os.path.getsize(path) / 1024:.0f} KB)")


def preview(name, cam_loc, target=(0, 0, 0.7)):
    """確認用に EEVEE でサムネイルを描画する(--preview 指定時のみ)。"""
    if "--preview" not in sys.argv:
        return
    os.makedirs(PREVIEW, exist_ok=True)
    scene = bpy.context.scene
    cam = bpy.data.objects.new("PreviewCam", bpy.data.cameras.new("PreviewCam"))
    link(cam)
    cam.location = cam_loc
    d = Vector(target) - Vector(cam_loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(30))
    link(sun)
    world = bpy.data.worlds.new("W")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.35, 0.38, 0.45, 1)
    scene.world = world
    scene.render.engine = "CYCLES"  # GPU/EGL の無い環境でも動く
    scene.cycles.device = "CPU"
    scene.cycles.samples = 24
    scene.render.resolution_x = 640
    scene.render.resolution_y = 400
    scene.render.filepath = os.path.join(PREVIEW, f"{name}.png")
    bpy.ops.render.render(write_still=True)


# ---------------------------------------------------------------- 共通マテリアル

def common():
    return dict(
        paint=mat("Paint", (0.8, 0.8, 0.8), rough=0.25, metal=0.4),
        glass=mat("Glass", (0.05, 0.07, 0.09), rough=0.05, metal=0.6),
        rubber=mat("Rubber", (0.03, 0.03, 0.03), rough=0.9),
        rim=mat("Rim", (0.6, 0.6, 0.62), rough=0.3, metal=0.9),
        chrome=mat("Chrome", (0.8, 0.8, 0.8), rough=0.15, metal=1.0),
        black=mat("BlackPlastic", (0.02, 0.02, 0.02), rough=0.6),
        head=mat("HeadLight", (1, 1, 0.95), emit=(1, 0.95, 0.85), emit_strength=3),
        tail=mat("TailLight", (0.6, 0.02, 0.02), emit=(1, 0.05, 0.05), emit_strength=2),
        plate=mat("Plate", (0.95, 0.95, 0.9), rough=0.5),
    )


# ---------------------------------------------------------------- 車両

def wheels(M, r, parent, x, y_front, y_rear, width=0.18):
    for tag, px, py in [("FL", -x, y_front), ("FR", x, y_front), ("RL", -x, y_rear), ("RR", x, y_rear)]:
        # ホイール原点を回転軸に置く(three.js 側で rotation.x を回す)
        pivot = root(f"Wheel_{tag}")
        pivot.location = (px, py, r)
        pivot.parent = parent
        tire = cylinder(f"Tire_{tag}", r, width, (0, 0, 0), M["rubber"], verts=20,
                        rot=(0, math.radians(90), 0))
        hub = cylinder(f"Hub_{tag}", r * 0.62, width + 0.01, (0, 0, 0), M["rim"], verts=12,
                       rot=(0, math.radians(90), 0))
        w = join([tire, hub], f"WheelMesh_{tag}")
        w.parent = pivot


def build_car(kind):
    """kind: kei(軽自動車) / taxi(タクシー) / police(パトカー)"""
    reset()
    M = common()
    car = root("Car")

    if kind == "kei":
        L, W, H0, H1 = 3.4, 1.48, 0.95, 0.72
        body = box("Body", (W, L, H0 - 0.28), (0, 0, 0.28 + (H0 - 0.28) / 2), M["paint"], bevel=0.08)
        cab = taper_box("Body_Cabin", (W - 0.06, L * 0.62), (W - 0.2, L * 0.52), H1,
                        (0, -0.18, H0), M["paint"], top_offset_y=-0.05, bevel=0.06)
        body = join([body, cab], "Body")
        glass = taper_box("Glass", (W - 0.02, L * 0.6), (W - 0.24, L * 0.49), H1 * 0.78,
                          (0, -0.18, H0 + 0.02), M["glass"], top_offset_y=-0.05, bevel=0.02)
        wr, wx, wf, wb = 0.29, W / 2 - 0.12, L / 2 - 0.55, -L / 2 + 0.5
        light_y, light_z = L / 2 + 0.01, 0.72
    else:
        L, W, H0, H1 = 4.7, 1.72, 0.9, 0.62
        body = box("Body", (W, L, H0 - 0.3), (0, 0, 0.3 + (H0 - 0.3) / 2), M["paint"], bevel=0.1)
        hood = box("Body_Hood", (W - 0.1, 1.2, 0.08), (0, L / 2 - 0.75, H0 - 0.01), M["paint"], bevel=0.03)
        cab = taper_box("Body_Cabin", (W - 0.08, L * 0.5), (W - 0.28, L * 0.36), H1,
                        (0, -0.25, H0), M["paint"], top_offset_y=-0.08, bevel=0.06)
        body = join([body, hood, cab], "Body")
        glass = taper_box("Glass", (W - 0.04, L * 0.48), (W - 0.3, L * 0.34), H1 * 0.8,
                          (0, -0.25, H0 + 0.02), M["glass"], top_offset_y=-0.08, bevel=0.02)
        wr, wx, wf, wb = 0.32, W / 2 - 0.14, L / 2 - 0.85, -L / 2 + 0.85
        light_y, light_z = L / 2 + 0.01, 0.7

    body.parent = car
    glass.parent = car

    # バンパー・ライト・ナンバー
    parts = [
        box("BumperF", (W + 0.02, 0.14, 0.2), (0, L / 2, 0.36), M["black"], bevel=0.04),
        box("BumperR", (W + 0.02, 0.14, 0.2), (0, -L / 2, 0.36), M["black"], bevel=0.04),
    ]
    trim = join(parts, "Trim")
    trim.parent = car
    heads = join([box("HL", (0.34, 0.06, 0.14), (s * (W / 2 - 0.26), light_y, light_z), M["head"], bevel=0.02)
                  for s in (-1, 1)], "Light_Head")
    heads.parent = car
    tails = join([box("TL", (0.3, 0.06, 0.12), (s * (W / 2 - 0.24), -light_y, light_z), M["tail"], bevel=0.02)
                  for s in (-1, 1)], "Light_Tail")
    tails.parent = car
    plates = join([box("PF", (0.34, 0.03, 0.17), (0, L / 2 + 0.08, 0.42), M["plate"]),
                   box("PR", (0.34, 0.03, 0.17), (0, -L / 2 - 0.08, 0.5), M["plate"])], "Plate")
    plates.parent = car
    mirrors = join([box("MI", (0.16, 0.08, 0.1), (s * (W / 2 + 0.06), 0.35 if kind == "kei" else 0.45, H0 + 0.12),
                        M["black"], bevel=0.02) for s in (-1, 1)], "Mirror")
    mirrors.parent = car

    if kind == "taxi":
        lamp = box("Light_Andon", (0.42, 0.16, 0.16), (0, -0.3, H0 + H1 + 0.08),
                   mat("Andon", (1, 0.75, 0.2), emit=(1, 0.7, 0.2), emit_strength=2.5), bevel=0.04)
        lamp.parent = car
    if kind == "police":
        white = mat("PoliceWhite", (0.92, 0.92, 0.92), rough=0.3, metal=0.3)
        # パトカーは下半分が黒、上半分(ドア上部・屋根)が白 → Body を黒にし、白パネルを重ねる
        panel = box("Body_White", (W + 0.012, L * 0.5, 0.26), (0, -0.2, H0 - 0.13), white, bevel=0.02)
        panel.parent = car
        bar = box("LightBarBase", (1.1, 0.26, 0.08), (0, -0.25, H0 + H1 + 0.04), M["black"], bevel=0.02)
        bar.parent = car
        red = box("Light_Siren", (1.0, 0.22, 0.12), (0, -0.25, H0 + H1 + 0.13),
                  mat("Siren", (0.9, 0.02, 0.02), emit=(1, 0.0, 0.0), emit_strength=4, rough=0.2), bevel=0.04)
        red.parent = car

    wheels(M, wr, car, wx, wf, wb)
    export(f"car_{kind}")
    preview(f"car_{kind}", (5.5, 6.5, 3.2), (0, 0, 0.6))


# ---------------------------------------------------------------- 街の小物

def build_vending():
    reset()
    r = root("Vending")
    body = mat("VendRed", (0.75, 0.05, 0.06), rough=0.35, metal=0.2)
    white = mat("VendPanel", (0.9, 0.95, 1.0), emit=(0.85, 0.92, 1.0), emit_strength=2.2)
    b = box("Body", (1.0, 0.75, 1.83), (0, 0, 0.915), body, bevel=0.02)
    b.parent = r
    panel = box("Light_Panel", (0.86, 0.02, 0.95), (0, 0.38, 1.2), white)
    panel.parent = r
    # ドリンク見本(色とりどりの缶)
    cans = []
    colors = [(0.9, 0.1, 0.1), (0.1, 0.4, 0.9), (0.95, 0.8, 0.1), (0.1, 0.7, 0.3), (0.95, 0.5, 0.1), (0.3, 0.2, 0.1)]
    for row in range(3):
        for i in range(6):
            c = colors[(i + row * 2) % len(colors)]
            cans.append(cylinder(f"Can{row}{i}", 0.045, 0.16, (-0.35 + i * 0.14, 0.4, 0.9 + row * 0.28),
                                 mat(f"Can{c}", c, rough=0.2, metal=0.8), verts=10))
    join(cans, "Cans").parent = r
    slot = box("Slot", (0.8, 0.06, 0.22), (0, 0.38, 0.32), mat("Slot", (0.02, 0.02, 0.02), rough=0.9))
    slot.parent = r
    export("vending")
    preview("vending", (2.5, 3.2, 1.8), (0, 0, 0.9))


def build_pole():
    reset()
    r = root("Pole")
    conc = mat("Concrete", (0.55, 0.55, 0.52), rough=0.9)
    dark = mat("PoleDark", (0.2, 0.2, 0.2), rough=0.6)
    grey = mat("Transformer", (0.45, 0.47, 0.48), rough=0.5, metal=0.4)
    stripe = mat("PoleStripe", (0.95, 0.8, 0.1), rough=0.6)
    parts = [cylinder("Shaft", 0.15, 10.0, (0, 0, 5.0), conc, verts=12)]
    parts.append(cylinder("Stripe", 0.155, 1.6, (0, 0, 1.2), stripe, verts=12))
    for z, w in [(9.3, 1.6), (8.4, 1.2)]:
        parts.append(box("Arm", (w, 0.1, 0.1), (0, 0, z), dark))
        for s in (-1, 0, 1):
            parts.append(cylinder("Insulator", 0.05, 0.12, (s * w * 0.42, 0, z + 0.1), mat("Porcelain", (0.9, 0.9, 0.85), rough=0.3), verts=8))
    parts.append(cylinder("TransformerA", 0.24, 0.8, (0.35, 0, 7.2), grey, verts=14))
    parts.append(box("SignPlate", (0.3, 0.05, 0.9), (0, 0.17, 2.6), mat("SignBlue", (0.1, 0.25, 0.6), rough=0.5)))
    j = join(parts, "PoleMesh")
    j.parent = r
    export("pole")
    preview("pole", (5, 7, 5), (0, 0, 5))


def build_lantern():
    """赤提灯"""
    reset()
    r = root("Lantern")
    paper = mat("LanternPaper", (0.9, 0.12, 0.08), emit=(1.0, 0.25, 0.1), emit_strength=2.5, rough=0.8)
    blackm = mat("LanternCap", (0.05, 0.04, 0.03), rough=0.7)
    s = sphere("Light_Lantern", 0.28, (0, 0, 0), paper, scale=(1, 1, 1.35), seg=20)
    s.parent = r
    caps = join([cylinder("CapT", 0.17, 0.06, (0, 0, 0.37), blackm, verts=16),
                 cylinder("CapB", 0.17, 0.06, (0, 0, -0.37), blackm, verts=16)], "Caps")
    caps.parent = r
    export("lantern")


def build_cone():
    reset()
    r = root("Cone")
    orange = mat("ConeOrange", (1.0, 0.3, 0.02), rough=0.6)
    white = mat("ConeWhite", (0.95, 0.95, 0.95), rough=0.4, emit=(0.6, 0.6, 0.6), emit_strength=0.3)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=0.16, radius2=0.03, depth=0.65)
    me = bpy.data.meshes.new("ConeBody")
    bm.to_mesh(me)
    bm.free()
    c = link(bpy.data.objects.new("ConeBody", me))
    c.location = (0, 0, 0.375)
    me.materials.append(orange)
    base = box("Base", (0.4, 0.4, 0.05), (0, 0, 0.025), orange)
    band = cylinder("Band", 0.105, 0.12, (0, 0, 0.42), white, verts=16)
    join([c, base, band], "ConeMesh").parent = r
    export("cone")


def build_person():
    """歩行アニメーションは three.js 側で各部位の回転として付けるので、
    関節位置を原点にした部位ごとのオブジェクトで構成する。"""
    reset()
    r = root("Person")
    skin = mat("Skin", (0.85, 0.66, 0.52), rough=0.6)
    shirt = mat("Shirt", (0.8, 0.8, 0.8), rough=0.7)       # three.js 側で色替え
    pants = mat("Pants", (0.15, 0.17, 0.22), rough=0.8)    # three.js 側で色替え
    hair = mat("Hair", (0.04, 0.03, 0.03), rough=0.6)
    shoe = mat("Shoe", (0.05, 0.05, 0.05), rough=0.5)

    torso = box("Torso", (0.42, 0.24, 0.58), (0, 0, 1.2), shirt, bevel=0.07, segments=3)
    torso.parent = r
    hips = box("Hips", (0.38, 0.22, 0.16), (0, 0, 0.9), pants, bevel=0.05)
    hips.parent = r

    head_p = root("HeadPivot")
    head_p.location = (0, 0, 1.52)
    head_p.parent = r
    h = sphere("Head", 0.13, (0, 0, 0.13), skin, scale=(1, 1.05, 1.15))
    hr = sphere("HairCap", 0.137, (0, -0.012, 0.16), hair, scale=(1.02, 1.08, 1.05))
    join([h, hr], "HeadMesh").parent = head_p

    for side, sx in (("L", -1), ("R", 1)):
        arm = root(f"Arm{side}")
        arm.location = (sx * 0.27, 0, 1.44)
        arm.parent = r
        upper = box("Upper", (0.11, 0.11, 0.34), (0, 0, -0.17), shirt, bevel=0.045, segments=2)
        fore = box("Fore", (0.09, 0.09, 0.3), (0, 0, -0.48), skin, bevel=0.04, segments=2)
        hand = sphere("Hand", 0.055, (0, 0, -0.66), skin)
        join([upper, fore, hand], f"ArmMesh{side}").parent = arm

        leg = root(f"Leg{side}")
        leg.location = (sx * 0.1, 0, 0.86)
        leg.parent = r
        thigh = box("Thigh", (0.15, 0.15, 0.44), (0, 0, -0.22), pants, bevel=0.05, segments=2)
        shin = box("Shin", (0.12, 0.12, 0.36), (0, 0, -0.62), pants, bevel=0.045, segments=2)
        foot = box("Foot", (0.12, 0.25, 0.08), (0, 0.05, -0.82), shoe, bevel=0.03)
        join([thigh, shin, foot], f"LegMesh{side}").parent = leg

    export("person")
    preview("person", (1.8, 2.6, 1.4), (0, 0, 0.95))


def build_pistol():
    """一人称視点用の拳銃(手付き)。"""
    reset()
    r = root("Pistol")
    steel = mat("GunSteel", (0.08, 0.08, 0.09), rough=0.35, metal=0.9)
    grip = mat("GunGrip", (0.05, 0.04, 0.035), rough=0.8)
    glove = mat("Glove", (0.07, 0.07, 0.08), rough=0.85)
    sleeve = mat("Sleeve", (0.12, 0.12, 0.16), rough=0.9)
    slide = box("Slide", (0.034, 0.2, 0.036), (0, 0.02, 0.05), steel, bevel=0.005)
    frame = box("Frame", (0.03, 0.15, 0.022), (0, 0.0, 0.022), steel, bevel=0.004)
    g = box("Grip", (0.032, 0.05, 0.11), (0, -0.05, -0.03), grip, bevel=0.008)
    g.rotation_euler = (math.radians(-15), 0, 0)
    muzzle = box("Muzzle", (0.012, 0.004, 0.012), (0, 0.122, 0.05), mat("Hole", (0, 0, 0), rough=1))
    sight = box("Sight", (0.006, 0.01, 0.008), (0, 0.11, 0.072), steel)
    gun = join([slide, frame, g, muzzle, sight], "GunMesh")
    gun.parent = r
    hand = box("Hand", (0.06, 0.08, 0.075), (0.004, -0.055, -0.02), glove, bevel=0.02, segments=3)
    arm = box("Forearm", (0.08, 0.3, 0.08), (0.015, -0.24, -0.05), sleeve, bevel=0.03, segments=3)
    join([hand, arm], "HandMesh").parent = r
    export("pistol")


def build_bench_and_sign():
    """鳥居(神社の入口)"""
    reset()
    r = root("Torii")
    red = mat("ToriiRed", (0.85, 0.15, 0.05), rough=0.5)
    blackm = mat("ToriiBlack", (0.03, 0.03, 0.03), rough=0.6)
    parts = [
        cylinder("PillarL", 0.22, 5.2, (-2.2, 0, 2.6), red, verts=16),
        cylinder("PillarR", 0.22, 5.2, (2.2, 0, 2.6), red, verts=16),
        box("Nuki", (5.4, 0.25, 0.3), (0, 0, 4.2), red),
        box("Kasagi", (6.6, 0.45, 0.35), (0, 0, 5.3), blackm, bevel=0.04),
        box("Shimaki", (6.0, 0.4, 0.25), (0, 0, 5.0), red),
        box("Gakuzuka", (0.3, 0.2, 0.7), (0, 0, 4.65), red),
        cylinder("BaseL", 0.3, 0.4, (-2.2, 0, 0.2), blackm, verts=16),
        cylinder("BaseR", 0.3, 0.4, (2.2, 0, 0.2), blackm, verts=16),
    ]
    join(parts, "ToriiMesh").parent = r
    export("torii")
    preview("torii", (8, 10, 4), (0, 0, 3))


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.modules.setdefault("build_assets", sys.modules[__name__])
    import detail  # 作り込み版(車・人・拳銃・信号・街路樹・街灯)
    print("夜ノ街: アセット生成開始")
    build_vending()
    build_lantern()
    build_cone()
    detail.main()
    import person  # 骨格・アニメーション付きの人物
    person.build(False)
    person.build(True)
    print("完了")
