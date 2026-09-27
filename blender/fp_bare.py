"""素手の一人称の両腕(fps-arms 素材)をゲーム用 glb にする

    python blender/fp_bare.py [素材フォルダ]   # 既定: assets/source/fps-arms

素材の .blend にはポーズ違いの両腕が 6 つ入っている。両腕を前に構えた Arms_Obj.001 を使う。
色(Arm_COL.png)と法線(Arm_NOR.png)を付け直し、WebP 2048px で書き出す。
"""
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[-1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[-1]) else os.path.join(ROOT, 'assets', 'source', 'fps-arms')
blend = next(os.path.join(SRC, 'source', f) for f in os.listdir(os.path.join(SRC, 'source')) if f.endswith('.blend'))
bpy.ops.wm.open_mainfile(filepath=blend)
for o in list(bpy.data.objects):
    if o.name != 'Arms_Obj.001':
        bpy.data.objects.remove(o)
arm = bpy.data.objects['Arms_Obj.001']
arm.location = (0, 0, 0)
m = bpy.data.materials.new('Arms'); m.use_nodes = True
nt = m.node_tree
b = nt.nodes['Principled BSDF']
col = nt.nodes.new('ShaderNodeTexImage'); col.image = bpy.data.images.load(os.path.join(SRC, 'textures', 'Arm_COL.png'))
nor = nt.nodes.new('ShaderNodeTexImage'); nor.image = bpy.data.images.load(os.path.join(SRC, 'textures', 'Arm_NOR.png')); nor.image.colorspace_settings.name = 'Non-Color'
nm = nt.nodes.new('ShaderNodeNormalMap')
nt.links.new(col.outputs[0], b.inputs['Base Color'])
nt.links.new(nor.outputs[0], nm.inputs['Color']); nt.links.new(nm.outputs[0], b.inputs['Normal'])
b.inputs['Roughness'].default_value = 0.55
arm.data.materials.clear(); arm.data.materials.append(m)
for p in arm.data.polygons:
    p.use_smooth = True
out = os.path.join(ROOT, 'assets', 'models', 'fp_bare.glb')
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_image_format='WEBP', export_image_quality=85, export_yup=True, export_apply=True)
print(f'  -> {os.path.relpath(out, ROOT)} ({os.path.getsize(out) / 1e6:.1f} MB)')
