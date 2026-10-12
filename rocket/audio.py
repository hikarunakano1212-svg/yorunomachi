"""動画の音を Python で合成する(外部の音素材は使わない)。

    python rocket/audio.py            # → rocket/out/audio.wav (48kHz ステレオ, 23.5秒)

電子音の BGM、波、カウントダウンの電子音、点火から上昇までの轟音、タイトルの和音。
時刻は timeline.py に合わせる。
"""
import os
import sys
import wave

import numpy as np
from scipy.signal import butter, lfilter, sosfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import timeline as T  # noqa: E402

SR = 48000
N = int(T.T_TOTAL * SR)
t = np.arange(N) / SR
rng = np.random.default_rng(2026)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "audio.wav")


def midi(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def env_adsr(n, a, d, s, r, sustain_len):
    """サンプル数で ADSR。"""
    A, D, R = int(a * SR), int(d * SR), int(r * SR)
    S = max(int(sustain_len * SR) - A - D, 0)
    e = np.concatenate([np.linspace(0, 1, A, endpoint=False), np.linspace(1, s, D, endpoint=False),
                        np.full(S, s), np.linspace(s, 0, R)])
    return e[:n] if len(e) >= n else np.pad(e, (0, n - len(e)))


def ramp(points):
    """[(秒, 値), ...] を折れ線でつないだ包絡。"""
    xs, ys = zip(*points)
    return np.interp(t, xs, ys)


def lp(x, fc, order=2):
    sos = butter(order, min(fc, SR * 0.45), "low", fs=SR, output="sos")
    return sosfilt(sos, x, axis=0)


def hp(x, fc, order=2):
    sos = butter(order, fc, "high", fs=SR, output="sos")
    return sosfilt(sos, x, axis=0)


def bp(x, lo, hi, order=2):
    sos = butter(order, [lo, hi], "band", fs=SR, output="sos")
    return sosfilt(sos, x, axis=0)


def place(buf, start, sig, pan=0.0, gain=1.0):
    """buf (N,2) の start 秒の位置に sig を足す。pan: -1 左 〜 +1 右。"""
    i = int(start * SR)
    if i >= N:
        return
    sig = sig[: N - i] * gain
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:i + len(sig), 0] += sig * l
    buf[i:i + len(sig), 1] += sig * r


def reverb(x, mix=0.3, size=1.0):
    """シュレーダー型の簡単なリバーブ(左右で遅延を少し変える)。"""
    out = np.zeros_like(x)
    for ch in range(2):
        s = x[:, ch]
        acc = np.zeros_like(s)
        for d, g in zip([1557, 1617, 1491, 1422, 1277, 1356], [0.84, 0.83, 0.82, 0.81, 0.80, 0.79]):
            D = int(d * size) + ch * 23
            a = np.zeros(D + 1)
            a[0], a[D] = 1.0, -g
            acc += lfilter([1.0], a, s)
        for d in (225, 556, 441):
            D = d + ch * 7
            b = np.zeros(D + 1)
            b[0], b[D] = -0.5, 1.0
            a = np.zeros(D + 1)
            a[0], a[D] = 1.0, -0.5
            acc = lfilter(b, a, acc)
        out[:, ch] = acc / 6
    return x * (1 - mix) + lp(out, 6000) * mix


def saw(f, n, detune=0.0):
    ph = np.cumsum(np.full(n, f * (1 + detune)) / SR)
    return 2 * (ph % 1.0) - 1


def tone(f, dur, wave_="sine", a=0.005, d=0.1, s=0.6, r=0.2, cutoff=None):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    if wave_ == "sine":
        x = np.sin(2 * np.pi * f * tt)
    elif wave_ == "saw":
        x = (saw(f, n, -0.004) + saw(f, n, 0.004)) * 0.5
    elif wave_ == "square":
        x = np.sign(np.sin(2 * np.pi * f * tt)) * 0.6
    else:
        x = np.sin(2 * np.pi * f * tt)
    if cutoff:
        x = lp(x, cutoff)
    return x * env_adsr(n, a, d, s, r, dur - r)


# ---------------------------------------------------------------------------
def bgm():
    """電子音の BGM: 120 BPM、A マイナーのアルペジオ + ベース + パッド + ハイハット。"""
    buf = np.zeros((N, 2))
    bpm = 120
    beat = 60 / bpm
    step = beat / 4                                     # 16分
    chords = [[57, 60, 64, 67], [53, 57, 60, 64], [48, 52, 55, 59], [55, 59, 62, 66]]   # Am7 Fmaj7 Cmaj7 G
    bass = [45, 41, 48, 43]
    end = T.TI + 0.3
    k = 0
    while k * step < end:
        ts = k * step
        bar = int(ts / (beat * 4))
        ch = chords[bar % 4]
        order = [0, 1, 2, 3, 2, 1, 3, 2]
        note = ch[order[k % 8]] + (12 if (k // 8) % 2 else 0)
        # 走査の間はまばら、積み上げで密に
        if ts < T.RISE[0] and k % 2:
            k += 1
            continue
        cutoff = np.interp(ts, [0, 3, 8.5, 11, 15.5], [900, 1800, 5200, 2600, 3800])
        g = np.interp(ts, [0, 2.5, 8.5, 11.0, 14.5, 15.5], [0.10, 0.16, 0.20, 0.13, 0.16, 0.0])
        x = tone(midi(note), step * 0.95, "saw", a=0.003, d=0.09, s=0.25, r=0.06, cutoff=cutoff)
        place(buf, ts, x, pan=0.35 * np.sin(k * 0.7), gain=g)
        k += 1
    for b4 in range(int(end / (beat * 4)) + 1):     # ベース(8分で刻む)
        for e8 in range(8):
            ts = b4 * beat * 4 + e8 * beat / 2
            if ts > end or ts < T.RISE[0] - 0.5:
                continue
            f = midi(bass[b4 % 4] - 12)
            x = tone(f, beat * 0.45, "saw", a=0.004, d=0.12, s=0.5, r=0.05, cutoff=420)
            x += 0.6 * tone(f, beat * 0.45, "sine", a=0.004, d=0.1, s=0.6, r=0.05)
            g = np.interp(ts, [3, 5, 8.5, 11, 15.5], [0.10, 0.22, 0.24, 0.12, 0.0])
            place(buf, ts, x, gain=g)
    for k4 in range(int(end / beat) + 1):           # キック(積み上げから)
        ts = k4 * beat
        if not (T.BUILD[0] - 0.3 <= ts <= T.DISSOLVE[0] + 0.2) and not (T.ARMS[0] <= ts <= T.TI - 0.3):
            continue
        n = int(0.35 * SR)
        tt = np.arange(n) / SR
        f = 45 + 110 * np.exp(-tt * 30)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 9)
        place(buf, ts, x, gain=0.45)
    for k8 in range(int(end / (beat / 2)) + 1):     # ハイハット
        ts = k8 * beat / 2 + beat / 4
        if not (T.RISE[0] <= ts <= T.TI - 0.2):
            continue
        n = int(0.05 * SR)
        x = hp(rng.normal(0, 1, n), 7000) * np.exp(-np.arange(n) / SR * 80)
        place(buf, ts, x, pan=0.4, gain=0.05)
    # パッド(図面が溶けるところと待機中)
    pad = np.zeros(N)
    for note in (57, 64, 67, 71, 74):
        pad += saw(midi(note), N, rng.uniform(-0.003, 0.003))
    pad = lp(pad, 1400) * ramp([(0, 0), (T.DISSOLVE[0], 0), (T.DISSOLVE[1], 0.05), (T.TI, 0.04),
                                (T.TI + 1.5, 0.0), (T.T_TOTAL, 0.0)])
    buf[:, 0] += pad
    buf[:, 1] += np.roll(pad, 300)
    return buf


def sfx():
    buf = np.zeros((N, 2))
    # 走査の上昇音(ノイズのスイープ)
    a, b = T.SCAN
    n = int((b - a + 0.6) * SR)
    tt = np.arange(n) / SR
    noise = rng.normal(0, 1, n)
    f = np.interp(tt, [0, b - a], [300, 5000])
    sw = np.zeros(n)
    seg = 2400
    for i in range(0, n, seg):
        fc = f[min(i, n - 1)]
        sw[i:i + seg] = bp(noise[max(0, i - 2000):i + seg], fc * 0.7, fc * 1.3)[-len(sw[i:i + seg]):]
    sw *= np.interp(tt, [0, 0.3, b - a, b - a + 0.6], [0, 1, 0.7, 0])
    place(buf, a, sw, gain=0.12)
    # ワイヤーが立ち上がる「ブン」(グループごとに少しずらす)
    for i in range(6):
        x = tone(midi(69 + [0, 7, 12, 3, 10, 15][i]), 0.6, "sine", a=0.01, d=0.2, s=0.2, r=0.3)
        place(buf, T.RISE[0] + 0.25 * i, x, pan=-0.6 + 0.24 * i, gain=0.06)
    # 光の粒のきらめき
    for k in range(70):
        ts = rng.uniform(T.BUILD[0], T.BUILD[1] + 0.6)
        x = tone(rng.uniform(1800, 4200), 0.12, "sine", a=0.002, d=0.05, s=0.2, r=0.06)
        place(buf, ts, x, pan=rng.uniform(-0.9, 0.9), gain=0.035)
    # マス目が溶けるデジタル音(短いブリップ)
    for k in range(60):
        ts = rng.uniform(T.DISSOLVE[0], T.DISSOLVE[1])
        x = tone(rng.choice([880, 1320, 1760, 2640]), 0.04, "square", a=0.001, d=0.02, s=0.3, r=0.015)
        place(buf, ts, x, pan=rng.uniform(-0.8, 0.8), gain=0.03)
    # 照明塔の点灯(低い「ガチャン」)
    for i, ts in enumerate(T.LIGHT_ON):
        n = int(0.3 * SR)
        tt = np.arange(n) / SR
        x = lp(rng.normal(0, 1, n), 900) * np.exp(-tt * 25) + 0.5 * np.sin(2 * np.pi * 70 * tt) * np.exp(-tt * 18)
        place(buf, ts, x, pan=[-0.7, 0.7, -0.4, 0.4][i], gain=0.18)
    # アームの離脱(機械のうなり)
    a, b = T.ARMS
    n = int((b - a) * SR)
    tt = np.arange(n) / SR
    hum = np.sin(2 * np.pi * (90 + 20 * tt / (b - a)) * tt) + 0.3 * np.sin(2 * np.pi * 180 * tt)
    hum *= np.interp(tt, [0, 0.3, b - a - 0.4, b - a], [0, 1, 1, 0])
    place(buf, a, lp(hum, 600), pan=0.4, gain=0.07)
    # カウントダウンの電子音
    for ts in T.COUNTS:
        x = tone(1000, 0.16, "sine", a=0.002, d=0.03, s=0.8, r=0.05)
        x += 0.25 * tone(2000, 0.16, "sine", a=0.002, d=0.03, s=0.8, r=0.05)
        place(buf, ts, x, gain=0.22)
    for j in range(2):                                   # 点火: 高い2連
        x = tone(1500, 0.12, "sine", a=0.002, d=0.03, s=0.8, r=0.04)
        place(buf, T.TI + j * 0.16, x, gain=0.22)
    x = tone(1200, 0.5, "sine", a=0.002, d=0.1, s=0.6, r=0.3)
    place(buf, T.TL, x, gain=0.15)
    return buf


def waves():
    """波: 低域を落としたノイズを、ゆっくり寄せて返すように揺らす。"""
    out = np.zeros((N, 2))
    for ch in range(2):
        nz = rng.normal(0, 1, N)
        body = lp(hp(nz, 150), 1800)
        hiss = hp(nz, 3500) * 0.25
        swell = np.zeros(N)
        tt0 = rng.uniform(0, 1.5)
        while tt0 < T.T_TOTAL:
            per = rng.uniform(4.0, 6.5)
            i0 = int(tt0 * SR)
            n = int(per * SR)
            u = np.arange(n) / n
            shape = np.where(u < 0.35, (u / 0.35) ** 2, np.exp(-(u - 0.35) * 5))
            swell[i0:i0 + n] += shape[: max(0, min(n, N - i0))]
            tt0 += per * rng.uniform(0.7, 0.95)
        out[:, ch] = (body + hiss * swell) * (0.25 + swell)
    level = ramp([(0, 0), (T.DISSOLVE[0], 0), (T.DISSOLVE[1], 0.05), (T.TI, 0.05), (T.TL + 0.5, 0.02),
                  (T.T_CUT - 0.01, 0.02), (T.T_CUT, 0.06), (T.T_END, 0.06), (T.T_TOTAL, 0.0)])
    return out * level[:, None]


def rumble():
    """点火から上昇までの轟音: 低い唸り + ばりばりと割れる音 + 高域の噴射音。"""
    out = np.zeros((N, 2))
    for ch in range(2):
        nz = rng.normal(0, 1, N)
        low = lp(np.cumsum(nz) * 0.02, 120, 2)               # 茶色いノイズ
        low = hp(low, 18)
        mid = bp(nz, 120, 900) * 0.6
        crack = np.zeros(N)
        k = np.where(rng.random(N) < 120 / SR)[0]             # 1秒に約120個のはじける音
        crack[k] = rng.normal(0, 1, len(k)) * 6
        crack = lp(hp(crack, 200), 2500)
        crack = lfilter([1.0], [1.0, -0.94], crack) * 0.08
        hiss = hp(nz, 2500) * 0.15
        out[:, ch] = low * 3.0 + mid + crack + hiss
    out /= np.abs(out).max() + 1e-9
    level = ramp([(0, 0), (T.TI, 0), (T.TI + 0.4, 0.35), (T.TL - 0.05, 0.42), (T.TL + 0.35, 0.95),
                  (T.T_CUT - 0.01, 0.9), (T.T_CUT, 0.6), (T.T_END, 0.42), (T.T_END + 2.5, 0.0),
                  (T.T_TOTAL, 0.0)])
    out *= level[:, None]
    # 海上カメラ以降は遠くの音(高域を落とす)
    i = int(T.T_CUT * SR)
    far = lp(out, 1500) * 1.1
    out[i:] = far[i:]
    return out


def title_chord():
    """タイトルの和音: A のメジャー9(柔らかい立ち上がり + 長い余韻)、ロゴでチャイム。"""
    buf = np.zeros((N, 2))
    dur = T.T_TOTAL - T.T_TITLE
    for j, note in enumerate((45, 57, 64, 68, 71, 76)):
        x = tone(midi(note), dur, "saw", a=0.9, d=1.0, s=0.7, r=2.2, cutoff=2400)
        x += 0.6 * tone(midi(note), dur, "sine", a=0.6, d=1.0, s=0.7, r=2.2)
        place(buf, T.T_TITLE + 0.03 * j, x, pan=-0.6 + 0.24 * j, gain=0.08)
    for j, note in enumerate((81, 88, 93)):
        x = tone(midi(note), 2.6, "sine", a=0.003, d=0.5, s=0.25, r=1.8)
        place(buf, T.T_END + 0.35 + 0.09 * j, x, pan=(-0.3, 0.3, 0.0)[j], gain=0.08)
    return buf


def main():
    mix = bgm() + sfx()
    mix = reverb(mix, mix=0.22, size=1.0)
    mix += waves() + rumble() * 0.9
    mix += reverb(title_chord(), mix=0.45, size=1.3)
    # 全体の頭と終わりを整え、ピークを -1 dBFS 付近へ
    fade = ramp([(0, 0), (0.05, 1), (T.T_TOTAL - 0.6, 1), (T.T_TOTAL, 0)])
    mix *= fade[:, None]
    mix = np.tanh(mix * 1.1) / np.tanh(1.1)
    mix *= 0.89 / (np.abs(mix).max() + 1e-9)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with wave.open(OUT, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix * 32767).astype("<i2").tobytes())
    print(OUT, f"{T.T_TOTAL:.1f}s")


if __name__ == "__main__":
    main()
