"""Poly Haven の .blend 素材をゲーム用の glb に変換する

    python blender/polyhaven.py <展開した .blend のパス> <出力名> <残すオブジェクト名,...> [テクスチャ解像度]

例:
    python blender/polyhaven.py service_pistol_4k.blend ph_pistol service_pistol_pistol_a,service_pistol_slide_a,service_pistol_hammer_a,service_pistol_trigger_a 2048
    python blender/polyhaven.py modular_chainlink_fence_4k.blend ph_fence modular_chainlink_fence_double,modular_chainlink_fence_post 1024

- 指定したオブジェクト以外は削除し、各オブジェクトは原点に置き直す(名前で参照する)
- 4K テクスチャを指定の解像度に縮める(色は JPEG、透明のある画像は PNG のまま)
- 拳銃は銃口が +X を向いているので、ゲームの規約(+Y が前)に回す
"""
import math
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
src, name, keep = args[0], args[1], args[2].split(',')
res = int(args[3]) if len(args) > 3 else 1024

bpy.ops.wm.open_mainfile(filepath=os.path.abspath(src))
for o in list(bpy.data.objects):
    if o.name not in keep:
        bpy.data.objects.remove(o)
for o in bpy.data.objects:
    if 'pistol' in name:
        # 拳銃は部品(スライド・撃鉄・引き金)の組み付け位置を保ったまま、全体を回す
        o.location = o.location.copy()
        o.location.rotate(__import__('mathutils').Euler((0, 0, math.radians(90))))
        o.rotation_euler = (0, 0, math.radians(90))  # 銃口(+X)を前(+Y)へ
    else:
        o.location = (0, 0, 0)  # 組み立て部品は1つずつ原点に置いて、ゲーム側で並べる
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
for img in bpy.data.images:
    if img.size[0] > res:
        img.scale(res, res)
out = os.path.join(ROOT, 'assets', 'models', f'{name}.glb')
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_image_format='WEBP', export_image_quality=80, export_yup=True, export_apply=True)
print(f'  -> {os.path.relpath(out, ROOT)} ({os.path.getsize(out) / 1e6:.1f} MB)')
