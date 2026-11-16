import * as THREE from './vendor/three.module.js';
import {OrbitControls} from './vendor/OrbitControls.js';
import {shell} from './shell.js';
export function mountArena(host){
host.innerHTML='<div class="arena-layout">'+shell+'</div>';
let loadout=null,catalog=null,mapId='',visualUrl='',jobId=null,pollTimer=null,active=false,loadToken=0;
let jobLoadout=null,resultLoadout=null,resultMap='',catalogLoading=false;
let selectedEnemy='',enemyIndex=new Map();
const $=id=>host.querySelector('[id="arena-'+id+'"]'),format=t=>{let n=Math.round(t*10);return Math.floor(n/600).toString().padStart(2,'0')+':'+((n%600)/10).toFixed(1).padStart(4,'0');};
let raw,result,playing=false,time=0,follow=false,loaded=false,last=performance.now(),frames=0,frameStart=last,fps=0;
const scene=new THREE.Scene(),viewer=$('viewer'),renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.localClippingEnabled=true;viewer.prepend(renderer.domElement);
const camera=new THREE.PerspectiveCamera(43,1,.1,1500),controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.08;controls.minDistance=10;controls.maxDistance=600;
scene.add(new THREE.HemisphereLight(0xcde5ff,0x4b5669,.9));let sun=new THREE.DirectionalLight(0xffffff,1.25);sun.position.set(60,150,90);scene.add(sun);
let detailedGroup=null,visualInfo=null;const plane=new THREE.Plane(new THREE.Vector3(0,-1,0),20),mapGroup=new THREE.Group();scene.add(mapGroup);let grid=new THREE.GridHelper(230,23,0x35495a,0x23313f);grid.position.y=-21;grid.material.transparent=true;grid.material.opacity=.25;scene.add(grid);
let player=new THREE.Mesh(new THREE.CapsuleGeometry(.55,1.1,4,8),new THREE.MeshBasicMaterial({color:0x38c6e9,depthTest:false,transparent:true}));player.renderOrder=8;scene.add(player);player.visible=false;
let bodies=new THREE.InstancedMesh(new THREE.CapsuleGeometry(.44,.9,3,6),new THREE.MeshBasicMaterial({color:0xffffff,depthTest:false,transparent:true}),256);bodies.count=0;bodies.frustumCulled=false;bodies.renderOrder=7;scene.add(bodies);let drones=new THREE.InstancedMesh(new THREE.OctahedronGeometry(.7),new THREE.MeshBasicMaterial({color:0xefca60,depthTest:false,transparent:true}),256);drones.count=0;drones.frustumCulled=false;drones.renderOrder=8;scene.add(drones);
const fieldGroup=new THREE.Group();scene.add(fieldGroup);const fieldMeshes=new Map();
const dummy=new THREE.Object3D(),color=new THREE.Color(),trails=new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0xe16e78,transparent:true,opacity:.35,depthTest:false})),playerTrail=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0x38c6e9,transparent:true,opacity:.9,depthTest:false})),rays=new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0xffdf8e,depthTest:false,transparent:true})),killMarks=new THREE.Points(new THREE.BufferGeometry(),new THREE.PointsMaterial({color:0xc78bff,size:1.1,depthTest:false,transparent:true}));const jumpTrail=new THREE.LineSegments(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color:0x93f2c3,transparent:true,opacity:.8,depthTest:false}));scene.add(trails,playerTrail,rays,killMarks,jumpTrail);jumpTrail.renderOrder=6;trails.renderOrder=5;playerTrail.renderOrder=6;rays.renderOrder=9;killMarks.renderOrder=10;
function linePositions(object,positions){object.geometry.dispose();object.geometry=new THREE.BufferGeometry();object.geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));}
let mapCenter=new THREE.Vector3(0,-7,0),mapExtent=180;function reset(){controls.target.copy(mapCenter);camera.position.copy(mapCenter).add(new THREE.Vector3(mapExtent*.72,mapExtent*.58,mapExtent*.75));controls.update();}reset();
let lastPaint=-1;
function theme(){const style=getComputedStyle(document.documentElement);scene.background=new THREE.Color(style.getPropertyValue('--void').trim()||'#090b10');lastPaint=-1;}theme();new MutationObserver(theme).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
$('reset').onclick=reset;$('top').onclick=()=>{camera.position.copy(mapCenter).add(new THREE.Vector3(0,mapExtent*1.35,.1));controls.target.copy(mapCenter);controls.update();};$('follow').onclick=()=>{follow=!follow;$('follow').textContent=follow?'停止跟随':'跟随战甲';};$('cut').oninput=()=>{plane.constant=Number($('cut').value);};$('detail').onclick=()=>{if(!detailedGroup)return;detailedGroup.visible=!detailedGroup.visible;mapGroup.visible=!detailedGroup.visible;$('detail').textContent=detailedGroup.visible?'导航代理':'精细地图';};
new ResizeObserver(()=>{let w=viewer.clientWidth,h=viewer.clientHeight;if(!w||!h)return;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}).observe(viewer);
function upper(path,t){let l=0,r=path.length;while(l<r){let m=(l+r)>>1;if(path[m][0]<=t)l=m+1;else r=m;}return l;}
function position(path,t){if(!path.length)return [0,0,0];let i=upper(path,t);if(!i)return path[0].slice(1);if(i>=path.length)return path.at(-1).slice(1);let a=path[i-1],b=path[i],k=(t-a[0])/Math.max(.00001,b[0]-a[0]);return [1,2,3].map(n=>a[n]+(b[n]-a[n])*k);}

function paintFields(t){
 if(!result)return;const states=new Map();for(const event of result.replay.fields||[]){if(event.time>t)break;states.set(event.id,event);}
 for(const [id,mesh]of fieldMeshes)mesh.visible=false;
 for(const [id,event]of states){if(!event.position||(event.expires!=null&&event.expires<t)||['expire','explode','replace'].includes(event.kind))continue;let mesh=fieldMeshes.get(id);if(!mesh){mesh=new THREE.Mesh(new THREE.SphereGeometry(1,12,6),new THREE.MeshBasicMaterial({color:event.entityType==='stug'?0xb4db7d:0x70bec8,wireframe:true,transparent:true,opacity:.28,depthTest:false}));fieldMeshes.set(id,mesh);fieldGroup.add(mesh);}mesh.visible=true;let point=event.position;if(event.host!=null){let actor=result.replay.actors.find(a=>a.id===event.host);if(actor&&actor.birth<=t&&(actor.death==null||actor.death>t))point=position(actor.path,t);}mesh.position.fromArray(point);mesh.scale.setScalar(Math.max(.2,event.radius||.4));}
}
function paintReplay(){if(!result||resultMap!==mapId||Math.abs(time-lastPaint)<.03)return;lastPaint=time;let r=result.replay,pp=position(r.player,time);const motion=null;player.position.set(pp[0],pp[1]+1,pp[2]);player.visible=true;if(follow){let delta=new THREE.Vector3(pp[0],pp[1]+1,pp[2]).sub(controls.target);controls.target.add(delta);camera.position.add(delta);}
 let bi=0,di=0,trail=[];for(let a of r.actors){if(a.birth>time||(a.death!=null&&a.death<=time))continue;let p=position(a.path,time);dummy.position.set(p[0],p[1]+.95,p[2]);dummy.updateMatrix();if(a.type==='drone'){if(di>=drones.instanceMatrix.count)continue;drones.setMatrixAt(di++,dummy.matrix);}else {if(bi>=bodies.instanceMatrix.count)continue;bodies.setMatrixAt(bi,dummy.matrix);color.set(a.type==='heavy'?0xed9a64:0xe26e77);bodies.setColorAt(bi++,color);}let from=upper(a.path,time-6),to=upper(a.path,time);for(let j=Math.max(1,from);j<to;j++)trail.push(...a.path[j-1].slice(1),...a.path[j].slice(1));}
 bodies.count=bi;drones.count=di;bodies.instanceMatrix.needsUpdate=true;drones.instanceMatrix.needsUpdate=true;if(bodies.instanceColor)bodies.instanceColor.needsUpdate=true;linePositions(trails,trail);let end=upper(r.player,time);linePositions(playerTrail,r.player.slice(0,end).flatMap(p=>[p[1],p[2]+.15,p[3]]));
 let shotPositions=[];for(let s of r.shots){if(s[0]>time)break;if(time-s[0]>.8)continue;shotPositions.push(...s.slice(1,7));}linePositions(rays,shotPositions);linePositions(killMarks,r.kills.filter(k=>k[0]<=time&&time-k[0]<8).flatMap(k=>[k[2],k[3]+.7,k[4]]));
 let air=[];for(let m of r.moves||[]){if(m.start>time||time-m.start>30||m.kind==='walk'||m.kind==='step')continue;for(let i=1;i<m.points.length;i++)air.push(...m.points[i-1],...m.points[i]);}linePositions(jumpTrail,air);
 paintFields(time);$('clock').textContent=format(time);$('timeline').value=time;let done=r.kills.filter(k=>k[0]<=time).length;$('viewMetrics').textContent='当前 '+(bi+di)+' 个目标 · '+(motion?({drop:'直接下落','jump-down':'跳跃下层','bullet-jump':'子弹跳'}[motion.kind]||'步行'):'射击/等待')+' · 累计 '+done+' 击杀';}
async function loadVisual(){const token=loadToken, url=visualUrl, begin=performance.now();try{const data=await json(url);if(token!==loadToken)return;detailedGroup=new THREE.Group();scene.add(detailedGroup);const geometries=data.meshes.map(m=>{let g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(m.positions,3));g.setIndex(m.indices);g.computeVertexNormals();for(let group of m.groups)g.addGroup(group.start,group.count,group.materialId);return g;});const materials=data.materials.map(m=>new THREE.MeshStandardMaterial({color:m.color,side:THREE.DoubleSide,roughness:.85,metalness:.12,clippingPlanes:[plane]}));const groups=new Map();for(let item of data.instances){let key=item.meshId+':'+JSON.stringify(item.materialOverrides);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);}let rendered=0;for(let instances of groups.values()){let first=instances[0],source=data.meshes[first.meshId],base=geometries[first.meshId],geometry=base.clone();geometry.clearGroups();const mats=[];for(let i=0;i<source.groups.length;i++){let group=source.groups[i],id=first.materialOverrides?.[i]??group.materialId;mats.push(materials[id]||materials[group.materialId]);geometry.addGroup(group.start,group.count,i);}const mesh=new THREE.InstancedMesh(geometry,mats,instances.length);for(let [i,item]of instances.entries()){dummy.position.fromArray(item.position);dummy.quaternion.fromArray(item.quaternion);dummy.scale.setScalar(item.scale);dummy.updateMatrix();mesh.setMatrixAt(i,dummy.matrix);}mesh.instanceMatrix.needsUpdate=true;mesh.computeBoundingSphere();detailedGroup.add(mesh);rendered+=source.indices.length/3*instances.length;}dummy.quaternion.identity();dummy.scale.setScalar(1);mapGroup.visible=false;visualInfo={meshes:data.meshes.length,instances:data.instances.length,triangles:rendered,loadMs:Math.round(performance.now()-begin)};$('detail').disabled=false;$('detail').textContent='导航代理';$('sceneMeta').textContent=data.instances.length.toLocaleString()+' 个真实实例 / '+Math.round(rendered/10000)+' 万面 · 加载 '+(visualInfo.loadMs/1000).toFixed(2)+'s';if(!jobId)$('status').textContent='地图就绪；点击开始才计算。';}catch(e){if(token!==loadToken)return;$('status').textContent='导航可用；精细地图加载失败：'+e.message;console.error(e);}}

const json=async(url,body)=>{const r=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const value=await r.json();if(!r.ok){const message=value.message||value.error?.message||value.error||'请求失败';throw new Error(typeof message==='string'?message:JSON.stringify(message));}return value;};
const option=(select,id,name)=>{const o=document.createElement('option');o.value=id;o.textContent=name;select.append(o);};
function diagnostics(value){let items=[];if(Array.isArray(value))items=value;else if(value)for(let [key,v]of Object.entries(value)){if(Array.isArray(v))items.push(...v);else if(v&&typeof v==='string')items.push(key+': '+v);}items=[...new Set(items.map(x=>typeof x==='string'?x:JSON.stringify(x)))];const box=$('diagnostics');box.hidden=!items.length;box.replaceChildren();if(items.length){const b=document.createElement('b');b.textContent='模型覆盖提示 · '+items.length;box.append(b);const ul=document.createElement('ul');for(let text of items){const li=document.createElement('li');li.textContent=text;ul.append(li);}box.append(ul);}}
function busy(value){$('run').disabled=value||!catalog||!loadout;$('cancel').disabled=!value;$('map').disabled=value;}
function config(){return {...(catalog?.defaults||{}),map:mapId,mapId,mode:$('budget').value,waves:20,seconds:1800,waveWait:Number($('wait').value),seed:Number($('seed').value)||20261116,enemies:Math.max(1,Math.min(128,Number($('enemies').value)||60)),aliveCap:Number(catalog?.defaults?.aliveCap)||128,region:$('region').value,enemy:selectedEnemy||$('enemy').value,enemySpec:$('enemySpec').value||'single',tier:Number($('tier').value)||0,level:Number($('level').value)||160,headshots:$('head').value==='head',movement:$('movement').value};}
function accept(r){for(const mesh of fieldMeshes.values()){mesh.geometry.dispose();mesh.material.dispose();fieldGroup.remove(mesh);}fieldMeshes.clear();resultLoadout=structuredClone(jobLoadout||loadout);resultMap=mapId;result=r;result.replay??={};for(let key of ['actors','player','shots','kills','waves','moves','fields'])result.replay[key]??=[];time=0;lastPaint=-1;playing=false;let s=r.stats||{};$('timeline').max=s.seconds||0;$('timeline').disabled=false;$('play').disabled=false;$('play').textContent='播放';$('export').disabled=false;$('simTime').textContent=format(s.seconds||0);$('kills').textContent=(s.waves||0)+' / '+(s.kills||0);$('wall').textContent=((s.totalElapsedMs??s.elapsedMs??0)/1000).toFixed(2)+' s';$('multi').textContent=s.maxGroupKill??'—';$('jump').textContent=s.jumps??'—';$('vitus').textContent=Number(s.vitusExpected||0).toLocaleString('zh-CN',{maximumFractionDigits:2});$('resultTitle').textContent=r.reason||r.status||'模拟完成';$('resultText').textContent=(s.shots||0)+' 次开火 · 直接伤害 '+Number(s.directDamage||0).toLocaleString('zh-CN',{maximumFractionDigits:1})+' · 状态伤害 '+Number(s.dotDamage||0).toLocaleString('zh-CN',{maximumFractionDigits:1})+' · 换弹 '+(s.reloads||0)+' 次 / 形态切换 '+(s.transforms||0)+' 次 · 路径失败 '+(s.failedPathPlans||0)+' 次。';$('fingerprint').textContent='事件指纹 '+(s.eventHash||'—')+' · '+(r.model||'');diagnostics(r.diagnostics||r.unsupported);$('status').textContent='任务已结束，可播放、拖动或导出。';paintReplay();}
async function poll(){clearTimeout(pollTimer);if(!jobId||!active)return;try{const data=await json('/api/arena/jobs?id='+encodeURIComponent(jobId));const p=data.progress||{};$('status').textContent='后台 '+(data.status||'running')+' · 模拟 '+format(p.t??p.seconds??0)+' · 第 '+(p.wave||0)+' 波';if(data.result){jobId=null;busy(false);accept(data.result);return;}if(['completed','failed','cancelled','limited'].includes(data.status)){jobId=null;busy(false);$('status').textContent=typeof(data.message||data.error)==='object'?JSON.stringify(data.message||data.error):(data.message||data.error||data.status);diagnostics(data.diagnostics);return;}}catch(e){$('status').textContent=e.message;}pollTimer=setTimeout(poll,500);}
$('run').onclick=async()=>{if(!loadout||jobId)return;busy(true);playing=false;try{jobLoadout=structuredClone(loadout);const data=await json('/api/arena/jobs',{loadout:jobLoadout,scenario:config()});jobId=data.id;if(!jobId)throw new Error('任务响应缺少 id');$('status').textContent='任务已创建';poll();}catch(e){busy(false);$('status').textContent=e.message;}};
$('cancel').onclick=async()=>{if(!jobId)return;try{await json('/api/arena/cancel',{id:jobId});$('status').textContent='正在取消后台任务…';poll();}catch(e){$('status').textContent=e.message;}};
$('back').onclick=()=>host.dispatchEvent(new CustomEvent('arena-back',{bubbles:true}));
$('play').onclick=()=>{if(!result||resultMap!==mapId)return;if(time>=result.stats.seconds)time=0;playing=!playing;$('play').textContent=playing?'暂停':'播放';};
$('timeline').oninput=()=>{time=Number($('timeline').value);playing=false;$('play').textContent='播放';paintReplay();};
$('export').onclick=()=>{if(!result)return;let url=URL.createObjectURL(new Blob([JSON.stringify({loadout:resultLoadout,result})],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='arena-replay-'+(result.stats.eventHash||Date.now())+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
async function loadMap(){const token=++loadToken;mapId=$('map').value;lastPaint=-1;bodies.count=0;drones.count=0;$('play').disabled=!result||resultMap!==mapId;$('timeline').disabled=!result||resultMap!==mapId;const map=(catalog.maps||[]).find(m=>(m.id||m.mapId)===mapId)||{};const base='/api/arena/assets/'+encodeURIComponent(mapId)+'/';visualUrl=map.visualUrl||base+'visual-map.json';$('mapTitle').textContent=map.name||map.label||mapId;try{const data=await json(map.sceneUrl||base+'scene.json');if(token!==loadToken)return;raw=data;const bounds=new THREE.Box3();for(let p of raw.collision.vertices)bounds.expandByPoint(new THREE.Vector3(...p));bounds.getCenter(mapCenter);const size=bounds.getSize(new THREE.Vector3());mapExtent=Math.max(size.x,size.z,size.y,30);$('cut').min=Math.floor(bounds.min.y-2);$('cut').max=Math.ceil(bounds.max.y+2);$('cut').value=$('cut').max;plane.constant=Number($('cut').value);grid.position.y=bounds.min.y-1;reset();for(let g of [mapGroup,detailedGroup])if(g)g.traverse(o=>{o.geometry?.dispose();});mapGroup.clear();if(detailedGroup){scene.remove(detailedGroup);detailedGroup=null;}$('detail').disabled=true;let geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(raw.collision.vertices.flat(),3));geo.setIndex(raw.collision.triangles.flat());geo.computeVertexNormals();mapGroup.add(new THREE.Mesh(geo,new THREE.MeshStandardMaterial({color:0x668b9c,side:THREE.DoubleSide,roughness:1,transparent:true,opacity:.8,clippingPlanes:[plane]})));mapGroup.visible=true;if(raw.start?.position){player.position.fromArray(raw.start.position);player.position.y+=1;player.visible=true;}loaded=true;$('sceneMeta').textContent=(raw.nav?.triangles?.length||0).toLocaleString()+' 导航面';loadVisual();}catch(e){$('status').textContent='地图显示加载失败：'+e.message;}}
$('map').onchange=()=>{playing=false;loadMap();};
for(let id of ['region','budget','wait','movement','enemies','seed','head','enemy','level','enemySpec','tier'])$(id).addEventListener('change',()=>{if(!jobId)$('status').textContent='配置已修改，点击开始才重新计算。';});
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
  $('singleEnemy').hidden=!!spec;$('specPanel').hidden=!spec;
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
    $('map').replaceChildren();for(let m of catalog.maps)option($('map'),m.id||m.mapId,m.nameZh||m.name||m.label||m.id);
    $('enemySpec').replaceChildren();option($('enemySpec'),'single','单一敌人 · 当前选择');
    for(let spec of catalog.enemySpecs)option($('enemySpec'),spec.id,spec.nameZh||spec.name||spec.id);
    applyCatalogDefaults();coverageText(catalog.coverage||catalog.modelCoverage);diagnostics(catalog.unsupported||catalog.diagnostics);busy(false);loadMap();
  }catch(e){catalog=null;$('status').textContent='场景目录加载失败：'+e.message;}
  finally{catalogLoading=false;}
}
let raf;
function animate(now){raf=requestAnimationFrame(animate);if(!active){last=now;return;}let dt=Math.min(.1,(now-last)/1000);last=now;if(playing&&result){time=Math.min(result.stats.seconds,time+dt*Number($('speed').value));if(time===result.stats.seconds){playing=false;$('play').textContent='播放';}}paintReplay();controls.update();renderer.render(scene,camera);frames++;if(now-frameStart>=1000){$('fps').textContent=Math.round(frames*1000/(now-frameStart))+' FPS · '+renderer.info.render.triangles.toLocaleString()+' 渲染面';frames=0;frameStart=now;}}
raf=requestAnimationFrame(animate);
return {open(payload,label){if(payload&&jobId){$('status').textContent='正在运行的任务保留原配装；取消后重新进入可更新快照。';payload=null;}if(payload){loadout=structuredClone(payload);$('weaponInfo').textContent=label+' · 已冻结当前槽位、紫卡、赋能与灵化';$('level').value=payload.level||160;$('head').value=payload.headshotChance>0?'head':'body';if(catalog&&payload.enemy&&enemyIndex.has(payload.enemy)){selectedEnemy=payload.enemy;filterEnemies();}if(result)$('status').textContent='配装快照已更新；上一结果仍绑定原快照，点击开始才重算。';}active=true;busy(!!jobId);if(!catalog)loadCatalog();else if(jobId)poll();requestAnimationFrame(()=>{const w=viewer.clientWidth,h=viewer.clientHeight;if(w&&h){renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}});},hide(){active=false;playing=false;clearTimeout(pollTimer);},get hasLoadout(){return !!loadout;}};
}
