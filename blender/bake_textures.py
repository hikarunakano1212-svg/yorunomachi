"""Blender で PBR テクスチャ(色・法線・粗さ)を焼く。

    python blender/bake_textures.py   # assets/tex/*.jpg を出力

ノードで組んだ手続きマテリアル(ノイズ・ボロノイ・レンガ等)を平面に貼り、
Cycles の Bake で 1024px の画像にする。どれもタイル状に繰り返せる。
"""
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "tex")
RES = 1024


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    s = bpy.context.scene
    s.render.engine = "CYCLES"
    s.cycles.device = "CPU"
    s.cycles.samples = 4


def plane():
    bpy.ops.mesh.primitive_plane_add(size=2)
    return bpy.context.active_object


def node(nt, t, loc=(0, 0), **kw):
    n = nt.nodes.new(t)
    n.location = loc
    for k, v in kw.items():
        if k in n.inputs:
            n.inputs[k].default_value = v
        else:
            setattr(n, k, v)
    return n


def tileable_coord(nt):
    """4D ノイズを円筒に巻いてタイル化するための座標(u,v を角度に)"""
    tc = node(nt, "ShaderNodeTexCoord")
    sep = node(nt, "ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["UV"], sep.inputs[0])
    import math
    def angle(ch):
        m = node(nt, "ShaderNodeMath", operation="MULTIPLY")
        m.inputs[1].default_value = 2 * math.pi
        nt.links.new(sep.outputs[ch], m.inputs[0])
        c = node(nt, "ShaderNodeMath", operation="COSINE"); nt.links.new(m.outputs[0], c.inputs[0])
        s = node(nt, "ShaderNodeMath", operation="SINE"); nt.links.new(m.outputs[0], s.inputs[0])
        return c, s
    cu, su = angle("X")
    cv, sv = angle("Y")
    comb = node(nt, "ShaderNodeCombineXYZ")
    nt.links.new(cu.outputs[0], comb.inputs[0]); nt.links.new(su.outputs[0], comb.inputs[1]); nt.links.new(cv.outputs[0], comb.inputs[2])
    return comb, sv  # xyz + w


def noise4(nt, coord, w, scale, detail=8, rough=0.6):
    n = node(nt, "ShaderNodeTexNoise", noise_dimensions="4D")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = detail
    n.inputs["Roughness"].default_value = rough
    nt.links.new(coord.outputs[0], n.inputs["Vector"])
    ws = node(nt, "ShaderNodeMath", operation="MULTIPLY"); ws.inputs[1].default_value = 1.0
    nt.links.new(w.outputs[0], ws.inputs[0])
    nt.links.new(ws.outputs[0], n.inputs["W"])
    return n


def voronoi4(nt, coord, w, scale, feature="F1"):
    n = node(nt, "ShaderNodeTexVoronoi", voronoi_dimensions="4D", feature=feature)
    n.inputs["Scale"].default_value = scale
    nt.links.new(coord.outputs[0], n.inputs["Vector"])
    nt.links.new(w.outputs[0], n.inputs["W"])
    return n


def ramp(nt, inp, stops):
    r = node(nt, "ShaderNodeValToRGB")
    cr = r.color_ramp
    cr.elements[0].position, cr.elements[0].color = stops[0][0], (*stops[0][1], 1)
    cr.elements[1].position, cr.elements[1].color = stops[-1][0], (*stops[-1][1], 1)
    for p, c in stops[1:-1]:
        e = cr.elements.new(p); e.color = (*c, 1)
    nt.links.new(inp, r.inputs[0])
    return r


def bake(obj, name, color_out, height_out, rough_out, bump_strength=0.6, bump_dist=0.02):
    """color / height / roughness の出力ソケットを受け取り、3 枚の画像に焼く"""
    mat = obj.active_material
    nt = mat.node_tree
    out = nt.nodes["Material Output"]
    bsdf = nt.nodes["Principled BSDF"]
    bump = node(nt, "ShaderNodeBump")
    bump.inputs["Strength"].default_value = bump_strength
    bump.inputs["Distance"].default_value = bump_dist
    nt.links.new(height_out, bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    img_node = node(nt, "ShaderNodeTexImage")
    nt.nodes.active = img_node
    emit = node(nt, "ShaderNodeEmission")

    def do(kind, socket, colorspace):
        img = bpy.data.images.new(f"{name}_{kind}", RES, RES, float_buffer=False)
        img.colorspace_settings.name = colorspace
        img_node.image = img
        if kind == "normal":
            nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
            bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT", margin=0)
        else:
            nt.links.new(socket, emit.inputs["Color"])
            nt.links.new(emit.outputs[0], out.inputs["Surface"])
            bpy.ops.object.bake(type="EMIT", margin=0)
        img.filepath_raw = os.path.join(OUT, f"{name}_{kind}.jpg")
        img.file_format = "JPEG"
        bpy.context.scene.render.image_settings.quality = 88
        img.save()
        print(f"  -> {name}_{kind}.jpg")

    do("albedo", color_out, "sRGB")
    do("rough", rough_out, "Non-Color")
    do("normal", None, "Non-Color")


def material(obj):
    m = bpy.data.materials.new("M")
    m.use_nodes = True
    obj.data.materials.append(m)
    return m.node_tree


def to_color(nt, value_socket):
    c = node(nt, "ShaderNodeCombineColor")
    for i in range(3):
        nt.links.new(value_socket, c.inputs[i])
    return c.outputs[0]


# ---------------------------------------------------------------- 各素材
def asphalt():
    """アスファルト(8m 四方で1タイル): 骨材の粒、補修跡、ひび、轍の汚れ"""
    reset(); o = plane(); nt = material(o)
    xyz, w = tileable_coord(nt)
    grain = noise4(nt, xyz, w, 900, 4, 0.8)          # 細かい骨材
    stones = voronoi4(nt, xyz, w, 520)               # 砂利の粒
    patches = noise4(nt, xyz, w, 3, 3, 0.5)          # 補修跡のまだら
    cracks = voronoi4(nt, xyz, w, 9, "DISTANCE_TO_EDGE")
    mix1 = node(nt, "ShaderNodeMix", data_type="FLOAT"); mix1.inputs["Factor"].default_value = 0.5
    nt.links.new(grain.outputs["Fac"], mix1.inputs["A"]); nt.links.new(stones.outputs["Distance"], mix1.inputs["B"])
    patch_r = ramp(nt, patches.outputs["Fac"], [(0.45, (0.9, 0.9, 0.9)), (0.55, (1.1, 1.1, 1.1))])
    crack_r = ramp(nt, cracks.outputs["Distance"], [(0.0, (0.35, 0.35, 0.35)), (0.012, (1, 1, 1))])
    col = ramp(nt, mix1.outputs[0], [(0.2, (0.05, 0.05, 0.055)), (0.5, (0.11, 0.11, 0.115)), (0.8, (0.2, 0.2, 0.2))])
    m2 = node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY"); m2.inputs["Factor"].default_value = 1
    nt.links.new(col.outputs[0], m2.inputs["A"]); nt.links.new(patch_r.outputs[0], m2.inputs["B"])
    m3 = node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY"); m3.inputs["Factor"].default_value = 1
    nt.links.new(m2.outputs[2], m3.inputs["A"]); nt.links.new(crack_r.outputs[0], m3.inputs["B"])
    h = node(nt, "ShaderNodeMath", operation="MULTIPLY"); h.inputs[1].default_value = 1
    nt.links.new(mix1.outputs[0], h.inputs[0])
    hc = node(nt, "ShaderNodeMath", operation="MULTIPLY"); nt.links.new(h.outputs[0], hc.inputs[0]); nt.links.new(crack_r.outputs[0], hc.inputs[1])
    rough = ramp(nt, patches.outputs["Fac"], [(0.3, (0.55, 0.55, 0.55)), (0.7, (0.85, 0.85, 0.85))])
    bake(o, "asphalt", m3.outputs[2], hc.outputs[0], rough.outputs[0], 0.8, 0.01)


def pavers():
    """歩道のインターロッキングブロック(2m 四方で1タイル, 20x10cm のヘリンボーン風の段違い)"""
    reset(); o = plane(); nt = material(o)
    tc = node(nt, "ShaderNodeTexCoord")
    brick = node(nt, "ShaderNodeTexBrick", offset=0.5)
    brick.inputs["Scale"].default_value = 10
    brick.inputs["Mortar Size"].default_value = 0.012
    brick.inputs["Brick Width"].default_value = 0.2
    brick.inputs["Row Height"].default_value = 0.1
    brick.inputs["Color1"].default_value = (0.42, 0.38, 0.34, 1)
    brick.inputs["Color2"].default_value = (0.3, 0.28, 0.27, 1)
    brick.inputs["Mortar"].default_value = (0.12, 0.12, 0.12, 1)
    nt.links.new(tc.outputs["UV"], brick.inputs["Vector"])
    xyz, w = tileable_coord(nt)
    dirt = noise4(nt, xyz, w, 12, 6, 0.6)
    dr = ramp(nt, dirt.outputs["Fac"], [(0.35, (0.75, 0.75, 0.75)), (0.65, (1.05, 1.05, 1.05))])
    m = node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY"); m.inputs["Factor"].default_value = 1
    nt.links.new(brick.outputs["Color"], m.inputs["A"]); nt.links.new(dr.outputs[0], m.inputs["B"])
    fine = noise4(nt, xyz, w, 400, 3, 0.7)
    h = node(nt, "ShaderNodeMath", operation="SUBTRACT"); h.inputs[0].default_value = 1
    nt.links.new(brick.outputs["Fac"], h.inputs[1])
    h2 = node(nt, "ShaderNodeMath", operation="MULTIPLY_ADD"); h2.inputs[1].default_value = 0.08
    nt.links.new(fine.outputs["Fac"], h2.inputs[0]); nt.links.new(h.outputs[0], h2.inputs[2])
    rough = ramp(nt, dirt.outputs["Fac"], [(0.3, (0.6, 0.6, 0.6)), (0.7, (0.9, 0.9, 0.9))])
    bake(o, "pavers", m.outputs[2], h2.outputs[0], rough.outputs[0], 1.0, 0.02)


def concrete():
    """外壁の打ち放し/吹付け(4m 四方): 型枠の継ぎ目、雨だれの汚れ"""
    reset(); o = plane(); nt = material(o)
    xyz, w = tileable_coord(nt)
    n1 = noise4(nt, xyz, w, 30, 10, 0.65)
    n2 = noise4(nt, xyz, w, 300, 4, 0.7)
    tc = node(nt, "ShaderNodeTexCoord")
    sep = node(nt, "ShaderNodeSeparateXYZ"); nt.links.new(tc.outputs["UV"], sep.inputs[0])
    # 雨だれ: x 方向に細かく y 方向に長いノイズ
    streak = node(nt, "ShaderNodeTexNoise"); streak.inputs["Scale"].default_value = 6; streak.inputs["Detail"].default_value = 6
    mp = node(nt, "ShaderNodeMapping"); mp.inputs["Scale"].default_value = (40, 1.5, 1)
    nt.links.new(tc.outputs["UV"], mp.inputs["Vector"]); nt.links.new(mp.outputs[0], streak.inputs["Vector"])
    sr = ramp(nt, streak.outputs["Fac"], [(0.4, (1, 1, 1)), (0.75, (0.72, 0.72, 0.72))])
    base = ramp(nt, n1.outputs["Fac"], [(0.3, (0.5, 0.5, 0.49)), (0.7, (0.62, 0.61, 0.59))])
    m = node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY"); m.inputs["Factor"].default_value = 1
    nt.links.new(base.outputs[0], m.inputs["A"]); nt.links.new(sr.outputs[0], m.inputs["B"])
    h = node(nt, "ShaderNodeMath", operation="ADD"); nt.links.new(n1.outputs["Fac"], h.inputs[0]); nt.links.new(n2.outputs["Fac"], h.inputs[1])
    rough = ramp(nt, streak.outputs["Fac"], [(0.4, (0.9, 0.9, 0.9)), (0.8, (0.7, 0.7, 0.7))])
    bake(o, "concrete", m.outputs[2], h.outputs[0], rough.outputs[0], 0.4, 0.02)


def tiles():
    """外壁タイル(日本の雑居ビルに多い 45 二丁掛け)"""
    reset(); o = plane(); nt = material(o)
    tc = node(nt, "ShaderNodeTexCoord")
    brick = node(nt, "ShaderNodeTexBrick", offset=0.5)
    brick.inputs["Scale"].default_value = 8
    brick.inputs["Mortar Size"].default_value = 0.008
    brick.inputs["Brick Width"].default_value = 0.23
    brick.inputs["Row Height"].default_value = 0.1
    brick.inputs["Color1"].default_value = (0.62, 0.55, 0.47, 1)
    brick.inputs["Color2"].default_value = (0.55, 0.49, 0.42, 1)
    brick.inputs["Mortar"].default_value = (0.7, 0.68, 0.64, 1)
    nt.links.new(tc.outputs["UV"], brick.inputs["Vector"])
    xyz, w = tileable_coord(nt)
    dirt = noise4(nt, xyz, w, 8, 6, 0.6)
    dr = ramp(nt, dirt.outputs["Fac"], [(0.3, (0.8, 0.8, 0.8)), (0.7, (1.05, 1.05, 1.05))])
    m = node(nt, "ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY"); m.inputs["Factor"].default_value = 1
    nt.links.new(brick.outputs["Color"], m.inputs["A"]); nt.links.new(dr.outputs[0], m.inputs["B"])
    h = node(nt, "ShaderNodeMath", operation="SUBTRACT"); h.inputs[0].default_value = 1
    nt.links.new(brick.outputs["Fac"], h.inputs[1])
    rough = ramp(nt, brick.outputs["Fac"], [(0.0, (0.35, 0.35, 0.35)), (0.5, (0.9, 0.9, 0.9))])
    bake(o, "tiles", m.outputs[2], h.outputs[0], rough.outputs[0], 0.7, 0.01)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    only = sys.argv[1:] and sys.argv[-1]
    for f in (asphalt, pavers, concrete, tiles):
        if not only or only == f.__name__:
            print("焼き込み:", f.__name__)
            f()
