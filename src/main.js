// 夜ノ街 — エントリポイント。レンダラ・ポストエフェクト・ゲームループ・状態遷移
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { GTAOPass } from 'three/addons/postprocessing/GTAOPass.js';
import { SMAAPass } from 'three/addons/postprocessing/SMAAPass.js';
import { loadAssets } from './assets.js';
import { buildYaesu, loadMapData } from './yaesu.js';
const groundY = () => 0;
import { Traffic, Police, resolveCarCollisions } from './vehicles.js';
import { Peds } from './peds.js';
import { Player } from './player.js';
import { Hud } from './hud.js';
import { Audio } from './audio.js';
import { Input } from './input.js';
import { Wanted } from './wanted.js';
import { Missions } from './missions.js';
import { Particles, Tracers, makeRain, makeSky } from './fx.js';
import { makeGlowSprite } from './textures.js';
import { clamp, damp, rand, yen } from './util.js';

const params = new URLSearchParams(location.search);
const lowQ0 = params.get('q') === 'low';
const canvas = document.getElementById('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' });
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.9;
// 画面の解像度: 高画質(既定)は端末の解像度そのまま(最大2倍)。軽量モードだけ下げる
const MAX_PR = params.get('q') === 'low' ? 0.85 : Math.min(devicePixelRatio, 2);
const MIN_PR = params.get('q') === 'low' ? 0.7 : Math.min(devicePixelRatio, 1);
let pixelRatio = MAX_PR;
renderer.setPixelRatio(pixelRatio);
renderer.setSize(innerWidth, innerHeight);
renderer.info.autoReset = false;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;

const scene = new THREE.Scene();
scene.fog = new THREE.FogExp2(0x070812, 0.0095);
scene.background = new THREE.Color(0x05060b);
const camera = new THREE.PerspectiveCamera(74, innerWidth / innerHeight, 0.05, 1200);
camera.layers.enable(1);
scene.add(camera);
scene.add(new THREE.HemisphereLight(0x3d4a80, 0x1a1016, 0.8));
// 月明かり(影を落とす)。プレイヤーの周囲だけを高解像度のシャドウマップで覆う
const moon = new THREE.DirectionalLight(0x9aa8ff, 0.8);
moon.castShadow = true;
moon.shadow.mapSize.set(lowQ0 ? 2048 : 4096, lowQ0 ? 2048 : 4096);
Object.assign(moon.shadow.camera, { left: -90, right: 90, top: 90, bottom: -90, near: 1, far: 600 });
moon.shadow.bias = -0.0004; moon.shadow.normalBias = 0.04;
scene.add(moon, moon.target);
// 爆発の閃光用(常駐させて明るさだけ変える)
const flashLight = new THREE.PointLight(0xff8a3a, 0, 40, 1.5);
scene.add(flashLight);
const sky = makeSky();
scene.add(sky);
const rain = makeRain(params.get('q') === 'low' ? 4000 : 9000);
scene.add(rain);

// ---------------------------------------------------------------- ポストエフェクト
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
// 非数(NaN)・無限大の画素を消す(ブルームで画面全体に広がって真っ黒になるのを防ぐ)
composer.addPass(new ShaderPass({
  uniforms: { tDiffuse: { value: null } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
  fragmentShader: 'uniform sampler2D tDiffuse; varying vec2 vUv; void main(){ vec4 c = texture2D(tDiffuse, vUv); if (any(isnan(c)) || any(isinf(c))) c = vec4(0.0, 0.0, 0.0, 1.0); gl_FragColor = min(c, vec4(64.0)); }',
}));
// 物の接地部分・隅の陰り(GTAO)。軽量モードでは省く
const lowQ = params.get('q') === 'low';
const gtao = lowQ ? null : new GTAOPass(scene, camera, innerWidth, innerHeight);
if (gtao) {
  gtao.updateGtaoMaterial({ radius: 0.8, distanceExponent: 1.5, thickness: 1.5, scale: 1.1, samples: 16 });
  gtao.updatePdMaterial({ lumaPhi: 10, depthPhi: 2, normalPhi: 3, radius: 10, rings: 3, samples: 24 });
  gtao.blendIntensity = 0.7;

  composer.addPass(gtao);
}
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth / 2, innerHeight / 2), 0.55, 0.45, 0.92);
composer.addPass(bloom);
const finalPass = new ShaderPass({
  uniforms: { tDiffuse: { value: null }, uTime: { value: 0 }, uHurt: { value: 0 }, uSpeed: { value: 0 }, uFade: { value: 0 }, uGrain: { value: 0 } },
  vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
  fragmentShader: /* glsl */`
    uniform sampler2D tDiffuse; uniform float uTime, uHurt, uSpeed, uFade, uGrain; varying vec2 vUv;
    float hash(vec2 p){ return fract(sin(dot(p, vec2(12.9898,78.233)) + uTime) * 43758.5453); }
    void main(){
      vec2 c = vUv - 0.5;
      float r = length(c);
      // 色収差(ダメージ時・高速時に強く)
      float ca = uHurt * 0.01 + uSpeed * 0.002;
      vec3 col;
      col.r = texture2D(tDiffuse, vUv + c * ca).r;
      col.g = texture2D(tDiffuse, vUv).g;
      col.b = texture2D(tDiffuse, vUv - c * ca).b;
      // 周辺減光
      col *= smoothstep(0.95, 0.25, r * (1.0 + uSpeed * 0.3));
      // 夜の色味(シャドウを青緑、ハイライトを暖色へ)
      float l = dot(col, vec3(0.299, 0.587, 0.114));
      col = mix(col, col * vec3(0.85, 0.98, 1.15), smoothstep(0.4, 0.0, l) * 0.5);
      col += (hash(vUv * 800.0) - 0.5) * uGrain;
      col = mix(col, vec3(l) * vec3(1.0, 0.4, 0.4), uHurt * 0.4);
      col *= 1.0 - uFade;
      gl_FragColor = vec4(col, 1.0);
    }`,
});
composer.addPass(finalPass);
composer.addPass(new OutputPass());
// 輪郭のギザギザ取り(SMAA)
if (!lowQ) composer.addPass(new SMAAPass(innerWidth * pixelRatio, innerHeight * pixelRatio));

// ---------------------------------------------------------------- ゲーム
const game = {
  scene, camera, renderer, flashLight,
  money: 0, goal: 3000000, time: 0,
  startMinutes: 23 * 60, endMinutes: 29 * 60, // 23:00 → 翌5:00
  timeScale: 12,  // 現実1秒 = ゲーム内12秒(約30分で夜明け)
  state: 'loading',
  arrest: 0, hurtFlash: 0, shakeAmt: 0,
  groundY,
  glowTex: makeGlowSprite(),
  audio: new Audio(),
  input: new Input(canvas),
  clockMinutes() { return this.startMinutes + this.time * this.timeScale / 60; },
  areaName() { return this.areaCache ?? '八重洲'; },
  allCars() { return this.traffic.cars; },
  shake(a) { this.shakeAmt = Math.max(this.shakeAmt, a); },
  addMoney(v, fx = true) {
    this.money = Math.max(0, this.money + v);
    if (fx && v > 0) { this.audio.cash(); this.hud.toast(`+${yen(v)}`, 'money'); this.hud.flashMoney(); }
  },
};

const loadingEl = document.getElementById('loading');
const startBtn = document.getElementById('start');
startBtn.disabled = true;

async function init() {
  // 看板の文字を正しいフォントで描くため、先にフォントを読み込む
  try {
    await Promise.race([
      Promise.all(['900 40px "Zen Kaku Gothic New"', '400 40px "Dela Gothic One"', '400 40px "Yuji Syuku"'].map((f) => document.fonts.load(f, '夜ノ街'))),
      new Promise((r) => setTimeout(r, 2500)),
    ]);
  } catch { /* フォントが無くても続行 */ }
  game.assets = await loadAssets('assets/models/', (p) => { loadingEl.textContent = `アセット読み込み中… ${Math.round(p * 100)}%`; });
  loadingEl.textContent = '街を生成中…';
  await new Promise((r) => setTimeout(r, 30));
  const mapData = await loadMapData();
  game.city = await buildYaesu(game, mapData);
  // 街の景色を環境マップに焼く(ガラス・車体・濡れた路面への映り込み)
  {
    const rt = new THREE.WebGLCubeRenderTarget(256, { type: THREE.HalfFloatType });
    const cube = new THREE.CubeCamera(1, 1500, rt);
    cube.position.set(40, 30, -20);
    scene.add(cube);
    cube.update(renderer, scene);
    const pm = new THREE.PMREMGenerator(renderer);
    scene.environment = pm.fromCubemap(rt.texture).texture;
    scene.environmentIntensity = 0.55;
    scene.remove(cube);
  }

  game.sparks = new Particles(scene, game.glowTex, true, 1200);
  game.smoke = new Particles(scene, game.glowTex, false, 600);
  game.tracers = new Tracers(scene);
  game.hud = new Hud(game);
  setupPlaces();
  game.startPos = game.places.start;
  applyMode(['day', 'sun'].includes(params.get('mode')) ? params.get('mode') : 'night');
  document.querySelectorAll('.mode button').forEach((x) => x.classList.toggle('on', x.dataset.mode === game.mode));
  game.player = new Player(game, game.startPos.x, game.startPos.z);
  game.traffic = new Traffic(game, params.get('q') === 'low' ? 16 : 24);
  game.police = new Police(game);
  game.peds = new Peds(game, params.get('q') === 'low' ? 20 : 32);
  game.wanted = new Wanted(game);
  game.missions = new Missions(game);
  // 最初に街を埋める
  for (let i = 0; i < 80; i++) { game.traffic.spawnNpc(game.player.pos.x, game.player.pos.z, 15, 170); game.peds.update(0.016); }
  game.state = 'title';
  loadingEl.textContent = '';
  startBtn.disabled = false;
  if (params.has('autostart')) startGame();
}

// ---------------------------------------------------------------- 実在の地名に合わせた重要地点
function freeSpot(x, z) {
  const col = game.city.colliders;
  for (let r = 0; r < 40; r += 1.5) for (let a = 0; a < 6.28; a += 0.5) {
    const px = x + Math.cos(a) * r, pz = z + Math.sin(a) * r;
    if (!col.inside(px, pz, 1.2)) return { x: px, z: pz };
  }
  return { x, z };
}
function roadside(x, z) {
  // 最寄りの車道の路肩
  const r = game.city.roads.nearestEdge(x, z);
  const a = r.e.pts[r.i], b = r.e.pts[r.i + 1];
  const l = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
  const mx = (a[0] + b[0]) / 2, mz = (a[1] + b[1]) / 2;
  const nx = (b[1] - a[1]) / l, nz = -(b[0] - a[0]) / l;
  const s = (x - mx) * nx + (z - mz) * nz > 0 ? 1 : -1;
  return { x: mx + nx * s * (r.e.w / 2 - 1.2), z: mz + nz * s * (r.e.w / 2 - 1.2), yaw: Math.atan2(-(b[0] - a[0]), -(b[1] - a[1])) };
}
function setupPlaces() {
  const c = game.city;
  const lm = (name) => c.landmarks.find((l) => l.n.includes(name));
  const roads = c.roads;
  // 八重洲通り × 外堀通り の交差点(東京駅八重洲口前)
  const startNode = roads.nodes.find((n) => {
    const names = new Set(roads.edges.filter((e) => e.a === n.i || e.b === n.i).map((e) => e.name));
    return names.has('八重洲通り') && names.has('外堀通り');
  }) ?? roads.nearestNode(0, 0);
  const mid = lm('東京ミッドタウン八重洲')?.c ?? [9, 81];
  const sp = freeSpot(startNode.x + 14, startNode.z + 10);
  const kb = freeSpot(-45, -40);
  const nearFront = (x, z, style) => c.shopFronts.filter((s) => !style || s.b.s === style)
    .reduce((b, s) => (Math.hypot(s.x - x, s.z - z) < Math.hypot(b.x - x, b.z - z) ? s : b));
  const yaesuDori = roads.edges.filter((e) => e.name === '八重洲通り').sort((a, b) => b.len - a.len)[0];
  game.places = {
    start: { ...sp, yaw: Math.atan2(-(mid[0] - sp.x), -(mid[1] - sp.z)) },
    hospital: freeSpot(260, 240),
    kaneda: nearFront(185, -70, 'mixed'),
    ramen: nearFront(240, 170, 'mixed'),
    chop: roadside(360, 360),
    titlePath: yaesuDori ? yaesuDori.pts : [[0, 0], [100, 0]],
  };
  // 交番(八重洲口)
  const k = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(6, 4.2, 5), new THREE.MeshStandardMaterial({ color: 0xd8d2c4, roughness: 0.8 }));
  body.position.y = 2.1; body.castShadow = body.receiveShadow = true; k.add(body);
  const roof = new THREE.Mesh(new THREE.BoxGeometry(6.6, 0.4, 5.6), new THREE.MeshStandardMaterial({ color: 0x2e3033 }));
  roof.position.y = 4.4; k.add(roof);
  const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.3, 16, 8), new THREE.MeshBasicMaterial({ color: new THREE.Color(5, 0.2, 0.15) }));
  lamp.position.set(0, 3.8, -2.6); k.add(lamp);
  const cv = document.createElement('canvas'); cv.width = 512; cv.height = 128;
  const g2 = cv.getContext('2d');
  g2.fillStyle = '#1d3f8f'; g2.fillRect(0, 0, 512, 128);
  g2.fillStyle = '#fff'; g2.font = '900 72px "Zen Kaku Gothic New", sans-serif'; g2.textAlign = 'center'; g2.textBaseline = 'middle';
  g2.fillText('八重洲口交番', 256, 66);
  const tx = new THREE.CanvasTexture(cv); tx.colorSpace = THREE.SRGBColorSpace;
  const sign = new THREE.Mesh(new THREE.PlaneGeometry(3.2, 0.8), new THREE.MeshBasicMaterial({ map: tx, color: new THREE.Color(1.5, 1.5, 1.5) }));
  sign.position.set(0, 3.2, -2.52); sign.rotation.y = Math.PI; k.add(sign);
  k.position.set(kb.x, 0, kb.z);
  scene.add(k);
  c.colliders.addBox(kb.x, kb.z, 3, 2.5, 0, 'building');
  game.places.koban = freeSpot(kb.x, kb.z - 4);
}

// ---------------------------------------------------------------- 射撃判定
game.shoot = (o, d, who) => {
  const maxT = 160;
  let best = { t: maxT, kind: null };
  // 建物
  const hl = Math.hypot(d.x, d.z);
  if (hl > 1e-4) {
    const th = game.city.colliders.raycast(o.x, o.z, d.x / hl, d.z / hl, maxT * hl);
    const t = th / hl;
    if (t < best.t) best = { t, kind: 'wall' };
  }
  if (d.y < -1e-4) { const t = (0 - o.y) / d.y; if (t < best.t) best = { t, kind: 'ground' }; }
  // 歩行者(縦長の円柱として判定)
  for (const p of game.peds.list) {
    if (p.state === 'down') continue;
    const rx = p.pos.x - o.x, rz = p.pos.z - o.z;
    const t = (rx * d.x + rz * d.z) / (hl * hl);
    if (t < 0 || t > best.t) continue;
    const cx = o.x + d.x * t - p.pos.x, cz = o.z + d.z * t - p.pos.z;
    const y = o.y + d.y * t - p.pos.y;
    if (cx * cx + cz * cz < 0.1 && y > 0 && y < p.height) best = { t, kind: 'ped', ped: p, head: y > p.height - 0.3 };
  }
  // 車(向きのある箱)
  for (const c of game.allCars()) {
    const cos = Math.cos(-c.yaw), sin = Math.sin(-c.yaw);
    const lx0 = o.x - c.pos.x, lz0 = o.z - c.pos.z;
    const ox = lx0 * cos + lz0 * sin, oz = -lx0 * sin + lz0 * cos, oy = o.y - c.pos.y - 0.75;
    const dx = d.x * cos + d.z * sin, dz = -d.x * sin + d.z * cos, dy = d.y;
    const hx = c.spec.W / 2, hy = 0.75, hz = c.spec.L / 2;
    let t0 = 0, t1 = best.t;
    for (const [oo, dd, h] of [[ox, dx, hx], [oy, dy, hy], [oz, dz, hz]]) {
      if (Math.abs(dd) < 1e-8) { if (Math.abs(oo) > h) { t0 = 1; t1 = 0; } continue; }
      let a = (-h - oo) / dd, b = (h - oo) / dd;
      if (a > b) [a, b] = [b, a];
      t0 = Math.max(t0, a); t1 = Math.min(t1, b);
    }
    if (t0 <= t1 && t0 < best.t && c !== game.player.inCar) best = { t: t0, kind: 'car', car: c };
  }
  const hit = o.clone().addScaledVector(d, best.t);
  const muzzle = game.player.gunHolder.localToWorld(new THREE.Vector3(0, 0.06, -0.22));
  game.tracers.add(muzzle, hit);
  if (best.kind) {
    const n = best.kind === 'ped' ? [0.6, 0.1, 0.1] : [1, 0.75, 0.4];
    for (let i = 0; i < 10; i++) game.sparks.emit({ x: hit.x, y: hit.y, z: hit.z, vx: rand(-3, 3) - d.x * 2, vy: rand(0, 4), vz: rand(-3, 3) - d.z * 2, life: rand(0.15, 0.4), s0: 0.08, s1: 0.02, c: n, grav: 9 });
    game.smoke.emit({ x: hit.x, y: hit.y, z: hit.z, vy: 0.4, life: 0.8, s0: 0.2, s1: 0.9, c: [0.5, 0.5, 0.52], a: 0.35 });
  }
  // 銃声で周囲がパニック
  game.peds.scareAll(o.x, o.z, 45, 1);
  const witnesses = game.peds.list.some((p) => p.state !== 'down' && p.pos.distanceTo(o) < 35) || game.police.nearest < 60;
  if (best.kind === 'ped') {
    const p = best.ped;
    p.hp -= best.head ? 100 : 40;
    game.hud.hitmark(); game.audio.hitMarker();
    if (p.hp <= 0 || best.head) { p.knock(d.x, d.z, 2); game.onPedHit(p, 'gun'); }
    else p.scare(o.x, o.z, 1);
  } else if (best.kind === 'car') {
    const c = best.car;
    c.hp = Math.max(0, c.hp - 8);
    game.hud.hitmark(); game.audio.hitMarker();
    if (c.driver === 'police') game.wanted.crime(3, 'パトカーへの発砲');
    if (c.driver === 'npc' && c.ai) { c.ai.cruise = 16; c.ai.wait = 0; }
  }
  if (witnesses && game.wanted.stars < 1) game.wanted.crime(1, '発砲の通報');
};

game.onPedHit = (p, how) => {
  game.wanted.crime(2, how === 'car' ? 'ひき逃げ' : '通行人への暴行');
  game.peds.scareAll(p.pos.x, p.pos.z, 30, 1);
};
game.onEnterCar = () => {
  const st = game.audio.stations[game.audio.station];
  game.hud.radio(st.style ? st.name : '');
};
game.hurtPlayer = (amt, cause) => {
  if (game.state !== 'play') return;
  const p = game.player;
  if (p.inCar && cause !== 'fire') { p.inCar.hp = Math.max(0, p.inCar.hp - amt * 0.5); amt *= 0.25; }
  p.hp -= amt;
  game.hurtFlash = Math.min(1, game.hurtFlash + amt / 30);
  game.shake(Math.min(0.6, amt / 25));
  if (p.hp <= 0) wasted();
};

function respawn(x, z, label, sub, cls) {
  const p = game.player;
  game.state = 'dead';
  game.hud.big(label, sub, cls, 0);
  document.getElementById('bigtext').classList.remove('hidden');
  game.missions.abort();
  setTimeout(() => {
    if (p.inCar) p.exitCar();
    p.pos.set(x, groundY(x, z), z); p.hp = 100; p.vx = p.vz = 0;
    game.wanted.clear();
    for (const c of game.police.cars) c.remove();
    game.arrest = 0;
    document.getElementById('bigtext').classList.add('hidden');
    game.state = 'play';
  }, 3500);
}
function wasted() {
  const fee = Math.round(game.money * 0.1);
  game.money -= fee;
  game.audio.jingle(false);
  const s = game.places.hospital;
  respawn(s.x, s.z, '病院送り', `治療費 −${yen(fee)}　…救急病院の前で目を覚ました`, 'red');
  game.time += 20 * 60 / game.timeScale; // 20分経過
}
function busted() {
  const fee = Math.round(game.money * 0.15);
  game.money -= fee;
  game.player.ammo = 12; game.player.reserve = 24;
  game.audio.jingle(false);
  const k = game.places.koban;
  respawn(k.x, k.z, '逮捕', `罰金 −${yen(fee)}　…八重洲口の交番で説教を食らった`, 'red');
  game.time += 30 * 60 / game.timeScale;
}
game.win = () => {
  game.state = 'end';
  game.addMoney(-game.goal, false);
  game.audio.jingle(true);
  const t = game.clockMinutes();
  const hh = Math.floor(t / 60) % 24, mm = Math.floor(t % 60);
  endScreen('完済', `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}　三百万円を返し切った。手元に ${yen(game.money)}`, 'gold');
  const line = document.createElement('div');
  line.className = 'sub'; line.style.cssText = 'font-family:"Zen Kaku Gothic New";letter-spacing:.1em;margin-top:18px;font-size:17px';
  line.textContent = '金田「…本当に揃えやがった。お前、うちで働かねえか？」';
  document.getElementById('bigtext').insertBefore(line, document.getElementById('bigtext').lastChild);
};
function dawnFail() {
  game.state = 'end';
  game.audio.jingle(false);
  endScreen('夜明け', `返済できず…所持金 ${yen(game.money)} / ${yen(game.goal)}`, 'red');
}
function endScreen(main, sub, cls) {
  game.input.unlock();
  game.input.enabled = false;
  document.getElementById('hud').classList.add('hidden');
  game.hud.big(main, sub, cls, 0);
  const b = document.getElementById('bigtext');
  b.classList.remove('hidden');
  const again = document.createElement('div');
  again.className = 'sub'; again.style.marginTop = '30px'; again.style.fontSize = '14px'; again.style.pointerEvents = 'auto'; again.style.cursor = 'pointer';
  again.textContent = '― クリックでもう一度 ―';
  b.appendChild(again);
  b.style.pointerEvents = 'auto';
  b.onclick = () => location.reload();
}

// ---------------------------------------------------------------- 昼(曇り雨) / 夜 の切り替え
const hemi = scene.children.find((o) => o.isHemisphereLight);
function applyMode(mode) {
  game.mode = mode;
  const sun = mode === 'sun';
  const day = mode !== 'night';
  const L = game.city.look;
  scene.fog.color.set(sun ? 0xbcd0e6 : day ? 0x8f98a2 : 0x070812);
  scene.fog.density = sun ? 0.00065 : day ? 0.0042 : 0.0095;
  hemi.color.set(sun ? 0x9fc3ee : day ? 0xc4ccd6 : 0x3d4a80); hemi.groundColor.set(day ? 0x4d4a47 : 0x1a1016);
  hemi.intensity = sun ? 1.3 : day ? 1.9 : 0.8;
  moon.color.set(sun ? 0xfff2de : day ? 0xeef1f5 : 0x9aa8ff); moon.intensity = sun ? 3.6 : day ? 1.4 : 0.8;
  game.sunMode = sun;
  finalPass.uniforms.uGrain.value = 0; // ざらつきは足さない(画面が汚く見えるため)
  renderer.toneMapping = day ? THREE.AgXToneMapping : THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = sun ? 1.0 : day ? 1.15 : 0.9;
  sky.material.uniforms.uDay.value = day ? 1 : 0;
  sky.material.uniforms.uSun.value = sun ? 1 : 0;
  for (const m of L.facadeMats) m.emissiveIntensity = m.userData.baseEmissive * (day ? 0.1 : 1);
  L.storeMat.emissiveIntensity = day ? 0.3 : 0.9;
  L.vSignMat.color.setScalar(day ? 0.85 : 1.8); L.hSignMat.color.setScalar(day ? 0.8 : 1.3);
  L.groundU.uLightAmt.value = day ? 0 : 1;
  L.groundU.uWetness.value = sun ? 0.04 : day ? 0.55 : 1;
  L.groundU.uRain.value = sun ? 0 : 1;
  L.uDay.value = day ? 1 : 0;
  L.uSun.value = sun ? 1 : 0;
  L.aviMat.visible = !day;
  L.glow().visible = !day;
  L.glow().uniforms.uScale.value = day ? 0 : 600;
  for (const m of L.lampMats) m.emissiveIntensity = day ? 0.05 : 6;
  bloom.strength = day ? 0.18 : 0.55;
  rain.material.uniforms.uAmount.value = sun ? 0 : day ? 0.7 : 1;
  rain.visible = !sun;
  game.startMinutes = day ? 13 * 60 : 23 * 60;
  game.endMinutes = day ? 19 * 60 : 29 * 60;
  // 映り込み用の環境マップも撮り直す
  const rt = new THREE.WebGLCubeRenderTarget(256, { type: THREE.HalfFloatType });
  const cube = new THREE.CubeCamera(1, 1500, rt);
  cube.position.set(40, 30, -20);
  scene.add(cube); cube.update(renderer, scene); scene.remove(cube);
  const pm = new THREE.PMREMGenerator(renderer);
  scene.environment = pm.fromCubemap(rt.texture).texture;
  scene.environmentIntensity = sun ? 1.0 : day ? 0.9 : 0.55;
}
game.applyMode = applyMode;
document.querySelectorAll('.mode button').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('.mode button').forEach((x) => x.classList.toggle('on', x === b));
  if (game.city) applyMode(b.dataset.mode);
}));

// ---------------------------------------------------------------- 開始
function startGame() {
  if (game.state !== 'title') return;
  game.audio.start();
  document.getElementById('title').classList.add('fade');
  document.getElementById('hud').classList.remove('hidden');
  game.input.enabled = true;
  game.input.lock();
  game.state = 'play';
  const sp = game.startPos;
  game.player.pos.set(sp.x, groundY(sp.x, sp.z), sp.z);
  game.player.yaw = game.startPos.yaw; // 東京ミッドタウン八重洲の方を向く
  game.peds.populate(sp.x, sp.z, 90);
  setTimeout(() => game.hud.say('金田', 'おう、俺だ。…三百万、夜明けまでに耳を揃えて持ってこい。', 5), 800);
  setTimeout(() => !game.missions.active && game.hud.say('金田', '仕事なら回してやる。事務所（黄色い印）に来い。車が売りたきゃヤマ自動車（紫）だ。', 6), 6500);
  setTimeout(() => game.hud.toast('F：車に乗る　E：話す/買う　M：地図'), 1500);
}
startBtn.addEventListener('click', startGame);

function togglePause(force) {
  const pause = document.getElementById('pause');
  const on = force ?? game.state === 'play';
  if (on && game.state === 'play') {
    game.state = 'pause'; pause.classList.remove('hidden'); game.hud.drawBigMap(); game.input.unlock();
  } else if (!on && game.state === 'pause') {
    game.state = 'play'; pause.classList.add('hidden'); game.input.lock();
  }
}
document.getElementById('pause').addEventListener('click', () => togglePause(false));
addEventListener('keydown', (e) => {
  if (e.code === 'KeyM' || e.code === 'Escape' || e.code === 'KeyP') {
    if (game.state === 'play' && e.code !== 'Escape') togglePause(true);
    else if (game.state === 'pause') togglePause(false);
  }
});
document.addEventListener('pointerlockchange', () => {
  // Esc でロックが外れたら一時停止
  if (!document.pointerLockElement && game.state === 'play' && game.input.wasLocked) togglePause(true);
  game.input.wasLocked = !!document.pointerLockElement;
});

addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight); composer.setSize(innerWidth, innerHeight);
});

// ---------------------------------------------------------------- ループ
const clock = new THREE.Clock();
let fpsAcc = 0, fpsN = 0, titleT = 0;
let simT = 0;
function frame() {
  requestAnimationFrame(frame);
  const dt = Math.min(clock.getDelta(), 0.05);
  if (game.state === 'loading') return;
  simulate(dt);
  renderFrame(dt);
}

function simulate(dt) {
  simT += dt;
  const t = simT;
  const g = game, p = g.player, input = g.input;

  if (g.state === 'play' || g.state === 'dead' || g.state === 'title' || g.state === 'end') {
    if (g.state === 'play') {
      g.time += dt;
      p.update(dt, input);
      if (input.hit('KeyQ') && p.inCar) g.hud.radio(g.audio.nextStation().replace('ラジオ OFF', ''));
      g.wanted.update(dt);
      // 現在地の通り名(0.5秒ごと)
      g.areaT = (g.areaT ?? 0) - dt;
      if (g.areaT <= 0) {
        g.areaT = 0.5;
        const r = g.city.roads.nearestEdge(p.pos.x, p.pos.z);
        const dist = p.pos.x < -120 ? '丸の内' : p.pos.z < -260 ? '日本橋' : p.pos.z > 260 ? '京橋' : '八重洲';
        g.areaCache = r && r.d < r.e.w / 2 + 8 && r.e.name ? `${dist} · ${r.e.name}` : dist;
      }
      const pr = g.missions.update(dt, t);
      let prompt = pr;
      if (!prompt && !p.inCar) {
        const nearCar = g.allCars().some((c) => Math.hypot(c.pos.x - p.pos.x, c.pos.z - p.pos.z) < 3.6 + c.spec.L * 0.25 && !(c.driver === 'police' && Math.abs(c.speed) > 2));
        const nearVend = g.city.vendings.some((v) => Math.hypot(v.x - p.pos.x, v.z - p.pos.z) < 2);
        if (nearVend) prompt = '<kbd>E</kbd> 缶コーヒーを買う（¥150）';
        else if (nearCar) prompt = '<kbd>F</kbd> 車に乗る';
      }
      if (!prompt && p.inCar && p.inCar.hp <= 0) prompt = '車が燃えている！ <kbd>F</kbd> で降りろ！';
      g.hud.prompt(prompt);
      updateArrest(dt);
      if (g.clockMinutes() >= g.endMinutes) dawnFail();
    } else if (g.state === 'title') {
      // タイトル: 夜の大通りをゆっくり進むカメラ
      // タイトル: 八重洲通りをゆっくり進むカメラ
      titleT += dt;
      const path = g.places.titlePath;
      const L = path.length - 1;
      const f = (titleT * 0.06) % L, i0 = Math.floor(f), u = f - i0;
      const a = path[i0], b = path[Math.min(L, i0 + 1)];
      const x = a[0] + (b[0] - a[0]) * u, z = a[1] + (b[1] - a[1]) * u;
      camera.position.set(x, 3.4, z);
      camera.rotation.set(0.02, Math.atan2(-(b[0] - a[0]), -(b[1] - a[1])) + 0.2 + Math.sin(titleT * 0.1) * 0.08, 0, 'YXZ');
      p.pos.set(x, 0, z);
      if (!g.titlePop) { g.titlePop = true; g.peds.populate(x, z, 90); }
      p.gunHolder.visible = false;
    }
    g.traffic.update(dt);
    resolveCarCollisions(g, dt);
    g.police.update(dt);
    g.peds.update(dt);
    updateCarDamage(dt);
    g.sparks.update(dt); g.smoke.update(dt); g.tracers.update(dt);
    g.hud.update(dt);
    g.audio.update({ pos: p.pos, inCar: !!p.inCar, speed: p.inCar ? p.inCar.speed : 0, throttle: p.throttle ?? 0, policeDist: g.police.nearest ?? 1e9 });
  }
  input.endFrame();
}

function renderFrame(dt) {
  const g = game, p = g.player, t = simT;
  // カメラの揺れ
  g.shakeAmt = damp(g.shakeAmt, 0, 6, dt);
  if (g.shakeAmt > 0.001) {
    camera.position.x += (Math.random() - 0.5) * g.shakeAmt * 0.3;
    camera.position.y += (Math.random() - 0.5) * g.shakeAmt * 0.3;
  }
  g.hurtFlash = damp(g.hurtFlash, 0, 2.5, dt);
  // 夜明けが近づくと空が明るむ
  const dawn = g.mode === 'day' ? 0 : clamp((g.clockMinutes() - (g.endMinutes - 60)) / 60, 0, 1);
  sky.material.uniforms.uDawn.value = dawn;
  sky.material.uniforms.uTime.value = t;
  sky.position.copy(camera.position);
  rain.material.uniforms.uTime.value = t;
  rain.material.uniforms.uCam.value.copy(camera.position);
  g.city.update(t, dt);
  // 影を落とす範囲をプレイヤーに追従させる
  moon.target.position.set(camera.position.x, 0, camera.position.z);
  if (game.sunMode) moon.position.set(camera.position.x + 90, 120, camera.position.z + 70);
  else moon.position.set(camera.position.x - 60, 140, camera.position.z + 50);
  const fovScale = renderer.domElement.height / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2));
  g.city.setGlowScale(fovScale);
  g.sparks.mat.uniforms.uScale.value = g.smoke.mat.uniforms.uScale.value = fovScale;
  finalPass.uniforms.uTime.value = t;
  finalPass.uniforms.uHurt.value = g.hurtFlash;
  finalPass.uniforms.uSpeed.value = p.inCar ? Math.min(1, Math.abs(p.inCar.speed) / 40) : 0;
  renderer.info.reset();
  composer.render();
  // 重いときは解像度を自動で下げる
  fpsAcc += dt; fpsN++;
  if (fpsAcc > 2) {
    const fps = fpsN / fpsAcc; fpsAcc = 0; fpsN = 0;
    if (fps < 30 && gtao && gtao.enabled) { gtao.enabled = false; }
    else if (fps < 30 && pixelRatio > MIN_PR) { pixelRatio = Math.max(MIN_PR, pixelRatio - 0.15); renderer.setPixelRatio(pixelRatio); composer.setPixelRatio(pixelRatio); }
    else if (fps > 55 && pixelRatio < MAX_PR) { pixelRatio = Math.min(MAX_PR, pixelRatio + 0.1); renderer.setPixelRatio(pixelRatio); composer.setPixelRatio(pixelRatio); }
    game.fps = fps;
  }
}

// 逮捕: 徒歩で停車中のパトカーのそばにいるとゲージが溜まる。★3以上では撃たれる
function updateArrest(dt) {
  const g = game, p = g.player;
  let near = false;
  for (const c of g.police.cars) {
    if (c.driver !== 'police' || g.wanted.stars === 0) continue;
    const d = Math.hypot(c.pos.x - p.pos.x, c.pos.z - p.pos.z);
    if (!p.inCar && d < 7 && Math.abs(c.speed) < 2.5) near = true;
    if (p.inCar && d < 6 && Math.abs(p.inCar.speed) < 1 && Math.abs(c.speed) < 2) near = true;
    if (g.wanted.stars >= 3 && d < 32) {
      c.fireT = (c.fireT ?? rand(0.5, 1.5)) - dt;
      if (c.fireT <= 0) {
        c.fireT = rand(0.8, 1.6);
        const dx = p.pos.x - c.pos.x, dz = p.pos.z - c.pos.z;
        if (g.city.colliders.raycast(c.pos.x, c.pos.z, dx / d, dz / d, d) >= d - 1) {
          g.audio.gunshot();
          if (Math.random() < 0.55) g.hurtPlayer(rand(5, 10), 'gun');
          g.tracers.add(new THREE.Vector3(c.pos.x, 1.3, c.pos.z), new THREE.Vector3(p.pos.x + rand(-1, 1), 1.4, p.pos.z + rand(-1, 1)));
        }
      }
    }
  }
  g.arrest = near ? Math.min(1, g.arrest + dt / 2.5) : Math.max(0, g.arrest - dt * 0.6);
  if (g.arrest >= 1) busted();
}

// 車の損傷: 煙 → 炎上 → 爆発
function updateCarDamage(dt) {
  const g = game;
  for (const c of g.allCars()) {
    if (c.dead || c.wrecked) continue;
    if (c.hp < 45 && Math.random() < dt * (c.hp < 20 ? 30 : 10)) {
      const f = c.fwd;
      g.smoke.emit({ x: c.pos.x + f.x * c.spec.L * 0.4, y: 1.0, z: c.pos.z + f.z * c.spec.L * 0.4, vx: rand(-0.3, 0.3), vy: rand(1, 2), vz: rand(-0.3, 0.3), life: 2.2, s0: 0.5, s1: 2.6, c: c.hp < 20 ? [0.08, 0.08, 0.08] : [0.45, 0.45, 0.48], a: 0.5 });
    }
    if (c.hp <= 0) {
      c.burn = (c.burn ?? 5) - dt;
      if (Math.random() < dt * 40) g.sparks.emit({ x: c.pos.x + rand(-0.8, 0.8), y: 1 + rand(0, 0.5), z: c.pos.z + rand(-1, 1), vy: rand(1.5, 3), life: rand(0.4, 0.8), s0: 0.9, s1: 0.2, c: [1, 0.45, 0.12] });
      if (c.driver === 'police') { c.driver = null; g.peds.spawnAt(c.pos.x + 2, c.pos.z + 2).scare(c.pos.x, c.pos.z, 1); }
      if (c.driver === 'npc') { c.driver = null; c.ai = null; g.peds.spawnAt(c.pos.x + 2, c.pos.z + 2).scare(c.pos.x, c.pos.z, 1); }
      if (c.burn <= 0) explode(c);
    }
  }
}
function explode(c) {
  const g = game;
  c.wrecked = true;
  c.mat.userData.u.uPaint.value.set(0x0a0a0a);
  c.mat.color.set(0x333333);
  c.beam.visible = false;
  g.audio.crash(1); g.audio.gunshot();
  for (let i = 0; i < 60; i++) g.sparks.emit({ x: c.pos.x, y: 1, z: c.pos.z, vx: rand(-8, 8), vy: rand(2, 10), vz: rand(-8, 8), life: rand(0.4, 1.1), s0: 1.6, s1: 0.2, c: [1, 0.55, 0.2], grav: 6, drag: 1.5 });
  for (let i = 0; i < 20; i++) g.smoke.emit({ x: c.pos.x + rand(-1, 1), y: 1.5, z: c.pos.z + rand(-1, 1), vx: rand(-1, 1), vy: rand(1, 3), vz: rand(-1, 1), life: 4, s0: 1.5, s1: 6, c: [0.06, 0.06, 0.07], a: 0.7 });
  const flash = g.flashLight;
  flash.position.set(c.pos.x, 2, c.pos.z);
  let k = 1; const fade = () => { k *= 0.85; flash.intensity = 400 * k; if (k > 0.02) requestAnimationFrame(fade); else flash.intensity = 0; }; fade();
  const d = Math.hypot(g.player.pos.x - c.pos.x, g.player.pos.z - c.pos.z);
  g.shake(Math.max(0, 1 - d / 40));
  if (g.player.inCar === c) g.hurtPlayer(200, 'fire');
  else if (d < 7) g.hurtPlayer(70 * (1 - d / 7), 'fire');
  g.peds.scareAll(c.pos.x, c.pos.z, 50, 1);
  for (const p of g.peds.list) {
    const pd = Math.hypot(p.pos.x - c.pos.x, p.pos.z - c.pos.z);
    if (pd < 5) p.knock((p.pos.x - c.pos.x) / pd, (p.pos.z - c.pos.z) / pd, 6);
  }
  if (c.driver === 'player' && g.player.inCar === c) { /* hurtPlayer で処理 */ }
  c.driver = null;
}

// デバッグ・自動テスト用
window.__game = game;
game.passes = { bloom, gtao, finalPass };
// 描画せずにシミュレーションだけ進める(自動テスト用)
window.__step = (dt, n = 1) => { for (let i = 0; i < n; i++) simulate(dt); };
init().catch((e) => { loadingEl.textContent = '読み込みに失敗しました: ' + e.message; console.error(e); });
frame();
