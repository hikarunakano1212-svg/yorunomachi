// 車両: 物理(アーケード寄り)、一般車の交通AI、パトカーの追跡AI
import * as THREE from 'three';
import { signalState } from './yaesu.js';
import { rand, randi, pick, clamp, wrapAngle, damp } from './util.js';
import { makeGlowSprite } from './textures.js';
import { carTemplate, carMaterial } from './carmodel.js';

export const SPECS = {
  kei:    { model: 'car_kei',    L: 3.4, W: 1.48, maxSpeed: 31, acc: 11, price: 45000,  eye: [0.34, 1.34, 0.25], name: '軽自動車' },
  sedan:  { model: 'car_sedan',  L: 4.9, W: 1.8,  maxSpeed: 42, acc: 14, price: 110000, eye: [0.4, 1.18, 0.45], name: 'セダン' },
  taxi:   { model: 'car_taxi',   L: 4.4, W: 1.7,  maxSpeed: 36, acc: 12, price: 80000,  eye: [0.38, 1.36, 0.1], name: 'タクシー' },
  police: { model: 'car_police', L: 4.9, W: 1.8,  maxSpeed: 47, acc: 17, price: 260000, eye: [0.4, 1.18, 0.45], name: 'パトカー' },
  van:    { model: 'car_van',    L: 4.7, W: 1.7,  maxSpeed: 33, acc: 10, price: 90000,  eye: [0.4, 1.55, -1.6], name: 'バン' },
  truck:  { model: 'car_truck',  L: 6.2, W: 1.9,  maxSpeed: 28, acc: 8,  price: 140000, eye: [0.45, 1.85, -2.4], name: '2tトラック' },
  bus:    { model: 'car_bus',    L: 10.5, W: 2.5, maxSpeed: 24, acc: 6,  price: 200000, eye: [0.8, 2.3, -4.3], name: '都営バス' },
};
const KEI_COLORS = [0xf2f2ee, 0xb9bcc0, 0x16171a, 0x9fd9c8, 0xf0b7c4, 0xe8d36a, 0x7aa0d8, 0xc4402f];
const SEDAN_COLORS = [0x1a1b20, 0xe9e9e6, 0x8d9096, 0x2a3550, 0x5a1b1e, 0xdadbd6];
const TAXI_COLORS = [0x1d2340, 0x1d2340, 0x1d2340, 0xf2c230, 0x2e6b3a];   // JPN TAXI の深藍が多い
const VAN_COLORS = [0xf0f0ee, 0xf0f0ee, 0xb9bcc0];
const TRUCK_COLORS = [0x3f8a4c, 0xe9e9e6, 0x2e5fa8];
function paintFor(kind) {
  return { police: 0x0d0d0f, taxi: pick(TAXI_COLORS), kei: pick(KEI_COLORS), van: pick(VAN_COLORS), truck: pick(TRUCK_COLORS), bus: 0xe9ece6 }[kind] ?? pick(SEDAN_COLORS);
}

let blobMat = null;
function blobMaterial() {
  if (blobMat) return blobMat;
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(32, 32, 4, 32, 32, 32);
  grd.addColorStop(0, 'rgba(0,0,0,0.75)'); grd.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = grd; g.fillRect(0, 0, 64, 64);
  blobMat = new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false });
  return blobMat;
}

let headTex = null;
function headlightTexture() {
  if (headTex) return headTex;
  const c = document.createElement('canvas'); c.width = 64; c.height = 128;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(32, 128, 0, 32, 128, 128);
  grd.addColorStop(0, 'rgba(255,240,210,0.9)'); grd.addColorStop(0.5, 'rgba(255,230,200,0.25)'); grd.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = grd; g.fillRect(0, 0, 64, 128);
  headTex = new THREE.CanvasTexture(c); headTex.colorSpace = THREE.SRGBColorSpace;
  return headTex;
}

const _v = new THREE.Vector3();

export class Car {
  constructor(game, kind, x, z, yaw, color) {
    this.game = game;
    this.kind = kind;
    this.spec = SPECS[kind];
    const src = game.assets.get(this.spec.model);
    const tpl = carTemplate(src, { andon: true });
    const paint = color ?? paintFor(kind);
    this.mat = carMaterial(paint);
    this.obj = new THREE.Group();
    this.bodyMesh = new THREE.Mesh(tpl.body, this.mat);
    this.bodyMesh.castShadow = true; this.bodyMesh.receiveShadow = true;
    this.obj.add(this.bodyMesh);
    // 車体の下の接地影(夜は光源が多いので、ぼかした暗がりを足す)
    const blob = new THREE.Mesh(new THREE.PlaneGeometry(this.spec.W * 1.5, this.spec.L * 1.15), blobMaterial());
    blob.rotation.x = -Math.PI / 2; blob.position.y = 0.03; blob.layers.set(1);
    this.obj.add(blob);
    // タイヤ(回転・操舵するので別メッシュ。路面反射には映さない)
    const order = ['FL', 'FR', 'RL', 'RR'];
    this.wheels = order.map((t) => {
      const w = tpl.wheels.find((q) => q.tag === t);
      const m = new THREE.Mesh(w.geo, this.mat);
      m.position.copy(w.pos); m.rotation.order = 'YXZ'; m.layers.set(1); m.castShadow = true;
      this.obj.add(m);
      return m;
    });
    // 地面を照らすヘッドライトの光だまり
    const beam = new THREE.Mesh(new THREE.PlaneGeometry(4.2, 11),
      new THREE.MeshBasicMaterial({ map: headlightTexture(), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, opacity: 0.55 }));
    beam.rotation.x = -Math.PI / 2;
    beam.position.set(0, 0.04, -this.spec.L / 2 - 5.2);
    beam.layers.set(1);
    this.obj.add(beam);
    this.beam = beam;
    game.scene.add(this.obj);

    this.pos = new THREE.Vector3(x, 0, z);
    this.yaw = yaw;
    this.vel = new THREE.Vector2();
    this.speed = 0;          // 前後方向の速度(m/s)
    this.steer = 0;
    this.hp = 100;
    this.driver = null;      // 'npc' | 'player' | 'police' | null
    this.ai = null;
    this.wheelSpin = 0;
    this.braking = false;
    this.dead = false;
    this.smoke = 0;
    this.siren = kind === 'police';
    this.sync();
  }

  get fwd() { return _v.set(-Math.sin(this.yaw), 0, -Math.cos(this.yaw)); }
  circles() {
    // 車長に応じて円を並べる(バスは5個ほど)
    const n = Math.max(2, Math.round(this.spec.L / this.spec.W));
    const f = this.spec.L / 2 - this.spec.W / 2;
    const fx = -Math.sin(this.yaw), fz = -Math.cos(this.yaw);
    const out = [];
    for (let k = 0; k < n; k++) { const t = -f + (2 * f * k) / (n - 1); out.push({ x: this.pos.x + fx * t, z: this.pos.z + fz * t }); }
    return out;
  }
  get radius() { return this.spec.W / 2 + 0.1; }

  // 入力: throttle(-1..1), steer(-1..1), handbrake(bool)
  drive(dt, throttle, steerIn, handbrake) {
    const s = this.spec;
    const fx = -Math.sin(this.yaw), fz = -Math.cos(this.yaw);
    const rx = Math.cos(this.yaw), rz = -Math.sin(this.yaw);
    let vF = this.vel.x * fx + this.vel.y * fz;
    let vR = this.vel.x * rx + this.vel.y * rz;
    const broken = this.hp <= 0;
    if (broken) throttle = Math.min(throttle, 0) * 0.2;
    this.braking = false;
    if (throttle > 0) {
      if (vF < -0.5) { vF += 22 * dt * throttle; this.braking = true; }
      else vF += s.acc * throttle * dt * (1 - Math.pow(Math.max(vF, 0) / s.maxSpeed, 2));
    } else if (throttle < 0) {
      if (vF > 0.5) { vF += 24 * dt * throttle; this.braking = true; }
      else vF = Math.max(vF + 8 * throttle * dt, -9);
    } else {
      vF -= Math.sign(vF) * Math.min(Math.abs(vF), 2.2 * dt);
    }
    vF -= vF * 0.08 * dt;
    if (handbrake) { vF -= Math.sign(vF) * Math.min(Math.abs(vF), 9 * dt); this.braking = true; }
    const grip = handbrake ? 1.4 : 7.5;
    vR *= Math.exp(-grip * dt);
    this.steer = damp(this.steer, steerIn, 8, dt);
    const angle = this.steer * 0.55 / (1 + Math.abs(vF) * 0.12);
    const yawRate = (vF * Math.tan(angle)) / (s.L * 0.6) * (handbrake ? 1.35 : 1);
    this.yaw += yawRate * dt;
    const nfx = -Math.sin(this.yaw), nfz = -Math.cos(this.yaw);
    const nrx = Math.cos(this.yaw), nrz = -Math.sin(this.yaw);
    this.vel.set(nfx * vF + nrx * vR, nfz * vF + nrz * vR);
    this.speed = vF;
    this.slip = Math.abs(vR);
    this.integrate(dt);
  }

  integrate(dt) {
    this.pos.x += this.vel.x * dt;
    this.pos.z += this.vel.y * dt;
    // 建物との衝突(車体に沿って並べた円)
    const r = this.radius;
    const n = Math.max(2, Math.round(this.spec.L / this.spec.W));
    const f = this.spec.L / 2 - this.spec.W / 2;
    for (let k = 0; k < n; k++) {
      const t = -f + (2 * f * k) / (n - 1);
      const fx = -Math.sin(this.yaw) * t, fz = -Math.cos(this.yaw) * t;
      const c = { x: this.pos.x + fx, z: this.pos.z + fz };
      const hit = this.game.city.colliders.resolve(c, r);
      if (hit) {
        this.pos.x = c.x - fx; this.pos.z = c.z - fz;
        const vn = this.vel.x * hit.nx + this.vel.y * hit.nz;
        if (vn < 0) {
          this.vel.x -= vn * hit.nx * 1.3; this.vel.y -= vn * hit.nz * 1.3;
          this.vel.multiplyScalar(0.85);
          this.impact(-vn, hit.c.tag);
        }
      }
    }
    this.pos.y = 0;
  }

  impact(v, what) {
    if (v < 2) return;
    this.hp = Math.max(0, this.hp - v * (this.kind === 'police' ? 0.9 : 1.4));
    if (this.driver === 'player') {
      this.game.shake(Math.min(1, v / 18));
      this.game.audio.crash(Math.min(1, v / 20));
    } else if (this.game.player && this.pos.distanceTo(this.game.player.pos) < 40) {
      this.game.audio.crash(Math.min(0.6, v / 25));
    }
  }

  sync(dt = 0) {
    this.obj.position.copy(this.pos);
    this.obj.rotation.set(0, this.yaw, 0);
    // 車体のロール・ピッチ(加減速と旋回で少し傾く)
    const lean = clamp(this.steer * this.speed * 0.004, -0.06, 0.06);
    this.obj.rotation.z = -lean;
    this.wheelSpin += (this.speed / 0.3) * dt;
    this.wheels.forEach((w, i) => {
      if (!w) return;
      w.rotation.x = -this.wheelSpin;
      if (i < 2) w.rotation.y = this.steer * 0.5;
    });
    const u = this.mat.userData.u;
    u.uBrake.value = this.wrecked ? 0 : this.braking ? 3.5 : 1;
    if (this.kind === 'police') {
      const on = this.siren && this.driver === 'police';
      const ph = Math.floor(performance.now() / 166) % 2;
      if (on) u.uSiren.value.setRGB(ph ? 12 : 0.5, 0, ph ? 0.5 : 12);
      else u.uSiren.value.setRGB(0.4, 0.02, 0.02);
    }
    this.beam.visible = this.hp > 0;
  }

  remove() { this.game.scene.remove(this.obj); this.dead = true; }
}

// ---------------------------------------------------------------- 一般車の交通(実際の道路網・左側通行・信号)
function bezier(p0, p1, p2, n = 8) {
  const out = [];
  for (let k = 1; k <= n; k++) {
    const u = k / n, iu = 1 - u;
    out.push([iu * iu * p0[0] + 2 * iu * u * p1[0] + u * u * p2[0], iu * iu * p0[1] + 2 * iu * u * p1[1] + u * u * p2[1]]);
  }
  return out;
}

// 道路を走るための経路(折れ線)を順に消費していく。
// junctions: 各区間の終点(=交差点の手前)の点番号・ノード・進入方向
class Route {
  constructor(graph) { this.g = graph; this.pts = []; this.i = 0; this.u = 0; this.junctions = []; }
  static start(graph, out, lane, s0) {
    const r = new Route(graph);
    r.lane = Math.min(lane, graph.laneCount(out.e) - 1);
    r.appendLeg(out, graph.lanePath(out.e, out.dir, r.lane));
    r.advance(s0);
    return r;
  }
  appendLeg(out, p) {
    this.last = out;
    this.pts.push(...(this.pts.length ? p.slice(1) : p));
    const a = p[Math.max(0, p.length - 2)], b = p[p.length - 1];
    this.junctions.push({ idx: this.pts.length - 1, node: this.g.nodes[out.to], yaw: Math.atan2(b[0] - a[0], b[1] - a[1]) });
  }
  lenFromHere(idx) {
    let L = -this.u;
    for (let k = this.i; k < idx && k + 1 < this.pts.length; k++) L += Math.hypot(this.pts[k + 1][0] - this.pts[k][0], this.pts[k + 1][1] - this.pts[k][1]);
    return L;
  }
  remaining() { return this.lenFromHere(this.pts.length - 1); }
  // 次の交差点(まだ通過していないもの)
  nextJunction() {
    while (this.junctions.length && this.junctions[0].idx < this.i) this.junctions.shift();
    const j = this.junctions[0];
    return j ? { ...j, dist: this.lenFromHere(j.idx) } : null;
  }
  // 行き先の区間を選び、交差点内のカーブと次の区間をつなげる
  chooseNext(prefer) {
    const n = this.g.nodes[this.last.to];
    let opts = n.out.filter((o) => o.e !== this.last.e);
    if (!opts.length) opts = n.out;
    if (!opts.length) return false;
    const next = prefer ? prefer(opts) : pick(opts);
    const nl = Math.min(this.lane, this.g.laneCount(next.e) - 1);
    const np = this.g.lanePath(next.e, next.dir, nl);
    const end = this.pts[this.pts.length - 1], prev = this.pts[this.pts.length - 2] ?? end;
    const start = np[0];
    const gap = Math.hypot(start[0] - end[0], start[1] - end[1]);
    const d0 = [end[0] - prev[0], end[1] - prev[1]], l0 = Math.hypot(d0[0], d0[1]) || 1;
    const ctrl = [end[0] + (d0[0] / l0) * gap * 0.5, end[1] + (d0[1] / l0) * gap * 0.5];
    this.pts.push(...bezier(end, ctrl, start, 8).slice(0, -1));
    this.lane = nl;
    this.appendLeg(next, np);
    if (this.i > 60) { // 消費済みの点を捨てる
      const cut = this.i;
      this.pts = this.pts.slice(cut); this.i = 0;
      for (const j of this.junctions) j.idx -= cut;
    }
    return true;
  }
  advance(d) {
    while (d > 0 && this.i + 1 < this.pts.length) {
      const a = this.pts[this.i], b = this.pts[this.i + 1];
      const l = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (this.u + d < l) { this.u += d; d = 0; }
      else { d -= l - this.u; this.u = 0; this.i++; }
    }
  }
  pos() {
    const a = this.pts[this.i], b = this.pts[Math.min(this.i + 1, this.pts.length - 1)];
    const l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
    const t = this.u / l;
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, Math.atan2(-(b[0] - a[0]), -(b[1] - a[1]))];
  }
}

const TRAFFIC_MIX = [['sedan', 26], ['taxi', 24], ['kei', 14], ['van', 12], ['truck', 10], ['bus', 5]];
function pickKind() {
  let r = Math.random() * TRAFFIC_MIX.reduce((s, [, w]) => s + w, 0);
  for (const [k, w] of TRAFFIC_MIX) { if ((r -= w) <= 0) return k; }
  return 'sedan';
}

export class Traffic {
  constructor(game, count = 26) {
    this.game = game;
    this.cars = [];
    this.target = count;
  }

  spawnNpc(nearX, nearZ, minD = 70, maxD = 170) {
    const g = this.game.city.roads;
    for (let tries = 0; tries < 25; tries++) {
      const e = pick(g.edges);
      if (e.len < 30) continue;
      const dirs = e.ow ? [1] : [1, -1];
      const dir = pick(dirs);
      const out = { e, dir, to: dir > 0 ? e.b : e.a };
      const lane = randi(0, g.laneCount(e) - 1);
      const route = Route.start(g, out, lane, rand(0, e.len * 0.5));
      const [x, z, yaw] = route.pos();
      const d = Math.hypot(x - nearX, z - nearZ);
      if (d < minD || d > maxD) continue;
      if (this.game.allCars().some((c) => Math.hypot(c.pos.x - x, c.pos.z - z) < 14)) continue;
      const kind = e.w < 7 && Math.random() < 0.6 ? 'kei' : pickKind();
      if (kind === 'bus' && e.w < 10) continue;
      const car = new Car(this.game, kind, x, z, yaw);
      car.driver = 'npc';
      car.ai = { route, speed: 0, wait: 0, cruise: rand(9, 13) * (kind === 'bus' || kind === 'truck' ? 0.8 : 1), honk: 0 };
      this.cars.push(car);
      return car;
    }
    return null;
  }

  update(dt) {
    const g = this.game;
    const px = g.player.pos.x, pz = g.player.pos.z;
    for (const c of this.cars) {
      if (c.driver === 'npc' && Math.hypot(c.pos.x - px, c.pos.z - pz) > 230) c.remove();
    }
    this.cars = this.cars.filter((c) => !c.dead);
    const npcCount = this.cars.filter((c) => c.driver === 'npc').length;
    if (npcCount < this.target) this.spawnNpc(px, pz);
    for (const car of this.cars) {
      if (car.driver === 'npc') this.steerNpc(car, dt);
      else if (car.driver === null) car.drive(dt, 0, 0, true);
      car.sync(dt);
    }
  }

  steerNpc(car, dt) {
    const ai = car.ai, g = this.game, r = ai.route;
    const fx = -Math.sin(car.yaw), fz = -Math.cos(car.yaw);
    let block = 99;
    const look = 14 + car.spec.L / 2;
    const check = (x, z, w) => {
      const rx = x - car.pos.x, rz = z - car.pos.z;
      const ahead = rx * fx + rz * fz;
      const side = Math.abs(rx * -fz + rz * fx);
      if (ahead > 0 && ahead < look && side < w) block = Math.min(block, ahead);
    };
    for (const o of g.allCars()) if (o !== car) check(o.pos.x, o.pos.z, 1.9 + o.spec.W / 2);
    // 人は自分の車線上にいるときだけ止まる(歩道の人には反応しない)
    check(g.player.pos.x, g.player.pos.z, car.spec.W / 2 + 0.35);
    for (const p of g.peds.list) if (p.state !== 'down') check(p.pos.x, p.pos.z, car.spec.W / 2 + 0.25);
    let target = ai.cruise;
    // 信号: 交差点の手前で赤・黄なら停止線で止まる
    const jn = r.nextJunction();
    if (jn && jn.node.deg >= 3 && jn.node.maxW >= 10 && jn.dist < 40) {
      const st = signalState(jn.node.i, jn.yaw, g.time);
      if (st !== 'G' && !(st === 'Y' && jn.dist < 6)) target = Math.min(target, Math.max(0, (jn.dist - 1.5) * 0.8));
    }
    if (r.remaining() < 40) r.chooseNext();
    const curv = this.curvatureAhead(r);
    target = Math.min(target, 5 + 16 / (1 + curv * 25));
    // 前の車に塞がれて長く動けないときは、少しの間だけすり抜ける(交差点での膠着を防ぐ)
    if (ai.ghost > 0) { ai.ghost -= dt; block = 99; }
    if (block < look) {
      target = Math.min(target, Math.max(0, (block - car.spec.L / 2 - 4) * 1.1));
      ai.blockedT = (ai.blockedT ?? 0) + (ai.speed < 0.5 ? dt : 0);
      if (ai.blockedT > 7 && car.pos.distanceTo(g.player.pos) > 12) { ai.ghost = 3; ai.blockedT = 0; }
    } else ai.blockedT = 0;
    if (ai.wait > 0) { ai.wait -= dt; target = 0; }
    ai.speed = damp(ai.speed, target, target < ai.speed ? 5 : 1.5, dt);
    car.braking = target < ai.speed - 0.5 || ai.speed < 0.3;
    if (block < 8 && ai.speed < 0.5) {
      ai.honk -= dt;
      if (ai.honk < 0) { ai.honk = rand(3, 6); if (car.pos.distanceTo(g.player.pos) < 35) g.audio.horn(car.pos); }
    }
    r.advance(ai.speed * dt);
    const [x, z, yaw] = r.pos();
    const dyaw = wrapAngle(yaw - car.yaw);
    car.pos.set(x, 0, z);
    car.yaw += dyaw * Math.min(1, dt * 10);
    car.steer = clamp(dyaw * 4, -1, 1);
    car.speed = ai.speed;
    car.vel.set(-Math.sin(car.yaw) * ai.speed, -Math.cos(car.yaw) * ai.speed);
  }

  curvatureAhead(r) {
    const p = r.pts, i = r.i;
    let turn = 0;
    for (let k = i; k < Math.min(p.length - 2, i + 6); k++) {
      const a = Math.atan2(p[k + 1][0] - p[k][0], p[k + 1][1] - p[k][1]);
      const b = Math.atan2(p[k + 2][0] - p[k + 1][0], p[k + 2][1] - p[k + 1][1]);
      turn = Math.max(turn, Math.abs(wrapAngle(b - a)));
    }
    return turn;
  }
}

// ---------------------------------------------------------------- パトカー(最短経路で追跡)
export class Police {
  constructor(game) {
    this.game = game;
    this.cars = [];
    this.light = new THREE.PointLight(0xff0000, 0, 30, 1.6);
    game.scene.add(this.light);
    this.distT = 0;
  }

  wantedCount(stars) { return [0, 1, 2, 3, 5, 6][stars]; }

  spawn() {
    const g = this.game, roads = g.city.roads;
    const p = g.player.pos;
    for (let tries = 0; tries < 40; tries++) {
      const n = pick(roads.nodes);
      const d = Math.hypot(n.x - p.x, n.z - p.z);
      if (d < 90 || d > 200) continue;
      const car = new Car(g, 'police', n.x, n.z, Math.atan2(n.x - p.x, n.z - p.z));
      car.driver = 'police';
      car.ai = { wp: null, stuck: 0, reverse: 0 };
      this.cars.push(car);
      g.traffic.cars.push(car);
      return;
    }
  }

  update(dt) {
    const g = this.game;
    const stars = g.wanted.stars;
    this.cars = this.cars.filter((c) => !c.dead);
    const active = this.cars.filter((c) => c.driver === 'police');
    if (active.length < this.wantedCount(stars)) {
      this.spawnTimer = (this.spawnTimer ?? 0) - dt;
      if (this.spawnTimer <= 0) { this.spawn(); this.spawnTimer = 4; }
    }
    // プレイヤー最寄りの交差点までの距離表を定期的に更新
    this.distT -= dt;
    if (stars > 0 && this.distT <= 0) {
      this.distT = 1.5;
      const tgt = g.player.inCar ? g.player.inCar.pos : g.player.pos;
      this.dist = g.city.roads.distancesTo(g.city.roads.nearestNode(tgt.x, tgt.z));
    }
    let nearest = null, nd = 1e9;
    for (const car of active) {
      const d = car.pos.distanceTo(g.player.pos);
      if (stars === 0) {
        car.siren = false;
        car.drive(dt, 0.4, 0, false);
        if (d > 160) car.remove();
        continue;
      }
      car.siren = true;
      this.chase(car, dt, d);
      if (d < nd) { nd = d; nearest = car; }
    }
    if (nearest && nd < 60) {
      const ph = Math.floor(performance.now() / 166) % 2;
      this.light.color.set(ph ? 0xff1010 : 0x1030ff);
      this.light.intensity = 60;
      this.light.position.copy(nearest.pos).y = 2.2;
    } else this.light.intensity = 0;
    this.nearest = nearest ? nd : 1e9;
  }

  chase(car, dt) {
    const g = this.game, ai = car.ai, roads = g.city.roads;
    const tgt = g.player.inCar ? g.player.inCar.pos : g.player.pos;
    const col = g.city.colliders;
    const dx = tgt.x - car.pos.x, dz = tgt.z - car.pos.z;
    const d = Math.hypot(dx, dz);
    const clear = d < 70 && col.raycast(car.pos.x, car.pos.z, dx / d, dz / d, d) >= d - 0.5;
    let aim;
    if (clear || d < 14) { aim = tgt; ai.wp = null; }
    else {
      if (!ai.wp || Math.hypot(ai.wp.x - car.pos.x, ai.wp.z - car.pos.z) < 10) {
        // 近くの交差点から、プレイヤーに一番近づく隣の交差点へ
        const here = roads.nearestNode(car.pos.x, car.pos.z);
        const atNode = Math.hypot(here.x - car.pos.x, here.z - car.pos.z) < 14;
        if (!atNode || !this.dist) ai.wp = here;
        else {
          let best = null, bd = 1e9;
          for (const o of here.out) { const v = this.dist[o.to] + o.e.len; if (v < bd) { bd = v; best = roads.nodes[o.to]; } }
          ai.wp = best ?? here;
        }
      }
      aim = ai.wp;
    }
    const want = Math.atan2(-(aim.x - car.pos.x), -(aim.z - car.pos.z));
    const diff = wrapAngle(want - car.yaw);
    let steer = clamp(diff * 2.2, -1, 1);
    let throttle = 1;
    if (Math.abs(diff) > 1.2 && car.speed > 12) throttle = -0.6;
    const stopDist = 7 + (car.speed * car.speed) / 30;
    if (!g.player.inCar && d < stopDist) throttle = car.speed > 1 ? -1 : 0;
    if (ai.reverse > 0) { ai.reverse -= dt; throttle = -1; steer = -steer; }
    else if (Math.abs(car.speed) < 1.2 && throttle > 0.5) {
      ai.stuck += dt;
      if (ai.stuck > 1.2) { ai.reverse = 1.1; ai.stuck = 0; }
    } else ai.stuck = 0;
    car.drive(dt, throttle, steer, Math.abs(diff) > 1.6 && car.speed > 8);
  }
}

// 車同士・車と人の当たり判定
export function resolveCarCollisions(game, dt) {
  const cars = game.allCars();
  for (let a = 0; a < cars.length; a++) {
    const A = cars[a];
    for (let b = a + 1; b < cars.length; b++) {
      const B = cars[b];
      if (Math.abs(A.pos.x - B.pos.x) > 7 || Math.abs(A.pos.z - B.pos.z) > 7) continue;
      for (const ca of A.circles()) for (const cb of B.circles()) {
        const dx = cb.x - ca.x, dz = cb.z - ca.z;
        const d = Math.hypot(dx, dz), min = A.radius + B.radius;
        if (d >= min || d < 1e-5) continue;
        const nx = dx / d, nz = dz / d, pen = min - d;
        const aK = A.driver === 'npc', bK = B.driver === 'npc';
        const wa = aK ? 0.15 : 0.5, wb = bK ? 0.15 : 0.5;
        const sum = wa + wb;
        A.pos.x -= nx * pen * (wa / sum); A.pos.z -= nz * pen * (wa / sum);
        B.pos.x += nx * pen * (wb / sum); B.pos.z += nz * pen * (wb / sum);
        const rv = (B.vel.x - A.vel.x) * nx + (B.vel.y - A.vel.y) * nz;
        if (rv < 0) {
          const j = -rv * 0.8;
          if (!aK) { A.vel.x -= nx * j * (wa / sum) * 2; A.vel.y -= nz * j * (wa / sum) * 2; }
          if (!bK) { B.vel.x += nx * j * (wb / sum) * 2; B.vel.y += nz * j * (wb / sum) * 2; }
          A.impact(-rv * 0.7); B.impact(-rv * 0.7);
          for (const [me, other] of [[A, B], [B, A]]) {
            if (me.driver === 'npc' && -rv > 3) { me.ai.wait = rand(2, 4); me.ai.speed = 0; }
            if (me.driver === 'police' && other.driver === 'player') game.hurtPlayer(-rv * 0.8, 'ram');
            if (other.driver === 'player' && me.driver === 'police' && -rv > 5) game.wanted.crime(3, 'パトカーに体当たり');
          }
        }
      }
    }
  }
}

export { makeGlowSprite };
