"""射点とロケットを GLB(glTF バイナリ)で書き出す。Web やスマホで回して見る用。

    /opt/bpyenv/bin/python rocket/export_glb.py      # → rocket/out/launch_pad.glb

scene.py と同じ組み立てを使う。ただし動画の演出用マテリアル(下だけ実体・光のワイヤー・
マス目で溶ける)は glTF に載らないので、普通の PBR マテリアルに付け替える。
図面の線・噴煙・炎・光の粒は書き出さない。
ビューアでアームを動かせるように、ヒンジ(arm_hinge*)とロケット(RocketRig)は節点として残す。
"""
import os
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scene  # noqa: E402

OUT = os.path.join(HERE, "out", "launch_pad.glb")

# マテリアル名 → (色, 粗さ, 金属, 発光色, 発光の強さ)
PBR = {
    "rk_white": ((0.82, 0.83, 0.84), 0.35, 0.0, None, 0),
    "rk_dark": ((0.05, 0.05, 0.055), 0.45, 0.0, None, 0),
    "rk_gray": ((0.36, 0.37, 0.38), 0.4, 0.0, None, 0),
    "rk_nozzle": ((0.10, 0.09, 0.085), 0.3, 0.9, None, 0),
    "ml_steel": ((0.06, 0.065, 0.07), 0.55, 0.3, None, 0),
    "ml_deck": ((0.13, 0.13, 0.135), 0.7, 0.2, None, 0),
    "tower_steel": ((0.20, 0.21, 0.23), 0.55, 0.4, None, 0),
    "lt_steel": ((0.24, 0.24, 0.25), 0.5, 0.5, None, 0),
    "pole": ((0.28, 0.28, 0.29), 0.5, 0.5, None, 0),
    "tank_white": ((0.70, 0.71, 0.72), 0.45, 0.0, None, 0),
    "bld_concrete": ((0.34, 0.34, 0.33), 0.85, 0.0, None, 0),
    "lamp_panel": ((1.0, 0.95, 0.85), 0.5, 0.0, (1.0, 0.93, 0.82), 6.0),
    "windows": ((1.0, 0.85, 0.6), 0.5, 0.0, (1.0, 0.82, 0.55), 2.0),
    "beacon_red": ((1.0, 0.1, 0.05), 0.5, 0.0, (1.0, 0.05, 0.02), 6.0),
    "ground": ((0.05, 0.06, 0.045), 0.95, 0.0, None, 0),
    "apron": ((0.30, 0.30, 0.29), 0.8, 0.0, None, 0),
    "road": ((0.07, 0.07, 0.07), 0.7, 0.0, None, 0),
    "slope": ((0.16, 0.15, 0.13), 0.95, 0.0, None, 0),
    "trench": ((0.20, 0.19, 0.17), 0.9, 0.0, None, 0),
    "hill": ((0.03, 0.04, 0.03), 0.95, 0.0, None, 0),
    "sea": ((0.01, 0.03, 0.06), 0.15, 0.0, None, 0),
}
SKIP = ("plan_lines", "void_floor", "smoke", "swirl", "flame", "cd_", "title_")


def part_info(name):
    """書き出す部品の名前と寸法(glTF の extras に入れ、ビューアでタップすると出す)。"""
    G = scene.G
    m = lambda v: f"{v / 1000:g} m"   # noqa: E731
    table = [
        ("rocket", "ロケット", f"全長 {m(G.ROCKET_LENGTH)}・代表径 {m(G.CORE_D)}・2段式液体 + SRB 2本"),
        ("nozzles", "エンジンのノズル", f"1段 {len(G.CORE_ENGINES)}基・SRB 2基"),
        ("ml", "移動発射台", f"{m(G.ML['w'])} × {m(G.ML['d'])}・デッキ GL+{m(G.ML['z_deck'])}"),
        ("tower", "アンビリカルタワー", f"高さ {m(G.TOWER['h'])}・{m(G.TOWER['w'])} 角"),
        ("arm", "アクセスアーム", "離脱時に北へ 80° 回る"),
        ("lightning", "避雷塔", f"高さ {m(G.LIGHTNING['h'])} + 避雷針 {m(G.LIGHTNING['mast_h'])}"),
        ("beacon", "航空障害灯", "赤く明滅"),
        ("lightpole", "照明塔", f"高さ {m(G.LIGHT['h'])}"),
        ("lighthead", "照明塔の灯具", "ロケットへ向ける"),
        ("watertank", "水タンク(音響抑制用)", f"径 {m(G.WATER_TANK['d'])} × 高さ {m(G.WATER_TANK['h'])}"),
        ("sphere2", "液体水素貯蔵", f"球径 {m(G.SPHERE['d'])}"),
        ("sphere3", "液体酸素貯蔵", f"球径 {m(G.SPHERE['d'])}"),
        ("trench", "排煙溝", f"幅 {m(G.TRENCH['w'])}・出口 Y={m(G.TRENCH['y_outlet'])}"),
        ("apron", "射点の床", "コンクリート"),
        ("road", "周回道路", f"幅 {m(G.ROAD_W)}"),
        ("slope", "法面(段丘の斜面)", f"GL±0 → 海面 GL{m(G.SEA_LEVEL)}"),
        ("sea", "海", f"海面 GL{m(G.SEA_LEVEL)}"),
        ("hill", "丘", ""),
        ("ground", "地面", "GL±0"),
        ("catenary", "架空地線", "避雷塔の頂部どうしを結ぶ"),
    ]
    for i, (bn, *_r) in enumerate(G.BUILDINGS):
        if name == f"building{i}":
            _, x, y, w, d, h = G.BUILDINGS[i]
            return bn, f"{m(w)} × {m(d)} × 高さ {m(h)}"
    for key, label, spec in table:
        if name.startswith(key):
            return label, spec
    return None


def plain_material(name, spec):
    col, rough, metal, emis, es = spec
    m = bpy.data.materials.new(f"glb_{name}")
    nt = m.node_tree
    nt.nodes.clear()
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = (*col, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if emis:
        bsdf.inputs["Emission Color"].default_value = (*emis, 1.0)
        bsdf.inputs["Emission Strength"].default_value = es
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    return m


def main():
    sc = scene.build((640, 360), 4)
    sc.frame_set(scene.F(10.95))      # 全部が実体になり、アームがまだ付いている時刻
    # アニメーションを外して、その時刻の姿で固定する
    for ob in bpy.data.objects:
        if ob.animation_data:
            ob.animation_data_clear()
        if ob.name.startswith("root_"):
            ob.scale = (1, 1, 1)
        if ob.name.startswith("arm_hinge"):
            ob.rotation_euler = (0, 0, 0)
        if ob.name == "RocketRig":
            ob.location = (0, 0, 0)
            # ビューアの打ち上げ用: 上昇の式の係数と炎の位置(geometry.py の値を m で渡す)
            G = scene.G
            M = scene.M
            ob["launch_accel"] = G.LAUNCH["accel"] * M
            ob["launch_jerk"] = G.LAUNCH["jerk"] * M
            N, SN = G.CORE_NOZZLE, G.SRB_NOZZLE
            fl = [[ex * M, ey * M, (G.Z_BASE + N["top"] - N["length"]) * M, N["exit_r"] * M, 0]
                  for ex, ey in G.CORE_ENGINES]
            fl += [[sx * M, sy * M, (G.Z_BASE + G.SRB_ST["bottom"] - SN["length"]) * M, SN["exit_r"] * M, 1]
                   for sx, sy in G.SRB_CENTERS]
            ob["flames"] = [v for f in fl for v in f]      # x, y, z, 半径, SRB か(5つずつ)
    for ob in bpy.data.objects:
        if ob.name.startswith("flame"):
            ob.hide_render = True
    # マテリアルの付け替え
    plain = {k: plain_material(k, v) for k, v in PBR.items()}
    keep = []
    for ob in bpy.data.objects:
        if ob.type == "EMPTY" and (ob.name.startswith(("root_", "arm_hinge")) or ob.name == "RocketRig"):
            keep.append(ob)
            continue
        if ob.type != "MESH" or ob.name.startswith(SKIP):
            continue
        cols = [c.name for c in ob.users_collection]
        if not set(cols) & {"Build", "Env"}:
            continue
        for slot in ob.material_slots:
            if slot.material and slot.material.name in plain:
                slot.material = plain[slot.material.name]
        info = part_info(ob.name)
        if info:
            ob["label"], ob["spec"] = info
        keep.append(ob)
    for ob in bpy.data.objects:
        ob.select_set(ob in keep)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=OUT, use_selection=True, export_animations=False,
                              export_apply=True, export_yup=True, export_cameras=False,
                              export_lights=False, export_extras=True)
    print(OUT, f"{os.path.getsize(OUT) / 1e6:.2f} MB", len(keep), "objects")
    # ビューア(rocket/viewer/)へ: GLB と、.glb を配れない場所向けの Base64 版
    import base64
    import json
    import shutil
    vdir = os.path.join(HERE, "viewer")
    shutil.copy(OUT, os.path.join(vdir, "launch_pad.glb"))
    with open(OUT, "rb") as f:
        data = {"glb_base64": base64.b64encode(f.read()).decode("ascii")}
    with open(os.path.join(vdir, "launch_pad_glb.json"), "w") as f:
        json.dump(data, f)


if __name__ == "__main__":
    main()
