// Web Audio による手続き生成サウンド(音声ファイルなし)
// 雨音・エンジン・サイレン・銃声・衝突音、そしてカーラジオ(シティポップ/シンセウェーブ)
export class Audio {
  constructor() {
    this.ctx = null;
    this.station = 0;
    this.stations = [
      { name: 'FM ヨルノ 88.1 ― シティポップ', bpm: 104, style: 'citypop' },
      { name: 'NEON WAVE 76.5 ― シンセウェーブ', bpm: 96, style: 'synth' },
      { name: 'ラジオ OFF', style: null },
    ];
  }

  start() {
    if (this.ctx) return;
    const ctx = this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    this.master = ctx.createGain(); this.master.gain.value = 0.8;
    const comp = ctx.createDynamicsCompressor(); comp.threshold.value = -16; comp.ratio.value = 4;
    this.master.connect(comp).connect(ctx.destination);
    // 街の反響(短いディレイ)
    this.echo = ctx.createDelay(1); this.echo.delayTime.value = 0.13;
    const fb = ctx.createGain(); fb.gain.value = 0.32;
    const elp = ctx.createBiquadFilter(); elp.type = 'lowpass'; elp.frequency.value = 2200;
    this.echo.connect(elp).connect(fb).connect(this.echo);
    elp.connect(this.master);
    this.sfx = ctx.createGain(); this.sfx.connect(this.master); this.sfx.connect(this.echo);

    this.noise = this.makeNoise(3);
    // 雨
    this.rain = this.loopNoise('bandpass', 2600, 0.4, 0.0);
    this.rainLow = this.loopNoise('lowpass', 380, 0.7, 0.0);
    this.rain.g.gain.value = 0.16; this.rainLow.g.gain.value = 0.12;
    // 車内では外の音をこもらせる
    this.outside = ctx.createBiquadFilter(); this.outside.type = 'lowpass'; this.outside.frequency.value = 20000;
    this.rain.out.disconnect(); this.rainLow.out.disconnect();
    this.rain.out.connect(this.outside); this.rainLow.out.connect(this.outside);
    this.outside.connect(this.master);

    // エンジン
    this.eng = ctx.createOscillator(); this.eng.type = 'sawtooth';
    this.eng2 = ctx.createOscillator(); this.eng2.type = 'square';
    this.engF = ctx.createBiquadFilter(); this.engF.type = 'lowpass'; this.engF.frequency.value = 500; this.engF.Q.value = 3;
    this.engG = ctx.createGain(); this.engG.gain.value = 0;
    this.eng.connect(this.engF); this.eng2.connect(this.engF); this.engF.connect(this.engG).connect(this.master);
    this.eng.start(); this.eng2.start();
    // サイレン
    this.sir = ctx.createOscillator(); this.sir.type = 'triangle';
    this.sirLfo = ctx.createOscillator(); this.sirLfo.frequency.value = 0.55;
    const sirDepth = ctx.createGain(); sirDepth.gain.value = 190;
    this.sirLfo.connect(sirDepth).connect(this.sir.frequency);
    this.sir.frequency.value = 780;
    this.sirG = ctx.createGain(); this.sirG.gain.value = 0;
    this.sir.connect(this.sirG).connect(this.outside);
    this.sir.start(); this.sirLfo.start();
    // ラジオ
    this.radioOut = ctx.createGain(); this.radioOut.gain.value = 0;
    const rf = ctx.createBiquadFilter(); rf.type = 'highpass'; rf.frequency.value = 90;
    this.radioOut.connect(rf).connect(this.master);
    this.radioStep = 0; this.nextNote = 0;
    this.radioTimer = setInterval(() => this.scheduleRadio(), 60);
  }

  makeNoise(sec) {
    const b = this.ctx.createBuffer(1, this.ctx.sampleRate * sec, this.ctx.sampleRate);
    const d = b.getChannelData(0);
    let last = 0;
    for (let i = 0; i < d.length; i++) { const w = Math.random() * 2 - 1; last = last * 0.6 + w * 0.4; d[i] = last * 1.4; }
    return b;
  }
  loopNoise(type, freq, q, gain) {
    const s = this.ctx.createBufferSource(); s.buffer = this.noise; s.loop = true;
    const f = this.ctx.createBiquadFilter(); f.type = type; f.frequency.value = freq; f.Q.value = q;
    const g = this.ctx.createGain(); g.gain.value = gain;
    s.connect(f).connect(g).connect(this.master); s.start();
    return { s, f, g, out: g };
  }
  burst(dur, type, freq, gain, when = 0, q = 1, dest = this.sfx) {
    if (!(gain > 0.001)) return; // 指数ランプは 0 を扱えない
    const t = this.ctx.currentTime + when;
    const s = this.ctx.createBufferSource(); s.buffer = this.noise;
    s.playbackRate.value = 0.8 + Math.random() * 0.4;
    const f = this.ctx.createBiquadFilter(); f.type = type; f.frequency.value = freq; f.Q.value = q;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(gain, t); g.gain.exponentialRampToValueAtTime(0.001, t + dur);
    s.connect(f).connect(g).connect(dest);
    s.start(t, Math.random() * 2); s.stop(t + dur + 0.05);
  }
  tone(freq, dur, type = 'sine', gain = 0.2, when = 0, slideTo = null, dest = this.sfx) {
    if (!(gain > 0.001)) return;
    const t = this.ctx.currentTime + when;
    const o = this.ctx.createOscillator(); o.type = type; o.frequency.setValueAtTime(freq, t);
    if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t + dur);
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(gain, t + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    o.connect(g).connect(dest); o.start(t); o.stop(t + dur + 0.05);
  }
  vol(pos) {
    if (!pos || !this.listener) return 1;
    const d = Math.hypot(pos.x - this.listener.x, pos.z - this.listener.z);
    return Math.max(0, 1 - d / 60);
  }

  // ---------- 効果音
  gunshot() {
    if (!this.ctx) return;
    this.burst(0.18, 'lowpass', 4200, 0.9);
    this.burst(0.5, 'lowpass', 700, 0.5);
    this.tone(140, 0.2, 'sine', 0.7, 0, 40);
  }
  empty() { if (this.ctx) this.tone(1800, 0.04, 'square', 0.05); }
  reload() {
    if (!this.ctx) return;
    this.burst(0.05, 'bandpass', 2500, 0.3, 0.05, 4);
    this.burst(0.06, 'bandpass', 1800, 0.35, 0.55, 5);
    this.burst(0.05, 'bandpass', 3000, 0.3, 0.75, 5);
  }
  crash(a) {
    if (!this.ctx) return;
    this.burst(0.5 + a * 0.4, 'lowpass', 900 + a * 1500, 0.5 + a * 0.5);
    this.tone(90, 0.3, 'sine', 0.4 * a, 0, 35);
    if (a > 0.4) this.burst(0.6, 'highpass', 5000, 0.15 * a, 0.05); // ガラス
  }
  thud(pos) { if (this.ctx) { const v = this.vol(pos); this.tone(110, 0.18, 'sine', 0.5 * v, 0, 50); this.burst(0.12, 'lowpass', 600, 0.4 * v); } }
  hitMarker() { if (this.ctx) this.tone(2200, 0.05, 'triangle', 0.08); }
  horn(pos) {
    if (!this.ctx) return;
    const v = this.vol(pos) * 0.12;
    if (v <= 0) return;
    this.tone(415, 0.35, 'square', v, 0); this.tone(523, 0.35, 'square', v * 0.8, 0);
  }
  scream(pos, d) {
    if (!this.ctx) return;
    const v = Math.max(0, 1 - d / 40) * 0.06;
    if (v <= 0.005) return;
    const t = this.ctx.currentTime;
    const o = this.ctx.createOscillator(); o.type = 'sawtooth';
    const base = 500 + Math.random() * 400;
    o.frequency.setValueAtTime(base, t); o.frequency.linearRampToValueAtTime(base * 1.4, t + 0.15); o.frequency.linearRampToValueAtTime(base * 0.9, t + 0.6);
    const f = this.ctx.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = 1300; f.Q.value = 3;
    const g = this.ctx.createGain(); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(v, t + 0.05); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.65);
    o.connect(f).connect(g).connect(this.sfx); o.start(t); o.stop(t + 0.7);
  }
  step(run) { if (this.ctx) this.burst(0.07, 'bandpass', run ? 1400 : 1100, run ? 0.09 : 0.05, 0, 1.5); }
  door() { if (this.ctx) { this.burst(0.12, 'lowpass', 800, 0.5); this.tone(180, 0.1, 'sine', 0.3, 0, 90); } }
  cash() {
    if (!this.ctx) return;
    [1318, 1760, 2637].forEach((f, i) => this.tone(f, 0.35, 'triangle', 0.12, i * 0.06));
  }
  jingle(good = true) {
    if (!this.ctx) return;
    const notes = good ? [523, 659, 784, 1047, 1319] : [392, 330, 277, 220];
    notes.forEach((f, i) => { this.tone(f, 0.5, 'triangle', 0.15, i * 0.11); this.tone(f / 2, 0.5, 'sine', 0.1, i * 0.11); });
  }
  starUp() { if (this.ctx) { this.tone(880, 0.12, 'square', 0.06); this.tone(1175, 0.2, 'square', 0.06, 0.1); } }
  pager() { if (this.ctx) [0, 0.18].forEach((w) => this.tone(1400, 0.12, 'square', 0.05, w)); }

  // ---------- 毎フレームの連続音
  update(state) {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.listener = state.pos;
    const inCar = state.inCar;
    this.outside.frequency.setTargetAtTime(inCar ? 900 : 20000, t, 0.1);
    this.rain.g.gain.setTargetAtTime(inCar ? 0.35 : 0.16, t, 0.3);
    const s = Math.min(1, Math.abs(state.speed) / 40);
    const rpm = inCar ? 38 + s * 90 + (state.throttle > 0 ? 18 : 0) : 0;
    this.eng.frequency.setTargetAtTime(Math.max(20, rpm), t, 0.08);
    this.eng2.frequency.setTargetAtTime(Math.max(20, rpm * 0.5), t, 0.08);
    this.engF.frequency.setTargetAtTime(300 + s * 1400 + (state.throttle > 0 ? 400 : 0), t, 0.1);
    this.engG.gain.setTargetAtTime(inCar ? 0.05 + s * 0.05 : 0, t, 0.15);
    const sv = state.policeDist < 1e8 ? Math.max(0, 1 - state.policeDist / 140) : 0;
    this.sirG.gain.setTargetAtTime(sv * 0.07, t, 0.2);
    const st = this.stations[this.station];
    this.radioOut.gain.setTargetAtTime(inCar && st.style ? 0.5 : 0, t, 0.4);
  }

  nextStation() {
    this.station = (this.station + 1) % this.stations.length;
    this.radioStep = 0;
    return this.stations[this.station].name;
  }

  // ---------- カーラジオ(ステップシーケンサ)
  scheduleRadio() {
    if (!this.ctx) return;
    const st = this.stations[this.station];
    if (!st.style) return;
    const spb = 60 / st.bpm / 4; // 16分音符
    const now = this.ctx.currentTime;
    if (this.nextNote < now) this.nextNote = now + 0.05;
    while (this.nextNote < now + 0.25) {
      this.playStep(st.style, this.radioStep, this.nextNote - now, spb);
      this.radioStep++;
      this.nextNote += spb;
    }
  }

  playStep(style, step, when, spb) {
    const out = this.radioOut;
    const bar = Math.floor(step / 16) % 4, s = step % 16;
    const mtof = (m) => 440 * Math.pow(2, (m - 69) / 12);
    if (style === 'citypop') {
      // 丸サ進行: Fmaj7 - E7 - Am7 - Gm7 C7
      const chords = [[53, 57, 60, 64], [52, 56, 59, 62], [57, 60, 64, 67], s < 8 ? [55, 58, 62, 65] : [48, 52, 55, 58]];
      const bass = [41, 40, 45, bar === 3 && s >= 8 ? 36 : 43];
      const ch = chords[bar];
      if (s === 0 || s === 6 || s === 10 || (s === 8 && bar === 3)) ch.forEach((m) => this.ep(mtof(m + 12), spb * 5, 0.045, when, out));
      if ([0, 3, 6, 8, 11, 14].includes(s)) this.tone(mtof(bass[bar] - 12 + (s === 11 ? 12 : 0)), spb * 1.8, 'triangle', 0.22, when, null, out);
      if (s === 0 || s === 8 || s === 10) this.tone(150, 0.14, 'sine', 0.5, when, 45, out);
      if (s === 4 || s === 12) this.burst(0.16, 'bandpass', 1900, 0.28, when, 0.9, out);
      if (s % 2 === 0) this.burst(0.04, 'highpass', 8000, s % 4 === 2 ? 0.1 : 0.05, when, 1, out);
      // メロディ(和音構成音から)
      const mel = [0, -1, 3, -1, 2, -1, 1, 2, 3, -1, -1, 2, 1, -1, 0, -1];
      const idx = mel[(s + bar * 5) % 16];
      if (idx >= 0 && (step >> 6) % 2 === 1) this.tone(mtof(ch[idx] + 24), spb * 2.2, 'square', 0.025, when, null, out);
    } else {
      // シンセウェーブ: Am - F - C - G
      const roots = [57, 53, 60, 55];
      const r = roots[bar];
      const tri = [r, r + (bar === 0 ? 3 : 4), r + 7, r + 12];
      this.tone(mtof(tri[s % 4] + 12), spb * 0.9, 'sawtooth', 0.03, when, null, out);
      if (s % 2 === 0) this.tone(mtof(r - 24), spb * 1.5, 'sawtooth', 0.07, when, null, out);
      if (s === 0 || s === 8) this.tone(160, 0.2, 'sine', 0.55, when, 40, out);
      if (s === 4 || s === 12) { this.burst(0.35, 'bandpass', 1500, 0.35, when, 0.6, out); }
      if (s === 0) tri.forEach((m) => this.tone(mtof(m), spb * 16, 'triangle', 0.03, when, null, out));
    }
  }
  // エレピ風(FM)
  ep(freq, dur, gain, when, out) {
    const t = this.ctx.currentTime + when;
    const c = this.ctx.createOscillator(); c.frequency.value = freq;
    const m = this.ctx.createOscillator(); m.frequency.value = freq;
    const mg = this.ctx.createGain(); mg.gain.setValueAtTime(freq * 1.2, t); mg.gain.exponentialRampToValueAtTime(freq * 0.05, t + 0.3);
    m.connect(mg).connect(c.frequency);
    const g = this.ctx.createGain(); g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(gain, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    c.connect(g).connect(out); c.start(t); m.start(t); c.stop(t + dur + 0.05); m.stop(t + dur + 0.05);
  }
}
