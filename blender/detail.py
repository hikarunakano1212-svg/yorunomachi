"""作り込み版アセット(東京・八重洲版)

- 車: 横から見た輪郭を押し出して車体を作り、タイヤハウスをブーリアンでくり抜く。
  キャビンはガラス+ワイヤーフレーム(ピラー・窓枠)、細部(グリル・ドア線・ミラー・灯火類)を追加。
- 環境遮蔽(AO)を Cycles で頂点カラーに焼き込む → ゲーム側で陰影・汚れとして使う。
- 車種: セダン/パトカー/JPN TAXI 型タクシー/軽ハイトワゴン/ハイエース型バン/2t トラック/都営バス風
- 信号機・街路樹・街灯・照準器付き拳銃・人物(スーツ姿)
"""
import math

import bpy
import bmesh
from mathutils import Vector

import build_assets as B

mat, box, cylinder, sphere, join, root, link = B.mat, B.box, B.cylinder, B.sphere, B.join, B.root, B.link


def set_active(o):
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o


def apply_mods(o):
    set_active(o)
    for m in list(o.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)


def extrude_profile(name, prof, width, material, top_scale=1.0, split_z=None, bevel=0.05):
    """YZ 平面の輪郭(反時計回り)を X 方向に押し出す。split_z より上の頂点は top_scale 倍に絞る。"""
    bm = bmesh.new()
    L = [bm.verts.new((-width / 2, y, z)) for y, z in prof]
    R = [bm.verts.new((width / 2, y, z)) for y, z in prof]
    bm.faces.new(L[::-1])
    bm.faces.new(R)
    n = len(prof)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new([L[i], L[j], R[j], R[i]])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if top_scale != 1.0 and split_z is not None:
        zmax = max(z for _, z in prof)
        for v in bm.verts:
            if v.co.z > split_z + 1e-4:
                k = (v.co.z - split_z) / max(1e-4, zmax - split_z)
                v.co.x *= 1 - (1 - top_scale) * k
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = link(bpy.data.objects.new(name, me))
    me.materials.append(material)
    if bevel:
        m = o.modifiers.new("Bevel", "BEVEL")
        m.width = bevel
        m.segments = 3
        m.limit_method = "ANGLE"
        m.angle_limit = math.radians(25)
        m.harden_normals = False
    for p in me.polygons:
        p.use_smooth = True
    return o


def boolean_cut(o, cutters):
    for c in cutters:
        m = o.modifiers.new("Cut", "BOOLEAN")
        m.operation = "DIFFERENCE"
        m.solver = "EXACT"
        m.object = c
    apply_mods(o)
    for c in cutters:
        bpy.data.objects.remove(c)


def subdivide_for_ao(o, cuts=1):
    """頂点カラーの AO がなめらかになるよう面を細かくする"""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    long_edges = [e for e in bm.edges if e.calc_length() > 0.35]
    if long_edges:
        bmesh.ops.subdivide_edges(bm, edges=long_edges, cuts=cuts, use_grid_fill=True)
    bm.to_mesh(o.data)
    bm.free()


def bake_ao(objs, samples=48):
    """選んだオブジェクトの AO を頂点カラー 'AO' に焼き込む(地面も遮蔽物として一時的に置く)"""
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    world = bpy.data.worlds.new("AOW")
    world.use_nodes = True
    scene.world = world
    ground = box("AO_Ground", (40, 40, 0.1), (0, 0, -0.05), mat("AOGround", (0.5, 0.5, 0.5)))
    bpy.ops.object.select_all(action="DESELECT")
    meshes = [o for o in objs if o.type == "MESH"]
    for o in meshes:
        if "AO" not in o.data.color_attributes:
            o.data.color_attributes.new("AO", "FLOAT_COLOR", "POINT")
        o.data.color_attributes.active_color = o.data.color_attributes["AO"]
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    scene.render.bake.target = "VERTEX_COLORS"
    bpy.ops.object.bake(type="AO", target="VERTEX_COLORS")
    bpy.data.objects.remove(ground)


def export(name, preview_cam=None, target=(0, 0, 0.8)):
    B.OUT  # noqa
    import os
    path = os.path.join(B.OUT, f"{name}.glb")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_apply=True, export_yup=True,
                              export_vertex_color="ACTIVE", export_all_vertex_colors=False,
                              export_lights=False, export_cameras=False)
    print(f"  -> {name}.glb ({os.path.getsize(path) / 1024:.0f} KB)")
    if preview_cam:
        B.preview(name, preview_cam, target)


# ---------------------------------------------------------------- 車両
VEHICLES = {
    # lower: 車体下半分の輪郭(y,z)  cabin: キャビン輪郭  wheels: (前輪y, 後輪y, 半径)
    "sedan": dict(L=4.9, W=1.8, lower=[(2.45, .3), (2.48, .55), (2.4, .74), (1.25, .87), (.82, .92), (-1.55, .93), (-2.28, .95), (-2.46, .8), (-2.47, .5), (-2.4, .3)],
                  cabin=[(.85, .92), (.08, 1.43), (-.98, 1.44), (-1.62, .94)], top=.82, wheels=(1.45, -1.42, .33)),
    "taxi": dict(L=4.4, W=1.7, lower=[(2.2, .3), (2.23, .6), (2.12, .83), (1.42, .96), (-2.1, .99), (-2.21, .82), (-2.23, .45), (-2.15, .3)],
                 cabin=[(1.38, .96), (.62, 1.7), (-1.92, 1.71), (-2.12, 1.0)], top=.9, wheels=(1.36, -1.35, .3)),
    "kei": dict(L=3.4, W=1.48, lower=[(1.7, .28), (1.72, .6), (1.58, .9), (1.18, 1.0), (-1.7, 1.01), (-1.72, .5), (-1.68, .28)],
                cabin=[(1.14, 1.0), (.58, 1.72), (-1.64, 1.74), (-1.71, 1.02)], top=.93, wheels=(1.17, -1.2, .28)),
    "van": dict(L=4.7, W=1.7, lower=[(2.35, .38), (2.38, .98), (-2.35, .98), (-2.37, .38)],
                cabin=[(2.33, .98), (1.98, 1.96), (-2.33, 1.98), (-2.36, .98)], top=.95, wheels=(1.45, -1.5, .32)),
    "truck": dict(L=6.2, W=1.9, lower=[(3.1, .6), (3.12, 1.2), (1.35, 1.2), (1.35, .6)],
                  cabin=[(3.1, 1.2), (2.95, 2.3), (1.42, 2.3), (1.35, 1.2)], top=.95, wheels=(2.3, -1.85, .38)),
    "bus": dict(L=10.5, W=2.5, lower=[(5.25, .38), (5.28, 1.2), (-5.25, 1.2), (-5.27, .38)],
                cabin=[(5.25, 1.2), (5.18, 2.98), (-5.2, 3.0), (-5.25, 1.2)], top=.97, wheels=(2.9, -2.6, .5)),
}


def build_vehicle(kind, police=False):
    B.reset()
    s = VEHICLES["sedan" if police else kind]
    L, W = s["L"], s["W"]
    paint = mat("Paint", (0.8, 0.8, 0.8), rough=0.22, metal=0.5)
    glass = mat("Glass", (0.02, 0.025, 0.03), rough=0.04, metal=0.8)
    black = mat("BlackTrim", (0.02, 0.02, 0.022), rough=0.55)
    chrome = mat("Chrome", (0.8, 0.8, 0.82), rough=0.12, metal=1.0)
    rubber = mat("Rubber", (0.025, 0.025, 0.025), rough=0.9)
    rim = mat("Rim", (0.55, 0.56, 0.58), rough=0.3, metal=0.9)
    head = mat("HeadLight", (1, 1, .95), emit=(1, .95, .85), emit_strength=3)
    tail = mat("TailLight", (.5, .02, .02), emit=(1, .04, .04), emit_strength=2)
    plate = mat("Plate", (.95, .95, .9), rough=.5)
    car = root("Car")
    parts = []

    # 車体(下)
    body = extrude_profile("Body", s["lower"], W, paint, bevel=0.06)
    fy, ry, wr = s["wheels"]
    cutters = []
    for y in (fy, ry):
        c = cylinder("arch", wr + 0.07, W + 0.4, (0, y, wr), paint, verts=32, rot=(0, math.radians(90), 0))
        cutters.append(c)
    apply_mods(body)
    boolean_cut(body, cutters)
    subdivide_for_ao(body)
    parts.append(body)

    # キャビン(ガラス)と窓枠・ピラー
    split = s["cabin"][0][1]
    cab = extrude_profile("Cabin", s["cabin"], W - 0.06, glass, s["top"], split, bevel=0.04)
    apply_mods(cab)
    # 屋根面は塗装に(パトカーは白)
    roof_mat = mat("PoliceWhite", (.93, .93, .93), rough=.25, metal=.3) if police else paint
    cab.data.materials.append(roof_mat)
    for p in cab.data.polygons:
        if p.normal.z > 0.75:
            p.material_index = 1
    frame = extrude_profile("Frame", s["cabin"], W - 0.05, black, s["top"], split, bevel=0)
    bm = bmesh.new(); bm.from_mesh(frame.data)
    # Bピラー用に中央で切る
    ys = [y for y, _ in s["cabin"]]
    mid = (max(ys) + min(ys)) / 2 - 0.1
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, mid, 0), plane_no=(0, 1, 0))
    if kind == "bus":
        for k in range(1, 6):
            bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=(0, -4.5 + k * 1.6, 0), plane_no=(0, 1, 0))
    bm.to_mesh(frame.data); bm.free()
    wf = frame.modifiers.new("WF", "WIREFRAME")
    wf.thickness = 0.07 if kind != "bus" else 0.12
    wf.use_even_offset = True
    apply_mods(frame)
    frame.data.materials.clear(); frame.data.materials.append(black if kind != "sedan" or police else paint)
    parts += [cab, frame]

    front, rear = max(y for y, _ in s["lower"]), min(y for y, _ in s["lower"])
    belt = s["lower"][2][1] if kind not in ("van", "truck", "bus") else s["lower"][1][1] - 0.2
    # 灯火類
    hz = belt - 0.1 if kind in ("sedan", "taxi", "kei") else 0.75
    parts.append(join([box("HL", (0.38, 0.1, 0.13), (sx * (W / 2 - 0.26), front - 0.04, hz), head, bevel=0.03) for sx in (-1, 1)], "Light_Head"))
    tz = s["lower"][-3][1] - 0.05 if kind in ("sedan", "taxi", "kei") else 0.95
    parts.append(join([box("TL", (0.34 if kind != "bus" else 0.2, 0.08, 0.14 if kind != "bus" else 0.4), (sx * (W / 2 - 0.22), rear + 0.02, tz), tail, bevel=0.02) for sx in (-1, 1)], "Light_Tail"))
    # グリル・バンパー・ナンバー・ミラー・ドアハンドル
    parts.append(box("Grille", (W * 0.42, 0.06, 0.16), (0, front + 0.005, hz - 0.12), black, bevel=0.02))
    parts.append(box("BumperF", (W + 0.02, 0.16, 0.2), (0, front - 0.03, 0.36 if kind not in ("truck", "bus") else 0.55), black, bevel=0.05))
    parts.append(box("BumperR", (W + 0.02, 0.16, 0.2), (0, rear + 0.03, 0.36 if kind not in ("truck", "bus") else 0.55), black, bevel=0.05))
    parts.append(box("PlateF", (0.33, 0.02, 0.165), (0, front + 0.08, 0.45 if kind not in ("truck", "bus") else 0.7), plate))
    parts.append(box("PlateR", (0.33, 0.02, 0.165), (0, rear - 0.08, 0.55 if kind not in ("truck", "bus") else 0.8), plate))
    mirror_y = s["cabin"][0][0] - 0.15
    for sx in (-1, 1):
        parts.append(box("Mirror", (0.2, 0.1, 0.12), (sx * (W / 2 + 0.08), mirror_y, split + 0.12), black, bevel=0.03))
    if kind in ("sedan", "taxi", "kei"):
        for sx in (-1, 1):
            for yy in (mid + 0.55, mid - 0.45):
                parts.append(box("Handle", (0.02, 0.14, 0.03), (sx * (W / 2 + 0.005), yy, belt - 0.08), chrome))
            # ドアの継ぎ目
            for yy in (s["cabin"][0][0] + 0.02, mid, s["cabin"][-1][0] + 0.1):
                parts.append(box("DoorLine", (0.01, 0.012, belt - 0.35), (sx * (W / 2 + 0.002), yy, (belt + 0.35) / 2 + 0.05), black))

    # 車種ごとの追加
    if kind == "taxi":
        parts.append(box("Light_Andon", (0.36, 0.14, 0.2), (0, -0.2, s["cabin"][1][1] + 0.1),
                         mat("Andon", (1, .75, .2), emit=(1, .72, .25), emit_strength=2.5), bevel=0.05))
    if police:
        for sx in (-1, 1):
            parts.append(box("DoorWhite", (0.012, 2.1, belt - 0.4), (sx * (W / 2 + 0.004), mid + 0.1, (belt + 0.4) / 2), roof_mat))
        parts.append(box("BarBase", (1.2, 0.3, 0.07), (0, -0.4, 1.47), black, bevel=0.02))
        parts.append(box("Light_Siren", (1.12, 0.26, 0.12), (0, -0.4, 1.56),
                         mat("Siren", (.9, .02, .02), emit=(1, 0, 0), emit_strength=4, rough=.2), bevel=0.05))
    if kind == "truck":
        cargo = mat("Cargo", (.82, .84, .86), rough=.35, metal=.6)
        parts.append(box("CargoBox", (W + 0.1, 4.3, 2.3), (0, -0.95, 1.35 + 1.15), cargo, bevel=0.04))
        for k in range(12):
            parts.append(box("Rib", (W + 0.14, 0.04, 2.3), (0, -3.0 + k * 0.37, 2.5), cargo))
        parts.append(box("Chassis", (0.9, 6.0, 0.25), (0, 0, 0.62), black))
    if kind == "bus":
        stripe = mat("Stripe", (.1, .45, .25), rough=.3, metal=.2)
        for sx in (-1, 1):
            parts.append(box("Stripe", (0.012, L - 0.3, 0.28), (sx * (W / 2 + 0.005), 0, 1.0), stripe))
        parts.append(box("Light_Dest", (1.6, 0.05, 0.28), (0, front + 0.01, 2.7), mat("Dest", (1, .6, .1), emit=(1, .55, .1), emit_strength=3)))
    if kind == "van":
        parts.append(box("SlideRail", (0.02, 2.2, 0.04), (W / 2 + 0.01, -0.4, 1.6), black))

    for p in parts:
        p.parent = car

    # タイヤ(回転軸に原点を置いた空オブジェクトの子)
    tw = 0.22 if kind not in ("truck", "bus") else 0.3
    for tag, sx, y in [("FL", -1, fy), ("FR", 1, fy), ("RL", -1, ry), ("RR", 1, ry)]:
        piv = root(f"Wheel_{tag}")
        piv.location = (sx * (W / 2 - tw / 2 - 0.02), y, wr)
        piv.parent = car
        t = cylinder(f"Tire_{tag}", wr, tw, (0, 0, 0), rubber, verts=28, rot=(0, math.radians(90), 0))
        bv = t.modifiers.new("B", "BEVEL"); bv.width = 0.04; bv.segments = 3
        apply_mods(t)
        h = cylinder(f"Rim_{tag}", wr * 0.62, tw + 0.012, (0, 0, 0), rim, verts=20, rot=(0, math.radians(90), 0))
        spokes = [box("Spoke", (tw + 0.02, wr * 1.1, 0.045), (0, 0, 0), rim) for _ in range(5)]
        for k, sp in enumerate(spokes):
            sp.rotation_euler = (math.radians(72 * k), 0, 0)
        w = join([t, h] + spokes, f"WheelMesh_{tag}")
        w.parent = piv

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    bake_ao(meshes)
    name = "car_police" if police else f"car_{kind}"
    export(name, (L * 1.1 + 2, L * 0.9 + 3, 2.5 + s["cabin"][1][1] * 0.6), (0, 0, 0.8))


# ---------------------------------------------------------------- 人物
def build_person():
    B.reset()
    r = root("Person")
    skin = mat("Skin", (0.8, 0.62, 0.5), rough=0.55)
    shirt = mat("Shirt", (0.8, 0.8, 0.8), rough=0.75)
    pants = mat("Pants", (0.15, 0.17, 0.22), rough=0.8)
    hair = mat("Hair", (0.03, 0.025, 0.02), rough=0.5)
    shoe = mat("Shoe", (0.03, 0.03, 0.03), rough=0.35, metal=0.2)
    white = mat("Collar", (0.9, 0.9, 0.88), rough=0.6)

    def capsule(name, r0, r1, length, material, loc):
        o = cylinder(name, 1, length, loc, material, verts=12)
        bm = bmesh.new(); bm.from_mesh(o.data)
        for v in bm.verts:
            t = (v.co.z + length / 2) / length
            rr = r1 + (r0 - r1) * t
            v.co.x *= rr; v.co.y *= rr * 0.9
        bm.to_mesh(o.data); bm.free()
        bv = o.modifiers.new("B", "BEVEL"); bv.width = min(r0, r1) * 0.8; bv.segments = 3
        apply_mods(o)
        for p in o.data.polygons:
            p.use_smooth = True
        return o

    torso = capsule("TorsoA", 0.2, 0.17, 0.62, shirt, (0, 0, 1.21))
    torso.scale = (1.1, 0.72, 1)
    collar = box("Collar", (0.14, 0.04, 0.16), (0, 0.12, 1.43), white)
    tie = box("Tie", (0.05, 0.02, 0.36), (0, 0.135, 1.3), mat("Tie", (0.35, 0.05, 0.08), rough=.5))
    hips = capsule("HipsA", 0.17, 0.16, 0.2, pants, (0, 0, 0.9))
    hips.scale = (1.05, 0.8, 1)
    j = join([torso, collar, tie, hips], "Torso")
    j.parent = r

    hp = root("HeadPivot"); hp.location = (0, 0, 1.52); hp.parent = r
    neck = capsule("Neck", 0.055, 0.05, 0.1, skin, (0, 0, 0.03))
    head = sphere("Head", 0.115, (0, 0.005, 0.17), skin, scale=(0.92, 1.0, 1.12), seg=20)
    hr = sphere("HairCap", 0.122, (0, -0.012, 0.2), hair, scale=(0.95, 1.05, 1.02), seg=20)
    nose = box("Nose", (0.025, 0.03, 0.04), (0, 0.11, 0.16), skin, bevel=0.01)
    join([neck, head, hr, nose], "HeadMesh").parent = hp

    for side, sx in (("L", -1), ("R", 1)):
        arm = root(f"Arm{side}"); arm.location = (sx * 0.24, 0, 1.44); arm.parent = r
        up = capsule("Up", 0.06, 0.05, 0.32, shirt, (0, 0, -0.16))
        fo = capsule("Fo", 0.05, 0.04, 0.28, shirt, (0, 0, -0.45))
        hand = sphere("Hand", 0.045, (0, 0.005, -0.63), skin, scale=(0.8, 1, 1.2))
        join([up, fo, hand], f"ArmMesh{side}").parent = arm
        leg = root(f"Leg{side}"); leg.location = (sx * 0.095, 0, 0.86); leg.parent = r
        th = capsule("Th", 0.085, 0.065, 0.44, pants, (0, 0, -0.22))
        sh = capsule("Sh", 0.062, 0.05, 0.38, pants, (0, 0, -0.62))
        ft = box("Foot", (0.1, 0.26, 0.07), (0, 0.05, -0.83), shoe, bevel=0.03)
        join([th, sh, ft], f"LegMesh{side}").parent = leg

    bake_ao([o for o in bpy.data.objects if o.type == "MESH"], samples=24)
    export("person", (1.6, 2.4, 1.5), (0, 0, 0.95))


# ---------------------------------------------------------------- 拳銃(照準器付き)
def build_pistol():
    B.reset()
    r = root("Pistol")
    steel = mat("GunSteel", (0.06, 0.06, 0.065), rough=0.3, metal=0.9)
    frame_m = mat("GunFrame", (0.035, 0.035, 0.038), rough=0.6, metal=0.2)
    glove = mat("Glove", (0.05, 0.05, 0.055), rough=0.85)
    sleeve = mat("Sleeve", (0.09, 0.09, 0.12), rough=0.9)
    dot = mat("SightDot", (1, 1, 1), emit=(0.3, 1, 0.4), emit_strength=4)
    parts = [box("Slide", (0.03, 0.19, 0.032), (0, 0.02, 0.055), steel, bevel=0.004)]
    for k in range(7):  # 後部セレーション
        parts.append(box("Serr", (0.032, 0.003, 0.02), (0, -0.06 + k * 0.006, 0.058), frame_m))
    parts.append(box("Port", (0.004, 0.045, 0.014), (0.015, 0.03, 0.062), frame_m))
    parts.append(cylinder("Barrel", 0.0075, 0.02, (0, 0.117, 0.052), frame_m, verts=12, rot=(math.radians(90), 0, 0)))
    parts.append(box("FrontSight", (0.005, 0.01, 0.008), (0, 0.105, 0.0745), steel))
    parts.append(box("FrontDot", (0.0025, 0.002, 0.0025), (0, 0.1, 0.0755), dot))
    for sx in (-1, 1):
        parts.append(box("RearSight", (0.009, 0.01, 0.009), (sx * 0.0075, -0.068, 0.0755), steel))
        parts.append(box("RearDot", (0.0025, 0.002, 0.0025), (sx * 0.0075, -0.063, 0.0765), dot))
    parts.append(box("RearBase", (0.026, 0.01, 0.004), (0, -0.068, 0.0725), steel))
    parts.append(box("Frame", (0.028, 0.15, 0.022), (0, 0.0, 0.028), frame_m, bevel=0.004))
    g = box("Grip", (0.03, 0.052, 0.115), (0, -0.05, -0.03), frame_m, bevel=0.008)
    g.rotation_euler = (math.radians(-16), 0, 0)
    parts.append(g)
    # 用心金(トリガーガード): 細いトーラス
    bpy.ops.mesh.primitive_torus_add(major_radius=0.02, minor_radius=0.0035, major_segments=20, minor_segments=6,
                                     location=(0, 0.004, 0.006), rotation=(0, math.radians(90), 0))
    tg = bpy.context.active_object
    tg.scale = (1, 1.3, 1)
    tg.data.materials.append(frame_m)
    parts.append(tg)
    parts.append(box("Trigger", (0.006, 0.006, 0.018), (0, 0.006, 0.004), steel))
    join(parts, "GunMesh").parent = r
    hand = box("Hand", (0.058, 0.08, 0.075), (0.004, -0.055, -0.02), glove, bevel=0.022, segments=3)
    thumb = box("Thumb", (0.018, 0.06, 0.02), (-0.022, -0.02, 0.02), glove, bevel=0.008)
    arm = box("Forearm", (0.075, 0.3, 0.075), (0.015, -0.24, -0.05), sleeve, bevel=0.03, segments=3)
    join([hand, thumb, arm], "HandMesh").parent = r
    export("pistol")


# ---------------------------------------------------------------- 街の設備
def build_signal():
    """日本の信号機(横型3灯)。灯器は Lamp_G/Y/R としてゲーム側で点灯制御"""
    B.reset()
    r = root("Signal")
    grey = mat("SigPole", (0.55, 0.56, 0.55), rough=0.5, metal=0.5)
    dark = mat("SigBody", (0.12, 0.12, 0.12), rough=0.5, metal=0.3)
    # 腕は +Y 方向へ伸び、灯器は腕に沿って横に3つ並び +X(車の来る方)を向く
    parts = [cylinder("Pole", 0.09, 5.6, (0, 0, 2.8), grey, verts=14),
             cylinder("Arm", 0.06, 3.4, (0, 1.65, 5.3), grey, verts=10, rot=(math.radians(90), 0, 0)),
             box("Housing", (0.3, 1.3, 0.42), (0, 2.9, 5.3), dark, bevel=0.05)]
    for k in range(3):
        parts.append(box("Visor", (0.28, 0.36, 0.03), (0.28, 2.5 + k * 0.4, 5.52), dark))
    parts.append(box("PedBox", (0.26, 0.34, 0.62), (0.2, 0, 2.6), dark, bevel=0.03))
    join(parts, "SignalMesh").parent = r
    for k, (n, c) in enumerate([("Lamp_G", (0.1, 1, 0.7)), ("Lamp_Y", (1, 0.7, 0.05)), ("Lamp_R", (1, 0.08, 0.05))]):
        m = cylinder(n, 0.13, 0.03, (0.16, 2.5 + k * 0.4, 5.3), mat(n, c, emit=c, emit_strength=1), verts=18, rot=(0, math.radians(90), 0))
        m.parent = r
    for n, z, c in [("Ped_R", 2.74, (1, 0.1, 0.05)), ("Ped_G", 2.46, (0.1, 1, 0.7))]:
        m = box(n, (0.02, 0.24, 0.22), (0.335, 0, z), mat(n, c, emit=c, emit_strength=1))
        m.parent = r
    bake_ao([o for o in bpy.data.objects if o.type == "MESH"], samples=16)
    export("signal", (4, 7, 5), (0, 1.5, 4))


def build_tree():
    B.reset()
    r = root("Tree")
    bark = mat("Bark", (0.2, 0.15, 0.11), rough=0.9)
    leaf = mat("Leaf", (0.12, 0.2, 0.1), rough=0.8)
    trunk = cylinder("Trunk", 0.16, 3.6, (0, 0, 1.8), bark, verts=10)
    bm = bmesh.new(); bm.from_mesh(trunk.data)
    for v in bm.verts:
        k = (v.co.z + 1.8) / 3.6
        v.co.x *= 1.25 - 0.5 * k; v.co.y *= 1.25 - 0.5 * k
    bm.to_mesh(trunk.data); bm.free()
    parts = [trunk]
    import random
    rnd = random.Random(3)
    for k in range(4):  # 枝
        a = k * 1.6
        b = cylinder("Branch", 0.06, 1.8, (math.cos(a) * 0.5, math.sin(a) * 0.5, 3.6), bark, verts=6,
                     rot=(math.cos(a) * 0.7, math.sin(a) * -0.7, 0))
        parts.append(b)
    j = join(parts, "TrunkMesh"); j.parent = r
    tex = bpy.data.textures.new("Cloud", "CLOUDS"); tex.noise_scale = 0.5
    leaves = []
    for k in range(9):  # 葉の塊(ノイズで凹凸を付ける)
        a = rnd.uniform(0, 6.28); d = rnd.uniform(0.3, 1.3)
        s = sphere("Leaves", rnd.uniform(0.9, 1.4), (math.cos(a) * d, math.sin(a) * d, rnd.uniform(3.8, 5.6)), leaf, seg=14)
        dm = s.modifiers.new("D", "DISPLACE"); dm.texture = tex; dm.strength = 0.5
        apply_mods(s)
        leaves.append(s)
    lj = join(leaves, "LeafMesh"); lj.parent = r
    for p in lj.data.polygons:
        p.use_smooth = False
    bake_ao([j, lj], samples=24)
    export("tree", (7, 9, 5), (0, 0, 3.5))


def build_lamp():
    B.reset()
    r = root("Lamp")
    grey = mat("LampPole", (0.6, 0.62, 0.64), rough=0.35, metal=0.8)
    led = mat("Light_LED", (1, 0.95, 0.85), emit=(1, 0.9, 0.75), emit_strength=6)
    parts = [cylinder("Pole", 0.1, 9.0, (0, 0, 4.5), grey, verts=14),
             cylinder("Base", 0.18, 0.8, (0, 0, 0.4), grey, verts=14)]
    arm = cylinder("Arm", 0.05, 2.4, (0, 1.1, 8.85), grey, verts=8, rot=(math.radians(84), 0, 0))
    head = box("Head", (0.35, 0.8, 0.12), (0, 2.25, 8.95), grey, bevel=0.04)
    parts += [arm, head]
    join(parts, "LampMesh").parent = r
    l = box("Light_LED", (0.28, 0.7, 0.02), (0, 2.25, 8.88), led)
    l.parent = r
    export("lamp", (5, 7, 7), (0, 1, 6))


def main():
    for k in ("sedan", "taxi", "kei", "van", "truck", "bus"):
        print("車両:", k)
        build_vehicle(k)
    build_vehicle("sedan", police=True)

    build_pistol()
    build_signal()
    build_tree()
    build_lamp()
