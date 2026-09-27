// キーボード・マウス入力。ポインタロックが使えない環境(iframe 等)でも操作できるようにする
export class Input {
  constructor(canvas) {
    this.canvas = canvas;
    this.keys = new Set();
    this.pressed = new Set();   // このフレームで押されたキー
    this.dx = 0; this.dy = 0;
    this.mouse = false; this.mouseDown = false; this.clicked = false;
    this.locked = false;
    this.sens = 0.0022;
    addEventListener('keydown', (e) => {
      if (['Space', 'ArrowUp', 'ArrowDown', 'Tab'].includes(e.code)) e.preventDefault();
      if (!this.keys.has(e.code)) this.pressed.add(e.code);
      this.keys.add(e.code);
    });
    addEventListener('keyup', (e) => this.keys.delete(e.code));
    addEventListener('blur', () => this.keys.clear());
    addEventListener('mousemove', (e) => {
      if (!this.enabled) return;
      // ロック中は movementX、ロックできない環境でもドラッグなしで視点が回るように movementX を使う
      this.dx += e.movementX || 0; this.dy += e.movementY || 0;
    });
    addEventListener('mousedown', (e) => {
      if (!this.enabled) return;
      if (e.button === 0) { this.mouseDown = true; this.clicked = true; }
      if (e.button === 2) this.aim = true;
      if (!this.locked) this.lock();
    });
    addEventListener('mouseup', (e) => { if (e.button === 0) this.mouseDown = false; if (e.button === 2) this.aim = false; });
    document.addEventListener('pointerlockchange', () => { this.locked = document.pointerLockElement === this.canvas; });
    addEventListener('contextmenu', (e) => e.preventDefault());
  }
  lock() {
    try {
      const p = this.canvas.requestPointerLock?.();
      if (p && p.catch) p.catch(() => {});
    } catch { /* iframe 内などで拒否されても続行 */ }
  }
  unlock() { if (document.pointerLockElement) document.exitPointerLock(); }
  down(code) { return this.keys.has(code); }
  hit(code) { return this.pressed.has(code); }
  consumeLook(scale = 1) { const r = [this.dx * this.sens * scale, this.dy * this.sens * scale]; this.dx = this.dy = 0; return r; }
  endFrame() { this.pressed.clear(); this.clicked = false; }
}
