import * as THREE from './vendor/three.module.js';
import {OrbitControls} from './vendor/OrbitControls.js';
import {shell} from './shell.js';
export function mountArena(host){
host.innerHTML='<div class="arena-layout">'+shell+'</div>';
let loadout=null,catalog=null,mapId='',visualUrl='',jobId=null,pollTimer=null,active=false,loadToken=0;
let jobLoadout=null,resultLoadout=null,resultMap='',catalogLoading=false;
let selectedEnemy='',enemyIndex=new Map();
let busyState=false,fixedPosition=null,pickingStanding=false,standingPending=false,standingRequest=0,navPicker=null,pointerStart=null,regionBeforeFixed=null;
const $=id=>host.querySelector('[id="arena-'+id+'"]'),format=t=>{let n=Math.round(t*10);return Math.floor(n/600).toString().padStart(2,'0')+':'+((n%600)/10).toFixed(1).padStart(4,'0');};
let raw,result,playing=false,time=0,follow=false,loaded=false,last=performance.now(),frames=0,frameStart=last,fps=0;
const scene=new THREE.Scene(),viewer=$('viewer'),renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.localClippingEnabled=true;viewer.prepend(renderer.domElement);
const camera=new THREE.PerspectiveCamera(43,1,.1,1500),controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.08;controls.minDistance=10;controls.maxDistance=600;
scene.add(new THREE.HemisphereLight(0xcde5ff,0x4b5669,.9));let sun=new THREE.DirectionalLight(0xffffff,1.25);sun.position.set(60,150,90);scene.add(sun);
let detailedGroup=null,visualInfo=null,clipTouched=false,floorCut=false;const plane=new THREE.Plane(new THREE.Vector3(0,-1,0),20),mapGroup=new THREE.Group();scene.add(mapGroup);let grid=new THREE.GridHelper(230,23,0x35495a,0x23313f);grid.position.y=-21;grid.material.transparent=true;grid.material.opacity=.25;scene.add(grid);
let player=new THREE.Mesh(new THREE.CapsuleGeometry(.55,1.1,4,8),new THREE.MeshBasicMaterial({color:0x38c6e9,depthTest:false,transparent:true}));player.renderOrder=8;scene.add(player);player.visible=false;
let bodies=new THREE.InstancedMesh(new THREE.CapsuleGeometry(.44,.9,3,6),new THREE.MeshBasicMaterial({color:0xffffff,depthTest:false,transparent:true}),256);bodies.count=0;bodies.frustumCulled=false;bodies.renderOrder=7;scene.add(bodies);let drones=new THREE.InstancedMesh(new THREE.OctahedronGeometry(.7),new THREE.MeshBasicMaterial({color:0xefca60,depthTest:false,transparent:true}),256);drones.count=0;drones.frustumCulled=false;drones.renderOrder=8;scene.add(drones);
const fieldGroup=new THREE.Group();scene.add(fieldGroup);const fieldMeshes=new Map();
const standingMarker=new THREE.Group();const standingRing=new THREE.Mesh(new THREE.RingGeometry(.55,.78,32),new THREE.MeshBasicMaterial({color:0x73cfdf,side:THREE.DoubleSide,depthTest:false,transparent:true,opacity:.95}));standingRing.rotation.x=-Math.PI/2;standingMarker.add(standingRing);const standingPin=new THREE.Mesh(new THREE.ConeGeometry(.18,.65,12),new THREE.MeshBasicMaterial({color:0x73cfdf,depthTest:false}));standingPin.position.y=.7;standingPin.rotation.z=Math.PI;standingMarker.add(standingPin);standingMarker.visible=false;standingMarker.renderOrder=20;scene.add(standingMarker);
const standingRay=new THREE.Raycaster(),standingPointer=new THREE.Vector2();
const dummy=new THREE.Object3D(),color=new THREE.Color(),trails=new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0xe16e78,transparent:true,opacity:.35,depthTest:false})),playerTrail=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0x38c6e9,transparent:true,opacity:.9,depthTest:false})),rays=new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0xffdf8e,depthTest:false,transparent:true})),killMarks=new THREE.Points(new THREE.BufferGeometry(),new THREE.PointsMaterial({color:0xc78bff,size:1.1,depthTest:false,transparent:true}));const jumpTrail=new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0x93f2c3,transparent:true,opacity:.8,depthTest:false}));scene.add(trails,playerTrail,rays,killMarks,jumpTrail);jumpTrail.renderOrder=6;trails.renderOrder=5;playerTrail.renderOrder=6;rays.renderOrder=9;killMarks.renderOrder=10;
function linePositions(object,positions){object.geometry.dispose();object.geometry=new THREE.BufferGeometry();object.geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));}
let mapCenter=new THREE.Vector3(0,-7,0),mapExtent=180;function reset(){controls.target.copy(mapCenter);camera.position.copy(mapCenter).add(new THREE.Vector3(mapExtent*.72,mapExtent*.58,mapExtent*.75));controls.update();}reset();
let lastPaint=-1;
function theme(){const style=getComputedStyle(document.documentElement);scene.background=new THREE.Color(style.getPropertyValue('--void').trim()||'#090b10');const accent=style.getPropertyValue('--ice').trim()||'#73cfdf';standingRing.material.color.set(accent);standingPin.material.color.set(accent);lastPaint=-1;}theme();new MutationObserver(theme).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
$('reset').onclick=reset;$('top').onclick=()=>{camera.position.copy(mapCenter).add(new THREE.Vector3(0,mapExtent*1.35,.1));controls.target.copy(mapCenter);controls.update();};$('follow').onclick=()=>{follow=!follow;$('follow').textContent=follow?'停止跟随':'跟随战甲';};$('cut').oninput=()=>{clipTouched=true;floorCut=false;$('floor').textContent='当前层';plane.constant=Number($('cut').value);};$('detail').onclick=()=>{if(!detailedGroup)return;detailedGroup.visible=!detailedGroup.visible;mapGroup.visible=!detailedGroup.visible;$('detail').textContent=detailedGroup.visible?'导航代理':'精细地图';};
$('floor').onclick=()=>{
  if(!raw)return;
  floorCut=!floorCut;clipTouched=floorCut;
  $('cut').value=floorCut?Math.min(Number($('cut').max),player.position.y+3):$('cut').max;
  plane.constant=Number($('cut').value);$('floor').textContent=floorCut?'完整外观':'当前层';
};
new ResizeObserver(()=>{let w=viewer.clientWidth,h=viewer.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}).observe(viewer);
function upper(path,t){let l=0,r=path.length;while(l<r){let m=(l+r)>>1;if(path[m][0]<=t)l=m+1;else r=m;}return l;}
function position(path,t){if(!path.length)return [0,0,0];let i=upper(path,t);if(!i)return path[0].slice(1);if(i>=path.length)return path.at(-1).slice(1);let a=path[i-1],b=path[i],k=(t-a[0])/Math.max(.00001,b[0]-a[0]);return [1,2,3].map(n=>a[n]+(b[n]-a[n])*k);}

function paintFields(t){
 if(!result)return;const states=new Map();for(const event of result.replay.fields||[]){if(event.time>t)break;states.set(event.id,event);}
 for(const [id,mesh]of fieldMeshes)mesh.visible=false;
 for(const [id,event]of states){if(!event.position||(event.expires!=null&&event.expires<t)||['expire','explode','replace'].includes(event.kind))continue;let mesh=fieldMeshes.get(id);if(!mesh){mesh=new THREE.Mesh(new THREE.SphereGeometry(1,12,6),new THREE.MeshBasicMaterial({color:event.entityType==='stug'?0xb4db7d:0x70bec8,wireframe:true,transparent:true,opacity:.28,depthTest:false}));fieldMeshes.set(id,mesh);fieldGroup.add(mesh);}mesh.visible=true;let point=event.position;if(event.host!=null){let actor=result.replay.actors.find(a=>a.id===event.host);if(actor&&actor.birth<=t&&(actor.death==null||actor.death>t))point=position(actor.path,t);}mesh.position.fromArray(point);mesh.scale.setScalar(Math.max(.2,event.radius||.4));}
}
function paintReplay(){if(!result||resultMap!==mapId||Math.abs(time-lastPaint)<.03)return;lastPaint=time;let r=result.replay,pp=position(r.player,time);const motion=(r.moves||[]).findLast(move=>move.start<=time&&time<move.start+move.duration);player.position.set(pp[0],pp[1]+1,pp[2]);player.visible=true;if(follow){let delta=new THREE.Vector3(pp[0],pp[1]+1,pp[2]).sub(controls.target);controls.target.add(delta);camera.position.add(delta);}
 let bi=0,di=0,trail=[];for(let a of r.actors){if(a.birth>time||(a.death!=null&&a.death<=time))continue;let p=position(a.path,time);dummy.position.set(p[0],p[1]+.95,p[2]);dummy.updateMatrix();if(a.type==='drone'){if(di>=drones.instanceMatrix.count)continue;drones.setMatrixAt(di++,dummy.matrix);}else {if(bi>=bodies.instanceMatrix.count)continue;bodies.setMatrixAt(bi,dummy.matrix);color.set(a.type==='heavy'?0xed9a64:0xe26e77);bodies.setColorAt(bi++,color);}let from=upper(a.path,time-6),to=upper(a.path,time);for(let j=Math.max(1,from);j<to;j++)trail.push(...a.path[j-1].slice(1),...a.path[j].slice(1));}
 bodies.count=bi;drones.count=di;bodies.instanceMatrix.needsUpdate=true;drones.instanceMatrix.needsUpdate=true;if(bodies.instanceColor)bodies.instanceColor.needsUpdate=true;linePositions(trails,trail);let end=upper(r.player,time);linePositions(playerTrail,r.player.slice(0,end).flatMap(p=>[p[1],p[2]+.15,p[3]]));
 let shotPositions=[];for(let s of r.shots){if(s[0]>time)break;if(time-s[0]>.8)continue;shotPositions.push(...s.slice(1,7));}linePositions(rays,shotPositions);linePositions(killMarks,r.kills.filter(k=>k[0]<=time&&time-k[0]<8).flatMap(k=>[k[2],k[3]+.7,k[4]]));
 let air=[];for(let m of r.moves||[]){if(m.start>time||time-m.start>30||m.kind==='walk'||m.kind==='step')continue;for(let i=1;i<m.points.length;i++)air.push(...m.points[i-1],...m.points[i]);}linePositions(jumpTrail,air);
 paintFields(time);$('clock').textContent=format(time);$('timeline').value=time;let done=r.kills.filter(k=>k[0]<=time).length;$('viewMetrics').textContent='当前 '+(bi+di)+' 个目标 · '+(motion?({drop:'直接下落','jump-down':'跳跃下层','bullet-jump':'子弹跳'}[motion.kind]||'步行'):'射击/等待')+' · 累计 '+done+' 击杀';}
function disposeMapGroup(group){
  if(!group)return;
  const geometries=new Set(),materials=new Set();
  group.traverse(object=>{
    if(object.geometry)geometries.add(object.geometry);
    for(const material of (Array.isArray(object.material)?object.material:[object.material]))if(material)materials.add(material);
    if(object.isInstancedMesh)object.dispose();
  });
  for(const geometry of geometries)geometry.dispose();
  for(const material of materials)material.dispose();
  group.clear();
}
function extendClipBounds(bounds){
  $('cut').min=Math.min(Number($('cut').min),Math.floor(bounds.min.y-2));
  $('cut').max=Math.max(Number($('cut').max),Math.ceil(bounds.max.y+2));
  // Initial view shows the entire actual visual asset; only an explicit user
  // drag clips it. NAV bounds alone omit roofs and elevated structures.
  if(!clipTouched){$('cut').value=$('cut').max;plane.constant=Number($('cut').value);}
}
async function loadVisual(){
  const token=loadToken,url=visualUrl,begin=performance.now();
  try{
    const data=await json(url);if(token!==loadToken)return;
    detailedGroup=new THREE.Group();scene.add(detailedGroup);
    const geometries=data.meshes.map(mesh=>{
      const geometry=new THREE.BufferGeometry();
      geometry.setAttribute('position',new THREE.Float32BufferAttribute(mesh.positions,3));
      geometry.setIndex(mesh.indices);geometry.computeVertexNormals();
      mesh.groups.forEach((group,index)=>geometry.addGroup(group.start,group.count,index));
      return geometry;
    });
    const materials=data.materials.map(material=>new THREE.MeshStandardMaterial({color:material.color,side:THREE.DoubleSide,roughness:.85,metalness:.12,clippingPlanes:[plane]}));
    const groups=new Map();
    for(const item of data.instances){const key=item.meshId+':'+JSON.stringify(item.materialOverrides);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);}
    let rendered=0;const visualBounds=new THREE.Box3();
    for(const instances of groups.values()){
      const first=instances[0],source=data.meshes[first.meshId];
      const mats=source.groups.map((group,index)=>materials[first.materialOverrides?.[index]??group.materialId]||materials[group.materialId]);
      const mesh=new THREE.InstancedMesh(geometries[first.meshId],mats,instances.length);
      for(const [index,item]of instances.entries()){
        dummy.position.fromArray(item.position);dummy.quaternion.fromArray(item.quaternion);dummy.scale.setScalar(item.scale);dummy.updateMatrix();mesh.setMatrixAt(index,dummy.matrix);
      }
      mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();mesh.computeBoundingBox();
      visualBounds.union(mesh.boundingBox);detailedGroup.add(mesh);rendered+=source.indices.length/3*instances.length;
    }
    dummy.quaternion.identity();dummy.scale.setScalar(1);
    if(!visualBounds.isEmpty())extendClipBounds(visualBounds);
    mapGroup.visible=false;
    visualInfo={meshes:data.meshes.length,instances:data.instances.length,triangles:rendered,loadMs:Math.round(performance.now()-begin)};
    $('detail').disabled=false;$('detail').textContent='导航代理';
    const coverage=data.metadata?.visualCoverage;
    $('sceneMeta').textContent=data.instances.length.toLocaleString()+' 个真实实例 / '+Math.round(rendered/10000)+' 万面 · 无纹理模型';
    if(coverage){const omitted=coverage.missingMeshInstances+coverage.unsupportedRiggedMeshInstances;if(omitted>0)$('sceneMeta').textContent+=' · '+omitted+' 个来源实例未解析';}
    if(!jobId)$('status').textContent='地图就绪；点击开始才计算。';
  }catch(error){if(token!==loadToken)return;$('status').textContent='导航可用；地图外观加载失败：'+error.message;console.error(error);}
}

const json=async(url,body)=>{const r=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await r.json();if(!r.ok){const message=value.message||value.error?.message||value.error||'请求失败';throw new Error(typeof message==='string'?message:JSON.stringify(message));}return value;};
const option=(select,id,name)=>{const o=document.createElement('option');o.value=id;o.textContent=name;select.append(o);};
function diagnostics(value){let items=[];if(Array.isArray(value))items=value;else if(value)for(let [key,v]of Object.entries(value)){if(Array.isArray(v))items.push(...v);else if(v&&typeof v==='string')items.push(key+': '+v);}items=[...new Set(items.map(x=>typeof x==='string'?x:JSON.stringify(x)))];const box=$('diagnostics');box.hidden=!items.length;box.replaceChildren();if(items.length){const b=document.createElement('b');b.textContent='模型覆盖提示 · '+items.length;box.append(b);const ul=document.createElement('ul');for(let text of items){const li=document.createElement('li');li.textContent=text;ul.append(li);}box.append(ul);}}
function updateRunState(){const missingFixed=$('movement').value==='fixed'&&!fixedPosition;$('run').disabled=busyState||!catalog||!loadout||!loaded||missingFixed||standingPending;$('cancel').disabled=!busyState;$('map').disabled=busyState;$('movement').disabled=busyState;$('region').disabled=busyState||$('movement').value==='fixed';$('standingPick').disabled=busyState||!loaded||standingPending;$('standingClear').disabled=busyState||!fixedPosition||standingPending;}
function busy(value){busyState=value;if(value)setStandingPicking(false);updateRunState();}
function config(){return {...(catalog?.defaults||{}),map:mapId,mapId,mode:$('budget').value,waves:20,seconds:1800,waveWait:Number($('wait').value),seed:Number($('seed').value)||20261116,enemies:Math.max(1,Math.min(128,Number($('enemies').value)||60)),aliveCap:Number(catalog?.defaults?.aliveCap)||128,region:$('region').value,enemy:selectedEnemy||$('enemy').value,enemySpec:$('enemySpec').value||'single',tier:Number($('tier').value)||0,level:Number($('level').value)||160,headshots:$('head').value==='head',movement:$('movement').value,fixedPosition:$('movement').value==='fixed'?structuredClone(fixedPosition):null};}
function accept(r){for(const mesh of fieldMeshes.values()){mesh.geometry.dispose();mesh.material.dispose();fieldGroup.remove(mesh);}fieldMeshes.clear();resultLoadout=structuredClone(jobLoadout||loadout);resultMap=mapId;result=r;result.replay??={};for(let key of ['actors','player','shots','kills','waves','moves','fields'])result.replay[key]??=[];time=0;lastPaint=-1;playing=false;let s=r.stats||{};$('timeline').max=s.seconds||0;$('timeline').disabled=false;$('play').disabled=false;$('play').textContent='播放';$('export').disabled=false;$('simTime').textContent=format(s.seconds||0);$('kills').textContent=(s.waves||0)+' / '+(s.kills||0);$('wall').textContent=((s.totalElapsedMs??s.elapsedMs??0)/1000).toFixed(2)+' s';$('multi').textContent=s.maxGroupKill??'—';$('jump').textContent=s.jumps??'—';$('vitus').textContent=Number(s.vitusExpected||0).toLocaleString('zh-CN',{maximumFractionDigits:2});$('vitusDetail').textContent='仅本次已模拟 '+format(s.seconds||0)+' 累计：无人机击杀 '+Number(s.droneKills||0)+' · 掉率 '+(Number(s.vitusDropChance??.06)*100).toLocaleString('zh-CN',{maximumFractionDigits:2})+'% · 模拟随机掉落 '+Number(s.vitusSample||0)+'。平均期望不是保底；未完成部分不外推。';$('resultTitle').textContent=r.reason||r.status||'模拟完成';$('resultText').textContent=(s.shots||0)+' 次开火 · 直接伤害 '+Number(s.directDamage||0).toLocaleString('zh-CN',{maximumFractionDigits:1})+' · 状态伤害 '+Number(s.dotDamage||0).toLocaleString('zh-CN',{maximumFractionDigits:1})+' · 换弹 '+(s.reloads||0)+' 次 / 形态切换 '+(s.transforms||0)+' 次 · 路径失败 '+(s.failedPathPlans||0)+' 次 · 合法避让 '+(s.crowdDetours||0)+' 次 · 剩余 '+(s.live||0)+' 个目标（地面暂不可达 '+(s.liveUnreachable||0)+'）。';$('fingerprint').textContent='事件指纹 '+(s.eventHash||'—')+' · '+(r.model||'');diagnostics(r.diagnostics||r.unsupported);$('status').textContent='任务已结束，可播放、拖动或导出。';paintReplay();}
async function poll(){clearTimeout(pollTimer);if(!jobId||!active)return;try{const data=await json('/api/arena/jobs?id='+encodeURIComponent(jobId));const p=data.progress||{};$('status').textContent='后台 '+(data.status||'running')+' · 模拟 '+format(p.t??p.seconds??0)+' · 第 '+(p.wave||0)+' 波';if(data.result){jobId=null;busy(false);accept(data.result);return;}if(['completed','failed','cancelled','limited'].includes(data.status)){jobId=null;busy(false);$('status').textContent=typeof(data.message||data.error)==='object'?JSON.stringify(data.message||data.error):(data.message||data.error||data.status);diagnostics(data.diagnostics);return;}}catch(e){$('status').textContent=e.message;}pollTimer=setTimeout(poll,500);}
$('run').onclick=async()=>{if(!loadout||jobId||busyState||standingPending||($('movement').value==='fixed'&&!fixedPosition))return;busy(true);playing=false;try{jobLoadout=structuredClone(loadout);const data=await json('/api/arena/jobs',{loadout:jobLoadout,scenario:config()});jobId=data.id;if(!jobId)throw new Error('任务响应缺少 id');$('status').textContent='任务已创建';poll();}catch(e){busy(false);$('status').textContent=e.message;}};
$('cancel').onclick=async()=>{if(!jobId)return;try{await json('/api/arena/cancel',{id:jobId});$('status').textContent='正在取消后台任务…';poll();}catch(e){$('status').textContent=e.message;}};
$('back').onclick=()=>host.dispatchEvent(new CustomEvent('arena-back',{bubbles:true}));
$('play').onclick=()=>{if(!result||resultMap!==mapId)return;if(time>=result.stats.seconds)time=0;playing=!playing;$('play').textContent=playing?'暂停':'播放';};
$('timeline').oninput=()=>{time=Number($('timeline').value);playing=false;$('play').textContent='播放';paintReplay();};
$('export').onclick=()=>{if(!result)return;let url=URL.createObjectURL(new Blob([JSON.stringify({loadout:resultLoadout,result})],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='arena-replay-'+(result.stats.eventHash||Date.now())+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
async function loadMap(){
  const token=++loadToken;mapId=$('map').value;loaded=false;raw=null;clearStandingPoint('地图已切换，请重新选择合法站点。');refreshSpecOptions();updateRunState();lastPaint=-1;clipTouched=false;floorCut=false;$('floor').textContent='当前层';bodies.count=0;drones.count=0;
  for(const object of [trails,playerTrail,rays,killMarks,jumpTrail])linePositions(object,[]);
  for(const mesh of fieldMeshes.values())mesh.visible=false;
  $('play').disabled=!result||resultMap!==mapId;$('timeline').disabled=!result||resultMap!==mapId;
  const map=catalog.maps.find(item=>(item.id||item.mapId)===mapId)||{},base='/api/arena/assets/'+encodeURIComponent(mapId)+'/';
  visualUrl=map.visualUrl||base+'visual-map.json';showMapMissions(map);
  $('sceneMeta').textContent='正在读取地图…';$('status').textContent='正在读取地图…';$('detail').disabled=true;
  try{
    const data=await json(map.sceneUrl||base+'scene.json');if(token!==loadToken)return;raw=data;
    const bounds=new THREE.Box3();for(const point of raw.collision.vertices)bounds.expandByPoint(new THREE.Vector3(...point));
    const walkBounds=new THREE.Box3();for(const point of raw.nav.nodePositions)walkBounds.expandByPoint(new THREE.Vector3(...point));
    walkBounds.getCenter(mapCenter);const size=walkBounds.getSize(new THREE.Vector3());mapExtent=Math.max(size.x,size.z,size.y,30);
    $('cut').min=Math.floor(bounds.min.y-2);$('cut').max=Math.ceil(bounds.max.y+2);$('cut').value=$('cut').max;plane.constant=Number($('cut').value);grid.position.y=bounds.min.y-1;reset();
    disposeMapGroup(mapGroup);disposeMapGroup(detailedGroup);if(detailedGroup){scene.remove(detailedGroup);detailedGroup=null;}
    const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(raw.collision.vertices.flat(),3));geometry.setIndex(raw.collision.triangles.flat());geometry.computeVertexNormals();
    mapGroup.add(new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color:0x668b9c,side:THREE.DoubleSide,roughness:1,transparent:true,opacity:.8,clippingPlanes:[plane]})));mapGroup.visible=true;
    if(raw.start?.position){player.position.fromArray(raw.start.position);player.position.y+=1;player.visible=true;}
    rebuildStandingNav();loaded=true;syncStandingMode();updateRunState();$('sceneMeta').textContent=(raw.nav?.triangles?.length||0).toLocaleString()+' 导航面';loadVisual();
  }catch(error){if(token!==loadToken)return;loaded=false;setStandingPicking(false);updateRunState();$('status').textContent='地图显示加载失败：'+error.message;}
}

$('map').onchange=()=>{playing=false;loadMap();};
for(let id of ['region','budget','wait','movement','enemies','seed','head','enemy','level','enemySpec','tier'])$(id).addEventListener('change',()=>{if(!jobId)$('status').textContent='配置已修改，点击开始才重新计算。';});
function missionPlanet(mission){return mission.planetZh||mission.planet;}
function missionNode(mission){return mission.nodeNameZh&&mission.nodeNameZh!==mission.nodeName?mission.nodeNameZh+' ('+mission.nodeName+')':mission.nodeName;}
function missionType(mission){return ({'mirror-defense':'镜像防御','1999-defense':'1999 防御','archwing':'空战拦截'}[mission.variant]||mission.missionTypeZh||mission.missionType);}
function mapOptionLabel(map){
  const planets=[...new Set((map.missions||[]).map(missionPlanet))];
  return (planets.length?planets.join(' / ')+' · ':'')+(map.nameZh||map.name||map.id);
}
function showMapMissions(map){
  const missions=map.missions||[],planets=[...new Set(missions.map(missionPlanet))];
  $('mapTitle').textContent=map.nameZh||map.name||map.id;
  $('mapSummary').textContent=planets.length?planets.join(' / '):'节点对应关系待核对';
  $('mapSubtitle').textContent=missions.map(m=>missionPlanet(m)+' · '+missionNode(m)+'（'+missionType(m)+'）').join('；');
  const box=$('mapMissions');box.replaceChildren();
  for(const mission of missions){
    const card=document.createElement('div');card.className='arena-mission';
    const node=document.createElement('b');node.textContent=missionNode(mission);
    const detail=document.createElement('span');detail.textContent=missionPlanet(mission)+' · '+missionType(mission);
    card.append(node,detail);
    if(mission.arbitrationQualification?.status==='officially-added'){const badge=document.createElement('span');badge.className='arena-official-note';badge.textContent='官方曾确认加入仲裁';card.append(badge);}box.append(card);
  }
  const historical=missions.filter(m=>m.arbitrationQualification?.status==='officially-added');
  $('mapQualification').textContent='这里列出关联该模板的星图节点；一个节点可能使用多个变体。'+(historical.length?'官方更新37已确认镜像防御加入仲裁；当前轮换名单尚未核实。':'当前仲裁轮换资格尚未核实。');
}
function showMapCoverage(){
  const coverage=catalog.missionCoverage,box=$('mapCoverage');box.replaceChildren();
  const intro=document.createElement('p');
  $('mapCoverageSummary').textContent='已接入 '+catalog.maps.length+' / '+(coverage?.summary.candidateTiles||catalog.maps.length)+' 份候选模板 · 覆盖范围';
  if(!coverage){intro.textContent='当前模板不是防御与拦截任务的完整地图集合。';box.append(intro);return;}
  const summary=coverage.summary;
  intro.textContent='已核对 '+summary.inScopeNodes+' 个地面节点（防御 '+summary.inScopeDefense+' / 拦截 '+summary.inScopeInterception+'），当前 '+summary.nodesWithImportedTile+' 个节点至少有一份模板接入。全清单另列 '+summary.excludedArchwing+' 个范围外空战节点。多个节点可以共享地图；镜像等特殊任务单独标注，不能据此判断仲裁轮换。';box.append(intro);
  const wrap=document.createElement('div');wrap.className='arena-coverage-table';
  const table=document.createElement('table'),head=document.createElement('thead'),heading=document.createElement('tr');
  for(const label of ['星球 / 节点','任务','状态']){const th=document.createElement('th');th.textContent=label;heading.append(th);}head.append(heading);table.append(head);
  const body=document.createElement('tbody');
  for(const mission of coverage.nodes||[]){
    const row=document.createElement('tr');
    for(const value of [missionPlanet(mission)+' · '+missionNode(mission),missionType(mission),({available:'模板已接入',partial:'部分已接入',missing:'未接入',excluded:'范围外'}[mission.coverageStatus]||mission.coverageLabel||'待核对')]){const td=document.createElement('td');td.textContent=value;row.append(td);}
    if(mission.missingMapReasons?.length){const detail=document.createElement('small');detail.className='arena-map-missing';detail.textContent=mission.missingMapReasons.map(item=>item.reason).join('；');row.lastChild.append(detail);}
    body.append(row);
  }
  table.append(body);wrap.append(table);box.append(wrap);
}
function specMissions(spec){
  if(Array.isArray(spec.missions))return spec.missions;
  return (catalog?.missionCoverage?.nodes||[]).filter(m=>(m.enemySpecPaths||[]).some(id=>(typeof id==='string'?id:id.id||id.path)===spec.id));
}
function specOnMap(spec){
  if((spec.mapIds||[]).includes(mapId))return true;
  return specMissions(spec).some(m=>(m.mapIds||[]).includes(mapId));
}
function factionLabel(source){
  if(source.factionZh)return source.factionZh;
  const value=source.faction??source.factionName??source.factionIndex;
  return ({Grineer:'克隆尼 Grineer',Corpus:'科普斯 Corpus',Infested:'感染者 Infested',Orokin:'奥罗金 Orokin',Sentient:'Sentient',0:'克隆尼 Grineer',1:'科普斯 Corpus',2:'感染者 Infested',3:'奥罗金 Orokin'})[value]||String(value||'');
}
function specOptionLabel(spec){
  const missions=specMissions(spec),places=[...new Set(missions.map(m=>[missionPlanet(m),m.nodeNameZh||m.nodeName].filter(Boolean).join(' / ')))];
  const factions=[...new Set([factionLabel(spec),...missions.map(factionLabel)].filter(Boolean))];
  const name=spec.nameZh||spec.name||spec.id.split('/').at(-1);
  return (specOnMap(spec)?'★ ':'')+name+(factions.length?' · '+factions.join('/'):'')+(places.length?' · '+places.slice(0,3).join('、')+(places.length>3?' 等'+places.length+'节点':''):' · 来源待确认');
}
function refreshSpecOptions(){
  if(!catalog)return;
  const selected=$('enemySpec').value||'single';$('enemySpec').replaceChildren();option($('enemySpec'),'single','单一敌人 · 当前选择');
  const native=document.createElement('optgroup'),other=document.createElement('optgroup');native.label='本图来源敌组';other.label='其他地图 / 来源待确认';
  for(const spec of catalog.enemySpecs||[]){const group=specOnMap(spec)?native:other;option(group,spec.id,specOptionLabel(spec)+(spec.selectionEnabled===false?' · 仅来源记录，不可选':''));group.lastElementChild.disabled=spec.selectionEnabled===false;}
  if(native.children.length)$('enemySpec').append(native);if(other.children.length)$('enemySpec').append(other);
  if([...$('enemySpec').options].some(o=>o.value===selected))$('enemySpec').value=selected;
  showSpecSource((catalog.enemySpecs||[]).find(spec=>spec.id===$('enemySpec').value));
}
function showSpecSource(spec){
  const box=$('specSource');box.replaceChildren();box.classList.toggle('is-native',!!spec&&specOnMap(spec));
  if(!spec){box.textContent='自定义单一敌人，来源独立于地图；选择地图不会自动替换敌人。';return;}
  const missions=specMissions(spec),known=missions.length>0||(spec.mapIds||[]).length>0;
  const badge=document.createElement('b');badge.textContent=specOnMap(spec)?'本图来源敌组':known?'跨地图自定义敌组':'来源待确认';box.append(badge);
  const description=document.createElement('p');description.textContent=missions.length?missions.map(m=>[missionPlanet(m),missionNode(m),missionType(m),factionLabel(m)].filter(Boolean).join(' · ')).join('；'):known?'已确认地图来源，暂无节点说明。':'尚未确认对应的星球、节点或地图，可作为自定义场景使用。';box.append(description);
  const note=document.createElement('small');note.textContent='关联来源说明，不是当前任务无条件刷新百分比；地图改变不会偷偷替换已选敌组。';box.append(note);
}
function setStandingPicking(enabled){
  pickingStanding=!!enabled&&$('movement').value==='fixed'&&loaded&&!busyState&&!standingPending;
  controls.enabled=!pickingStanding;controls.update();if(navPicker)navPicker.visible=pickingStanding;
  viewer.classList.toggle('is-standing-pick',pickingStanding);$('standingPick').textContent=pickingStanding?'退出选点模式':'进入选点模式';$('standingPick').setAttribute('aria-pressed',String(pickingStanding));
  if(pickingStanding){playing=false;$('play').textContent='播放';$('standingStatus').textContent='选点模式：单击半透明可行走面，后台验证；退出选点后恢复旋转/拖动。';}
}
function clearStandingPoint(message='尚未选择合法站点'){
  standingRequest++;standingPending=false;fixedPosition=null;standingMarker.visible=false;setStandingPicking(false);
  $('standingPoint').textContent='尚未选择合法站点';$('standingStatus').textContent=message;updateRunState();
}
function syncStandingMode(){
  const fixed=$('movement').value==='fixed';$('standingPanel').hidden=!fixed;
  if(fixed){if(regionBeforeFixed===null)regionBeforeFixed=$('region').value;$('region').value='full';}else if(regionBeforeFixed!==null){$('region').value=regionBeforeFixed;regionBeforeFixed=null;}
  if(!fixed)setStandingPicking(false);standingMarker.visible=fixed&&!!fixedPosition;
  if(fixed&&!fixedPosition&&!pickingStanding)$('standingStatus').textContent=loaded?'点击“进入选点模式”，从可站立区域选择并验证。':'请等待地图可行走面加载。';updateRunState();
}
function rebuildStandingNav(){
  if(navPicker){scene.remove(navPicker);navPicker.geometry.dispose();navPicker.material.dispose();navPicker=null;}
  if(!raw?.nav?.vertices||!raw.nav.triangles)return;
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(raw.nav.vertices.flat(),3));geometry.setIndex(raw.nav.triangles.flat());
  navPicker=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({color:0x73cfdf,side:THREE.DoubleSide,transparent:true,opacity:.2,depthWrite:false,clippingPlanes:[plane]}));navPicker.visible=false;navPicker.renderOrder=3;scene.add(navPicker);
}
async function validateStandingPoint(face,point){
  const request=++standingRequest,map=mapId;standingPending=true;setStandingPicking(false);updateRunState();$('standingStatus').textContent='后台验证脚下支撑、坡度和站立净空…';
  try{
    const response=await json('/api/arena/standing-point',{mapId:map,face,position:point});if(request!==standingRequest||map!==mapId)return;
    fixedPosition={face:response.face,position:[...response.position]};standingMarker.position.fromArray(response.position);standingMarker.position.y+=.04;standingMarker.visible=$('movement').value==='fixed';
    $('standingPoint').textContent='X '+response.position[0].toFixed(2)+' / Y '+response.position[1].toFixed(2)+' / Z '+response.position[2].toFixed(2);
    $('standingStatus').textContent='站点验证通过。普通地面敌人可接近的出生点 '+response.enemyReachableSpawns+'/'+response.candidateSpawns+'。玩家保持该位置；固定站点可能限制敌人接近，不保证全图可达。';
  }catch{if(request!==standingRequest||map!==mapId)return;$('standingStatus').textContent='该位置未通过站立验证，或验证请求未完成'+(fixedPosition?'；保留上一合法站点。':'；请重新选点。');}
  finally{if(request===standingRequest){standingPending=false;updateRunState();}}
}
$('movement').addEventListener('change',syncStandingMode);$('standingPick').onclick=()=>setStandingPicking(!pickingStanding);$('standingClear').onclick=()=>clearStandingPoint('已清除，请重新选择合法站点。');
renderer.domElement.addEventListener('pointerdown',event=>{pointerStart=pickingStanding&&event.button===0?{x:event.clientX,y:event.clientY}:null;});
renderer.domElement.addEventListener('pointerup',event=>{
  const start=pointerStart;pointerStart=null;if(!pickingStanding||event.button!==0||!start||Math.hypot(event.clientX-start.x,event.clientY-start.y)>5||!navPicker)return;
  const rect=renderer.domElement.getBoundingClientRect();standingPointer.set((event.clientX-rect.left)/rect.width*2-1,-(event.clientY-rect.top)/rect.height*2+1);standingRay.setFromCamera(standingPointer,camera);
  const hit=standingRay.intersectObject(navPicker,false).find(h=>h.point.y<=plane.constant+.001);
  if(!hit){$('standingStatus').textContent='这里没有可选择的可行走面；未改变已选站点。';return;}validateStandingPoint(hit.faceIndex,hit.point.toArray());
});
function enemyLabel(enemy){return enemy.nameZh||enemy.name||enemy.nameEn||enemy.path||enemy.id;}
function filterEnemies(){
  const query=$('enemySearch').value.trim().toLocaleLowerCase();
  const matches=(catalog?.enemies||[]).filter(e=>[e.nameZh,e.nameEn,e.name,e.faction,e.path].some(v=>String(v||'').toLocaleLowerCase().includes(query)));
  const selected=enemyIndex.get(selectedEnemy),shown=matches.slice(0,60);
  if(selected&&!shown.some(e=>(e.path||e.id)===selectedEnemy))shown.unshift(selected);
  $('enemy').replaceChildren();
  for(const e of shown)option($('enemy'),e.path||e.id,enemyLabel(e));
  if(!shown.length)option($('enemy'),'','没有匹配项，请修改搜索');
  if(selectedEnemy)$('enemy').value=selectedEnemy;
  $('enemyMatches').textContent='匹配 '+matches.length+' 项 · 最多显示60项，当前选择保留'+(selected?' · '+enemyLabel(selected):'');
}
function specChanged(resetTier=true){
  const id=$('enemySpec').value||'single',spec=(catalog?.enemySpecs||[]).find(s=>s.id===id);
  $('singleEnemy').hidden=!!spec;$('specPanel').hidden=!spec;showSpecSource(spec);
  if(!spec)return;
  if(resetTier){const prior=$('tier').value;let tiers=spec.tiers||[...new Set((spec.rows||[]).map(r=>r.tier))];
    tiers=tiers.map(t=>typeof t==='object'?(t.id??t.tier??t.value):t).filter(t=>t!=null);
    $('tier').replaceChildren();for(let tier of tiers)option($('tier'),String(tier),'Tier '+tier);
    if([...$('tier').options].some(o=>o.value===prior))$('tier').value=prior;
    if(!$('tier').options.length)option($('tier'),'0','Tier 0');
  }
  const current=Number($('tier').value),rows=(spec.rows||[]).filter(r=>r.tier==null||Number(r.tier)===current),box=$('specRows');box.replaceChildren();
  const table=document.createElement('table'),head=document.createElement('thead'),hr=document.createElement('tr');
  for(let label of ['类别 / 敌人','weight','cap']){const th=document.createElement('th');th.textContent=label;hr.append(th);}head.append(hr);table.append(head);
  const body=document.createElement('tbody');
  for(let row of rows){const tr=document.createElement('tr'),known=enemyIndex.get(row.avatar);for(let value of [row.nameZh||known?.nameZh||row.name||known?.nameEn||row.avatar,row.weight??'—',row.cap??'—']){const td=document.createElement('td');td.textContent=String(value);tr.append(td);}body.append(tr);}
  table.append(body);box.append(table);if(!rows.length){const text=document.createElement('p');text.textContent='该 tier 没有来源条目。';box.append(text);}
}
function coverageText(value){
  const box=$('coverage');box.replaceChildren();
  const intro=document.createElement('p');intro.textContent='本页只显示后端计算的记录轨迹；NPC 追击、无任务目标。未覆盖项按本次任务诊断显示。';box.append(intro);
  const lines=[];
  const visit=v=>{if(typeof v==='string')lines.push(v);else if(Array.isArray(v))v.forEach(visit);else if(v&&typeof v==='object')Object.values(v).forEach(visit);};visit(value);
  if(lines.length){const ul=document.createElement('ul');for(let text of [...new Set(lines)]){const li=document.createElement('li');li.textContent=text;ul.append(li);}box.append(ul);}
}
function applyCatalogDefaults(){
  const defaults=catalog.defaults||{};
  const choose=(id,value)=>{if(value!=null&&[...$(id).options].some(o=>o.value===String(value)))$(id).value=String(value);};
  choose('map',defaults.mapId||defaults.map||catalog.defaultMap);choose('region',defaults.region);choose('budget',defaults.mode);choose('wait',defaults.waveWait);choose('movement',defaults.movement);
  for(let [id,key]of [['enemies','enemies'],['seed','seed']])if(defaults[key]!=null)$(id).value=defaults[key];
  $('level').value=loadout?.level??defaults.level??160;
  $('head').value=loadout?.headshotChance!=null?(loadout.headshotChance>0?'head':'body'):(defaults.headshots?'head':'body');
  selectedEnemy=loadout?.enemy||defaults.enemy||catalog.enemies[0]?.path||catalog.enemies[0]?.id||'';
  if(!enemyIndex.has(selectedEnemy))selectedEnemy=enemyIndex.has(defaults.enemy)?defaults.enemy:(catalog.enemies[0]?.path||catalog.enemies[0]?.id||'');
  choose('enemySpec',defaults.enemySpec||'single');specChanged();choose('tier',defaults.tier);filterEnemies();specChanged(false);
}
$('enemySearch').addEventListener('input',filterEnemies);
$('enemy').addEventListener('change',()=>{if($('enemy').value)selectedEnemy=$('enemy').value;});
$('enemySpec').addEventListener('change',()=>specChanged());$('tier').addEventListener('change',()=>specChanged(false));
async function loadCatalog(){
  if(catalogLoading)return;catalogLoading=true;
  try{
    catalog=await json('/api/arena/catalog');
    for(let key of ['maps','enemies','enemySpecs'])catalog[key]=Array.isArray(catalog[key])?catalog[key]:Object.values(catalog[key]||{});
    enemyIndex=new Map(catalog.enemies.map(e=>[e.path||e.id,e]));
    $('map').replaceChildren();for(let m of catalog.maps)option($('map'),m.id||m.mapId,mapOptionLabel(m));showMapCoverage();
    refreshSpecOptions();
    applyCatalogDefaults();coverageText(catalog.coverage||catalog.modelCoverage);diagnostics(catalog.unsupported||catalog.diagnostics);busy(false);loadMap();
  }catch(e){catalog=null;$('status').textContent='场景目录加载失败：'+e.message;}
  finally{catalogLoading=false;}
}
let raf;
function animate(now){raf=requestAnimationFrame(animate);if(!active){last=now;return;}let dt=Math.min(.1,(now-last)/1000);last=now;if(playing&&result){time=Math.min(result.stats.seconds,time+dt*Number($('speed').value));if(time===result.stats.seconds){playing=false;$('play').textContent='播放';}}paintReplay();controls.update();renderer.render(scene,camera);frames++;if(now-frameStart>=1000){$('fps').textContent=Math.round(frames*1000/(now-frameStart))+' FPS · '+renderer.info.render.triangles.toLocaleString()+' 渲染面';frames=0;frameStart=now;}}
raf=requestAnimationFrame(animate);
return {open(payload,label){if(payload&&jobId){$('status').textContent='正在运行的任务保留原配装；取消后重新进入可更新快照。';payload=null;}if(payload){loadout=structuredClone(payload);$('weaponInfo').textContent=label+' · 已冻结当前槽位、紫卡、赋能与灵化';$('level').value=payload.level||160;$('head').value=payload.headshotChance>0?'head':'body';if(catalog&&payload.enemy&&enemyIndex.has(payload.enemy)){selectedEnemy=payload.enemy;filterEnemies();}if(result)$('status').textContent='配装快照已更新；上一结果仍绑定原快照，点击开始才重算。';}active=true;busy(!!jobId);if(!catalog)loadCatalog();else if(jobId)poll();requestAnimationFrame(()=>{const w=viewer.clientWidth,h=viewer.clientHeight;if(w&&h){renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}});},hide(){active=false;playing=false;setStandingPicking(false);clearTimeout(pollTimer);},get hasLoadout(){return !!loadout;}};
}
