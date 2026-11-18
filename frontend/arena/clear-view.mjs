import * as THREE from './vendor/three.module.js';

// Only static scenery and its lights are visible to the lens camera.
export const lensLayer = 1;

export function createClearView(renderer, scene, camera) {
  const cropCamera = new THREE.PerspectiveCamera();
  const target = new THREE.WebGLRenderTarget(1, 1, {depthBuffer:true});
  const size = new THREE.Vector2(), previousSize = new THREE.Vector2();
  const vp = new THREE.Matrix4(), previousVP = new THREE.Matrix4();
  const actor = new THREE.Vector3(), previousActor = new THREE.Vector3(), projected = new THREE.Vector3();
  const circle = new THREE.Vector3(); // drawing-buffer center (bottom left origin) and radius
  const mode = {value:0}, behind = {value:null};
  const uniforms = {arenaLensMode:mode, arenaBehind:behind, arenaCircle:{value:circle}, arenaActorView:{value:actor}};
  let dirty = true, previousCut, previousRadius;

  function attach(shader) {
    Object.assign(shader.uniforms, uniforms);
    shader.fragmentShader = shader.fragmentShader.replace('#include <common>', `#include <common>
      uniform int arenaLensMode;
      uniform sampler2D arenaBehind;
      uniform vec3 arenaCircle, arenaActorView;
      float arenaForeground(vec3 toEye) {
        vec3 delta = arenaActorView - toEye;
        float height = dot(delta, viewMatrix[1].xyz);
        float horizontal2 = dot(delta, delta) - height * height;
        // The actor anchor is one metre above its feet. Keep nearby low cover
        // and the footing intact; a distant eye-level wall can still obstruct it.
        float sill = mix(1.0, -0.65, smoothstep(36.0, 144.0, horizontal2));
        vec3 face = normalize(cross(dFdx(toEye), dFdy(toEye)));
        float walkSlope = smoothstep(0.55, 0.82, abs(dot(face, viewMatrix[1].xyz)));
        sill = max(sill, mix(-0.65, 2.0, walkSlope));
        return smoothstep(1.0, 3.0, delta.z) * smoothstep(sill, sill + 1.0, height);
      }`).replace('#include <clipping_planes_fragment>', `#include <clipping_planes_fragment>
      if (arenaLensMode == 1 && arenaForeground(vViewPosition) > 0.0) discard;
      `).replace('#include <opaque_fragment>', `#include <opaque_fragment>
      if (arenaLensMode == 2) {
        vec2 offset = (gl_FragCoord.xy - arenaCircle.xy) / arenaCircle.z;
        float r2 = dot(offset, offset);
        if (r2 < 1.0) {
          float weight = 0.70 * (1.0 - smoothstep(0.58, 1.0, sqrt(r2))) * arenaForeground(vViewPosition);
          if (weight > 0.0) {
            vec4 rear = texture2D(arenaBehind, offset * 0.5 + 0.5);
            if (rear.a > 0.0) gl_FragColor.rgb = mix(gl_FragColor.rgb, rear.rgb / rear.a, weight * rear.a);
          }
        }
      }`);
  }

  function prepare(anchor, radiusFraction, cut) {
    mode.value = 0;
    if (!anchor) return;
    camera.updateMatrixWorld();
    actor.copy(anchor).applyMatrix4(camera.matrixWorldInverse).negate();
    if (actor.z <= camera.near || actor.z >= camera.far) return;
    projected.copy(anchor).project(camera);
    if (Math.abs(projected.x) > 1 || Math.abs(projected.y) > 1) return;

    renderer.getDrawingBufferSize(size);
    const radius = Math.round(Math.min(size.x, size.y) * radiusFraction);
    if (!radius) return;
    circle.set((projected.x + 1) * size.x / 2, (projected.y + 1) * size.y / 2, radius);
    vp.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    if (dirty || !vp.equals(previousVP) || !anchor.equals(previousActor) || !size.equals(previousSize) || radius !== previousRadius || cut !== previousCut) {
      const diameter = 2 * radius, resolution = Math.min(384, diameter);
      target.setSize(resolution, resolution);
      cropCamera.copy(camera, false);
      cropCamera.layers.set(lensLayer);
      cropCamera.setViewOffset(size.x, size.y, circle.x - radius, size.y - circle.y - radius, diameter, diameter);
      // An empty reference pixel means no modeled surface lies behind the
      // foreground. Leave its original colour intact instead of exposing sky.
      const background = scene.background, clearAlpha = renderer.getClearAlpha();
      scene.background = null; renderer.setClearAlpha(0);
      mode.value = 1; behind.value = null; // never sample a bound render target
      renderer.setRenderTarget(target);
      renderer.render(scene, cropCamera);
      renderer.setRenderTarget(null);
      scene.background = background; renderer.setClearAlpha(clearAlpha);
      previousVP.copy(vp); previousActor.copy(anchor); previousSize.copy(size);
      previousRadius = radius; previousCut = cut; dirty = false;
    }
    behind.value = target.texture; mode.value = 2;
  }

  return {attach, prepare, invalidate(){dirty = true;}};
}
