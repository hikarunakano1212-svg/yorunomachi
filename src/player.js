// プレイヤー: 徒歩(一人称)、車の運転(運転席視点/後方視点)、拳銃
import * as THREE from 'three';
import { clamp, damp, rand, wrapAngle } from './util.js';
import { Car } from './vehicles.js';

const EYE = 1.62;

export class Player {
  constructor(game, x, z) {
    this.game = game;
    this.pos = new THREE.Vector3(x, 0, z);
    this.yaw = 0; this.pitch = 0;
    this.vy = 0; this.grounded = true;
    this.hp = 100;
    this.inCar = null;
    this.ammo = 12; this.reserve = 60;
    this.reloadT = 0; this.cool = 0;
    this.bob = 0; this.stepT = 0;
    this.recoil = 0;
    this.thirdPerson = false;
    this.camYawOff = 0; this.camPitchOff = 0;

    const cam = game.camera;
    // 一人称の拳銃
    this.gun = game.assets.clone('pistol');
    this.gun.traverse((o) => { if (o.isMesh) { o.material = o.material.clone(); o.material.depthTest = true; o.frustumCulled = false; } });
    this.gunHolder = new THREE.Group();
    this.gunHolder.add(this.gun);
    this.gun.scale.setScalar(0.85);
    // Poly Haven の実物スキャン風の拳銃があれば差し替える(照準器の高さと後端を元の拳銃に合わせる)
    if (game.assets.has('ph_pistol')) {
      const ph = game.assets.clone('ph_pistol');
      const old = this.gun.getObjectByName('GunMesh');
      if (old) old.visible = false;
      const box = new THREE.Box3().setFromObject(ph);
      ph.position.set(-(box.min.x + box.max.x) / 2, 0.079 - box.max.y, 0.08 - box.max.z);
      ph.traverse((o) => { if (o.isMesh) { o.frustumCulled = false; o.material = o.material.clone(); o.material.envMapIntensity = 1.4; } });
      this.gun.add(ph);
      // Mixamo の人物から切り出した右腕(スーツの袖・実写風の手)でグリップを握る
      if (game.assets.has('fp_arm')) {
        const arm = game.assets.clone('fp_arm');
        const oldHand = this.gun.getObjectByName('HandMesh');
        if (oldHand) oldHand.visible = false;
        const pb = new THREE.Box3().setFromObject(ph);
        const grip = new THREE.Vector3(0, pb.min.y + 0.035, pb.max.z - 0.035);
        arm.rotation.set(0.55, 0.0, -Math.PI / 2, 'ZXY');   // 手でグリップを後ろから包み、前腕は手前下へ伸ばす
        arm.updateMatrixWorld(true);
        const fist = new THREE.Vector3(0, -0.025, -0.075).applyEuler(arm.rotation);
        arm.position.copy(grip).sub(fist).add(new THREE.Vector3(-0.025, 0.035, 0.0)); // 指がグリップを包む位置へ微調整
        arm.traverse((o) => { if (o.isMesh) { o.frustumCulled = false; o.material = o.material.clone(); } });
        this.gun.add(arm);
        this.fpArm = arm;
      }
    }
    // 路面反射に映り込まないようレイヤー1へ
    this.gun.traverse((o) => o.layers.set(1));
    cam.add(this.gunHolder);
    // 素手(両腕)。1 キーで素手、2 キーで拳銃に持ち替える
    this.weapon = 'pistol';
    this.bareHolder = new THREE.Group();
    this.bareHolder.visible = false;
    cam.add(this.bareHolder);
    if (game.assets.has('fp_bare')) {
      const bare = game.assets.clone('fp_bare');
      bare.scale.setScalar(0.2);
      bare.traverse((o) => { if (o.isMesh) { o.frustumCulled = false; o.layers.set(1); o.material = o.material.clone(); o.material.envMapIntensity = 0.6; } });
      this.bareHolder.add(bare);
    }
    this.punchT = 0; this.punchSide = 1;
    this.flash = new THREE.PointLight(0xffc070, 0, 12, 2);
    cam.add(this.flash);
    // 手元を照らす弱いライト(街の光の照り返し)
    const fill = new THREE.PointLight(0xb0c0ff, 1.2, 1.2, 1);
    fill.position.set(0.1, 0.25, 0.1);
    cam.add(fill);
    const fm = new THREE.SpriteMaterial({ map: game.glowTex, color: 0xffcc66, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true });
    this.muzzle = new THREE.Sprite(fm); this.muzzle.scale.setScalar(0.35); this.muzzle.visible = false;
    this.gunHolder.add(this.muzzle);
    // 運転席(内装)
    this.cockpit = makeCockpit();
    // プレイヤーの車用ヘッドライト(実ライト)
    this.headlight = new THREE.SpotLight(0xfff0d8, 0, 70, 0.55, 0.5, 1.4);
    this.headlight.target = new THREE.Object3D();
    // 光源の数が変わるとシェーダーが再コンパイルされるので、最初から置いて明るさだけ変える
    game.scene.add(this.headlight, this.headlight.target);
  }

  get eye() { return new THREE.Vector3(this.pos.x, this.pos.y + EYE, this.pos.z); }

  update(dt, input) {
    const g = this.game;
    // 覗き込み中は視野に合わせて感度を下げる
    const [lx, ly] = input.consumeLook(this.inCar ? 1 : 1 - (this.aimT ?? 0) * 0.45);
    if (this.trans) { this.updateTrans(dt); return; }
    if (this.inCar) this.updateCar(dt, input, lx, ly);
    else this.updateFoot(dt, input, lx, ly);
    if (input.hit('KeyF')) this.inCar ? this.startExit() : this.tryEnter();
    if (input.hit('KeyE')) this.interact();
    this.hp = Math.min(100, this.hp + dt * 0.6);
  }

  // ---------------------------------------------------------------- 徒歩
  updateFoot(dt, input, lx, ly) {
    const g = this.game;
    this.yaw -= lx; this.pitch = clamp(this.pitch - ly, -1.45, 1.45);
    const f = (input.down('KeyW') || input.down('ArrowUp') ? 1 : 0) - (input.down('KeyS') || input.down('ArrowDown') ? 1 : 0);
    const s = (input.down('KeyD') ? 1 : 0) - (input.down('KeyA') ? 1 : 0);
    if (input.down('ArrowLeft')) this.yaw += dt * 2.2;
    if (input.down('ArrowRight')) this.yaw -= dt * 2.2;
    const run = input.down('ShiftLeft') || input.down('ShiftRight');
    const speed = run ? 7.2 : 3.8;
    const fx = -Math.sin(this.yaw), fz = -Math.cos(this.yaw);
    const rx = Math.cos(this.yaw), rz = -Math.sin(this.yaw);
    let mx = fx * f + rx * s, mz = fz * f + rz * s;
    const ml = Math.hypot(mx, mz);
    if (ml > 0) { mx /= ml; mz /= ml; }
    this.vx = damp(this.vx ?? 0, mx * speed, 12, dt);
    this.vz = damp(this.vz ?? 0, mz * speed, 12, dt);
    this.pos.x += this.vx * dt; this.pos.z += this.vz * dt;
    g.city.colliders.resolve(this.pos, 0.35);
    // 車との当たり
    for (const c of g.allCars()) {
      for (const cc of c.circles()) {
        const dx = this.pos.x - cc.x, dz = this.pos.z - cc.z, d = Math.hypot(dx, dz), m = c.radius + 0.35;
        if (d < m && d > 1e-4) {
          this.pos.x = cc.x + dx / d * m; this.pos.z = cc.z + dz / d * m;
          const hitSpeed = Math.abs(c.speed);
          if (hitSpeed > 6 && c.driver !== 'player') { g.hurtPlayer(hitSpeed * (c.driver === 'police' && g.wanted.stars < 4 ? 0.4 : 1.0), 'car'); this.vx += dx / d * hitSpeed; this.vz += dz / d * hitSpeed; }
        }
      }
    }
    // ジャンプと重力
    const gy = g.groundY(this.pos.x, this.pos.z);
    if (this.grounded && input.hit('Space')) { this.vy = 4.6; this.grounded = false; }
    this.vy -= 13 * dt;
    this.pos.y += this.vy * dt;
    if (this.pos.y <= gy) { this.pos.y = damp(this.pos.y, gy, 30, dt); if (this.vy < 0) this.vy = 0; this.grounded = true; if (this.pos.y < gy) this.pos.y = gy; }
    // 足音・視点の揺れ
    const moving = Math.hypot(this.vx, this.vz);
    this.bob += moving * dt * 1.9;
    this.stepT += moving * dt;
    if (this.stepT > (run ? 1.9 : 1.5) && this.grounded) { this.stepT = 0; g.audio.step(run); }
    const cam = g.camera;
    cam.position.set(this.pos.x, this.pos.y + EYE + Math.sin(this.bob * 2) * 0.035 * Math.min(1, moving / 4), this.pos.z);
    cam.rotation.set(this.pitch + this.recoil * 0.05, this.yaw, Math.sin(this.bob) * 0.006 * moving, 'YXZ');
    this.aimT = damp(this.aimT ?? 0, input.aim && this.reloadT <= 0 ? 1 : 0, 14, dt);
    cam.fov = damp(cam.fov, (run && moving > 5 ? 80 : 74) * (1 - this.aimT * 0.38), 10, dt);
    document.body.classList.toggle('aiming', this.aimT > 0.5);
    cam.updateProjectionMatrix();
    if (input.hit('Digit1') && this.weapon !== 'fists') { this.weapon = 'fists'; this.switchT = 0.3; }
    if (input.hit('Digit2') && this.weapon !== 'pistol') { this.weapon = 'pistol'; this.switchT = 0.3; }
    if (this.weapon === 'fists') this.updateFists(dt, input, moving);
    else { this.bareHolder.visible = false; this.updateGun(dt, input, moving); }
  }

  // 素手: 構えた両腕。左クリックで左右交互にパンチ
  updateFists(dt, input, moving) {
    const g = this.game;
    this.gunHolder.visible = false;
    this.bareHolder.visible = true;
    this.switchT = Math.max(0, (this.switchT ?? 0) - dt);
    this.punchT = Math.max(0, this.punchT - dt);
    if (input.clicked && this.punchT <= 0.05) {
      this.punchT = 0.38; this.punchSide *= -1; this.punchHit = false;
      g.audio.burst(0.12, 'bandpass', 900, 0.25, 0, 1.5);
    }
    // パンチの当たり判定(振り切る瞬間に 1.6m 以内・前方の人)
    const k = this.punchT > 0 ? Math.sin((1 - this.punchT / 0.38) * Math.PI) : 0;
    if (k > 0.8 && !this.punchHit) {
      this.punchHit = true;
      const fx = -Math.sin(this.yaw), fz = -Math.cos(this.yaw);
      for (const p of g.peds.list) {
        if (p.state === 'down') continue;
        const dx = p.pos.x - this.pos.x, dz = p.pos.z - this.pos.z, d = Math.hypot(dx, dz);
        if (d < 1.7 && (dx * fx + dz * fz) / (d || 1) > 0.6) {
          g.audio.thud(p.pos); g.hud.hitmark(); g.shake(0.15);
          p.hp -= 12;
          if (p.hp <= 0) { p.knock(fx, fz, 3); g.onPedHit(p, 'fist'); }
          else p.scare(this.pos.x, this.pos.z, 1);
          if (g.peds.list.some((q) => q !== p && q.state !== 'down' && q.pos.distanceTo(this.pos) < 30) && g.wanted.stars < 1) g.wanted.crime(1, '暴行の通報');
          break;
        }
      }
    }
    const sway = Math.sin(this.bob) * 0.01 * Math.min(1, moving / 4);
    const sw = this.switchT / 0.3;
    this.bareHolder.position.set(sway + this.punchSide * k * 0.05, -0.31 - Math.abs(Math.cos(this.bob)) * 0.01 - sw * 0.3 + k * 0.04, 0.02 - k * 0.22);
    this.bareHolder.rotation.set(0.12 + k * 0.1, this.punchSide * k * 0.15, 0);
  }

  updateGun(dt, input, moving) {
    const g = this.game;
    this.gunHolder.visible = true;
    this.cool -= dt;
    this.recoil = damp(this.recoil, 0, 12, dt);
    if (this.reloadT > 0) {
      this.reloadT -= dt;
      if (this.reloadT <= 0) { const n = Math.min(12 - this.ammo, this.reserve); this.ammo += n; this.reserve -= n; }
    }
    if (input.hit('KeyR') && this.ammo < 12 && this.reserve > 0 && this.reloadT <= 0) { this.reloadT = 1.3; g.audio.reload(); }
    if (input.clicked && this.cool <= 0 && this.reloadT <= 0) {
      if (this.ammo > 0) this.fire();
      else { g.audio.empty(); if (this.reserve > 0) { this.reloadT = 1.3; g.audio.reload(); } }
    }
    // 拳銃の位置(揺れ・反動・リロード時は下げる)
    const rl = this.reloadT > 0 ? Math.sin(Math.min(1, (1.3 - this.reloadT) / 1.3) * Math.PI) : 0;
    const k = this.aimT ?? 0;
    const sway = Math.sin(this.bob) * 0.012 * Math.min(1, moving / 4) * (1 - k * 0.8);
    // 腰だめ位置と照準位置(照星と照門の上端を画面中央に合わせる: 0.08 × 0.85)
    const hip = [0.075, -0.105 - Math.abs(Math.cos(this.bob)) * 0.008, -0.2];
    const ads = [0.003, -0.068, -0.27];
    this.gunHolder.position.set(hip[0] + (ads[0] - hip[0]) * k + sway, hip[1] + (ads[1] - hip[1]) * k - rl * 0.15, hip[2] + (ads[2] - hip[2]) * k + this.recoil * 0.05);
    // 腰だめでは銃口をやや内側・上に向け、スライドの後ろ側が見える構え
    this.gunHolder.rotation.set(this.recoil * (0.25 - k * 0.15) - rl * 0.6 + 0.03 * (1 - k), 0.14 * (1 - k), rl * 0.4 + 0.12 * (1 - k));
    this.muzzle.position.set(0, 0.06, -0.2);
    this.flash.intensity = damp(this.flash.intensity, 0, 30, dt);
    if (this.muzzleT > 0) { this.muzzleT -= dt; if (this.muzzleT <= 0) this.muzzle.visible = false; }
  }

  fire() {
    const g = this.game;
    this.ammo--; this.cool = 0.16; this.recoil = 1;
    const steady = 1 - (this.aimT ?? 0) * 0.6;
    this.pitch += 0.018 * steady; this.yaw += rand(-0.006, 0.006) * steady;
    g.audio.gunshot();
    this.flash.intensity = 25; this.muzzle.visible = true; this.muzzleT = 0.05;
    this.muzzle.material.rotation = rand(0, 6);
    g.shake(0.12);
    const cam = g.camera;
    const o = cam.getWorldPosition(new THREE.Vector3());
    const d = new THREE.Vector3(0, 0, -1).applyQuaternion(cam.getWorldQuaternion(new THREE.Quaternion()));
    g.shoot(o, d, 'player');
  }

  // ---------------------------------------------------------------- 運転
  updateCar(dt, input, lx, ly) {
    const g = this.game, car = this.inCar;
    this.gunHolder.visible = false;
    const thr = (input.down('KeyW') || input.down('ArrowUp') ? 1 : 0) - (input.down('KeyS') || input.down('ArrowDown') ? 1 : 0);
    const st = (input.down('KeyA') || input.down('ArrowLeft') ? 1 : 0) - (input.down('KeyD') || input.down('ArrowRight') ? 1 : 0);
    car.drive(dt, thr, st, input.down('Space'));
    this.throttle = thr;
    this.pos.set(car.pos.x, car.pos.y, car.pos.z);
    if (input.hit('KeyC')) this.thirdPerson = !this.thirdPerson;
    if (input.hit('KeyH')) g.audio.horn(car.pos);
    // マウスで車内を見回す(離すとゆっくり正面に戻る)
    this.camYawOff = clamp(this.camYawOff - lx, -2.2, 2.2);
    this.camPitchOff = clamp(this.camPitchOff - ly, -0.6, 0.5);
    if (Math.abs(lx) < 1e-4) this.camYawOff = damp(this.camYawOff, 0, 1.2, dt);
    if (Math.abs(ly) < 1e-4) this.camPitchOff = damp(this.camPitchOff, -0.06, 1.2, dt);
    const cam = g.camera;
    const speedAbs = Math.abs(car.speed);
    if (this.thirdPerson) {
      const back = new THREE.Vector3(Math.sin(car.yaw + this.camYawOff), 0, Math.cos(car.yaw + this.camYawOff));
      const want = car.pos.clone().addScaledVector(back, 7.5 + speedAbs * 0.06); want.y = 2.6;
      if (!this._tp) this._tp = want.clone();
      this._tp.lerp(want, 1 - Math.exp(-8 * dt));
      cam.position.copy(this._tp);
      cam.lookAt(car.pos.x, 1.2, car.pos.z);
      this.cockpit.visible = false;
    } else {
      const e = car.spec.eye;
      const local = new THREE.Vector3(e[0], e[1], e[2]);
      car.obj.updateMatrixWorld();
      cam.position.copy(local.applyMatrix4(car.obj.matrixWorld));
      cam.rotation.set(this.camPitchOff + (car.accelPitch ?? 0), car.yaw + this.camYawOff, car.obj.rotation.z * 0.6, 'YXZ');
      this.cockpit.visible = true;
      this.cockpit.userData.wheel.rotation.z = car.steer * 1.6;
      this.cockpit.userData.needle.rotation.z = 1.2 - Math.min(speedAbs * 3.6 / 180, 1) * 2.4;
    }
    cam.fov = damp(cam.fov, 72 + Math.min(speedAbs, 40) * 0.35, 4, dt);
    cam.updateProjectionMatrix();
    this.yaw = car.yaw; this.pitch = 0;
    // ヘッドライト
    const f = car.fwd.clone();
    this.headlight.position.copy(car.pos).addScaledVector(f, car.spec.L / 2).setY(0.9);
    this.headlight.target.position.copy(car.pos).addScaledVector(f, 25).setY(0);
    this.headlight.target.updateMatrixWorld();
    this.headlight.intensity = car.hp > 0 ? 180 : 0;
  }

  tryEnter() {
    const g = this.game;
    let best = null, bd = 3.6;
    for (const c of g.allCars()) {
      const d = Math.hypot(c.pos.x - this.pos.x, c.pos.z - this.pos.z);
      if (d < bd + c.spec.L * 0.25) { bd = d; best = c; }
    }
    if (!best) return;
    if (best.driver === 'police' && Math.abs(best.speed) > 2) return;
    this.startEnter(best);
  }

  // ---------------------------------------------------------------- 乗り降りのアニメーション
  // 車のローカル座標(右 = +X, 前 = -Z)をワールドへ
  carPoint(car, lx, ly, lz) {
    car.obj.updateMatrixWorld();
    return new THREE.Vector3(lx, ly, lz).applyMatrix4(car.obj.matrixWorld);
  }
  makeDoor(car) {
    const s = car.spec, e = s.eye;
    const H = Math.max(0.9, e[1] - 0.25), L = Math.min(1.25, s.L * 0.26);
    const door = new THREE.Group();
    const paint = new THREE.MeshPhysicalMaterial({ color: car.mat.userData.u.uPaint.value.clone(), roughness: 0.22, metalness: 0.45, clearcoat: 1, clearcoatRoughness: 0.06 });
    const lower = new THREE.Mesh(new THREE.BoxGeometry(0.06, H * 0.58, L), paint);
    lower.position.set(0, 0.35 + H * 0.29, L / 2);
    const glass = new THREE.Mesh(new THREE.BoxGeometry(0.03, H * 0.38, L * 0.92), new THREE.MeshPhysicalMaterial({ color: 0x1a2228, roughness: 0.05, metalness: 0.3, transparent: true, opacity: 0.55 }));
    glass.position.set(0, 0.35 + H * 0.58 + H * 0.19, L / 2 + 0.03);
    const inner = new THREE.Mesh(new THREE.BoxGeometry(0.02, H * 0.55, L * 0.95), new THREE.MeshStandardMaterial({ color: 0x1b1c1f, roughness: 0.8 }));
    inner.position.set(-0.04, 0.35 + H * 0.29, L / 2);
    const handle = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.03, 0.14), new THREE.MeshStandardMaterial({ color: 0xcccccc, metalness: 1, roughness: 0.2 }));
    handle.position.set(0.035, 0.35 + H * 0.5, L * 0.8);
    door.add(lower, glass, inner, handle);
    door.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.layers.set(1); } });
    door.position.set(s.W / 2 + 0.02, 0, e[2] - 0.75); // 前側の蝶番
    car.obj.add(door);
    return door;
  }
  startEnter(car) {
    const g = this.game;
    // 運転手が乗っていれば先に引きずり下ろす(車は止まる)
    if (car.driver === 'npc' || car.driver === 'police') this.dragOut(car);
    car.driver = null;
    const cam = g.camera;
    this.gunHolder.visible = false;
    this.trans = { type: 'enter', t: 0, dur: 1.5, car, p0: cam.position.clone(), yaw0: this.yaw, pitch0: this.pitch, door: this.makeDoor(car), sounds: {} };
  }
  startExit() {
    const g = this.game, car = this.inCar;
    if (Math.abs(car.speed) > 9) return; // 速すぎると降りられない
    const r = new THREE.Vector3(Math.cos(car.yaw), 0, -Math.sin(car.yaw));
    let out = null;
    for (const side of [1, -1]) {
      const p = { x: car.pos.x + r.x * 1.8 * side, z: car.pos.z + r.z * 1.8 * side };
      const q = { ...p };
      g.city.colliders.resolve(q, 0.35);
      if (Math.hypot(q.x - p.x, q.z - p.z) < 0.2 || side === -1) { out = q; break; }
    }
    car.driver = null;
    this.headlight.intensity = 0;
    document.body.classList.remove('driving');
    this.trans = { type: 'exit', t: 0, dur: 1.3, car, out, door: this.makeDoor(car), sounds: {} };
  }
  updateTrans(dt) {
    const g = this.game, T = this.trans, car = T.car, cam = g.camera, s = car.spec, e = s.eye;
    T.t += dt / T.dur;
    const t = Math.min(1, T.t);
    const sm = (a, b, x) => { const k = Math.min(1, Math.max(0, (x - a) / (b - a))); return k * k * (3 - 2 * k); };
    const lerpAng = (a, b, k) => a + wrapAngle(b - a) * k;
    car.drive(dt, 0, 0, true); car.sync(dt);
    const seat = this.carPoint(car, e[0], e[1], e[2]);
    const doorStand = this.carPoint(car, s.W / 2 + 0.85, 1.62, e[2] + 0.25);
    const faceIn = car.yaw + Math.PI / 2;   // 車の内側(左)を向く
    let pos, yaw, pitch, open;
    if (T.type === 'enter') {
      // 0-0.3: ドアの前へ / 0.15-0.45: ドアを開ける / 0.4-0.8: かがんで座席へ / 0.8-1: 前を向きドアを閉める
      const k1 = sm(0, 0.3, t), k2 = sm(0.38, 0.8, t);
      pos = T.p0.clone().lerp(doorStand, k1).lerp(seat, k2);
      pos.y -= Math.sin(k2 * Math.PI) * 0.35;                         // 頭をかがめる
      yaw = lerpAng(lerpAng(T.yaw0, faceIn, k1), car.yaw, sm(0.5, 0.9, t));
      pitch = T.pitch0 * (1 - k1) - 0.25 * Math.sin(k2 * Math.PI) - 0.06 * sm(0.8, 1, t);
      open = sm(0.12, 0.42, t) * (1 - sm(0.8, 0.97, t));
      if (t > 0.14 && !T.sounds.open) { T.sounds.open = 1; g.audio.door(); }
      if (t > 0.95 && !T.sounds.close) { T.sounds.close = 1; g.audio.door(); g.shake(0.08); }
    } else {
      const out = new THREE.Vector3(T.out.x, 1.62, T.out.z);
      // 0-0.25: ドアを開ける / 0.15-0.6: 体を外へ出す / 0.55-0.85: 立ち上がって離れる / 0.85-1: ドアを閉める
      const k1 = sm(0.15, 0.6, t), k2 = sm(0.55, 0.85, t);
      pos = seat.clone().lerp(doorStand, k1).lerp(out, k2);
      pos.y -= Math.sin(k1 * Math.PI) * 0.3;
      yaw = lerpAng(lerpAng(car.yaw, car.yaw - Math.PI / 2, k1), car.yaw, k2 * 0.7);
      pitch = -0.2 * Math.sin(k1 * Math.PI);
      open = sm(0.0, 0.25, t) * (1 - sm(0.82, 0.98, t));
      if (!T.sounds.open) { T.sounds.open = 1; g.audio.door(); }
      if (t > 0.6 && !T.sounds.out) { T.sounds.out = 1; car.obj.remove(this.cockpit); }
      if (t > 0.96 && !T.sounds.close) { T.sounds.close = 1; g.audio.door(); }
    }
    T.door.rotation.y = open * 1.15;
    cam.position.copy(pos);
    cam.rotation.set(pitch, yaw, 0, 'YXZ');
    this.yaw = yaw; this.pitch = pitch;
    this.pos.set(pos.x, 0, pos.z);
    if (t >= 1) {
      car.obj.remove(T.door);
      this.trans = null;
      if (T.type === 'enter') this.enterCar(car);
      else this.finishExit(car, T.out);
    }
  }
  dragOut(car) {
    const g = this.game, prev = car.driver;
    const r = new THREE.Vector3(Math.cos(car.yaw), 0, -Math.sin(car.yaw));
    const p = g.peds.spawnAt(car.pos.x + r.x * 1.6, car.pos.z + r.z * 1.6);
    if (prev === 'police') p.obj.traverse((m) => { if (m.isMesh && m.material.name === 'Jacket') m.material.color.set(0x1d2c55); });
    p.scare(this.pos.x, this.pos.z, 1);
    g.wanted.crime(prev === 'police' ? 3 : 1, prev === 'police' ? 'パトカー強奪' : '車両強盗');
    car.ai = null;
    car.vel.set(-Math.sin(car.yaw) * car.speed, -Math.cos(car.yaw) * car.speed);
  }

  enterCar(car) {
    const g = this.game;
    const prev = car.driver;
    if (prev === 'npc' || prev === 'police') {
      // 運転手を引きずり下ろす
      const r = new THREE.Vector3(Math.cos(car.yaw), 0, -Math.sin(car.yaw));
      const p = g.peds.spawnAt(car.pos.x + r.x * 1.6, car.pos.z + r.z * 1.6);
      if (prev === 'police') p.obj.traverse((m) => { if (m.isMesh && m.material.name === 'Jacket') m.material.color.set(0x1d2c55); });
      p.scare(this.pos.x, this.pos.z, 1);
      g.wanted.crime(prev === 'police' ? 3 : 1, prev === 'police' ? 'パトカー強奪' : '車両強盗');
      if (car.ai) car.ai = null;
      car.vel.set(-Math.sin(car.yaw) * car.speed, -Math.cos(car.yaw) * car.speed);
    }
    car.driver = 'player';
    car.siren = false;
    this.inCar = car;
    this.thirdPerson = false; this._tp = null;
    car.obj.add(this.cockpit);
    const e = car.spec.eye;
    this.cockpit.position.set(e[0], e[1], e[2]);
    this.cockpit.userData.fit(car.spec);
    g.audio.door();
    document.body.classList.add('driving');
    g.hud.toast(`${car.spec.name}に乗った`);
    g.onEnterCar(car);
  }

  finishExit(car, out) {
    const g = this.game;
    this.pos.set(out.x, 0, out.z);
    car.obj.remove(this.cockpit);
    this.inCar = null;
    this.vx = this.vz = 0;
    g.camera.fov = 74; g.camera.updateProjectionMatrix();
  }

  exitCar() {
    const g = this.game, car = this.inCar;
    if (Math.abs(car.speed) > 9) return; // 速すぎると降りられない
    const r = new THREE.Vector3(Math.cos(car.yaw), 0, -Math.sin(car.yaw));
    for (const side of [1, -1]) {
      const p = { x: car.pos.x + r.x * 1.8 * side, z: car.pos.z + r.z * 1.8 * side };
      const q = { ...p };
      g.city.colliders.resolve(q, 0.35);
      if (Math.hypot(q.x - p.x, q.z - p.z) < 0.2 || side === -1) { this.pos.set(q.x, g.groundY(q.x, q.z), q.z); break; }
    }
    car.driver = null;
    car.obj.remove(this.cockpit);
    this.headlight.intensity = 0;
    this.inCar = null;
    this.yaw = car.yaw; this.pitch = 0;
    g.audio.door();
    document.body.classList.remove('driving');
  }

  interact() {
    const g = this.game;
    if (this.inCar) return;
    for (const v of g.city.vendings) {
      if (Math.hypot(v.x - this.pos.x, v.z - this.pos.z) < 2) {
        if (g.money < 150) { g.hud.toast('お金が足りない', 'bad'); return; }
        g.addMoney(-150, false);
        this.hp = Math.min(100, this.hp + 30);
        g.audio.burst(0.3, 'lowpass', 500, 0.6); g.audio.tone(900, 0.1, 'sine', 0.1, 0.35);
        g.hud.toast('缶コーヒーを買った　体力 +30（−¥150）');
        return;
      }
    }
  }
}

// 車内の内装(ダッシュボード・ハンドル・Aピラー・天井)
function makeCockpit() {
  const g = new THREE.Group();
  const dark = new THREE.MeshStandardMaterial({ color: 0x1a1b1f, roughness: 0.7 });
  const trim = new THREE.MeshStandardMaterial({ color: 0x1c1d21, roughness: 0.6, metalness: 0.2 });
  const dash = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.22, 0.55), dark); g.add(dash);
  const hood = new THREE.Mesh(new THREE.BoxGeometry(1.5, 0.05, 0.5), trim); g.add(hood);
  const wheel = new THREE.Group();
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.17, 0.018, 8, 28), trim); wheel.add(ring);
  const spoke = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.03, 0.02), trim); wheel.add(spoke);
  const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.04, 12), trim); hub.rotation.x = Math.PI / 2; wheel.add(hub);
  g.add(wheel);
  // メーター
  const gauge = new THREE.Mesh(new THREE.CircleGeometry(0.075, 24), new THREE.MeshBasicMaterial({ color: new THREE.Color(0.05, 0.25, 0.35) }));
  g.add(gauge);
  const needle = new THREE.Mesh(new THREE.BoxGeometry(0.005, 0.065, 0.002), new THREE.MeshBasicMaterial({ color: new THREE.Color(3, 0.6, 0.3) }));
  needle.geometry.translate(0, 0.03, 0);
  gauge.add(needle); needle.position.z = 0.002;
  const roof = new THREE.Mesh(new THREE.PlaneGeometry(1.4, 1.1), new THREE.MeshStandardMaterial({ color: 0x2a2826, roughness: 1, side: THREE.DoubleSide }));
  roof.rotation.x = Math.PI / 2; g.add(roof);
  const pillarL = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.62, 0.07), dark); g.add(pillarL);
  const pillarR = pillarL.clone(); g.add(pillarR);
  const mirror = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.06, 0.02), trim); g.add(mirror);
  // お守り(吊り下げ)
  const omamori = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.05, 0.008), new THREE.MeshStandardMaterial({ color: 0xb01c2e }));
  g.add(omamori);
  g.userData = {
    wheel, needle,
    // 目の位置を原点として車種ごとに配置
    fit(spec) {
      const w = spec.W;
      dash.position.set(-0.38, -0.42, -0.62); dash.scale.x = w / 1.5;
      hood.position.set(-0.38, -0.31, -0.9); hood.scale.x = w / 1.5;
      wheel.position.set(0, -0.33, -0.42); wheel.rotation.x = -0.35;
      gauge.position.set(0, -0.3, -0.62); gauge.rotation.x = -0.3;
      roof.position.set(-0.38, spec.L < 4 ? 0.26 : 0.24, 0.35);
      pillarL.position.set(-0.38 - w / 2 + 0.08, -0.05, -0.72); pillarL.rotation.x = -0.6;
      pillarR.position.set(-0.38 + w / 2 - 0.08, -0.05, -0.72); pillarR.rotation.x = -0.6;
      mirror.position.set(-0.38, 0.12, -0.62);
      omamori.position.set(-0.38, 0.04, -0.6);
    },
  };
  g.traverse((o) => { if (o.isMesh) o.layers.set(1); });
  return g;
}
