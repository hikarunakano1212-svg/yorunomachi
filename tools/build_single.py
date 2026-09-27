"""ダブルクリックで遊べる単体 HTML を作る。

    python tools/build_single.py            # dist/yorunomachi.html を出力

JavaScript を 1 本にまとめるのに esbuild (npx) を使う。Node.js が必要。
3D モデル(glb)と八重洲の地図データ・画像は HTML の中に埋め込む。
"""
import base64
import json
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, 'dist')


def glb_to_gltf(path):
    """glb を、バッファを data URI で埋め込んだ glTF(JSON) に変換する"""
    d = open(path, 'rb').read()
    o, js, binc = 12, None, b''
    while o < len(d):
        ln, t = struct.unpack('<II', d[o:o + 8])
        c = d[o + 8:o + 8 + ln]
        o += 8 + ln
        if t == 0x4E4F534A:
            js = json.loads(c)
        else:
            binc = c
    js['buffers'][0]['uri'] = 'data:application/octet-stream;base64,' + base64.b64encode(binc).decode()
    return js


def data_uri(path, mime):
    return f'data:{mime};base64,' + base64.b64encode(open(path, 'rb').read()).decode()


def main():
    os.makedirs(DIST, exist_ok=True)
    bundle = os.path.join(DIST, '_game.js')
    three = os.path.join(ROOT, 'vendor', 'three')
    cmd = ['npx', '--yes', 'esbuild@0.24', os.path.join(ROOT, 'src', 'main.js'), '--bundle', '--format=esm', '--minify',
           f'--alias:three={os.path.join(three, "three.module.js")}', f'--alias:three/addons={os.path.join(three, "addons")}',
           f'--outfile={bundle}']
    subprocess.run(cmd, check=True, shell=sys.platform == 'win32')
    js = open(bundle, encoding='utf-8').read().replace('</script', '<\\/script')
    os.remove(bundle)

    models_dir = os.path.join(ROOT, 'assets', 'models')
    models = {f[:-4]: glb_to_gltf(os.path.join(models_dir, f)) for f in os.listdir(models_dir) if f.endswith('.glb')}
    map_dir = os.path.join(ROOT, 'assets', 'map')
    mapdata = {
        'json': json.load(open(os.path.join(map_dir, 'yaesu.json'), encoding='utf-8')),
        'ground': data_uri(os.path.join(map_dir, 'ground.webp'), 'image/webp'),
        'minimap': data_uri(os.path.join(map_dir, 'minimap.png'), 'image/png'),
    }

    tex_dir = os.path.join(ROOT, 'assets', 'tex')
    tex = {f[:-4]: data_uri(os.path.join(tex_dir, f), 'image/jpeg') for f in os.listdir(tex_dir) if f.endswith('.jpg')}

    html = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
    css = open(os.path.join(ROOT, 'style.css'), encoding='utf-8').read()
    html = html.replace('<link rel="stylesheet" href="style.css">', f'<style>\n{css}</style>')
    i = html.index('<script type="importmap">')
    j = html.index('</script>', i) + len('</script>')
    html = html[:i] + html[j:]
    embed = ('<script>window.__MODELS = ' + json.dumps(models, separators=(',', ':')) + ';\n'
             'window.__MAPDATA = ' + json.dumps(mapdata, ensure_ascii=False, separators=(',', ':')) + ';\n'
             'window.__TEX = ' + json.dumps(tex) + ';</script>\n')
    html = html.replace('<script type="module" src="src/main.js"></script>', embed + '<script type="module">\n' + js + '\n</script>')
    out = os.path.join(DIST, 'yorunomachi.html')
    open(out, 'w', encoding='utf-8').write(html)
    print(f'出力: {out} ({os.path.getsize(out) / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
