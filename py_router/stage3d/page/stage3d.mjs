// The stage3d film's 3D board (#1081). A PURE FUNCTION of (scene, timeline,
// state index): `renderState(i)` sets every transform, visibility and colour
// from the timeline and renders once. Nothing reads a clock, so two renders
// of one state are the same pixels (pinned three.js, SwiftShader).
//
// Frames: KiCad's board (x, y-down) maps to three (x, z) with y UP out of the
// board's top face, so a KiCad rotation `rot` is `rotation.y = rad(rot)` --
// what kicad-cli's own GLB carries (F.Cu parts `Ry(rot)`, B.Cu `Ry(rot)
// Rx(180)`). The board turns over about its SCREEN-vertical axis (three z),
// the same flip the X-ray animates, so the far side comes up mirrored
// left-right exactly as the 2D film shows it.
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const S = {};

function rad(d) { return d * Math.PI / 180; }

function rgb(c) { return new THREE.Color(c[0] / 255, c[1] / 255, c[2] / 255); }

// ---------------------------------------------------------------- board
function buildBoard(scene, colors) {
  const d = scene.thickness;
  const shape = new THREE.Shape(scene.outline.map(p => new THREE.Vector2(p[0], p[1])));
  for (const ring of scene.cutouts) {
    shape.holes.push(new THREE.Path(ring.map(p => new THREE.Vector2(p[0], p[1]))));
  }
  const geo = new THREE.ExtrudeGeometry(shape, { depth: d, bevelEnabled: false, curveSegments: 24 });
  geo.rotateX(Math.PI / 2);          // shape (x, y) -> three (x, z); depth -> -y
  geo.translate(0, d, 0);            // y in [0, d]: the top face is y = d
  const mat = new THREE.MeshStandardMaterial({ color: rgb(colors.board), roughness: 0.85,
                                               metalness: 0.0, transparent: true, opacity: 0.9 });
  return new THREE.Mesh(geo, mat);
}

// ---------------------------------------------------------------- copper
const COPPER_VS = `
attribute float born; attribute float died; attribute float hidden;
uniform float uN; varying float vKeep;
void main() {
  vKeep = (born < uN && (died < 0.0 || died >= uN) && hidden < 0.5) ? 1.0 : 0.0;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`;
const COPPER_FS = `
uniform vec3 uColor; uniform float uAlpha; varying float vKeep;
void main() { if (vKeep < 0.5) discard; gl_FragColor = vec4(uColor, uAlpha); }`;

function layerY(li, n, d) {
  if (li === 0) return d + 0.035;                 // F.Cu, on the top face
  if (li === n - 1) return -0.035;                // B.Cu, on the bottom face
  return d * (1 - li / (n - 1));                  // an inner layer, inside
}

// One flat quad per segment, lengthened by half its width at each end (a
// square-capped trace), with its item index, birth and death per vertex.
function segQuads(items, y, withLife) {
  const pos = [], born = [], died = [], idx = [], hid = [];
  const tri = [];
  let v = 0;
  for (const it of items) {
    const [sx, sy, ex, ey, w] = it.row;
    let dx = ex - sx, dy = ey - sy;
    const L = Math.hypot(dx, dy) || 1e-6;
    dx /= L; dy /= L;
    const hw = Math.max(w, 0.05) / 2;
    const nx = -dy * hw, ny = dx * hw;
    const ax = sx - dx * hw, ay = sy - dy * hw, bx = ex + dx * hw, by = ey + dy * hw;
    pos.push(ax + nx, y, ay + ny, ax - nx, y, ay - ny, bx - nx, y, by - ny, bx + nx, y, by + ny);
    tri.push(v, v + 2, v + 1, v, v + 3, v + 2, v, v + 1, v + 2, v, v + 2, v + 3);  // both faces
    for (let k = 0; k < 4; k++) {
      if (withLife) { born.push(it.born); died.push(it.died); hid.push(0); idx.push(it.i); }
    }
    v += 4;
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  if (withLife) {
    g.setAttribute('born', new THREE.Float32BufferAttribute(born, 1));
    g.setAttribute('died', new THREE.Float32BufferAttribute(died, 1));
    g.setAttribute('hidden', new THREE.Float32BufferAttribute(hid, 1));
  }
  g.setIndex(tri);
  g.userData.items = idx;
  return g;
}

function buildCopper(tl, scene, colors, root) {
  const n = tl.layers.length, d = scene.thickness;
  S.copper = [];
  S.segLayerOf = new Int32Array(tl.segs.length);
  S.segSlot = new Int32Array(tl.segs.length);
  const per = tl.layers.map(() => []);
  tl.segs.forEach((s, i) => {
    const li = s[5];
    S.segLayerOf[i] = li;
    S.segSlot[i] = per[li].length;
    per[li].push({ row: s, born: s[6], died: s[7], i });
  });
  per.forEach((items, li) => {
    if (!items.length) { S.copper.push(null); return; }
    const g = segQuads(items, layerY(li, n, d), true);
    const inner = li !== 0 && li !== n - 1;
    const m = new THREE.ShaderMaterial({
      vertexShader: COPPER_VS, fragmentShader: COPPER_FS, transparent: inner,
      uniforms: { uN: { value: 0 }, uColor: { value: rgb(colors.layers[li] || colors.pad) },
                  uAlpha: { value: inner ? 0.55 : 1.0 } } });
    const mesh = new THREE.Mesh(g, m);
    mesh.renderOrder = inner ? 1 : 2;
    root.add(mesh);
    S.copper.push(mesh);
  });
  // vias: one instanced barrel each, shown or scaled away per frame
  const cyl = new THREE.CylinderGeometry(0.5, 0.5, d + 0.09, 16);
  cyl.translate(0, d / 2, 0);
  const vm = new THREE.MeshStandardMaterial({ color: rgb(colors.via), roughness: 0.4, metalness: 0.6 });
  S.vias = new THREE.InstancedMesh(cyl, vm, Math.max(1, tl.vias.length));
  S.vias.count = tl.vias.length;
  S.viaRows = tl.vias;
  S.lastNv = -1;
  root.add(S.vias);
  S.hidden = new Set();
}

function setCopper(st) {
  for (const m of S.copper) if (m) m.material.uniforms.uN.value = st.ns;
  // a growth stage hides its finished self under it (`hide` = item indices)
  const want = new Set(st.hide);
  const touched = new Set();
  for (const i of S.hidden) if (!want.has(i)) touched.add(i);
  for (const i of want) if (!S.hidden.has(i)) touched.add(i);
  for (const i of touched) {
    const m = S.copper[S.segLayerOf[i]];
    if (!m) continue;
    const a = m.geometry.getAttribute('hidden');
    const base = S.segSlot[i] * 4;
    const v = want.has(i) ? 1 : 0;
    for (let k = 0; k < 4; k++) a.array[base + k] = v;
    a.needsUpdate = true;
  }
  S.hidden = want;
  if (st.nv !== S.lastNv) {
    const M = new THREE.Matrix4(), Z = new THREE.Matrix4().makeScale(0, 0, 0);
    S.viaRows.forEach((v, i) => {
      const on = v[6] < st.nv && (v[7] < 0 || v[7] >= st.nv);
      if (on) {
        const r = Math.max(v[2], 0.1);
        M.makeScale(r, 1, r).setPosition(v[0], 0, v[1]);
        S.vias.setMatrixAt(i, M);
      } else S.vias.setMatrixAt(i, Z);
    });
    S.vias.instanceMatrix.needsUpdate = true;
    S.lastNv = st.nv;
  }
}

function setHighlight(st, tl, scene, colors, root) {
  if (S.hl) {
    root.remove(S.hl);
    S.hl.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
    S.hl = null;
  }
  if (!st.hl_s.length && !st.hl_v.length) return;
  const n = tl.layers.length, d = scene.thickness;
  const col = st.color ? rgb(st.color) : rgb(colors.hilite);
  const g = new THREE.Group();
  const byLayer = {};
  for (const h of st.hl_s) (byLayer[h[5]] = byLayer[h[5]] || []).push({ row: h });
  for (const li of Object.keys(byLayer)) {
    const y = layerY(+li, n, d) + (+li === n - 1 ? -0.03 : 0.03);
    const geo = segQuads(byLayer[li], y, false);
    g.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: col, side: THREE.DoubleSide })));
  }
  for (const v of st.hl_v) {
    const c = new THREE.Mesh(new THREE.CylinderGeometry(v[2] / 2 + 0.05, v[2] / 2 + 0.05, d + 0.15, 16),
                             new THREE.MeshBasicMaterial({ color: col }));
    c.position.set(v[0], d / 2, v[1]);
    g.add(c);
  }
  g.traverse(o => { o.renderOrder = 3; });
  S.hl = g;
  root.add(g);
}

// ---------------------------------------------------------------- parts
function buildParts(scene, colors, root) {
  S.parts = {};
  const d = scene.thickness;
  const bodyMat = new THREE.MeshStandardMaterial({ color: rgb(colors.body), roughness: 0.7 });
  const padMat = new THREE.MeshStandardMaterial({ color: rgb(colors.pad), roughness: 0.35, metalness: 0.7 });
  for (const ref of Object.keys(scene.parts).sort()) {
    const P = scene.parts[ref];
    const grp = new THREE.Group();
    const faces = { F: new THREE.Group(), B: new THREE.Group() };
    for (const p of P.pads) {
      const [lx, ly, sx, sy, ang, shape, face] = p;
      const geo = (shape === 'circle')
        ? new THREE.CylinderGeometry(Math.max(sx, sy) / 2, Math.max(sx, sy) / 2, 0.05, 20)
        : new THREE.BoxGeometry(Math.max(sx, 0.05), 0.05, Math.max(sy, 0.05));
      for (const f of (face === 'T' ? ['F', 'B'] : [face])) {
        const m = new THREE.Mesh(geo, padMat);
        m.position.set(lx, f === 'F' ? 0.03 : -0.03, ly);
        m.rotation.y = -rad(ang);
        faces[f].add(m);
      }
    }
    let body = null;
    if (P.body) {
      const [x0, y0, x1, y1, h] = P.body;
      body = new THREE.Mesh(new THREE.BoxGeometry(Math.max(x1 - x0, 0.1), h, Math.max(y1 - y0, 0.1)), bodyMat);
      body.position.set((x0 + x1) / 2, h / 2 + 0.06, (y0 + y1) / 2);
      grp.add(body);
    }
    grp.add(faces.F, faces.B);
    root.add(grp);
    S.parts[ref] = { grp, faces, body, side: P.side, d };
  }
}

function poseParts(st, tl) {
  const ep = tl.epochs[Math.max(0, Math.min(st.epoch, tl.epochs.length - 1))] || {};
  for (const ref of Object.keys(S.parts)) {
    const part = S.parts[ref];
    const e = ep[ref];
    if (!e) { part.grp.visible = false; continue; }
    part.grp.visible = true;
    const m = st.moving[ref];
    const x = m ? m[0] : e[0], y = m ? m[1] : e[1], rot = m ? m[2] : e[2];
    const back = String(e[3] || 'F.Cu').startsWith('B');
    part.grp.position.set(x, back ? 0 : part.d, y);
    part.grp.rotation.set(0, rad(rot), 0);
    // pads drawn on the part's own face (THT pads carry both), and the body
    // hangs below a back-side part
    part.faces.F.position.y = back ? part.d : 0;
    part.faces.B.position.y = back ? 0 : -part.d;
    if (part.body) {
      part.body.scale.y = back ? -1 : 1;
      part.body.visible = !part.glb;
    }
    if (part.glb) {
      const F = new THREE.Matrix4().makeRotationY(rad(rot));
      if (back) F.multiply(new THREE.Matrix4().makeRotationX(Math.PI));
      F.setPosition(x, 0, y);
      for (const n of part.glb) {
        n.obj.matrix.multiplyMatrices(F, n.rest);
        n.obj.matrixWorldNeedsUpdate = true;
      }
    }
  }
}

async function loadGlb(url, glb, root) {
  const buf = await (await fetch(url)).arrayBuffer();
  const gltf = await new GLTFLoader().parseAsync(buf, '');
  gltf.scene.updateMatrixWorld(true);
  const want = new Set(glb.matched);
  const mm = new THREE.Matrix4().makeScale(1000, 1000, 1000);   // glTF metres -> mm
  const picked = [];
  gltf.scene.traverse(o => {
    if (!want.has(o.name)) return;
    for (let a = o.parent; a; a = a.parent) if (want.has(a.name)) return;  // top node only
    picked.push(o);
  });
  let n = 0;
  for (const o of picked) {
    const pose = glb.poses[o.name];
    const part = S.parts[o.name];
    if (!pose || !part) continue;
    // rest = F(final)^-1 * node (in mm): the model in its part's own frame,
    // so any later pose is F(now) * rest -- no knowledge of the model's own
    // offset needed.
    const F = new THREE.Matrix4().makeRotationY(rad(pose[2]));
    if (pose[3] === 'B') F.multiply(new THREE.Matrix4().makeRotationX(Math.PI));
    F.setPosition(pose[0], 0, pose[1]);
    const world = new THREE.Matrix4().multiplyMatrices(mm, o.matrixWorld);
    const rest = new THREE.Matrix4().copy(F).invert().multiply(world);
    const clone = o.clone(true);
    clone.matrixAutoUpdate = false;
    clone.matrix.identity();
    clone.traverse(c => { if (c !== clone) c.matrixAutoUpdate = true; });
    // children keep their own local transforms; the clone's matrix is the
    // whole world transform, so strip its scale ancestry by construction
    root.add(clone);
    (part.glb = part.glb || []).push({ obj: clone, rest });
    n += 1;
  }
  return n;
}

// ---------------------------------------------------------------- camera
function frameCamera(scene, W, H) {
  const [x0, y0, x1, y1] = scene.bounds;
  const cx = (x0 + x1) / 2, cz = (y0 + y1) / 2;
  const r = 0.5 * Math.hypot(x1 - x0, y1 - y0) + 2;
  const fov = 30;
  const cam = new THREE.PerspectiveCamera(fov, W / H, 0.5, 100000);
  const fv = rad(fov), fh = 2 * Math.atan(Math.tan(fv / 2) * W / H);
  let dist = r / Math.sin(Math.min(fv, fh) / 2);
  const el = rad(52);                   // a 3/4 view from the board's near edge
  const cy = scene.thickness / 2;
  // Fit the board's OWN corners, not a bounding sphere: a long board seen at
  // 3/4 wastes most of a sphere fit. The flip turns the board about the
  // screen-vertical axis, so its x-extent is what the turn sweeps; the fit
  // holds at every angle because the corners are symmetric about the pivot.
  const corners = [];
  for (const x of [x0, x1]) for (const z of [y0, y1]) for (const y of [-3, scene.thickness + 3])
    corners.push(new THREE.Vector3(x, y, z));
  for (let k = 0; k < 4; k++) {
    cam.position.set(cx, cy + dist * Math.sin(el), cz + dist * Math.cos(el));
    cam.lookAt(cx, cy, cz);
    cam.updateMatrixWorld(true);
    let ext = 0;
    for (const c of corners) {
      const p = c.clone().project(cam);
      ext = Math.max(ext, Math.abs(p.x), Math.abs(p.y));
    }
    dist *= ext / 0.9;                  // 10 % margin
  }
  cam.position.set(cx, cy + dist * Math.sin(el), cz + dist * Math.cos(el));
  cam.lookAt(cx, cy, cz);
  return { cam, cx, cz };
}

// ---------------------------------------------------------------- entry
window.stage3dInit = async function (o) {
  const scene = await (await fetch(o.sceneUrl)).json();
  const tl = await (await fetch(o.timelineUrl)).json();
  const W = o.width, H = o.height;
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: false });
  renderer.setPixelRatio(1);
  renderer.setSize(W, H);
  renderer.setClearColor(rgb(o.colors.ground), 1);
  document.body.appendChild(renderer.domElement);
  const world = new THREE.Scene();
  world.add(new THREE.HemisphereLight(0xffffff, 0x404048, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(0.35, 1.0, 0.7);
  world.add(sun);
  const { cam, cx, cz } = frameCamera(scene, W, H);
  // the flip pivot: the board turns about the screen-vertical axis through
  // its centre, like the X-ray's flip
  const pivot = new THREE.Group();
  pivot.position.set(cx, scene.thickness / 2, cz);
  const root = new THREE.Group();
  root.position.set(-cx, -scene.thickness / 2, -cz);
  pivot.add(root);
  world.add(pivot);
  root.add(buildBoard(scene, o.colors));
  buildCopper(tl, scene, o.colors, root);
  buildParts(scene, o.colors, root);
  let glbParts = 0;
  if (o.glbUrl && scene.glb) glbParts = await loadGlb(o.glbUrl, scene.glb, root);
  Object.assign(S, { renderer, world, cam, pivot, root, tl, scene, colors: o.colors });
  const gl = renderer.getContext();
  const ext = gl.getExtension('WEBGL_debug_renderer_info');
  return { renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
           three: THREE.REVISION, states: tl.states.length, glbParts };
};

window.renderState = function (i) {
  const st = S.tl.states[i];
  setCopper(st);
  setHighlight(st, S.tl, S.scene, S.colors, S.root);
  poseParts(st, S.tl);
  S.pivot.rotation.set(0, 0, st.angle);
  S.renderer.render(S.world, S.cam);
  return true;
};

window.stage3dReady = true;
