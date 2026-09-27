"""Mixamo の人物と動きをゲーム用に変換する

    python blender/mixamo.py [人物FBXのあるフォルダ]   # 既定: assets/source/mixamo

- 人物 FBX(メッシュ付き)と動き FBX(骨のみ)を見分けて読み込む
- 骨の名前の接頭辞(mixamorig4: など)を外し、人物と動きで名前をそろえる
- ポリゴンを間引き(目標 約 9,000 三角形)、テクスチャを 1024px に縮小して JPEG で書き出す
- 前へ進む動き(ルートモーション)を消して、その場で足踏みする動きにする
- 動きは walk / run / idle / walk_turn の名前で glb に入れる

出力: assets/models/mx_<人物名>.glb
"""
import glob
import os
import re
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[-1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[-1]) else os.path.join(ROOT, 'assets', 'source', 'mixamo')
OUT = os.path.join(ROOT, 'assets', 'models')
TARGET_TRIS = 9000
TEX = 1024
ANIM_NAMES = {'walk w_ briefcase': 'walk', 'walking': 'walk', 'running': 'run', 'running 1': 'run2', 'idle': 'idle',
              'walking left turn': 'walk_turn', 'standing yell': 'yell'}
PREFIX = re.compile(r'mixamorig\d*:')


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_fbx(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=False)
    return [o for o in bpy.data.objects if o not in before]


def strip_bone_prefix(arm, meshes):
    for b in arm.data.bones:
        b.name = PREFIX.sub('', b.name)
    for m in meshes:
        for g in m.vertex_groups:
            g.name = PREFIX.sub('', g.name)


def fix_action(act):
    """データパスの接頭辞を外し、腰の水平移動(前進)を消す"""
    for fc in act.fcurves:
        fc.data_path = PREFIX.sub('', fc.data_path)
    for fc in act.fcurves:
        if fc.data_path == 'pose.bones["Hips"].location':
            pts = fc.keyframe_points
            if len(pts) < 2:
                continue
            drift = pts[-1].co[1] - pts[0].co[1]
            if abs(drift) > 15:  # 15cm 以上進む軸 = 前進方向 → 直線的な移動分を引く
                n = len(pts)
                v0 = pts[0].co[1]
                for i, p in enumerate(pts):
                    p.co[1] -= drift * i / (n - 1)
                    p.handle_left[1] -= drift * i / (n - 1)
                    p.handle_right[1] -= drift * i / (n - 1)


def decimate(meshes):
    tris = sum(sum(len(p.vertices) - 2 for p in m.data.polygons) for m in meshes)
    ratio = min(1.0, TARGET_TRIS / max(1, tris))
    for m in meshes:
        if ratio < 0.98 and len(m.data.polygons) > 300:
            mod = m.modifiers.new('Dec', 'DECIMATE')
            mod.ratio = ratio
            bpy.context.view_layer.objects.active = m
            # アーマチュアより前に置いて適用する
            while m.modifiers.find('Dec') > 0:
                bpy.ops.object.modifier_move_up(modifier='Dec')
            bpy.ops.object.modifier_apply(modifier='Dec')
    after = sum(sum(len(p.vertices) - 2 for p in m.data.polygons) for m in meshes)
    print(f'  三角形 {tris} → {after}')


def shrink_textures():
    for img in bpy.data.images:
        if img.size[0] > TEX:
            img.scale(TEX, TEX)


def main():
    files = sorted(glob.glob(os.path.join(SRC, '*.fbx')))
    chars, anims = [], []
    for f in files:
        reset()
        objs = import_fbx(f)
        (chars if any(o.type == 'MESH' for o in objs) else anims).append(f)
    print('人物:', [os.path.basename(c) for c in chars])
    print('動き:', [os.path.basename(a) for a in anims])
    os.makedirs(OUT, exist_ok=True)
    for cf in chars:
        reset()
        objs = import_fbx(cf)
        arm = next(o for o in objs if o.type == 'ARMATURE')
        meshes = [o for o in objs if o.type == 'MESH']
        strip_bone_prefix(arm, meshes)
        decimate(meshes)
        shrink_textures()
        arm.animation_data_create()
        for af in anims:
            key = os.path.splitext(os.path.basename(af))[0].lower()
            name = ANIM_NAMES.get(key)
            if not name:
                continue
            new = import_fbx(af)
            a2 = next(o for o in new if o.type == 'ARMATURE')
            act = a2.animation_data.action
            act.name = name
            fix_action(act)
            for o in new:
                bpy.data.objects.remove(o)
            tr = arm.animation_data.nla_tracks.new()
            tr.name = name
            tr.strips.new(name, int(act.frame_range[0]), act)
        arm.animation_data.action = None
        base = re.sub(r'_nonPBR$', '', os.path.splitext(os.path.basename(cf))[0])
        path = os.path.join(OUT, f'mx_{base.lower()}.glb')
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.export_scene.gltf(filepath=path, export_format='GLB', export_animations=True,
                                  export_animation_mode='NLA_TRACKS', export_skins=True,
                                  export_image_format='WEBP', export_image_quality=80, export_yup=True)
        print(f'  -> {os.path.relpath(path, ROOT)} ({os.path.getsize(path) / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
