// 仕事(ミッション)と解体屋。報酬で借金 300 万円の返済を目指す
import * as THREE from 'three';
import { rand, pick, yen } from './util.js';
import { Car } from './vehicles.js';

const COLORS = { job: '#ffb62e', target: '#ffe23a', chop: '#b36bff', pay: '#7dff9b', koban: '#4d8dff' };

// 光の柱(ワールド上の目印)
class Beacon {
  constructor(scene, x, z, color, r = 1.6) {
    const mat = new THREE.ShaderMaterial({
      uniforms: { uColor: { value: new THREE.Color(color).multiplyScalar(1.6) }, uTime: { value: 0 }, uFade: { value: 1 } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }',
      fragmentShader: `uniform vec3 uColor; uniform float uTime, uFade; varying vec2 vUv;
        void main(){ float a = pow(1.0 - vUv.y, 1.6) * (0.55 + 0.25 * sin(vUv.y * 20.0 - uTime * 4.0));
          gl_FragColor = vec4(uColor * a * uFade, 1.0); }`,
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide,
    });
    this.mesh = new THREE.Mesh(new THREE.CylinderGeometry(r, r, 4, 32, 1, true), mat);
    this.mesh.position.set(x, 2, z);
    this.mesh.layers.set(1);
    const ring = new THREE.Mesh(new THREE.RingGeometry(r - 0.12, r, 48), new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(3), transparent: true, opacity: 0.9, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = -1.93; ring.layers.set(1);
    this.mesh.add(ring);
    scene.add(this.mesh);
    this.scene = scene; this.x = x; this.z = z; this.r = r;
  }
  update(t, p) {
    this.mesh.material.uniforms.uTime.value = t;
    // 近づいたら柱を薄くする(中に入ると画面が染まらないように)
    const d = p ? Math.hypot(p.x - this.x, p.z - this.z) : 99;
    this.mesh.material.uniforms.uFade.value = Math.min(1, Math.max(0.12, (d - this.r) / 8));
  }
  remove() { this.scene.remove(this.mesh); }
}

export class Missions {
  constructor(game) {
    this.game = game;
    const pl = game.places;
    this.places = { kaneda: pl.kaneda, ramen: pl.ramen, chop: pl.chop };
    this.jobs = [
      { id: 'demae', giver: 'ramen', title: '出前', who: 'ラーメン龍 店主', desc: 'ラーメンを冷める前に、こぼさず届ける' },
      { id: 'shukin', giver: 'kaneda', title: '集金', who: '金田', desc: '滞納者3人から取り立てる' },
      { id: 'nigashi', giver: 'kaneda', title: '逃がし屋', who: '金田', desc: '車で客を拾い、警察を振り切って送り届ける' },
      { id: 'kaishu', giver: 'chop', title: '車両の回収', who: 'ヤマ自動車', desc: '指定の赤い軽自動車を盗んで持ってくる' },
    ];
    this.beacons = {};
    for (const k of ['kaneda', 'ramen']) this.beacons[k] = new Beacon(game.scene, this.places[k].x, this.places[k].z, COLORS.job);
    this.beacons.chop = new Beacon(game.scene, this.places.chop.x, this.places.chop.z, COLORS.chop, 3.2);
    this.active = null;
    this.targetBeacon = null;
    this.jobIndex = { kaneda: 0, ramen: 0, chop: 0 };
    this.done = 0;
  }

  markers() {
    const m = [];
    if (!this.active) {
      m.push({ x: this.places.kaneda.x, z: this.places.kaneda.z, color: this.game.money >= this.game.goal ? COLORS.pay : COLORS.job, size: 6, always: true });
      m.push({ x: this.places.ramen.x, z: this.places.ramen.z, color: COLORS.job, size: 6, always: true });
    }
    m.push({ x: this.places.chop.x, z: this.places.chop.z, color: COLORS.chop, size: 6, shape: 'square', always: true });
    const kb = this.game.places.koban;
    m.push({ x: kb.x, z: kb.z, color: COLORS.koban, size: 4 });
    if (this.active?.target) m.push({ x: this.active.target.x, z: this.active.target.z, color: COLORS.target, size: 7, always: true });
    return m;
  }

  setTarget(x, z, color = COLORS.target, r = 2.2) {
    if (this.targetBeacon) this.targetBeacon.remove();
    this.targetBeacon = x == null ? null : new Beacon(this.game.scene, x, z, color, r);
    if (this.active) this.active.target = x == null ? null : { x, z };
  }

  farFront(minD, maxD) {
    const p = this.game.player.pos;
    const list = this.game.city.shopFronts.filter((s) => {
      const d = Math.hypot(s.x - p.x, s.z - p.z);
      const H = this.game.city.half - 15;
      return d > minD && d < maxD && Math.abs(s.x) < H && Math.abs(s.z) < H;
    });
    return pick(list.length ? list : this.game.city.shopFronts);
  }

  update(dt, t) {
    const g = this.game, p = g.player;
    Object.values(this.beacons).forEach((b) => b.update(t, p.pos));
    if (this.targetBeacon) this.targetBeacon.update(t, p.pos);
    let prompt = null;
    const near = (pl, r) => Math.hypot(pl.x - p.pos.x, pl.z - p.pos.z) < r;

    // 仕事の受注 / 返済
    if (!this.active) {
      for (const giver of ['kaneda', 'ramen']) {
        if (!near(this.places[giver], 2.6)) continue;
        if (giver === 'kaneda' && g.money >= g.goal) {
          prompt = '<kbd>E</kbd> 金田に三百万円を返す';
          if (g.input.hit('KeyE')) g.win();
          break;
        }
        const jobs = this.jobs.filter((j) => j.giver === giver);
        const job = jobs[this.jobIndex[giver] % jobs.length];
        prompt = `<kbd>E</kbd> 仕事「${job.title}」を受ける ― ${job.desc}`;
        if (g.input.hit('KeyE')) { this.jobIndex[giver]++; this.start(job); }
      }
    }
    // 解体屋: 車を売る / 回収の仕事
    const inCar = p.inCar;
    if (near(this.places.chop, 4.5)) {
      if (inCar) {
        const price = Math.round(inCar.spec.price * Math.max(0.15, inCar.hp / 100) / 1000) * 1000;
        if (this.active?.id === 'kaishu' && inCar === this.active.car) prompt = null;
        else if (g.wanted.stars > 0) prompt = 'ヤマ「サツを連れてくんじゃねえ！撒いてから来い」';
        else {
          prompt = `<kbd>E</kbd> ${inCar.spec.name}を売る（${yen(price)}）`;
          if (g.input.hit('KeyE')) this.sellCar(inCar, price);
        }
      } else if (!this.active) {
        const job = this.jobs.find((j) => j.id === 'kaishu');
        prompt = `<kbd>E</kbd> 仕事「${job.title}」を受ける ― ${job.desc}`;
        if (g.input.hit('KeyE')) this.start(job);
      }
    }
    if (this.active) {
      const a = this.active;
      a.time -= dt;
      const r = a.update(dt);
      if (r === 'win') this.finish(true);
      else if (r === 'fail' || a.time <= 0) this.finish(false, r === 'fail' ? a.failReason : '時間切れ');
      else g.hud.mission(`仕事：${a.title}`, a.status(), a.time);
    }
    return prompt;
  }

  sellCar(car, price) {
    const g = this.game;
    g.player.exitCar();
    car.remove();
    g.addMoney(price);
    g.hud.say('ヤマ', pick(['いい車だ。バラせばいい値になる。', 'まいど。足がつかねえようにしとくよ。', '次もいいのを頼むぜ。']));
  }

  start(job) {
    const g = this.game;
    g.audio.pager();
    const a = this.active = { ...job, time: 120, target: null };
    if (job.id === 'demae') {
      const dest = this.farFront(170, 300);
      a.time = 85; a.soup = 100;
      this.setTarget(dest.x, dest.z);
      g.hud.say(job.who, '宇田川ビルの先生に醤油ラーメン。伸びたら金は出ねえ、急げ！', 5);
      a.status = () => `目的地へ配達する<br>スープ残量 <b style="color:${a.soup < 40 ? '#ff5a6e' : '#7dff9b'}">${Math.round(a.soup)}%</b>`;
      a.lastSpeed = 0;
      a.update = (dt) => {
        const car = g.player.inCar;
        // 急ブレーキ・衝突・急旋回でスープがこぼれる
        if (car) {
          const acc = Math.abs(car.speed - a.lastSpeed) / dt;
          a.lastSpeed = car.speed;
          const slosh = Math.max(0, acc - 14) * 0.02 + Math.max(0, (car.slip ?? 0) - 2.5) * 0.25 * dt * 10;
          a.soup -= slosh;
        }
        if (a.soup <= 0) { a.failReason = 'ラーメンが全部こぼれた'; return 'fail'; }
        if (this.reached(2.8)) {
          a.reward = Math.round((80000 + a.soup * 900 + a.time * 600) / 1000) * 1000;
          a.winLine = ['先生', a.soup > 70 ? 'おお、熱々じゃないか。チップをはずもう。' : '…ぬるいな。まあいい。'];
          return 'win';
        }
      };
    }
    if (job.id === 'shukin') {
      a.time = 170;
      a.stops = [this.farFront(60, 200), this.farFront(120, 260), this.farFront(150, 320)];
      a.idx = 0;
      this.setTarget(a.stops[0].x, a.stops[0].z);
      g.hud.say('金田', '返済が滞ってる連中がいる。三軒回って、きっちり回収してこい。', 5);
      a.status = () => `滞納者を回る（${a.idx} / 3）`;
      const lines = ['ま、待ってくれ！来月には…いや、払います！', 'こ、これで勘弁してください…', 'ちっ…持ってけよ！'];
      a.update = () => {
        if (this.reached(3)) {
          g.hud.say('滞納者', lines[a.idx], 3);
          g.audio.cash();
          a.idx++;
          if (a.idx >= 3) { a.reward = 300000; a.winLine = ['金田', 'ご苦労。お前の取り分だ。']; return 'win'; }
          this.setTarget(a.stops[a.idx].x, a.stops[a.idx].z);
        }
      };
    }
    if (job.id === 'nigashi') {
      a.time = 200; a.phase = 0;
      const pick1 = this.farFront(80, 200);
      this.setTarget(pick1.x, pick1.z, COLORS.target, 3);
      g.hud.say('金田', '取引先がヘマをした。車で拾って、遠くまで逃がしてやれ。車がなきゃ話にならねえぞ。', 5);
      a.status = () => (a.phase === 0 ? '車で客を迎えに行く（止まって乗せる）' : '警察を振り切り、目的地で降ろす');
      a.update = () => {
        const car = g.player.inCar;
        if (a.phase === 1 && !car) { a.failReason = '客を置き去りにした'; return 'fail'; }
        if (a.phase === 1 && car.hp <= 0) { a.failReason = '車が壊れた'; return 'fail'; }
        if (car && this.reached(4) && Math.abs(car.speed) < 2.5) {
          if (a.phase === 0) {
            a.phase = 1;
            g.audio.door();
            g.hud.say('客', '出してくれ！サツがすぐそこまで来てる！', 4);
            g.wanted.crime(3, '逃亡ほう助');
            const d = this.farFront(260, 420);
            this.setTarget(d.x, d.z, COLORS.target, 3);
            a.time = 150;
          } else if (g.wanted.stars > 0) {
            g.hud.prompt('警察を撒いてから降ろせ');
          } else {
            a.reward = 500000; a.winLine = ['客', '助かったよ。これは礼だ。金田さんによろしく。'];
            return 'win';
          }
        }
      };
    }
    if (job.id === 'kaishu') {
      a.time = 180;
      const spot = pick(g.city.parkedSpots.filter((s) => Math.hypot(s.x - g.player.pos.x, s.z - g.player.pos.z) > 150)) || g.city.parkedSpots[0];
      a.car = new Car(g, 'kei', spot.x, spot.z, spot.yaw, 0xd0101a);
      a.car.driver = null;
      g.traffic.cars.push(a.car);
      this.setTarget(spot.x, spot.z);
      g.hud.say('ヤマ', '赤い軽を一台持ってこい。傷は少ないほど高く買う。', 5);
      a.status = () => (g.player.inCar === a.car ? `解体屋へ運ぶ（車体 ${Math.round(a.car.hp)}%）` : '赤い軽自動車を盗む');
      a.update = () => {
        if (a.car.dead) { a.failReason = '車が失われた'; return 'fail'; }
        const inIt = g.player.inCar === a.car;
        if (inIt && !a.stolen) { a.stolen = true; g.wanted.crime(1, '車両窃盗の通報'); this.setTarget(this.places.chop.x, this.places.chop.z, COLORS.chop, 3.2); }
        if (!inIt && a.stolen) { this.setTarget(a.car.pos.x, a.car.pos.z); a.stolen = false; }
        if (inIt && Math.hypot(this.places.chop.x - a.car.pos.x, this.places.chop.z - a.car.pos.z) < 5 && Math.abs(a.car.speed) < 2.5) {
          if (g.wanted.stars > 0) { g.hud.prompt('ヤマ「サツを撒いてから来い！」'); return; }
          a.reward = Math.round((150000 + 250000 * a.car.hp / 100) / 1000) * 1000;
          a.winLine = ['ヤマ', a.car.hp > 70 ? '上物だ。色をつけておく。' : 'ボコボコじゃねえか…まあいい。'];
          g.player.exitCar(); a.car.remove();
          return 'win';
        }
      };
    }
    g.hud.toast(`仕事開始：${job.title}`);
  }

  reached(r) {
    const t = this.active.target, p = this.game.player.pos;
    return t && Math.hypot(t.x - p.x, t.z - p.z) < r;
  }

  finish(ok, reason) {
    const g = this.game, a = this.active;
    this.active = null;
    this.setTarget(null);
    g.hud.mission(null);
    if (ok) {
      this.done++;
      g.hud.big('完了', `報酬 ${yen(a.reward)}`, 'gold', 2.6);
      g.addMoney(a.reward);
      g.audio.jingle(true);
      if (a.winLine) setTimeout(() => g.hud.say(a.winLine[0], a.winLine[1], 4), 900);
    } else {
      g.hud.big('失敗', reason, 'red', 2.6);
      g.audio.jingle(false);
      if (a.car && !a.car.dead && g.player.inCar !== a.car) { /* 車は街に残す */ }
    }
  }

  abort() {
    if (this.active) this.finish(false, '仕事を失った');
  }
}
