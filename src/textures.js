// キャンバスで手続き生成するテクスチャ類(外部画像ファイル不要)
import * as THREE from 'three';
import { rand, randi, pick } from './util.js';

function canvas(w, h) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  return [c, c.getContext('2d')];
}

function tex(c, { srgb = true, repeat = false } = {}) {
  const t = new THREE.CanvasTexture(c);
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  if (repeat) t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = 8;
  return t;
}

// ビル外壁: 1枚 = 横8窓 × 縦8階 (24m × 28m)。map と emissiveMap を対で作る
export const FACADE_W = 24, FACADE_H = 28;
export function makeFacade(style) {
  const S = 512;
  const [c, g] = canvas(S, S);
  const [e, ge] = canvas(S, S);
  const cols = 8, rows = 8, cw = S / cols, rh = S / rows;
  const wall = { concrete: '#6d6f73', tile: '#8a7f70', dark: '#23262d', white: '#a9adb0' }[style];
  g.fillStyle = wall; g.fillRect(0, 0, S, S);
  ge.fillStyle = '#000'; ge.fillRect(0, 0, S, S);
  // 外壁の汚れ・タイル目地
  for (let i = 0; i < 2500; i++) {
    g.fillStyle = `rgba(0,0,0,${rand(0.02, 0.07)})`;
    g.fillRect(rand(0, S), rand(0, S), rand(1, 4), rand(2, 30));
  }
  if (style === 'tile') {
    g.strokeStyle = 'rgba(0,0,0,.12)'; g.lineWidth = 1;
    for (let y = 0; y < S; y += 8) { g.beginPath(); g.moveTo(0, y); g.lineTo(S, y); g.stroke(); }
  }
  const warm = ['#ffd9a0', '#ffe7c2', '#ffcf8a', '#fff1d6'];
  const cool = ['#d8f0ff', '#e9f7ff', '#c8ffe9'];
  for (let r = 0; r < rows; r++) {
    for (let k = 0; k < cols; k++) {
      const x = k * cw, y = r * rh;
      const glassy = style === 'dark';
      const ww = glassy ? cw - 6 : cw * 0.5, wh = glassy ? rh - 10 : rh * 0.48;
      const wx = x + (cw - ww) / 2, wy = y + (rh - wh) / 2 - 2;
      // 窓枠
      g.fillStyle = 'rgba(20,20,24,.9)'; g.fillRect(wx - 2, wy - 2, ww + 4, wh + 4);
      const lit = Math.random() < (glassy ? 0.22 : 0.3);
      if (lit) {
        const col = Math.random() < 0.6 ? pick(warm) : pick(cool);
        g.fillStyle = col; g.fillRect(wx, wy, ww, wh);
        const inten = rand(0.3, 0.75);
        ge.globalAlpha = inten; ge.fillStyle = col; ge.fillRect(wx, wy, ww, wh);
        // カーテン・ブラインド
        if (Math.random() < 0.5) {
          ge.globalAlpha = inten * 0.5; ge.fillStyle = '#000';
          const bw = rand(0.2, 0.6) * ww;
          ge.fillRect(Math.random() < 0.5 ? wx : wx + ww - bw, wy, bw, wh);
          g.fillStyle = 'rgba(60,40,30,.5)'; g.fillRect(wx, wy, bw, wh);
        }
        if (Math.random() < 0.35) {
          ge.globalAlpha = inten * 0.35; ge.fillStyle = '#000';
          for (let yy = wy; yy < wy + wh; yy += 4) ge.fillRect(wx, yy, ww, 1.5);
        }
        ge.globalAlpha = 1;
      } else {
        const grd = g.createLinearGradient(wx, wy, wx + ww, wy + wh);
        grd.addColorStop(0, '#1b2230'); grd.addColorStop(1, '#0c0f16');
        g.fillStyle = grd; g.fillRect(wx, wy, ww, wh);
      }
      if (!glassy) { // 窓の桟
        g.fillStyle = 'rgba(25,25,28,.85)'; g.fillRect(wx + ww / 2 - 1, wy, 2, wh);
        ge.fillStyle = '#000'; ge.fillRect(wx + ww / 2 - 1, wy, 2, wh);
      }
      // エアコン室外機
      if (!glassy && Math.random() < 0.18) {
        g.fillStyle = '#b8b8b2'; g.fillRect(wx + ww + 2, wy + wh - 12, 12, 10);
      }
    }
  }
  return { map: tex(c, { repeat: true }), emissive: tex(e, { repeat: true }) };
}

// 1階の店舗ファサード: アルミの枠・ガラス越しの店内(棚・照明)・自動ドア・シャッター
export function makeStorefronts() {
  const W = 2048, H = 256;               // 1 枚 = 48m × 4.5m、6m 幅の店が 8 軒
  const [c, g] = canvas(W, H);
  const [e, ge] = canvas(W, H);
  ge.fillStyle = '#000'; ge.fillRect(0, 0, W, H);
  const n = 8, cw = W / n;
  for (let i = 0; i < n; i++) {
    const x = i * cw;
    const kind = pick(['shop', 'shop', 'cafe', 'conbini', 'shutter', 'office']);
    // 建物の腰壁と枠
    g.fillStyle = '#3b3d40'; g.fillRect(x, 0, cw, H);
    if (kind === 'shutter') {
      g.fillStyle = '#8b8e91'; g.fillRect(x + 8, 20, cw - 16, H - 24);
      for (let y = 24; y < H; y += 6) { g.fillStyle = 'rgba(0,0,0,.22)'; g.fillRect(x + 8, y, cw - 16, 2); g.fillStyle = 'rgba(255,255,255,.08)'; g.fillRect(x + 8, y + 2, cw - 16, 1); }
      for (let k = 0; k < 30; k++) { g.fillStyle = `rgba(40,40,40,${rand(0.05, 0.2)})`; g.fillRect(x + rand(10, cw - 30), rand(40, H - 20), rand(4, 30), rand(2, 14)); } // 落書き・汚れ
      continue;
    }
    const inner = { shop: ['#e9dcc4', '#d8d2c8'], cafe: ['#f0c894', '#d9a86a'], conbini: ['#f6fbff', '#eef6ff'], office: ['#dde6ee', '#c9d3dc'] }[kind];
    const gx = x + 10, gy = 18, gw = cw - 20, gh = H - 26;
    // 店内: 奥の壁・天井の照明・棚・人影
    const grd = g.createLinearGradient(0, gy, 0, gy + gh);
    grd.addColorStop(0, inner[0]); grd.addColorStop(1, inner[1]);
    g.fillStyle = grd; g.fillRect(gx, gy, gw, gh);
    ge.fillStyle = grd; ge.globalAlpha = 0.85; ge.fillRect(gx, gy, gw, gh); ge.globalAlpha = 1;
    for (let k = 0; k < 5; k++) { ge.fillStyle = '#fff'; ge.fillRect(gx + 10 + k * gw / 5, gy + 6, gw / 5 - 24, 4); g.fillStyle = '#fff'; g.fillRect(gx + 10 + k * gw / 5, gy + 6, gw / 5 - 24, 4); }
    if (kind !== 'office') {
      for (let sx = gx + 12; sx < gx + gw - 30; sx += rand(40, 70)) {   // 陳列棚
        const sh = rand(80, 150), sw = rand(26, 44);
        g.fillStyle = '#6d6a66'; g.fillRect(sx, gy + gh - sh, sw, sh);
        for (let yy = gy + gh - sh + 6; yy < gy + gh - 4; yy += 16)
          for (let xx = sx + 2; xx < sx + sw - 4; xx += 5) { g.fillStyle = `hsl(${rand(0, 360)},${rand(15, 45)}%,${rand(35, 65)}%)`; g.fillRect(xx, yy, 4, 11); }
        ge.fillStyle = 'rgba(0,0,0,.45)'; ge.fillRect(sx, gy + gh - sh, sw, sh);
      }
    } else {
      g.fillStyle = '#8a8680'; g.fillRect(gx + gw * 0.3, gy + gh - 70, gw * 0.4, 36); // 受付
    }
    for (let k = 0; k < randi(0, 3); k++) { // 人影
      const px = gx + rand(20, gw - 30);
      g.fillStyle = 'rgba(40,38,40,.8)'; g.fillRect(px, gy + gh - 110, 18, 110); g.beginPath(); g.arc(px + 9, gy + gh - 120, 10, 0, 7); g.fill();
      ge.fillStyle = 'rgba(0,0,0,.7)'; ge.fillRect(px, gy + gh - 130, 18, 130);
    }
    // ガラスの映り込み(斜めのハイライト)
    g.fillStyle = 'rgba(255,255,255,.12)';
    g.beginPath(); g.moveTo(gx + gw * 0.2, gy); g.lineTo(gx + gw * 0.35, gy); g.lineTo(gx + gw * 0.15, gy + gh); g.lineTo(gx, gy + gh); g.fill();
    // アルミのサッシと自動ドア
    g.fillStyle = '#9ea3a8';
    g.fillRect(gx - 4, gy - 4, gw + 8, 5); g.fillRect(gx - 4, gy + gh - 2, gw + 8, 6);
    for (const f of [0, 0.34, 0.5, 0.66, 1]) g.fillRect(gx + gw * f - 3, gy, 6, gh);
    ge.fillStyle = '#000'; for (const f of [0, 0.34, 0.5, 0.66, 1]) ge.fillRect(gx + gw * f - 3, gy, 6, gh);
    // ポスター
    if (Math.random() < 0.6) { const px = gx + gw * rand(0.05, 0.2); g.fillStyle = `hsl(${rand(0, 360)},50%,55%)`; g.fillRect(px, gy + 40, 34, 48); g.fillStyle = 'rgba(255,255,255,.7)'; g.fillRect(px + 4, gy + 70, 26, 4); }
  }
  return { map: tex(c, { repeat: true }), emissive: tex(e, { repeat: true }) };
}

// 縦看板・横看板のアトラス
const V_SIGNS = ['居酒屋', 'ラーメン', 'カラオケ', '焼肉', '質', '薬', '麻雀', 'スナック夜霧', '喫茶', 'ホテル', '寿司', '金融', '占い', 'BAR', '餃子', '整体'];
const H_SIGNS = ['コンビニ ヨルマート', '居酒屋 ほろ酔い', 'ラーメン 龍', '牛丼 ほし屋', '漫画喫茶', 'カラオケ 歌宴', '不動産', '中華 飯店',
  '焼鳥 とり吉', '立ち食いそば', 'ゲームセンター', '古着 屋根裏', '歯科医院', 'クリーニング', '回転寿司', 'ドラッグストア'];
const NEON = ['#ff2e88', '#35e8ff', '#ffb62e', '#8cff5a', '#ff4b3a', '#c070ff', '#ffffff', '#ffe23a'];

function fitText(g, text, max, weight, font, start) {
  let size = start;
  do { g.font = `${weight} ${size}px ${font}`; size -= 2; } while (g.measureText(text).width > max && size > 10);
}

export function makeSignAtlas() {
  // 縦看板: 128x512 セル × 8列 × 2行、横看板: 512x128 セル × 2列 × 8行
  const [vc, vg] = canvas(1024, 1024);
  const [hc, hg] = canvas(1024, 1024);
  const font = '"Zen Kaku Gothic New", "Hiragino Sans", "Yu Gothic", sans-serif';
  V_SIGNS.forEach((t, i) => {
    const x = (i % 8) * 128, y = Math.floor(i / 8) * 512;
    const col = NEON[i % NEON.length];
    const inverted = i % 3 === 0;
    vg.fillStyle = inverted ? col : '#111';
    vg.fillRect(x + 4, y + 4, 120, 504);
    vg.strokeStyle = inverted ? '#fff' : col; vg.lineWidth = 5;
    vg.strokeRect(x + 10, y + 10, 108, 492);
    vg.fillStyle = inverted ? '#111' : col;
    vg.shadowColor = col; vg.shadowBlur = inverted ? 0 : 14;
    const chars = [...t];
    const step = Math.min(96, 470 / chars.length);
    vg.font = `900 ${Math.floor(step * 0.86)}px ${font}`;
    vg.textAlign = 'center'; vg.textBaseline = 'middle';
    chars.forEach((ch, k) => vg.fillText(ch, x + 64, y + 30 + step * (k + 0.5) + (470 - step * chars.length) / 2));
    vg.shadowBlur = 0;
  });
  H_SIGNS.forEach((t, i) => {
    const x = (i % 2) * 512, y = Math.floor(i / 2) * 128;
    const col = NEON[(i * 3) % NEON.length];
    const bg = i % 2 === 0 ? '#cfc8b4' : '#141418';
    hg.fillStyle = bg; hg.fillRect(x + 3, y + 3, 506, 122);
    hg.fillStyle = col; hg.fillRect(x + 3, y + 3, 506, 14);
    hg.fillStyle = i % 2 === 0 ? '#1a1a1a' : col;
    hg.shadowColor = col; hg.shadowBlur = i % 2 === 0 ? 0 : 12;
    hg.textAlign = 'center'; hg.textBaseline = 'middle';
    fitText(hg, t, 470, 900, font, 72);
    hg.fillText(t, x + 256, y + 72);
    hg.shadowBlur = 0;
  });
  return { v: tex(vc), h: tex(hc), vCount: V_SIGNS.length, hCount: H_SIGNS.length };
}

// 屋上広告(大型ビルボード)
export function makeBillboards() {
  const [c, g] = canvas(1024, 512);
  const ads = [
    { bg: ['#ff2e88', '#6a0dad'], t: '夜ノ街銀行', s: 'すぐ借りられる。すぐ返せない。' },
    { bg: ['#0a4bff', '#00d0ff'], t: 'ネオ缶コーヒー', s: '眠らない街の、眠らない一本。' },
    { bg: ['#ff8a00', '#ff2a00'], t: '激辛らーめん地獄', s: '完食で無料。無理はしない。' },
    { bg: ['#141414', '#3a3a3a'], t: 'TOKYO 2040', s: '— 近日公開 —' },
  ];
  const font = '"Zen Kaku Gothic New", sans-serif';
  ads.forEach((a, i) => {
    const x = (i % 2) * 512, y = Math.floor(i / 2) * 256;
    const grd = g.createLinearGradient(x, y, x + 512, y + 256);
    grd.addColorStop(0, a.bg[0]); grd.addColorStop(1, a.bg[1]);
    g.fillStyle = grd; g.fillRect(x, y, 512, 256);
    g.fillStyle = 'rgba(255,255,255,.08)';
    for (let k = 0; k < 8; k++) { g.beginPath(); g.arc(x + rand(0, 512), y + rand(0, 256), rand(20, 90), 0, 7); g.fill(); }
    g.fillStyle = '#fff'; g.textAlign = 'left'; g.textBaseline = 'alphabetic';
    fitText(g, a.t, 460, 900, font, 64); g.fillText(a.t, x + 28, y + 140);
    g.font = `700 22px ${font}`; g.fillStyle = 'rgba(255,255,255,.85)'; g.fillText(a.s, x + 30, y + 190);
  });
  return tex(c);
}

// 路面の細かいざらつき(タイル可能なノイズ)
export function makeGrain() {
  const S = 256;
  const [c, g] = canvas(S, S);
  const img = g.createImageData(S, S);
  for (let i = 0; i < S * S; i++) {
    const v = 110 + Math.random() * 60;
    img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = v;
    img.data[i * 4 + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  // 水たまり用の大きなまだら(アルファではなく G チャンネルに入れる)
  for (let i = 0; i < 40; i++) {
    const x = rand(0, S), y = rand(0, S), r = rand(10, 40);
    const grd = g.createRadialGradient(x, y, 0, x, y, r);
    grd.addColorStop(0, 'rgba(0,0,0,.5)'); grd.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = grd;
    for (const dx of [-S, 0, S]) for (const dy of [-S, 0, S]) { g.save(); g.translate(dx, dy); g.fillRect(x - r, y - r, r * 2, r * 2); g.restore(); }
  }
  return tex(c, { srgb: false, repeat: true });
}

// 歩道タイル
export function makeSidewalk() {
  const S = 256;
  const [c, g] = canvas(S, S);
  g.fillStyle = '#5b5a58'; g.fillRect(0, 0, S, S);
  const n = 4, s = S / n;
  for (let i = 0; i < n; i++) for (let k = 0; k < n; k++) {
    const l = rand(-8, 8);
    g.fillStyle = `rgb(${88 + l},${87 + l},${85 + l})`;
    g.fillRect(i * s + 2, k * s + 2, s - 4, s - 4);
  }
  for (let i = 0; i < 800; i++) { g.fillStyle = `rgba(0,0,0,${rand(0.05, 0.2)})`; g.fillRect(rand(0, S), rand(0, S), 2, 2); }
  return tex(c, { repeat: true });
}

// 光のにじみを1枚に焼き込んだ地面ライトマップ(街全体を上から見た図)
export function makeGroundLightmap(size, extent, lights) {
  const [c, g] = canvas(size, size);
  g.fillStyle = '#000'; g.fillRect(0, 0, size, size);
  g.globalCompositeOperation = 'lighter';
  const k = size / extent;
  for (const L of lights) {
    const x = L.x * k, y = L.z * k, r = L.r * k;
    const grd = g.createRadialGradient(x, y, 0, x, y, r);
    const [cr, cg, cb] = L.color;
    grd.addColorStop(0, `rgba(${cr},${cg},${cb},${L.i})`);
    grd.addColorStop(0.4, `rgba(${cr},${cg},${cb},${L.i * 0.35})`);
    grd.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = grd;
    if (L.w) { // 店先の横長の光
      g.save(); g.translate(x, y); g.rotate(L.rot || 0); g.scale(L.w / L.r, 1);
      g.beginPath(); g.arc(0, 0, r, 0, Math.PI * 2); g.fillStyle = (() => {
        const gg = g.createRadialGradient(0, 0, 0, 0, 0, r);
        gg.addColorStop(0, `rgba(${cr},${cg},${cb},${L.i})`); gg.addColorStop(1, 'rgba(0,0,0,0)'); return gg;
      })(); g.fill(); g.restore();
    } else {
      g.fillRect(x - r, y - r, r * 2, r * 2);
    }
  }
  const t = tex(c);
  t.wrapS = t.wrapT = THREE.ClampToEdgeWrapping;
  return t;
}

// 雨粒・光のフレア用のやわらかいスプライト
export function makeGlowSprite() {
  const [c, g] = canvas(64, 64);
  const grd = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grd.addColorStop(0, 'rgba(255,255,255,1)');
  grd.addColorStop(0.25, 'rgba(255,255,255,.5)');
  grd.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
  return tex(c);
}

// ---------------------------------------------------------------- 八重洲版の外壁
// 1枚 = 横 24m × 縦 32m(8階分, 階高4m)。map / emissive / roughness(G)
export const FW = 24, FH = 32;
export function makeFacade2(style) {
  const S = 1024;
  const [c, g] = canvas(S, S);
  const [e, ge] = canvas(S, S);
  const [r, gr] = canvas(S, S);
  ge.fillStyle = '#000'; ge.fillRect(0, 0, S, S);
  const px = S / FW;            // 1m あたりのピクセル
  const floorH = 4 * px;
  const lit = (p) => Math.random() < p;
  if (style === 'glass') {
    // カーテンウォール: 1.5m ピッチの方立、階ごとのスパンドレル、横の日除けフィン
    g.fillStyle = '#1c2a3a'; g.fillRect(0, 0, S, S);
    gr.fillStyle = '#101010'; gr.fillRect(0, 0, S, S);   // 低い粗さ = よく映り込む
    for (let f = 0; f < 8; f++) {
      const y = f * floorH;
      const on = lit(0.72);
      const tone = pick(['#dfe9ff', '#eef6ff', '#fff4e0', '#d8ecff']);
      for (let x = 0; x < S; x += 1.5 * px) {
        const cellOn = on && lit(0.85);
        const grd = g.createLinearGradient(x, y, x + 1.5 * px, y + floorH);
        grd.addColorStop(0, '#2a3a4e'); grd.addColorStop(1, '#141c26');
        g.fillStyle = grd; g.fillRect(x, y + 0.7 * px, 1.5 * px, floorH - 0.7 * px);
        if (cellOn) {
          ge.globalAlpha = rand(0.5, 0.85);
          ge.fillStyle = tone; ge.fillRect(x, y + 0.9 * px, 1.5 * px, floorH - 1.1 * px);
          // 天井の照明の列
          ge.globalAlpha = 0.9; ge.fillStyle = '#ffffff';
          ge.fillRect(x, y + 0.95 * px, 1.5 * px, 0.08 * px);
          ge.globalAlpha = 1;
          if (lit(0.3)) { ge.fillStyle = 'rgba(0,0,0,.6)'; ge.fillRect(x + rand(0, px), y + 2.2 * px, rand(0.2, 0.5) * px, 1.8 * px); }
        }
      }
      // スパンドレル(床の帯)と横フィン
      g.fillStyle = '#3b4652'; g.fillRect(0, y, S, 0.7 * px);
      gr.fillStyle = '#707070'; gr.fillRect(0, y, S, 0.7 * px);
      g.fillStyle = '#8a95a0'; g.fillRect(0, y + 0.66 * px, S, 0.06 * px);
    }
    for (let x = 0; x < S; x += 1.5 * px) { g.fillStyle = '#56616c'; g.fillRect(x, 0, 0.08 * px, S); ge.fillStyle = '#000'; ge.fillRect(x, 0, 0.08 * px, S); }
  } else if (style === 'grid') {
    // 白いプレキャストコンクリートに、縦長の窓が 1.5m ピッチで並ぶ(丸の内・八重洲の高層オフィス)
    const wall = pick(['#d9d8d2', '#cfd0cc', '#e2ded4', '#c4c6c4']);
    g.fillStyle = wall; g.fillRect(0, 0, S, S);
    gr.fillStyle = '#b0b0b0'; gr.fillRect(0, 0, S, S);
    for (let i = 0; i < 2500; i++) { g.fillStyle = `rgba(60,60,60,${rand(0.01, 0.05)})`; g.fillRect(rand(0, S), rand(0, S), rand(1, 3), rand(4, 40)); }
    const pitch = 1.5 * px, ww = 0.95 * px, wh = 2.5 * px;
    for (let f = 0; f < 8; f++) {
      const y = f * floorH;
      const floorLit = lit(0.55);
      const tone = pick(['#eef4ff', '#f6f8ff', '#fff7ea']);
      for (let x = 0; x < S; x += pitch) {
        const wx = x + (pitch - ww) / 2, wy = y + 0.75 * px;
        // 窓の奥行き(上と左に影、下と右に光)
        g.fillStyle = 'rgba(0,0,0,.35)'; g.fillRect(wx - 3, wy - 4, ww + 6, 5); g.fillRect(wx - 4, wy, 4, wh);
        g.fillStyle = 'rgba(255,255,255,.5)'; g.fillRect(wx - 3, wy + wh, ww + 6, 3);
        const on = floorLit ? lit(0.8) : lit(0.06);
        gr.fillStyle = '#181818'; gr.fillRect(wx, wy, ww, wh);
        if (on) { g.fillStyle = tone; g.fillRect(wx, wy, ww, wh); ge.globalAlpha = rand(0.4, 0.8); ge.fillStyle = tone; ge.fillRect(wx, wy, ww, wh); ge.globalAlpha = 1; }
        else { const grd = g.createLinearGradient(wx, wy, wx, wy + wh); grd.addColorStop(0, '#3a4a5c'); grd.addColorStop(1, '#1a222c'); g.fillStyle = grd; g.fillRect(wx, wy, ww, wh); }
      }
    }
  } else if (style === 'office' || style === 'mixed') {
    const wall = style === 'office' ? pick(['#6f7378', '#8a8479', '#575b61', '#9a9a94']) : pick(['#7d7468', '#6b6d70', '#8c8175', '#4f5257', '#a39b8e']);
    g.fillStyle = wall; g.fillRect(0, 0, S, S);
    gr.fillStyle = '#d0d0d0'; gr.fillRect(0, 0, S, S);
    for (let i = 0; i < 3000; i++) { g.fillStyle = `rgba(0,0,0,${rand(0.02, 0.08)})`; g.fillRect(rand(0, S), rand(0, S), rand(1, 3), rand(3, 40)); }
    const win = style === 'office' ? 2.4 : 1.8, pitch = style === 'office' ? 3 : 3;
    for (let f = 0; f < 8; f++) {
      const y = f * floorH;
      const floorLit = lit(style === 'office' ? 0.55 : 0.4);
      const tone = style === 'office' ? pick(['#e8f2ff', '#f4f8ff', '#fff6e8']) : pick(['#ffdcae', '#ffe9c8', '#dff0ff', '#ffd1d1']);
      for (let x = 0; x < S; x += pitch * px) {
        const wx = x + (pitch - win) / 2 * px, wy = y + 1.0 * px, ww = win * px, wh = 2.2 * px;
        g.fillStyle = '#1c2029'; g.fillRect(wx - 3, wy - 3, ww + 6, wh + 6);
        const on = floorLit ? lit(0.8) : lit(0.08);
        gr.fillStyle = '#181818'; gr.fillRect(wx, wy, ww, wh); // 窓マスク(粗さ小)
        if (on) {
          g.fillStyle = tone; g.fillRect(wx, wy, ww, wh);
          ge.globalAlpha = rand(0.4, 0.8); ge.fillStyle = tone; ge.fillRect(wx, wy, ww, wh); ge.globalAlpha = 1;
          if (lit(0.4)) { ge.fillStyle = 'rgba(0,0,0,.55)'; for (let yy = wy; yy < wy + wh; yy += 5) ge.fillRect(wx, yy, ww, 2); }
        } else {
          const grd = g.createLinearGradient(wx, wy, wx, wy + wh);
          grd.addColorStop(0, '#29313e'); grd.addColorStop(1, '#10141b');
          g.fillStyle = grd; g.fillRect(wx, wy, ww, wh);
          gr.fillStyle = '#202020'; gr.fillRect(wx, wy, ww, wh);
        }
        g.fillStyle = 'rgba(20,20,24,.9)'; g.fillRect(wx + ww / 2 - 1.5, wy, 3, wh);
        ge.fillStyle = '#000'; ge.fillRect(wx + ww / 2 - 1.5, wy, 3, wh);
      }
      if (style === 'office') { // 八重洲に多い横ルーバー
        g.fillStyle = 'rgba(210,214,218,.9)'; g.fillRect(0, y + 3.4 * px, S, 0.18 * px);
        g.fillStyle = 'rgba(0,0,0,.35)'; g.fillRect(0, y + 3.58 * px, S, 0.12 * px);
      } else if (lit(0.25)) {
        g.fillStyle = '#b8b8b2';
        for (let x = 0; x < S; x += pitch * px * 2) g.fillRect(x + 0.2 * px, y + 3.1 * px, 0.8 * px, 0.6 * px); // 室外機
      }
    }
  } else if (style === 'brick') {
    // 東京駅丸の内駅舎風: 赤レンガ + 白い石の帯
    g.fillStyle = '#7a3122'; g.fillRect(0, 0, S, S);
    for (let y = 0; y < S; y += 6) for (let x = (y / 6) % 2 ? 0 : 7; x < S; x += 14) {
      g.fillStyle = `rgb(${110 + rand(-20, 20)},${45 + rand(-10, 10)},${32 + rand(-8, 8)})`; g.fillRect(x, y, 13, 5);
    }
    gr.fillStyle = '#e0e0e0'; gr.fillRect(0, 0, S, S);
    for (let f = 0; f < 8; f++) {
      const y = f * floorH;
      g.fillStyle = '#d8d2c2'; g.fillRect(0, y + 3.6 * px, S, 0.4 * px);
      for (let x = 0; x < S; x += 3 * px) {
        const wx = x + 0.8 * px, wy = y + 1.1 * px, ww = 1.4 * px, wh = 2.2 * px;
        g.fillStyle = '#d8d2c2'; g.fillRect(wx - 5, wy - 5, ww + 10, wh + 10);
        const on = lit(0.6);
        g.fillStyle = on ? '#ffd08a' : '#1a1a20'; g.fillRect(wx, wy, ww, wh);
        gr.fillStyle = '#181818'; gr.fillRect(wx, wy, ww, wh);
        if (on) { ge.fillStyle = '#ffc070'; ge.globalAlpha = 0.8; ge.fillRect(wx, wy, ww, wh); ge.globalAlpha = 1; }
      }
    }
  } else { // canopy / granroof / viaduct
    const base = style === 'granroof' ? '#e8ecef' : style === 'viaduct' ? '#5d5f62' : '#6d7075';
    g.fillStyle = base; g.fillRect(0, 0, S, S);
    gr.fillStyle = '#c0c0c0'; gr.fillRect(0, 0, S, S);
    for (let i = 0; i < 1500; i++) { g.fillStyle = `rgba(0,0,0,${rand(0.02, 0.1)})`; g.fillRect(rand(0, S), rand(0, S), rand(1, 4), rand(4, 60)); }
    if (style === 'viaduct') { // ガード下のアーチ
      for (let x = 0; x < S; x += 8 * px) {
        g.fillStyle = '#2b2c2f';
        g.beginPath(); g.moveTo(x + 1 * px, S); g.lineTo(x + 1 * px, S - 4 * px); g.arc(x + 4 * px, S - 4 * px, 3 * px, Math.PI, 0); g.lineTo(x + 7 * px, S); g.fill();
      }
    }
  }
  const t = (cv, srgb) => { const x = tex(cv, { repeat: true, srgb }); return x; };
  return { map: t(c, true), emissive: t(e, true), rough: t(r, false) };
}

// 青い案内標識(通り名)
export function makeRoadSign(text) {
  const [c, g] = canvas(512, 160);
  g.fillStyle = '#1f4fa8'; g.fillRect(0, 0, 512, 160);
  g.strokeStyle = '#fff'; g.lineWidth = 6; g.strokeRect(8, 8, 496, 144);
  g.fillStyle = '#fff'; g.textAlign = 'center'; g.textBaseline = 'middle';
  fitText(g, text, 440, 700, '"Zen Kaku Gothic New", sans-serif', 64);
  g.fillText(text, 256, 82);
  return tex(c);
}

// 布の織り目(法線マップ): 綾織りの細かい凹凸
let fabricTex = null;
export function makeFabricNormal() {
  if (fabricTex) return fabricTex;
  const S = 256;
  const [c, g] = canvas(S, S);
  const img = g.createImageData(S, S);
  const h = (x, y) => {
    const tw = Math.sin((x + y) * 0.9) * 0.5 + 0.5;          // 綾目(斜めの畝)
    const n = Math.sin(x * 12.9898 + y * 78.233) * 43758.5453;
    return tw * 0.8 + (n - Math.floor(n)) * 0.2;
  };
  for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) {
    const dx = h(x + 1, y) - h(x - 1, y), dy = h(x, y + 1) - h(x, y - 1);
    const i = (y * S + x) * 4;
    img.data[i] = 128 - dx * 90; img.data[i + 1] = 128 - dy * 90; img.data[i + 2] = 255; img.data[i + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  fabricTex = tex(c, { srgb: false, repeat: true });
  fabricTex.repeat.set(10, 10);
  return fabricTex;
}
