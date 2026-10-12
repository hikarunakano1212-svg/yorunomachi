"""本番の連番レンダー(休みを挟みながら)と、MP4 への書き出し。

    LP_NUM_THREADS=3 nice -n 19 /opt/bpyenv/bin/python rocket/render.py frames --chunk 48 --rest 240
    python3 rocket/render.py logo  [--logo path/to/logo.png]
    python3 rocket/render.py mux

frames: 本編 20 秒(480 枚)を out/frames/ に PNG で出す。できている番号は飛ばすので、
        途中で止めても同じコマンドで続きから再開できる。
        chunk 枚ごとに rest 秒休む(CPU の温度と他の作業のため)。
logo:   最後の 3.5 秒(ロゴ)を out/frames/ の続きの番号で作る。
mux:    out/frames/*.png と out/audio.wav を MP4 (H.264 + AAC) にまとめる。
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import timeline as TL  # noqa: E402

FRAMES = os.path.join(HERE, "out", "frames")
LOG = os.path.join(HERE, "out", "render.log")
N_MAIN = int(round(TL.T_END * TL.FPS))                 # 480
N_LOGO = int(round(TL.LOGO_LEN * TL.FPS))              # 84


def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def frame_path(f):
    return os.path.join(FRAMES, f"{f:04d}.png")


def cmd_frames(a):
    import bpy
    import scene
    os.makedirs(FRAMES, exist_ok=True)
    todo = [f for f in range(a.start, min(a.end, N_MAIN) + 1) if not os.path.exists(frame_path(f))]
    log(f"frames: 残り {len(todo)} 枚 (chunk={a.chunk}, rest={a.rest}s)")
    if not todo:
        return
    sc = scene.build((1920, 1080), a.samples)
    done, t_start, busy = 0, time.time(), 0.0
    for f in todo:
        t = (f - 1) / TL.FPS
        # 噴煙は半透明の粒なので、点火後だけサンプル数を増やしてざらつきを抑える
        sc.eevee.taa_render_samples = a.samples_smoke if t >= TL.TI else a.samples
        t0 = time.time()
        sc.frame_set(f)
        tmp = frame_path(f) + ".tmp.png"
        sc.render.filepath = tmp
        bpy.ops.render.render(write_still=True)
        os.replace(tmp, frame_path(f))
        dt = time.time() - t0
        busy += dt
        done += 1
        left = len(todo) - done
        eta = busy / done * left + (left // a.chunk) * a.rest
        log(f"frame {f:4d} ({t:5.2f}s) {dt:5.1f}s  残り {left} 枚  見込み あと {eta / 60:5.1f} 分")
        if left and done % a.chunk == 0:
            log(f"休憩 {a.rest} 秒")
            time.sleep(a.rest)
    log(f"frames: 完了 {done} 枚 / 経過 {(time.time() - t_start) / 60:.1f} 分")


def cmd_logo(a):
    """ロゴの 3.5 秒: 黒地にロゴがふわっと現れ、最後に暗転する。"""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    os.makedirs(FRAMES, exist_ok=True)
    W, H = 1920, 1080
    if a.logo:
        logo = Image.open(a.logo).convert("RGBA")
        s = min(W * 0.42 / logo.width, H * 0.32 / logo.height)
        logo = logo.resize((int(logo.width * s), int(logo.height * s)), Image.LANCZOS)
    else:   # 仮のロゴ(指定のロゴが届いたら --logo で差し替える)
        logo = Image.new("RGBA", (900, 260), (0, 0, 0, 0))
        d = ImageDraw.Draw(logo)
        f1 = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Light.otf", 120)
        f2 = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Light.otf", 30)
        d.text((450, 110), "LOGO", font=f1, fill=(200, 255, 248, 255), anchor="mm")
        d.text((450, 215), "PLACEHOLDER", font=f2, fill=(120, 220, 210, 255), anchor="mm")
    glow = logo.filter(ImageFilter.GaussianBlur(18))
    for i in range(N_LOGO):
        t = i / TL.FPS
        a_in = min(max((t - 0.25) / 0.9, 0), 1)
        a_out = min(max((TL.LOGO_LEN - t - 0.15) / 0.6, 0), 1)
        k = (a_in * a_in * (3 - 2 * a_in)) * a_out
        frame = Image.new("RGB", (W, H), (2, 5, 12))
        x, y = (W - logo.width) // 2, (H - logo.height) // 2
        for img, mul in ((glow, 0.55), (logo, 1.0)):
            layer = img.copy()
            alpha = layer.getchannel("A").point(lambda v: int(v * k * mul))
            layer.putalpha(alpha)
            frame.paste(layer, (x, y), layer)
        frame.save(frame_path(N_MAIN + 1 + i))
    log(f"logo: {N_LOGO} 枚 ({'指定のロゴ' if a.logo else '仮のロゴ'})")


def cmd_mux(a):
    out = os.path.join(HERE, "out", a.name)
    n = len([f for f in os.listdir(FRAMES) if f.endswith(".png") and not f.endswith(".tmp.png")])
    assert n == N_MAIN + N_LOGO, f"フレームが足りない: {n} / {N_MAIN + N_LOGO}"
    cmd = ["ffmpeg", "-y", "-framerate", str(TL.FPS), "-i", os.path.join(FRAMES, "%04d.png"),
           "-i", os.path.join(HERE, "out", "audio.wav"),
           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", out]
    subprocess.run(cmd, check=True)
    log(f"mux: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("frames")
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int, default=N_MAIN)
    p.add_argument("--samples", type=int, default=8)
    p.add_argument("--samples-smoke", type=int, default=12)
    p.add_argument("--chunk", type=int, default=48)
    p.add_argument("--rest", type=int, default=240)
    p = sub.add_parser("logo")
    p.add_argument("--logo", default=None)
    p = sub.add_parser("mux")
    p.add_argument("--name", default="night_launch.mp4")
    a = ap.parse_args()
    {"frames": cmd_frames, "logo": cmd_logo, "mux": cmd_mux}[a.cmd](a)
