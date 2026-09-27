"""一人称視点の右腕(拳銃を握る手)を Mixamo の人物から切り出す

    python blender/fp_arm.py [人物FBX] [--preview]

- 右の前腕・手・指に強く結び付いた頂点だけを残す(スーツの袖と手の写真テクスチャをそのまま使う)
- 指の骨を曲げて拳銃のグリップを握る形にし、そのポーズでメッシュを固定する
- 手首の位置を原点、指先の向きを +Y(前)に置き直して assets/models/fp_arm.glb に書き出す
"""
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = [a for a in sys.argv[1:] if not a.startswith('--')]
SRC = args[-1] if args and args[-1].endswith('.fbx') else os.path.join(ROOT, 'assets', 'source', 'mixamo', 'Ch33_nonPBR.fbx')
PREVIEW = '--preview' in sys.argv
KEEP = ('RightForeArm', 'RightHand')
CURL = float(os.environ.get('CURL', '1.25'))       # 指を曲げる量(ラジアン/関節)
AXIS = os.environ.get('AXIS', 'Z')                  # 指を曲げる軸


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=SRC)
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']
    strip = lambda n: n.split(':')[-1]
    for b in arm.data.bones:
        b.name = strip(b.name)
    for m in meshes:
        for g in m.vertex_groups:
            g.name = strip(g.name)

    # ---- ポーズ: 腕を前に出し、指を握る
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='POSE')
    pb = arm.pose.bones
    for p in pb:
        p.rotation_mode = 'XYZ'
    for name, p in pb.items():
        if name.startswith('RightHand') and name != 'RightHand':
            j = name[-1]
            if 'Thumb' in name:
                setattr(p.rotation_euler, AXIS.lower(), CURL * 0.35)
            elif 'Index' in name:
                setattr(p.rotation_euler, AXIS.lower(), CURL * (0.55 if j == '1' else 0.35))  # 人差し指は引き金に掛ける
            else:
                setattr(p.rotation_euler, AXIS.lower(), CURL)
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.update()

    # ---- 右前腕・手・指に強く結び付いた頂点だけ残す
    for m in meshes:
        keep_groups = [g.index for g in m.vertex_groups if g.name.startswith(KEEP)]
        import bmesh
        bm = bmesh.new(); bm.from_mesh(m.data)
        deform = bm.verts.layers.deform.active
        kill = []
        for v in bm.verts:
            w = sum(v[deform].get(i, 0) for i in keep_groups) if deform else 0
            if w < 0.5:
                kill.append(v)
        bmesh.ops.delete(bm, geom=kill, context='VERTS')
        bm.to_mesh(m.data); bm.free()
        if len(m.data.vertices) == 0:
            bpy.data.objects.remove(m)
            continue
        # ポーズでメッシュを固定(アーマチュアモディファイアを適用)
        bpy.context.view_layer.objects.active = m
        for mod in list(m.modifiers):
            if mod.type == 'ARMATURE':
                bpy.ops.object.modifier_apply(modifier=mod.name)
    meshes = [o for o in bpy.data.objects if o.type == 'MESH']

    # ---- 手首を原点に、指先の向きを +Y に
    hand = arm.pose.bones['RightHand']
    mw = arm.matrix_world
    wrist = mw @ hand.head
    tip = mw @ hand.tail
    fore = mw @ arm.pose.bones['RightForeArm'].head
    fwd = (tip - fore).normalized()
    # fwd を +Y に向ける回転
    rot = fwd.rotation_difference(Vector((0, 1, 0))).to_matrix().to_4x4()
    T = rot @ Matrix.Translation(-wrist)
    for m in meshes:
        m.parent = None
        m.matrix_world = T @ m.matrix_world
    bpy.data.objects.remove(arm)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for img in bpy.data.images:
        if img.size[0] > 1024:
            img.scale(1024, 1024)
    tris = sum(len(p.vertices) - 2 for m in meshes for p in m.data.polygons)
    dims = [max(v.co[i] for m in meshes for v in m.data.vertices) - min(v.co[i] for m in meshes for v in m.data.vertices) for i in range(3)]
    print(f'  三角形 {tris}  大きさ {[round(d, 3) for d in dims]}')

    if PREVIEW:
        import build_assets as B  # noqa
    out = os.path.join(ROOT, 'assets', 'models', 'fp_arm.glb')
    bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_image_format='WEBP', export_image_quality=85, export_yup=True)
    print(f'  -> {os.path.relpath(out, ROOT)} ({os.path.getsize(out) / 1e6:.1f} MB)')
    if PREVIEW:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import build_assets as B
        B.preview(f'fp_arm_{AXIS}', (0.35, -0.1, 0.25), (0, 0.08, 0))


if __name__ == '__main__':
    main()
