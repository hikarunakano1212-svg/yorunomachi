// HUD(DOM) とミニマップ
import { yen } from './util.js';

const $ = (id) => document.getElementById(id);
let K = 1, M = 450; // 地図のピクセル/メートル、原点のずれ(m)

export class Hud {
  constructor(game) {
    this.game = game;
    this.el = {
      hud: $('hud'), money: $('money'), wanted: $('wanted'), clock: $('clock'), mission: $('mission'),
      hp: $('hp'), carhp: $('carhp'), speed: $('speed').querySelector('b'), ammo: $('ammo'), prompt: $('prompt'),
      subtitle: $('subtitle'), toasts: $('toasts'), area: $('area'), radio: $('radio'), arrest: $('arrest'),
      arrestBar: $('arrest').querySelector('i'), vignette: $('vignette'), big: $('bigtext'), hit: $('hitmarker'), cross: $('crosshair'),
    };
    this.mini = $('minimap').getContext('2d');
    this.bigmap = $('bigmap').getContext('2d');
    this.base = this.drawBase();
    this.shownMoney = 0;
    this.subT = 0;
    this.lastStars = -1;
  }

  drawBase() {
    // 実データから作った八重洲の地図画像
    const img = this.game.city.minimapImg;
    M = this.game.city.half;
    K = img.width / (M * 2);
    return img;
  }

  // ---------- 表示更新
  update(dt) {
    const g = this.game, p = g.player;
    // 所持金(カウントアップ演出)
    const diff = g.money - this.shownMoney;
    this.shownMoney += Math.abs(diff) < 50 ? diff : diff * Math.min(1, dt * 6);
    this.el.money.innerHTML = `${yen(this.shownMoney)}<span class="goal">返済まで あと ${yen(Math.max(0, g.goal - g.money))}</span>`;
    // 手配度
    const st = g.wanted.stars;
    if (st !== this.lastStars || g.wanted.hidden !== this.lastHidden) {
      this.el.wanted.innerHTML = [1, 2, 3, 4, 5].map((n) => `<span class="s ${n <= st ? 'on' : ''}">★</span>`).join('');
      this.lastStars = st; this.lastHidden = g.wanted.hidden;
      this.el.wanted.classList.toggle('blink', g.wanted.hidden && st > 0);
    }
    // 時計
    const mins = g.clockMinutes();
    const hh = Math.floor(mins / 60) % 24, mm = Math.floor(mins % 60);
    this.el.clock.innerHTML = `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}<small>${g.mode === 'day' ? '期限の19時まで' : '夜明けまで'} ${Math.max(0, Math.ceil((g.endMinutes - mins) / 60 * 10) / 10)}時間</small>`;
    this.el.hp.style.transform = `scaleX(${p.hp / 100})`;
    this.el.hp.style.background = p.hp < 30 ? '#ff4d6a' : '';
    if (p.inCar) {
      this.el.carhp.style.transform = `scaleX(${p.inCar.hp / 100})`;
      this.el.speed.textContent = Math.round(Math.abs(p.inCar.speed) * 3.6);
    }
    this.el.ammo.innerHTML = p.reloadT > 0 ? '<small>リロード中…</small>' : `<b>${p.ammo}</b><small> / ${p.reserve}</small>`;
    this.el.cross.classList.toggle('car', !!p.inCar);
    this.el.area.textContent = g.areaName();
    // 字幕
    if (this.subT > 0) { this.subT -= dt; if (this.subT <= 0) this.el.subtitle.classList.remove('on'); }
    // 逮捕ゲージ
    this.el.arrest.classList.toggle('on', g.arrest > 0.01);
    this.el.arrestBar.style.width = `${g.arrest * 100}%`;
    this.el.vignette.style.opacity = Math.max(g.hurtFlash, p.hp < 30 ? 0.35 + Math.sin(performance.now() / 200) * 0.15 : 0);
    this.drawMini();
  }

  toWorldMap(x, z) { return [(x + M) * K, (z + M) * K]; }

  drawMini() {
    const g = this.game, p = g.player;
    const ctx = this.mini, S = 220, R = S / 2;
    const scale = 1.1 / K; // 画面上で 1m = 1.1px
    ctx.save();
    ctx.clearRect(0, 0, S, S);
    ctx.beginPath(); ctx.arc(R, R, R, 0, Math.PI * 2); ctx.clip();
    ctx.fillStyle = '#07080d'; ctx.fillRect(0, 0, S, S);
    ctx.translate(R, R);
    ctx.rotate(p.yaw);
    ctx.scale(scale, scale);
    const [mx, my] = this.toWorldMap(p.pos.x, p.pos.z);
    ctx.drawImage(this.base, -mx, -my);
    ctx.restore();
    // マーカー(回転後の位置)
    const put = (x, z, color, size, shape = 'dot', clampEdge = false) => {
      let dx = (x - p.pos.x), dz = (z - p.pos.z);
      const c = Math.cos(p.yaw), s = Math.sin(p.yaw);
      let sx = dx * c - dz * s, sy = dx * s + dz * c;
      const d = Math.hypot(sx, sy);
      if (d > R - 10) { if (!clampEdge) return; sx *= (R - 10) / d; sy *= (R - 10) / d; }
      ctx.fillStyle = color;
      ctx.beginPath();
      if (shape === 'square') ctx.rect(R + sx - size, R + sy - size, size * 2, size * 2);
      else ctx.arc(R + sx, R + sy, size, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = 'rgba(0,0,0,.7)'; ctx.lineWidth = 1.5; ctx.stroke();
    };
    for (const m of g.missions.markers()) put(m.x, m.z, m.color, m.size ?? 5, m.shape, m.always);
    const blink = Math.floor(performance.now() / 250) % 2;
    for (const c of g.police.cars) if (c.driver === 'police') put(c.pos.x, c.pos.z, blink ? '#ff3b4d' : '#3b6bff', 4, 'dot');
    // 自分(矢印)
    ctx.save(); ctx.translate(R, R);
    ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.moveTo(0, -8); ctx.lineTo(6, 7); ctx.lineTo(0, 3); ctx.lineTo(-6, 7); ctx.closePath(); ctx.fill();
    ctx.restore();
    // 方角
    ctx.save(); ctx.translate(R, R); ctx.rotate(p.yaw);
    ctx.fillStyle = '#ff2e88'; ctx.font = '700 12px "Zen Kaku Gothic New"'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText('北', 0, -R + 10);
    ctx.restore();
    // 手配中は縁を赤青に
    if (g.wanted.stars > 0) {
      ctx.strokeStyle = blink ? 'rgba(255,50,70,.8)' : 'rgba(60,100,255,.8)'; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.arc(R, R, R - 2, 0, Math.PI * 2); ctx.stroke();
    }
  }

  drawBigMap() {
    const g = this.game, ctx = this.bigmap, S = 560;
    const k = S / this.base.width;
    ctx.clearRect(0, 0, S, S);
    ctx.drawImage(this.base, 0, 0, S, S);
    const put = (x, z, color, r) => {
      const [mx, my] = this.toWorldMap(x, z);
      ctx.fillStyle = color; ctx.beginPath(); ctx.arc(mx * k, my * k, r, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = '#000'; ctx.stroke();
    };
    for (const m of g.missions.markers()) put(m.x, m.z, m.color, 6);
    const [px, py] = this.toWorldMap(g.player.pos.x, g.player.pos.z);
    ctx.save(); ctx.translate(px * k, py * k); ctx.rotate(-g.player.yaw);
    ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.moveTo(0, -9); ctx.lineTo(7, 8); ctx.lineTo(0, 4); ctx.lineTo(-7, 8); ctx.closePath(); ctx.fill();
    ctx.restore();
  }

  // ---------- 通知
  toast(msg, kind = '') {
    const d = document.createElement('div');
    d.className = `toast ${kind}`; d.textContent = msg;
    this.el.toasts.appendChild(d);
    setTimeout(() => d.remove(), 3300);
    while (this.el.toasts.children.length > 5) this.el.toasts.firstChild.remove();
  }
  say(who, text, dur = 4) {
    this.el.subtitle.innerHTML = `<span class="who">${who}</span>${text}`;
    this.el.subtitle.classList.add('on');
    this.subT = dur;
  }
  mission(title, body, timer = null) {
    const m = this.el.mission;
    if (!title) { m.classList.add('off'); return; }
    m.classList.remove('off');
    m.querySelector('.m-title').textContent = title;
    m.querySelector('.m-body').innerHTML = body;
    const t = m.querySelector('.m-timer');
    if (timer == null) t.textContent = '';
    else { t.textContent = `${Math.floor(timer / 60)}:${String(Math.floor(timer % 60)).padStart(2, '0')}`; t.classList.toggle('low', timer < 15); }
  }
  prompt(html) {
    if (html === this.lastPrompt) return;
    this.lastPrompt = html;
    this.el.prompt.innerHTML = html || '';
    this.el.prompt.classList.toggle('on', !!html);
  }
  big(main, sub = '', cls = '', dur = 3) {
    const b = this.el.big;
    b.className = cls;
    b.querySelector('.main').textContent = main;
    b.querySelector('.sub').textContent = sub;
    // アニメーションを再生し直す
    const mm = b.querySelector('.main'); mm.style.animation = 'none'; void mm.offsetWidth; mm.style.animation = '';
    clearTimeout(this.bigTimer);
    if (dur) this.bigTimer = setTimeout(() => b.classList.add('hidden'), dur * 1000);
  }
  hitmark() { const h = this.el.hit; h.classList.remove('on'); void h.offsetWidth; h.classList.add('on'); }
  radio(name) {
    this.el.radio.textContent = name ? `♪ ${name}` : '';
  }
  flashMoney() { const m = this.el.money; m.classList.remove('flash'); void m.offsetWidth; m.classList.add('flash'); }
}
