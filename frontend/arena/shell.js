export const shell = `
<aside class="arena-controls" aria-labelledby="arena-configTitle">
  <header class="arena-config-head">
    <h2 id="arena-configTitle">场景配置</h2>
    <button id="arena-back" type="button">← 返回配装</button>
  </header>
  <p class="arena-loadout" id="arena-weaponInfo"></p>
  <label class="arena-map-field">地图模板<select id="arena-map"><option>读取目录…</option></select></label>

  <div class="arena-run-controls">
    <p class="arena-spawn-requirement arena-field-note">来源刷怪规则需要选择敌组。</p>
    <div class="actions"><button type="button" id="arena-run" class="primary" disabled>开始模拟</button><button type="button" id="arena-cancel" disabled>取消</button></div>
    <p id="arena-status" role="status">正在读取地图…</p>
  </div>

  <details id="arena-sceneParameters">
    <summary>场景参数</summary>
  <div class="arena-fields">
    <label>战甲移动<select id="arena-movement"><option value="parkour">步行 / 子弹跳 / 直接下落</option><option value="walking">仅步行与短跨步（对照）</option><option value="fixed">固定点站桩 · 玩家不移动</option></select></label>
    <section id="arena-standingPanel" class="arena-standing-panel" aria-labelledby="arena-standingTitle" hidden>
      <h3 id="arena-standingTitle">固定站点</h3>
      <div class="arena-standing-actions">
        <button type="button" id="arena-standingPick" aria-controls="arena-viewer" aria-pressed="false" disabled>进入选点模式</button>
        <button type="button" id="arena-standingClear" disabled>清除站点</button>
      </div>
      <output id="arena-standingPoint" aria-live="polite">尚未选择合法站点</output>
      <p id="arena-standingStatus" role="status">请等待地图可行走面加载。</p>
    </section>
    <div class="arena-pair">
      <label>结束条件<select id="arena-budget"><option value="waves">20 波清场</option><option value="time">30 分钟模拟</option></select></label>
      <label>瞄准部位<select id="arena-head"><option value="head">强制头部</option><option value="body">躯干</option></select></label>
    </div>
  </div>

  <div class="arena-fields arena-enemy-fields">
    <label>刷怪规则<select id="arena-spawnProfile"><option value="custom">自定义固定工况</option><option value="defense">来源防御</option><option value="arbitration">来源仲裁防御</option><option value="interception">拦截定额清场</option><option value="arbitration_interception">仲裁拦截定额清场</option></select></label>
    <label><span class="arena-enemy-label">敌人来源<span class="arena-native-indicator">本图敌组</span></span><select id="arena-enemySpec"><option value="single">单一敌人 · 当前选择</option></select></label>
    <div id="arena-singleEnemy" class="arena-pair arena-single-fields">
      <label>搜索敌人<input id="arena-enemySearch" type="search" autocomplete="off" placeholder="名称、派系或路径"></label>
      <label>敌人种类<select id="arena-enemy"><option value="">读取敌人目录…</option></select></label>
      <small id="arena-enemyMatches" class="arena-field-note">输入名称缩小候选，当前选择始终保留。</small>
    </div>
    <div id="arena-specPanel" hidden>
      <label>敌组层级（源 tier）<select id="arena-tier"><option value="0">0</option></select></label>
    </div>
    <div class="arena-pair">
      <label>起始等级<input id="arena-level" type="number" min="1" max="9999" value="160"></label>
      <label><span id="arena-quotaLabel">自定义每波目标数量</span><input id="arena-enemies" type="number" min="1" max="128" step="1" value="60"></label>
    </div>
    <div class="arena-pair" id="arena-sourceSpawnFields" hidden>
      <label>队伍人数<select id="arena-squadSize"><option value="1">1 人</option><option value="2">2 人</option><option value="3">3 人</option><option value="4">4 人</option></select></label>
      <label id="arena-interceptionFields" hidden>固定拦截进度<input id="arena-interceptionProgress" type="number" min="0" max="1" step="0.05" value="0.5"></label>
    </div>
  </div>

  <details class="arena-advanced">
    <summary>高级模拟设置</summary>
    <div class="arena-fields">
      <label>地图范围<select id="arena-region"><option value="focus">中心区域</option><option value="full">全部已接入区域</option></select></label>
      <label>波间等待<select id="arena-wait"><option value="">按规则 (默认)</option><option value="3">3 秒</option><option value="6">6 秒</option><option value="15">15 秒</option></select></label>
      <label>门的视线<select id="arena-doorSight"><option value="open">常开 · 门不遮挡视线</option><option value="closed">关闭遮挡 · 仅影响视线</option></select></label>
      <label class="arena-check"><input id="arena-npcShortGap" type="checkbox" checked aria-describedby="arena-npcGapInfo">NPC 跨越（场景近似）</label>
      <p id="arena-npcGapInfo" class="arena-field-note">允许跨过已检查的窄隙（≤0.8 米）和出生区动作空段（跨度≤2.5 米、上升≤2 米、下落≤3.5 米），另含审核过的≤4 米下落和源指定跳点。</p>
      <label class="arena-check"><input id="arena-levelGrowth" type="checkbox" aria-describedby="arena-levelGrowthHelp">按来源规则增长等级</label>
      <p id="arena-levelGrowthHelp" class="arena-field-note">仅影响后续出生的敌人；不改变每波数量使用的起始等级。</p>
      <label>随机种子<input id="arena-seed" type="number" min="1" max="2147483646" value="20261116"></label>
      <details class="arena-source-parameters">
        <summary>任务来源参数</summary>
        <div class="arena-fields">
          <label>Director 硬上限<input id="arena-directorHardCap" type="number" min="1" max="128" step="1" value="40"></label>
          <label>任务 difficulty（0–1）<input id="arena-missionDifficulty" type="number" min="0" max="1" step="0.1" value="0"></label>
          <label>任务 MissionInfo tier<input id="arena-missionTier" type="number" min="0" max="99" step="1" value="0"></label>
          <label>卓越者倍率<input id="arena-eximusMultiplier" type="number" min="0" max="10" step="0.1" value="1"></label>
          <p class="arena-field-note">默认值为场景假设。PC 来源默认上限 40；特殊任务可覆盖。本场景使用全体存活 NPC 准入，没有外部预留槽位。</p>
        </div>
      </details>
      <div class="limits"><b>运行上限</b><span id="arena-limitsText">单波 180 秒 · 60 秒无伤害或击杀进展熔断<br>最长模拟 30 分钟 · 计算预算 30 秒</span></div>
    </div>
  </details>
  </details>

</aside>

<section class="arena-workspace" aria-labelledby="arena-mapTitle">
  <header class="scene-head">
    <div class="arena-scene-title">
      <h2 id="arena-mapTitle">场景靶场</h2>
      <p id="arena-mapBrief" class="arena-field-note"></p>
    </div>
    <span id="arena-sceneMeta">载入几何</span>
  </header>
  <div class="arena-view-toolbar">
    <div class="legend"><span><i class="blue"></i>战甲</span><span><i class="red"></i>目标</span><span><i class="gold"></i>无人机</span><span><i class="purple"></i>击杀</span></div>
    <div class="view-buttons">
      <button type="button" id="arena-detail" disabled>加载精细地图</button>
      <button type="button" id="arena-reset">重置视角</button>
      <button type="button" id="arena-top">俯视</button>
      <button type="button" id="arena-floor" title="剖切随战甲当前层移动；再次点击回到最高可站层去顶">当前层</button>
      <button type="button" id="arena-follow">跟随战甲</button>
    </div>
  </div>
  <div id="arena-viewer" role="region" aria-label="三维地图" tabindex="-1">
    <div class="bottom-overlay"><span id="arena-clock">00:00.0</span><span id="arena-viewMetrics">拖动旋转 · 右键平移 · 滚轮缩放</span></div>
  </div>
  <div class="playback" aria-label="回放控制">
    <button type="button" id="arena-play" disabled>播放</button>
    <select id="arena-speed" aria-label="回放速度"><option value="4">4 ×</option><option value="16" selected>16 ×</option><option value="64">64 ×</option></select>
    <input id="arena-timeline" aria-label="回放进度" type="range" min="0" max="1" step="0.1" value="0" disabled>
  </div>
  <details class="arena-replay-settings">
    <summary>回放显示设置</summary>
    <div class="arena-view-options">
      <label>剖切方式<select id="arena-clipMode"><option value="roof">自动去顶 · 最高可站层以上</option><option value="player">跟随战甲所在层</option><option value="full">完整外观</option><option value="manual">手动高度</option></select></label>
      <label>地图配色<select id="arena-mapColors"><option value="semantic">材质辨识配色</option><option value="gray">简洁灰模</option></select></label>
      <label>渲染档位<select id="arena-renderQuality"><option value="low">轻量 · 30帧 / 1×</option><option value="balanced" selected>均衡 · 60帧 / 1.5×</option><option value="high">高画质 · 屏幕帧率 / 2×</option></select></label>
      <label class="cut">剖切高度<input id="arena-cut" type="range" min="-21" max="20" step=".5" value="20"></label>
      <label class="arena-check"><input id="arena-clearView" type="checkbox" disabled>角色周围遮挡半透明</label>
      <label class="arena-check"><input id="arena-occludedMarker" type="checkbox" checked>遮挡位置圆环</label>
      <label><span>透视圈半径 <output id="arena-lensRadiusValue" for="arena-lensRadius">18%</output></span><input id="arena-lensRadius" type="range" min="10" max="30" step="1" value="18" disabled aria-label="透视圈半径（画面短边百分比）"></label>
      <small id="arena-viewHint">显示设置仅影响回放，不改变碰撞、伤害或解算结果。</small>
    </div>
  </details>

  <section class="arena-results" aria-labelledby="arena-resultsHeading">
    <h2 id="arena-resultsHeading">模拟结果</h2>
    <div class="stats">
      <article><span>模拟时间</span><b id="arena-simTime">—</b></article>
      <article><span>完成波次 / 击杀</span><b id="arena-kills">—</b></article>
      <article><span>计算耗时</span><b id="arena-wall">—</b></article>
      <article><span>单发最多击杀</span><b id="arena-multi">—</b></article>
      <article><span>跨层跳跃</span><b id="arena-jump">—</b></article>
      <article><span>本次精华期望</span><b id="arena-vitus">—</b></article>
    </div>
    <p id="arena-vitusDetail" class="arena-vitus-detail">仅累计本次已模拟部分的平均期望；中止时不外推剩余波次。</p>
    <div class="resultbar">
      <div><b id="arena-resultTitle">等待首次运行</b><p id="arena-resultText"></p></div>
      <button type="button" id="arena-export" disabled>导出回放</button>
    </div>
    <div class="arena-diagnostics" id="arena-diagnostics" role="status" hidden></div>
    <details>
      <summary>模型范围与未覆盖机制</summary>
      <div id="arena-coverage">后端目录加载后显示覆盖范围。当前只支持远程武器；NPC 追击、无任务目标。</div>
    </details>
  </section>

  <div class="arena-source-details">
    <details>
      <summary>地图<span class="arena-enemy-source">与敌组</span>来源</summary>
      <div class="arena-sources">
        <section aria-label="地图所属任务">
          <h3 id="arena-mapSummary"></h3>
          <p id="arena-mapSubtitle" class="arena-map-subtitle"></p>
          <div id="arena-mapMissions" class="arena-mission-list"></div>
          <p id="arena-mapQualification" class="arena-field-note"></p>
          <p id="arena-doorInfo" class="arena-field-note"></p>
          <p class="arena-field-note">已确认的门口始终允许通行；普通墙体保留遮挡。站桩模式使用全部已接入区域的出生点，敌人照常追击；不保证全图可达。</p>
        </section>
        <section class="arena-enemy-source" aria-label="敌组来源">
          <div id="arena-specSource" class="arena-spec-source" aria-live="polite"></div>
          <p id="arena-spawnHelp" class="arena-field-note"></p>
          <div>
            <p id="arena-tierHelp" class="arena-field-note"></p>
            <div id="arena-specRows" class="arena-spec-rows" tabindex="0" role="region" aria-label="敌组条目"></div>
            <p class="arena-field-note">weight / cap 保留源值。队伍人数仅影响刷怪量，仍只有一名射手。</p>
          </div>
        </section>
      </div>
    </details>
    <details class="arena-map-coverage">
      <summary id="arena-mapCoverageSummary">地图覆盖范围</summary>
      <div id="arena-mapCoverage" tabindex="0" role="region" aria-labelledby="arena-mapCoverageSummary"></div>
    </details>
  </div>
  <footer><span id="arena-fingerprint">独立后端任务 · 固定 seed · 当前配装快照</span><span id="arena-fps">WebGL 初始化</span></footer>
</section>`;
