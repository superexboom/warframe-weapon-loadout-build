import * as THREE from './vendor/three.module.js';

// Conservative horizontal footprint: a prop spanning even one padded NAV cell stays in.
export function exteriorScenery(nav) {
  const cells = new Map(), cell = 8, margin = 5;
  for (const face of nav.triangles) {
    const [a,b,c] = face.map(i => nav.vertices[i]);
    const x0 = Math.floor((Math.min(a[0],b[0],c[0])-margin)/cell), x1 = Math.floor((Math.max(a[0],b[0],c[0])+margin)/cell);
    const z0 = Math.floor((Math.min(a[2],b[2],c[2])-margin)/cell), z1 = Math.floor((Math.max(a[2],b[2],c[2])+margin)/cell);
    for (let z=z0; z<=z1; z++) {
      let row=cells.get(z); if (!row) cells.set(z,row=new Set());
      for (let x=x0; x<=x1; x++) row.add(x);
    }
  }
  return (source, bounds) => {
    if (source.category!=='prop') return false;
    if (/\/[^/]*BackgroundCanopy[^/]*$/i.test(source.path)) return true;
    const x0=Math.floor(bounds.min.x/cell), x1=Math.floor(bounds.max.x/cell);
    for(let z=Math.floor(bounds.min.z/cell); z<=Math.floor(bounds.max.z/cell); z++) {
      const row=cells.get(z); if (!row) continue;
      for (let x=x0; x<=x1; x++) if (row.has(x)) return false;
    }
    return true;
  };
}

// Draw just the NAV depth once per camera/section change. Detailed fragments can
// reveal a floor behind them without tracing the visual meshes on the CPU.
export function createClearView(renderer, camera, plane) {
  const depth = new THREE.DepthTexture(1,1,THREE.UnsignedIntType);
  depth.minFilter=depth.magFilter=THREE.NearestFilter;
  const target=new THREE.WebGLRenderTarget(1,1,{depthTexture:depth});
  const reference=new THREE.Scene();
  const ground=new THREE.Mesh(undefined,new THREE.MeshBasicMaterial({side:THREE.DoubleSide,colorWrite:false,clippingPlanes:[plane]}));
  reference.add(ground);
  const size=new THREE.Vector2(), vp=new THREE.Matrix4(), previous=new THREE.Matrix4();
  const uniforms={arenaNavDepth:{value:depth},arenaViewSize:{value:size},arenaNearFar:{value:new THREE.Vector2(camera.near,camera.far)},arenaClear:{value:false}};
  let dirty=true, previousCut;
  function attach(shader) {
    Object.assign(shader.uniforms,uniforms);
    shader.fragmentShader=shader.fragmentShader.replace('#include <common>',`#include <common>
      uniform sampler2D arenaNavDepth;
      uniform vec2 arenaViewSize, arenaNearFar;
      uniform bool arenaClear;`).replace('#include <clipping_planes_fragment>',`#include <clipping_planes_fragment>
      if (arenaClear) {
        float d = texture2D(arenaNavDepth, gl_FragCoord.xy / arenaViewSize).r;
        if (d < 1.0) {
          float floorDepth = -perspectiveDepthToViewZ(d, arenaNearFar.x, arenaNearFar.y);
          float gap = floorDepth - vViewPosition.z;
          float height = gap * dot(vViewPosition, viewMatrix[1].xyz) / vViewPosition.z;
          if (gap > 3.0 && (height > 2.2 || (gap > 12.0 && height > 0.6))) discard;
        }
      }`);
  }
  function prepare(geometry,enabled) {
    uniforms.arenaClear.value=Boolean(enabled && geometry);
    if (!uniforms.arenaClear.value) return;
    if (ground.geometry!==geometry) {ground.geometry=geometry;dirty=true;}
    renderer.getDrawingBufferSize(size);
    const scale=Math.min(.75,768/Math.max(size.x,size.y));
    const w=Math.max(1,Math.round(size.x*scale)),h=Math.max(1,Math.round(size.y*scale));
    if (w!==target.width || h!==target.height) {target.setSize(w,h);dirty=true;}
    camera.updateMatrixWorld();vp.multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse);
    if (!dirty && previousCut===plane.constant && previous.equals(vp)) return;
    previous.copy(vp);previousCut=plane.constant;dirty=false;
    renderer.setRenderTarget(target);renderer.render(reference,camera);renderer.setRenderTarget(null);
  }
  return {attach,prepare,clear(){ground.geometry=null;dirty=true;uniforms.arenaClear.value=false;}};
}
