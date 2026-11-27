import * as THREE from './vendor/three.module.js';
import {OrbitControls} from './vendor/OrbitControls.js';
import {createClearView, lensLayer} from './clear-view.mjs';
import {shell} from './shell.js';

const DEFAULT_WARFRAME_PORTRAIT = '/assets/warframes/portraits/Excalibur.png';

const DAMAGE_LABELS = {
  DT_IMPACT: '冲击',
  DT_PUNCTURE: '穿刺',
  DT_SLASH: '切割',
  DT_FIRE: '火焰',
  DT_FREEZE: '冰冻',
  DT_ELECTRICITY: '电击',
  DT_POISON: '毒素',
  DT_EXPLOSION: '爆炸',
  DT_RADIATION: '辐射',
  DT_GAS: '毒气',
  DT_MAGNETIC: '磁力',
  DT_VIRAL: '病毒',
  DT_CORROSIVE: '腐蚀',
  DT_RADIANT: '虚空',
  DT_FINISHER: '处决',
  DT_TRUE: '真实',
};

function fmtNum(value, maxFrac = 1) {
  return Number(value || 0).toLocaleString('zh-CN', {maximumFractionDigits: maxFrac});
}

function factionInitial(enemyInfo, enemyPath = '') {
  const token = [enemyInfo?.factionZh, enemyInfo?.faction, enemyInfo?.factionName, enemyPath]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
  if (token.includes('narmer') || token.includes('合一众')) return '合';
  if (token.includes('duviri') || token.includes('murmur') || token.includes('双衍') || token.includes('低语')) return '双';
  if (token.includes('grineer') || token.includes('克隆尼') || token.includes('scaldra')) return 'G';
  if (token.includes('corpus') || token.includes('科普斯')) return 'C';
  if (token.includes('infest') || token.includes('感染') || token.includes('techrot')) return 'I';
  if (token.includes('orokin') || token.includes('corrupted') || token.includes('奥罗金') || token.includes('堕落')) return 'O';
  if (token.includes('sentient')) return 'S';
  return '?';
}

function weaponIconCandidates(weaponPath, weaponNameEn = '') {
  const mapped = (typeof window !== 'undefined' && window.__WF_BUNDLE_PROFILE__?.weaponIconMap) || null;
  if (mapped && weaponPath && Object.prototype.hasOwnProperty.call(mapped, weaponPath)) {
    const resolved = mapped[weaponPath];
    return resolved ? ['/assets/weapons/' + resolved] : [];
  }
  const internal = String(weaponPath || '').split('/').pop() || '';
  const name = String(weaponNameEn || '');
  const raw = [];
  if (internal) raw.push(internal);
  if (name) {
    raw.push(
      name.replace(/ /g, ''),
      name.replace(/ /g, '').replace(/'/g, ''),
      name.replace(/ /g, '').replace(/-/g, ''),
    );
  }
  const seen = new Set();
  const out = [];
  for (const pattern of raw) {
    if (!pattern) continue;
    for (const variant of [pattern, pattern.replace(/^MK1(?=[A-Z])/, 'Mk1')]) {
      if (!variant || seen.has(variant)) continue;
      seen.add(variant);
      out.push('/assets/weapons/' + variant + '.png');
    }
  }
  return out;
}

export function mountArena(host) {
  host.innerHTML = '<div class="arena-layout">' + shell + '</div>';
  let loadout = null, weaponLabel = '', openMeta = null;
  let catalog = null, mapId = '', visualUrl = '', job = null, pollTimer = null, active = false, loadToken = 0;
  let currentReplay = null, catalogLoading = false;
  const replaysByMap = new Map();
  let selectedEnemy = '', enemyIndex = new Map();

  let viewPrefs = {
    clipMode: 'roof',
    cutHeight: 20,
    colors: 'semantic',
    quality: 'balanced',
    marker: true,
    clearView: true,
    lensRadius: 18,
    avatars: true,
    droneAura: true,
    abilityRanges: true,
  };
  try {
    const stored = JSON.parse(localStorage.getItem('arena-view-v1') || 'null');
    if (stored) viewPrefs = {...viewPrefs, ...stored};
  } catch {}
  for (const [key, values] of Object.entries({
    clipMode: ['roof', 'player', 'full', 'manual'],
    colors: ['semantic', 'gray'],
    quality: ['low', 'balanced', 'high'],
  })) {
    if (!values.includes(viewPrefs[key])) viewPrefs[key] = values[0];
  }
  const saveViewPrefs = () => {
    try { localStorage.setItem('arena-view-v1', JSON.stringify(viewPrefs)); } catch {}
  };

  let busyState = false, fixedPosition = null, mapAutoVantage = null, autoVantageReq = 0, pickingStanding = false, standingPending = false, standingRequest = 0, navPicker = null, pointerStart = null, regionBeforeFixed = null;
  const $ = id => host.querySelector('[id="arena-' + id + '"]');
  const format = t => {
    const n = Math.round(t * 10);
    return Math.floor(n / 600).toString().padStart(2, '0') + ':' + ((n % 600) / 10).toFixed(1).padStart(4, '0');
  };

  const narrowLayout = matchMedia('(max-width: 850px)');
  $('sceneParameters').open = !narrowLayout.matches;
  narrowLayout.addEventListener('change', event => { $('sceneParameters').open = !event.matches; });

  let raw, result, playing = false, time = 0, follow = false, loaded = false, last = performance.now(), frames = 0, frameStart = last;
  let actorById = new Map(), snapshotCacheIdx = -1, snapshotCacheMap = new Map(), compMaxPool = 250, wfMaxOverguard = 1500;

  const viewer = $('viewer');
  const avatarCanvas = $('avatarOverlay');
  const avatarCtx = avatarCanvas.getContext('2d');
  let overlayW = 0, overlayH = 0, overlayDpr = 1, avatarDirty = true;
  const avatarVp = new THREE.Matrix4(), prevAvatarVp = new THREE.Matrix4();

  const scene = new THREE.Scene();
  const renderer = new THREE.WebGLRenderer({antialias: true, alpha: false});
  renderer.setPixelRatio(Math.min(devicePixelRatio, viewPrefs.quality === 'high' ? 2 : viewPrefs.quality === 'low' ? 1 : 1.5));
  renderer.localClippingEnabled = true;
  viewer.prepend(renderer.domElement);
  renderer.info.autoReset = false;

  const camera = new THREE.PerspectiveCamera(43, 1, .1, 1500);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = .08;
  controls.minDistance = 10;
  controls.maxDistance = 600;

  const sky = new THREE.HemisphereLight(0xcde5ff, 0x4b5669, .9);
  const sun = new THREE.DirectionalLight(0xffffff, 1.25);
  sun.position.set(60, 150, 90);
  sky.layers.enable(lensLayer);
  sun.layers.enable(lensLayer);
  scene.add(sky, sun);

  let detailedGroup = null, clipMode = viewPrefs.clipMode, walkCeiling = 20, materialRows = [], renderCost = 0, renderedFrames = 0, lastRender = 0, clipStatusHeight = null;
  const plane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 20);
  const mapGroup = new THREE.Group();
  scene.add(mapGroup);

  const grid = new THREE.GridHelper(230, 23, 0xffffff, 0xb8c7d6);
  grid.position.y = -21;
  grid.material.transparent = true;
  grid.material.opacity = .28;
  scene.add(grid);

  const clearView = createClearView(renderer, scene, camera);
  function clearing() { return viewPrefs.clearView !== false && clipMode !== 'full'; }
  function syncScenery() {
    const available = Boolean(detailedGroup?.visible) && clipMode !== 'full', enabled = available && clearing();
    $('clearView').checked = enabled;
    $('clearView').disabled = !available;
    $('lensRadius').disabled = !enabled;
    clipStatusHeight = null;
    syncClip();
  }

  const player = new THREE.Mesh(
    new THREE.CapsuleGeometry(.55, 1.1, 4, 8),
    new THREE.MeshBasicMaterial({color: 0x38c6e9, depthTest: true, depthWrite: true}),
  );
  player.renderOrder = 8;
  player.visible = false;
  scene.add(player);

  const companionBody = new THREE.Mesh(
    new THREE.OctahedronGeometry(.42, 1),
    new THREE.MeshBasicMaterial({color: 0x68d4aa, depthTest: true, depthWrite: true}),
  );
  companionBody.renderOrder = 8;
  companionBody.visible = false;
  scene.add(companionBody);

  // GPU GreaterDepth shows the ring only where map geometry occludes the player.
  const occludedRing = new THREE.Mesh(
    new THREE.RingGeometry(.76, 1, 32),
    new THREE.MeshBasicMaterial({
      color: 0x72e8ff,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: .95,
      depthTest: true,
      depthFunc: THREE.GreaterDepth,
      depthWrite: false,
    }),
  );
  occludedRing.renderOrder = 12;
  occludedRing.frustumCulled = false;
  occludedRing.visible = false;
  scene.add(occludedRing);
  const markerView = new THREE.Vector3();

  const bodyGeometry = new THREE.CapsuleGeometry(.44, .9, 3, 6);
  const bodyMaterial = new THREE.MeshBasicMaterial({color: 0xffffff, depthTest: true, depthWrite: true});
  let bodies = new THREE.InstancedMesh(bodyGeometry, bodyMaterial, 256);
  bodies.count = 0;
  bodies.frustumCulled = false;
  bodies.renderOrder = 7;
  scene.add(bodies);

  const droneGeometry = new THREE.OctahedronGeometry(.7);
  const droneMaterial = new THREE.MeshBasicMaterial({color: 0xefca60, depthTest: true, depthWrite: true});
  let drones = new THREE.InstancedMesh(droneGeometry, droneMaterial, 256);
  drones.count = 0;
  drones.frustumCulled = false;
  drones.renderOrder = 8;
  scene.add(drones);

  const droneAuraGeometry = new THREE.RingGeometry(9.82, 10.0, 48);
  droneAuraGeometry.rotateX(-Math.PI / 2);
  const droneAuraMaterial = new THREE.MeshBasicMaterial({
    color: 0xefca60,
    side: THREE.DoubleSide,
    transparent: true,
    opacity: .6,
    depthTest: true,
    depthWrite: false,
  });
  let droneAuras = new THREE.InstancedMesh(droneAuraGeometry, droneAuraMaterial, 256);
  droneAuras.count = 0;
  droneAuras.frustumCulled = false;
  droneAuras.renderOrder = 5;
  scene.add(droneAuras);

  function ensureBodiesCapacity(needed) {
    if (needed <= bodies.instanceMatrix.count) return;
    const cap = Math.max(256, 1 << Math.ceil(Math.log2(needed + 1)));
    scene.remove(bodies);
    bodies.dispose();
    bodies = new THREE.InstancedMesh(bodyGeometry, bodyMaterial, cap);
    bodies.count = 0;
    bodies.frustumCulled = false;
    bodies.renderOrder = 7;
    scene.add(bodies);
  }

  function ensureDronesCapacity(needed) {
    if (needed <= drones.instanceMatrix.count) return;
    const cap = Math.max(256, 1 << Math.ceil(Math.log2(needed + 1)));
    scene.remove(drones);
    scene.remove(droneAuras);
    drones.dispose();
    droneAuras.dispose();
    drones = new THREE.InstancedMesh(droneGeometry, droneMaterial, cap);
    drones.count = 0;
    drones.frustumCulled = false;
    drones.renderOrder = 8;
    droneAuras = new THREE.InstancedMesh(droneAuraGeometry, droneAuraMaterial, cap);
    droneAuras.count = 0;
    droneAuras.frustumCulled = false;
    droneAuras.renderOrder = 5;
    scene.add(drones, droneAuras);
  }

  const fieldGroup = new THREE.Group();
  scene.add(fieldGroup);
  const fieldMeshes = new Map();

  // Warframe 3D Ground Ability Range Circles + Expanding Nuke Shockwaves
  const abilityRangeGroup = new THREE.Group();
  abilityRangeGroup.renderOrder = 5;
  scene.add(abilityRangeGroup);
  const abilityRangeMeshes = new Map();

  const nukePulseGroup = new THREE.Group();
  nukePulseGroup.renderOrder = 6;
  scene.add(nukePulseGroup);
  const nukePulsePool = [];
  let previewAbilityRanges = [];
  let previewNukeIgnoresLoS = null;
  let previewNukeData = null;
  let previewRangeReq = 0;

  function syncArenaNukeControls() {
    const isNuke = ($('combatStyle')?.value || 'weapon_only') !== 'weapon_only';
    const wrap = $('nukeSetupWrap');
    const sel = $('nukeSetup');
    const guide = $('arena-nukeGuide') || $('nukeGuide');
    const setups = Array.isArray(previewNukeData?.availableSetups) ? previewNukeData.availableSetups : [];

    if (wrap && sel) {
      wrap.hidden = !isNuke || !setups.length;
      if (setups.length) {
        const want = previewNukeData?.selectedSetupId || previewNukeData?.setupId || loadout?.warframeLink?.nukeSetupId || '';
        sel.replaceChildren();
        for (const r of setups) {
          const o = document.createElement('option');
          o.value = r.setupId;
          o.disabled = r.available === false;
          o.textContent = (r.labelZh || r.setupId) + (r.available === false ? ' - ' + (r.unavailableReasonZh || '不可用') : '');
          sel.append(o);
        }
        if (want && [...sel.options].some(o => o.value === want && !o.disabled)) {
          sel.value = want;
        }
      }
    }

    if (!guide) return;
    guide.replaceChildren();
    if (!isNuke) {
      guide.hidden = true;
      return;
    }
    guide.hidden = false;
    if (!loadout?.warframeLink?.enabled) {
      const w = document.createElement('span');
      w.className = 'is-warn';
      w.textContent = '⚠ 请先返回配装页在「协同配装中枢」启用战甲参与计算，或从战甲工坊地图炮面板一键跳转。';
      guide.append(w);
      return;
    }
    if (!previewNukeData) {
      guide.textContent = '正在读取当前战甲的地图炮流派与范围参数…';
      return;
    }
    if (!previewNukeData.supported) {
      const w = document.createElement('span');
      w.className = 'is-warn';
      w.textContent = '⚠ ' + (previewNukeData.notesZh || '当前战甲未匹配可用地图炮流派。');
      guide.append(w);
      return;
    }
    const titleEl = document.createElement('b');
    titleEl.textContent = '当前路线：' + (previewNukeData.titleZh || previewNukeData.setupId);
    const seqEl = document.createElement('span');
    seqEl.textContent = '实战分工：' + (previewNukeData.comboSequenceZh || '');
    const radEl = document.createElement('span');
    radEl.textContent = '分段半径：' + (previewNukeData.radiusSummaryZh || (Number(previewNukeData.primaryRadiusM || 0).toFixed(1) + 'm'));
    guide.append(titleEl, seqEl, radEl);
    for (const chk of previewNukeData.buildChecks || []) {
      if (chk.status === 'warn' || chk.status === 'ok') {
        const line = document.createElement('span');
        line.className = chk.status === 'warn' ? 'is-warn' : 'is-ok';
        line.textContent = (chk.status === 'warn' ? '⚠ ' : '✓ ') + chk.textZh;
        guide.append(line);
      }
    }
  }

  function currentSetupUsesLoS() {
    const cs = $('combatStyle')?.value || 'weapon_only';
    if (cs === 'weapon_only') return true;
    return previewNukeIgnoresLoS === false;
  }

  function slotRingColorHex(slot, light) {
    const idx = Number(slot) || 4;
    if (idx === 1) return light ? 0x0284c7 : 0x38bdf8;
    if (idx === 2) return light ? 0x059669 : 0x34d399;
    if (idx === 3) return light ? 0xd97706 : 0xfbbf24;
    return light ? 0xdb2777 : 0xf472b6;
  }
  function slotRingCss(slot, light) {
    const idx = Number(slot) || 4;
    if (idx === 1) return light ? '#0284c7' : '#38bdf8';
    if (idx === 2) return light ? '#059669' : '#34d399';
    if (idx === 3) return light ? '#d97706' : '#fbbf24';
    return light ? '#db2777' : '#f472b6';
  }

  function currentActiveRanges() {
    if (result) return result.visuals?.warframe?.abilityRanges || [];
    return previewAbilityRanges || [];
  }

  function syncAbilityRangeRings(anchorPos) {
    const ranges = viewPrefs.abilityRanges !== false && anchorPos ? currentActiveRanges() : [];
    if ($('legendRanges')) $('legendRanges').hidden = !ranges.length;
    for (const [, m] of abilityRangeMeshes) m.visible = false;
    if (!ranges.length || !anchorPos) return;
    for (const r of ranges) {
      const rad = Number(r.moddedRadiusM || 0);
      if (!(rad > 0.5)) continue;
      const key = `${r.slot}:${r.id || r.nameEn || r.slot}`;
      let mesh = abilityRangeMeshes.get(key);
      if (!mesh) {
        const geom = new THREE.RingGeometry(0.985, 1.0, 72);
        geom.rotateX(-Math.PI / 2);
        const mat = new THREE.MeshBasicMaterial({
          color: slotRingColorHex(r.slot, isLightTheme),
          side: THREE.DoubleSide,
          transparent: true,
          opacity: isLightTheme ? 0.62 : 0.52,
          depthTest: true,
          depthWrite: false,
        });
        mesh = new THREE.Mesh(geom, mat);
        mesh.frustumCulled = false;
        mesh.renderOrder = 5;
        mesh.userData.slot = r.slot;
        abilityRangeMeshes.set(key, mesh);
        abilityRangeGroup.add(mesh);
      }
      mesh.material.color.setHex(slotRingColorHex(r.slot, isLightTheme));
      mesh.material.opacity = isLightTheme ? 0.62 : 0.52;
      mesh.position.set(anchorPos[0], anchorPos[1] + 0.10 + (Number(r.slot) || 1) * 0.015, anchorPos[2]);
      mesh.scale.setScalar(rad);
      mesh.visible = true;
    }
  }

  function paintNukePulses(t) {
    for (const m of nukePulsePool) m.visible = false;
    if (!result) return;
    const pulses = result.visuals?.warframe?.nukePulses || [];
    if (!pulses.length) return;
    let used = 0;
    for (const p of pulses) {
      const pt = p[0], dur = Math.max(0.25, p[6] || 0.65);
      if (pt > t) break;
      if (t - pt > dur) continue;
      const progress = (t - pt) / dur;
      const eased = 1 - Math.pow(1 - progress, 2.2);
      const rad = Math.max(0.5, (p[5] || 15) * (0.18 + 0.82 * eased));
      let mesh = nukePulsePool[used];
      if (!mesh) {
        const geom = new THREE.RingGeometry(0.94, 1.0, 64);
        geom.rotateX(-Math.PI / 2);
        const mat = new THREE.MeshBasicMaterial({
          color: 0xf472b6,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.6,
          depthTest: true,
          depthWrite: false,
        });
        mesh = new THREE.Mesh(geom, mat);
        mesh.frustumCulled = false;
        mesh.renderOrder = 6;
        nukePulsePool.push(mesh);
        nukePulseGroup.add(mesh);
      }
      mesh.material.color.setHex(slotRingColorHex(p[4], isLightTheme));
      mesh.material.opacity = Math.max(0.04, (1 - progress) * (isLightTheme ? 0.78 : 0.70));
      mesh.position.set(p[1], p[2] + 0.18, p[3]);
      mesh.scale.setScalar(rad);
      mesh.visible = true;
      used += 1;
      if (used >= 12) break;
    }
  }

  async function refreshPreviewWarframeRanges() {
    const wfLink = loadout?.warframeLink;
    if (!wfLink?.enabled || !wfLink.frameId) {
      previewAbilityRanges = [];
      previewNukeIgnoresLoS = null;
      previewNukeData = null;
      if ($('arbucepWrap')) $('arbucepWrap').hidden = true;
      syncArenaNukeControls();
      if (!result && player.visible) syncPreviewActors();
      return;
    }
    const reqId = ++previewRangeReq;
    const desiredSetupId = $('nukeSetup')?.value || wfLink.nukeSetupId || wfLink.config?.nukeSetupId || null;
    try {
      const calcRes = await json('/api/warframe/calculate', {
        frameId: wfLink.frameId,
        ...(wfLink.config || {}),
        ...(wfLink.parentConfig ? {parentConfig: wfLink.parentConfig} : {}),
        nukeSetupId: desiredSetupId,
        arbucepEmpowered: Boolean($('arbucepEmpowered')?.checked ?? wfLink.arbucepEmpowered),
        externalBuffs: loadout?.externalBuffs || [],
        operatorLink: loadout?.operatorLink || undefined,
      });
      if (reqId !== previewRangeReq) return;
      previewAbilityRanges = Array.isArray(calcRes?.abilityRanges) ? calcRes.abilityRanges : [];
      previewNukeData = calcRes?.defenseNuke || null;
      previewNukeIgnoresLoS = typeof calcRes?.defenseNuke?.ignoresLoS === 'boolean' ? calcRes.defenseNuke.ignoresLoS : null;
      if (previewNukeData?.setupId && loadout?.warframeLink) {
        loadout.warframeLink.nukeSetupId = previewNukeData.setupId;
      }
      const hasBb = Boolean(
        String(wfLink.nameEn || wfLink.frameId || '').toLowerCase().includes('nokko')
        || (calcRes?.weaponBridge?.energyEconomy?.slotAbilities || []).some(sa => sa.id === 'brightbonnet')
      );
      if ($('arbucepWrap')) $('arbucepWrap').hidden = !hasBb;
      syncArenaNukeControls();
      syncStandingMode();
      if (!result && loaded) syncPreviewActors();
      avatarDirty = true;
    } catch {
      if (reqId === previewRangeReq) {
        previewAbilityRanges = [];
        previewNukeIgnoresLoS = null;
        previewNukeData = null;
        syncArenaNukeControls();
      }
    }
  }

  const standingMarker = new THREE.Group();
  const standingRing = new THREE.Mesh(
    new THREE.RingGeometry(.55, .78, 32),
    new THREE.MeshBasicMaterial({color: 0x73cfdf, side: THREE.DoubleSide, depthTest: false, depthWrite: false, transparent: true, opacity: .95}),
  );
  standingRing.rotation.x = -Math.PI / 2;
  standingMarker.add(standingRing);
  const standingPin = new THREE.Mesh(
    new THREE.ConeGeometry(.18, .65, 12),
    new THREE.MeshBasicMaterial({color: 0x73cfdf, depthTest: false, depthWrite: false}),
  );
  standingPin.position.y = .7;
  standingPin.rotation.z = Math.PI;
  standingMarker.add(standingPin);
  standingMarker.visible = false;
  standingMarker.renderOrder = 20;
  scene.add(standingMarker);
  const standingRay = new THREE.Raycaster(), standingPointer = new THREE.Vector2();

  const dummy = new THREE.Object3D(), color = new THREE.Color();
  const trails = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({color: 0xe16e78, transparent: true, opacity: .35, depthTest: true, depthWrite: false}));
  const playerTrail = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({color: 0x38c6e9, transparent: true, opacity: .9, depthTest: true, depthWrite: false}));
  const rays = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({color: 0xffdf8e, depthTest: true, depthWrite: false, transparent: true, opacity: .92}));
  const companionRays = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({color: 0x68d4aa, depthTest: true, depthWrite: false, transparent: true, opacity: .9}));
  const enemyRays = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({color: 0xff7b72, depthTest: true, depthWrite: false, transparent: true, opacity: .5}));
  const killMarks = new THREE.Points(new THREE.BufferGeometry(), new THREE.PointsMaterial({color: 0xc78bff, size: 1.1, depthTest: true, depthWrite: false, transparent: true}));
  const jumpTrail = new THREE.LineSegments(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({color: 0x93f2c3, transparent: true, opacity: .82, depthTest: true, depthWrite: false}));
  scene.add(trails, playerTrail, rays, companionRays, enemyRays, killMarks, jumpTrail);
  trails.renderOrder = 5;
  jumpTrail.renderOrder = 6;
  playerTrail.renderOrder = 6;
  enemyRays.renderOrder = 9;
  companionRays.renderOrder = 9;
  rays.renderOrder = 9;
  killMarks.renderOrder = 10;

  function linePositions(object, positions) {
    object.geometry.dispose();
    object.geometry = new THREE.BufferGeometry();
    object.geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  }

  let mapCenter = new THREE.Vector3(0, -7, 0), mapExtent = 180;
  function reset() {
    controls.target.copy(mapCenter);
    camera.position.copy(mapCenter).add(new THREE.Vector3(mapExtent * .72, mapExtent * .58, mapExtent * .75));
    controls.update();
    avatarDirty = true;
  }
  reset();

  let isLightTheme = false;
  let overlayTheme = {};
  let lastPaint = -1;

  function theme() {
    const style = getComputedStyle(document.documentElement);
    isLightTheme = document.documentElement.dataset.theme === 'light';
    scene.background = new THREE.Color(style.getPropertyValue('--void').trim() || (isLightTheme ? '#eef1f5' : '#090b10'));
    const accent = style.getPropertyValue('--ice').trim() || (isLightTheme ? '#1d7f95' : '#73cfdf');
    standingRing.material.color.set(accent);
    standingPin.material.color.set(accent);
    if (navPicker) navPicker.material.color.set(accent);

    player.material.color.setHex(isLightTheme ? 0x1d7f95 : 0x38c6e9);
    companionBody.material.color.setHex(isLightTheme ? 0x1f8f5f : 0x68d4aa);
    occludedRing.material.color.setHex(isLightTheme ? 0x0284c7 : 0x72e8ff);
    droneMaterial.color.setHex(isLightTheme ? 0xd97706 : 0xefca60);
    droneAuraMaterial.color.setHex(isLightTheme ? 0xb45309 : 0xefca60);
    droneAuraMaterial.opacity = isLightTheme ? .72 : .6;

    rays.material.color.setHex(isLightTheme ? 0xb45309 : 0xffdf8e);
    companionRays.material.color.setHex(isLightTheme ? 0x0f766e : 0x68d4aa);
    enemyRays.material.color.setHex(isLightTheme ? 0xdc2626 : 0xff7b72);
    enemyRays.material.opacity = isLightTheme ? .58 : .5;
    playerTrail.material.color.setHex(isLightTheme ? 0x0284c7 : 0x38c6e9);
    trails.material.color.setHex(isLightTheme ? 0xbe123c : 0xe16e78);
    jumpTrail.material.color.setHex(isLightTheme ? 0x059669 : 0x93f2c3);
    killMarks.material.color.setHex(isLightTheme ? 0x7e22ce : 0xc78bff);
    grid.material.color.setHex(isLightTheme ? 0x64748b : 0x35495a);
    grid.material.opacity = isLightTheme ? .28 : .32;

    overlayTheme = {
      surface: isLightTheme ? '#f8fafc' : '#10151d',
      fallbackBg: isLightTheme ? '#e2e8f0' : '#1b2230',
      fallbackText: isLightTheme ? '#1e293b' : '#e2e8f0',
      shadow: isLightTheme ? 'rgba(15, 23, 42, 0.24)' : 'rgba(0, 0, 0, 0.56)',
      track: isLightTheme ? 'rgba(15, 23, 42, 0.15)' : 'rgba(255, 255, 255, 0.16)',
      wfRing: isLightTheme ? '#1d7f95' : '#38c6e9',
      compRing: isLightTheme ? '#1f8f5f' : '#68d4aa',
      droneRing: isLightTheme ? '#d97706' : '#efca60',
      bossRing: isLightTheme ? '#8b4fc4' : '#c78bff',
      eximusRing: isLightTheme ? '#d97706' : '#f59e42',
      normalRing: isLightTheme ? '#c33a50' : '#e26e77',
      hpGood: isLightTheme ? '#16a34a' : '#68d4aa',
      hpLow: isLightTheme ? '#dc2626' : '#ef7183',
      shieldArc: isLightTheme ? '#0284c7' : '#38c6e9',
      overshieldArc: isLightTheme ? '#7c3aed' : '#c78bff',
      overguardArc: isLightTheme ? '#d97706' : '#f59e0b',
      pillBg: isLightTheme ? 'rgba(255, 255, 255, 0.95)' : 'rgba(15, 20, 28, 0.92)',
      pillBorder: isLightTheme ? '#94a3b8' : '#475569',
      pillText: isLightTheme ? '#0f172a' : '#f8fafc',
      buffBg: isLightTheme ? '#b45309' : '#f3d27a',
      buffText: isLightTheme ? '#ffffff' : '#1b1404',
      pinHalo: isLightTheme ? 'rgba(29, 127, 149, 0.35)' : 'rgba(115, 207, 223, 0.42)',
    };

    lastPaint = -1;
    avatarDirty = true;
  }
  theme();
  new MutationObserver(theme).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme']});

  // Lazy-loaded HTMLImageElement cache for 2D circular map avatars
  const avatarImageCache = new Map();
  function getAvatarImage(url) {
    if (!url) return null;
    let entry = avatarImageCache.get(url);
    if (entry) return entry.status === 'loaded' ? entry.img : null;
    const img = new Image();
    entry = {img, status: 'loading'};
    avatarImageCache.set(url, entry);
    img.onload = () => {
      entry.status = 'loaded';
      lastPaint = -1;
      avatarDirty = true;
    };
    img.onerror = () => {
      entry.status = 'error';
      avatarDirty = true;
    };
    img.src = url;
    return null;
  }

  function syncOverlaySize() {
    const w = viewer.clientWidth, h = viewer.clientHeight;
    if (!w || !h) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    if (w !== overlayW || h !== overlayH || dpr !== overlayDpr) {
      overlayW = w;
      overlayH = h;
      overlayDpr = dpr;
      avatarCanvas.width = Math.round(w * dpr);
      avatarCanvas.height = Math.round(h * dpr);
      avatarDirty = true;
    }
  }

  // Actor Inspector Card DOM skeleton (zero re-mount churn during 60fps playback)
  const actorCard = $('actorCard');
  const cardAvatarBox = document.createElement('div');
  cardAvatarBox.className = 'arena-actor-avatar';
  const cardAvatarImg = document.createElement('img');
  cardAvatarImg.alt = '';
  cardAvatarImg.hidden = true;
  const cardAvatarFallback = document.createElement('span');
  cardAvatarImg.addEventListener('error', () => {
    cardAvatarImg.hidden = true;
    cardAvatarFallback.hidden = false;
  });
  cardAvatarImg.addEventListener('load', () => {
    if (cardAvatarImg.dataset.src) {
      cardAvatarImg.hidden = false;
      cardAvatarFallback.hidden = true;
    }
  });
  cardAvatarBox.append(cardAvatarImg, cardAvatarFallback);

  const cardBody = document.createElement('div');
  cardBody.className = 'arena-actor-body';
  const cardHead = document.createElement('div');
  cardHead.className = 'arena-actor-head';
  const cardName = document.createElement('strong');
  const cardLevel = document.createElement('span');
  cardLevel.className = 'arena-actor-level';
  const cardBadge = document.createElement('span');
  cardBadge.className = 'arena-actor-badge';
  const cardPin = document.createElement('span');
  cardPin.className = 'arena-actor-pin';
  cardPin.textContent = '已锁定';
  cardPin.hidden = true;
  cardHead.append(cardName, cardLevel, cardBadge, cardPin);
  const cardPools = document.createElement('div');
  cardPools.className = 'arena-actor-pools';
  cardBody.append(cardHead, cardPools);
  actorCard.append(cardAvatarBox, cardBody);

  let drawnAvatars = [];
  let hoveredActorKey = null, pinnedActorKey = null, avatarClickStart = null;

  function setCardPortrait(url, fallbackChar) {
    cardAvatarFallback.textContent = fallbackChar || '?';
    if (!url) {
      cardAvatarImg.dataset.src = '';
      cardAvatarImg.hidden = true;
      cardAvatarFallback.hidden = false;
      return;
    }
    if (cardAvatarImg.dataset.src !== url) {
      cardAvatarImg.dataset.src = url;
      cardAvatarImg.hidden = true;
      cardAvatarFallback.hidden = false;
      cardAvatarImg.src = url;
    } else if (cardAvatarImg.complete && cardAvatarImg.naturalWidth > 0) {
      cardAvatarImg.hidden = false;
      cardAvatarFallback.hidden = true;
    }
  }

  function topStandableHeight(data) {
    const nav = data.nav, faces = data.reachable?.faces?.length ? data.reachable.faces : nav.triangles.map((_, i) => i);
    let top = -Infinity;
    for (const face of faces) {
      const triangle = nav.triangles[face];
      if (!triangle) continue;
      const [a, b, c] = triangle.map(i => nav.vertices[i]);
      const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]], v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
      const nx = u[1] * v[2] - u[2] * v[1], ny = u[2] * v[0] - u[0] * v[2], nz = u[0] * v[1] - u[1] * v[0];
      const length = Math.hypot(nx, ny, nz);
      if (length > 1e-6 && Math.abs(ny) / length >= .55) top = Math.max(top, a[1], b[1], c[1]);
    }
    return Number.isFinite(top) ? top : data.start.position[1];
  }

  function syncClip() {
    if (!raw) return;
    const height = clipMode === 'roof'
      ? walkCeiling + 2.2
      : clipMode === 'player'
        ? player.position.y + 1.2
        : clipMode === 'full'
          ? Number($('cut').max)
          : Number($('cut').value);
    plane.constant = Math.min(Number($('cut').max), Math.max(Number($('cut').min), height));
    if (clipMode !== 'manual') $('cut').value = plane.constant;
    $('clipMode').value = clipMode;
    $('floor').textContent = clipMode === 'player' ? '最高可站层' : '当前层';
    const rounded = Math.round(plane.constant * 10) / 10;
    if (clipStatusHeight !== rounded) {
      clipStatusHeight = rounded;
      $('viewHint').textContent = clipMode === 'full'
        ? '完整外观 - 保留全部已还原的布景。按空格键可快速播放 / 暂停。'
        : (clipMode === 'roof' ? '最高可站层 ' + walkCeiling.toFixed(1) + ' m + 2.2 m 净空' : clipMode === 'player' ? '跟随战甲' : '手动剖切') + ' / 切面 Y ' + rounded.toFixed(1) + ' m。';
      avatarDirty = true;
    }
  }

  function selectClip(mode) {
    clipMode = mode;
    viewPrefs.clipMode = mode;
    if (mode === 'manual') viewPrefs.cutHeight = Number($('cut').value);
    saveViewPrefs();
    syncScenery();
  }

  function setMaterialAppearance() {
    clearView.invalidate();
    const gray = $('mapColors').value === 'gray', emissive = $('renderQuality').value !== 'low';
    for (const row of materialRows) {
      const p = row.palette;
      row.material.color.set(gray ? '#7d8890' : p?.color || row.fallback);
      row.material.roughness = gray ? .94 : (p?.roughness ?? .88);
      row.material.metalness = gray ? 0 : (p?.metalness ?? .08);
      row.material.emissive.set(!gray && emissive && p?.emissiveColor ? p.emissiveColor : '#000000');
      row.material.emissiveIntensity = !gray && emissive ? .35 : 0;
    }
  }

  $('clipMode').value = clipMode;
  $('mapColors').value = viewPrefs.colors;
  $('renderQuality').value = viewPrefs.quality;
  $('occludedMarker').checked = viewPrefs.marker !== false;
  $('showAvatars').checked = viewPrefs.avatars !== false;
  $('droneAura').checked = viewPrefs.droneAura !== false;
  if ($('showAbilityRanges')) $('showAbilityRanges').checked = viewPrefs.abilityRanges !== false;

  $('clearView').onchange = () => { viewPrefs.clearView = $('clearView').checked; saveViewPrefs(); syncScenery(); };
  $('lensRadius').value = viewPrefs.lensRadius;
  const syncRadius = () => { viewPrefs.lensRadius = $('lensRadius').valueAsNumber; $('lensRadiusValue').textContent = viewPrefs.lensRadius + '%'; };
  syncRadius();
  $('lensRadius').oninput = syncRadius;
  $('lensRadius').onchange = saveViewPrefs;
  $('clipMode').onchange = () => selectClip($('clipMode').value);
  $('mapColors').onchange = () => { viewPrefs.colors = $('mapColors').value; saveViewPrefs(); setMaterialAppearance(); };
  $('renderQuality').onchange = () => {
    viewPrefs.quality = $('renderQuality').value;
    saveViewPrefs();
    renderer.setPixelRatio(Math.min(devicePixelRatio, viewPrefs.quality === 'high' ? 2 : viewPrefs.quality === 'low' ? 1 : 1.5));
    renderer.setSize(viewer.clientWidth, viewer.clientHeight, false);
    syncOverlaySize();
    setMaterialAppearance();
  };
  $('occludedMarker').onchange = () => { viewPrefs.marker = $('occludedMarker').checked; saveViewPrefs(); };
  $('showAvatars').onchange = () => {
    viewPrefs.avatars = $('showAvatars').checked;
    saveViewPrefs();
    avatarDirty = true;
    if (!viewPrefs.avatars) {
      hoveredActorKey = null;
      pinnedActorKey = null;
      actorCard.hidden = true;
      renderer.domElement.style.cursor = '';
    }
  };
  $('droneAura').onchange = () => {
    viewPrefs.droneAura = $('droneAura').checked;
    saveViewPrefs();
    lastPaint = -1;
    paintReplay(true);
  };
  if ($('showAbilityRanges')) {
    $('showAbilityRanges').onchange = () => {
      viewPrefs.abilityRanges = $('showAbilityRanges').checked;
      saveViewPrefs();
      if (result) {
        lastPaint = -1;
        paintReplay(true);
      } else {
        syncPreviewActors();
      }
      avatarDirty = true;
    };
  }

  $('reset').onclick = reset;
  $('top').onclick = () => {
    camera.position.copy(mapCenter).add(new THREE.Vector3(0, mapExtent * 1.35, .1));
    controls.target.copy(mapCenter);
    controls.update();
    avatarDirty = true;
  };
  $('follow').onclick = () => { follow = !follow; $('follow').textContent = follow ? '停止跟随' : '跟随战甲'; };
  $('cut').oninput = () => selectClip('manual');
  $('detail').onclick = () => {
    if (!detailedGroup) return;
    detailedGroup.visible = !detailedGroup.visible;
    mapGroup.visible = !detailedGroup.visible;
    $('detail').textContent = detailedGroup.visible ? '导航代理' : '精细地图';
    syncScenery();
  };
  $('floor').onclick = () => { if (raw) selectClip(clipMode === 'player' ? 'roof' : 'player'); };

  new ResizeObserver(() => {
    const w = viewer.clientWidth, h = viewer.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    syncOverlaySize();
  }).observe(viewer);

  function upper(path, t) {
    let l = 0, r = path.length;
    while (l < r) {
      const m = (l + r) >> 1;
      if (path[m][0] <= t) l = m + 1;
      else r = m;
    }
    return l;
  }

  function position(path, t) {
    if (!path.length) return [0, 0, 0];
    const i = upper(path, t);
    if (!i) return path[0].slice(1, 4);
    if (i >= path.length) return path.at(-1).slice(1, 4);
    const a = path[i - 1], b = path[i], k = (t - a[0]) / Math.max(.00001, b[0] - a[0]);
    return [1, 2, 3].map(n => a[n] + (b[n] - a[n]) * k);
  }

  function sampleWarframeFrame(wfVis, t) {
    const framesList = wfVis?.frames;
    if (!framesList?.length) {
      return {
        hp: wfVis?.maxHealth ?? 300,
        shield: wfVis?.maxShield ?? 300,
        overshield: 0,
        overguard: 0,
        avengerActive: 0,
        adaptationMax: 0,
        energy: wfVis?.maxEnergy ?? 100,
        isCasting: 0,
      };
    }
    const i = upper(framesList, t);
    if (!i) {
      const f = framesList[0];
      return {hp: f[1], shield: f[2], overshield: f[3], overguard: f[4], avengerActive: f[5], adaptationMax: f[6], energy: f[7] ?? 0, isCasting: f[8] ?? 0};
    }
    if (i >= framesList.length) {
      const f = framesList.at(-1);
      return {hp: f[1], shield: f[2], overshield: f[3], overguard: f[4], avengerActive: f[5], adaptationMax: f[6], energy: f[7] ?? 0, isCasting: f[8] ?? 0};
    }
    const a = framesList[i - 1], b = framesList[i];
    const k = (t - a[0]) / Math.max(.00001, b[0] - a[0]);
    return {
      hp: a[1] + (b[1] - a[1]) * k,
      shield: a[2] + (b[2] - a[2]) * k,
      overshield: a[3] + (b[3] - a[3]) * k,
      overguard: a[4] + (b[4] - a[4]) * k,
      avengerActive: a[5],
      adaptationMax: a[6],
      energy: (a[7] ?? 0) + ((b[7] ?? 0) - (a[7] ?? 0)) * k,
      isCasting: a[8] ?? 0,
    };
  }

  function sampleCompanionFrame(compVis, t, fallbackPlayerPos) {
    const framesList = compVis?.frames;
    const isSentinel = compVis?.kind === 'sentinel';
    const defPos = [
      fallbackPlayerPos[0] - .75,
      fallbackPlayerPos[1] + (isSentinel ? 1.85 : 0),
      fallbackPlayerPos[2] - .65,
    ];
    if (!framesList?.length) return {pos: defPos, shield: 0, overshield: 0};
    const i = upper(framesList, t);
    if (!i) {
      const f = framesList[0];
      return {pos: [f[1], f[2], f[3]], shield: f[4] || 0, overshield: f[5] || 0};
    }
    if (i >= framesList.length) {
      const f = framesList.at(-1);
      return {pos: [f[1], f[2], f[3]], shield: f[4] || 0, overshield: f[5] || 0};
    }
    const a = framesList[i - 1], b = framesList[i];
    const k = (t - a[0]) / Math.max(.00001, b[0] - a[0]);
    return {
      pos: [a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k, a[3] + (b[3] - a[3]) * k],
      shield: (a[4] || 0) + ((b[4] || 0) - (a[4] || 0)) * k,
      overshield: (a[5] || 0) + ((b[5] || 0) - (a[5] || 0)) * k,
    };
  }

  function getSnapshotMapAt(t) {
    const snaps = result?.visuals?.actorSnapshots;
    if (!snaps?.length) return snapshotCacheMap;
    let i = upper(snaps, t);
    let bestIdx;
    if (i <= 0) bestIdx = 0;
    else if (i >= snaps.length) bestIdx = snaps.length - 1;
    else bestIdx = Math.abs(snaps[i][0] - t) < Math.abs(snaps[i - 1][0] - t) ? i : i - 1;
    if (bestIdx !== snapshotCacheIdx) {
      snapshotCacheIdx = bestIdx;
      snapshotCacheMap = new Map();
      for (const row of snaps[bestIdx][1] || []) snapshotCacheMap.set(row[0], row);
    }
    return snapshotCacheMap;
  }

  function activeLinks() {
    return {
      wfLink: loadout?.warframeLink || openMeta?.warframeLink || null,
      compLink: loadout?.companionLink || openMeta?.companionLink || null,
    };
  }

  function syncCompanionLegend() {
    const {compLink} = activeLinks();
    $('legendCompanion').hidden = !(compLink?.enabled || result?.visuals?.companion?.enabled);
  }

  function buildMiniAvatar(candidates, fallbackText, variantClass) {
    const wrap = document.createElement('span');
    wrap.className = 'arena-mini-avatar ' + variantClass;
    const fallback = document.createElement('span');
    fallback.textContent = fallbackText;
    wrap.append(fallback);
    const urls = (Array.isArray(candidates) ? candidates : [candidates]).filter(Boolean);
    if (urls.length) {
      const img = document.createElement('img');
      img.alt = '';
      img.hidden = true;
      let idx = 0;
      const tryNext = () => {
        if (idx >= urls.length) {
          img.remove();
          fallback.hidden = false;
          return;
        }
        img.src = urls[idx++];
      };
      img.addEventListener('load', () => {
        img.hidden = false;
        fallback.hidden = true;
      });
      img.addEventListener('error', tryNext);
      wrap.prepend(img);
      tryNext();
    }
    return wrap;
  }

  function renderLoadoutSnapshot() {
    const box = $('weaponInfo');
    box.replaceChildren();
    if (!loadout) return;
    const {wfLink, compLink} = activeLinks();

    const makeRow = (avatarEl, titleText, subText, copyMod = '') => {
      const row = document.createElement('div');
      row.className = 'arena-loadout-row';
      const copy = document.createElement('div');
      copy.className = 'arena-loadout-copy' + (copyMod ? ' ' + copyMod : '');
      const b = document.createElement('b');
      b.textContent = titleText;
      const small = document.createElement('small');
      small.textContent = subText;
      copy.append(b, small);
      row.append(avatarEl, copy);
      return row;
    };

    const wCandidates = [
      openMeta?.weaponAsset,
      loadout?.weaponAsset,
      ...weaponIconCandidates(loadout.weapon, openMeta?.weaponNameEn || weaponLabel),
    ];
    box.append(
      makeRow(
        buildMiniAvatar(wCandidates, '武', 'is-weapon'),
        weaponLabel || '当前远程武器',
        '已冻结槽位 / 紫卡 / 赋能 / 灵化',
      ),
    );

    const wfEnabled = Boolean(wfLink?.enabled);
    const wfPortrait = wfEnabled && wfLink?.portraitAsset
      ? wfLink.portraitAsset
      : (catalog?.defaultWarframePortrait || DEFAULT_WARFRAME_PORTRAIT);
    const wfName = wfEnabled
      ? (wfLink.nameZh || wfLink.nameEn || wfLink.frameId || 'Excalibur') + (wfLink.configName ? ' [配置 ' + wfLink.configName + ']' : '')
      : 'Excalibur';
    const wfSub = wfEnabled
      ? (wfLink?.abilityRotation?.enabled ? '参战联动 + 拟真技能循环' : '参战联动')
      : '默认中立（未参与计算）';
    box.append(
      makeRow(
        buildMiniAvatar(wfPortrait, '战', 'is-warframe'),
        wfName,
        wfSub,
        wfEnabled ? 'is-active' : '',
      ),
    );

    if (compLink?.enabled) {
      const compName = (compLink.nameZh || compLink.nameEn || compLink.companionId || '同伴')
        + (compLink.weaponNameZh ? ' + ' + compLink.weaponNameZh : compLink.weaponNameEn ? ' + ' + compLink.weaponNameEn : '')
        + (compLink.configName ? ' [配置 ' + compLink.configName + ']' : '');
      const compMode = compLink.category === 'beast' ? '生物被动' : '机械索敌';
      box.append(
        makeRow(
          buildMiniAvatar(compLink.portraitAsset, '伴', 'is-companion'),
          compName,
          compMode,
          'is-companion',
        ),
      );
    }
    const opLink = loadout?.operatorLink;
    if (opLink?.enabled) {
      const scName = String(opLink.activeSchool || 'madurai').toUpperCase();
      const modeZh = {passive: '常驻被动', cycle: '实战周期穿插', peak: '峰值爆发'}[opLink.triggerMode] || '常驻被动';
      box.append(
        makeRow(
          buildMiniAvatar('/assets/focus/Focus.png', '专', 'is-warframe'),
          '专精 ' + scName + (opLink.configName ? ' [配置 ' + opLink.configName + ']' : ''),
          modeZh + (opLink.enableTauronStrike ? ' + Tauron终极' : ''),
          'is-active',
        ),
      );
    }
    syncCompanionLegend();
  }

  function syncPreviewActors() {
    if (!loaded || result || !raw?.start?.position) return;
    const mv = $('movement').value;
    const useObjAutoVantage = mv === 'objective' && currentSetupUsesLoS() && Array.isArray(mapAutoVantage?.position);
    const point = mv === 'fixed' && fixedPosition
      ? fixedPosition.position
      : useObjAutoVantage
        ? mapAutoVantage.position
        : mv === 'objective' && raw?.defenseObjective?.position
          ? raw.defenseObjective.position
          : raw.start.position;
    player.position.fromArray(point);
    player.position.y += 1;
    player.visible = true;
    if (useObjAutoVantage) {
      standingMarker.position.fromArray(point);
      standingMarker.position.y += .04;
      standingMarker.visible = true;
    } else if (mv !== 'fixed') {
      standingMarker.visible = false;
    }
    syncAbilityRangeRings(point);
    const {compLink} = activeLinks();
    if (compLink?.enabled) {
      const beast = compLink.category === 'beast';
      companionBody.position.set(
        player.position.x - (beast ? 1.05 : .65),
        player.position.y + (beast ? -.45 : .85),
        player.position.z - (beast ? .8 : .45),
      );
      companionBody.visible = true;
    } else {
      companionBody.visible = false;
    }
    avatarDirty = true;
  }

  function paintFields(t) {
    if (!result) return;
    const states = new Map();
    for (const event of result.replay.fields || []) {
      if (event.time > t) break;
      states.set(event.id, event);
    }
    for (const [, mesh] of fieldMeshes) mesh.visible = false;
    for (const [id, event] of states) {
      if (!event.position || (event.expires != null && event.expires < t) || ['expire', 'explode', 'replace'].includes(event.kind)) continue;
      let mesh = fieldMeshes.get(id);
      if (!mesh) {
        mesh = new THREE.Mesh(
          new THREE.SphereGeometry(1, 12, 6),
          new THREE.MeshBasicMaterial({
            color: event.entityType === 'stug' ? 0xb4db7d : 0x70bec8,
            wireframe: true,
            transparent: true,
            opacity: .28,
            depthTest: true,
            depthWrite: false,
          }),
        );
        fieldMeshes.set(id, mesh);
        fieldGroup.add(mesh);
      }
      mesh.visible = true;
      let point = event.position;
      if (event.host != null) {
        const actor = actorById.get(event.host);
        if (actor && actor.birth <= t && (actor.death == null || actor.death > t)) point = position(actor.path, t);
      }
      mesh.position.fromArray(point);
      mesh.scale.setScalar(Math.max(.2, event.radius || .4));
    }
  }

  function paintReplay(force = false) {
    if (!loaded || !result || (!force && time === lastPaint) || (!force && time !== 0 && time !== result.stats.seconds && Math.abs(time - lastPaint) < .03)) return;
    lastPaint = time;
    avatarDirty = true;
    const r = result.replay, pp = position(r.player, time);
    const motion = (r.moves || []).findLast(move => move.start <= time && time < move.start + move.duration);
    player.position.set(pp[0], pp[1] + 1, pp[2]);
    player.visible = true;

    const compVis = result.visuals?.companion;
    if (compVis?.enabled) {
      const compSample = sampleCompanionFrame(compVis, time, pp);
      const cy = compVis.kind === 'sentinel' ? compSample.pos[1] : compSample.pos[1] + .55;
      companionBody.position.set(compSample.pos[0], cy, compSample.pos[2]);
      companionBody.visible = true;
    } else {
      companionBody.visible = false;
    }

    if (follow) {
      const delta = new THREE.Vector3(pp[0], pp[1] + 1, pp[2]).sub(controls.target);
      controls.target.add(delta);
      camera.position.add(delta);
    }

    let liveBodies = 0, liveDrones = 0;
    for (const a of r.actors) {
      if (a.birth > time || (a.death != null && a.death <= time)) continue;
      if (a.type === 'drone') liveDrones++;
      else liveBodies++;
    }
    ensureBodiesCapacity(liveBodies);
    ensureDronesCapacity(liveDrones);

    let bi = 0, di = 0, ai = 0;
    const trail = [];
    const showAura = viewPrefs.droneAura !== false;
    for (const a of r.actors) {
      if (a.birth > time || (a.death != null && a.death <= time)) continue;
      const p = position(a.path, time);
      if (a.type === 'drone') {
        dummy.position.set(p[0], p[1] + .95, p[2]);
        dummy.updateMatrix();
        drones.setMatrixAt(di++, dummy.matrix);
        if (showAura) {
          dummy.position.set(p[0], p[1] + .08, p[2]);
          dummy.updateMatrix();
          droneAuras.setMatrixAt(ai++, dummy.matrix);
        }
      } else {
        dummy.position.set(p[0], p[1] + .95, p[2]);
        dummy.updateMatrix();
        bodies.setMatrixAt(bi, dummy.matrix);
        const hex = a.boss
          ? (isLightTheme ? 0x9333ea : 0xc78bff)
          : a.eximus
            ? (isLightTheme ? 0xd97706 : 0xf59e42)
            : (isLightTheme ? 0xdc2626 : 0xe26e77);
        color.setHex(hex);
        bodies.setColorAt(bi++, color);
      }
      const from = upper(a.path, time - 6), to = upper(a.path, time);
      for (let j = Math.max(1, from); j < to; j++) trail.push(...a.path[j - 1].slice(1, 4), ...a.path[j].slice(1, 4));
    }
    bodies.count = bi;
    drones.count = di;
    droneAuras.count = ai;
    bodies.instanceMatrix.needsUpdate = true;
    drones.instanceMatrix.needsUpdate = true;
    droneAuras.instanceMatrix.needsUpdate = true;
    if (bodies.instanceColor) bodies.instanceColor.needsUpdate = true;

    linePositions(trails, trail);
    const end = upper(r.player, time);
    linePositions(playerTrail, r.player.slice(0, end).flatMap(p => [p[1], p[2] + .15, p[3]]));

    const shotPositions = [];
    for (const s of r.shots) {
      if (s[0] > time) break;
      if (time - s[0] > .8) continue;
      shotPositions.push(...s.slice(1, 7));
    }
    linePositions(rays, shotPositions);

    const compShotPositions = [];
    for (const s of compVis?.shots || []) {
      if (s[0] > time) break;
      if (time - s[0] > .6) continue;
      compShotPositions.push(...s.slice(1, 7));
    }
    linePositions(companionRays, compShotPositions);

    const enemyShotPositions = [];
    for (const s of result.visuals?.enemyShots || []) {
      if (s[0] > time) break;
      if (time - s[0] > .5) continue;
      enemyShotPositions.push(...s.slice(1, 7));
    }
    linePositions(enemyRays, enemyShotPositions);

    linePositions(killMarks, r.kills.filter(k => k[0] <= time && time - k[0] < 8).flatMap(k => [k[2], k[3] + .7, k[4]]));

    const air = [];
    for (const m of r.moves || []) {
      if (m.start > time || time - m.start > 30 || m.kind === 'walk' || m.kind === 'step') continue;
      for (let i = 1; i < m.points.length; i++) air.push(...m.points[i - 1], ...m.points[i]);
    }
    linePositions(jumpTrail, air);

    paintFields(time);
    syncAbilityRangeRings(pp);
    paintNukePulses(time);
    $('clock').textContent = format(time);
    $('timeline').value = time;
    const done = r.kills.filter(k => k[0] <= time).length;
    $('viewMetrics').textContent = '当前 ' + (bi + di) + ' 个目标 / '
      + (motion ? ({drop: '直接下落', 'jump-down': '跳跃下层', 'bullet-jump': '子弹跳'}[motion.kind] || '步行') : '射击或等待')
      + ' / 累计 ' + done + ' 击杀';
  }

  const projVec = new THREE.Vector3();
  function projectToOverlay(x, y, z) {
    projVec.set(x, y, z).project(camera);
    if (!Number.isFinite(projVec.z) || projVec.z < 0 || projVec.z > 1) return null;
    if (projVec.x < -1.12 || projVec.x > 1.12 || projVec.y < -1.12 || projVec.y > 1.12) return null;
    return {
      sx: (projVec.x * .5 + .5) * overlayW,
      sy: (-projVec.y * .5 + .5) * overlayH,
      ndcZ: projVec.z,
    };
  }

  function drawProgressArc(ctx, x, y, radius, ratio, strokeColor, lineWidth = 2.5, startRatio = 0) {
    const clamped = Math.max(0, Math.min(1, ratio));
    if (clamped <= .004) return;
    const a0 = -Math.PI / 2 + startRatio * Math.PI * 2;
    const a1 = a0 + clamped * Math.PI * 2;
    ctx.beginPath();
    ctx.arc(x, y, radius, a0, a1, false);
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = lineWidth;
    ctx.lineCap = 'round';
    ctx.stroke();
  }

  function drawPillBadge(ctx, cx, cy, text, bg, fg, border) {
    ctx.font = '700 9.5px "Segoe UI", "Microsoft YaHei UI", sans-serif';
    const tw = ctx.measureText(text).width;
    const pw = Math.max(13, tw + 6), ph = 13;
    const x = cx - pw / 2, y = cy - ph / 2, rad = 6.5;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, pw, ph, rad);
    else {
      ctx.moveTo(x + rad, y);
      ctx.arcTo(x + pw, y, x + pw, y + ph, rad);
      ctx.arcTo(x + pw, y + ph, x, y + ph, rad);
      ctx.arcTo(x, y + ph, x, y, rad);
      ctx.arcTo(x, y, x + pw, y, rad);
      ctx.closePath();
    }
    ctx.fillStyle = bg;
    ctx.fill();
    if (border) {
      ctx.strokeStyle = border;
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    ctx.fillStyle = fg;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, cx, cy + .5);
  }

  function drawAvatarItem(ctx, item, isFocused) {
    const {sx, sy, radius, imgUrl, fallback, ringColor} = item;
    if (isFocused) {
      ctx.beginPath();
      ctx.arc(sx, sy, radius + 5.5, 0, Math.PI * 2);
      ctx.fillStyle = overlayTheme.pinHalo;
      ctx.fill();
    }

    ctx.save();
    ctx.shadowColor = overlayTheme.shadow;
    ctx.shadowBlur = 6;
    ctx.shadowOffsetY = 1.5;
    ctx.beginPath();
    ctx.arc(sx, sy, radius, 0, Math.PI * 2);
    ctx.fillStyle = overlayTheme.surface;
    ctx.fill();
    ctx.restore();

    const innerR = Math.max(4, radius - 1.4);
    const img = getAvatarImage(imgUrl);
    ctx.save();
    ctx.beginPath();
    ctx.arc(sx, sy, innerR, 0, Math.PI * 2);
    ctx.clip();
    if (img && img.naturalWidth > 0 && img.naturalHeight > 0) {
      const scale = Math.max((innerR * 2) / img.naturalWidth, (innerR * 2) / img.naturalHeight);
      const dw = img.naturalWidth * scale, dh = img.naturalHeight * scale;
      ctx.drawImage(img, sx - dw / 2, sy - dh / 2, dw, dh);
    } else {
      ctx.fillStyle = overlayTheme.fallbackBg;
      ctx.fillRect(sx - innerR, sy - innerR, innerR * 2, innerR * 2);
      ctx.fillStyle = overlayTheme.fallbackText;
      ctx.font = '700 ' + Math.max(10, Math.round(radius * .82)) + 'px "Segoe UI", "Microsoft YaHei UI", sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(fallback || '?', sx, sy + .5);
    }
    ctx.restore();

    ctx.beginPath();
    ctx.arc(sx, sy, radius, 0, Math.PI * 2);
    ctx.strokeStyle = ringColor;
    ctx.lineWidth = isFocused ? 2.6 : 1.8;
    ctx.stroke();

    if (item.arcs?.length) {
      for (const arc of item.arcs) {
        if (arc.track) {
          ctx.beginPath();
          ctx.arc(sx, sy, arc.r, 0, Math.PI * 2);
          ctx.strokeStyle = overlayTheme.track;
          ctx.lineWidth = arc.w || 2.5;
          ctx.stroke();
        }
        drawProgressArc(ctx, sx, sy, arc.r, arc.ratio, arc.color, arc.w || 2.5, arc.start || 0);
      }
    }

    if (item.statusCount > 0) {
      const label = item.statusCount >= 1 ? String(Math.round(item.statusCount)) : item.statusCount.toFixed(1);
      drawPillBadge(ctx, sx + radius * .72, sy + radius * .72, label, overlayTheme.pillBg, overlayTheme.pillText, overlayTheme.pillBorder);
    }
    if (item.buffBadge) {
      drawPillBadge(ctx, sx + radius * .74, sy - radius * .74, item.buffBadge, overlayTheme.buffBg, overlayTheme.buffText, null);
    }
  }

  function updateActorInspector() {
    const activeKey = pinnedActorKey ?? hoveredActorKey;
    if (!activeKey || pickingStanding || viewPrefs.avatars === false || !loaded) {
      actorCard.hidden = true;
      return;
    }

    let item = drawnAvatars.find(entry => entry.key === activeKey);
    if (!item && result && activeKey.startsWith('enemy:')) {
      const id = Number(activeKey.slice(6));
      const actor = actorById.get(id);
      if (actor) {
        const eInfo = enemyIndex.get(actor.enemyPath);
        const dead = actor.death != null && actor.death <= time;
        const snap = !dead ? getSnapshotMapAt(time).get(id) : null;
        const hpR = dead ? 0 : (snap ? snap[1] : 1);
        const shR = dead ? 0 : (snap ? snap[2] : 0);
        const ogR = dead ? 0 : (snap ? snap[3] : 0);
        const sc = dead ? 0 : (snap ? snap[4] : 0);
        const roleKey = actor.type === 'drone' ? 'drone' : actor.boss ? 'boss' : actor.eximus ? 'eximus' : 'normal';
        const roleText = actor.type === 'drone' ? '仲裁无人机' : actor.boss ? '首领' : actor.eximus ? '卓越者' : '普通目标';
        const parts = [dead ? '已击杀' : '生命 ' + Math.round(hpR * 100) + '%'];
        if (!dead && shR > 0) parts.push('护盾 ' + Math.round(shR * 100) + '%');
        if (!dead && ogR > 0) parts.push('超宏 ' + Math.round(ogR * 100) + '%');
        if (!dead) parts.push(actor.type === 'drone' ? '免疫异常' : '异常 ' + sc);
        item = {
          key: activeKey,
          roleKey,
          roleText,
          name: eInfo?.nameZh || actor.name || eInfo?.nameEn || '目标',
          levelText: 'Lv.' + (actor.level || result.scenario?.level || 160),
          imgUrl: result.visuals?.enemyIcons?.[actor.enemyPath] || eInfo?.imageAsset || '',
          fallback: factionInitial(eInfo, actor.enemyPath),
          poolsText: parts.join(' / '),
        };
      }
    }

    if (!item) {
      actorCard.hidden = true;
      return;
    }

    actorCard.hidden = false;
    actorCard.dataset.role = item.roleKey || 'normal';
    setCardPortrait(item.imgUrl, item.fallback);
    cardName.textContent = item.name;
    cardLevel.textContent = item.levelText || '';
    cardLevel.hidden = !item.levelText;
    cardBadge.textContent = item.roleText;
    cardPin.hidden = pinnedActorKey !== activeKey;
    cardPools.textContent = item.poolsText;
  }

  function paintAvatars() {
    syncOverlaySize();
    if (!overlayW || !overlayH) return;
    camera.updateMatrixWorld();
    camera.matrixWorldInverse.copy(camera.matrixWorld).invert();
    avatarVp.multiplyMatrices(camera.projectionMatrix, camera.matrixWorldInverse);
    const camMoved = !avatarVp.equals(prevAvatarVp);
    if (!avatarDirty && !camMoved) return;
    prevAvatarVp.copy(avatarVp);
    avatarDirty = false;

    avatarCtx.setTransform(overlayDpr, 0, 0, overlayDpr, 0, 0);
    avatarCtx.clearRect(0, 0, overlayW, overlayH);
    avatarCtx.imageSmoothingEnabled = true;
    avatarCtx.imageSmoothingQuality = 'high';
    drawnAvatars = [];

    if (viewPrefs.avatars === false || !loaded) {
      actorCard.hidden = true;
      return;
    }

    // 1. Pre-Run Map Preview
    if (!result && player.visible) {
      const {wfLink, compLink} = activeLinks();
      const wfProj = projectToOverlay(player.position.x, player.position.y + .9, player.position.z);
      let compItem = null;
      if (compLink?.enabled && companionBody.visible) {
        const cProj = projectToOverlay(companionBody.position.x, companionBody.position.y + .55, companionBody.position.z);
        if (cProj) {
          const beast = compLink.category === 'beast';
          compItem = {
            key: 'companion',
            roleKey: 'companion',
            roleText: beast ? '生物同伴 (被动)' : '机械同伴',
            name: compLink.nameZh || compLink.nameEn || compLink.companionId || '同伴',
            levelText: compLink.weaponNameZh || '',
            sx: cProj.sx,
            sy: cProj.sy,
            ndcZ: cProj.ndcZ,
            radius: 12,
            imgUrl: compLink.portraitAsset || '',
            fallback: '伴',
            ringColor: overlayTheme.compRing,
            poolsText: beast ? '生物同伴连结就绪 / 不主动攻击' : '机械同伴索敌就绪 / 点击开始后参战',
          };
        }
      }
      let wfItem = null;
      if (wfProj) {
        const wfEnabled = Boolean(wfLink?.enabled);
        const wfPortrait = wfEnabled && wfLink?.portraitAsset
          ? wfLink.portraitAsset
          : (catalog?.defaultWarframePortrait || DEFAULT_WARFRAME_PORTRAIT);
        wfItem = {
          key: 'warframe',
          roleKey: 'warframe',
          roleText: wfEnabled ? '参战战甲' : '默认战甲 (未参与计算)',
          name: wfEnabled ? (wfLink.nameZh || wfLink.nameEn || wfLink.frameId || 'Excalibur') : 'Excalibur',
          levelText: wfEnabled && wfLink?.configName ? '配置 ' + wfLink.configName : '',
          sx: wfProj.sx,
          sy: wfProj.sy,
          ndcZ: wfProj.ndcZ,
          radius: 17,
          imgUrl: wfPortrait,
          fallback: '战',
          ringColor: overlayTheme.wfRing,
          poolsText: wfEnabled
            ? (wfLink?.abilityRotation?.enabled ? '已启用战甲生存、受击赋能与拟真技能循环' : '已启用战甲生存与受击赋能联动')
            : '中立基准姿态 / 不承受伤害与受击赋能',
        };
      }
      if (wfItem && compItem) {
        const dx = compItem.sx - wfItem.sx, dy = compItem.sy - wfItem.sy;
        const d = Math.hypot(dx, dy), minSep = wfItem.radius + compItem.radius + 5;
        if (d < minSep) {
          const ux = d > .5 ? dx / d : .92, uy = d > .5 ? dy / d : -.39;
          compItem.sx = wfItem.sx + ux * minSep;
          compItem.sy = wfItem.sy + uy * minSep;
        }
      }
      if (compItem) drawnAvatars.push(compItem);
      if (wfItem) drawnAvatars.push(wfItem);
      if (viewPrefs.abilityRanges !== false) {
        const ranges = currentActiveRanges();
        ranges.forEach((rg, idx) => {
          const rad = Number(rg.moddedRadiusM || 0);
          if (!(rad > 0.5)) return;
          const ang = -0.65 + idx * 0.52;
          const rp = projectToOverlay(
            player.position.x + Math.cos(ang) * rad,
            player.position.y - 0.85,
            player.position.z + Math.sin(ang) * rad,
          );
          if (rp) {
            drawPillBadge(
              avatarCtx,
              rp.sx,
              rp.sy,
              `${rg.slot}技 ${rad.toFixed(1)}m${rg.ignoresLoS ? ' 穿墙' : ''}`,
              overlayTheme.pillBg,
              slotRingCss(rg.slot, isLightTheme),
              slotRingCss(rg.slot, isLightTheme),
            );
          }
        });
      }
      const focusKey = pinnedActorKey ?? hoveredActorKey;
      for (const entry of drawnAvatars) drawAvatarItem(avatarCtx, entry, entry.key === focusKey);
      updateActorInspector();
      return;
    }

    if (!result) return;

    // 2. Replay Mode
    const r = result.replay;
    const pp = position(r.player, time);
    const snapMap = getSnapshotMapAt(time);
    const enemies = [];

    for (const a of r.actors) {
      if (a.birth > time || (a.death != null && a.death <= time)) continue;
      const p = position(a.path, time);
      if (clipMode !== 'full' && p[1] + .35 > plane.constant) continue;
      const proj = projectToOverlay(p[0], p[1] + 1.65, p[2]);
      if (!proj) continue;
      const camDist = Math.hypot(camera.position.x - p[0], camera.position.y - (p[1] + 1), camera.position.z - p[2]);
      const scaleT = Math.max(0, Math.min(1, (95 - camDist) / 77));
      const diameter = 20 + 8 * scaleT;
      const radius = diameter * .5;
      const eInfo = enemyIndex.get(a.enemyPath);
      const snap = snapMap.get(a.id);
      const hpR = snap ? snap[1] : 1;
      const shR = snap ? snap[2] : 0;
      const ogR = snap ? snap[3] : 0;
      const statusCount = snap ? snap[4] : 0;

      const roleKey = a.type === 'drone' ? 'drone' : a.boss ? 'boss' : a.eximus ? 'eximus' : 'normal';
      const roleText = a.type === 'drone' ? '仲裁无人机' : a.boss ? '首领' : a.eximus ? '卓越者' : '普通目标';
      const ringColor = a.type === 'drone'
        ? overlayTheme.droneRing
        : a.boss
          ? overlayTheme.bossRing
          : a.eximus
            ? overlayTheme.eximusRing
            : overlayTheme.normalRing;

      const arcs = [
        {r: radius + 2.3, ratio: hpR, color: hpR > .4 ? overlayTheme.hpGood : overlayTheme.hpLow, w: 2.5, track: true},
      ];
      if (ogR > 0) {
        arcs.push({r: radius + 5.2, ratio: ogR, color: overlayTheme.overguardArc, w: 2.2, track: false});
      } else if (shR > 0) {
        arcs.push({r: radius + 5.2, ratio: shR, color: overlayTheme.shieldArc, w: 2.2, track: false});
      }

      const poolParts = ['生命 ' + Math.round(hpR * 100) + '%'];
      if (shR > 0) poolParts.push('护盾 ' + Math.round(shR * 100) + '%');
      if (ogR > 0) poolParts.push('超宏 ' + Math.round(ogR * 100) + '%');
      poolParts.push(a.type === 'drone' ? '10m 保护圈 / 免疫异常' : '异常 ' + statusCount);

      enemies.push({
        key: 'enemy:' + a.id,
        roleKey,
        roleText,
        name: eInfo?.nameZh || a.name || eInfo?.nameEn || '目标',
        levelText: 'Lv.' + (a.level || result.scenario?.level || 160),
        sx: proj.sx,
        sy: proj.sy,
        ndcZ: proj.ndcZ,
        radius,
        imgUrl: result.visuals?.enemyIcons?.[a.enemyPath] || eInfo?.imageAsset || '',
        fallback: factionInitial(eInfo, a.enemyPath),
        ringColor,
        arcs,
        statusCount,
        poolsText: poolParts.join(' / '),
      });
    }

    enemies.sort((a, b) => b.ndcZ - a.ndcZ);

    const compVis = result.visuals?.companion;
    let compItem = null;
    if (compVis?.enabled) {
      const compSample = sampleCompanionFrame(compVis, time, pp);
      const projY = compSample.pos[1] + (compVis.kind === 'sentinel' ? .55 : 1.35);
      const cProj = projectToOverlay(compSample.pos[0], projY, compSample.pos[2]);
      if (cProj) {
        const beast = compVis.category === 'beast';
        const totalSh = compSample.shield + compSample.overshield;
        const shRatio = totalSh > 0 ? Math.min(1, totalSh / Math.max(1, compMaxPool)) : 0;
        const cArcs = shRatio > 0
          ? [{
            r: 13 + 2.5,
            ratio: shRatio,
            color: compSample.overshield > 0 ? overlayTheme.overshieldArc : overlayTheme.shieldArc,
            w: 2.5,
            track: true,
          }]
          : [];
        const cPools = [];
        if (compVis.weaponNameZh) cPools.push(compVis.weaponNameZh);
        if (compSample.shield > 0 || !beast) cPools.push('护盾 ' + Math.round(compSample.shield));
        if (compSample.overshield > 0) cPools.push('过载 ' + Math.round(compSample.overshield));
        if (beast) cPools.push('被动连结');
        compItem = {
          key: 'companion',
          roleKey: 'companion',
          roleText: beast ? '生物同伴 (被动)' : '机械同伴',
          name: compVis.nameZh || compVis.nameEn || '同伴',
          levelText: beast ? '' : (compVis.engageRange ? compVis.engageRange + 'm' : ''),
          sx: cProj.sx,
          sy: cProj.sy,
          ndcZ: cProj.ndcZ,
          radius: 13,
          imgUrl: compVis.portraitAsset || '',
          fallback: '伴',
          ringColor: overlayTheme.compRing,
          arcs: cArcs,
          poolsText: cPools.join(' / ') || '参战同伴',
        };
      }
    }

    const wfVis = result.visuals?.warframe;
    let wfItem = null;
    const wfProj = projectToOverlay(pp[0], pp[1] + 1.85, pp[2]);
    if (wfProj) {
      const wfEnabled = Boolean(wfVis?.enabled);
      const wfPortrait = wfVis?.portraitAsset || catalog?.defaultWarframePortrait || DEFAULT_WARFRAME_PORTRAIT;
      const wfArcs = [];
      let wfBuffBadge = '';
      let wfPoolsText = '中立基准姿态 / 不承受伤害与受击赋能';
      if (wfEnabled) {
        const wfSample = sampleWarframeFrame(wfVis, time);
        const maxHp = Math.max(1, wfVis.maxHealth || 300);
        const hpRatio = Math.max(0, Math.min(1, wfSample.hp / maxHp));
        wfArcs.push({
          r: 17 + 2.6,
          ratio: hpRatio,
          color: hpRatio > .38 ? overlayTheme.hpGood : overlayTheme.hpLow,
          w: 2.5,
          track: true,
        });
        if (wfSample.overguard > 0) {
          const ogRatio = Math.min(1, wfSample.overguard / Math.max(1, wfMaxOverguard));
          wfArcs.push({r: 17 + 5.6, ratio: ogRatio, color: overlayTheme.overguardArc, w: 2.5, track: true});
        } else if ((wfVis.maxShield || 0) > 0 || wfSample.overshield > 0) {
          const maxSh = Math.max(1, wfVis.maxShield || 300);
          const shRatio = Math.min(1, wfSample.shield / maxSh);
          wfArcs.push({r: 17 + 5.6, ratio: shRatio, color: overlayTheme.shieldArc, w: 2.5, track: true});
          if (wfSample.overshield > 0) {
            const osRatio = Math.min(1, wfSample.overshield / Math.max(1, wfVis.maxOvershield || 1200));
            wfArcs.push({r: 17 + 5.6, ratio: osRatio, color: overlayTheme.overshieldArc, w: 2.5, track: false});
          }
        }
        if (wfSample.avengerActive) wfBuffBadge = '复';
        else if (wfVis.abilityRotationEnabled && wfSample.isCasting) wfBuffBadge = '施';
        const parts = ['生命 ' + Math.round(wfSample.hp) + '/' + Math.round(maxHp)];
        if ((wfVis.maxShield || 0) > 0) parts.push('护盾 ' + Math.round(wfSample.shield));
        if (wfSample.overshield > 0) parts.push('过载 ' + Math.round(wfSample.overshield));
        if (wfSample.overguard > 0) parts.push('超宏 ' + Math.round(wfSample.overguard));
        if (wfVis.abilityRotationEnabled) {
          parts.push('能量 ' + Math.round(wfSample.energy) + '/' + Math.round(wfVis.maxEnergy || 100));
          if (wfSample.isCasting) parts.push('施放技能中');
        }
        if (wfSample.avengerActive) parts.push('复仇者激活');
        if (wfSample.adaptationMax > 0) parts.push('适应 ' + Math.round(wfSample.adaptationMax * 100) + '%');
        wfPoolsText = parts.join(' / ');
      }
      wfItem = {
        key: 'warframe',
        roleKey: 'warframe',
        roleText: wfEnabled ? '参战战甲' : '默认战甲 (未参与计算)',
        name: wfVis?.nameZh || wfVis?.nameEn || 'Excalibur',
        levelText: wfEnabled && wfVis?.armor != null ? '护甲 ' + Math.round(wfVis.armor) : '',
        sx: wfProj.sx,
        sy: wfProj.sy,
        ndcZ: wfProj.ndcZ,
        radius: 17,
        imgUrl: wfPortrait,
        fallback: '战',
        ringColor: overlayTheme.wfRing,
        arcs: wfArcs,
        buffBadge: wfBuffBadge,
        poolsText: wfPoolsText,
      };
    }

    if (wfItem && compItem) {
      const dx = compItem.sx - wfItem.sx, dy = compItem.sy - wfItem.sy;
      const d = Math.hypot(dx, dy), minSep = wfItem.radius + compItem.radius + 5;
      if (d < minSep) {
        const ux = d > .5 ? dx / d : .92, uy = d > .5 ? dy / d : -.39;
        compItem.sx = wfItem.sx + ux * minSep;
        compItem.sy = wfItem.sy + uy * minSep;
      }
    }

    drawnAvatars = enemies;
    if (compItem) drawnAvatars.push(compItem);
    if (wfItem) drawnAvatars.push(wfItem);

    if (viewPrefs.abilityRanges !== false) {
      const ranges = currentActiveRanges();
      ranges.forEach((rg, idx) => {
        const rad = Number(rg.moddedRadiusM || 0);
        if (!(rad > 0.5)) return;
        const ang = -0.65 + idx * 0.52;
        const rp = projectToOverlay(
          pp[0] + Math.cos(ang) * rad,
          pp[1] + 0.15,
          pp[2] + Math.sin(ang) * rad,
        );
        if (rp) {
          drawPillBadge(
            avatarCtx,
            rp.sx,
            rp.sy,
            `${rg.slot}技 ${rad.toFixed(1)}m`,
            overlayTheme.pillBg,
            slotRingCss(rg.slot, isLightTheme),
            slotRingCss(rg.slot, isLightTheme),
          );
        }
      });
    }

    const focusKey = pinnedActorKey ?? hoveredActorKey;
    for (const entry of drawnAvatars) drawAvatarItem(avatarCtx, entry, entry.key === focusKey);
    updateActorInspector();
  }

  function hitTestAvatar(clientX, clientY) {
    if (pickingStanding || viewPrefs.avatars === false || !drawnAvatars.length) return null;
    const rect = viewer.getBoundingClientRect();
    const mx = clientX - rect.left, my = clientY - rect.top;
    for (let i = drawnAvatars.length - 1; i >= 0; i--) {
      const item = drawnAvatars[i];
      if (Math.hypot(mx - item.sx, my - item.sy) <= item.radius + 4) return item;
    }
    return null;
  }

  renderer.domElement.addEventListener('pointermove', event => {
    if (pickingStanding || event.buttons !== 0 || viewPrefs.avatars === false) return;
    const hit = hitTestAvatar(event.clientX, event.clientY);
    const nextKey = hit ? hit.key : null;
    renderer.domElement.style.cursor = nextKey ? 'pointer' : '';
    if (nextKey !== hoveredActorKey) {
      hoveredActorKey = nextKey;
      avatarDirty = true;
      updateActorInspector();
    }
  });

  renderer.domElement.addEventListener('pointerleave', () => {
    if (hoveredActorKey !== null) {
      hoveredActorKey = null;
      avatarDirty = true;
      updateActorInspector();
    }
    if (!pickingStanding) renderer.domElement.style.cursor = '';
  });

  function disposeMapGroup(group) {
    if (!group) return;
    const geometries = new Set(), materials = new Set();
    group.traverse(object => {
      if (object.geometry) geometries.add(object.geometry);
      for (const material of (Array.isArray(object.material) ? object.material : [object.material])) {
        if (material) materials.add(material);
      }
      if (object.isInstancedMesh) object.dispose();
    });
    for (const geometry of geometries) geometry.dispose();
    for (const material of materials) material.dispose();
    group.clear();
  }

  function extendClipBounds(bounds) {
    $('cut').min = Math.min(Number($('cut').min), Math.floor(bounds.min.y - 2));
    $('cut').max = Math.max(Number($('cut').max), Math.ceil(bounds.max.y + 2));
    syncClip();
  }

  function unpackVisualMapBinary(buffer) {
    const view = new DataView(buffer);
    if (buffer.byteLength < 12 || view.getUint32(0, true) !== 0x4d564657 || view.getUint32(4, true) !== 1) {
      throw new Error('invalid visual-map binary header');
    }
    const headerLen = view.getUint32(8, true);
    const data = JSON.parse(new TextDecoder('utf-8').decode(new Uint8Array(buffer, 12, headerLen)));
    let offset = (12 + headerLen + 3) & ~3;
    for (const mesh of data.meshes) {
      const vFloats = (mesh.vertexCount || 0) * 3;
      mesh.positions = new Float32Array(buffer, offset, vFloats);
      offset += vFloats * 4;
      const iCount = mesh.indexCount || 0;
      if (mesh.indexBits === 16) {
        mesh.indices = new Uint16Array(buffer, offset, iCount);
        offset = (offset + iCount * 2 + 3) & ~3;
      } else {
        mesh.indices = new Uint32Array(buffer, offset, iCount);
        offset += iCount * 4;
      }
    }
    return data;
  }

  async function fetchVisualMap(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(response.status + ' ' + response.statusText);
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/octet-stream')) {
      return unpackVisualMapBinary(await response.arrayBuffer());
    }
    return response.json();
  }

  async function loadVisual() {
    const token = loadToken, url = visualUrl;
    try {
      const data = await fetchVisualMap(url);
      if (token !== loadToken) return;
      detailedGroup = new THREE.Group();
      scene.add(detailedGroup);
      const geometries = data.meshes.map(mesh => {
        const geometry = new THREE.BufferGeometry();
        geometry.setAttribute('position', new THREE.Float32BufferAttribute(mesh.positions, 3));
        geometry.setIndex(ArrayBuffer.isView(mesh.indices) ? new THREE.BufferAttribute(mesh.indices, 1) : mesh.indices);
        geometry.computeVertexNormals();
        mesh.groups.forEach((group, index) => geometry.addGroup(group.start, group.count, index));
        return geometry;
      });
      materialRows = data.materials.map(source => ({
        material: new THREE.MeshStandardMaterial({
          color: source.color,
          side: THREE.DoubleSide,
          roughness: .85,
          metalness: .12,
          clippingPlanes: [plane],
        }),
        fallback: source.color,
        palette: catalog.materialPalette?.materials?.[source.sourcePath.replaceAll('\\', '/')],
      }));
      const materials = materialRows.map(row => {
        row.material.onBeforeCompile = clearView.attach;
        return row.material;
      });
      setMaterialAppearance();
      const groups = new Map();
      for (const item of data.instances) {
        const key = item.meshId + ':' + JSON.stringify(item.materialOverrides);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(item);
      }
      let rendered = 0;
      const visualBounds = new THREE.Box3();
      for (const instances of groups.values()) {
        const first = instances[0], source = data.meshes[first.meshId];
        const mats = source.groups.map((group, index) => materials[first.materialOverrides?.[index] ?? group.materialId] || materials[group.materialId]);
        const mesh = new THREE.InstancedMesh(geometries[first.meshId], mats, instances.length);
        mesh.layers.enable(lensLayer);
        for (let i = 0; i < instances.length; i++) {
          const item = instances[i];
          dummy.position.fromArray(item.position);
          dummy.quaternion.fromArray(item.quaternion);
          dummy.scale.setScalar(item.scale);
          dummy.updateMatrix();
          mesh.setMatrixAt(i, dummy.matrix);
        }
        mesh.instanceMatrix.needsUpdate = true;
        mesh.computeBoundingSphere();
        mesh.computeBoundingBox();
        visualBounds.union(mesh.boundingBox);
        detailedGroup.add(mesh);
        rendered += source.indices.length / 3 * instances.length;
      }
      dummy.quaternion.identity();
      dummy.scale.setScalar(1);
      mapGroup.visible = false;
      if (!visualBounds.isEmpty()) extendClipBounds(visualBounds);
      syncScenery();
      $('detail').disabled = false;
      $('detail').textContent = '导航代理';
      const coverage = data.metadata?.visualCoverage;
      $('sceneMeta').textContent = data.instances.length.toLocaleString() + ' 个真实实例 / ' + Math.round(rendered / 10000) + ' 万面 / 轻量材质配色（无贴图）';
      if (coverage) {
        const omitted = coverage.missingMeshInstances + coverage.unsupportedRiggedMeshInstances;
        if (omitted > 0) $('sceneMeta').textContent += ' / ' + omitted + ' 个来源实例未解析';
      }
      if (!job && !result) $('status').textContent = '地图就绪；点击开始才计算。';
    } catch (error) {
      if (token !== loadToken) return;
      $('status').textContent = '导航可用；地图外观加载失败：' + error.message;
      console.error(error);
    }
  }

  const json = async (url, body) => {
    const r = await fetch(url, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    const value = await r.json();
    if (!r.ok) {
      const message = value.message || value.error?.message || value.error || '请求失败';
      const error = new Error(typeof message === 'string' ? message : JSON.stringify(message));
      error.status = r.status;
      throw error;
    }
    return value;
  };
  const option = (select, id, name) => {
    const o = document.createElement('option');
    o.value = id;
    o.textContent = name;
    select.append(o);
  };

  function diagnostics(value) {
    let items = [];
    if (Array.isArray(value)) items = value;
    else if (value) {
      for (const [key, v] of Object.entries(value)) {
        if (Array.isArray(v)) items.push(...v);
        else if (v && typeof v === 'string') items.push(key + ': ' + v);
      }
    }
    items = [...new Set(items.map(x => typeof x === 'string' ? x : JSON.stringify(x)))];
    const box = $('diagnostics');
    box.hidden = !items.length;
    box.replaceChildren();
    if (items.length) {
      const b = document.createElement('b');
      b.textContent = '模型覆盖提示 (' + items.length + ')';
      box.append(b);
      const ul = document.createElement('ul');
      for (const text of items) {
        const li = document.createElement('li');
        li.textContent = text;
        ul.append(li);
      }
      box.append(ul);
    }
  }

  function budgetSpec() {
    const val = $('budget').value;
    if (val === 'waves') return {mode: 'waves', seconds: 1800, wall: 30, label: '30 分钟'};
    if (val === 'time_3600') return {mode: 'time', seconds: 3600, wall: 75, label: '1 小时'};
    if (val === 'time_7200') return {mode: 'time', seconds: 7200, wall: 150, label: '2 小时'};
    return {mode: 'time', seconds: 1800, wall: 30, label: '30 分钟'};
  }

  function isCustomSingleEnemy() {
    return $('spawnProfile').value === 'custom' && ($('enemySpec').value || 'single') === 'single';
  }

  function defaultMissionStartLevel() {
    const profile = $('spawnProfile').value;
    const specId = $('enemySpec').value || 'single';
    const wantInterception = profile.includes('interception');
    const nodes = catalog?.missionCoverage?.nodes || [];
    const matchesSpec = m => (m.enemySpecPaths || []).some(id => (typeof id === 'string' ? id : id.id || id.path) === specId);
    const matchesMap = m => (m.mapIds || []).includes(mapId);
    const pickBest = list => {
      if (!list.length) return null;
      const typed = list.filter(m => wantInterception ? m.missionType === 'Interception' : m.missionType === 'Defense');
      const pool = typed.length ? typed : list;
      return pool.find(m => Number.isFinite(Number(m.minEnemyLevel))) || pool[0];
    };
    let node = specId !== 'single' ? pickBest(nodes.filter(m => matchesMap(m) && matchesSpec(m))) : null;
    if (!node && specId !== 'single') node = pickBest(nodes.filter(matchesSpec));
    if (!node) node = pickBest(nodes.filter(matchesMap));
    const nodeMin = Math.max(1, Number(node?.minEnemyLevel) || 30);
    const spAdd = $('steelPath')?.checked ? 100 : 0;
    if (profile === 'arbitration' || profile === 'arbitration_interception') {
      return Math.max(60, nodeMin) + spAdd;
    }
    return nodeMin + spAdd;
  }

  let lastEnemyModeKey = 'custom|single|';
  function syncMissionStartLevel(force = false) {
    if (!catalog) return;
    const customSingle = isCustomSingleEnemy();
    const spBit = $('steelPath')?.checked ? 'sp1' : 'sp0';
    const nextKey = customSingle
      ? 'custom|single|'
      : `${$('spawnProfile').value}|${$('enemySpec').value || 'single'}|${mapId || ''}|${spBit}`;
    if (!force && nextKey === lastEnemyModeKey) return;
    const wasCustomSingle = lastEnemyModeKey.startsWith('custom|single|');
    lastEnemyModeKey = nextKey;
    if (customSingle) {
      if (!wasCustomSingle || force) {
        $('level').value = loadout?.level || catalog?.defaults?.level || 160;
      }
    } else {
      $('level').value = defaultMissionStartLevel();
    }
  }

  function updateRunState() {
    const missingFixed = $('movement').value === 'fixed' && !fixedPosition;
    const nukeNeedsWf = ($('combatStyle')?.value && $('combatStyle').value !== 'weapon_only') && !loadout?.warframeLink?.enabled;
    $('run').disabled = busyState || !catalog || !loadout || !loaded || missingFixed || standingPending || nukeNeedsWf || ($('spawnProfile').value !== 'custom' && $('enemySpec').value === 'single');
    $('cancel').disabled = !job?.id || job.cancelling;
    $('map').disabled = busyState;
    $('movement').disabled = busyState;
    if ($('combatStyle')) $('combatStyle').disabled = busyState;
    if ($('nukeSetup')) $('nukeSetup').disabled = busyState;
    $('doorSight').disabled = busyState;
    for (const id of ['spawnProfile', 'squadSize', 'steelPath', 'arbucepEmpowered', 'missionDifficulty', 'missionTier', 'eximusMultiplier', 'directorHardCap', 'interceptionTowers', 'interceptionProgress', 'npcShortGap', 'strictSurvival', 'enemyShieldRecharge']) {
      if ($(id)) $(id).disabled = busyState;
    }
    $('levelGrowth').disabled = busyState || $('spawnProfile').value === 'custom';
    $('region').disabled = busyState || ['fixed', 'objective'].includes($('movement').value);
    if ($('standingAuto')) $('standingAuto').disabled = busyState || !loaded || standingPending;
    $('standingPick').disabled = busyState || !loaded || standingPending;
    $('standingClear').disabled = busyState || !fixedPosition || standingPending;
  }

  function busy(value) {
    busyState = value;
    if (value) setStandingPicking(false);
    updateRunState();
  }

  function config() {
    const wait = $('wait').value;
    const bSpec = budgetSpec();
    return {
      ...(catalog?.defaults || {}),
      map: mapId,
      mapId,
      spawnProfile: $('spawnProfile').value,
      squadSize: Number($('squadSize').value),
      directorHardCap: Number($('directorHardCap').value),
      missionDifficulty: Number($('missionDifficulty').value),
      interceptionTowers: Number($('interceptionTowers')?.value ?? 1),
      interceptionProgress: Number($('interceptionProgress').value),
      missionTier: Number($('missionTier').value),
      eximusMultiplier: Number($('eximusMultiplier').value),
      mode: bSpec.mode,
      waves: 20,
      seconds: bSpec.seconds,
      maxWave: $('spawnProfile').value.includes('interception') ? 600 : 180,
      waveWait: wait === '' ? null : Number(wait),
      seed: Number($('seed').value) || 20261116,
      enemies: Math.max(1, Math.min(128, Number($('enemies').value) || 60)),
      aliveCap: Number(catalog?.defaults?.aliveCap) || 128,
      region: $('region').value,
      enemy: selectedEnemy || $('enemy').value,
      enemySpec: $('enemySpec').value || 'single',
      levelGrowth: $('levelGrowth').checked && $('spawnProfile').value !== 'custom',
      strictSurvival: $('strictSurvival').checked,
      enemyShieldRecharge: $('enemyShieldRecharge').checked,
      tier: Number($('tier').value) || 0,
      level: Number($('level').value) || 160,
      steelPath: Boolean($('steelPath')?.checked),
      combatStyle: $('combatStyle')?.value || 'weapon_only',
      nukeSetupId: ($('combatStyle')?.value && $('combatStyle').value !== 'weapon_only')
        ? ($('nukeSetup')?.value || loadout?.warframeLink?.nukeSetupId || null)
        : null,
      arbucepEmpowered: Boolean($('arbucepEmpowered')?.checked),
      headshots: $('head').value === 'head',
      movement: $('movement').value,
      doorSight: $('doorSight').value,
      npcShortGap: $('npcShortGap').checked,
      fixedPosition: $('movement').value === 'fixed' ? structuredClone(fixedPosition) : null,
    };
  }

  function clearReplayMeshes() {
    bodies.count = 0;
    drones.count = 0;
    droneAuras.count = 0;
    for (const m of nukePulsePool) m.visible = false;
    for (const object of [trails, playerTrail, rays, companionRays, enemyRays, killMarks, jumpTrail]) linePositions(object, []);
    for (const mesh of fieldMeshes.values()) {
      mesh.geometry.dispose();
      mesh.material.dispose();
      fieldGroup.remove(mesh);
    }
    fieldMeshes.clear();
  }

  function renderWaveTicks(r) {
    const box = $('waveTicks');
    box.replaceChildren();
    const total = Number(r?.stats?.seconds || 0);
    if (!r || total <= 0) return;
    for (const w of r.replay?.waves || []) {
      const start = Number(w.start || 0);
      if (start <= 0 || start >= total) continue;
      const tick = document.createElement('i');
      tick.style.left = ((start / total) * 100).toFixed(3) + '%';
      tick.title = '第 ' + w.wave + ' 波 (' + format(start) + ')';
      box.append(tick);
    }
  }

  function makeSynergyMetric(label, value, valueClass = '', wide = false) {
    const cell = document.createElement('div');
    cell.className = 'arena-synergy-metric' + (wide ? ' is-wide' : '');
    const sp = document.createElement('span');
    sp.textContent = label;
    const val = document.createElement('b');
    if (valueClass) val.className = valueClass;
    val.textContent = value;
    cell.append(sp, val);
    return cell;
  }

  function makeSynergyAvatar(url, fallbackText) {
    const box = document.createElement('div');
    box.className = 'arena-synergy-avatar';
    const fb = document.createElement('span');
    fb.textContent = fallbackText;
    box.append(fb);
    if (url) {
      const img = document.createElement('img');
      img.alt = '';
      img.hidden = true;
      img.addEventListener('load', () => { img.hidden = false; fb.hidden = true; });
      img.addEventListener('error', () => { img.remove(); fb.hidden = false; });
      img.src = url;
      box.prepend(img);
    }
    return box;
  }

  function renderSynergyResults(r) {
    const box = $('synergyResults');
    box.replaceChildren();
    const wfStats = r?.synergy?.warframeStats;
    const compStats = r?.synergy?.companionStats;
    const nukeStats = r?.synergy?.nukeStats || r?.visuals?.warframe?.nukeSummary;
    if (!wfStats && !compStats && !nukeStats) {
      box.hidden = true;
      return;
    }
    box.hidden = false;

    const wfVis = r.visuals?.warframe;
    if (nukeStats) {
      const nukeCard = document.createElement('article');
      nukeCard.className = 'arena-synergy-card is-nuke';
      const nHead = document.createElement('header');
      nHead.className = 'arena-synergy-head';
      const nTitle = document.createElement('div');
      nTitle.className = 'arena-synergy-title';
      const nH3 = document.createElement('h3');
      nH3.textContent = '防御地图炮与枪械补刀统计';
      const nSub = document.createElement('small');
      nSub.textContent = (nukeStats.titleZh || wfVis?.nameZh || '战甲地图炮')
        + ' / '
        + (nukeStats.radiusSummaryZh || ('作用半径 ' + Number(nukeStats.primaryRadiusM || 0).toFixed(1) + 'm (' + (nukeStats.ignoresLoS ? '无视视线穿墙' : '受视野限制') + ')'));
      nTitle.append(nH3, nSub);
      const nTag = document.createElement('span');
      nTag.className = 'arena-synergy-tag is-live';
      nTag.textContent = nukeStats.combatStyle === 'ability_only' ? '纯技能清场' : '地图炮 + 枪械补刀';
      nHead.append(makeSynergyAvatar(wfVis?.portraitAsset || DEFAULT_WARFRAME_PORTRAIT, '核'), nTitle, nTag);
      nukeCard.append(nHead);

      const nGrid = document.createElement('div');
      nGrid.className = 'arena-synergy-metrics';
      const sharePct = ((Number(nukeStats.abilityKillShare || 0)) * 100).toFixed(1);
      nGrid.append(
        makeSynergyMetric('技能击杀 / 枪械补刀', (nukeStats.abilityKills ?? 0) + ' 杀 (' + sharePct + '%) / ' + (nukeStats.weaponKills ?? 0) + ' 杀', 'is-good'),
        makeSynergyMetric('连招施放 / 累计耗蓝', (nukeStats.castsExecuted ?? 0) + ' 次 / ' + fmtNum(nukeStats.energySpent, 1) + ' 蓝' + (nukeStats.innerMightFreeCasts ? ' (内在之力免耗×' + nukeStats.innerMightFreeCasts + ')' : '')),
        makeSynergyMetric('技能直伤 / 技能异常伤害', fmtNum(nukeStats.abilityDirectDamage, 1) + ' / ' + fmtNum(nukeStats.abilityDotDamage, 1)),
        makeSynergyMetric('缺蓝等待次数 / 冲击波脉冲', (nukeStats.starvedWaits ?? 0) + ' 次 / ' + (nukeStats.pulseCount ?? 0) + ' 次', (nukeStats.starvedWaits || 0) > 5 ? 'is-warn' : 'is-good'),
      );
      if (nukeStats.mainJewelsConjured != null) {
        nGrid.append(
          makeSynergyMetric(
            '镜厅主副诱敌宝石 (1+2联动 20s)',
            '主宝石 ' + (nukeStats.mainJewelsConjured ?? 0)
              + ' 颗 / 镜厅分身小宝石 ' + (nukeStats.cloneMiniJewelsConjured ?? 0)
              + ' 颗(50%伤害与范围) / 引爆 ' + (nukeStats.jewelsDetonated ?? 0) + ' 颗',
            (nukeStats.jewelsDetonated || 0) > 0 ? 'is-good' : '',
            true,
          ),
        );
      }
      if (nukeStats.legerdemainGemsConverted != null) {
        nGrid.append(
          makeSynergyMetric(
            nukeStats.hasLegerdemainAugment === false
              ? '爆炸戏法掉落转化 (集团卡检查)'
              : '爆炸戏法宝石循环 (60s跨波+掩体视线)',
            nukeStats.hasLegerdemainAugment === false
              ? '未装配［爆炸戏法］集团卡：地面掉落物不转化地雷，仅生效上方 1+2 诱敌主副宝石'
              : ('掉落 ' + (nukeStats.pickupsDropped ?? 0)
                + ' / 转化 ' + (nukeStats.legerdemainGemsConverted ?? 0)
                + ' / 刷新 ' + (nukeStats.legerdemainGemsRefreshed ?? 0)
                + ' / 引爆 ' + (nukeStats.legerdemainGemsDetonated ?? 0)),
            nukeStats.hasLegerdemainAugment === false
              ? 'is-warn'
              : ((nukeStats.legerdemainGemsDetonated || 0) > 0 ? 'is-good' : ''),
            true,
          ),
        );
      }
      if (r.stats?.vantagePoint?.autoSelected) {
        const vp = r.stats.vantagePoint;
        nGrid.append(
          makeSynergyMetric(
            '自动优选可达高台视野站位',
            '高差 +' + Number(vp.elevationGainM || 0).toFixed(2) + 'm / 无遮挡视野 '
              + (Number(vp.visibilityRatio || 0) * 100).toFixed(1) + '% (底层核心 '
              + (Number(vp.objectiveVisibilityRatio || 0) * 100).toFixed(1) + '%)',
            'is-good',
            true,
          ),
        );
      }
      nukeCard.append(nGrid);
      box.append(nukeCard);
    }
    const wfCard = document.createElement('article');
    wfCard.className = 'arena-synergy-card is-warframe';
    const wfHead = document.createElement('header');
    wfHead.className = 'arena-synergy-head';
    const wfTitle = document.createElement('div');
    wfTitle.className = 'arena-synergy-title';
    const wfH3 = document.createElement('h3');
    wfH3.textContent = wfStats?.abilityRotation?.enabled ? '战甲生存、技能循环与吸球经济' : '战甲生存与受击赋能';
    const wfSub = document.createElement('small');
    wfSub.textContent = wfStats
      ? (wfVis?.nameZh || wfVis?.nameEn || 'Excalibur') + ' / 生命 ' + Math.round(wfVis?.maxHealth || 0) + ' / 护盾 ' + Math.round(wfVis?.maxShield || 0) + ' / 护甲 ' + Math.round(wfVis?.armor || 0)
      : 'Excalibur / 默认中立姿态';
    wfTitle.append(wfH3, wfSub);
    const wfTag = document.createElement('span');
    wfTag.className = 'arena-synergy-tag' + (wfStats ? ' is-live' : '');
    wfTag.textContent = wfStats ? '参战联动' : '未启用';
    wfHead.append(makeSynergyAvatar(wfVis?.portraitAsset || DEFAULT_WARFRAME_PORTRAIT, '战'), wfTitle, wfTag);
    wfCard.append(wfHead);

    if (wfStats) {
      const gridEl = document.createElement('div');
      gridEl.className = 'arena-synergy-metrics';
      gridEl.append(
        makeSynergyMetric('总承伤', fmtNum(wfStats.damageTaken, 1)),
        makeSynergyMetric('受击 / 闪避次数', (wfStats.hitsTaken ?? 0) + ' 次 / ' + (wfStats.evadedHits ?? 0) + ' 次'),
        makeSynergyMetric('护盾破碎 / 护盾门次数', (wfStats.shieldBreaks ?? 0) + ' 次 / ' + (wfStats.shieldGatesTriggered ?? 0) + ' 次'),
      );
      const downed = Number(wfStats.downedCount || 0);
      const downedText = downed > 0
        ? downed + ' 次' + (wfStats.firstDownedAt != null ? '（首次 ' + Number(wfStats.firstDownedAt).toFixed(1) + 's / ' + (r.scenario?.strictSurvival ? '严格生存终止' : '不死基准续航') + '）' : '')
        : '0 次（全程存活）';
      gridEl.append(
        makeSynergyMetric('倒地次数', downedText, downed > 0 ? (r.scenario?.strictSurvival ? 'is-danger' : 'is-warn') : 'is-good'),
        makeSynergyMetric('复仇者覆盖率', ((wfStats.avengerUptimeRatio || 0) * 100).toFixed(1) + '%'),
        makeSynergyMetric('保卫者覆盖率', ((wfStats.guardianUptimeRatio || 0) * 100).toFixed(1) + '%'),
        makeSynergyMetric('战斗教条触发', (wfStats.combatDisciplineTriggers ?? 0) + ' 次', '', !wfStats.abilityRotation?.enabled),
      );
      if (wfStats.abilityRotation?.enabled) {
        const rot = wfStats.abilityRotation;
        const orbDetail = '蓝球 ' + (rot.energyOrbsPicked ?? 0)
          + ' / 血球 ' + (rot.healthOrbsPicked ?? 0)
          + (rot.energizeProcs ? ' / 充沛×' + rot.energizeProcs : '')
          + '（出生 ' + Math.round(rot.spawnEnergy || 0)
          + ' → 末态 ' + Math.round(rot.finalEnergy || 0)
          + '/' + Math.round(rot.maxEnergy || 0) + '）';
        gridEl.append(
          makeSynergyMetric(
            '技能循环覆盖 / 施放停火',
            ((rot.meanUptimeRatio || 0) * 100).toFixed(1) + '% / ' + Number(rot.weaponCastPauseSeconds || 0).toFixed(2) + 's',
            (rot.meanUptimeRatio || 0) >= 0.85 ? 'is-good' : 'is-warn',
          ),
          makeSynergyMetric(
            '缺蓝真空 / 施放次数',
            Number(rot.maxVacuumSeconds || 0).toFixed(2) + 's / ' + (rot.totalCasts ?? 0) + ' 次',
            (rot.maxVacuumSeconds || 0) > 0.5 ? 'is-warn' : 'is-good',
          ),
          makeSynergyMetric('全图吸球与能量状态', orbDetail, '', true),
        );
      }
      wfCard.append(gridEl);
    } else {
      const empty = document.createElement('p');
      empty.className = 'arena-synergy-empty';
      empty.textContent = '本次运行未启用战甲参战联动，Excalibur 保持中立无承伤基准。';
      wfCard.append(empty);
    }

    const compVis = r.visuals?.companion;
    const compCard = document.createElement('article');
    compCard.className = 'arena-synergy-card is-companion';
    const compHead = document.createElement('header');
    compHead.className = 'arena-synergy-head';
    const compTitle = document.createElement('div');
    compTitle.className = 'arena-synergy-title';
    const compH3 = document.createElement('h3');
    compH3.textContent = '同伴协战与异常铺垫';
    const compSub = document.createElement('small');
    const compModeLabel = !compVis
      ? '未装备同伴'
      : compVis.category === 'beast'
        ? '生物被动连结'
        : (compVis.canAttack === false || compVis.arenaActiveAttack === false)
          ? '机械被动辅助'
          : '机械主动索敌';
    compSub.textContent = compVis
      ? [compVis.nameZh || compVis.nameEn, compVis.weaponNameZh].filter(Boolean).join(' + ')
      : '未启用同伴联动';
    compTitle.append(compH3, compSub);
    const compTag = document.createElement('span');
    compTag.className = 'arena-synergy-tag' + (compStats ? ' is-live' : '');
    compTag.textContent = compStats ? compModeLabel : '未启用';
    compHead.append(makeSynergyAvatar(compVis?.portraitAsset, '伴'), compTitle, compTag);
    compCard.append(compHead);

    if (compStats) {
      const gridEl = document.createElement('div');
      gridEl.className = 'arena-synergy-metrics';
      const modeDetail = compModeLabel + (compVis?.category !== 'beast' && compVis?.engageRange ? ' (' + compVis.engageRange + 'm)' : '');
      gridEl.append(
        makeSynergyMetric('协战模式', modeDetail),
        makeSynergyMetric('开火 / 命中', (compStats.shots ?? 0) + ' 次 / ' + (compStats.hits ?? 0) + ' 次'),
        makeSynergyMetric('直伤 / 状态伤害', fmtNum(compStats.directDamage, 1) + ' / ' + fmtNum(compStats.dotDamage, 1)),
        makeSynergyMetric('同伴击杀', (compStats.kills ?? 0) + ' 杀'),
      );
      const procRows = Object.entries(compStats.procsApplied || {})
        .filter(([, v]) => Number(v) > 0)
        .sort((a, b) => b[1] - a[1]);
      const totalProcs = procRows.reduce((acc, [, v]) => acc + Number(v), 0);
      const procSummary = procRows.length
        ? '共 ' + fmtNum(totalProcs, 1) + ' 层 - ' + procRows.slice(0, 5).map(([dt, v]) => (DAMAGE_LABELS[dt] || dt) + ' ' + fmtNum(v, 1)).join(' / ')
        : '0 层（无异常施加）';
      const bondSummary = '传染扩散 ' + (compStats.contagiousSpreads ?? 0) + ' 次 / 流形减冷却 ' + (compStats.manifoldTriggers ?? 0) + ' 次 / 强固覆盖 ' + ((compStats.reinforcedUptimeRatio || 0) * 100).toFixed(1) + '% / 坚韧连结 ' + (compStats.tenaciousActive ? '已激活' : '未激活');
      gridEl.append(
        makeSynergyMetric('异常施加总数与前排元素', procSummary, '', true),
        makeSynergyMetric('连结协同统计', bondSummary, compStats.tenaciousActive ? 'is-good' : '', true),
      );
      compCard.append(gridEl);
    } else {
      const empty = document.createElement('p');
      empty.className = 'arena-synergy-empty';
      empty.textContent = '本次运行未启用同伴联动，无额外同伴索敌或连结增益。';
      compCard.append(empty);
    }

    box.append(wfCard, compCard);
  }

  function showReplay(entry) {
    currentReplay = entry || null;
    result = entry?.result || null;
    time = entry?.time || 0;
    lastPaint = -1;
    playing = false;
    hoveredActorKey = null;
    pinnedActorKey = null;
    snapshotCacheIdx = -1;
    snapshotCacheMap = new Map();
    actorById = new Map((result?.replay?.actors || []).map(a => [a.id, a]));
    const compFrames = result?.visuals?.companion?.frames || [];
    compMaxPool = Math.max(250, ...compFrames.map(f => (f[4] || 0) + (f[5] || 0)));
    const wfFrames = result?.visuals?.warframe?.frames || [];
    wfMaxOverguard = Math.max(1500, ...wfFrames.map(f => f[4] || 0));

    clearReplayMeshes();
    syncCompanionLegend();
    const r = result, s = r?.stats;
    $('timeline').max = s?.seconds || 0;
    $('timeline').value = time;
    for (const id of ['timeline', 'play', 'export']) $(id).disabled = !r;
    $('play').textContent = '播放';
    renderWaveTicks(r);

    if (!r) {
      $('clock').textContent = format(0);
      $('totalTime').textContent = '/ 00:00.0';
      $('viewMetrics').textContent = '拖动旋转 / 右键平移 / 滚轮缩放';
      for (const id of ['simTime', 'kills', 'wall', 'multi', 'jump', 'vitus']) $(id).textContent = '—';
      $('vitusDetail').textContent = '仅累计本次已模拟部分的平均期望；中止时不外推剩余波次。';
      $('resultTitle').textContent = '等待首次运行';
      $('resultText').replaceChildren();
      renderSynergyResults(null);
      $('fingerprint').textContent = '独立后端任务 / 固定 seed / 当前配装快照';
      diagnostics(catalog?.unsupported || catalog?.diagnostics);
      syncPreviewActors();
      avatarDirty = true;
      return;
    }

    $('totalTime').textContent = '/ ' + format(s.seconds || 0);
    $('simTime').textContent = format(s.seconds || 0);
    $('kills').textContent = (s.waves || 0) + ' / ' + (s.kills || 0);
    $('wall').textContent = ((s.totalElapsedMs ?? s.elapsedMs ?? 0) / 1000).toFixed(2) + ' s';
    $('multi').textContent = s.maxGroupKill ?? '—';
    $('jump').textContent = s.jumps ?? '—';
    $('vitus').textContent = fmtNum(s.vitusExpected, 2);
    $('vitusDetail').textContent = '仅本次已模拟 ' + format(s.seconds || 0) + ' 累计：无人机击杀 ' + Number(s.droneKills || 0) + ' / 掉率 ' + fmtNum(Number(s.vitusDropChance ?? .06) * 100, 2) + '% / 模拟随机掉落 ' + Number(s.vitusSample || 0) + '。平均期望不是保底；未完成部分不外推。';

    const reasonText = r.reason === 'warframe_downed' ? '战甲倒地（严格生存终止）' : (r.reason || r.status || '模拟完成');
    $('resultTitle').textContent = [r.weaponName, reasonText].filter(Boolean).join(' - ');

    const lines = [];
    lines.push(
      (s.shots || 0) + ' 次开火 / 直接伤害 ' + fmtNum(s.directDamage, 1)
      + ' / 状态伤害 ' + fmtNum(s.dotDamage, 1)
      + ' / 无人机爆炸 ' + fmtNum(s.droneExplosionDamage, 1)
      + ' / 换弹 ' + (s.reloads || 0) + ' 次 / 形态切换 ' + (s.transforms || 0) + ' 次',
    );
    lines.push(
      '路径失败 ' + (s.failedPathPlans || 0) + ' 次 / 合法避让 ' + (s.crowdDetours || 0) + ' 次 / NPC跨越 ' + (s.npcShortGaps || 0) + ' 次 / 剩余 ' + (s.live || 0) + ' 个目标（地面暂不可达 ' + (s.liveUnreachable || 0) + '）'
      + (s.confirmedDoors != null ? ' / 门口 ' + s.confirmedDoors + ' 处（通行常开，门视线' + (s.doorSight === 'closed' ? '关闭遮挡' : '开放') + '）' : ''),
    );
    const extras = [];
    if (r.scenario?.spawnProfile && r.scenario.spawnProfile !== 'custom') {
      extras.push('来源规则：已生成普通目标 ' + (s.regularSpawned || 0) + '（含卓越者 ' + (s.eximusSpawned || 0) + '）/ 独立无人机 ' + (s.dronesSpawned || 0) + '，每波配额与准入层级已写入导出回放。');
    }
    if (Number.isFinite(r.scenario?.waveWait)) extras.push('波间等待 ' + r.scenario.waveWait + ' 秒。');
    if (s.blastNeighbourDamage > 0) extras.push('状态伤害中，爆炸异常波及邻体 ' + fmtNum(s.blastNeighbourDamage, 1) + '。');
    if (extras.length) lines.push(extras.join(' '));

    const textBox = $('resultText');
    textBox.replaceChildren(...lines.map(line => {
      const p = document.createElement('p');
      p.textContent = line;
      return p;
    }));

    renderSynergyResults(r);
    $('fingerprint').textContent = '事件指纹 ' + (s.eventHash || '—') + (r.model ? ' / ' + r.model : '');
    diagnostics(r.diagnostics || r.unsupported);
    $('status').textContent = '任务已结束，可播放、拖动或导出。';
    paintReplay(true);
  }

  function accept(r, submitted) {
    const resultMap = r.scenario?.mapId || submitted.mapId;
    r.replay ??= {};
    for (const key of ['actors', 'player', 'shots', 'kills', 'waves', 'moves', 'fields']) r.replay[key] ??= [];
    const entry = {result: r, loadout: submitted.loadout, time: 0};
    replaysByMap.delete(resultMap);
    replaysByMap.set(resultMap, entry);
    if (replaysByMap.size > 2) replaysByMap.delete(replaysByMap.keys().next().value);
    if (resultMap !== mapId || !loaded) return;
    if (r.scenario?.movement === 'fixed' && r.scenario.fixedPosition) displayStandingPoint(r.scenario.fixedPosition);
    showReplay(entry);
  }

  function finishJob(submitted) {
    if (job !== submitted) return false;
    job = null;
    busy(false);
    return true;
  }

  async function poll(submitted = job) {
    if (!active || !submitted?.id || job !== submitted || submitted.polling) return;
    clearTimeout(pollTimer);
    submitted.polling = true;
    try {
      const data = await json('/api/arena/jobs?id=' + encodeURIComponent(submitted.id));
      if (job !== submitted || (data.id && data.id !== submitted.id)) return;
      if (data.result) { finishJob(submitted); accept(data.result, submitted); return; }
      if (['completed', 'failed', 'cancelled', 'limited'].includes(data.status)) {
        finishJob(submitted);
        const message = data.message || data.error;
        $('status').textContent = typeof message === 'object' ? JSON.stringify(message) : (message || data.status);
        diagnostics(data.diagnostics);
        return;
      }
      const p = data.progress || {};
      const progExtra = p.interceptionProgress != null ? ' (总占领 ' + Math.round(Number(p.interceptionProgress) * 100) + '%)' : '';
      $('status').textContent = (submitted.cancelling ? '正在取消' : '后台 ' + (data.status || 'running')) + ' / 模拟 ' + format(p.t ?? p.seconds ?? 0) + ' / 第 ' + (p.wave || 0) + (submitted && config().spawnProfile?.includes('interception') ? ' 轮' : ' 波') + progExtra;
    } catch (e) {
      if (job !== submitted) return;
      if (e.status === 404) finishJob(submitted);
      $('status').textContent = e.message;
    } finally {
      submitted.polling = false;
      if (active && job === submitted) pollTimer = setTimeout(() => poll(submitted), 500);
    }
  }

  $('run').onclick = async () => {
    if (job || $('run').disabled) return;
    const submitted = {id: null, mapId, loadout: structuredClone(loadout), polling: false, cancelling: false}, scenario = config();
    job = submitted;
    busy(true);
    playing = false;
    $('play').textContent = '播放';
    $('status').textContent = '正在创建后台任务…';
    try {
      const data = await json('/api/arena/jobs', {loadout: submitted.loadout, scenario});
      if (job !== submitted) return;
      if (!data.id) throw new Error('任务响应缺少 id');
      submitted.id = data.id;
      updateRunState();
      $('status').textContent = '任务已创建';
      poll(submitted);
    } catch (e) {
      if (finishJob(submitted)) $('status').textContent = e.message;
    }
  };

  $('cancel').onclick = async () => {
    const submitted = job;
    if (!submitted?.id || submitted.cancelling) return;
    submitted.cancelling = true;
    updateRunState();
    try {
      await json('/api/arena/cancel', {id: submitted.id});
      if (job !== submitted) return;
      $('status').textContent = '正在取消后台任务…';
      poll(submitted);
    } catch (e) {
      if (job === submitted) {
        submitted.cancelling = false;
        updateRunState();
        $('status').textContent = e.message;
      }
    }
  };

  $('back').onclick = () => host.dispatchEvent(new CustomEvent('arena-back', {bubbles: true}));
  $('play').onclick = () => {
    if (!result) return;
    if (time >= result.stats.seconds) { time = 0; paintReplay(true); }
    playing = !playing;
    $('play').textContent = playing ? '暂停' : '播放';
  };
  $('timeline').oninput = () => {
    if (!result) return;
    const value = Number($('timeline').value), end = Number($('timeline').max);
    time = end - value < Number($('timeline').step) ? end : value;
    playing = false;
    $('play').textContent = '播放';
    paintReplay(true);
  };
  $('export').onclick = () => {
    if (!currentReplay) return;
    const {loadout: snapLoadout, result: snapResult} = currentReplay;
    const url = URL.createObjectURL(new Blob([JSON.stringify({loadout: snapLoadout, result: snapResult})], {type: 'application/json'}));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'arena-replay-' + (snapResult.stats.eventHash || Date.now()) + '.json';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  window.addEventListener('keydown', event => {
    if (!active || host.hidden || pickingStanding || !result) return;
    if (event.code !== 'Space' && event.key !== ' ') return;
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target;
    if (target && target.closest?.('input, select, textarea, button, summary, [contenteditable="true"]')) return;
    event.preventDefault();
    $('play').click();
  });

  async function loadMap() {
    const token = ++loadToken;
    if (currentReplay) currentReplay.time = time;
    mapId = $('map').value;
    loaded = false;
    raw = null;
    mapAutoVantage = null;
    autoVantageReq++;
    showReplay(null);
    clearStandingPoint('地图已切换，请重新选择合法站点。');
    refreshSpecOptions();
    syncMissionStartLevel();
    updateRunState();
    clipMode = viewPrefs.clipMode;
    clipStatusHeight = null;
    materialRows = [];
    $('floor').textContent = '当前层';
    occludedRing.visible = false;
    player.visible = false;
    companionBody.visible = false;
    grid.visible = false;
    disposeMapGroup(mapGroup);
    disposeMapGroup(detailedGroup);
    if (detailedGroup) { scene.remove(detailedGroup); detailedGroup = null; }
    syncScenery();
    rebuildStandingNav();
    const map = catalog.maps.find(item => (item.id || item.mapId) === mapId) || {};
    const base = '/api/arena/assets/' + encodeURIComponent(mapId) + '/';
    visualUrl = map.visualUrl || base + 'visual-map.json';
    showMapMissions(map);
    $('sceneMeta').textContent = '正在读取地图…';
    $('status').textContent = '正在读取地图…';
    $('viewHint').textContent = '';
    $('detail').disabled = true;
    try {
      const data = await json(map.sceneUrl || base + 'scene.json');
      if (token !== loadToken) return;
      raw = data;
      walkCeiling = topStandableHeight(raw);
      const bounds = new THREE.Box3();
      for (const point of raw.collision.vertices) bounds.expandByPoint(new THREE.Vector3(...point));
      const walkBounds = new THREE.Box3();
      for (const point of raw.nav.nodePositions) walkBounds.expandByPoint(new THREE.Vector3(...point));
      walkBounds.getCenter(mapCenter);
      const size = walkBounds.getSize(new THREE.Vector3());
      mapExtent = Math.max(size.x, size.z, size.y, 30);
      $('cut').min = Math.floor(bounds.min.y - 2);
      $('cut').max = Math.ceil(bounds.max.y + 2);
      $('cut').value = clipMode === 'manual' && Number.isFinite(viewPrefs.cutHeight)
        ? Math.min(Number($('cut').max), Math.max(Number($('cut').min), Number(viewPrefs.cutHeight)))
        : $('cut').max;
      plane.constant = Number($('cut').value);
      grid.position.y = bounds.min.y - 1;
      grid.visible = true;
      reset();
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(raw.collision.vertices.flat(), 3));
      geometry.setIndex(raw.collision.triangles.flat());
      geometry.computeVertexNormals();
      mapGroup.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({
        color: 0x668b9c,
        side: THREE.DoubleSide,
        roughness: 1,
        transparent: true,
        opacity: .8,
        clippingPlanes: [plane],
      })));
      mapGroup.visible = true;
      loaded = true;
      syncPreviewActors();
      syncClip();
      rebuildStandingNav();
      syncStandingMode();
      refreshMapAutoVantage();
      updateRunState();
      $('sceneMeta').textContent = (raw.nav?.triangles?.length || 0).toLocaleString() + ' 导航面';
      const entry = replaysByMap.get(mapId);
      if (entry) showReplay(entry);
      else $('status').textContent = '导航就绪；正在读取地图外观…';
      loadVisual();
    } catch (error) {
      if (token !== loadToken) return;
      loaded = false;
      raw = null;
      player.visible = false;
      companionBody.visible = false;
      grid.visible = false;
      disposeMapGroup(mapGroup);
      rebuildStandingNav();
      setStandingPicking(false);
      updateRunState();
      $('sceneMeta').textContent = '地图未加载';
      $('status').textContent = '地图显示加载失败：' + error.message;
    }
  }

  $('map').onchange = loadMap;
  for (const id of ['region', 'budget', 'wait', 'movement', 'combatStyle', 'steelPath', 'arbucepEmpowered', 'doorSight', 'enemies', 'seed', 'head', 'enemy', 'level', 'enemySpec', 'tier', 'spawnProfile', 'squadSize', 'missionDifficulty', 'missionTier', 'eximusMultiplier', 'levelGrowth', 'strictSurvival', 'enemyShieldRecharge', 'directorHardCap', 'interceptionTowers', 'interceptionProgress', 'npcShortGap']) {
    if ($(id)) $(id).addEventListener('change', () => { if (!job) $('status').textContent = '配置已修改，点击开始才重新计算。'; });
  }
  $('budget').addEventListener('change', syncSpawnProfile);
  $('interceptionTowers')?.addEventListener('change', syncSpawnProfile);
  $('steelPath')?.addEventListener('change', () => {
    if ($('steelPath').checked && $('spawnProfile').value !== 'custom') {
      $('squadSize').value = '4';
    }
    syncMissionStartLevel();
    updateRunState();
  });
  $('combatStyle')?.addEventListener('change', () => {
    const cs = $('combatStyle').value;
    if (cs !== 'weapon_only') {
      if (!loadout?.warframeLink?.enabled) {
        $('status').textContent = '地图炮与纯技能模式需要启用战甲参与计算；请先在武器配装或战甲配装中开启战甲协同。';
      } else if ($('spawnProfile').value === 'defense' || $('spawnProfile').value === 'arbitration') {
        if ($('movement').value === 'parkour') {
          $('movement').value = 'objective';
          syncStandingMode();
        }
      }
    }
    updateRunState();
  });
  $('arbucepEmpowered')?.addEventListener('change', () => {
    refreshPreviewWarframeRanges();
  });

  function missionPlanet(mission) { return mission.planetZh || mission.planet; }
  function missionNode(mission) { return mission.nodeNameZh && mission.nodeNameZh !== mission.nodeName ? mission.nodeNameZh + ' (' + mission.nodeName + ')' : mission.nodeName; }
  function missionType(mission) { return ({'mirror-defense': '镜像防御', '1999-defense': '1999 防御', archwing: '空战拦截'}[mission.variant] || mission.missionTypeZh || mission.missionType); }
  function mapOptionLabel(map) {
    const planets = [...new Set((map.missions || []).map(missionPlanet))];
    return (planets.length ? planets.join(' / ') + ' - ' : '') + (map.nameZh || map.name || map.id);
  }

  function showMapMissions(map) {
    const missions = map.missions || [], planets = [...new Set(missions.map(missionPlanet))];
    $('mapTitle').textContent = map.nameZh || map.name || map.id;
    $('mapBrief').textContent = [planets.slice(0, 2).join(' / '), [...new Set(missions.map(missionType).filter(Boolean))].slice(0, 2).join(' / ')].filter(Boolean).join(' - ');
    const doors = map.doorSummary;
    $('doorInfo').textContent = doors ? '已确认 ' + doors.confirmedDoors + ' 处门口，其中 ' + doors.doorsWithUsableLinks + ' 处已接入通行。' : '本图尚无可确认的门口连接；不会开放普通墙体。';
    $('mapSummary').textContent = planets.length ? planets.join(' / ') : '节点对应关系待核对';
    $('mapSubtitle').textContent = missions.map(m => missionPlanet(m) + ' / ' + missionNode(m) + '（' + missionType(m) + '）').join('；');
    const box = $('mapMissions');
    box.replaceChildren();
    for (const mission of missions) {
      const card = document.createElement('div');
      card.className = 'arena-mission';
      const node = document.createElement('b');
      node.textContent = missionNode(mission);
      const detail = document.createElement('span');
      detail.textContent = missionPlanet(mission) + ' / ' + missionType(mission);
      card.append(node, detail);
      if (mission.arbitrationQualification?.status === 'officially-added') {
        const badge = document.createElement('span');
        badge.className = 'arena-official-note';
        badge.textContent = '官方曾确认加入仲裁';
        card.append(badge);
      }
      box.append(card);
    }
    const historical = missions.filter(m => m.arbitrationQualification?.status === 'officially-added');
    $('mapQualification').textContent = '这里列出关联该模板的星图节点；一个节点可能使用多个变体。' + (historical.length ? '官方更新37已确认镜像防御加入仲裁；当前轮换名单尚未核实。' : '当前仲裁轮换资格尚未核实。');
  }

  function showMapCoverage() {
    const coverage = catalog.missionCoverage, box = $('mapCoverage');
    box.replaceChildren();
    const intro = document.createElement('p');
    $('mapCoverageSummary').textContent = '已接入 ' + catalog.maps.length + ' / ' + (coverage?.summary.candidateTiles || catalog.maps.length) + ' 份候选模板 - 覆盖范围';
    if (!coverage) {
      intro.textContent = '当前模板不是防御与拦截任务的完整地图集合。';
      box.append(intro);
      return;
    }
    const summary = coverage.summary;
    intro.textContent = '已核对 ' + summary.inScopeNodes + ' 个地面节点（防御 ' + summary.inScopeDefense + ' / 拦截 ' + summary.inScopeInterception + '），当前 ' + summary.nodesWithImportedTile + ' 个节点至少有一份模板接入。全清单另列 ' + summary.excludedArchwing + ' 个范围外空战节点。多个节点可以共享地图；镜像等特殊任务单独标注，不能据此判断仲裁轮换。';
    box.append(intro);
    const wrap = document.createElement('div');
    wrap.className = 'arena-coverage-table';
    const table = document.createElement('table'), head = document.createElement('thead'), heading = document.createElement('tr');
    for (const label of ['星球 / 节点', '任务', '状态']) {
      const th = document.createElement('th');
      th.textContent = label;
      heading.append(th);
    }
    head.append(heading);
    table.append(head);
    const body = document.createElement('tbody');
    for (const mission of coverage.nodes || []) {
      const row = document.createElement('tr');
      for (const value of [missionPlanet(mission) + ' / ' + missionNode(mission), missionType(mission), ({available: '模板已接入', partial: '部分已接入', missing: '未接入', excluded: '范围外'}[mission.coverageStatus] || mission.coverageLabel || '待核对')]) {
        const td = document.createElement('td');
        td.textContent = value;
        row.append(td);
      }
      if (mission.missingMapReasons?.length) {
        const detail = document.createElement('small');
        detail.className = 'arena-map-missing';
        detail.textContent = mission.missingMapReasons.map(item => item.reason).join('；');
        row.lastChild.append(detail);
      }
      body.append(row);
    }
    table.append(body);
    wrap.append(table);
    box.append(wrap);
  }

  function specMissions(spec) {
    if (Array.isArray(spec.missions)) return spec.missions;
    return (catalog?.missionCoverage?.nodes || []).filter(m => (m.enemySpecPaths || []).some(id => (typeof id === 'string' ? id : id.id || id.path) === spec.id));
  }

  function specOnMap(spec) {
    if ((spec.mapIds || []).includes(mapId)) return true;
    return specMissions(spec).some(m => (m.mapIds || []).includes(mapId));
  }

  function factionLabel(source) {
    if (source.factionZh) return source.factionZh;
    const value = source.faction ?? source.factionName ?? source.factionIndex;
    return ({Grineer: '克隆尼 Grineer', Corpus: '科普斯 Corpus', Infested: '感染者 Infested', Orokin: '奥罗金 Orokin', Sentient: 'Sentient', 0: '克隆尼 Grineer', 1: '科普斯 Corpus', 2: '感染者 Infested', 3: '奥罗金 Orokin'})[value] || String(value || '');
  }

  function specOptionLabel(spec) {
    const missions = specMissions(spec), places = [...new Set(missions.map(m => [missionPlanet(m), m.nodeNameZh || m.nodeName].filter(Boolean).join(' / ')))];
    const factions = [...new Set([factionLabel(spec), ...missions.map(factionLabel)].filter(Boolean))];
    const name = spec.nameZh || spec.name || spec.id.split('/').at(-1);
    return (specOnMap(spec) ? '★ ' : '') + name + (factions.length ? ' - ' + factions.join('/') : '') + (places.length ? ' - ' + places.slice(0, 3).join('、') + (places.length > 3 ? ' 等' + places.length + '节点' : '') : ' - 来源待确认');
  }

  function refreshSpecOptions() {
    if (!catalog) return;
    const selected = $('enemySpec').value || 'single';
    $('enemySpec').replaceChildren();
    option($('enemySpec'), 'single', '单一敌人 - 当前选择');
    const native = document.createElement('optgroup'), other = document.createElement('optgroup');
    native.label = '本图来源敌组';
    other.label = '其他地图 / 来源待确认';
    for (const spec of catalog.enemySpecs || []) {
      const group = specOnMap(spec) ? native : other;
      option(group, spec.id, specOptionLabel(spec) + (spec.selectionEnabled === false ? ' - 仅来源记录，不可选' : ''));
      group.lastElementChild.disabled = spec.selectionEnabled === false;
    }
    if (native.children.length) $('enemySpec').append(native);
    if (other.children.length) $('enemySpec').append(other);
    if ([...$('enemySpec').options].some(o => o.value === selected)) $('enemySpec').value = selected;
    showSpecSource((catalog.enemySpecs || []).find(spec => spec.id === $('enemySpec').value));
  }

  function showSpecSource(spec) {
    const box = $('specSource');
    box.replaceChildren();
    box.classList.toggle('is-native', !!spec && specOnMap(spec));
    if (!spec) {
      box.textContent = '自定义单一敌人，来源独立于地图；选择地图不会自动替换敌人。';
      return;
    }
    const missions = specMissions(spec), known = missions.length > 0 || (spec.mapIds || []).length > 0;
    const badge = document.createElement('b');
    badge.textContent = specOnMap(spec) ? '本图来源敌组' : known ? '跨地图自定义敌组' : '来源待确认';
    box.append(badge);
    const description = document.createElement('p');
    description.textContent = missions.length
      ? missions.map(m => [missionPlanet(m), missionNode(m), missionType(m), factionLabel(m)].filter(Boolean).join(' / ')).join('；')
      : known ? '已确认地图来源，暂无节点说明。' : '尚未确认对应的星球、节点或地图，可作为自定义场景使用。';
    box.append(description);
    const note = document.createElement('small');
    note.textContent = '关联来源说明，不是当前任务无条件刷新百分比；地图改变不会偷偷替换已选敌组。';
    box.append(note);
  }

  function setStandingPicking(enabled) {
    pickingStanding = !!enabled && $('movement').value === 'fixed' && loaded && !busyState && !standingPending;
    controls.enabled = !pickingStanding;
    controls.update();
    if (navPicker) navPicker.visible = pickingStanding;
    viewer.classList.toggle('is-standing-pick', pickingStanding);
    $('standingPick').textContent = pickingStanding ? '退出选点模式' : '进入选点模式';
    $('standingPick').setAttribute('aria-pressed', String(pickingStanding));
    if (pickingStanding) {
      playing = false;
      $('play').textContent = '播放';
      hoveredActorKey = null;
      actorCard.hidden = true;
      renderer.domElement.style.cursor = '';
      $('standingStatus').textContent = '选点模式：单击半透明可行走面，后台验证；退出选点后恢复旋转/拖动。';
      viewer.focus({preventScroll: true});
      viewer.scrollIntoView({block: 'nearest'});
    }
  }

  viewer.addEventListener('keydown', event => {
    if (pickingStanding && event.key === 'Escape') {
      setStandingPicking(false);
      $('standingPick').focus();
    } else if (!pickingStanding && event.key === 'Escape' && pinnedActorKey !== null) {
      pinnedActorKey = null;
      avatarDirty = true;
      updateActorInspector();
    }
  });

  function previewStandingPoint() {
    syncPreviewActors();
  }

  function clearStandingPoint(message = '尚未选择合法站点') {
    standingRequest++;
    standingPending = false;
    fixedPosition = null;
    standingMarker.visible = false;
    setStandingPicking(false);
    previewStandingPoint();
    $('standingPoint').textContent = '尚未选择合法站点';
    $('standingStatus').textContent = message;
    updateRunState();
  }

  function syncStandingMode() {
    const mv = $('movement').value;
    const fixed = mv === 'fixed';
    const stationary = fixed || mv === 'objective';
    $('standingPanel').hidden = !fixed;
    previewStandingPoint();
    if (stationary) {
      if (regionBeforeFixed === null) regionBeforeFixed = $('region').value;
      $('region').value = 'full';
    } else if (regionBeforeFixed !== null) {
      $('region').value = regionBeforeFixed;
      regionBeforeFixed = null;
    }
    if (!fixed) setStandingPicking(false);
    standingMarker.visible = (fixed && !!fixedPosition) || (mv === 'objective' && currentSetupUsesLoS() && Array.isArray(mapAutoVantage?.position) && !result);
    if (fixed && !fixedPosition && !pickingStanding) {
      if (loaded) {
        if (mapAutoVantage) displayStandingPoint(mapAutoVantage);
        else requestAutoStandingPoint();
      } else {
        $('standingStatus').textContent = '请等待地图可行走面加载。';
      }
    }
    updateRunState();
  }

  function rebuildStandingNav() {
    if (navPicker) {
      scene.remove(navPicker);
      navPicker.geometry.dispose();
      navPicker.material.dispose();
      navPicker = null;
    }
    if (!raw?.nav?.vertices || !raw.nav.triangles) return;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(raw.nav.vertices.flat(), 3));
    geometry.setIndex(raw.nav.triangles.flat());
    const accent = getComputedStyle(document.documentElement).getPropertyValue('--ice').trim() || '#73cfdf';
    navPicker = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({color: accent, side: THREE.DoubleSide, transparent: true, opacity: .22, depthWrite: false, clippingPlanes: [plane]}));
    navPicker.visible = false;
    navPicker.renderOrder = 3;
    scene.add(navPicker);
  }

  function displayStandingPoint(response) {
    fixedPosition = {
      face: response.face,
      position: [...response.position],
      ...(response.autoSelected ? {
        autoSelected: true,
        elevationGainM: response.elevationGainM,
        visibilityRatio: response.visibilityRatio,
        objectiveVisibilityRatio: response.objectiveVisibilityRatio,
      } : {}),
    };
    standingMarker.position.fromArray(response.position);
    standingMarker.position.y += .04;
    standingMarker.visible = $('movement').value === 'fixed';
    previewStandingPoint();
    $('standingPoint').textContent = 'X ' + response.position[0].toFixed(2) + ' / Y ' + response.position[1].toFixed(2) + ' / Z ' + response.position[2].toFixed(2)
      + (response.autoSelected ? ' (自动高台 +' + Number(response.elevationGainM || 0).toFixed(2) + 'm)' : '');
    $('standingStatus').textContent = response.autoSelected
      ? '已自动优选可达低遮挡高台：无遮挡视野 ' + (Number(response.visibilityRatio || 0) * 100).toFixed(1) + '%（底层核心 ' + (Number(response.objectiveVisibilityRatio || 0) * 100).toFixed(1) + '%），地面敌人可接近出生点 ' + response.enemyReachableSpawns + '/' + response.candidateSpawns + '。也可点击“进入选点模式”手动改点。'
      : '站点验证通过。普通地面敌人可接近的出生点 ' + response.enemyReachableSpawns + '/' + response.candidateSpawns + '。玩家保持该位置；固定站点可能限制敌人接近，不保证全图可达。';
  }

  async function refreshMapAutoVantage() {
    if (!loaded || !mapId) return;
    const req = ++autoVantageReq, map = mapId;
    try {
      const response = await json('/api/arena/standing-point', {mapId: map, auto: true, npcShortGap: $('npcShortGap').checked});
      if (req !== autoVantageReq || map !== mapId) return;
      mapAutoVantage = response;
      if ($('movement').value === 'fixed' && !fixedPosition && !pickingStanding) {
        displayStandingPoint(response);
        updateRunState();
      } else if (!result) {
        syncPreviewActors();
      }
    } catch {
      // Ignore silent background preview failure
    }
  }

  async function requestAutoStandingPoint() {
    if (!loaded || !mapId) return;
    const request = ++standingRequest, map = mapId;
    standingPending = true;
    setStandingPicking(false);
    updateRunState();
    $('standingStatus').textContent = '正在扫描可达高台并计算全图视野遮挡率…';
    try {
      const response = await json('/api/arena/standing-point', {mapId: map, auto: true, npcShortGap: $('npcShortGap').checked});
      if (request !== standingRequest || map !== mapId) return;
      mapAutoVantage = response;
      displayStandingPoint(response);
    } catch {
      if (request !== standingRequest || map !== mapId) return;
      $('standingStatus').textContent = '自动优选高台未完成，请手动点击进入选点模式选择。';
    } finally {
      if (request === standingRequest) {
        standingPending = false;
        updateRunState();
      }
    }
  }

  async function validateStandingPoint(face, point) {
    const request = ++standingRequest, map = mapId;
    standingPending = true;
    setStandingPicking(false);
    updateRunState();
    $('standingStatus').textContent = '后台验证脚下支撑、坡度和站立净空…';
    try {
      const response = await json('/api/arena/standing-point', {mapId: map, face, position: point, npcShortGap: $('npcShortGap').checked});
      if (request !== standingRequest || map !== mapId) return;
      displayStandingPoint(response);
    } catch {
      if (request !== standingRequest || map !== mapId) return;
      $('standingStatus').textContent = '该位置未通过站立验证，或验证请求未完成' + (fixedPosition ? '；保留上一合法站点。' : '；请重新选点。');
    } finally {
      if (request === standingRequest) {
        standingPending = false;
        updateRunState();
      }
    }
  }

  $('npcShortGap').addEventListener('change', () => {
    refreshMapAutoVantage();
    if (fixedPosition) {
      if (fixedPosition.autoSelected) requestAutoStandingPoint();
      else validateStandingPoint(fixedPosition.face, fixedPosition.position);
    }
  });
  $('movement').addEventListener('change', syncStandingMode);
  if ($('standingAuto')) $('standingAuto').onclick = () => requestAutoStandingPoint();
  $('standingPick').onclick = () => setStandingPicking(!pickingStanding);
  $('standingClear').onclick = () => clearStandingPoint('已清除站点；可点击“自动优选高台视野”或“进入选点模式”手动选点。');

  renderer.domElement.addEventListener('pointerdown', event => {
    if (event.button !== 0) { pointerStart = null; avatarClickStart = null; return; }
    if (pickingStanding) {
      pointerStart = {x: event.clientX, y: event.clientY};
      avatarClickStart = null;
    } else {
      pointerStart = null;
      avatarClickStart = {x: event.clientX, y: event.clientY};
    }
  });

  renderer.domElement.addEventListener('pointerup', event => {
    const standStart = pointerStart;
    const clickStart = avatarClickStart;
    pointerStart = null;
    avatarClickStart = null;
    if (event.button !== 0) return;

    if (pickingStanding) {
      if (!standStart || Math.hypot(event.clientX - standStart.x, event.clientY - standStart.y) > 5 || !navPicker) return;
      const rect = renderer.domElement.getBoundingClientRect();
      standingPointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
      standingRay.setFromCamera(standingPointer, camera);
      const hit = standingRay.intersectObject(navPicker, false).find(h => h.point.y <= plane.constant + .001);
      if (!hit) { $('standingStatus').textContent = '这里没有可选择的可行走面；未改变已选站点。'; return; }
      validateStandingPoint(hit.faceIndex, hit.point.toArray());
      return;
    }

    if (clickStart && Math.hypot(event.clientX - clickStart.x, event.clientY - clickStart.y) <= 5 && viewPrefs.avatars !== false) {
      const hit = hitTestAvatar(event.clientX, event.clientY);
      const nextPin = hit ? (pinnedActorKey === hit.key ? null : hit.key) : null;
      if (nextPin !== pinnedActorKey) {
        pinnedActorKey = nextPin;
        avatarDirty = true;
        updateActorInspector();
      }
    }
  });

  function enemyLabel(enemy) { return enemy.nameZh || enemy.name || enemy.nameEn || enemy.path || enemy.id; }

  function updateEnemyThumb() {
    const thumb = $('enemyThumb');
    if (!thumb) return;
    const key = selectedEnemy || $('enemy').value;
    const enemy = enemyIndex.get(key);
    const initial = factionInitial(enemy, key);
    thumb.replaceChildren();
    thumb.title = enemy ? enemyLabel(enemy) : '未选择敌人';
    if (enemy?.imageAsset) {
      const img = document.createElement('img');
      img.alt = '';
      img.src = enemy.imageAsset;
      img.addEventListener('error', () => {
        thumb.textContent = initial;
      });
      thumb.append(img);
    } else {
      thumb.textContent = initial;
    }
  }

  function filterEnemies() {
    const query = $('enemySearch').value.trim().toLocaleLowerCase();
    const matches = (catalog?.enemies || []).filter(e => [e.nameZh, e.nameEn, e.name, e.faction, e.path].some(v => String(v || '').toLocaleLowerCase().includes(query)));
    const selected = enemyIndex.get(selectedEnemy), shown = matches.slice(0, 60);
    if (selected && !shown.some(e => (e.path || e.id) === selectedEnemy)) shown.unshift(selected);
    $('enemy').replaceChildren();
    for (const e of shown) option($('enemy'), e.path || e.id, enemyLabel(e));
    if (!shown.length) option($('enemy'), '', '没有匹配项，请修改搜索');
    if (selectedEnemy) $('enemy').value = selectedEnemy;
    $('enemyMatches').textContent = '匹配 ' + matches.length + ' 项 / 最多显示60项，当前选择保留' + (selected ? ' - ' + enemyLabel(selected) : '');
    updateEnemyThumb();
  }

  function syncSpawnProfile() {
    const profile = $('spawnProfile').value, source = profile !== 'custom', interception = profile.includes('interception'), single = $('enemySpec').value === 'single';
    const waveOpt = $('budget').querySelector('option[value="waves"]');
    if (waveOpt) waveOpt.disabled = interception;
    if (interception && $('budget').value === 'waves') {
      $('budget').value = 'time';
    }
    const bSpec = budgetSpec();
    const towers = Number($('interceptionTowers')?.value ?? 1);
    $('npcShortGap').disabled = busyState;
    $('levelGrowth').disabled = busyState || !source;
    $('levelGrowthHelp').textContent = interception
      ? (towers > 0
        ? '默认关闭。开启后每当总占领进度达到 100% 结轮时按拦截轮次公式涨级；选择 1 塔慢推可最大限度拖慢敌人等级成长。'
        : '当前为固定总占领进度卡点不结轮，全程保持第 1 轮等级不增长。')
      : source
        ? '默认关闭；单值起点前10波保持，第20波增加11级，仅作用于新出生敌人。'
        : '等级增长只用于来源规则；当前固定等级。';
    $('limitsText').innerHTML = interception
      ? '无单轮固定数量上限 / 60 秒无伤害或击杀进展熔断<br>模拟时长 ' + bSpec.label + ' / 计算预算 ' + bSpec.wall + ' 秒'
      : '单波 180 秒 / 60 秒无伤害或击杀进展熔断<br>模拟上限 ' + bSpec.label + ' / 计算预算 ' + bSpec.wall + ' 秒';
    $('interceptionFields').hidden = !interception;
    if ($('interceptionProgressWrap')) $('interceptionProgressWrap').hidden = !interception || towers > 0;
    $('sourceSpawnFields').hidden = !source;
    $('enemies').disabled = source;
    $('enemies').closest('label').hidden = source;
    $('tier').disabled = source;
    $('tier').closest('label').hidden = source;
    $('quotaLabel').textContent = '自定义每波目标数量';
    $('missionTier').closest('label').hidden = interception;
    $('spawnHelp').textContent = source
      ? (single
        ? '来源规则需要选择敌人编组；单一敌人请使用自定义工况。'
        : interception
          ? '按所选时长统计单位时间击杀与精华，不设单轮杀敌数量配额。总占领进度（Tenno 对敌方派系总占领条）随控塔速率推进或卡点固定，无需走位占点即可真实模拟控进度压级刷怪。'
          : '每波数量由队伍人数、起始等级、波次及仲裁修正计算，再按累计层级编排配额；每0.25秒最多尝试生成1只。最终数量见回放波次记录。')
      : '当前固定数量/层级和每7只一只无人机为可复现测试工况，不等同游戏每波敌人数。';
    updateRunState();
  }

  $('spawnProfile').addEventListener('change', () => { specChanged(false); syncMissionStartLevel(); updateRunState(); syncSpawnProfile(); });
  $('combatStyle')?.addEventListener('change', () => { syncArenaNukeControls(); syncStandingMode(); updateRunState(); });
  $('nukeSetup')?.addEventListener('change', () => {
    if (loadout?.warframeLink) loadout.warframeLink.nukeSetupId = $('nukeSetup').value || null;
    refreshPreviewWarframeRanges();
  });
  $('arbucepEmpowered')?.addEventListener('change', () => {
    refreshPreviewWarframeRanges();
  });

  function specChanged(resetTier = true) {
    const id = $('enemySpec').value || 'single', spec = (catalog?.enemySpecs || []).find(s => s.id === id);
    $('singleEnemy').hidden = !!spec;
    $('specPanel').hidden = !spec;
    showSpecSource(spec);
    syncSpawnProfile();
    syncMissionStartLevel();
    if (!spec) return;
    if (resetTier) {
      const prior = $('tier').value;
      let tiers = spec.tiers || [...new Set((spec.rows || []).map(r => r.tier))];
      tiers = tiers.map(t => typeof t === 'object' ? (t.id ?? t.tier ?? t.value) : t).filter(t => t != null);
      $('tier').replaceChildren();
      for (const tier of tiers) option($('tier'), String(tier), '层级 ' + tier + '（源 tier）');
      if ([...$('tier').options].some(o => o.value === prior)) $('tier').value = prior;
      if (!$('tier').options.length) option($('tier'), '0', 'Tier 0');
    }
    const current = Number($('tier').value), source = $('spawnProfile').value !== 'custom';
    const rows = (spec.rows || []).filter(r => source || r.tier == null || Number(r.tier) === current);
    const box = $('specRows');
    box.replaceChildren();
    $('tierHelp').textContent = $('spawnProfile').value.includes('interception') ? '拦截累计准入层级取固定进度阶段与清场周期：floor(min(阶段tier+(周期−1)/2,8))。逐只按源权重抽取，并检查Agent存活限额；未套用防御整波配额。' : source ? '来源防御累计准入：1–2波 tier≤0；3–5波≤1；6–8波≤2；9–11波≤3；12–14波≤4；15波起≤5。tier9以上特殊编组另按Boss波检查，不作为普通池。下表展示全部来源。' : '自定义工况固定层级 ' + current + '，含 ' + rows.length + ' 条记录；这不是原生防御波次编排。';
    const table = document.createElement('table'), head = document.createElement('thead'), hr = document.createElement('tr');
    for (const label of ['类别 / 敌人', 'tier', 'weight', 'cap']) {
      const th = document.createElement('th');
      th.textContent = label;
      hr.append(th);
    }
    head.append(hr);
    table.append(head);
    const body = document.createElement('tbody');
    for (const row of rows) {
      const tr = document.createElement('tr'), known = enemyIndex.get(row.avatar);
      for (const value of [row.nameZh || known?.nameZh || row.name || known?.nameEn || row.avatar, row.tier ?? '—', row.weight ?? '—', row.cap ?? '—']) {
        const td = document.createElement('td');
        td.textContent = String(value);
        tr.append(td);
      }
      body.append(tr);
    }
    table.append(body);
    box.append(table);
    if (!rows.length) {
      const text = document.createElement('p');
      text.textContent = '该 tier 没有来源条目。';
      box.append(text);
    }
  }

  function coverageText(value) {
    const box = $('coverage');
    box.replaceChildren();
    const intro = document.createElement('p');
    intro.textContent = '本页只显示后端计算的记录轨迹；NPC 追击、无任务目标。未覆盖项按本次任务诊断显示。';
    box.append(intro);
    const lines = [];
    const visit = v => {
      if (typeof v === 'string') lines.push(v);
      else if (Array.isArray(v)) v.forEach(visit);
      else if (v && typeof v === 'object') Object.values(v).forEach(visit);
    };
    visit(value);
    if (lines.length) {
      const ul = document.createElement('ul');
      for (const text of [...new Set(lines)]) {
        const li = document.createElement('li');
        li.textContent = text;
        ul.append(li);
      }
      box.append(ul);
    }
  }

  function applyCatalogDefaults() {
    const defaults = catalog.defaults || {};
    const choose = (id, value) => {
      if (value != null && [...$(id).options].some(o => o.value === String(value))) $(id).value = String(value);
    };
    let wait = defaults.waveWait ?? '';
    try { wait = localStorage.getItem('arena-wave-wait-v1') ?? wait; } catch {}
    choose('map', defaults.mapId || defaults.map || catalog.defaultMap);
    choose('region', defaults.region);
    choose('budget', defaults.mode);
    choose('wait', wait);
    choose('movement', defaults.movement);
    choose('doorSight', defaults.doorSight || 'open');
    choose('spawnProfile', defaults.spawnProfile || 'custom');
    choose('squadSize', defaults.squadSize || 1);
    if ($('interceptionTowers')) choose('interceptionTowers', 1);
    $('interceptionProgress').value = defaults.interceptionProgress ?? 0.5;
    for (const [id, key] of [['enemies', 'enemies'], ['seed', 'seed']]) {
      if (defaults[key] != null) $(id).value = defaults[key];
    }
    $('level').value = loadout?.level ?? defaults.level ?? 160;
    $('levelGrowth').checked = defaults.levelGrowth === true;
    $('strictSurvival').checked = Boolean(defaults.strictSurvival);
    $('enemyShieldRecharge').checked = Boolean(defaults.enemyShieldRecharge);
    $('npcShortGap').checked = defaults.npcShortGap !== false;
    $('head').value = loadout?.headshotChance != null ? (loadout.headshotChance > 0 ? 'head' : 'body') : (defaults.headshots ? 'head' : 'body');
    selectedEnemy = loadout?.enemy || defaults.enemy || catalog.enemies[0]?.path || catalog.enemies[0]?.id || '';
    if (!enemyIndex.has(selectedEnemy)) selectedEnemy = enemyIndex.has(defaults.enemy) ? defaults.enemy : (catalog.enemies[0]?.path || catalog.enemies[0]?.id || '');
    choose('enemySpec', defaults.enemySpec || 'single');
    syncMissionStartLevel(true);
    specChanged();
    choose('tier', defaults.tier);
    filterEnemies();
    specChanged(false);
  }

  $('enemySearch').addEventListener('input', filterEnemies);
  $('wait').addEventListener('change', () => { try { localStorage.setItem('arena-wave-wait-v1', $('wait').value); } catch {} });
  $('enemy').addEventListener('change', () => {
    if ($('enemy').value) selectedEnemy = $('enemy').value;
    updateEnemyThumb();
  });
  $('enemySpec').addEventListener('change', () => specChanged());
  $('tier').addEventListener('change', () => specChanged(false));

  async function loadCatalog() {
    if (catalogLoading) return;
    catalogLoading = true;
    try {
      catalog = await json('/api/arena/catalog');
      for (const key of ['maps', 'enemies', 'enemySpecs']) {
        catalog[key] = Array.isArray(catalog[key]) ? catalog[key] : Object.values(catalog[key] || {});
      }
      enemyIndex = new Map(catalog.enemies.map(e => [e.path || e.id, e]));
      $('map').replaceChildren();
      for (const m of catalog.maps) option($('map'), m.id || m.mapId, mapOptionLabel(m));
      showMapCoverage();
      refreshSpecOptions();
      applyCatalogDefaults();
      renderLoadoutSnapshot();
      coverageText(catalog.coverage || catalog.modelCoverage);
      diagnostics(catalog.unsupported || catalog.diagnostics);
      busy(false);
      loadMap();
    } catch (e) {
      catalog = null;
      $('status').textContent = '场景目录加载失败：' + e.message;
    } finally {
      catalogLoading = false;
    }
  }

  function animate(now) {
    requestAnimationFrame(animate);
    if (!active) { last = now; lastRender = now; return; }
    const interval = viewPrefs.quality === 'low' ? 1000 / 30 : viewPrefs.quality === 'balanced' ? 1000 / 60 : 0;
    if (now - lastRender < interval) return;
    lastRender = interval ? now - Math.max(0, now - lastRender) % interval : now;
    const dt = Math.min(.15, (now - last) / 1000);
    last = now;
    if (playing && result) {
      time = Math.min(result.stats.seconds, time + dt * Number($('speed').value));
      if (time === result.stats.seconds) {
        playing = false;
        $('play').textContent = '播放';
      }
    }
    paintReplay();
    controls.update();
    if (clipMode === 'player') syncClip();
    occludedRing.visible = loaded && player.visible && viewPrefs.marker !== false;
    if (occludedRing.visible) {
      camera.updateMatrixWorld();
      markerView.copy(player.position).applyMatrix4(camera.matrixWorldInverse);
      const depth = -markerView.z;
      occludedRing.visible = depth > camera.near && depth < camera.far;
      if (occludedRing.visible) {
        occludedRing.position.copy(player.position);
        occludedRing.quaternion.copy(camera.quaternion);
        const radius = 14 * 2 * depth * Math.tan(THREE.MathUtils.degToRad(camera.fov * .5)) / Math.max(1, viewer.clientHeight);
        occludedRing.scale.setScalar(radius);
      }
    }
    const renderBegin = performance.now();
    renderer.info.reset();
    clearView.prepare(loaded && player.visible && detailedGroup?.visible && clearing() && !pickingStanding ? player.position : null, viewPrefs.lensRadius / 100, plane.constant);
    renderer.render(scene, camera);
    paintAvatars();
    renderCost += performance.now() - renderBegin;
    renderedFrames++;
    frames++;
    if (now - frameStart >= 1000) {
      $('fps').textContent = Math.round(frames * 1000 / (now - frameStart)) + ' FPS / ' + renderer.info.render.triangles.toLocaleString() + ' 面 / ' + renderer.info.render.calls + ' 次绘制 / CPU提交 ' + (renderCost / Math.max(1, renderedFrames)).toFixed(1) + ' ms';
      frames = 0;
      frameStart = now;
      renderCost = 0;
      renderedFrames = 0;
    }
  }
  requestAnimationFrame(animate);

  return {
    open(payload, label, meta) {
      if (payload && job) {
        $('status').textContent = '正在运行的任务保留原配装；取消后重新进入可更新快照。';
        payload = null;
      }
      if (payload) {
        const firstOpen = !loadout;
        loadout = structuredClone(payload);
        weaponLabel = label || payload.weaponName || weaponLabel || '当前远程武器';
        openMeta = meta ? structuredClone(meta) : null;
        renderLoadoutSnapshot();
        if (isCustomSingleEnemy()) {
          $('level').value = payload.level || 160;
        }
        if (firstOpen) {
          $('head').value = payload.headshotChance > 0 ? 'head' : 'body';
        }
        if (catalog && isCustomSingleEnemy() && payload.enemy && enemyIndex.has(payload.enemy)) {
          selectedEnemy = payload.enemy;
          filterEnemies();
        }
        if ($('arbucepEmpowered') && firstOpen) {
          $('arbucepEmpowered').checked = Boolean(payload?.warframeLink?.arbucepEmpowered);
        }
        if ($('nukeSetup')) $('nukeSetup').replaceChildren();
        refreshPreviewWarframeRanges();
        syncPreviewActors();
        updateRunState();
        if (result) $('status').textContent = '配装快照已更新；上一结果仍绑定原快照，点击开始才重算。';
      }
      active = true;
      busy(!!job);
      if (!catalog) loadCatalog();
      else if (job?.id) poll(job);
      requestAnimationFrame(() => {
        const w = viewer.clientWidth, h = viewer.clientHeight;
        if (w && h) {
          renderer.setSize(w, h, false);
          camera.aspect = w / h;
          camera.updateProjectionMatrix();
          syncOverlaySize();
          avatarDirty = true;
        }
      });
    },
    hide() {
      active = false;
      playing = false;
      $('play').textContent = '播放';
      setStandingPicking(false);
      clearTimeout(pollTimer);
    },
    applyDefenseNukePreset(opts = {}) {
      const applyNow = () => {
        if (!catalog) return;
        $('spawnProfile').value = 'defense';
        refreshSpecOptions();
        const hasTier0 = s => Array.isArray(s?.tiers) && s.tiers.includes(0);
        const nativeSpec = (catalog.enemySpecs || []).find(s => specOnMap(s) && s.selectionEnabled !== false && hasTier0(s))
          || (catalog.enemySpecs || []).find(s => s.selectionEnabled !== false && hasTier0(s));
        if (nativeSpec) $('enemySpec').value = nativeSpec.id;
        if ($('steelPath')) $('steelPath').checked = opts.steelPath !== false;
        $('squadSize').value = '4';
        if ($('combatStyle')) $('combatStyle').value = opts.combatStyle || 'hybrid_nuke';
        $('movement').value = 'objective';
        if (opts.nukeSetupId && loadout?.warframeLink) {
          loadout.warframeLink.nukeSetupId = opts.nukeSetupId;
          if ($('nukeSetup')) $('nukeSetup').replaceChildren();
        }
        if ($('arbucepEmpowered') && opts.arbucepEmpowered != null) {
          $('arbucepEmpowered').checked = Boolean(opts.arbucepEmpowered);
        }
        specChanged(true);
        syncMissionStartLevel(true);
        syncStandingMode();
        syncSpawnProfile();
        refreshPreviewWarframeRanges();
        $('status').textContent = '已切换为「钢铁之路来源防御 + 驻守核心 + 地图炮主清与枪械补刀」，点击开始即可模拟。';
      };
      if (catalog) applyNow();
      else {
        const waitCat = setInterval(() => {
          if (catalog) {
            clearInterval(waitCat);
            applyNow();
          }
        }, 120);
      }
    },
    get hasLoadout() {
      return !!loadout;
    },
  };
}
