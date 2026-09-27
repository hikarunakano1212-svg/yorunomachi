// 八重洲マップ: Overture Maps(OSM 由来)の実データから街を組み立てる
// 建物・濡れた路面(反射+影)・高架の線路と電車・首都高・街路樹・街灯・信号機・ガードレール
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { Reflector } from 'three/addons/objects/Reflector.js';
import { rand, randi, pick, clamp } from './util.js';
import * as T from './textures.js';

// ---------------------------------------------------------------- データ読み込み
export async function loadMapData() {
  if (window.__MAPDATA) return window.__MAPDATA; // 単体 HTML 版(埋め込み)
  const [json, ground, minimap] = await Promise.all([
    fetch('assets/map/yaesu.json').then((r) => r.json()),
    'assets/map/ground.webp', 'assets/map/minimap.png',
  ]);
  return { json, ground, minimap };
}
function loadImage(src) {
  return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = src; });
}

// Blender で焼いた PBR テクスチャ(単体 HTML 版では埋め込み)
const TEX_NAMES = ['asphalt', 'pavers', 'concrete', 'tiles'];
export async function loadPbr() {
  const loader = new THREE.TextureLoader();
  const out = {};
  await Promise.all(TEX_NAMES.flatMap((n) => ['albedo', 'normal', 'rough'].map(async (k) => {
    const src = window.__TEX?.[`${n}_${k}`] ?? `assets/tex/${n}_${k}.jpg`;
    const t = await loader.loadAsync(src);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.anisotropy = 8;
    if (k === 'albedo') t.colorSpace = THREE.SRGBColorSpace;
    (out[n] ??= {})[k] = t;
  })));
  return out;
}

const pts2 = (a) => { const o = []; for (let i = 0; i < a.length; i += 2) o.push([a[i], a[i + 1]]); return o; };

// ---------------------------------------------------------------- 当たり判定(線分)
export class Colliders {
  constructor() { this.segs = []; this.polys = []; this.cell = 8; this.grid = new Map(); }
  key(i, k) { return i * 73856093 ^ k * 19349663; }
  addSeg(ax, az, bx, bz, tag) {
    const s = { ax, az, bx, bz, tag };
    this.segs.push(s);
    const c = this.cell;
    const x0 = Math.floor(Math.min(ax, bx) / c), x1 = Math.floor(Math.max(ax, bx) / c);
    const z0 = Math.floor(Math.min(az, bz) / c), z1 = Math.floor(Math.max(az, bz) / c);
    for (let i = x0; i <= x1; i++) for (let k = z0; k <= z1; k++) {
      const kk = this.key(i, k);
      if (!this.grid.has(kk)) this.grid.set(kk, { segs: [], polys: [] });
      this.grid.get(kk).segs.push(s);
    }
  }
  addPoly(p, tag = 'wall') {
    const pts = pts2(p);
    let minX = 1e9, minZ = 1e9, maxX = -1e9, maxZ = -1e9;
    for (let i = 0; i < pts.length; i++) {
      const a = pts[i], b = pts[(i + 1) % pts.length];
      this.addSeg(a[0], a[1], b[0], b[1], tag);
      minX = Math.min(minX, a[0]); maxX = Math.max(maxX, a[0]); minZ = Math.min(minZ, a[1]); maxZ = Math.max(maxZ, a[1]);
    }
    const poly = { pts, minX, minZ, maxX, maxZ, tag };
    this.polys.push(poly);
    const c = this.cell;
    for (let i = Math.floor(minX / c); i <= Math.floor(maxX / c); i++) for (let k = Math.floor(minZ / c); k <= Math.floor(maxZ / c); k++) {
      const kk = this.key(i, k);
      if (!this.grid.has(kk)) this.grid.set(kk, { segs: [], polys: [] });
      this.grid.get(kk).polys.push(poly);
    }
    return poly;
  }
  addBox(x, z, hw, hd, yaw = 0, tag = 'prop') {
    const c = Math.cos(yaw), s = Math.sin(yaw);
    const p = [];
    for (const [a, b] of [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]]) p.push(x + a * c + b * s, z - a * s + b * c);
    return this.addPoly(p, tag);
  }
  cellsNear(x, z, r) {
    const c = this.cell, out = [];
    for (let i = Math.floor((x - r) / c); i <= Math.floor((x + r) / c); i++)
      for (let k = Math.floor((z - r) / c); k <= Math.floor((z + r) / c); k++) {
        const g = this.grid.get(this.key(i, k));
        if (g) out.push(g);
      }
    return out;
  }
  inside(x, z, margin = 0) {
    for (const g of this.cellsNear(x, z, margin + 0.1)) for (const p of g.polys) {
      if (x < p.minX - margin || x > p.maxX + margin || z < p.minZ - margin || z > p.maxZ + margin) continue;
      if (pointInPoly(x, z, p.pts)) return p;
      if (margin > 0) for (const s of g.segs) if (segDist(x, z, s) < margin) return p;
    }
    return null;
  }
  // 円を壁の外へ押し出す
  resolve(pos, r) {
    let hit = null;
    for (let iter = 0; iter < 2; iter++) {
      const seen = new Set();
      for (const g of this.cellsNear(pos.x, pos.z, r + 0.5)) for (const s of g.segs) {
        if (seen.has(s)) continue; seen.add(s);
        const [cx, cz] = closest(pos.x, pos.z, s);
        let dx = pos.x - cx, dz = pos.z - cz;
        const d2 = dx * dx + dz * dz;
        if (d2 >= r * r) continue;
        const d = Math.sqrt(d2) || 1e-4;
        dx /= d; dz /= d;
        // 内側に入り込んでいたら反対へ
        const poly = this.inside(pos.x, pos.z);
        if (poly) { dx = -dx; dz = -dz; pos.x = cx + dx * r; pos.z = cz + dz * r; }
        else { pos.x = cx + dx * r; pos.z = cz + dz * r; }
        hit = { nx: dx, nz: dz, c: s };
      }
    }
    // 完全に中に入っていたら一番近い辺から出す
    const inPoly = this.inside(pos.x, pos.z);
    if (inPoly) {
      let best = null, bd = 1e9;
      const P = inPoly.pts;
      for (let i = 0; i < P.length; i++) {
        const s = { ax: P[i][0], az: P[i][1], bx: P[(i + 1) % P.length][0], bz: P[(i + 1) % P.length][1] };
        const d = segDist(pos.x, pos.z, s);
        if (d < bd) { bd = d; best = s; }
      }
      const [cx, cz] = closest(pos.x, pos.z, best);
      let dx = cx - pos.x, dz = cz - pos.z; const d = Math.hypot(dx, dz) || 1;
      dx /= d; dz /= d;
      pos.x = cx + dx * r; pos.z = cz + dz * r;
      hit = { nx: dx, nz: dz, c: best };
    }
    return hit;
  }
  // 水平方向のレイと壁の交差距離
  raycast(ox, oz, dx, dz, maxT) {
    let best = maxT;
    const seen = new Set();
    const step = this.cell * 0.9;
    for (let t = 0; t <= maxT + step; t += step) {
      const x = ox + dx * Math.min(t, maxT), z = oz + dz * Math.min(t, maxT);
      for (const g of this.cellsNear(x, z, 1)) for (const s of g.segs) {
        if (seen.has(s)) continue; seen.add(s);
        const ex = s.bx - s.ax, ez = s.bz - s.az;
        const den = dx * ez - dz * ex;
        if (Math.abs(den) < 1e-9) continue;
        const wx = s.ax - ox, wz = s.az - oz;
        const tt = (wx * ez - wz * ex) / den, u = (wx * dz - wz * dx) / den;
        if (tt >= 0 && tt < best && u >= 0 && u <= 1) best = tt;
      }
      if (t > best) break;
    }
    return best;
  }
}
function closest(x, z, s) {
  const ex = s.bx - s.ax, ez = s.bz - s.az, l2 = ex * ex + ez * ez || 1;
  const t = clamp(((x - s.ax) * ex + (z - s.az) * ez) / l2, 0, 1);
  return [s.ax + ex * t, s.az + ez * t];
}
function segDist(x, z, s) { const [cx, cz] = closest(x, z, s); return Math.hypot(x - cx, z - cz); }
export function pointInPoly(x, z, P) {
  let inside = false;
  for (let i = 0, j = P.length - 1; i < P.length; j = i++) {
    const [xi, zi] = P[i], [xj, zj] = P[j];
    if ((zi > z) !== (zj > z) && x < ((xj - xi) * (z - zi)) / (zj - zi) + xi) inside = !inside;
  }
  return inside;
}

// ---------------------------------------------------------------- 道路グラフ
export class RoadGraph {
  constructor(data) {
    this.nodes = data.nodes.map(([x, z], i) => ({ i, x, z, out: [] }));
    this.edges = data.edges.map((e, i) => {
      const pts = pts2(e.pts);
      return { ...e, i, pts, len: e.len };
    });
    for (const e of this.edges) {
      this.nodes[e.a].out.push({ e, dir: 1, to: e.b });
      if (!e.ow) this.nodes[e.b].out.push({ e, dir: -1, to: e.a });
      this.nodes[e.a].deg = (this.nodes[e.a].deg ?? 0) + 1;
      this.nodes[e.b].deg = (this.nodes[e.b].deg ?? 0) + 1;
      if (!this.nodes[e.a].maxW || this.nodes[e.a].maxW < e.w) this.nodes[e.a].maxW = e.w;
      if (!this.nodes[e.b].maxW || this.nodes[e.b].maxW < e.w) this.nodes[e.b].maxW = e.w;
    }
  }
  junctionR(n) { return n.deg >= 3 ? n.maxW / 2 + 3 : 1; }
  // 向きつき区間の車線中心線(左側通行)。lane=0 が一番左
  lanePath(e, dir, lane = 0) {
    let p = dir > 0 ? e.pts : [...e.pts].reverse();
    const lanes = this.laneCount(e);
    const half = e.w / 2;
    const off = e.ow ? half - (lane + 0.5) * (e.w / lanes) : (lane + 0.5) * (half / lanes);
    const out = offsetLine(p, off);
    const a = this.nodes[dir > 0 ? e.a : e.b], b = this.nodes[dir > 0 ? e.b : e.a];
    // 終点は停止線(交差点の横断歩道の手前)まで
    return trimLine(out, Math.min(this.junctionR(a) + 2, e.len * 0.35), Math.min(this.junctionR(b) + (b.deg >= 3 ? 7.5 : 1), e.len * 0.4));
  }
  laneCount(e) { return e.ow ? Math.max(1, Math.round(e.w / 3.3)) : Math.max(1, Math.floor(e.w / 2 / 3.2)); }
  nearestNode(x, z) {
    let best = null, bd = 1e9;
    for (const n of this.nodes) { const d = (n.x - x) ** 2 + (n.z - z) ** 2; if (d < bd) { bd = d; best = n; } }
    return best;
  }
  // 目標ノードまでの距離(ダイクストラ、逆向きグラフで)
  distancesTo(target) {
    const dist = new Float32Array(this.nodes.length).fill(1e9);
    dist[target.i] = 0;
    const open = [target.i];
    const inRev = this._rev ??= (() => {
      const r = this.nodes.map(() => []);
      for (const n of this.nodes) for (const o of n.out) r[o.to].push({ from: n.i, len: o.e.len });
      return r;
    })();
    while (open.length) {
      let bi = 0;
      for (let k = 1; k < open.length; k++) if (dist[open[k]] < dist[open[bi]]) bi = k;
      const u = open.splice(bi, 1)[0];
      for (const { from, len } of inRev[u]) {
        const nd = dist[u] + len;
        if (nd < dist[from]) { if (dist[from] >= 1e9) open.push(from); dist[from] = nd; }
      }
    }
    return dist;
  }
  // 最寄りの車道上の点(区間・向き)
  nearestEdge(x, z) {
    let best = null, bd = 1e9;
    for (const e of this.edges) for (let i = 0; i + 1 < e.pts.length; i++) {
      const s = { ax: e.pts[i][0], az: e.pts[i][1], bx: e.pts[i + 1][0], bz: e.pts[i + 1][1] };
      const d = segDist(x, z, s);
      if (d < bd) { bd = d; best = { e, d, i }; }
    }
    return best;
  }
}
export function offsetLine(p, off) {
  const out = [];
  for (let i = 0; i < p.length; i++) {
    const a = p[Math.max(0, i - 1)], b = p[Math.min(p.length - 1, i + 1)];
    let dx = b[0] - a[0], dz = b[1] - a[1];
    const l = Math.hypot(dx, dz) || 1; dx /= l; dz /= l;
    // 進行方向の左 = (dz, -dx)
    out.push([p[i][0] + dz * off, p[i][1] - dx * off]);
  }
  return out;
}
function lineLen(p) { let L = 0; for (let i = 0; i + 1 < p.length; i++) L += Math.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1]); return L; }
export function trimLine(p, t0, t1) {
  const L = lineLen(p);
  if (t0 + t1 > L - 1) { const k = (L - 1) / (t0 + t1 + 1e-6); t0 *= k; t1 *= k; }
  const at = (t) => {
    let acc = 0;
    for (let i = 0; i + 1 < p.length; i++) {
      const l = Math.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1]);
      if (acc + l >= t) { const u = (t - acc) / (l || 1); return [i, [p[i][0] + (p[i + 1][0] - p[i][0]) * u, p[i][1] + (p[i + 1][1] - p[i][1]) * u]]; }
      acc += l;
    }
    return [p.length - 2, p[p.length - 1]];
  };
  const [i0, s] = at(t0), [i1, e] = at(L - t1);
  return [s, ...p.slice(i0 + 1, i1 + 1), e];
}

// ---------------------------------------------------------------- ワールド生成
export async function buildYaesu(game, mapData) {
  const { scene, assets } = game;
  const M = mapData.json;
  const pbr = await loadPbr();
  const facadeMats = [];
  const uDay = { value: 0 }; // 昼モード(窓を空が映る暗いガラスにする)
  const group = new THREE.Group();
  scene.add(group);
  const col = new Colliders();
  const HALF = M.half;
  const glowLights = [], glowSprites = [], shopFronts = [];

  // ---------- 建物
  const styles = ['glass', 'office', 'mixed', 'brick', 'canopy', 'granroof'];
  const facadeVariants = { office: 3, mixed: 4 };
  const facades = {};
  for (const s of styles) {
    const n = facadeVariants[s] ?? 1;
    facades[s] = Array.from({ length: n }, () => T.makeFacade2(s));
  }
  const geos = {};
  const store = T.makeStorefronts();
  const signs = T.makeSignAtlas();
  const bill = T.makeBillboards();
  const vSign = { pos: [], uv: [] }, hSign = { pos: [], uv: [] }, storeG = { pos: [], uv: [] }, billG = { pos: [], uv: [] };
  const roofBoxes = [], aviation = [];
  const quad = (G, a, b, c, d, u0, v0, u1, v1) => { G.pos.push(...a, ...b, ...c, ...a, ...c, ...d); G.uv.push(u0, v0, u1, v0, u1, v1, u0, v0, u1, v1, u0, v1); };

  for (const b of M.buildings) {
    const P = pts2(b.p);
    const variant = randi(0, (facadeVariants[b.s] ?? 1) - 1);
    const key = `${b.s}:${variant}`;
    const G = (geos[key] ??= { pos: [], uv: [], style: b.s, variant });
    const fronts = new Set(b.f);
    const shops = (b.s === 'mixed' || b.s === 'office') && b.mh === 0;
    const base = b.mh;
    let u = rand(0, 1);
    const vOff = randi(0, 7) / 8;
    for (let i = 0; i < P.length; i++) {
      const a = P[i], c = P[(i + 1) % P.length];
      const len = Math.hypot(c[0] - a[0], c[1] - a[1]);
      const store = shops && fronts.has(i);
      const yb = store ? 4.5 : base;
      // 外から見て左(c)→右(a) の順で並べると法線が外向きになる
      quad(G, [c[0], yb, c[1]], [a[0], yb, a[1]], [a[0], b.h, a[1]], [c[0], b.h, c[1]],
        u, vOff + yb / T.FH, u + len / T.FW, vOff + b.h / T.FH);
      if (store) {
        quad(storeG, [c[0], 0, c[1]], [a[0], 0, a[1]], [a[0], 4.5, a[1]], [c[0], 4.5, c[1]], u, 0, u + len / 48, 1);
        decorate(a, c, len, b);
      }
      u += len / T.FW;
    }
    // 屋根(底面も: 高架のホーム屋根などを下から見るため)
    const shape = P.map(([x, z]) => new THREE.Vector2(x, z));
    const tris = THREE.ShapeUtils.triangulateShape(shape, []);
    const R = (geos['roof'] ??= { pos: [], uv: [], style: 'roof' });
    for (const [i0, i1, i2] of tris) {
      for (const k of [i0, i2, i1]) { R.pos.push(P[k][0], b.h, P[k][1]); R.uv.push(P[k][0] / 6, P[k][1] / 6); }
      if (base > 0) for (const k of [i0, i1, i2]) { R.pos.push(P[k][0], base, P[k][1]); R.uv.push(P[k][0] / 6, P[k][1] / 6); }
    }
    if (base === 0 || b.s === 'granroof') col.addPoly(b.p, 'building');
    // 屋上設備・航空障害灯
    const cx = P.reduce((s, p) => s + p[0], 0) / P.length, cz = P.reduce((s, p) => s + p[1], 0) / P.length;
    if (b.h > 25 && b.s !== 'canopy') {
      for (let k = 0; k < randi(1, 3); k++) roofBoxes.push({ x: cx + rand(-4, 4), y: b.h + 0.8, z: cz + rand(-4, 4), sx: rand(1.5, 4), sy: 1.6, sz: rand(1.5, 3) });
    }
    if (b.h > 90) for (let k = 0; k < P.length; k += Math.max(1, Math.floor(P.length / 4))) aviation.push([P[k][0], b.h + 0.5, P[k][1]]);
    // 高層ビルの屋上広告は付けない(八重洲はオフィス街)。中層の雑居ビルには看板
    if (b.s === 'mixed' && b.h > 18 && b.h < 45 && fronts.size && Math.random() < 0.18) {
      const i = [...fronts][0];
      const a = P[i], c = P[(i + 1) % P.length];
      const len = Math.hypot(c[0] - a[0], c[1] - a[1]);
      if (len > 8) {
        const ux = (c[0] - a[0]) / len, uz = (c[1] - a[1]) / len, nx = uz, nz = -ux;
        const bw = Math.min(len * 0.7, 12), bh = bw / 2;
        const mx = (a[0] + c[0]) / 2 - nx * 1.5, mz = (a[1] + c[1]) / 2 - nz * 1.5;
        const k = randi(0, 3), u0 = (k % 2) * 0.5, v0 = 1 - (Math.floor(k / 2) + 1) * 0.5;
        quad(billG, [mx + ux * bw / 2, b.h + 1, mz + uz * bw / 2], [mx - ux * bw / 2, b.h + 1, mz - uz * bw / 2],
          [mx - ux * bw / 2, b.h + 1 + bh, mz - uz * bw / 2], [mx + ux * bw / 2, b.h + 1 + bh, mz + uz * bw / 2], u0, v0, u0 + 0.5, v0 + 0.5);
      }
    }
  }

  function decorate(a, c, len, b) {
    const dx = (c[0] - a[0]) / len, dz = (c[1] - a[1]) / len;
    const nx = dz, nz = -dx; // 外向き法線(反時計回りの多角形)
    const n = Math.max(1, Math.floor(len / 8));
    for (let s = 0; s < n; s++) {
      const t = (s + 0.5) / n * len;
      const px = a[0] + dx * t, pz = a[1] + dz * t;
      shopFronts.push({ x: px + nx * 2.2, z: pz + nz * 2.2, yaw: Math.atan2(-nx, -nz), b });
      if (b.s === 'mixed' && Math.random() < 0.75) {
        const k = randi(0, signs.hCount - 1);
        const u0 = (k % 2) * 0.5, v1 = 1 - Math.floor(k / 2) * 0.125, v0 = v1 - 0.125;
        const hw = Math.min(len / n * 0.42, 3.2), y0 = 4.65, y1 = y0 + hw * 0.5;
        const ox = px + nx * 0.12, oz = pz + nz * 0.12;
        quad(hSign, [ox + dx * hw, y0, oz + dz * hw], [ox - dx * hw, y0, oz - dz * hw], [ox - dx * hw, y1, oz - dz * hw], [ox + dx * hw, y1, oz + dz * hw], u0, v0, u0 + 0.5, v1);
      }
      const warm = b.s === 'mixed' ? pick([[255, 214, 160], [230, 240, 255], [255, 190, 210]]) : [220, 235, 255];
      glowLights.push({ x: px + nx * 2.5, z: pz + nz * 2.5, r: 5, w: 8, rot: Math.atan2(dz, dx), color: warm, i: 0.45 });
    }
    if (b.s !== 'mixed' || b.h < 10) return;
    const nV = Math.floor(len / 10) + (Math.random() < 0.5 ? 1 : 0);
    for (let s = 0; s < nV; s++) {
      const t = rand(2, len - 2);
      const k = randi(0, signs.vCount - 1);
      const u0 = (k % 8) * 0.125, v1 = 1 - Math.floor(k / 8) * 0.5, v0 = v1 - 0.5;
      const sh = Math.min(b.h - 6.5, rand(4.5, 8)), sw = sh / 4;
      const y0 = 6, y1 = y0 + sh;
      const bx = a[0] + dx * t + nx * 0.2, bz = a[1] + dz * t + nz * 0.2;
      const fx = bx + nx * sw, fz = bz + nz * sw;
      quad(vSign, [bx, y0, bz], [fx, y0, fz], [fx, y1, fz], [bx, y1, bz], u0, v0, u0 + 0.125, v1);
      quad(vSign, [fx, y0, fz], [bx, y0, bz], [bx, y1, bz], [fx, y1, fz], u0, v0, u0 + 0.125, v1);
      const cHex = [0xff2e88, 0x35e8ff, 0xffb62e, 0x8cff5a, 0xff4b3a, 0xc070ff, 0xffffff, 0xffe23a][k % 8];
      glowSprites.push({ x: (bx + fx) / 2 + nx * 0.3, y: (y0 + y1) / 2, z: (bz + fz) / 2 + nz * 0.3, s: sh * 1.3, c: cHex, o: 0.22 });
      const cc = new THREE.Color(cHex);
      glowLights.push({ x: bx + nx * 3, z: bz + nz * 3, r: 7, color: [cc.r * 255, cc.g * 255, cc.b * 255], i: 0.35 });
    }
  }

  const mk = (G) => {
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(G.pos, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(G.uv, 2));
    g.computeVertexNormals();
    return g;
  };
  const buildingMeshes = [];
  for (const G of Object.values(geos)) {
    if (!G.pos.length) continue;
    let m;
    if (G.style === 'roof') m = new THREE.MeshStandardMaterial({ color: 0x3a3b40, map: T.makeGrain(), roughness: 0.95, side: THREE.DoubleSide });
    else {
      const f = facades[G.style][G.variant];
      const glass = G.style === 'glass';
      // 外壁の素材(Blender で焼いたタイル/コンクリートの凹凸と汚れ)を 4m ピッチで重ねる
      const detail = G.style === 'mixed' || G.style === 'brick' ? pbr.tiles : pbr.concrete;
      const nrm = detail.normal.clone(); nrm.repeat.set(T.FW / 4, T.FH / 4); nrm.needsUpdate = true;
      m = new THREE.MeshStandardMaterial({
        map: f.map, emissiveMap: f.emissive, emissive: 0xffffff, emissiveIntensity: glass ? 1.3 : 1.0,
        roughnessMap: f.rough, roughness: 1, metalness: glass ? 0.85 : 0.1, envMapIntensity: glass ? 1.6 : 0.6,
        normalMap: glass ? null : nrm, normalScale: new THREE.Vector2(0.8, 0.8),
        side: G.style === 'canopy' || G.style === 'granroof' ? THREE.DoubleSide : THREE.FrontSide,
      });
      // 窓の配置(テクスチャ上の m 単位): ピッチ, 窓の左端, 幅, 下端, 高さ
      const WIN = { office: [3, 0.3, 2.4, 1.0, 2.2], mixed: [3, 0.6, 1.8, 1.0, 2.2], brick: [3, 0.8, 1.4, 1.1, 2.2], glass: [1.5, 0.0, 1.5, 0.7, 3.3] }[G.style];
      m.onBeforeCompile = (sh) => {
        sh.uniforms.uDetail = { value: detail.albedo };
        sh.uniforms.uDay = uDay;
        sh.uniforms.uWin = { value: new THREE.Vector4(WIN?.[0] ?? 3, WIN?.[1] ?? 0, WIN?.[2] ?? 0, WIN?.[3] ?? 0) };
        sh.uniforms.uWinH = { value: WIN?.[4] ?? 0 };
        sh.vertexShader = sh.vertexShader
          .replace('#include <common>', '#include <common>\nvarying vec3 vWp; varying vec3 vWN;')
          .replace('#include <begin_vertex>', '#include <begin_vertex>\nvWp = (modelMatrix * vec4(position, 1.0)).xyz; vWN = normalize(mat3(modelMatrix) * normal);');
        sh.fragmentShader = sh.fragmentShader
          .replace('#include <common>', `#include <common>
            uniform sampler2D uDetail; uniform float uDay, uWinH; uniform vec4 uWin; varying vec3 vWp; varying vec3 vWN;
            float gWin, gRoomLit; vec3 gRoom;
            float hh(vec2 p){ return fract(sin(dot(p, vec2(41.3, 289.1))) * 43758.5453); }`)
          .replace('#include <map_fragment>', `#include <map_fragment>
            // 窓マスク(粗さマップの暗い所)
            gWin = 1.0 - smoothstep(0.12, 0.3, texture2D(roughnessMap, vRoughnessMapUv).g);
            ${glass ? '' : `vec3 dt = texture2D(uDetail, vNormalMapUv).rgb / 0.5;
            diffuseColor.rgb *= mix(clamp(dt, 0.6, 1.4), vec3(1.0), gWin);`}
            // ---- インテリアマッピング: 窓の奥に部屋の箱を置き、視線と交差させる
            gRoom = vec3(0.0); gRoomLit = 0.0;
            vec2 mm = vMapUv * vec2(${T.FW.toFixed(1)}, ${T.FH.toFixed(1)});
            vec2 cell = vec2(floor(mm.x / uWin.x), floor(mm.y / 4.0));
            vec2 loc = vec2(mod(mm.x, uWin.x) - uWin.y, mod(mm.y, 4.0) - uWin.w);
            if (uWinH > 0.0 && gWin > 0.5 && abs(vWN.y) < 0.5) {
              vec3 N = normalize(vec3(vWN.x, 0.0, vWN.z));
              vec3 Tn = normalize(cross(vec3(0.0, 1.0, 0.0), N));
              vec3 V = normalize(vWp - cameraPosition);
              vec3 d = vec3(dot(V, Tn), V.y, -dot(V, N));
              // 0 除算で NaN が出るとブルームで画面全体に広がるので必ず避ける
              d = sign(d + 1e-7) * max(abs(d), vec3(1e-4));
              d.z = max(d.z, 1e-3);
              vec3 p = vec3(loc, 0.0);
              vec3 lo = vec3(-0.8, -uWin.w + 0.02, 0.0), hi = vec3(uWin.z + 0.8, 4.0 - uWin.w - 0.35, 4.5);
              vec3 tA = (lo - p) / d, tB = (hi - p) / d;
              vec3 tm = max(tA, tB);
              float t = min(min(tm.x, tm.y), tm.z);
              vec3 q = p + d * t;
              // 部屋ごとの点灯(夜の窓明かりのテクスチャと合わせる)
              vec2 cuv = (vec2(cell.x * uWin.x + uWin.y + uWin.z * 0.5, cell.y * 4.0 + uWin.w + uWinH * 0.5)) / vec2(${T.FW.toFixed(1)}, ${T.FH.toFixed(1)});
              vec3 litC = texture2D(emissiveMap, cuv).rgb;
              gRoomLit = clamp(dot(litC, vec3(0.333)) * 1.6, 0.0, 1.0);
              float r = hh(cell + floor(vMapUv * 7.0));
              vec3 wallC = mix(vec3(0.62, 0.6, 0.55), vec3(0.55, 0.58, 0.6), r);
              vec3 c;
              if (t == tm.z) {           // 奥の壁: 棚・机・人影
                c = wallC * 0.9;
                if (q.y < 0.75) c *= 0.45;
                if (abs(fract(q.x * 0.35 + r) - 0.5) < 0.12 && q.y < 1.9 && hh(cell + 3.0) > 0.5) c *= 0.3;
              } else if (t == tm.y) {    // 床か天井
                if (d.y > 0.0) { c = vec3(0.75); float strip = step(0.85, fract(q.z * 0.5)); c += vec3(1.6) * strip * gRoomLit; }
                else { c = mix(vec3(0.28, 0.27, 0.26), vec3(0.35, 0.3, 0.26), r) * (0.7 + 0.3 * step(0.5, fract(q.x + q.z))); }
              } else {                   // 左右の壁
                c = wallC * 0.75;
              }
              c *= 1.0 - q.z / 7.0;       // 奥ほど暗く
              // ブラインドが下りている部屋
              if (hh(cell + 9.1) > 0.7) { float bl = step(0.5, fract(loc.y * 12.0)); float down = step(uWinH * (1.0 - hh(cell + 2.3) * 0.8), loc.y); c = mix(c, vec3(0.7, 0.7, 0.68) * (0.8 + 0.2 * bl), down); }
              gRoom = clamp(c * mix(vec3(1.0), litC * 1.4 + 0.1, gRoomLit), 0.0, 4.0);
              // 昼: 室内は外より暗い。夜: 点灯していない部屋はほぼ真っ暗
              diffuseColor.rgb = mix(gRoom * mix(0.05, 0.35, uDay), diffuseColor.rgb, 0.0);
            } else {
              diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.1, 0.12, 0.14), gWin * uDay);
            }`)
          .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
            if (uWinH > 0.0 && gWin > 0.5 && abs(vWN.y) < 0.5) totalEmissiveRadiance = gRoom * gRoomLit * emissive.r * mix(1.0, 2.5, uDay);`)
          .replace('#include <metalnessmap_fragment>', `#include <metalnessmap_fragment>
            metalnessFactor = mix(metalnessFactor, 0.0, gWin);`)
          .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
            roughnessFactor = mix(roughnessFactor, 0.04, gWin);`)
          .replace('#include <lights_fragment_end>', `#include <lights_fragment_end>
            // 窓ガラスの反射(フレネル): 浅い角度ほど空や街が映る
            if (gWin > 0.5) {
              vec3 Vv = normalize(vWp - cameraPosition);
              float fr = 0.04 + 0.96 * pow(1.0 - abs(dot(Vv, normalize(vWN))), 5.0);
              reflectedLight.indirectSpecular *= mix(0.6, 1.6, fr);
              reflectedLight.directDiffuse *= 0.3; reflectedLight.indirectDiffuse *= mix(0.3, 1.0, uDay);
            }`);
      };
      m.userData.baseEmissive = m.emissiveIntensity;
      facadeMats.push(m);
    }
    const mesh = new THREE.Mesh(mk(G), m);
    mesh.castShadow = true; mesh.receiveShadow = true;
    group.add(mesh); buildingMeshes.push(mesh);
  }
  const storeMat = new THREE.MeshStandardMaterial({ map: store.map, emissiveMap: store.emissive, emissive: 0xffffff, emissiveIntensity: 0.9, roughness: 0.12, metalness: 0.15, envMapIntensity: 1.2 });
  const storeMesh = new THREE.Mesh(mk(storeG), storeMat);
  storeMesh.receiveShadow = true;
  group.add(storeMesh);
  const vSignMat = new THREE.MeshBasicMaterial({ map: signs.v, color: new THREE.Color(1.8, 1.8, 1.8) });
  const hSignMat = new THREE.MeshBasicMaterial({ map: signs.h, color: new THREE.Color(1.3, 1.3, 1.3) });
  group.add(new THREE.Mesh(mk(vSign), vSignMat), new THREE.Mesh(mk(hSign), hSignMat));
  if (billG.pos.length) group.add(new THREE.Mesh(mk(billG), new THREE.MeshBasicMaterial({ map: bill, color: new THREE.Color(1.5, 1.5, 1.5), side: THREE.DoubleSide })));
  {
    const im = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ color: 0x8d9094, roughness: 0.7 }), roofBoxes.length);
    const Mx = new THREE.Matrix4();
    roofBoxes.forEach((b, i) => { Mx.makeScale(b.sx, b.sy, b.sz).setPosition(b.x, b.y, b.z); im.setMatrixAt(i, Mx); });
    im.castShadow = true;
    group.add(im);
  }
  // 航空障害灯(赤く点滅)
  const aviGeo = new THREE.BufferGeometry();
  aviGeo.setAttribute('position', new THREE.Float32BufferAttribute(aviation.flat(), 3));
  const aviMat = new THREE.PointsMaterial({ color: new THREE.Color(6, 0.3, 0.2), size: 1.4, sizeAttenuation: true, map: game.glowTex, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending });
  const avi = new THREE.Points(aviGeo, aviMat); avi.layers.set(1); group.add(avi);

  // ---------- 高架の線路(東京駅)とガード下・電車
  const viaTex = T.makeFacade2('viaduct');
  const viaMat = new THREE.MeshStandardMaterial({ map: viaTex.map, roughness: 0.9, side: THREE.DoubleSide });
  const VH = 7;
  {
    const G = { pos: [], uv: [] };
    const top = { pos: [], uv: [] };
    for (const p of M.corridor) {
      const P = pts2(p);
      let u = 0;
      for (let i = 0; i < P.length; i++) {
        const a = P[i], c = P[(i + 1) % P.length];
        const len = Math.hypot(c[0] - a[0], c[1] - a[1]);
        quad(G, [a[0], 0, a[1]], [c[0], 0, c[1]], [c[0], VH, c[1]], [a[0], VH, a[1]], u, 0, u + len / T.FW, VH / T.FH);
        u += len / T.FW;
      }
      const tris = THREE.ShapeUtils.triangulateShape(P.map(([x, z]) => new THREE.Vector2(x, z)), []);
      for (const [i0, i1, i2] of tris) for (const k of [i0, i2, i1]) { top.pos.push(P[k][0], VH, P[k][1]); top.uv.push(P[k][0] / 4, P[k][1] / 4); }
      col.addPoly(p, 'viaduct');
    }
    for (const p of M.underpass) { // ガード下の天井(上に線路)
      const P = pts2(p);
      const tris = THREE.ShapeUtils.triangulateShape(P.map(([x, z]) => new THREE.Vector2(x, z)), []);
      for (const [i0, i1, i2] of tris) {
        for (const k of [i0, i2, i1]) { top.pos.push(P[k][0], VH, P[k][1]); top.uv.push(P[k][0] / 4, P[k][1] / 4); }
        for (const k of [i0, i1, i2]) { G.pos.push(P[k][0], VH - 1.2, P[k][1]); G.uv.push(P[k][0] / 8, P[k][1] / 8); }
      }
    }
    const wall = new THREE.Mesh(mk(G), viaMat); wall.castShadow = wall.receiveShadow = true; group.add(wall);
    const ballast = new THREE.Mesh(mk(top), new THREE.MeshStandardMaterial({ color: 0x3e3a36, map: T.makeGrain(), roughness: 1, side: THREE.DoubleSide }));
    ballast.receiveShadow = true; group.add(ballast);
    // レール(細い箱を並べる)
    const rails = [];
    const railGeo = new THREE.BoxGeometry(1, 0.15, 0.08);
    for (const r of M.rails) {
      const P = pts2(r);
      for (let i = 0; i + 1 < P.length; i++) {
        const [ax, az] = P[i], [bx, bz] = P[i + 1];
        const len = Math.hypot(bx - ax, bz - az);
        if (len < 0.5) continue;
        const yaw = Math.atan2(-(bz - az), bx - ax);
        const nx = -(bz - az) / len * 0.534, nz = (bx - ax) / len * 0.534;
        for (const s of [-1, 1]) rails.push({ x: (ax + bx) / 2 + nx * s, z: (az + bz) / 2 + nz * s, len, yaw });
      }
    }
    const rm = new THREE.InstancedMesh(railGeo, new THREE.MeshStandardMaterial({ color: 0x9a9ea3, metalness: 0.9, roughness: 0.3 }), rails.length);
    const Mx = new THREE.Matrix4(), Q = new THREE.Quaternion(), Y = new THREE.Vector3(0, 1, 0);
    rails.forEach((r, i) => { Mx.compose(new THREE.Vector3(r.x, VH + 0.1, r.z), Q.setFromAxisAngle(Y, r.yaw), new THREE.Vector3(r.len + 0.05, 1, 1)); rm.setMatrixAt(i, Mx); });
    group.add(rm);
  }
  const trains = makeTrains(group, M.rails.map(pts2), VH);

  // ---------- 首都高(高架)
  {
    const deck = { pos: [], uv: [] }, wall = { pos: [], uv: [] };
    const EH = 11, EW = 10;
    const pillars = [];
    for (const r of M.express) {
      const P = pts2(r);
      const L = offsetLine(P, EW / 2), Rr = offsetLine(P, -EW / 2);
      let acc = 0;
      for (let i = 0; i + 1 < P.length; i++) {
        const seg = Math.hypot(P[i + 1][0] - P[i][0], P[i + 1][1] - P[i][1]);
        const a = L[i], b = L[i + 1], c = Rr[i + 1], d = Rr[i];
        quad(deck, [d[0], EH, d[1]], [c[0], EH, c[1]], [b[0], EH, b[1]], [a[0], EH, a[1]], 0, acc / 8, 1, (acc + seg) / 8);
        quad(deck, [a[0], EH - 1.4, a[1]], [b[0], EH - 1.4, b[1]], [c[0], EH - 1.4, c[1]], [d[0], EH - 1.4, d[1]], 0, 0, 1, 1);
        for (const [s, t] of [[a, b], [c, d]]) quad(wall, [s[0], EH - 1.4, s[1]], [t[0], EH - 1.4, t[1]], [t[0], EH + 1.2, t[1]], [s[0], EH + 1.2, s[1]], acc / T.FW, 0, (acc + seg) / T.FW, 2.6 / T.FH);
        for (let t = (25 - acc % 25); t < seg; t += 25) {
          const u = t / seg, x = P[i][0] + (P[i + 1][0] - P[i][0]) * u, z = P[i][1] + (P[i + 1][1] - P[i][1]) * u;
          if (Math.abs(x) < HALF && Math.abs(z) < HALF) pillars.push([x, z]);
        }
        acc += seg;
      }
    }
    const dm = new THREE.Mesh(mk(deck), new THREE.MeshStandardMaterial({ color: 0x55585c, roughness: 0.85, side: THREE.DoubleSide }));
    dm.castShadow = true; dm.receiveShadow = true;
    group.add(dm, new THREE.Mesh(mk(wall), viaMat));
    const pg = new THREE.BoxGeometry(1.6, EH - 1.4, 1.6); pg.translate(0, (EH - 1.4) / 2, 0);
    const pm = new THREE.InstancedMesh(pg, viaMat, pillars.length);
    const Mx = new THREE.Matrix4();
    pillars.forEach(([x, z], i) => { Mx.makeTranslation(x, 0, z); pm.setMatrixAt(i, Mx); col.addBox(x, z, 0.8, 0.8, 0, 'pillar'); });
    pm.castShadow = true; group.add(pm);
  }

  // ---------- 街灯・街路樹・信号・ガードレール・自販機・案内標識
  const lampSpots = M.lamps.map(([x, z, yaw]) => ({ x, z, yaw }));
  group.add(instanceAsset(assets.get('lamp'), lampSpots, true));
  for (const l of lampSpots) {
    // 腕の先(モデルのローカル -Z 方向 2.25m)
    const fx = l.x - Math.sin(l.yaw) * 2.25, fz = l.z - Math.cos(l.yaw) * 2.25;
    l.hx = fx; l.hz = fz;
    glowLights.push({ x: fx, z: fz, r: 13, color: [255, 236, 214], i: 0.7 });
    glowSprites.push({ x: fx, y: 8.8, z: fz, s: 3.5, c: 0xfff0dd, o: 0.5 });
    col.addBox(l.x, l.z, 0.2, 0.2, 0, 'pole');
  }
  group.add(instanceAsset(assets.get('tree'), M.trees.map(([x, z, s]) => ({ x, z, s, yaw: rand(0, 6.28) })), true));
  for (const [x, z] of M.trees) col.addBox(x, z, 0.3, 0.3, 0, 'tree');
  const signalObjs = buildSignals(group, assets.get('signal'), M.signals);
  for (const s of M.signals) col.addBox(s[0], s[1], 0.15, 0.15, 0, 'pole');
  group.add(instanceAsset(assets.get('vending'), M.vendings.map(([x, z, yaw]) => ({ x, z, yaw })), true));
  const vendings = M.vendings.map(([x, z, yaw]) => {
    col.addBox(x, z, 0.5, 0.4, yaw, 'vending');
    glowLights.push({ x: x - Math.sin(yaw) * 1.2, z: z - Math.cos(yaw) * 1.2, r: 3.5, color: [220, 235, 255], i: 0.8 });
    return { x, z, yaw };
  });
  group.add(buildFences(M.fences));
  if (assets.has?.('ph_fence')) buildSites(group, assets, col, M);
  for (const s of M.signs) {
    const t = T.makeRoadSign(s.t);
    // 表裏2枚(裏から見ても鏡文字にならない)+支柱
    const m = new THREE.Group();
    const mat = new THREE.MeshBasicMaterial({ map: t, color: new THREE.Color(1.1, 1.1, 1.1) });
    const f = new THREE.Mesh(new THREE.PlaneGeometry(4.2, 1.3), mat);
    const bk = f.clone(); bk.rotation.y = Math.PI;
    m.add(f, bk);
    const sp = freeSignSpot(s.x, s.z);
    m.position.set(sp.x, 6.2, sp.z);
    m.rotation.y = sp.yaw;
    group.add(m);
  }

  function freeSignSpot(x, z) {
    const g = new RoadGraph(M.roads);
    const r = g.nearestEdge(x, z);
    const a = r.e.pts[r.i], b = r.e.pts[r.i + 1];
    const t = 0.5, px = a[0] + (b[0] - a[0]) * t, pz = a[1] + (b[1] - a[1]) * t;
    return { x: px, z: pz, yaw: Math.atan2(b[0] - a[0], b[1] - a[1]) };
  }

  // ---------- 光のにじみ(加算スプライト)
  {
    const pos = [], colr = [], size = [];
    const c = new THREE.Color();
    for (const g of glowSprites) { pos.push(g.x, g.y, g.z); c.set(g.c).multiplyScalar(g.o); colr.push(c.r, c.g, c.b); size.push(g.s); }
    const bg = new THREE.BufferGeometry();
    bg.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    bg.setAttribute('color', new THREE.Float32BufferAttribute(colr, 3));
    bg.setAttribute('size', new THREE.Float32BufferAttribute(size, 1));
    const mat = new THREE.ShaderMaterial({
      uniforms: { map: { value: game.glowTex }, uScale: { value: 600 } },
      vertexShader: 'attribute float size; attribute vec3 color; varying vec3 vC; uniform float uScale; void main(){ vC = color; vec4 mv = modelViewMatrix * vec4(position,1.0); gl_PointSize = size * uScale / -mv.z; gl_Position = projectionMatrix * mv; }',
      fragmentShader: 'uniform sampler2D map; varying vec3 vC; void main(){ gl_FragColor = vec4(vC * texture2D(map, gl_PointCoord).a, 1.0); }',
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    });
    const p = new THREE.Points(bg, mat); p.frustumCulled = false; p.layers.set(1);
    group.add(p); group.userData.glowMat = mat;
  }

  // ---------- 地面(濡れた路面: 反射 + 影 + 焼き込みライトマップ)
  const size = HALF * 2 + 400;
  const [groundImg] = await Promise.all([loadImage(mapData.ground)]);
  const maskTex = new THREE.Texture(groundImg); maskTex.flipY = false; maskTex.needsUpdate = true; maskTex.anisotropy = 8;
  const lightmap = T.makeGroundLightmap(2048, HALF * 2, glowLights.map((l) => ({ ...l, x: l.x + HALF, z: l.z + HALF })));
  lightmap.flipY = false; lightmap.needsUpdate = true;
  const planeGeo = new THREE.PlaneGeometry(size, size);
  const reflector = new Reflector(planeGeo, {
    textureWidth: Math.floor(innerWidth * 0.5), textureHeight: Math.floor(innerHeight * 0.5), multisample: 0, clipBias: 0.003,
    shader: { uniforms: { color: { value: null }, tDiffuse: { value: null }, textureMatrix: { value: null } },
      vertexShader: 'void main(){ gl_Position = vec4(2.0); }', fragmentShader: 'void main(){ discard; }' },
  });
  reflector.rotation.x = -Math.PI / 2;
  reflector.position.y = 0.0;
  reflector.material.colorWrite = false; reflector.material.depthWrite = false;
  reflector.renderOrder = -10;
  const origGet = reflector.getReflectionCamera;
  reflector.getReflectionCamera = (cam) => { const rc = origGet.call(reflector, cam); rc.layers.set(0); return rc; };
  reflector.frustumCulled = false;
  group.add(reflector);
  const groundU = {
    uMask: { value: maskTex }, uLight: { value: lightmap }, uHalf: { value: HALF }, uGrain: { value: T.makeGrain() },
    tRefl: { value: reflector.getRenderTarget().texture }, uTexMat: { value: reflector.material.uniforms.textureMatrix.value },
    uTime: { value: 0 }, uRain: { value: 1 }, uLightAmt: { value: 1 }, uWetness: { value: 1 },
    uAsA: { value: pbr.asphalt.albedo }, uAsN: { value: pbr.asphalt.normal }, uAsR: { value: pbr.asphalt.rough },
    uPvA: { value: pbr.pavers.albedo }, uPvN: { value: pbr.pavers.normal }, uCoA: { value: pbr.concrete.albedo },
  };
  const groundMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.6, metalness: 0.0 });
  groundMat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, groundU);
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nuniform mat4 uTexMat; varying vec4 vRefl; varying vec3 vW;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvRefl = uTexMat * vec4(position, 1.0); vW = (modelMatrix * vec4(position,1.0)).xyz;');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>
        uniform sampler2D uMask, uLight, uGrain, tRefl, uAsA, uAsN, uAsR, uPvA, uPvN, uCoA; uniform float uHalf, uTime, uRain, uLightAmt, uWetness;
        varying vec4 vRefl; varying vec3 vW;
        float h21(vec2 p){ return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
        vec2 ripple(vec2 p){ vec2 o = vec2(0.0); vec2 c0 = floor(p * 1.6);
          for (int i=-1;i<=1;i++) for (int j=-1;j<=1;j++){ vec2 c = c0 + vec2(float(i),float(j)); float h = h21(c);
            vec2 ctr = (c + vec2(h21(c+3.1), h21(c+7.7))) / 1.6; float t = fract(uTime*0.9 + h); vec2 d = p - ctr; float r = length(d);
            o += normalize(d + 1e-4) * sin((r - t*0.55)*60.0) * smoothstep(0.06,0.0,abs(r - t*0.55)) * (1.0 - t); }
          return o * 0.012 * uRain; }
        float gMark, gRoad, gWalk, gPuddle, gGrain;`)
      .replace('#include <color_fragment>', `#include <color_fragment>
        vec2 muv = (vW.xz + uHalf) / (2.0 * uHalf);
        vec3 mk = texture2D(uMask, muv).rgb;
        float inside = step(0.0, muv.x) * step(muv.x, 1.0) * step(0.0, muv.y) * step(muv.y, 1.0);
        gRoad = mk.r * inside; float white = mk.g * inside; float yellow = mk.b * gRoad; gWalk = mk.b * (1.0 - gRoad) * inside;
        gGrain = texture2D(uGrain, vW.xz * 0.35).r;
        gPuddle = smoothstep(0.52, 0.38, texture2D(uGrain, vW.xz * 0.018 + 0.3).r);
        // Blender で焼いた素材: アスファルト(8m), インターロッキング(2m), 広場の石(4m)
        vec3 asph = texture2D(uAsA, vW.xz / 8.0).rgb * 0.62;
        vec3 walkC = texture2D(uPvA, vW.xz / 2.0).rgb * 0.95;
        vec2 st = vW.xz / 0.9; vec2 sf = fract(st);
        vec3 plazaC = texture2D(uCoA, vW.xz / 4.0).rgb * 0.62 * (0.9 + 0.2 * h21(floor(st))) * (1.0 - (step(0.97, sf.x) + step(0.97, sf.y)) * 0.35);
        vec3 base = mix(plazaC, walkC, gWalk);
        base = mix(base, asph, gRoad);
        base = mix(base, vec3(0.62, 0.62, 0.58), clamp(white - yellow, 0.0, 1.0) * 0.25);
        diffuseColor.rgb = base;
        gMark = max(white, yellow);`)
      .replace('#include <roughnessmap_fragment>', `#include <roughnessmap_fragment>
        float rAs = texture2D(uAsR, vW.xz / 8.0).r;
        roughnessFactor = mix(mix(0.6, rAs * 0.7, gRoad), 0.06, gPuddle * gRoad * uWetness);
        roughnessFactor = mix(roughnessFactor * 1.3, roughnessFactor, uWetness);`)
      .replace('#include <normal_fragment_maps>', `#include <normal_fragment_maps>
        // 路面の凹凸(水たまりでは平ら)
        vec3 nA = texture2D(uAsN, vW.xz / 8.0).xyz * 2.0 - 1.0;
        vec3 nP = texture2D(uPvN, vW.xz / 2.0).xyz * 2.0 - 1.0;
        vec3 tn = mix(nP, nA, gRoad);
        tn.xy *= (1.0 - gPuddle * gRoad) * 1.2;
        vec3 wn = normalize(vec3(tn.x, tn.z, -tn.y));
        normal = normalize((viewMatrix * vec4(wn, 0.0)).xyz);`)
      .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
        vec3 lm = texture2D(uLight, (vW.xz + uHalf) / (2.0 * uHalf)).rgb;
        totalEmissiveRadiance += diffuseColor.rgb * lm * 2.4 * uLightAmt;`)
      .replace('#include <opaque_fragment>', `
        vec3 toCam = normalize(cameraPosition - vW);
        float fres = 0.06 + 0.94 * pow(1.0 - max(toCam.y, 0.0), 4.0);
        vec2 dist = (vec2(gGrain, texture2D(uGrain, vW.xz * 0.35 + 0.5).r) - 0.5) * 0.03 * (1.0 - gPuddle) + ripple(vW.xz) * gPuddle;
        vec4 ru = vRefl; ru.xy += dist * ru.w;
        vec3 refl = texture2DProj(tRefl, ru).rgb;
        float wet = mix(0.25, 1.0, gPuddle) * (1.0 - gMark * 0.5) * mix(0.45, 1.0, gRoad) * uWetness;
        outgoingLight += refl * fres * wet;
        #include <opaque_fragment>`);
  };
  const ground = new THREE.Mesh(planeGeo, groundMat);
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  ground.layers.set(1); // 反射の描画(レイヤー0)には含めない: 自分の反射テクスチャを読むため
  group.add(ground);

  // 路面標示(白線・黄線・横断歩道・停止線)を実際の形状として貼る(遠くでも潰れない)
  if (M.marks?.length) {
    const pos = [], col = [];
    const W = [0.78, 0.78, 0.74], Yc = [0.8, 0.55, 0.1];
    for (const q of M.marks) {
      const c = q[8] ? Yc : W;
      const v = [[q[0], q[1]], [q[2], q[3]], [q[4], q[5]], [q[6], q[7]]];
      for (const k of [0, 2, 1, 0, 3, 2]) { pos.push(v[k][0], 0.012, v[k][1]); col.push(...c); }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    g.computeVertexNormals();
    const mm = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.55, polygonOffset: true, polygonOffsetFactor: -2, side: THREE.DoubleSide });
    // 塗料もうっすら濡れて、ライトマップの光を受ける
    mm.onBeforeCompile = (sh) => {
      sh.uniforms.uLight = groundU.uLight; sh.uniforms.uHalf = groundU.uHalf; sh.uniforms.uLightAmt = groundU.uLightAmt;
      sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vW2;')
        .replace('#include <begin_vertex>', '#include <begin_vertex>\nvW2 = (modelMatrix * vec4(position,1.0)).xyz;');
      sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nvarying vec3 vW2; uniform sampler2D uLight; uniform float uHalf, uLightAmt;')
        .replace('#include <emissivemap_fragment>', '#include <emissivemap_fragment>\ntotalEmissiveRadiance += diffuseColor.rgb * texture2D(uLight, (vW2.xz + uHalf) / (2.0 * uHalf)).rgb * 2.0 * uLightAmt;');
    };
    const marks = new THREE.Mesh(g, mm);
    marks.receiveShadow = true;
    marks.layers.set(1);
    group.add(marks);
  }

  // ワールドの端(見えない壁)
  const E = HALF - 2;
  col.addSeg(-E, -E, E, -E); col.addSeg(E, -E, E, E); col.addSeg(E, E, -E, E); col.addSeg(-E, E, -E, -E);

  const roads = new RoadGraph(M.roads);
  // 路肩の駐車スポット(細い道)
  const parkedSpots = [];
  for (const e of roads.edges) {
    if (e.w < 7 || e.w > 12 || e.ow || e.len < 30 || Math.random() > 0.3) continue;
    const line = offsetLine(e.pts, e.w / 2 - 1.1);
    const k = Math.floor(line.length / 2);
    const a = line[Math.max(0, k - 1)], b = line[Math.min(line.length - 1, k)];
    if (!a || !b || (a[0] === b[0] && a[1] === b[1])) continue;
    parkedSpots.push({ x: (a[0] + b[0]) / 2, z: (a[1] + b[1]) / 2, yaw: Math.atan2(-(b[0] - a[0]), -(b[1] - a[1])) });
  }

  const minimapImg = await loadImage(mapData.minimap);
  return {
    group, colliders: col, roads, lamps: lampSpots, shopFronts, parkedSpots, vendings, landmarks: M.landmarks, half: HALF,
    buildingMeshes, minimapImg, signals: signalObjs, trains,
    look: { uDay, facadeMats, storeMat, vSignMat, hSignMat, groundU, aviMat, glow: () => group.userData.glowMat, lampMats: collectLampMats(group) },
    update(t, dt) {
      groundU.uTime.value = t;
      aviMat.opacity = Math.sin(t * 3) > 0 ? 1 : 0.1;
      signalObjs.update(t);
      trains.update(dt);
    },
    setGlowScale(s) { group.userData.glowMat.uniforms.uScale.value = s; },
  };
}

function collectLampMats(group) {
  const out = new Set();
  group.traverse((o) => { if (o.isMesh && o.material?.name === 'Light_LED') out.add(o.material); });
  return [...out];
}

// glb の小物をまとめて InstancedMesh にする。
// 120m 四方の区画ごとに分け、画面外・影の範囲外の区画は描画しない(視錐台カリング)
const CHUNK = 120;
function chunked(list) {
  const m = new Map();
  for (const t of list) {
    const k = `${Math.floor(t.x / CHUNK)},${Math.floor(t.z / CHUNK)}`;
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(t);
  }
  return [...m.values()];
}
function instanceAsset(src, list, shadow = false) {
  const g = new THREE.Group();
  if (!list.length) return g;
  src.updateMatrixWorld(true);
  const Mx = new THREE.Matrix4(), Q = new THREE.Quaternion(), Y = new THREE.Vector3(0, 1, 0);
  const parts = [];
  src.traverse((mesh) => { if (mesh.isMesh) parts.push({ geo: mesh.geometry.clone().applyMatrix4(mesh.matrixWorld), mat: mesh.material }); });
  for (const chunk of chunked(list)) {
    for (const { geo, mat } of parts) {
      const im = new THREE.InstancedMesh(geo, mat, chunk.length);
      chunk.forEach((t, n) => { Mx.compose(new THREE.Vector3(t.x, t.y ?? 0, t.z), Q.setFromAxisAngle(Y, t.yaw ?? 0), new THREE.Vector3().setScalar(t.s ?? 1)); im.setMatrixAt(n, Mx); });
      im.computeBoundingSphere();
      im.castShadow = shadow; im.receiveShadow = shadow;
      g.add(im);
    }
  }
  return g;
}

// 信号機: 灯器ごとに InstancedMesh にして色(明るさ)で点灯を表す
// 周期 40 秒: 軸A 青17→黄3→全赤2 / 軸B 青15→黄3
export function signalState(nodeIdx, yaw, t) {
  // yaw = 交差点へ向かう進行方向。南北寄りか東西寄りかで2つの系統に分ける
  const axis = Math.abs(Math.cos(yaw)) > Math.abs(Math.sin(yaw)) ? 0 : 1;
  const ph = (t + nodeIdx * 7.3) % 40;
  const a = ph < 17 ? 'G' : ph < 20 ? 'Y' : ph < 22 ? 'R' : 'R';
  const b = ph < 22 ? 'R' : ph < 37 ? 'G' : 'Y';
  return axis === 0 ? a : b;
}
function buildSignals(group, src, list) {
  const g = new THREE.Group();
  src.updateMatrixWorld(true);
  const Mx = new THREE.Matrix4(), Q = new THREE.Quaternion(), Y = new THREE.Vector3(0, 1, 0);
  const lamps = {};
  src.traverse((mesh) => {
    if (!mesh.isMesh) return;
    const geo = mesh.geometry.clone().applyMatrix4(mesh.matrixWorld);
    const name = mesh.name.startsWith('Lamp_') || mesh.name.startsWith('Ped_') ? mesh.name : null;
    const mat = name ? new THREE.MeshBasicMaterial({ color: 0xffffff }) : mesh.material;
    const im = new THREE.InstancedMesh(geo, mat, list.length);
    list.forEach(([x, z, yaw], n) => {
      // yaw は進行方向 d=(sin,cos)。腕(ローカル -Z)を車道側=進行方向の右 (-dz, dx) へ、灯器(ローカル +X)を対向(-d)へ
      const dx = Math.sin(yaw), dz = Math.cos(yaw);
      Mx.compose(new THREE.Vector3(x, 0, z), Q.setFromAxisAngle(Y, Math.atan2(dz, -dx)), new THREE.Vector3(1, 1, 1));
      im.setMatrixAt(n, Mx);
    });
    if (name) { lamps[name] = im; im.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(list.length * 3), 3); }
    else { im.castShadow = true; }
    g.add(im);
  });
  group.add(g);
  const base = { Lamp_G: new THREE.Color(0.1, 1, 0.7), Lamp_Y: new THREE.Color(1, 0.7, 0.05), Lamp_R: new THREE.Color(1, 0.06, 0.04), Ped_G: new THREE.Color(0.1, 1, 0.7), Ped_R: new THREE.Color(1, 0.06, 0.04) };
  const c = new THREE.Color();
  let last = -1;
  return {
    list,
    update(t) {
      const sec = Math.floor(t * 2);
      if (sec === last) return;
      last = sec;
      list.forEach(([x, z, yaw, arm, node], n) => {
        const st = signalState(node, yaw, t);
        for (const k of ['G', 'Y', 'R']) {
          const on = st === k;
          lamps['Lamp_' + k]?.setColorAt(n, c.copy(base['Lamp_' + k]).multiplyScalar(on ? 5 : 0.05));
        }
        const pedGo = st === 'R';
        lamps.Ped_G?.setColorAt(n, c.copy(base.Ped_G).multiplyScalar(pedGo ? 3 : 0.05));
        lamps.Ped_R?.setColorAt(n, c.copy(base.Ped_R).multiplyScalar(pedGo ? 0.05 : 3));
      });
      for (const im of Object.values(lamps)) im.instanceColor.needsUpdate = true;
    },
  };
}

// 工事現場: Poly Haven の金網フェンスで囲った空き地(カラーコーン・看板・資材)
function buildSites(group, assets, col, M) {
  const src = assets.get('ph_fence');
  const section = src.getObjectByName('modular_chainlink_fence_double');
  const post = src.getObjectByName('modular_chainlink_fence_post');
  if (!section) return;
  src.traverse((o) => { if (o.isMesh && /wire/.test(o.material.name)) { o.material.alphaTest = 0.4; o.material.side = THREE.DoubleSide; o.material.transparent = false; } });
  const roads = new RoadGraph(M.roads);
  const secs = [], posts = [], cones = [], stacks = [];
  const SEG = 1.91;
  let sites = 0;
  for (let tries = 0; tries < 400 && sites < 4; tries++) {
    const x = rand(-M.half + 40, M.half - 40), z = rand(-M.half + 40, M.half - 40);
    const W = randi(4, 7) * SEG, D = randi(3, 5) * SEG, yaw = rand(0, Math.PI);
    if (col.inside(x, z, Math.hypot(W, D) / 2 + 2)) continue;
    const r = roads.nearestEdge(x, z);
    if (!r || r.d < r.e.w / 2 + Math.hypot(W, D) / 2 + 3 || r.d > 45) continue; // 車道に面した空き地
    sites++;
    const c = Math.cos(yaw), s = Math.sin(yaw);
    const P = (lx, lz) => [x + lx * c + lz * s, z - lx * s + lz * c];
    const corners = [[-W / 2, -D / 2], [W / 2, -D / 2], [W / 2, D / 2], [-W / 2, D / 2]];
    for (let k = 0; k < 4; k++) {
      const [ax, az] = corners[k], [bx, bz] = corners[(k + 1) % 4];
      const len = Math.hypot(bx - ax, bz - az), n = Math.round(len / SEG);
      const eyaw = yaw + Math.atan2(-(bz - az), bx - ax);
      for (let i = 0; i < n; i++) {
        if (k === 0 && i === Math.floor(n / 2)) continue; // 出入口
        const t = (i + 0.5) / n;
        const [px, pz] = P(ax + (bx - ax) * t, az + (bz - az) * t);
        secs.push({ x: px, z: pz, yaw: eyaw });
      }
      const [px, pz] = P(ax, az);
      posts.push({ x: px, z: pz });
      const [qa, qb] = [P(ax, az), P(bx, bz)];
      col.addSeg(qa[0], qa[1], qb[0], qb[1], 'fence');
    }
    for (let i = 0; i < 5; i++) { const [px, pz] = P(rand(-W / 2, W / 2), -D / 2 - rand(0.6, 1.4)); cones.push({ x: px, z: pz, yaw: rand(0, 6) }); }
    for (let i = 0; i < 3; i++) { const [px, pz] = P(rand(-W / 3, W / 3), rand(-D / 4, D / 4)); stacks.push({ x: px, z: pz, yaw: yaw + rand(-0.3, 0.3), s: rand(0.8, 1.3) }); }
    // 工事中の看板
    const cv = document.createElement('canvas'); cv.width = 256; cv.height = 320;
    const g = cv.getContext('2d');
    g.fillStyle = '#f2f2ee'; g.fillRect(0, 0, 256, 320);
    for (let yy = 0; yy < 40; yy += 20) { g.fillStyle = yy % 40 ? '#111' : '#f5c400'; }
    g.fillStyle = '#f5c400'; g.fillRect(0, 0, 256, 40); g.fillStyle = '#111';
    for (let xx = -40; xx < 256; xx += 40) { g.beginPath(); g.moveTo(xx, 40); g.lineTo(xx + 20, 40); g.lineTo(xx + 40, 0); g.lineTo(xx + 20, 0); g.fill(); }
    g.fillStyle = '#c4161c'; g.font = '900 64px "Zen Kaku Gothic New", sans-serif'; g.textAlign = 'center';
    g.fillText('工事中', 128, 120);
    g.fillStyle = '#222'; g.font = '700 22px "Zen Kaku Gothic New", sans-serif';
    g.fillText('ご迷惑をおかけします', 128, 175); g.fillText('八重洲二丁目 再開発', 128, 215);
    g.fillText('施工 ヤマ建設', 128, 255);
    const tx = new THREE.CanvasTexture(cv); tx.colorSpace = THREE.SRGBColorSpace;
    const board = new THREE.Mesh(new THREE.PlaneGeometry(1.2, 1.5), new THREE.MeshStandardMaterial({ map: tx, roughness: 0.6 }));
    const [bx2, bz2] = P(W / 4, -D / 2 - 0.08);
    board.position.set(bx2, 1.2, bz2); board.rotation.y = yaw + Math.PI;
    group.add(board);
  }
  group.add(instanceAsset(section, secs, true), instanceAsset(post ?? section, posts, true));
  if (assets.get('cone')) group.add(instanceAsset(assets.get('cone'), cones));
  const sg = new THREE.BoxGeometry(2.6, 0.5, 1.1); sg.translate(0, 0.25, 0);
  const sm = new THREE.InstancedMesh(sg, new THREE.MeshStandardMaterial({ color: 0x7c6a52, roughness: 0.9 }), stacks.length);
  const Mx = new THREE.Matrix4(), Q = new THREE.Quaternion(), Y = new THREE.Vector3(0, 1, 0);
  stacks.forEach((t, i) => { Mx.compose(new THREE.Vector3(t.x, 0, t.z), Q.setFromAxisAngle(Y, t.yaw), new THREE.Vector3(t.s, t.s, t.s)); sm.setMatrixAt(i, Mx); });
  sm.castShadow = sm.receiveShadow = true;
  group.add(sm);
  group.userData.sites = sites;
}

// 歩道のガードレール(白い横柵)
function buildFences(list) {
  const rail = new THREE.BoxGeometry(1, 0.06, 0.05);
  const post = new THREE.BoxGeometry(0.06, 0.8, 0.06); post.translate(0, 0.4, 0);
  const rails = [], posts = [];
  for (const [ax, az, bx, bz] of list) {
    const len = Math.hypot(bx - ax, bz - az);
    const yaw = Math.atan2(-(bz - az), bx - ax);
    for (const y of [0.45, 0.78]) rails.push({ x: (ax + bx) / 2, y, z: (az + bz) / 2, len, yaw });
    for (let t = 0; t < len; t += 2) posts.push({ x: ax + (bx - ax) * t / len, z: az + (bz - az) * t / len });
  }
  const m = new THREE.MeshStandardMaterial({ color: 0xd8dadc, roughness: 0.4, metalness: 0.5 });
  const g = new THREE.Group();
  const Mx = new THREE.Matrix4(), Q = new THREE.Quaternion(), Y = new THREE.Vector3(0, 1, 0);
  const ri = new THREE.InstancedMesh(rail, m, rails.length);
  rails.forEach((r, i) => { Mx.compose(new THREE.Vector3(r.x, r.y, r.z), Q.setFromAxisAngle(Y, r.yaw), new THREE.Vector3(r.len, 1, 1)); ri.setMatrixAt(i, Mx); });
  const pi = new THREE.InstancedMesh(post, m, posts.length);
  posts.forEach((p, i) => { Mx.makeTranslation(p.x, 0, p.z); pi.setMatrixAt(i, Mx); });
  ri.castShadow = pi.castShadow = true;
  g.add(ri, pi);
  return g;
}

// 高架を走る電車(銀色の車体に緑の帯)
function makeTrains(group, rails, VH) {
  const lines = rails.filter((p) => lineLen(p) > 300).sort((a, b) => lineLen(b) - lineLen(a)).slice(0, 4);
  const carG = new THREE.BoxGeometry(2.9, 3.4, 19.5); carG.translate(0, 1.9, 0);
  const body = new THREE.MeshStandardMaterial({ color: 0xc8ccd0, metalness: 0.8, roughness: 0.3 });
  const cT = document.createElement('canvas'); cT.width = 256; cT.height = 64;
  const g = cT.getContext('2d');
  g.fillStyle = '#c8ccd0'; g.fillRect(0, 0, 256, 64);
  g.fillStyle = '#1a1d22'; for (let x = 8; x < 256; x += 30) g.fillRect(x, 14, 22, 18);
  g.fillStyle = '#4fc36a'; g.fillRect(0, 36, 256, 6);
  const et = document.createElement('canvas'); et.width = 256; et.height = 64;
  const eg = et.getContext('2d'); eg.fillStyle = '#000'; eg.fillRect(0, 0, 256, 64);
  eg.fillStyle = '#fff4dc'; for (let x = 8; x < 256; x += 30) eg.fillRect(x, 14, 22, 18);
  const side = new THREE.MeshStandardMaterial({ map: new THREE.CanvasTexture(cT), emissiveMap: new THREE.CanvasTexture(et), emissive: 0xffffff, emissiveIntensity: 1.4, metalness: 0.7, roughness: 0.3 });
  side.map.colorSpace = side.emissiveMap.colorSpace = THREE.SRGBColorSpace;
  const mats = [side, side, body, body, body, body];
  const trains = lines.map((P, k) => {
    const cars = [];
    for (let i = 0; i < 10; i++) { const m = new THREE.Mesh(carG, mats); m.castShadow = true; group.add(m); cars.push(m); }
    return { P, L: lineLen(P), s: k * 120, speed: 12 + k * 2, dir: k % 2 ? -1 : 1, cars, wait: 0 };
  });
  const at = (P, t) => {
    let acc = 0;
    for (let i = 0; i + 1 < P.length; i++) {
      const l = Math.hypot(P[i + 1][0] - P[i][0], P[i + 1][1] - P[i][1]);
      if (acc + l >= t) { const u = (t - acc) / (l || 1); return [P[i][0] + (P[i + 1][0] - P[i][0]) * u, P[i][1] + (P[i + 1][1] - P[i][1]) * u]; }
      acc += l;
    }
    return P[P.length - 1];
  };
  return {
    list: trains,
    update(dt) {
      for (const tr of trains) {
        tr.s += tr.speed * tr.dir * dt;
        const span = 10 * 20;
        if (tr.s > tr.L + span) tr.s = -span;
        if (tr.s < -span) tr.s = tr.L + span;
        tr.cars.forEach((m, i) => {
          const s = tr.s - i * 20 * tr.dir;
          const inside = s > 0 && s < tr.L;
          m.visible = inside;
          if (!inside) return;
          const a = at(tr.P, Math.max(0, s - 9)), b = at(tr.P, Math.min(tr.L, s + 9));
          m.position.set((a[0] + b[0]) / 2, VH + 0.2, (a[1] + b[1]) / 2);
          m.rotation.y = Math.atan2(b[0] - a[0], b[1] - a[1]);
        });
      }
    },
  };
}
