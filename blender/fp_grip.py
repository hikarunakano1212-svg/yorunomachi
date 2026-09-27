"""指の骨格付きの一人称の腕(fps-arms_1 素材)で、拳銃を握る右腕を作る

    python blender/fp_grip.py [素材フォルダ]   # 既定: assets/source/fps-arms-rigged

- 右手の指を骨の X 軸まわりに曲げてグリップを握る形にする(人差し指は引き金に掛けるので浅く)
- ポーズのまま形を固め、左腕の頂点は消す
- 手首を原点、前腕→手首の向きを +Y に置き直して assets/models/fp_arm.glb に書き出す(従来の腕と差し替え)
"""
import os
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[-1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[-1]) else os.path.join(ROOT, 'assets', 'source', 'fps-arms-rigged')
tex = lambda n: os.path.join(SRC, 'textures', n)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=os.path.join(SRC, 'source', 'arms1.fbx'))
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
mesh = bpy.data.objects['armmesh']

# ---- マテリアル(色・法線・AO)
m = mesh.data.materials[0]; m.use_nodes = True; nt = m.node_tree
for n in list(nt.nodes): nt.nodes.remove(n)
out = nt.nodes.new('ShaderNodeOutputMaterial'); b = nt.nodes.new('ShaderNodeBsdfPrincipled')
col = nt.nodes.new('ShaderNodeTexImage'); col.image = bpy.data.images.load(tex('arm1Color.png'))
nor = nt.nodes.new('ShaderNodeTexImage'); nor.image = bpy.data.images.load(tex('arm1Normal.png')); nor.image.colorspace_settings.name = 'Non-Color'
ao = nt.nodes.new('ShaderNodeTexImage'); ao.image = bpy.data.images.load(tex('ao.png')); ao.image.colorspace_settings.name = 'Non-Color'
mix = nt.nodes.new('ShaderNodeMix'); mix.data_type = 'RGBA'; mix.blend_type = 'MULTIPLY'; mix.inputs['Factor'].default_value = 1
nm = nt.nodes.new('ShaderNodeNormalMap')
nt.links.new(col.outputs[0], mix.inputs['A']); nt.links.new(ao.outputs[0], mix.inputs['B'])
nt.links.new(mix.outputs[2], b.inputs['Base Color'])
nt.links.new(nor.outputs[0], nm.inputs['Color']); nt.links.new(nm.outputs[0], b.inputs['Normal'])
b.inputs['Roughness'].default_value = 0.6
nt.links.new(b.outputs[0], out.inputs[0])

# ---- 握るポーズ
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode='POSE')
for p in arm.pose.bones:
    p.rotation_mode = 'XYZ'
CURL = {'point': [0.55, 0.35, 0.25], 'middle': [1.35, 1.3, 1.0], 'ring': [1.4, 1.35, 1.0], 'pink': [1.4, 1.3, 1.0], 'thumb': [0.3, 0.4, 0.3]}
for f, vals in CURL.items():
    for i, v in enumerate(vals):
        pb = arm.pose.bones.get(f'R_{f}{i + 1}')
        if pb:
            pb.rotation_euler.x = -v
bpy.ops.object.mode_set(mode='OBJECT')
bpy.context.view_layer.update()

# ---- 左腕の頂点を消し、ポーズで固める
bm = bmesh.new(); bm.from_mesh(mesh.data)
deform = bm.verts.layers.deform.active
lefts = [g.index for g in mesh.vertex_groups if g.name.startswith('L_')]
kill = [v for v in bm.verts if deform and sum(v[deform].get(i, 0) for i in lefts) > 0.5]
bmesh.ops.delete(bm, geom=kill, context='VERTS')
bm.to_mesh(mesh.data); bm.free()
bpy.context.view_layer.objects.active = mesh
for mod in list(mesh.modifiers):
    if mod.type == 'ARMATURE':
        bpy.ops.object.modifier_apply(modifier=mod.name)

# ---- 手首を原点、前向きを +Y に
mw = arm.matrix_world
wrist = mw @ arm.pose.bones['R_wrist'].head
elbow = mw @ arm.pose.bones['R_elbow'].head
fwd = (wrist - elbow).normalized()
rot = fwd.rotation_difference(Vector((0, 1, 0))).to_matrix().to_4x4()
mesh.parent = None
mesh.matrix_world = rot @ Matrix.Translation(-wrist) @ mesh.matrix_world
for o in list(bpy.data.objects):
    if o is not mesh:
        bpy.data.objects.remove(o)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
dims = [round(d, 3) for d in mesh.dimensions]
print('  大きさ', dims)
out_p = os.path.join(ROOT, 'assets', 'models', 'fp_arm.glb')
bpy.ops.export_scene.gltf(filepath=out_p, export_format='GLB', export_image_format='WEBP', export_image_quality=85, export_yup=True)
print(f'  -> {os.path.relpath(out_p, ROOT)} ({os.path.getsize(out_p) / 1e6:.1f} MB)')
