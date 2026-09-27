"""人物モデル(骨格・歩行アニメーション付き)

    python blender/person.py        # assets/models/person_m.glb, person_f.glb

- 体: スキンモディファイアで骨格線に太さを与え、細分化してなめらかな人体にする
- 骨格: スキンモディファイアの「アーマチュア作成」で骨とウェイトを自動生成し、部位名に付け替える
- 服: 頂点の位置で部位を判定してマテリアルを分ける(ジャケット/シャツ/ズボン/スカート/靴/肌)
- 顔: 目・眉・鼻・口・耳・髪を頭の骨に付ける
- アニメーション: walk / run / idle を Blender でキーフレームを打って書き出す
"""
import math
import os
import sys

import bpy
import bmesh
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_assets as B  # noqa: E402

mat = B.mat
ROOT = B.ROOT


def set_active(o):
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o


# 関節(名前, 位置, 半径x, 半径y)  Z=上, +Y=前
def skeleton(female):
    s = 0.95 if female else 1.0
    hipW = 0.105 if female else 0.1
    sh = 0.17 if female else 0.19
    J = {
        "pelvis": ((0, 0, 0.95), (0.15 if female else 0.14, 0.1)),
        "spine": ((0, 0.0, 1.13), (0.12 if female else 0.135, 0.095)),
        "chest": ((0, 0.005, 1.33), (0.15 if female else 0.165, 0.105)),
        "neck": ((0, 0.0, 1.5), (0.05, 0.05)),
        "headbase": ((0, 0.01, 1.56), (0.055, 0.055)),
    }
    for side, sx in (("L", 1), ("R", -1)):
        J[f"shoulder.{side}"] = ((sx * sh, 0, 1.43), (0.055, 0.055))
        J[f"elbow.{side}"] = ((sx * (sh + 0.03), -0.02, 1.15), (0.042, 0.042))
        J[f"wrist.{side}"] = ((sx * (sh + 0.04), 0.0, 0.9), (0.03, 0.025))
        J[f"hand.{side}"] = ((sx * (sh + 0.045), 0.01, 0.81), (0.035, 0.018))
        J[f"hip.{side}"] = ((sx * hipW, 0, 0.9), (0.085 if female else 0.08, 0.085))
        J[f"knee.{side}"] = ((sx * (hipW - 0.01), 0.01, 0.5), (0.052, 0.055))
        J[f"ankle.{side}"] = ((sx * (hipW - 0.01), -0.01, 0.09), (0.038, 0.04))
        J[f"toe.{side}"] = ((sx * (hipW - 0.01), 0.14, 0.04), (0.04, 0.03))
    return {k: (Vector(p) * s if k else Vector(p), r) for k, (p, r) in J.items()}


EDGES = [("pelvis", "spine"), ("spine", "chest"), ("chest", "neck"), ("neck", "headbase")] + [
    e for side in ("L", "R") for e in [
        ("chest", f"shoulder.{side}"), (f"shoulder.{side}", f"elbow.{side}"), (f"elbow.{side}", f"wrist.{side}"),
        (f"wrist.{side}", f"hand.{side}"), ("pelvis", f"hip.{side}"), (f"hip.{side}", f"knee.{side}"),
        (f"knee.{side}", f"ankle.{side}"), (f"ankle.{side}", f"toe.{side}")]]


def build(female):
    B.reset()
    J = skeleton(female)
    names = list(J.keys())
    me = bpy.data.meshes.new("Body")
    me.from_pydata([J[n][0] for n in names], [(names.index(a), names.index(b)) for a, b in EDGES], [])
    body = B.link(bpy.data.objects.new("Body", me))
    set_active(body)
    sk = body.modifiers.new("Skin", "SKIN")
    sk.use_smooth_shade = True
    for i, n in enumerate(names):
        body.data.skin_vertices[0].data[i].radius = J[n][1]
    body.data.skin_vertices[0].data[names.index("pelvis")].use_root = True
    # 骨とウェイトを自動生成
    bpy.ops.object.skin_armature_create(modifier="Skin")
    arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
    arm.name = "Rig"
    sub = body.modifiers.new("Sub", "SUBSURF")
    sub.levels = 2
    # スキン→細分化を適用(アーマチュアモディファイアは残す)
    set_active(body)
    for m in ["Skin", "Sub"]:
        bpy.ops.object.modifier_move_to_index(modifier=m, index=0) if False else None
    for m in list(body.modifiers):
        if m.type in ("SKIN", "SUBSURF"):
            bpy.ops.object.modifier_apply(modifier=m.name)

    # 布の織り目を貼るための UV 展開
    set_active(body)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")

    # 骨の名前を部位名に(骨の根元の位置で判定)
    set_active(arm)
    bpy.ops.object.mode_set(mode="EDIT")
    rename = {}
    for b in arm.data.edit_bones:
        h, t = b.head, b.tail
        near = min(names, key=lambda n: (J[n][0] - t).length)
        rename[b.name] = near
    bpy.ops.object.mode_set(mode="OBJECT")
    for old, new in rename.items():
        arm.data.bones[old].name = "b_" + new.replace(".", "_")
        g = body.vertex_groups.get(old)
        if g:
            g.name = "b_" + new.replace(".", "_")

    # ---- 服・肌のマテリアル(頂点位置で面を振り分け)
    skin = mat("Skin", (0.78, 0.6, 0.48), rough=0.5)
    jacket = mat("Jacket", (0.2, 0.21, 0.24), rough=0.8)      # 個体ごとにゲーム側で色替え
    pants = mat("Pants", (0.15, 0.16, 0.2), rough=0.8)
    shoe = mat("Shoe", (0.04, 0.035, 0.03), rough=0.3, metal=0.1)
    shirt = mat("ShirtW", (0.9, 0.9, 0.88), rough=0.7)
    for m in (skin, jacket, pants, shoe, shirt):
        body.data.materials.append(m)
    bm = bmesh.new()
    bm.from_mesh(body.data)
    s = 0.95 if female else 1.0
    for f in bm.faces:
        c = f.calc_center_median()
        ax = abs(c.x)
        if c.z < 0.11 * s:
            f.material_index = 3                       # 靴
        elif c.z > 1.47 * s:
            f.material_index = 0                       # 首
        elif c.z < 0.9 * s and ax > (0.15 if female else 0.17):
            f.material_index = 0                       # 手首から先(腕の下端)
        elif (female and c.z < 0.58 * s):
            f.material_index = 0                       # スカートの下の脚(肌色のストッキング風)
        elif c.z < 0.93 * s and ax < (0.2 if female else 0.22):
            f.material_index = 1 if female else 2      # 女性はスカート(上着と同系色)、男性はズボン
        else:
            f.material_index = 1                       # 上着
        # シャツの V ゾーン
        if not female and c.y > 0.07 and 1.2 * s < c.z < 1.46 * s and ax < 0.05:
            f.material_index = 4
    bm.to_mesh(body.data)
    bm.free()
    if female:  # 台形のスカート(腰の骨に追従)
        bpy.ops.mesh.primitive_cone_add(vertices=24, radius1=0.24, radius2=0.155, depth=0.42, location=(0, 0, 0.74 * s), end_fill_type="NOTHING")
        sk_ = bpy.context.active_object
        sk_.name = "Skirt"
        sk_.scale = (1, 0.8, 1)
        sk_.data.materials.append(jacket)
        so = sk_.modifiers.new("So", "SOLIDIFY"); so.thickness = 0.008
        set_active(sk_); bpy.ops.object.modifier_apply(modifier="So")
        bpy.ops.object.transform_apply(scale=True)
        for p in sk_.data.polygons:
            p.use_smooth = True
        vg = sk_.vertex_groups.new(name="b_spine"); vg.add(list(range(len(sk_.data.vertices))), 1.0, "REPLACE")
        sk_.modifiers.new("Arm", "ARMATURE").object = arm
        sk_.parent = arm

    # ---- 頭(顔のパーツ付き)を頭の骨に付ける
    headZ = 1.66 * s
    hb = "b_headbase"
    parts = []
    head = B.sphere("Head", 0.1, (0, 0.012, headZ), skin, scale=(0.9, 1.0, 1.15), seg=24)
    bmh = bmesh.new(); bmh.from_mesh(head.data)
    for v in bmh.verts:  # あごを細く、後頭部を丸く
        if v.co.z < -0.02:
            v.co.x *= 1 - (-v.co.z - 0.02) * 2.2
        if v.co.y > 0.05 and -0.03 < v.co.z < 0.03:
            v.co.y += 0.006
    bmh.to_mesh(head.data); bmh.free()
    parts.append(head)
    hair_col = (0.02, 0.018, 0.015) if not female else (0.05, 0.03, 0.02)
    hair = mat("Hair", hair_col, rough=0.45)
    hc = B.sphere("Hair", 0.106, (0, 0.0, headZ + 0.028), hair, scale=(0.94, 1.05, 1.0), seg=24)
    bmh = bmesh.new(); bmh.from_mesh(hc.data)
    for v in list(bmh.verts):  # 顔の部分を削る
        if v.co.y > 0.02 and v.co.z < 0.05:
            v.co.y -= 0.03; v.co.z += 0.02
    bmh.to_mesh(hc.data); bmh.free()
    parts.append(hc)
    if female:  # 肩までの髪
        back = B.sphere("HairBack", 0.1, (0, -0.03, headZ - 0.07), hair, scale=(1.0, 0.7, 1.3), seg=18)
        parts.append(back)
    eyeW = mat("EyeWhite", (0.85, 0.85, 0.82), rough=0.2)
    eyeD = mat("EyeDark", (0.02, 0.015, 0.012), rough=0.1)
    brow = mat("Brow", hair_col, rough=0.8)
    lip = mat("Lip", (0.55, 0.3, 0.28) if not female else (0.6, 0.2, 0.22), rough=0.4)
    for sx in (-1, 1):
        parts.append(B.sphere("EyeW", 0.013, (sx * 0.033, 0.1, headZ + 0.014), eyeW, scale=(1.25, 0.7, 0.75), seg=10))
        parts.append(B.sphere("Pupil", 0.0075, (sx * 0.033, 0.1085, headZ + 0.014), eyeD, seg=8))
        parts.append(B.box("Brow", (0.032, 0.01, 0.007), (sx * 0.034, 0.106, headZ + 0.036), brow, bevel=0.002))
        parts.append(B.sphere("Ear", 0.022, (sx * 0.092, 0.0, headZ + 0.0), skin, scale=(0.35, 0.8, 1.2), seg=10))
    nose = B.box("Nose", (0.02, 0.03, 0.042), (0, 0.113, headZ - 0.012), skin, bevel=0.009)
    nose.rotation_euler = (math.radians(-12), 0, 0)
    parts.append(nose)
    parts.append(B.box("Mouth", (0.036, 0.012, 0.009), (0, 0.098, headZ - 0.048), lip, bevel=0.004))
    headmesh = B.join(parts, "HeadMesh")
    # 頭は骨一本に 100% で追従させる
    vg = headmesh.vertex_groups.new(name=hb)
    vg.add(list(range(len(headmesh.data.vertices))), 1.0, "REPLACE")
    headmesh.modifiers.new("Arm", "ARMATURE").object = arm
    headmesh.parent = arm
    for p in headmesh.data.polygons:
        p.use_smooth = True

    # ネクタイ・襟(男性)
    if not female:
        tie = B.box("Tie", (0.045, 0.012, 0.3), (0, 0.118 * s, 1.3 * s), mat("Tie", (0.35, 0.06, 0.08), rough=0.5), bevel=0.004)
        vg = tie.vertex_groups.new(name="b_chest"); vg.add(list(range(len(tie.data.vertices))), 1.0, "REPLACE")
        tie.modifiers.new("Arm", "ARMATURE").object = arm
        tie.parent = arm

    # ---- AO を頂点カラーへ(骨を付けた状態のまま)
    import detail
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    detail.bake_ao(meshes, samples=32)

    # ---- アニメーション
    make_actions(arm)
    body.parent = arm
    name = "person_f" if female else "person_m"
    path = os.path.join(B.OUT, f"{name}.glb")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", export_yup=True, export_apply=False,
                              export_animations=True, export_animation_mode="ACTIONS", export_skins=True,
                              export_vertex_color="ACTIVE", export_all_vertex_colors=False)
    print(f"  -> {name}.glb ({os.path.getsize(path) / 1024:.0f} KB)")
    B.preview(name, (1.6, 3.6, 1.3), (0, 0, 0.9))
    B.preview(name + "_face", (0.25, 0.55, 1.62), (0, 0, 1.6))


def make_actions(arm):
    """walk / run / idle をキーフレームで作る(骨のローカル X 軸まわりの回転で前後に振る)"""
    set_active(arm)
    bpy.ops.object.mode_set(mode="POSE")
    pb = arm.pose.bones
    for p in pb:
        p.rotation_mode = "XYZ"

    def act(name, frames, fn):
        a = bpy.data.actions.new(name)
        arm.animation_data_create()
        arm.animation_data.action = a
        for f in range(frames + 1):
            t = f / frames
            for p in pb:
                p.rotation_euler = (0, 0, 0)
                p.location = (0, 0, 0)
            fn(t)
            for p in pb:
                p.keyframe_insert("rotation_euler", frame=f + 1)
                p.keyframe_insert("location", frame=f + 1)
        # NLA に積んでおく(書き出し対象にする)
        tr = arm.animation_data.nla_tracks.new()
        tr.name = name
        tr.strips.new(name, 1, a)
        arm.animation_data.action = None

    def g(n):
        return pb.get("b_" + n.replace(".", "_"))

    def gait(t, amp, knee, arm_amp, bob, lean):
        ph = t * 2 * math.pi
        for side, sgn in (("L", 1), ("R", -1)):
            s = math.sin(ph) * sgn
            k = max(0.0, math.sin(ph + (0 if sgn > 0 else math.pi) - 0.9))
            if g(f"knee.{side}"): g(f"knee.{side}").rotation_euler.x = -amp * s      # 太もも(股関節→膝の骨)
            if g(f"ankle.{side}"): g(f"ankle.{side}").rotation_euler.x = knee * k    # すね(膝の曲げ)
            if g(f"elbow.{side}"): g(f"elbow.{side}").rotation_euler.x = arm_amp * s  # 上腕の振り
            if g(f"wrist.{side}"): g(f"wrist.{side}").rotation_euler.x = -0.25 - abs(s) * 0.2
        if g("spine"):
            g("spine").location.z = bob * abs(math.cos(ph))
            g("spine").rotation_euler.x = lean
            g("spine").rotation_euler.z = 0.05 * math.sin(ph)
        if g("neck"): g("neck").rotation_euler.x = -lean * 0.6

    act("walk", 24, lambda t: gait(t, 0.42, 0.75, 0.35, 0.02, 0.05))
    act("run", 16, lambda t: gait(t, 0.8, 1.5, 0.9, 0.05, 0.22))

    def idle(t):
        ph = t * 2 * math.pi
        if g("spine"): g("spine").rotation_euler.x = 0.02 * math.sin(ph)
        if g("chest"): g("chest").location.z = 0.004 * math.sin(ph)
        for side in ("L", "R"):
            if g(f"wrist.{side}"): g(f"wrist.{side}").rotation_euler.x = -0.15
    act("idle", 48, idle)
    bpy.ops.object.mode_set(mode="OBJECT")


if __name__ == "__main__":
    build(False)
    build(True)
