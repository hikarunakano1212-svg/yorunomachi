"""アニメーション付きの一人称の腕+拳銃(fps-pistol-animations 素材)をゲーム用 glb にする

    python blender/fp_pistol.py [素材フォルダ]   # 既定: assets/source/fps-pistol

- 腕(arms)と拳銃(xd_frame*)に色・法線・粗さ・AO を付け直す(2048px の WebP)
- 拳銃用のアクションだけを idle / fire / reload / reload_full / walk の名前で書き出す
出力: assets/models/fp_pistol.glb
"""
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = sys.argv[-1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[-1]) else os.path.join(ROOT, 'assets', 'source', 'fps-pistol')
T = lambda n: os.path.join(SRC, 'textures', n)
RES = 2048

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=os.path.join(SRC, 'source', 'Armpist.fbx'))
arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')


def img(path, color=True):
    i = bpy.data.images.load(path)
    if not color:
        i.colorspace_settings.name = 'Non-Color'
    if i.size[0] > RES:
        i.scale(RES, RES)
    return i


def material(name, col, nor, rough=None, ao=None, gloss=None, metal=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes['Principled BSDF']
    c = nt.nodes.new('ShaderNodeTexImage'); c.image = img(col)
    base = c.outputs[0]
    if ao:
        a = nt.nodes.new('ShaderNodeTexImage'); a.image = img(ao, False)
        mx = nt.nodes.new('ShaderNodeMix'); mx.data_type = 'RGBA'; mx.blend_type = 'MULTIPLY'; mx.inputs['Factor'].default_value = 1
        nt.links.new(base, mx.inputs['A']); nt.links.new(a.outputs[0], mx.inputs['B']); base = mx.outputs[2]
    nt.links.new(base, b.inputs['Base Color'])
    n = nt.nodes.new('ShaderNodeTexImage'); n.image = img(nor, False)
    nm = nt.nodes.new('ShaderNodeNormalMap'); nt.links.new(n.outputs[0], nm.inputs['Color']); nt.links.new(nm.outputs[0], b.inputs['Normal'])
    if rough:
        r = nt.nodes.new('ShaderNodeTexImage'); r.image = img(rough, False); nt.links.new(r.outputs[0], b.inputs['Roughness'])
    elif gloss:
        gi = nt.nodes.new('ShaderNodeTexImage'); gi.image = img(gloss, False)
        inv = nt.nodes.new('ShaderNodeInvert'); nt.links.new(gi.outputs[0], inv.inputs['Color']); nt.links.new(inv.outputs[0], b.inputs['Roughness'])
    b.inputs['Metallic'].default_value = metal
    return m


arms_m = material('Arms', T('armColor.png'), T('armNormal.png'), rough=T('armRoughness.png'), ao=T('armAO.png'))
gun_m = material('Pistol', T('for_texturing_None.001_Diffuse.png'), T('for_texturing_None.001_Normal.png'), gloss=T('for_texturing_None.001_Glossiness.png'), metal=0.7)
for o in bpy.data.objects:
    if o.type == 'MESH':
        o.data.materials.clear()
        o.data.materials.append(arms_m if o.name == 'arms' else gun_m)
        for p in o.data.polygons:
            p.use_smooth = True

# アクションを NLA トラックとして並べる(拳銃用のみ)
names = {'FPS_Pistol_Idle': 'idle', 'FPS_Pistol_Fire': 'fire', 'FPS_Pistol_Reload_easy': 'reload',
         'FPS_Pistol_Reload_full': 'reload_full', 'FPS_Pistol_Walk': 'walk'}
arm.animation_data_create()
for a in list(bpy.data.actions):
    key = a.name.split('|')[-1]
    if key in names:
        a.name = names[key]
        tr = arm.animation_data.nla_tracks.new(); tr.name = a.name
        tr.strips.new(a.name, int(a.frame_range[0]), a)
arm.animation_data.action = None
out = os.path.join(ROOT, 'assets', 'models', 'fp_pistol.glb')
bpy.ops.object.select_all(action='SELECT')
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_animations=True, export_animation_mode='NLA_TRACKS',
                          export_skins=True, export_image_format='WEBP', export_image_quality=85, export_yup=True)
print(f'  -> {os.path.relpath(out, ROOT)} ({os.path.getsize(out) / 1e6:.1f} MB)')
