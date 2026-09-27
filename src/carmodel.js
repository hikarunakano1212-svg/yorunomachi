// Blender 製の車 glb を「車体1メッシュ + タイヤ4本」にまとめ直す(描画コール削減)。
// 部位ごとの色・粗さ・発光は頂点属性に焼き込み、塗装色・ブレーキ・サイレンはユニフォームで切り替える。
import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';

const MASK = { normal: 0, paint: 1, tail: 2, siren: 3 };
const cache = new Map();

function bakeMesh(mesh, rootInv, mask) {
  mesh.updateWorldMatrix(true, false);
  const g = mesh.geometry.clone().applyMatrix4(new THREE.Matrix4().multiplyMatrices(rootInv, mesh.matrixWorld));
  const m = mesh.material;
  const n = g.attributes.position.count;
  const col = new Float32Array(n * 3), emit = new Float32Array(n), mk = new Float32Array(n), rough = new Float32Array(n), metal = new Float32Array(n);
  const e = m.emissive ? m.emissive.clone().multiplyScalar(m.emissiveIntensity ?? 1) : new THREE.Color(0);
  const aoAttr = g.attributes.color; // Blender で焼いた AO(頂点カラー)
  const ao = new Float32Array(n);
  const hasEmit = e.r + e.g + e.b > 0.01;
  for (let i = 0; i < n; i++) {
    const c = hasEmit ? e : m.color;
    col.set([c.r, c.g, c.b], i * 3);
    emit[i] = hasEmit ? 1 : 0;
    mk[i] = mask; rough[i] = m.roughness ?? 0.5; metal[i] = m.metalness ?? 0;
    ao[i] = aoAttr ? Math.min(1, aoAttr.getX(i) * 1.15) : 1;
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', g.attributes.position);
  out.setAttribute('normal', g.attributes.normal);
  out.setAttribute('color', new THREE.BufferAttribute(col, 3));
  out.setAttribute('aEmit', new THREE.BufferAttribute(emit, 1));
  out.setAttribute('aMask', new THREE.BufferAttribute(mk, 1));
  out.setAttribute('aRough', new THREE.BufferAttribute(rough, 1));
  out.setAttribute('aMetal', new THREE.BufferAttribute(metal, 1));
  out.setAttribute('aAO', new THREE.BufferAttribute(ao, 1));
  if (g.index) out.setIndex(g.index);
  return out.index ? out.toNonIndexed() : out;
}

export function carTemplate(root, { andon }) {
  const key = root.uuid + andon;
  if (cache.has(key)) return cache.get(key);
  root.updateMatrixWorld(true);
  const rootInv = root.matrixWorld.clone().invert();
  const body = [], wheels = [];
  root.traverse((o) => {
    if (!o.isMesh) return;
    let p = o, wheel = null;
    while (p) { if (p.name.startsWith('Wheel_')) wheel = p; p = p.parent; }
    const name = (o.name + ' ' + (o.parent?.name ?? '')).trim();
    if (name.includes('Andon') && !andon) return;
    if (wheel) {
      // タイヤは回転軸を原点にしたローカル座標で焼く
      wheel.updateWorldMatrix(true, false);
      const inv = wheel.matrixWorld.clone().invert();
      wheels.push({ tag: wheel.name.slice(6), geo: bakeMesh(o, inv, MASK.normal), pos: new THREE.Vector3().setFromMatrixPosition(new THREE.Matrix4().multiplyMatrices(rootInv, wheel.matrixWorld)) });
      return;
    }
    // 塗装はマテリアル名で判定(キャビンの屋根面なども含む)
    const matName = o.material.name;
    const mask = matName === 'TailLight' ? MASK.tail : matName === 'Siren' ? MASK.siren : matName === 'Paint' ? MASK.paint : MASK.normal;
    body.push(bakeMesh(o, rootInv, mask));
  });
  const byTag = {};
  for (const w of wheels) (byTag[w.tag] ??= { geos: [], pos: w.pos }).geos.push(w.geo);
  const t = {
    body: mergeGeometries(body),
    wheels: Object.entries(byTag).map(([tag, w]) => ({ tag, geo: mergeGeometries(w.geos), pos: w.pos })),
  };
  cache.set(key, t);
  return t;
}

export function carMaterial(paint) {
  const u = { uPaint: { value: new THREE.Color(paint) }, uBrake: { value: 1 }, uSiren: { value: new THREE.Color(0) } };
  // 塗装はクリアコート(二層塗装)で、映り込みがくっきり乗る
  const m = new THREE.MeshPhysicalMaterial({ vertexColors: true, clearcoat: 1, clearcoatRoughness: 0.06 });
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, u);
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nattribute float aEmit, aMask, aRough, aMetal, aAO;\nvarying float vEmit, vMask, vRough, vMetal, vAO;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvEmit = aEmit; vMask = aMask; vRough = aRough; vMetal = aMetal; vAO = aAO;');
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', '#include <common>\nvarying float vEmit, vMask, vRough, vMetal, vAO;\nuniform vec3 uPaint, uSiren; uniform float uBrake;')
      .replace('#include <color_fragment>', `#include <color_fragment>
        vec3 baseVC = diffuseColor.rgb;
        if (vMask > 0.5 && vMask < 1.5) diffuseColor.rgb = uPaint;
        if (vEmit > 0.5) diffuseColor.rgb *= 0.2;
        diffuseColor.rgb *= vAO;`)
      .replace('#include <roughnessmap_fragment>', '#include <roughnessmap_fragment>\nroughnessFactor = vRough;')
      .replace('#include <aomap_fragment>', '#include <aomap_fragment>\nreflectedLight.indirectDiffuse *= vAO; reflectedLight.indirectSpecular *= mix(0.4, 1.0, vAO);')
      .replace('#include <metalnessmap_fragment>', '#include <metalnessmap_fragment>\nmetalnessFactor = vMetal;')
      .replace('#include <lights_physical_fragment>', '#include <lights_physical_fragment>\nmaterial.clearcoat *= (vMask > 0.5 && vMask < 1.5) ? 1.0 : 0.0;')
      .replace('#include <emissivemap_fragment>', `#include <emissivemap_fragment>
        if (vEmit > 0.5) {
          float k = vMask > 1.5 && vMask < 2.5 ? uBrake : 1.0;
          totalEmissiveRadiance += baseVC * k;
          if (vMask > 2.5) totalEmissiveRadiance = uSiren;
        }`);
  };
  m.userData.u = u;
  return m;
}
