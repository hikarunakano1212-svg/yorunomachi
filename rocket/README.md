# 夜の射点 — 架空の大型ロケットと射点の図面・動画

架空の大型ロケット(2段式液体 + 固体ブースター2本、白い機体、名前なし)とその射点について、
2D の CAD 図面(DXF)と Blender の動画(EEVEE)を作るスクリプトです。
**架空の機体・射場のイメージで、実在の図面ではありません。**

寸法はすべて `geometry.py`(形状モジュール)で決めています。図面と動画の両方がこれを読み込みます。

| ファイル | 役割 |
|---|---|
| `geometry.py` | 寸法(mm)。機体の外形・タンク・SRB、移動発射台、排煙溝、タワー、避雷塔、照明塔、水タンク、建屋、海岸線 |
| `drawings.py` | DXF 3枚とプレビュー PNG(濃紺の背景)。A2 の図枠・表題欄・特記事項つき |
| `floorplan.py` | 射点配置図の DXF を、床に光らせる線と文字の三角形に分解する |
| `timeline.py` | 動画の時刻表(映像と音で共有) |
| `scene.py` | Blender のシーン(bpy)。テスト静止画もここから出す |
| `audio.py` | 音の合成(BGM・波・カウントダウン・轟音・タイトルの和音) |
| `render.py` | 本番の連番レンダー(休憩つき・途中から再開可)、ロゴ、MP4 への書き出し |

## 図面(`out/drawings/`)

| 図番 | 図名 | 尺度 |
|---|---|---|
| LP-001 | 射点配置図 | 1:500 |
| LP-002 | 射点立面図(南から) | 1:400 |
| RK-001 | ロケット外形図・断面図 | 1:250 |

- モデル空間に実寸(mm)で描き、図枠と文字は尺度倍して置いています。CAD で測ると実寸が出ます。
- 線は青緑系の色です(画層ごとに RGB の色を指定)。
- 文字のスタイルは MS ゴシック(`msgothic.ttc`)です。プレビューだけ IPA ゴシックで描いています。

```bash
pip install ezdxf matplotlib shapely
python rocket/drawings.py          # DXF と PNG を作り、文字の重なりを検査して表示する
```

## 動画

- 1920×1080、24fps、本編 20 秒 + ロゴ 3.5 秒、音つき MP4(`out/night_launch.mp4`)。
- Blender 5.2 を Python モジュール(`pip install bpy`)で使っています。

```bash
python3.13 -m venv /opt/bpyenv && /opt/bpyenv/bin/pip install bpy==5.2.2 ezdxf shapely numpy
/opt/bpyenv/bin/python rocket/scene.py --samples 8 --still 2.9 12.0 19.2   # テスト静止画 → out/test/
python3 rocket/audio.py                                                    # → out/audio.wav
LP_NUM_THREADS=3 nice -n 19 /opt/bpyenv/bin/python rocket/render.py frames --chunk 48 --rest 240
python3 rocket/render.py logo --logo ロゴ.png
python3 rocket/render.py mux
```

### 構成(秒)

| 時刻 | 内容 |
|---|---|
| 0–3 | 暗闇の床に、射点配置図(DXF そのもの)がロケットの位置から走査されて光る。真上から見る |
| 3–5 | 図面の線が光のワイヤーとして立ち上がる |
| 5–8.5 | 光の粒(Geometry Nodes)が渦を巻いて昇り、積み上がった高さより下だけが実体になる。カメラは寄る |
| 8.6–11 | 図面がマス目ごとに溶け、海・丘・星空の夜の射点が現れる。照明塔が点き、頂部の赤い灯が明滅する |
| 11–15.5 | アクセスアームが離れる → カウントダウン(T−3, T−2, T−1) |
| 15.5–17.6 | 点火 → リフトオフ。炎は発光する円錐、噴煙は排煙溝と発射台から湧く |
| 17.6–20 | 海の上から上昇するロケットを見上げ、タイトル |
| 20–23.5 | ロゴ |

## 3D モデル(Web で回して見る)

```bash
/opt/bpyenv/bin/python rocket/export_glb.py      # → rocket/out/launch_pad.glb と rocket/viewer/ へのコピー
cd rocket/viewer && python -m http.server 8000   # ブラウザで http://localhost:8000 を開く
```

- 動画と同じ組み立て(`scene.py`)から、射点・ロケット・地形を GLB で書き出す(約 1.4MB)。
- 動画の演出用マテリアルは、普通の PBR マテリアル(白い機体・鉄骨・コンクリートなど)に付け替える。
- 部品ごとに名前と寸法(`geometry.py` の値)を glTF の extras に入れてある。ビューアで部品をタップすると表示される。
- `rocket/viewer/index.html` は Three.js のビューア。回転・拡大、昼と夜の切り替え、アクセスアームの離脱、打ち上げができる。
- 上昇の式の係数と炎の位置も GLB に入れてあり、打ち上げの動きは動画と同じ式で動く。
- `.glb` を置けない配信先のために、同じ中身を Base64 にした `launch_pad_glb.json` も出す。

### 軽い設定にするための工夫

- GPU のないソフトウェア描画では影が一番重いので、影は切っています。夜景なので、影がなくても目立ちません。
- サンプル数は 8 です。半透明の噴煙が出る点火後だけ 12 にしています。
- 噴煙の粒の位置は、毎フレーム Python で計算しています。計算は時刻だけで決まり、乱数の種も固定しています。そのため、どのフレームから描き直しても同じ絵になります。
