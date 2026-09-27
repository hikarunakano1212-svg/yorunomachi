// Blender で生成した glb を読み込んで複製するための窓口
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { clone as skeletonClone } from 'three/addons/utils/SkeletonUtils.js';

const NAMES = ['car_sedan', 'car_taxi', 'car_kei', 'car_van', 'car_truck', 'car_bus', 'car_police', 'vending', 'lantern', 'cone',
  'person_m', 'person_f', 'pistol', 'signal', 'tree', 'lamp'];
// Mixamo の人物(あれば使う。無ければ Blender 製の人物で代用)
const OPTIONAL = ['mx_ch12', 'mx_ch33'];

export async function loadAssets(base = 'assets/models/', onProgress = () => {}) {
  const loader = new GLTFLoader();
  const store = {};
  let done = 0;
  await Promise.all(OPTIONAL.map(async (n) => {
    try {
      const gltf = window.__MODELS ? (window.__MODELS[n] ? await loader.parseAsync(JSON.stringify(window.__MODELS[n]), '') : null)
        : await loader.loadAsync(`${base}${n}.glb`);
      if (!gltf) return;
      gltf.scene.userData.animations = gltf.animations;
      gltf.scene.traverse((o) => { if (o.isMesh) { o.castShadow = true; } });
      store[n] = gltf.scene;
    } catch { /* 無ければ使わない */ }
  }));
  await Promise.all(NAMES.map(async (n) => {
    // 単体HTML版ではモデルが window.__MODELS に埋め込まれている
    const gltf = window.__MODELS
      ? await loader.parseAsync(JSON.stringify(window.__MODELS[n]), '')
      : await loader.loadAsync(`${base}${n}${window.__MODEL_EXT ?? '.glb'}`);
    const root = gltf.scene;
    root.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = false; o.receiveShadow = false;
        const m = o.material;
        // 夜景でしっかり光るよう、発光部はブルームのしきい値を超える強さにする
        if (m.emissive && m.emissive.getHex() !== 0) m.emissiveIntensity = Math.max(m.emissiveIntensity, 3);
        // 自販機は筐体ごと明るく光って見えるように
        if (m.name === 'VendRed') { m.emissive.setRGB(0.5, 0.03, 0.04); m.emissiveIntensity = 0.5; }
        if (m.name === 'VendPanel') m.emissiveIntensity = 1.4;
      }
    });
    store[n] = root;
    root.userData.animations = gltf.animations;
    onProgress(++done / NAMES.length);
  }));
  return {
    get: (n) => store[n],
    has: (n) => !!store[n],
    // 骨格付きモデルの複製(骨ごと複製する)
    cloneSkinned(n) {
      const c = skeletonClone(store[n]);
      c.traverse((o) => { if (o.isMesh) o.material = o.material.clone(); });
      c.userData.animations = store[n].userData.animations;
      return c;
    },
    clone: (n) => store[n].clone(true),
    // マテリアルも複製する(個体ごとに色を変えるとき用)
    cloneUnique(n) {
      const c = store[n].clone(true);
      c.traverse((o) => { if (o.isMesh) o.material = o.material.clone(); });
      return c;
    },
  };
}
