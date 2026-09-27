// 手配度(★)の管理: 犯罪で上がり、警察の視界から消え続けると下がる
export class Wanted {
  constructor(game) { this.game = game; this.stars = 0; this.points = 0; this.lostT = 0; this.hidden = false; }

  crime(level, reason) {
    const before = this.stars;
    if (this.stars < level) this.stars = level;
    else {
      this.points += level;
      if (this.points >= 5 && this.stars < 5) { this.stars++; this.points = 0; }
    }
    this.lostT = 0;
    if (this.stars > before) {
      this.game.audio.starUp();
      this.game.hud.toast(`${'★'.repeat(this.stars)}　${reason}`, 'bad');
    }
  }

  clear() { this.stars = 0; this.points = 0; this.lostT = 0; }

  update(dt) {
    if (this.stars === 0) { this.hidden = false; return; }
    const g = this.game;
    const p = g.player.pos;
    let seen = false;
    for (const c of g.police.cars) {
      if (c.driver !== 'police') continue;
      const dx = p.x - c.pos.x, dz = p.z - c.pos.z, d = Math.hypot(dx, dz);
      if (d < 18) { seen = true; break; }
      if (d < 75 && g.city.colliders.raycast(c.pos.x, c.pos.z, dx / d, dz / d, d) >= d - 1) { seen = true; break; }
    }
    this.hidden = !seen;
    if (seen) this.lostT = 0;
    else {
      this.lostT += dt;
      if (this.lostT > 9 + this.stars * 3) {
        this.clear();
        g.hud.toast('警察を撒いた');
        g.audio.jingle(true);
      }
    }
  }
}
