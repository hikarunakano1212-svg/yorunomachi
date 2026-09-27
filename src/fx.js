// エフェクト: パーティクル(火花・煙・炎)、弾道、雨、夜空
import * as THREE from 'three';
import { rand } from './util.js';

export class Particles {
  constructor(scene, tex, additive, max = 1500) {
    this.max = max;
    this.list = [];
    const g = new THREE.BufferGeometry();
    this.pos = new Float32Array(max * 3); this.col = new Float32Array(max * 4); this.size = new Float32Array(max);
    g.setAttribute('position', new THREE.BufferAttribute(this.pos, 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('color', new THREE.BufferAttribute(this.col, 4).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('size', new THREE.BufferAttribute(this.size, 1).setUsage(THREE.DynamicDrawUsage));
    this.mat = new THREE.ShaderMaterial({
      uniforms: { map: { value: tex }, uScale: { value: 600 } },
      vertexShader: `attribute float size; attribute vec4 color; varying vec4 vC; uniform float uScale;
        void main(){ vC = color; vec4 mv = modelViewMatrix * vec4(position,1.0); gl_PointSize = size * uScale / -mv.z; gl_Position = projectionMatrix * mv; }`,
      fragmentShader: additive
        ? `uniform sampler2D map; varying vec4 vC; void main(){ float a = texture2D(map, gl_PointCoord).a * vC.a; gl_FragColor = vec4(vC.rgb * a, 1.0); }`
        : `uniform sampler2D map; varying vec4 vC; void main(){ float a = texture2D(map, gl_PointCoord).a * vC.a; if (a < 0.01) discard; gl_FragColor = vec4(vC.rgb, a); }`,
      transparent: true, depthWrite: false, blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
    });
    this.points = new THREE.Points(g, this.mat);
    this.points.frustumCulled = false;
    this.points.layers.set(1);
    scene.add(this.points);
  }
  emit(o) {
    if (this.list.length >= this.max) this.list.shift();
    this.list.push({ x: o.x, y: o.y, z: o.z, vx: o.vx ?? 0, vy: o.vy ?? 0, vz: o.vz ?? 0, life: 0, max: o.life ?? 1,
      s0: o.s0 ?? 0.2, s1: o.s1 ?? 0.2, c: o.c ?? [1, 1, 1], a: o.a ?? 1, grav: o.grav ?? 0, drag: o.drag ?? 0 });
  }
  update(dt) {
    let n = 0;
    this.list = this.list.filter((p) => (p.life += dt) < p.max);
    for (const p of this.list) {
      p.vy -= p.grav * dt;
      const k = Math.exp(-p.drag * dt); p.vx *= k; p.vy *= k; p.vz *= k;
      p.x += p.vx * dt; p.y += p.vy * dt; p.z += p.vz * dt;
      if (p.y < 0.02 && p.grav > 0) { p.y = 0.02; p.vy *= -0.3; }
      const t = p.life / p.max;
      this.pos[n * 3] = p.x; this.pos[n * 3 + 1] = p.y; this.pos[n * 3 + 2] = p.z;
      this.col[n * 4] = p.c[0]; this.col[n * 4 + 1] = p.c[1]; this.col[n * 4 + 2] = p.c[2];
      this.col[n * 4 + 3] = p.a * (1 - t) * Math.min(1, t * 12);
      this.size[n] = p.s0 + (p.s1 - p.s0) * t;
      n++;
    }
    const g = this.points.geometry;
    g.setDrawRange(0, n);
    g.attributes.position.needsUpdate = g.attributes.color.needsUpdate = g.attributes.size.needsUpdate = true;
  }
}

// 弾道の光跡
export class Tracers {
  constructor(scene) {
    this.scene = scene; this.list = [];
    this.mat = new THREE.LineBasicMaterial({ color: new THREE.Color(3, 2.4, 1.4), transparent: true, blending: THREE.AdditiveBlending, depthWrite: false });
  }
  add(a, b) {
    const g = new THREE.BufferGeometry().setFromPoints([a, b]);
    const l = new THREE.Line(g, this.mat.clone());
    l.layers.set(1);
    this.scene.add(l); this.list.push({ l, t: 0 });
  }
  update(dt) {
    this.list = this.list.filter((o) => {
      o.t += dt; o.l.material.opacity = 1 - o.t / 0.08;
      if (o.t > 0.08) { this.scene.remove(o.l); o.l.geometry.dispose(); return false; }
      return true;
    });
  }
}

// 雨(頂点シェーダで落下とカメラ追従を計算)
export function makeRain(count = 9000) {
  const pos = new Float32Array(count * 2 * 3);
  const seed = new Float32Array(count * 2 * 4);
  for (let i = 0; i < count; i++) {
    const x = rand(-40, 40), y = rand(0, 30), z = rand(-40, 40), s = rand(0.7, 1.3);
    for (let e = 0; e < 2; e++) {
      pos.set([x, y, z], (i * 2 + e) * 3);
      seed.set([x, y, z, e === 0 ? 0 : s], (i * 2 + e) * 4);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('seed', new THREE.BufferAttribute(seed, 4));
  const mat = new THREE.ShaderMaterial({
    uniforms: { uTime: { value: 0 }, uCam: { value: new THREE.Vector3() }, uWind: { value: new THREE.Vector2(1.2, 0.4) }, uAmount: { value: 1 } },
    vertexShader: /* glsl */`
      attribute vec4 seed; uniform float uTime; uniform vec3 uCam; uniform vec2 uWind; varying float vA;
      void main(){
        vec3 p = seed.xyz;
        float fall = 22.0;
        p.y = mod(p.y - uTime * fall, 30.0);
        p.xz += uWind * (30.0 - p.y) * 0.04;
        // カメラ周辺の箱に巻き付ける
        p.x = mod(p.x - uCam.x + 40.0, 80.0) - 40.0 + uCam.x;
        p.z = mod(p.z - uCam.z + 40.0, 80.0) - 40.0 + uCam.z;
        p.y += uCam.y - 12.0;
        // 線の下端(速度方向に伸ばす)
        p.y -= seed.w * 0.55; p.xz -= uWind * seed.w * 0.03;
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        vA = smoothstep(60.0, 5.0, -mv.z) * smoothstep(0.5, 2.0, -mv.z);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: 'uniform float uAmount; varying float vA; void main(){ gl_FragColor = vec4(vec3(0.5,0.55,0.65) * vA * 0.28 * uAmount, 1.0); }',
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
  });
  const l = new THREE.LineSegments(g, mat);
  l.frustumCulled = false;
  l.layers.set(1);
  return l;
}

// 夜空(光害で地平線がにじむ都市の空)
export function makeSky() {
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { uTime: { value: 0 }, uDawn: { value: 0 }, uDay: { value: 0 } },
    vertexShader: 'varying vec3 vP; void main(){ vP = position; vec4 p = projectionMatrix * modelViewMatrix * vec4(position,1.0); gl_Position = p.xyww; }',
    fragmentShader: /* glsl */`
      varying vec3 vP; uniform float uTime, uDawn, uDay;
      float hash(vec2 p){ return fract(sin(dot(p, vec2(12.9898,78.233))) * 43758.5453); }
      float noise(vec2 p){ vec2 i = floor(p), f = fract(p); f = f*f*(3.0-2.0*f);
        return mix(mix(hash(i), hash(i+vec2(1,0)), f.x), mix(hash(i+vec2(0,1)), hash(i+vec2(1,1)), f.x), f.y); }
      float fbm(vec2 p){ float v = 0.0, a = 0.5; for (int i = 0; i < 5; i++) { v += a * noise(p); p *= 2.1; a *= 0.5; } return v; }
      void main(){
        vec3 d = normalize(vP);
        float h = max(d.y, 0.0);
        vec3 top = mix(vec3(0.01, 0.013, 0.028), vec3(0.08, 0.12, 0.25), uDawn);
        vec3 glow = mix(vec3(0.16, 0.1, 0.13), vec3(0.9, 0.45, 0.3), uDawn);
        vec3 col = mix(glow, top, pow(h, 0.45));
        // 低い雨雲(街の光で下から照らされる)
        vec2 uv = d.xz / (d.y + 0.15) * 1.3 + vec2(uTime * 0.01, 0.0);
        float c = fbm(uv);
        col += vec3(0.09, 0.07, 0.09) * smoothstep(0.35, 0.8, c) * (1.0 - h * 0.6) * (1.0 - uDawn * 0.5);
        // 昼(曇り): 明るい灰色の雲に覆われた空
        vec3 dayC = mix(vec3(0.78, 0.8, 0.82), vec3(0.55, 0.58, 0.62), pow(h, 0.6));
        dayC *= 0.88 + 0.16 * fbm(uv * 0.7 + uTime * 0.005);
        col = mix(col, dayC * 1.6, uDay);
        gl_FragColor = vec4(col, 1.0);
      }`,
  });
  const m = new THREE.Mesh(new THREE.SphereGeometry(900, 32, 16), mat);
  m.frustumCulled = false;
  m.renderOrder = -1;
  return m;
}
