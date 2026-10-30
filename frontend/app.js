"use strict";

// Apply the stored theme before first paint to avoid a dark flash.
const THEME_STORAGE_KEY = "wf-riven-theme";
function applyTheme(theme) {
  const next = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  const toggle = document.getElementById("theme-toggle");
  if (toggle) {
    toggle.textContent = next === "light" ? "☾" : "☀";
    toggle.setAttribute("aria-pressed", String(next === "light"));
  }
  try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch (_error) { /* private mode */ }
}
let storedTheme = "dark";
try { storedTheme = localStorage.getItem(THEME_STORAGE_KEY) || "dark"; } catch (_error) { /* ignore */ }
document.documentElement.dataset.theme = storedTheme === "light" ? "light" : "dark";

const state = {
  catalog: null,
  modAssets: null,
  weapon: null,
  result: null,
  lastPayload: null,
  submittedStats: [],
  buildMode: "actual",
  recRoute: "status",
  requestedFireMode: null,
  weaponPickerTarget: "build",
  assemblyFor: "build",
  activeTool: "analysis",
  buildWeapon: null,
  buildResult: null,
  liveTimer: null,
  liveRequestId: 0,
  loadingTimer: null,
  buildInputMode: "manual",
  manualSlot: 0,
  manualSlots: Array.from({ length: 8 }, () => null),
  manualLocks: Array.from({ length: 8 }, () => false),
  activeConfig: "A",
  buildConfigs: { A: null, B: null, C: null },
  buildStore: {},
  arcaneSelections: [],
  stanceSelection: null,
  stanceLocked: false,
  exilusSelection: null,
  weaponArcane: null,
  weaponArcane2: null, // 空战武器（地面）第二武器赋能槽（主+副赋能池，wfsim 口径）
  frameArcanes: [null, null],
  incarnonChoices: {},
  manualModCategory: "all",
  enemyFaction: "all",
  // 搜索约束（「限制」面板）：必选/禁选 mod path 集合 + 配卡数量范围。
  requiredMods: [],
  forbiddenMods: [],
  // 全局屏蔽（跨武器，本机记忆）与「屏蔽派系歧视卡」开关。
  globalForbiddenMods: readStoredList("wf-global-forbidden-mods"),
  excludeFactionMods: readStoredFlag("wf-exclude-faction-mods"),
  // 同伴武器：机械守护本体（槽位 / 开关）与镀层叠层开关；见 isCompanionWeapon。
  sentinel: null,
  companionPlayerStacks: false,
  exaltedLink: null,
  exaltedResult: null,
  sentinelPanel: null,
  // 真正缺少等级缩放锚点的目标默认在选择器里隐藏；无独立弱点区的目标仍可选。
  enemyShowMissing: false,
  modPickerView: "grid",
  modPickerSlot: 0,
  modPickerKind: "normal",
  arcanePickerSlot: 0,
  modGains: null,
  modGainsSort: false,
  equippedGains: null,
  externalBuffs: [],
  weaponPickerCategory: "all",
  rivenBuilderStats: [],
  rivenBuilderPolarity: null,
  kitgunBase: null,
  kitgunParts: null,
  formaCount: 0,
  formaSlots: {},
  warframeCatalog: null,
  warframeCatalogPromise: null,
  warframePickerKind: "normal",
  warframePickerSlot: 0,
  warframePickerCategory: "all",
  warframeBuild: {
    frame: null,
    aura: null,
    exilus: null,
    normalMods: Array.from({ length: 8 }, () => null),
    normalLocks: Array.from({ length: 8 }, () => false),
    arcanes: [null, null],
    shards: Array.from({ length: 5 }, () => null),
    slotPolarities: { aura: null, exilus: null, normal: Array.from({ length: 8 }, () => null) },
    helminthSlot: null,
    helminthAbility: null,
    invigoration: [],
    applyConditionals: false,
    activeConfig: "A",
    activeForm: "main",
    configs: { A: null, B: null, C: null },
    formConfigs: { main: { A: null, B: null, C: null } },
    store: {},
    result: null,
  },
};

const ui = Object.fromEntries([
  "app-shell", "boot-screen", "page-title",
  "health-dot", "health-label", "build-label", "weapon-count", "coverage-count",
  "sample-button", "reset-button", "export-button", "riven-form",
  "weapon", "weapon-options", "build-weapon-options", "weapon-caption", "disposition-value", "disposition-dots",
  "weapon-issue", "weapon-issue-text", "stat-rows", "stat-row-template", "add-stat",
  "analysis-innate-element-field", "analysis-innate-element-select", "analysis-innate-element-icon", "analysis-preferred-element-select", "analysis-preferred-element-icon",
  "analysis-headshot-chance", "analysis-melee-route-field", "analysis-melee-route-select",
  "form-message", "analyze-button", "riven-stage", "riven-card", "card-name",
  "card-polarity", "card-stats", "card-mr", "card-rerolls",
  "result-badge", "result-idle", "result-loading", "result-error", "result-content",
  "loading-copy", "error-message", "retry-button", "score-orbit", "orbit-value",
  "score-value", "grade-value", "weapon-result-name", "actual-gain", "optimal-gain", "score-context-note",
  "roll-quality", "result-disposition", "contribution-list", "tier-list",
  "tier-filters", "tier-route", "tier-route-note",
  "recommended-negative", "fatal-negative", "fatal-box", "build-mode", "build-slot",
  "build-weapon-name", "build-fire-mode", "build-metric", "damage-metrics",
  "fire-mode-strip", "fire-mode-strip-note", "mod-grid", "analysis-stance", "analysis-incarnon-route", "build-forma", "diagnostics", "diagnostic-count", "diagnostic-list",
  "analysis-tool", "build-tool", "warframe-tool", "weapon-build-form", "build-weapon",
  "build-weapon-caption", "build-disposition", "build-disposition-dots",
  "build-variant-select", "build-variant-caption",
  "build-fire-mode-select", "build-metric-select", "build-element-select", "build-element-icon",
  "build-innate-element-field", "build-innate-element-select", "build-innate-element-icon",
  "build-innate-element-value-field", "build-innate-element-value", "build-innate-element-output",
  "build-incarnon-panel", "build-incarnon-tiers", "build-incarnon-note", "build-incarnon-cycle", "build-incarnon-cycle-note",
  "build-optimize-arcanes", "build-auto-arcane", "build-auto-incarnon", "build-min-fill", "build-max-fill",
  "build-slot-count", "build-slot-output", "build-weapon-issue",
  "build-weapon-issue-text", "build-form-message",
  "build-enemy-select", "build-enemy-search", "build-enemy-factions", "build-enemy-list", "build-enemy-count", "build-enemy-level", "build-steel-path", "build-armour-strip", "build-armour-strip-output",
  "build-enemy-show-missing", "build-enemy-missing-count",
  "build-enemy-eximus", "build-enemy-empowered", "build-enemy-player-count", "build-enemy-archimedea",
  "build-enemy-stats", "build-enemy-stats-context",
  "build-setup-folds", "build-enemy-open", "build-enemy-current", "build-enemy-current-meta", "enemy-picker", "enemy-picker-close",
  "build-aiming", "build-headshot-chance", "build-headshot-output", "build-distance", "build-combo-tier", "build-heavy-attack", "build-damage-model",
  "build-manual-detonation", "build-detonation-batch", "build-detonation-delay",
  "build-config-tabs", "build-config-status", "build-config-copy", "build-config-compare", "build-config-import", "build-config-export", "build-config-import-json", "build-config-import-rabbit", "build-config-export-json", "build-config-export-rabbit", "build-config-import-file", "build-config-compare-output",
  "custom-defense-fields", "build-custom-health", "build-custom-armor", "build-custom-shield", "build-custom-health-type", "build-custom-armor-type", "build-custom-shield-type", "custom-defense-note",
  "build-arcane-list", "special-loadout", "special-mod-slots",
  "arcane-picker", "arcane-picker-close", "arcane-picker-sub", "arcane-picker-search", "arcane-picker-list",
  "manual-slots", "manual-mod-search", "manual-mod-categories", "manual-mod-list", "manual-level-toggle", "manual-clear", "manual-build-summary",
  "mod-picker", "mod-picker-scrim", "mod-picker-close", "mod-picker-title", "mod-picker-sub", "mod-picker-view",
  "fill-optimal-button",
  "capacity-bar", "capacity-readout", "forma-counter", "forma-count", "forma-optimize", "forma-needed", "build-reset-all", "kitgun-assembly-title", "theme-toggle", "compute-button", "compute-button-value", "compute-panel", "compute-machine", "compute-workers", "compute-workers-value", "compute-workers-hint", "compute-low-priority", "compute-status", "compute-default", "compute-close",
  "weapon-picker", "weapon-picker-close", "weapon-picker-sub", "weapon-picker-search", "weapon-picker-categories", "weapon-picker-list",
  "live-hud", "live-hud-pulse", "live-hud-metrics", "build-bench", "build-detail",
  "weapon-build-idle", "weapon-build-loading",
  "weapon-build-error", "weapon-build-error-message", "weapon-build-content",
  "weapon-build-type", "weapon-build-name", "weapon-build-fire-mode", "weapon-build-archetype",
  "weapon-build-metric", "weapon-build-stat-band",
  "weapon-build-element-note", "weapon-build-damage-types", "weapon-build-fire-modes",
  "weapon-build-slot-summary",
  "manual-results", "probability-content", "timeline-content",
  "weapon-build-diagnostic-count", "weapon-build-diagnostic-list", "toast-region",
  "part-values", "part-values-run", "part-values-status", "part-values-content",
  "warframe-catalog-status", "warframe-frame-select", "warframe-frame-open", "warframe-frame-select-visual", "warframe-frame-select-name", "warframe-frame-select-description", "warframe-frame-caption", "warframe-portrait", "warframe-profile-name", "warframe-profile-description", "warframe-passive",
  "warframe-apply-conditionals", "warframe-helminth-slot", "warframe-helminth-slot-open", "warframe-helminth-slot-visual", "warframe-helminth-slot-name", "warframe-helminth-slot-description", "warframe-helminth-ability", "warframe-helminth-ability-open", "warframe-helminth-ability-visual", "warframe-helminth-ability-name", "warframe-helminth-ability-source", "warframe-helminth-description", "warframe-invigoration-open", "warframe-invigoration-name", "warframe-invigoration-description",
  "warframe-config-tabs", "warframe-config-status", "warframe-config-copy", "warframe-config-import", "warframe-config-export", "warframe-config-import-json", "warframe-config-import-rabbit", "warframe-config-export-json", "warframe-config-export-rabbit", "warframe-config-import-file", "warframe-clear", "warframe-message", "warframe-result-name", "warframe-result-kicker", "warframe-capacity-readout", "warframe-capacity-bar", "warframe-forma-readout", "warframe-loading", "warframe-build-content",
  "warframe-form-switch", "warframe-form-tabs", "warframe-form-switch-note", "warframe-shard-inheritance-note",
  "warframe-special-slots", "warframe-normal-slots", "warframe-arcane-slots", "warframe-shard-slots", "warframe-effect-status", "warframe-panel-grid", "warframe-ability-grid",
  "warframe-diagnostics", "warframe-diagnostic-count", "warframe-diagnostic-list", "warframe-picker", "warframe-picker-title", "warframe-picker-sub", "warframe-picker-search", "warframe-picker-close", "warframe-picker-categories", "warframe-picker-list",
  "rabbit-dialog-scrim", "rabbit-dialog", "rabbit-dialog-title", "rabbit-dialog-close", "rabbit-export-form", "rabbit-import-panel", "rabbit-target", "rabbit-archetype", "rabbit-build-title", "rabbit-summary", "rabbit-usage", "rabbit-cautions", "rabbit-export-status", "rabbit-generate", "rabbit-code-result", "rabbit-code-count", "rabbit-code", "rabbit-copy", "rabbit-import-code", "rabbit-import-status", "rabbit-import-apply",
].map((id) => [id, document.getElementById(id)]));

const TYPE_LABELS = {
  rifle: "步枪", shotgun: "霰弹枪", pistol: "手枪", kitgun: "组合枪",
  melee: "近战", zaw: "组合近战", archgun: "空战武器(地面)", companion: "同伴武器",
};

const METRIC_LABELS = {
  killsPerMinute: "标准靶 KPM",
  windowedDps: "窗口 DPS",
  shotDamage: "单发伤害", burstDps: "爆发 DPS", sustainedDps: "持续 DPS",
  attackDps: "攻击 DPS", heavyDamage: "重击伤害", heavyAttackDps: "重击 DPS",
  statusSustainedDps: "持续 DPS（触发+直伤）", targetSustainedDps: "目标持续 DPS",
  objectiveScore: "标准靶 KPM",
};

const METRIC_KEYS = ["shotDamage", "burstDps", "sustainedDps", "attackDps", "heavyDamage", "heavyAttackDps"];
const DAMAGE_TYPE_LABELS = {
  DT_IMPACT: "冲击", DT_PUNCTURE: "穿刺", DT_SLASH: "切割",
  DT_FIRE: "火焰", DT_FREEZE: "冰冻", DT_ELECTRICITY: "电击", DT_POISON: "毒素",
  DT_EXPLOSION: "爆炸", DT_RADIATION: "辐射", DT_GAS: "毒气",
  DT_MAGNETIC: "磁力", DT_VIRAL: "病毒", DT_CORROSIVE: "腐蚀",
  DT_RADIANT: "虚空", DT_FINISHER: "处决", DT_TRUE: "真实",
};

// In game <DT_SLASH_COLOR> renders as the damage-type glyph and name. Most
// localized lines repeat the name after the token; some (Hunter Munitions) don't.
function damageTokenText(text) {
  return String(text ?? "").replace(/<(\/?)(DT_[A-Z_]+?)(?:_COLOR)?>/g, (token, closing, dt, offset, whole) => {
    const name = DAMAGE_TYPE_LABELS[dt];
    if (closing || !name) return "";
    return whole.slice(offset + token.length).trimStart().startsWith(name) ? "" : name;
  });
}
const TRIGGER_LABELS = {
  Auto: "自动", AutoBurst: "自动点射", SemiAuto: "半自动", Burst: "点射",
  Charge: "蓄力", Held: "持续", TriggerContinous: "持续",
  Activated: "激活", SemiAutoFireOnUp: "释放射击",
};
const VARIANT_LABELS = {
  VT_NORMAL: "基础型", VT_PRIME: "Prime", VT_VANDAL: "Vandal", VT_WRAITH: "Wraith",
  VT_PRISMA: "棱晶", VT_DEX: "Dex", VT_SYNDICATE: "集团", VT_KUVA: "赤毒",
  VT_TENET: "信条", VT_CODA: "科达",
};
const POLARITY_IMAGES = {
  AP_ATTACK: "/assets/polarities/madurai.png",
  AP_DEFENSE: "/assets/polarities/vazarin.png",
  AP_TACTIC: "/assets/polarities/naramon.png",
  AP_UMBRA: "/assets/polarities/umbra.png",
  AP_POWER: "/assets/polarities/power.png",
  AP_WARD: "/assets/polarities/ward.png",
  AP_PRECEPT: "/assets/polarities/precept.png",
  AP_FUSION: "/assets/polarities/aura.png",
  AP_UNIVERSAL: "/assets/polarities/universal.png",
  AP_ANY: "/assets/polarities/any.png",
};
// All supported polarities have a real game PNG.  Keep the fallback blank so a
// missing asset is diagnosed by the browser rather than being replaced by a
// misleading ASCII glyph ("=", "W", etc.).
const POLARITY_GLYPHS = Object.freeze({});
// A Riven card only ever carries the three ordinary MOD polarities.  Stance,
// Umbra, Aura/Exilus and universal polarities belong to loadout slots, not to
// the random polarity printed on a Riven.
const RIVEN_CARD_POLARITIES = Object.freeze(["AP_ATTACK", "AP_DEFENSE", "AP_TACTIC"]);
const RIVEN_FACTION_CODES = Object.freeze(["C", "G", "I"]);

function finite(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

const BUILD_CONFIG_SCHEMA = 2;
const BUILD_CONFIG_STORAGE_KEY = "wf-riven-portable-build-configs-v1";
const RABBIT_FULL_PREFIX = "WRB1.";
const RABBIT_CONFIG_PREFIX = "WRC1.";
const RABBIT_COMMAND_LIMIT = 2900;
const RABBIT_WIRE_SCHEMA = 2;
const RABBIT_TEXT_BASE = 0x4E00;
const RABBIT_TEXT_BITS = 14;
const RABBIT_ARCHETYPES = Object.freeze({
  weapon: [
    ["crit", "暴击流"], ["status", "异况流"], ["heavy-attack", "重击流"], ["aoe", "清图流"], ["boss", "Boss"],
  ],
  warframe: [
    ["range", "范围流"], ["strength", "强度流"], ["survival", "生存流"], ["weapon-platform", "武器流"],
  ],
});
let rabbitDialogKind = "weapon";

function readBuildStore() {
  try {
    const raw = localStorage.getItem(BUILD_CONFIG_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_error) {
    return {};
  }
}

function writeBuildStore() {
  try { localStorage.setItem(BUILD_CONFIG_STORAGE_KEY, JSON.stringify(state.buildStore)); } catch (_error) { /* offline/private mode */ }
}

function captureBuildConfig() {
  const get = (id, fallback = null) => ui[id] ? ui[id].value : fallback;
  const checked = (id) => Boolean(ui[id]?.checked);
  const mods = state.manualSlots.flatMap((mod, slot) => (mod && !mod.__riven) ? ({
    path: mod.path,
    slot,
    rank: Number(mod.rank ?? mod.maxRank ?? 0),
  }) : []);
  const rivenSlot = state.manualSlots.findIndex((mod) => mod && mod.__riven);
  const rivenMod = rivenSlot >= 0 ? state.manualSlots[rivenSlot] : null;
  return {
    schema: BUILD_CONFIG_SCHEMA,
    buildLabel: state.catalog?.buildLabel || "OFFLINE",
    weapon: state.buildWeapon?.path || null,
    fireMode: Number(get("build-fire-mode-select", 0) || 0),
    metric: get("build-metric-select", ""),
    elementTarget: get("build-element-select", "") || null,
    innateElement: get("build-innate-element-select", "") || null,
    innateElementValue: Number(get("build-innate-element-value", 60) || 60) / 100,
    slotCount: Number(get("build-slot-count", 8) || 8),
    mode: state.buildInputMode,
    triggerPolicy: document.getElementById("trigger-policy-select")?.value || "emergent",
    configId: state.activeConfig,
    configSchema: BUILD_CONFIG_SCHEMA,
    mods,
    formaSlots: Object.keys(state.formaSlots).length ? { ...state.formaSlots } : undefined,
    // Special-slot Forma is exported explicitly as well as in formaSlots so
    // consumers do not have to infer stance/Exilus from ordinary-slot indexes.
    specialSlotPolarities: Object.keys(specialSlotPolaritiesPayload()).length ? specialSlotPolaritiesPayload() : undefined,
    sentinel: captureSentinelConfig(),
    exaltedLink: captureExaltedLink(),
    riven: rivenMod ? { slot: rivenSlot, polarity: rivenFixedPolarity(rivenMod, rivenSlot), stats: rivenMod.stats.map((s) => ({ code: s.code, value: Number(s.value || 0), negative: Boolean(s.negative) })) } : null,
    enemy: get("build-enemy-select", "") || null,
    level: Number(get("build-enemy-level", 160) || 160),
    steelPath: checked("build-steel-path"),
    enemyEximus: checked("build-enemy-eximus"),
    enemyEmpowered: checked("build-enemy-empowered"),
    enemyPlayerCount: Number(get("build-enemy-player-count", 1) || 1),
    enemyArchimedea: checked("build-enemy-archimedea"),
    armourStrip: Number(get("build-armour-strip", 0) || 0),
    headshotChance: Number(get("build-headshot-chance", 0) || 0),
    distance: Number(get("build-distance", 0) || 0),
    detonationBatchSize: ui["build-manual-detonation"]?.hidden === false ? Number(get("build-detonation-batch", 1)) : 1,
    detonationDelaySeconds: ui["build-manual-detonation"]?.hidden === false ? Number(get("build-detonation-delay", 0)) : 0,
    combatState: combatStatePayload(),
    comboTier: Number(get("build-combo-tier", 0) || 0),
    heavyAttack: checked("build-heavy-attack"),
    damageModel: get("build-damage-model", "panel"),
    customDefense: {
      health: Number(get("build-custom-health", 100000) || 100000),
      armor: Number(get("build-custom-armor", 0) || 0),
      shield: Number(get("build-custom-shield", 0) || 0),
      healthType: get("build-custom-health-type", "RK_CLONED_FLESH"),
      armorType: get("build-custom-armor-type", "RK_ARMOR"),
      shieldType: get("build-custom-shield-type", "RK_HEAVY_SHIELD"),
    },
    stancePath: state.stanceSelection?.path || null,
    exilus: compactRankedSelection(state.exilusSelection),
    weaponArcane: compactRankedSelection(state.weaponArcane),
    weaponArcane2: compactRankedSelection(state.weaponArcane2),
    frameArcanes: state.frameArcanes.filter(Boolean).map(compactRankedSelection),
    externalBuffs: state.externalBuffs.map((buff) => ({ ...buff })),
    incarnonChoices: { ...state.incarnonChoices },
    incarnonCycle: Boolean(ui["build-incarnon-cycle"]?.checked),
    aiming: Boolean(ui["build-aiming"]?.checked),
    // 「限制」面板：搜索约束随配置槽持久化。
    requiredMods: state.requiredMods.length ? [...state.requiredMods] : undefined,
    forbiddenMods: state.forbiddenMods.length ? [...state.forbiddenMods] : undefined,
    minFill: scopeFillValue("build-min-fill"),
    maxFill: scopeFillValue("build-max-fill"),
    optimizeWithArcanes: checked("build-optimize-arcanes") ? undefined : false,
    autoArcane: checked("build-auto-arcane") || undefined,
    autoIncarnon: checked("build-auto-incarnon") || undefined,
    // 最优紫卡求解的预算档位（10/20/30/60s）随配置持久化。
    rivenSolveBudget: state.rivenSolveBudget || 10,
  };
}

function combatStatePayload() {
  const result = {};
  document.querySelectorAll('[data-combat-state]').forEach((control) => {
    const key = control.dataset.combatState;
    if (control.closest('[data-projectile-policy]')?.hidden) return;
    if (['zymosChildContacts','zymosChildArrivalSeconds'].includes(key) && document.querySelector('[data-combat-state="zymosChildOverlap"]')?.value !== 'ideal-contact') return;
    if (['grimoireCoverageSeconds','grimoireExpiryDistance'].includes(key) && document.querySelector('[data-combat-state="grimoireStrategy"]')?.value !== 'single-occupant') return;
    if (key === 'phantasmaChildArrivalSeconds' && document.querySelector('[data-combat-state="phantasmaChildOverlap"]')?.value !== 'ideal-contact') return;
    if (control.type === 'checkbox') {
      // Default-on switches are only sent when turned off.
      if ('defaultOn' in control.dataset) { if (!control.checked) result[key] = false; }
      else if (control.checked) result[key] = true;
    } else if (control.value !== '') {
      result[key] = control.type === 'number' ? Number(control.value) : control.value;
    }
  });
  document.querySelectorAll('[data-combat-gear]').forEach((control) => {
    if (control.value === 'empty') (result.emptySlots ||= []).push(control.dataset.combatGear);
    else if (control.value) (result.equippedWeapons ||= []).push(control.value);
  });
  document.querySelectorAll('[data-combat-orbtype]').forEach((control) => {
    if (control.value !== '') (result.orbAbsorbedDamageTypes ||= {})[control.dataset.combatOrbtype] = Number(control.value);
  });
  return result;
}

function restoreCombatState(value = {}) {
  const vector = Array.isArray(value.orbAbsorbedDamageTypes) ? Object.fromEntries(value.orbAbsorbedDamageTypes) : value.orbAbsorbedDamageTypes || {};
  const host = document.getElementById('build-orb-damage-vector');
  if (host && !host.children.length) {
    const choices = document.querySelector('[data-combat-state="orbAbsorbedDamageType"]')?.options || [];
    Array.from(choices).filter((option) => option.value).forEach((option) => {
      const label = document.createElement('label'); label.className = 'field';
      const name = document.createElement('span'); name.textContent = option.textContent;
      const input = document.createElement('input'); input.type = 'number'; input.min = '0'; input.step = '1'; input.placeholder = '未设置'; input.dataset.combatOrbtype = option.value;
      label.append(name, input); host.append(label);
    });
  }
  document.querySelectorAll('[data-combat-orbtype]').forEach((control) => { control.value = vector[control.dataset.combatOrbtype] ?? ''; });
  document.querySelectorAll('[data-combat-state]').forEach((control) => {
    if (control.type === 'checkbox') control.checked = 'defaultOn' in control.dataset ? value[control.dataset.combatState] !== false : Boolean(value[control.dataset.combatState]);
    else control.value = value[control.dataset.combatState] ?? control.dataset.defaultValue ?? '';
  });
  refreshProjectileStrategyControls();
  refreshMeleeRouteOptions(document.getElementById("build-melee-route-select"), state.buildWeapon, "build");
  document.querySelectorAll('[data-combat-gear]').forEach((control) => {
    const family = control.dataset.combatGear;
    const weapons = state.catalog?.weapons || [];
    const belongs = (weapon) => family === 'melee' ? ['melee', 'zaw'].includes(weapon.weaponType) : weapon.slot === family;
    const options = weapons.filter(belongs);
    control.replaceChildren(new Option('未设置', ''), new Option('空槽', 'empty'), ...options.map((w) => new Option(w.nameZh || w.nameEn, w.path)));
    control.value = (value.emptySlots || []).includes(family) ? 'empty' : (value.equippedWeapons || []).find((path) => options.some((w) => w.path === path)) || '';
  });
}

function persistActiveBuildConfig() {
  if (!state.buildWeapon) return;
  state.buildConfigs[state.activeConfig] = captureBuildConfig();
  state.buildStore[state.buildWeapon.path] = state.buildConfigs;
  state.buildStore.__lastSelection = { weapon: state.buildWeapon.path, config: state.activeConfig };
  writeBuildStore();
  if (ui["build-config-status"]) ui["build-config-status"].textContent = `配置 ${state.activeConfig} 已保存`;
}

function loadBuildConfigsForWeapon(weapon) {
  const stored = weapon?.path ? state.buildStore[weapon.path] : null;
  state.buildConfigs = { A: stored?.A || null, B: stored?.B || null, C: stored?.C || null };
  const selected = state.buildStore.__lastSelection;
  state.activeConfig = selected?.weapon === weapon?.path && ["A", "B", "C"].includes(selected.config) ? selected.config : "A";
  updateConfigTabs();
}

function updateConfigTabs() {
  ui["build-config-tabs"]?.querySelectorAll("[data-config]").forEach((button) => {
    const active = button.dataset.config === state.activeConfig;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
}

function setControlValue(id, value) {
  if (ui[id] && value !== undefined && value !== null) ui[id].value = String(value);
}

function setBuildModeUI(mode) {
  state.buildInputMode = mode === "auto" ? "auto" : "manual";
  document.querySelectorAll("[data-build-mode]").forEach((button) => {
    const active = button.dataset.buildMode === state.buildInputMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  if (ui["build-bench"]) ui["build-bench"].classList.toggle("is-auto", state.buildInputMode === "auto");
}

function normalizeArcaneSelections(items) {
  const records = new Map(arcaneRecords().map((arcane) => [arcane.path, arcane]));
  let warframeCount = 0;
  let weaponCount = 0;
  return (Array.isArray(items) ? items : []).flatMap((item) => {
    if (!item?.path) return [];
    const isWarframe = (records.get(item.path)?.slotKind || item.slotKind) === "warframe";
    if (isWarframe ? warframeCount >= 2 : weaponCount >= weaponArcaneSlotCount()) return [];
    if (isWarframe) warframeCount += 1;
    else weaponCount += 1;
    return [{ ...item }];
  });
}

function compactRankedSelection(item) {
  if (!item?.path) return null;
  const result = { path: item.path, rank: Number(item.rank ?? item.maxRank ?? 0) };
  // 赋能开关（强制触发 / 限定层数）随配置持久化；模拟请求再翻译成 stacks/uptime。
  if (item.forceProc) result.forceProc = true;
  if (Number.isInteger(item.fixedStacks) && item.fixedStacks > 0) result.fixedStacks = item.fixedStacks;
  return result;
}

function arcaneSimulationSelection(item) {
  // 默认不携带 stacks/uptime，后端按武器面板推导触发；开关打开时改为手动状态：
  // 强制触发 = 满层且全程覆盖，限定层数 = 固定层数全程覆盖。
  const base = compactRankedSelection(item);
  if (!base) return null;
  const controls = arcaneStateControls(item);
  const maxStacks = Math.max(1, Number(controls.forceStacks ?? item.trigger?.maxStacks ?? 1) || 1);
  if (item.forceProc && controls.force) return { ...base, stacks: maxStacks, uptime: 1 };
  if (Number.isInteger(item.fixedStacks) && item.fixedStacks > 0 && controls.stacks) {
    return { ...base, stacks: clamp(item.fixedStacks, 1, Number(controls.stacks)), uptime: 1 };
  }
  return base;
}

// 槽位开关以目录为准（存档里的旧 trigger 不可信）：force = 强制触发是否有意义，
// stacks = 「限定层数」上限，note = 这张卡在解算里怎么算。
function arcaneStateControls(item) {
  const record = arcaneRecords().find((arcane) => arcane.path === item?.path);
  return record?.stateControls || item?.stateControls || {};
}

// ── 全局计算设置（顶栏「算力」）：核心数与优先级由用户决定，后端调度器即时生效 ──
const compute = { settings: null, timer: 0, poll: 0 };

function renderComputeSettings() {
  const s = compute.settings;
  if (!s) return;
  ui["compute-button-value"].textContent = `${s.workers} 核`;
  ui["compute-workers"].max = String(s.logicalCores);
  ui["compute-workers"].value = String(s.workers);
  ui["compute-workers-value"].textContent = `${s.workers}${s.workers === s.defaultWorkers ? "（默认）" : ""}`;
  ui["compute-low-priority"].checked = Boolean(s.lowPriority);
  ui["compute-machine"].textContent = `本机 ${s.physicalCores} 个物理核心 · ${s.logicalCores} 个逻辑线程；默认 ${s.defaultWorkers}（物理核心数再加四分之一）`;
  const over = s.workers > s.physicalCores ? "超过物理核心数时按超线程运行，单核更慢、总量更多。" : "紫卡分析、自动配装和 MOD 收益共用这些核心。";
  ui["compute-workers-hint"].textContent = s.workers <= 1 ? "1 个核心：全部在主进程里串行计算。" : over;
  ui["compute-status"].textContent = s.running || s.queued ? `正在计算 ${s.running} 项 · 排队 ${s.queued} 项` : "当前空闲";
}

async function loadComputeSettings() {
  try {
    const response = await fetch("/api/settings");
    if (!response.ok) return;
    compute.settings = (await response.json()).compute;
    renderComputeSettings();
  } catch { /* 引擎未就绪时保持占位 */ }
}

function saveComputeSettings(patch) {
  compute.settings = { ...compute.settings, ...patch };
  renderComputeSettings();
  clearTimeout(compute.timer);
  compute.timer = setTimeout(async () => {
    try {
      const response = await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ compute: { workers: compute.settings.workers, lowPriority: compute.settings.lowPriority } }) });
      if (response.ok) { compute.settings = (await response.json()).compute; renderComputeSettings(); }
      else toast("计算设置保存失败");
    } catch { toast("计算设置保存失败"); }
  }, 250);
}

function setComputePanel(open) {
  ui["compute-panel"].hidden = !open;
  ui["compute-button"].setAttribute("aria-expanded", String(open));
  clearInterval(compute.poll);
  if (open) { loadComputeSettings(); compute.poll = setInterval(loadComputeSettings, 1500); }
}

function setupComputeSettings() {
  if (!ui["compute-button"]) return;
  loadComputeSettings();
  ui["compute-button"].addEventListener("click", (event) => { event.stopPropagation(); setComputePanel(ui["compute-panel"].hidden); });
  ui["compute-panel"].addEventListener("click", (event) => event.stopPropagation());
  ui["compute-close"].addEventListener("click", () => setComputePanel(false));
  ui["compute-workers"].addEventListener("input", () => saveComputeSettings({ workers: Number(ui["compute-workers"].value) }));
  ui["compute-low-priority"].addEventListener("change", () => saveComputeSettings({ lowPriority: ui["compute-low-priority"].checked }));
  ui["compute-default"].addEventListener("click", () => saveComputeSettings({ workers: compute.settings?.defaultWorkers ?? 1, lowPriority: true }));
  document.addEventListener("click", () => { if (!ui["compute-panel"].hidden) setComputePanel(false); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !ui["compute-panel"].hidden) setComputePanel(false); });
}

function syncArcaneSelections() {
  state.arcaneSelections = [state.weaponArcane, state.weaponArcane2, ...state.frameArcanes].filter(Boolean).map((item) => ({ ...item }));
}

function applyBuildConfig(config) {
  const restored = migrateLegacyBuildConfig(config, state.catalog?.legacyModReplacements);
  const migrated = restored.config !== config;
  config = restored.config;
  if (migrated && state.buildWeapon?.path) {
    state.buildConfigs[state.activeConfig] = config;
    state.buildStore[state.buildWeapon.path] = state.buildConfigs;
    writeBuildStore();
  }
  if (!config || typeof config !== "object") {
    state.manualSlots = Array.from({ length: 8 }, () => null);
    resetSpecialSelections();
    state.incarnonChoices = {};
    if (ui["build-incarnon-cycle"]) ui["build-incarnon-cycle"].checked = false;
    if (ui["build-aiming"]) ui["build-aiming"].checked = false;
    setControlValue("build-detonation-batch", 1);
    setControlValue("build-detonation-delay", 0);
    restoreCombatState();
    state.requiredMods = [];
    state.forbiddenMods = [];
    restoreSentinelConfig(null);
    renderCompanionPanel();
    restoreExaltedLink(null);
    renderExaltedPanel();
    renderSentinelBench();
    scheduleSentinelEvaluate();
    setControlValue("build-min-fill", "");
    setControlValue("build-max-fill", "");
    if (ui["build-optimize-arcanes"]) ui["build-optimize-arcanes"].checked = true;
    if (ui["build-auto-arcane"]) ui["build-auto-arcane"].checked = false;
    if (ui["build-auto-incarnon"]) ui["build-auto-incarnon"].checked = false;
    renderScopeLists();
    renderManualSlots();
    renderManualMods();
    renderSpecialSlots();
    renderArcaneSelections();
    return;
  }
  setControlValue("build-fire-mode-select", config.fireMode ?? 0);
  const triggerPolicyControl = document.getElementById("trigger-policy-select");
  if (triggerPolicyControl) triggerPolicyControl.value = config.triggerPolicy === "assumed_max" ? "assumed_max" : "emergent";
  refreshBuildMetrics();
  setControlValue("build-metric-select", config.metric || ui["build-metric-select"]?.value || "");
  setControlValue("build-element-select", config.elementTarget || "");
  setControlValue("build-innate-element-select", config.innateElement || defaultInnateElement(state.buildWeapon));
  setControlValue("build-innate-element-value", clamp(Math.round(Number(config.innateElementValue ?? 0.60) * 100), 25, 60));
  setControlValue("build-slot-count", clamp(Number(config.slotCount ?? 8), 4, 8));
  if (ui['build-slot-output']) ui['build-slot-output'].textContent = ui['build-slot-count'].value;
  setSliderVisual(ui['build-slot-count']);
  setControlValue("build-enemy-select", config.enemy || ui["build-enemy-select"]?.value || "");
  fillBuildEnemies();
  setControlValue("build-enemy-level", config.level ?? 160);
  setControlValue("build-armour-strip", config.armourStrip ?? 0);
  setControlValue("build-headshot-chance", config.headshotChance ?? 0);
  setControlValue("build-distance", config.distance ?? 0);
  setControlValue("build-detonation-batch", config.detonationBatchSize ?? 1);
  setControlValue("build-detonation-delay", config.detonationDelaySeconds ?? 0);
  restoreCombatState(config.combatState);
  setControlValue("build-combo-tier", config.comboTier ?? 0);
  setControlValue("build-damage-model", config.damageModel || "panel");
  if (ui["build-steel-path"]) ui["build-steel-path"].checked = Boolean(config.steelPath);
  if (ui["build-heavy-attack"]) ui["build-heavy-attack"].checked = Boolean(config.heavyAttack);
  if (ui["build-enemy-eximus"]) ui["build-enemy-eximus"].checked = Boolean(config.enemyEximus);
  if (ui["build-enemy-empowered"]) ui["build-enemy-empowered"].checked = Boolean(config.enemyEmpowered);
  if (ui["build-enemy-archimedea"]) ui["build-enemy-archimedea"].checked = Boolean(config.enemyArchimedea);
  setControlValue("build-enemy-player-count", clamp(Number(config.enemyPlayerCount ?? 1), 1, 4));
  syncEmpoweredPlayerCount();
  const defense = config.customDefense || {};
  setControlValue("build-custom-health", defense.health ?? 100000);
  setControlValue("build-custom-armor", defense.armor ?? 0);
  setControlValue("build-custom-shield", defense.shield ?? 0);
  setControlValue("build-custom-health-type", defense.healthType || "RK_CLONED_FLESH");
  setControlValue("build-custom-armor-type", defense.armorType || "RK_ARMOR");
  setControlValue("build-custom-shield-type", defense.shieldType || "RK_HEAVY_SHIELD");
  setBuildModeUI(config.mode);
  const records = new Map([...(state.catalog?.manualMods || []), ...(state.catalog?.manualModVariants || [])].map((mod) => [mod.path, mod]));
  const configMods = Array.isArray(config.mods) ? config.mods : [];
  state.manualSlots = Array.from({ length: 8 }, (_, index) => {
    const item = configMods.find((candidate, position) => (Number.isInteger(candidate?.slot) ? candidate.slot : position) === index);
    if (!item?.path) return null;
    const record = records.get(item.path) || { path: item.path, nameInternal: item.path, selectable: true, maxRank: 0 };
    return { ...record, ...item, rank: Number(item.rank ?? record.maxRank ?? 0) };
  });
  if (Array.isArray(config.riven?.stats) && config.riven.stats.length) {
    const emptySlot = state.manualSlots.findIndex((slot) => !slot);
    const savedSlot = Number(config.riven.slot);
    const target = Number.isInteger(savedSlot) && savedSlot >= 0 && savedSlot < state.manualSlots.length ? savedSlot : (emptySlot >= 0 ? emptySlot : state.manualSlots.length - 1);
    state.manualSlots[target] = {
      __riven: true,
      path: "__riven__",
      nameZh: `${state.buildWeapon?.nameZh || "紫卡"} (自定义)`,
      nameEn: "Custom Riven",
      maxRank: 8,
      rank: 8,
      rivenPolarity: config.riven.polarity || null,
      stats: config.riven.stats.map((s) => ({ ...s })),
    };
  }
  restoreSpecialSelections(config);
  state.externalBuffs = normalizeExternalBuffs(config.externalBuffs);
  state.formaSlots = {};
  if (config.formaSlots && typeof config.formaSlots === "object") {
    for (const [key, value] of Object.entries(config.formaSlots)) {
      const index = Number(key);
      if (Number.isInteger(index) && index >= 0 && index < 10 && typeof value === "string" && value) state.formaSlots[index] = value;
    }
  }
  // 旧配置里的紫卡可能存成了紫卡不会有的极性（曾允许 Zenurik/Unairu/Penjaga）：
  // 换成合法极性，为它准备的槽位极化一起跟过去。
  const savedRivenSlot = state.manualSlots.findIndex((mod) => mod?.__riven);
  if (savedRivenSlot >= 0 && config.riven?.polarity && !RIVEN_POLARITY_CHOICES.includes(config.riven.polarity)) {
    const riven = state.manualSlots[savedRivenSlot];
    riven.rivenPolarity = null;
    riven.rivenPolarity = rivenFixedPolarity(riven, savedRivenSlot);
    if (state.formaSlots[savedRivenSlot] === config.riven.polarity) state.formaSlots[savedRivenSlot] = riven.rivenPolarity;
  }
  if (config.specialSlotPolarities && typeof config.specialSlotPolarities === "object") {
    for (const [kind, value] of Object.entries(config.specialSlotPolarities)) {
      const index = specialSlotIndex(kind);
      if (index === null || typeof value !== "string" || !value) continue;
      const native = normalizedSpecialPolarity(state.buildWeapon?.specialSlots?.[kind]?.slotPolarity);
      const desired = normalizedSpecialPolarity(value);
      if (desired && desired !== native) state.formaSlots[index] = desired;
      else if (desired === native || !desired) delete state.formaSlots[index];
    }
  }
  refreshStanceSelection();
  refreshFormaCount();
  state.rivenBuilderStats = Array.isArray(config.riven?.stats) ? config.riven.stats.map((s) => ({ ...s })) : [];
  state.incarnonChoices = config.incarnonChoices && typeof config.incarnonChoices === "object" ? { ...config.incarnonChoices } : {};
  if (ui["build-incarnon-cycle"]) ui["build-incarnon-cycle"].checked = Boolean(config.incarnonCycle);
  if (ui["build-aiming"]) ui["build-aiming"].checked = Boolean(config.aiming);
  if (ui["build-incarnon-cycle-note"]) ui["build-incarnon-cycle-note"].textContent = config.incarnonCycle ? "真实循环（弱点充能 / 实际弹池）" : "常驻灵化（默认）";
  // 「限制」面板状态恢复。
  state.requiredMods = Array.isArray(config.requiredMods) ? [...config.requiredMods] : [];
  state.forbiddenMods = Array.isArray(config.forbiddenMods) ? [...config.forbiddenMods] : [];
  setControlValue("build-min-fill", config.minFill ?? "");
  setControlValue("build-max-fill", config.maxFill ?? "");
  if (ui["build-optimize-arcanes"]) ui["build-optimize-arcanes"].checked = config.autoArcane === true || config.optimizeWithArcanes !== false;
  if (ui["build-auto-arcane"]) ui["build-auto-arcane"].checked = config.autoArcane === true;
  if (ui["build-auto-incarnon"]) ui["build-auto-incarnon"].checked = config.autoIncarnon === true;
  state.rivenSolveBudget = [10, 20, 30, 60].includes(Number(config.rivenSolveBudget)) ? Number(config.rivenSolveBudget) : 10;
  renderScopeLists();
  refreshScenarioLabels();
  setElementControlIcon(ui["build-element-select"], ui["build-element-icon"]);
  setElementControlIcon(ui["build-innate-element-select"], ui["build-innate-element-icon"]);
  if (ui["build-innate-element-value"] && ui["build-innate-element-output"]) {
    const innateValue = clamp(Number(ui["build-innate-element-value"].value || 60), 25, 60);
    ui["build-innate-element-value"].value = String(innateValue);
    ui["build-innate-element-output"].textContent = `${innateValue}%`;
    setSliderVisual(ui["build-innate-element-value"]);
  }
  updateCustomDamageControls();
  renderManualSlots();
  renderManualMods();
  renderSpecialSlots();
  renderArcaneSelections();
  renderExternalBuffs();
  renderIncarnonChoices();
  restoreSentinelConfig(config);
  renderCompanionPanel();
  restoreExaltedLink(config);
  renderExaltedPanel();
  renderSentinelBench();
  scheduleSentinelEvaluate();
}

function switchBuildConfig(name) {
  if (!/^[ABC]$/.test(name) || name === state.activeConfig) return;
  persistActiveBuildConfig();
  state.activeConfig = name;
  updateConfigTabs();
  applyBuildConfig(state.buildConfigs[name]);
  if (ui["build-config-status"]) ui["build-config-status"].textContent = `配置 ${name}${state.buildConfigs[name] ? "已载入" : "为空"}`;
}

function compareBuildConfigs() {
  persistActiveBuildConfig();
  const rows = ["A", "B", "C"].map((name) => `${name}: ${state.buildConfigs[name] ? JSON.stringify(state.buildConfigs[name], null, 2) : "(空)"}`);
  const output = ui["build-config-compare-output"];
  if (!output) return;
  output.hidden = !output.hidden;
  if (!output.hidden) output.textContent = rows.join("\n\n");
}

function copyBuildConfig() {
  persistActiveBuildConfig();
  const names = ["A", "B", "C"];
  const target = names[(names.indexOf(state.activeConfig) + 1) % names.length];
  state.buildConfigs[target] = JSON.parse(JSON.stringify(state.buildConfigs[state.activeConfig] || captureBuildConfig()));
  state.buildStore[state.buildWeapon?.path] = state.buildConfigs;
  writeBuildStore();
  if (ui["build-config-status"]) ui["build-config-status"].textContent = `已复制到配置 ${target}`;
}

function exportBuildConfig() {
  persistActiveBuildConfig();
  const payload = { schema: BUILD_CONFIG_SCHEMA, buildLabel: state.catalog?.buildLabel || "OFFLINE", configId: state.activeConfig, config: state.buildConfigs[state.activeConfig] || captureBuildConfig() };
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `wf-riven-build-${state.activeConfig}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function importBuildConfig(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.addEventListener("load", () => {
    try {
      const parsed = JSON.parse(String(reader.result || ""));
      const config = parsed.config || parsed;
      const schema = Number(parsed.schema ?? config.schema ?? BUILD_CONFIG_SCHEMA);
      if (!config || ![1, BUILD_CONFIG_SCHEMA].includes(schema)) throw new Error("配置文件格式不兼容");
      const target = config.weapon || parsed.weapon;
      if (target) {
        const weapon = state.catalog?.weapons?.find((item) => item.path === target);
        if (!weapon) throw new Error("配置中的武器不在当前目录");
        if (state.buildWeapon?.path !== weapon.path) selectBuildWeapon(weapon);
      }
      state.buildConfigs[state.activeConfig] = config;
      applyBuildConfig(config);
      scheduleLiveBuild();
      persistActiveBuildConfig();
      toast(`已导入配置 ${state.activeConfig}`, "success");
    } catch (error) {
      toast(error.message || "配置导入失败", "error");
    }
  });
  reader.readAsText(file);
}

function rabbitTextLines(value) {
  return String(value || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
}

function rabbitBase64Url(bytes) {
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function rabbitBase64Bytes(value) {
  const base64 = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(base64 + "=".repeat((4 - base64.length % 4) % 4));
  return Uint8Array.from(binary, (char) => char.charCodeAt(0));
}

function rabbitTextPack(bytes) {
  const padding = (RABBIT_TEXT_BITS - bytes.length * 8 % RABBIT_TEXT_BITS) % RABBIT_TEXT_BITS;
  let buffer = 0;
  let bits = 0;
  let output = `K${String.fromCharCode(RABBIT_TEXT_BASE + padding)}`;
  for (const byte of bytes) {
    buffer = buffer * 256 + byte;
    bits += 8;
    while (bits >= RABBIT_TEXT_BITS) {
      bits -= RABBIT_TEXT_BITS;
      const divisor = 2 ** bits;
      output += String.fromCharCode(RABBIT_TEXT_BASE + Math.floor(buffer / divisor));
      buffer %= divisor;
    }
  }
  if (bits) output += String.fromCharCode(RABBIT_TEXT_BASE + buffer * 2 ** (RABBIT_TEXT_BITS - bits));
  return output;
}

function rabbitTextUnpack(value) {
  const source = String(value || "");
  const padding = (source.codePointAt(1) ?? 0) - RABBIT_TEXT_BASE;
  if (source[0] !== "K" || padding < 0 || padding >= RABBIT_TEXT_BITS) return rabbitBase64Bytes(source);
  const symbols = Array.from(source.slice(2));
  if (!symbols.length) return new Uint8Array();
  let buffer = 0;
  let bits = 0;
  const output = [];
  symbols.forEach((symbol, index) => {
    const value = symbol.codePointAt(0) - RABBIT_TEXT_BASE;
    if (value < 0 || value >= 2 ** RABBIT_TEXT_BITS) throw new Error("Rabbit 短码包含无效字符");
    const symbolBits = index === symbols.length - 1 ? RABBIT_TEXT_BITS - padding : RABBIT_TEXT_BITS;
    buffer = buffer * 2 ** symbolBits + Math.floor(value / 2 ** (RABBIT_TEXT_BITS - symbolBits));
    bits += symbolBits;
    while (bits >= 8) {
      bits -= 8;
      const divisor = 2 ** bits;
      output.push(Math.floor(buffer / divisor));
      buffer %= divisor;
    }
  });
  if (bits || output.length * 8 !== symbols.length * RABBIT_TEXT_BITS - padding) throw new Error("Rabbit 短码位数无效");
  return Uint8Array.from(output);
}

async function rabbitDeflate(value) {
  if (typeof CompressionStream !== "function") throw new Error("当前浏览器不支持 Rabbit 配装压缩");
  const stream = new Blob([JSON.stringify(value)]).stream().pipeThrough(new CompressionStream("deflate"));
  return rabbitTextPack(new Uint8Array(await new Response(stream).arrayBuffer()));
}

async function rabbitInflate(value) {
  if (typeof DecompressionStream !== "function") throw new Error("当前浏览器不支持 Rabbit 配装解压");
  const stream = new Blob([rabbitTextUnpack(value)]).stream().pipeThrough(new DecompressionStream("deflate"));
  return JSON.parse(await new Response(stream).text());
}

async function rabbitEncode(prefix, value) {
  return prefix + await rabbitDeflate(value);
}

function rabbitCodeToken(value) {
  const match = String(value || "").match(/(?:WRB1|WRC1)\.[^\s，。！？；：、,.!?:;]+/u);
  if (!match) throw new Error("没有找到 WRB1/WRC1 配装码");
  return match[0];
}

function rabbitPathToken(value) {
  const bytes = new TextEncoder().encode(String(value || ""));
  let hash = 0xcbf29ce484222325n;
  for (const byte of bytes) {
    hash ^= BigInt(byte);
    hash = BigInt.asUintN(64, hash * 0x100000001b3n);
  }
  const output = new Uint8Array(6);
  for (let index = 5; index >= 0; index--) {
    output[index] = Number(hash & 0xffn);
    hash >>= 8n;
  }
  return rabbitBase64Url(output);
}

function rabbitWireRows(kind) {
  if (kind === "warframe") return ["mods", "arcanes", "shards", "helminth", "invigoration"].flatMap((key) => warframeRows(key));
  const catalog = state.catalog || {};
  const parts = catalog.kitgunParts || {};
  const zaw = catalog.zawParts || {};
  return [
    ...(catalog.manualMods || []), ...(catalog.manualModVariants || []), ...(catalog.utilityMods || []),
    ...(catalog.stances || []), ...(catalog.arcanes || []),
    ...(parts.chambers || []), ...(parts.grips || []), ...(parts.loaders || []),
    ...(zaw.strikes || []), ...(zaw.grips || []), ...(zaw.links || []),
  ];
}

function rabbitWireIndex(kind) {
  const byPath = new Map();
  const byToken = new Map();
  for (const row of rabbitWireRows(kind)) {
    const path = String(row?.path || row?.id || "");
    if (!path) continue;
    byPath.set(path, row);
    const token = rabbitPathToken(path);
    const previous = byToken.get(token);
    if (previous && String(previous.path || previous.id) !== path) throw new Error(`Rabbit 目录短 ID 冲突：${token}`);
    byToken.set(token, row);
  }
  return { byPath, byToken };
}

function rabbitWirePolarity(value) {
  const index = WARFRAME_POLARITIES.indexOf(value || null);
  return index >= 0 ? index : value;
}

function rabbitWirePolarityValue(value) {
  return Number.isInteger(value) ? (WARFRAME_POLARITIES[value] ?? null) : (value || null);
}

function rabbitWirePair(value) {
  return value?.path ? [rabbitPathToken(value.path), Number(value.rank ?? 0)] : null;
}

function rabbitWireDictionary(kind, config) {
  const { byPath } = rabbitWireIndex(kind);
  const rows = new Map();
  const add = (value) => {
    const path = typeof value === "string" ? value : value?.path;
    if (!path) return;
    const row = byPath.get(path);
    // Bot resolves ordinary catalog items by the same stable hash. Only carry
    // labels for Portable-only rows such as shards, invigoration and Helminth.
    if (!row || (kind === "warframe" && !["mods", "arcanes"].some((key) => warframeRows(key).includes(row)))) rows.set(path, row || { path });
  };
  if (kind === "weapon") (config.kitgunParts || []).forEach(add);
  else { (config.shards || []).forEach(add); add(config.helminthAbility); (config.invigoration || []).forEach(add); }
  return [...rows.entries()].map(([path, row]) => {
    return [rabbitPathToken(path), row.nameZh || row.nameCn || "", row.nameEn || row.nameInternal || "", Number(row.maxRank ?? row.rank ?? 0), rabbitWirePolarity(row.polarity)];
  });
}

function rabbitCompactConfig(wrapper) {
  const config = wrapper.config || {};
  if (wrapper.kind === "weapon") {
    const result = {
      m: (config.mods || []).map((item) => [rabbitPathToken(item.path), Number(item.rank ?? 0), Number(item.slot ?? 0)]),
    };
    if (Number(config.fireMode || 0)) result.f = Number(config.fireMode);
    if (Number(config.slotCount || 8) !== 8) result.z = Number(config.slotCount);
    if (config.formaSlots) result.p = Object.entries(config.formaSlots).map(([slot, polarity]) => [Number(slot), rabbitWirePolarity(polarity)]);
    if (config.specialSlotPolarities) result.t = Object.fromEntries(Object.entries(config.specialSlotPolarities).map(([kind, polarity]) => [kind, rabbitWirePolarity(polarity)]));
    if (Array.isArray(config.riven?.stats) && config.riven.stats.length) result.r = [Number(config.riven.slot ?? 7), ...config.riven.stats.map((item) => [item.code, Number(item.value || 0), item.negative ? 1 : 0])];
    if (config.stancePath) result.s = rabbitPathToken(config.stancePath);
    if (config.exilus) result.x = rabbitWirePair(config.exilus);
    if (config.weaponArcane) result.a = rabbitWirePair(config.weaponArcane);
    if (config.incarnonChoices && Object.keys(config.incarnonChoices).length) result.i = Object.entries(config.incarnonChoices).map(([tier, choice]) => [Number(String(tier).replace(/\D+/g, "")), choice]);
    if (Array.isArray(config.kitgunParts) && config.kitgunParts.length) result.g = config.kitgunParts.map(rabbitPathToken);
    if (config.incarnonCycle) result.ic = 1;
    if (config.aiming) result.aim = 1;
    if (config.combatState && Object.keys(config.combatState).length) result.cs = config.combatState;
    if (config.detonationDelaySeconds || Number(config.detonationBatchSize || 1) !== 1) result.dt = [Number(config.detonationBatchSize || 1), Number(config.detonationDelaySeconds || 0)];
    if (config.innateElement) result.e = config.innateElement;
    if (config.innateElement) result.b = Number(config.innateElementValue ?? 0.60);
    return result;
  }
  const result = {
    m: (config.normalMods || []).flatMap((item, slot) => item?.path ? [[slot, rabbitPathToken(item.path), Number(item.rank ?? 0)]] : []),
  };
  if (config.aura) result.a = rabbitWirePair(config.aura);
  if (config.exilus) result.x = rabbitWirePair(config.exilus);
  if ((config.arcanes || []).some(Boolean)) result.r = config.arcanes.flatMap((item) => item?.path ? [rabbitWirePair(item)] : []);
  if ((config.shards || []).some(Boolean)) result.s = config.shards.flatMap((item, slot) => item?.path ? [[slot, rabbitPathToken(item.path), item.tau ? 1 : 0]] : []);
  const polarities = config.slotPolarities || {};
  const polarityRows = [polarities.aura, polarities.exilus, ...(polarities.normal || [])].map(rabbitWirePolarity);
  if (polarityRows.some((value) => value)) result.p = polarityRows;
  if (Number.isInteger(config.helminthSlot) && config.helminthAbility) result.h = [config.helminthSlot, rabbitPathToken(config.helminthAbility)];
  if ((config.invigoration || []).length) result.i = config.invigoration.map((value) => rabbitPathToken(typeof value === "string" ? value : value.path));
  if (config.applyConditionals) result.c = 1;
  return result;
}

function rabbitExpandPair(value, byToken) {
  if (!Array.isArray(value) || !value[0]) return null;
  const row = byToken.get(value[0]);
  if (!row) throw new Error(`Rabbit 目录缺少短 ID：${value[0]}`);
  return { path: String(row.path || row.id), rank: Number(value[1] || 0) };
}

function rabbitExpandCompactConfig(kind, compact) {
  const { byToken } = rabbitWireIndex(kind);
  const resolve = (token) => {
    const row = byToken.get(token);
    if (!row) throw new Error(`Rabbit 目录缺少短 ID：${token}`);
    return String(row.path || row.id);
  };
  if (kind === "weapon") {
    const config = {
      schema: BUILD_CONFIG_SCHEMA, fireMode: Number(compact.f || 0), slotCount: Number(compact.z || 8), mode: "manual",
      mods: (compact.m || []).map(([token, rank, slot]) => ({ path: resolve(token), rank: Number(rank || 0), slot: Number(slot || 0) })),
      riven: Array.isArray(compact.r) ? { slot: Number(compact.r[0] ?? 7), stats: compact.r.slice(1).map(([code, value, negative]) => ({ code, value: Number(value || 0), negative: Boolean(negative) })) } : null,
      stancePath: compact.s ? resolve(compact.s) : null,
      exilus: rabbitExpandPair(compact.x, byToken), weaponArcane: rabbitExpandPair(compact.a, byToken),
      incarnonChoices: Object.fromEntries((compact.i || []).map(([tier, choice]) => [String(tier), choice])),
      incarnonCycle: Boolean(compact.ic), aiming: Boolean(compact.aim),
      combatState: compact.cs || {},
      detonationBatchSize: Number(compact.dt?.[0] ?? 1), detonationDelaySeconds: Number(compact.dt?.[1] ?? 0),
      innateElement: compact.e || null,
      innateElementValue: Number(compact.b ?? 0.60),
      specialSlotPolarities: compact.t && typeof compact.t === "object" ? Object.fromEntries(Object.entries(compact.t).map(([kind, polarity]) => [kind, rabbitWirePolarityValue(polarity) || "AP_UNIVERSAL"])) : undefined,
    };
    if (Array.isArray(compact.p) && compact.p.length) config.formaSlots = Object.fromEntries(compact.p.map(([slot, polarity]) => [String(slot), rabbitWirePolarityValue(polarity)]));
    if (Array.isArray(compact.g) && compact.g.length) config.kitgunParts = compact.g.map(resolve);
    return config;
  }
  const normalMods = Array.from({ length: 8 }, () => null);
  for (const [slot, token, rank] of compact.m || []) normalMods[Number(slot)] = { path: resolve(token), rank: Number(rank || 0) };
  const shards = Array.from({ length: 5 }, () => null);
  for (const [slot, token, tau] of compact.s || []) shards[Number(slot)] = { path: resolve(token), tau: Boolean(tau) };
  const polarities = Array.isArray(compact.p) ? compact.p.map(rabbitWirePolarityValue) : [];
  return {
    schema: 1, aura: rabbitExpandPair(compact.a, byToken), exilus: rabbitExpandPair(compact.x, byToken), normalMods,
    arcanes: (compact.r || []).map((item) => rabbitExpandPair(item, byToken)), shards,
    slotPolarities: { aura: polarities[0] ?? null, exilus: polarities[1] ?? null, normal: Array.from({ length: 8 }, (_, index) => polarities[index + 2] ?? null) },
    helminthSlot: Array.isArray(compact.h) ? Number(compact.h[0]) : null,
    helminthAbility: Array.isArray(compact.h) ? resolve(compact.h[1]) : null,
    invigoration: (compact.i || []).map(resolve), applyConditionals: Boolean(compact.c),
  };
}

function rabbitCompactDetails(meta) {
  if (meta.kind === "weapon") {
    const weapon = meta.details?.weapon || {};
    const stats = weapon.stats || {};
    return [0, weapon.fire_mode?.name || "", [stats.total_damage || 0, stats.sustained_dps || 0, stats.crit_chance || 0, stats.status_chance || 0, stats.fire_rate || 0],
      (weapon.incarnon || []).map((row) => [row.tier, row.choice, row.label || ""]), weapon.innate_element || null,
      // values[5] carries the weapon arcane description (v2.3+).
      String(weapon.weapon_arcane?.description || "") || null,
      // values[6] carries the post-build damage type distribution (v2.4+).
      (weapon.damage_types || []).length ? (weapon.damage_types || []).map((row) => [row.damage_type || "", Number(row.percent || 0)]) : null,
      // values[7] carries the full slot polarity layout with native flags (v2.5+).
      (weapon.slot_polarities || []).length ? (weapon.slot_polarities || []).map((row) => [row.slot === "stance" ? 8 : row.slot === "exilus" ? 9 : Number(row.slot), rabbitWirePolarity(row.polarity), row.native ? 1 : 0]) : null];
  }
  const frame = meta.details?.warframe || {};
  const panel = frame.panel || {};
  return [1,
    [panel.health || 0, panel.shield || 0, panel.armor || 0, panel.energy || 0, panel.abilityStrength || 0, panel.abilityDuration || 0, panel.abilityRange || 0, panel.abilityEfficiency || 0],
    (frame.shards || []).map((item) => {
      const row = [item.name_zh || "", item.name_en || "", item.effect || "", item.tau ? 1 : 0];
      // row[4] is the optional shard icon basename (v2.2+).
      if (item.icon) row.push(String(item.icon));
      return row;
    }),
    frame.helminth ? [frame.helminth.replaces?.name_zh || frame.helminth.replaces?.name_en || "", frame.helminth.ability?.name_zh || frame.helminth.ability?.name_en || ""] : null,
    (frame.invigoration || []).map((item) => [item.name_zh || item.name_en || "", item.effect || ""]),
    (frame.abilities || []).map((ability) => {
      const row = [ability.slot, ability.name || "", ability.replaced ? 1 : 0, ability.replaces || "", (ability.scalars || []).map((scalar) => [scalar.label || "", scalar.value || "", scalar.group || ""])];
      const cost = rabbitCompactAbilityCost(ability.energyCost);
      const icon = String(ability.icon || "");
      const description = String(ability.description || "");
      // Baseline fields (v2.5+): row[8] baseline scalars, row[9] baseline
      // activation cost, so the Bot can color changed values. Earlier slots
      // stay present so older readers stop cleanly at the length they know.
      const baseScalars = (ability.base_scalars || []).map((scalar) => [scalar.label || "", scalar.value || "", scalar.group || ""]);
      const baseActivation = ability.base_activation;
      const hasBaseline = baseScalars.length > 0 || baseActivation !== null && baseActivation !== undefined;
      if (cost || icon || description || hasBaseline) row.push(cost || null);
      if (icon || description || hasBaseline) row.push(icon);
      if (description || hasBaseline) row.push(description);
      if (hasBaseline) {
        row.push(baseScalars);
        if (baseActivation !== null && baseActivation !== undefined) row.push(baseActivation);
      }
      return row;
    }),
    (frame.forma_slots || []).map((row) => [row.slot === "aura" ? 8 : row.slot === "exilus" ? 9 : Number(row.slot), rabbitWirePolarity(row.polarity)]),
    // values[7] carries arcane descriptions aligned with the compact config
    // arcane order (empty slots are dropped on both sides) (v2.3+).
    (() => {
      const descriptions = (frame.arcanes || []).filter(Boolean).map((item) => String(item.description || ""));
      return descriptions.some(Boolean) ? descriptions : null;
    })(),
    // values[8] carries the full slot polarity layout with native flags (v2.5+).
    (frame.slot_polarities || []).length ? (frame.slot_polarities || []).map((row) => [row.slot === "aura" ? 8 : row.slot === "exilus" ? 9 : Number(row.slot), rabbitWirePolarity(row.polarity), row.native ? 1 : 0]) : null,
    // values[9] carries the unmodded baseline panel for value coloring (v2.5+).
    (() => { const base = frame.panel_base || {}; return [base.health || 0, base.shield || 0, base.armor || 0, base.energy || 0, base.abilityStrength ?? 1, base.abilityDuration ?? 1, base.abilityRange ?? 1, base.abilityEfficiency ?? 1]; })(),
  ];
}

// Icons travel as bare filenames (no portable-local /assets/ prefix); the Bot
// maps ability basenames onto the DE /Lotus/Interface/Icons/Abilities tree and
// shard basenames onto the ArchonShards tree.
function rabbitWireIconBase(asset) {
  const raw = String(asset || "").trim();
  if (!raw) return "";
  return raw.split("/").filter(Boolean).pop() || "";
}

function rabbitShardWireIcon(item) {
  const assets = warframeShardAssets(item || {});
  return rabbitWireIconBase(item?.tau && assets.glow ? assets.glow : assets.base);
}

// Keep the non-standard resource rule separate from the overloaded 0-cost
// scalar.  The short keys are only on the Rabbit wire; the page keeps the
// canonical API object for rendering and future fields.
function rabbitCompactAbilityCost(cost) {
  if (!cost || typeof cost !== "object") return null;
  const resource = String(cost.resource || "energy");
  const hasSpecialRule = resource !== "energy" || Object.keys(cost).some((name) => !["resource", "activation", "baseActivation", "sourceKind"].includes(name));
  if (!hasSpecialRule) return null;
  const names = {
    resource: "r", activation: "a", airborneActivation: "aa", cooldownSeconds: "cd",
    drainPerSecond: "d", boostedDrainPerSecond: "b", perTarget: "t", perShot: "s", chargedShot: "c",
    perAllyPerSecond: "l", perEnemyPerSecond: "e", perAbilityPerSecond: "p", perDodge: "o", reviveMaximum: "v",
    targetCap: "cap", maximumHealthPercent: "hp", minimumRemaining: "min", stacks: "st", perChargePercent: "pc",
    maximumTotal: "max", restoreOnActivationPercent: "ra", restorePerSecondPercent: "rs", requiredPercent: "req",
    drainPerSecondPercent: "dp", discountPercent: "q", noteZh: "n", variableChannel: "x",
    baseActivation: "ba", baseAirborneActivation: "baa", baseCooldownSeconds: "bcd", baseDrainPerSecond: "bd",
    baseBoostedDrainPerSecond: "bb", basePerTarget: "bt", basePerShot: "bs", baseChargedShot: "bc",
    basePerAllyPerSecond: "bl", basePerEnemyPerSecond: "be", basePerAbilityPerSecond: "bp", basePerDodge: "bo",
    baseReviveMaximum: "bv",
  };
  const compact = {};
  Object.entries(names).forEach(([name, key]) => {
    const value = cost[name];
    if (value !== undefined && value !== null && value !== "" && (typeof value !== "boolean" || value)) compact[key] = value;
  });
  return Object.keys(compact).length ? compact : null;
}

function rabbitCompactUpload(meta, wrapper) {
  const kind = meta.kind;
  const archetypes = RABBIT_ARCHETYPES[kind].map(([value]) => value);
  return {
    v: RABBIT_WIRE_SCHEMA, k: kind === "weapon" ? 0 : 1,
    t: [meta.target.id, meta.target.name_zh || "", meta.target.name_en || ""], b: meta.build_label || "",
    n: meta.title, a: archetypes.indexOf(meta.archetype), s: meta.summary_zh,
    u: meta.usage_zh, c: meta.cautions_zh, f: Number(meta.forma_count || 0),
    q: rabbitCompactConfig(wrapper), l: rabbitWireDictionary(kind, wrapper.config || {}), d: rabbitCompactDetails(meta),
  };
}

function rabbitCompactConfigCode(wrapper) {
  const kind = wrapper.kind;
  return {
    v: RABBIT_WIRE_SCHEMA, k: kind === "weapon" ? 0 : 1, t: [wrapper.target],
    q: rabbitCompactConfig(wrapper), l: rabbitWireDictionary(kind, wrapper.config || {}),
  };
}

function rabbitExpandWireConfig(value) {
  if (!value || Number(value.v) !== RABBIT_WIRE_SCHEMA || ![0, 1].includes(Number(value.k))) throw new Error("Rabbit v2 短码结构无效");
  const kind = Number(value.k) === 0 ? "weapon" : "warframe";
  const target = Array.isArray(value.t) ? value.t[0] : value.t;
  return { schema: 1, kind, target, config: rabbitExpandCompactConfig(kind, value.q || {}) };
}

async function rabbitDecode(value) {
  const code = rabbitCodeToken(value);
  if (code.startsWith(RABBIT_FULL_PREFIX)) {
    const envelope = await rabbitInflate(code.slice(RABBIT_FULL_PREFIX.length));
    if (Number(envelope?.v) === RABBIT_WIRE_SCHEMA) return rabbitExpandWireConfig(envelope);
    if (!envelope || typeof envelope !== "object" || !envelope.config) throw new Error("WRB1 配装码缺少 config");
    return envelope.config;
  }
  const config = await rabbitInflate(code.slice(RABBIT_CONFIG_PREFIX.length));
  if (Number(config?.v) === RABBIT_WIRE_SCHEMA) return rabbitExpandWireConfig(config);
  if (!config || typeof config !== "object") throw new Error("WRC1 配装码无效");
  return config;
}

function rabbitItem(item) {
  if (!item) return null;
  return {
    id: String(item.path || item.id || item.nameInternal || ""),
    name_zh: item.nameZh || item.nameCn || item.nameEn || "",
    name_en: item.nameEn || item.nameInternal || "",
    rank: Number(item.rank ?? item.maxRank ?? 0),
  };
}

function rabbitBuildMod(item, slot, kind = "normal", polarity = "") {
  if (!item) return null;
  return {
    unique_name: String(item.path || item.id || item.nameInternal || ""),
    name_zh: item.nameZh || item.nameCn || item.nameEn || (item.__riven ? "自定义紫卡" : ""),
    name_en: item.nameEn || item.nameInternal || "",
    rank: Number(item.rank ?? item.maxRank ?? 0),
    max_rank: Number(item.maxRank ?? item.rank ?? 0),
    slot,
    polarity: polarity || item.polarity || "",
    aura: kind === "aura",
    exilus: kind === "exilus",
  };
}

function rabbitBuildArcane(item) {
  if (!item) return null;
  return {
    name_zh: item.nameZh || item.nameCn || item.nameEn || "",
    name_en: item.nameEn || item.nameInternal || "",
    rank: Number(item.rank ?? item.maxRank ?? 0),
    // 描述走线上格式：Bot 目录不存赋能描述（v2.3+）
    description: arcaneDescription(item),
  };
}

// details 级赋能注解：紧凑线按配置顺序携带描述（v2.3）。
function rabbitArcaneDetail(item) {
  if (!item) return null;
  return { ...rabbitItem(item), description: arcaneDescription(item) };
}

// 配装后的伤害类型分布（紧凑线 values[6]），按占比降序。
function rabbitDamageTypeRows(result) {
  const build = resultBuildView(result);
  const entries = Object.entries(build?.damageTypes || {}).filter(([, value]) => Number(value) > 0);
  const total = entries.reduce((sum, [, value]) => sum + Number(value), 0);
  if (!total) return [];
  return entries.sort((a, b) => Number(b[1]) - Number(a[1])).map(([type, value]) => ({ damage_type: type, percent: Number(value) / total }));
}

function rabbitWeaponConfig() {
  const source = captureBuildConfig();
  const config = {
    schema: BUILD_CONFIG_SCHEMA,
    fireMode: source.fireMode,
    slotCount: source.slotCount,
    mode: "manual",
    mods: source.mods,
    formaSlots: source.formaSlots,
    specialSlotPolarities: source.specialSlotPolarities,
    riven: source.riven,
    innateElement: source.innateElement,
    innateElementValue: source.innateElementValue,
    stancePath: source.stancePath,
    exilus: source.exilus,
    weaponArcane: source.weaponArcane,
    incarnonChoices: source.incarnonChoices,
    incarnonCycle: source.incarnonCycle, aiming: source.aiming,
    combatState: source.combatState,
    detonationBatchSize: source.detonationBatchSize, detonationDelaySeconds: source.detonationDelaySeconds,
  };
  const parts = kitgunPartsPayload();
  if (parts) config.kitgunParts = parts;
  return { schema: 1, kind: "weapon", target: state.buildWeapon?.path || "", config };
}

function rabbitWarframeConfig() {
  const build = state.warframeBuild;
  const source = captureWarframeConfig();
  const alternate = isAlternateWarframeForm();
  const config = {
    schema: 1,
    buildLabel: source.buildLabel,
    aura: source.aura,
    exilus: source.exilus,
    normalMods: source.normalMods,
    arcanes: source.arcanes,
    shards: alternate ? build.shards.map((row) => row ? { path: warframeId(row), tau: Boolean(row.tau) } : null) : source.shards,
    slotPolarities: source.slotPolarities,
    helminthSlot: source.helminthSlot,
    helminthAbility: source.helminthAbility,
    invigoration: alternate ? build.invigoration.map(warframeId) : source.invigoration,
    applyConditionals: source.applyConditionals,
  };
  return { schema: 1, kind: "warframe", target: warframeId(activeWarframeRecord()), config };
}

async function rabbitCleanWeaponResult() {
  const payload = buildPayloadFromForm();
  payload.externalBuffs = [];
  payload.arcanes = state.weaponArcane ? [compactRankedSelection(state.weaponArcane)] : [];
  payload.damageModel = "panel";
  payload.defenseSnapshot = null;
  payload.armourStrip = 0;
  payload.elementalArmourStrip = 0;
  payload.headshotChance = 0;
  payload.distance = null;
  payload.enemyEnhancements = { eximus: false, empowered: false, playerCount: null, archimedea: false };
  const response = await fetch("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const result = await response.json();
  if (!response.ok) throw new Error(result?.error?.message || `Rabbit 武器配装生成失败（${response.status}）`);
  return result;
}

async function rabbitCurrentWarframeResult() {
  const response = await fetch("/api/warframe/calculate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(warframePayload()) });
  const result = await response.json();
  if (!response.ok) throw new Error(result?.error?.message || `Rabbit 战甲配装生成失败（${response.status}）`);
  return result;
}

function rabbitIncarnonRows(choices) {
  const tiers = Array.isArray(state.buildWeapon?.incarnon) ? state.buildWeapon.incarnon : [];
  return Object.entries(choices || {}).map(([tierKey, choice]) => {
    // incarnonChoices 的键是 "tier2"/"tier3" 形式，先解析出阶段数字再匹配选项
    const tier = Number(String(tierKey).replace(/\D+/g, ""));
    const row = tiers.find((item) => Number(item.tier) === tier);
    const option = row?.options?.find((item) => item.id === choice);
    return { tier, choice, label: option?.label || choice };
  });
}

function rabbitWeaponFormaRows() {
  return Object.entries(state.formaSlots).map(([slot, polarity]) => ({
    slot: Number(slot), polarity, label: POLARITY_NAMES[polarity] || polarity,
  }));
}

function rabbitWarframeFormaRows() {
  const build = state.warframeBuild;
  const native = frameSlotPolarities(activeWarframeRecord());
  const result = [];
  for (const kind of ["aura", "exilus"]) {
    const polarity = build.slotPolarities[kind];
    if (polarity && polarity !== native[kind]) result.push({ slot: kind, polarity, label: POLARITY_NAMES[polarity] || polarity });
  }
  build.slotPolarities.normal.forEach((polarity, slot) => {
    if (polarity && polarity !== native.normal[slot]) result.push({ slot, polarity, label: POLARITY_NAMES[polarity] || polarity });
  });
  return result;
}

// 全槽位极性明细（含原生/未极化槽位）：Bot 端展示所有槽位并区分原生/被极化（v2.5+）。
function rabbitWeaponSlotPolarityRows() {
  const rows = [];
  const stanceIndex = specialSlotIndex("stance");
  if (stanceIndex !== null) rows.push({ slot: "stance", polarity: weaponSpecialSlotPolarity("stance") || "", native: !Object.hasOwn(state.formaSlots, stanceIndex) });
  rows.push({ slot: "exilus", polarity: weaponSpecialSlotPolarity("exilus") || "", native: !Object.hasOwn(state.formaSlots, specialSlotIndex("exilus")) });
  weaponSlotPolarities().forEach((polarity, slot) => {
    rows.push({ slot, polarity: polarity || "", native: !Object.hasOwn(state.formaSlots, slot) });
  });
  return rows;
}

function rabbitWarframeSlotPolarityRows() {
  const build = state.warframeBuild;
  const native = frameSlotPolarities(activeWarframeRecord());
  const rows = [];
  for (const kind of ["aura", "exilus"]) {
    const polarity = build.slotPolarities[kind] || null;
    rows.push({ slot: kind, polarity: polarity || "", native: (polarity || null) === (native[kind] || null) });
  }
  build.slotPolarities.normal.forEach((polarity, slot) => {
    rows.push({ slot, polarity: polarity || "", native: (polarity || null) === (native.normal[slot] || null) });
  });
  return rows;
}

function rabbitWarframeAbilityRows(result) {
  const build = state.warframeBuild;
  const source = Array.isArray(activeWarframeRecord()?.abilities) ? activeWarframeRecord().abilities : [];
  const rows = Array.isArray(result.abilityScalars) ? result.abilityScalars : source;
  return Array.from({ length: Math.max(source.length, rows.length) }, (_, slot) => {
    const raw = rows[slot] || {};
    const original = source[slot] || {};
    const replaced = build.helminthSlot === slot && build.helminthAbility;
    const ability = { ...original, ...raw };
    const visible = replaced ? { ...ability, ...build.helminthAbility, scalars: ability.scalars, energyCost: ability.energyCost || build.helminthAbility.energyCost } : ability;
    const cost = visible.energyCost || {};
    const hasExtraCostFields = Object.keys(cost).some((key) => !["resource", "sourceKind", "activation", "baseActivation"].includes(key) && cost[key] !== null && cost[key] !== undefined) || String(cost.resource || "energy") !== "energy";
    // Special costs (per-target, per-shot, shield/restraint, ...) are not an
    // ordinary activation cost.  The engine also emits a placeholder
    // `Energy Cost = 0` scalar for those abilities; drop that duplicate so
    // Rabbit snapshots cannot render the misleading zero line.
    const scalars = (Array.isArray(ability.scalars) ? ability.scalars : []).filter((scalar) => !(
      hasExtraCostFields && (scalar.isEnergy || /energy cost|能量消耗/i.test(String(scalar.label || ""))) && Number(scalar.value) === 0
    )).map((scalar) => ({
      label: warframeScalarLabel(scalar), value: warframeScalarValueText(scalar), group: scalar.group || "",
    }));
    return {
      slot, id: warframeId(visible), name: warframeName(visible), replaced: Boolean(replaced),
      replaces: replaced ? warframeName(original) : "", scalars, energyCost: visible.energyCost || null,
      icon: rabbitWireIconBase(visible.iconAsset || visible.icon), description: cleanOfficialText(visible.description || ""),
      // 基准（无 MOD）数值：渲染端据此给变动数值着色（v2.5+）。基准标量是
      // 目录形态（parts/base），用 warframeScalarBaseText 而不是结果形态的取值。
      base_scalars: (Array.isArray(original.scalars) ? original.scalars : []).map((scalar) => ({
        label: warframeScalarLabel(scalar), value: warframeScalarBaseText(scalar), group: scalar.group || "",
      })),
      base_activation: finite(original.energyCost?.activation),
    };
  });
}

function rabbitExportCapacity(kind) {
  if (kind === "weapon") {
    const current = computeCapacity();
    const remaining = Number(current.limit) - Number(current.used);
    return { remaining, valid: Number.isFinite(remaining) && remaining >= 0 && !current.over };
  }
  const capacity = state.warframeBuild.result?.capacityBreakdown;
  if (capacity && Number.isFinite(Number(capacity.remaining))) {
    const remaining = Number(capacity.remaining);
    return { remaining, valid: capacity.valid !== false && remaining >= 0 };
  }
  return { remaining: null, valid: false };
}

async function rabbitWeaponMeta(fields) {
  const result = await rabbitCleanWeaponResult();
  const stats = result.moddedStats || {};
  const slotPolarities = weaponSlotPolarities();
  const mods = state.manualSlots.map((item, slot) => rabbitBuildMod(item, slot, "normal", slotPolarities[slot])).filter(Boolean);
  if (state.stanceSelection) mods.push(rabbitBuildMod(state.stanceSelection, 8, "stance", weaponSpecialSlotPolarity("stance")));
  if (state.exilusSelection) mods.push(rabbitBuildMod(state.exilusSelection, specialSlotIndex("exilus"), "exilus", weaponSpecialSlotPolarity("exilus")));
  const weapon = state.buildWeapon;
  const innateElement = ui["build-innate-element-select"]?.value || "";
  return {
    schema: 1,
    kind: "weapon",
    build_label: state.catalog?.buildLabel || "OFFLINE",
    game_version: state.catalog?.buildLabel || "OFFLINE",
    target: { id: weapon.path, name_zh: weaponName(weapon), name_en: weapon.nameEn || weapon.nameInternal || "" },
    ...fields,
    forma_count: rabbitWeaponFormaRows().length,
    mods,
    arcanes: [rabbitBuildArcane(state.weaponArcane)].filter(Boolean),
    details: {
      weapon: {
        fire_mode: { index: Number(ui["build-fire-mode-select"].value || 0), name: ui["build-fire-mode-select"].selectedOptions[0]?.textContent || "" },
        stats: {
          total_damage: Number(stats.totalDamage ?? stats.total_damage ?? 0),
          sustained_dps: Number(result.totalSustainedDps ?? stats.sustainedDps ?? stats.sustained_dps ?? 0),
          crit_chance: Number(stats.critChance ?? stats.crit_chance ?? 0),
          status_chance: Number(stats.statusChance ?? stats.status_chance ?? 0),
          fire_rate: Number(stats.fireRate ?? stats.fire_rate ?? 0),
        },
        stance: rabbitItem(state.stanceSelection),
        exilus: rabbitItem(state.exilusSelection),
        weapon_arcane: rabbitArcaneDetail(state.weaponArcane),
        damage_types: rabbitDamageTypeRows(result),
        slot_polarities: rabbitWeaponSlotPolarityRows(),
        innate_element: innateElement ? {
          damage_type: innateElement,
          value: Number(ui["build-innate-element-value"]?.value || 60) / 100,
        } : null,
        incarnon: rabbitIncarnonRows(result.incarnonChoices || state.incarnonChoices),
        forma_slots: rabbitWeaponFormaRows(),
      },
    },
  };
}

async function rabbitWarframeMeta(fields) {
  const result = await rabbitCurrentWarframeResult();
  state.warframeBuild.result = result;
  const build = state.warframeBuild;
  const mods = build.normalMods.map((item, slot) => rabbitBuildMod(item, slot, "normal", build.slotPolarities.normal[slot])).filter(Boolean);
  if (build.aura) mods.push(rabbitBuildMod(build.aura, 8, "aura", build.slotPolarities.aura));
  if (build.exilus) mods.push(rabbitBuildMod(build.exilus, 9, "exilus", build.slotPolarities.exilus));
  const panel = result.finalPanel || {};
  const formaRows = rabbitWarframeFormaRows();
  const sourceAbility = build.helminthSlot === null ? null : activeWarframeRecord()?.abilities?.[build.helminthSlot];
  return {
    schema: 1,
    kind: "warframe",
    build_label: state.warframeCatalog?.buildLabel || "OFFLINE",
    game_version: state.warframeCatalog?.buildLabel || "OFFLINE",
    target: { id: warframeId(activeWarframeRecord()), name_zh: warframeName(activeWarframeRecord()), name_en: activeWarframeRecord()?.nameEn || "" },
    ...fields,
    forma_count: formaRows.length,
    mods,
    arcanes: build.arcanes.filter(Boolean).map(rabbitBuildArcane),
    details: {
      warframe: {
        panel: Object.fromEntries(["health", "shield", "armor", "energy", "abilityStrength", "abilityDuration", "abilityRange", "abilityEfficiency"].map((key) => [key, Number(panel[key] ?? 0)])),
        forma_slots: formaRows,
        shards: build.shards.filter(Boolean).map((item) => ({ ...rabbitItem(item), tau: Boolean(item.tau), effect: warframeDescription(item), icon: rabbitShardWireIcon(item) })),
        helminth: build.helminthSlot !== null && build.helminthAbility ? { slot: build.helminthSlot, replaces: rabbitItem(sourceAbility), ability: rabbitItem(build.helminthAbility) } : null,
        invigoration: build.invigoration.map((item) => ({ ...rabbitItem(item), effect: warframeDescription(item) })),
        abilities: rabbitWarframeAbilityRows(result),
        // 赋能描述注解：按配置槽顺序（紧凑线 values[7] 与之对齐，v2.3+）
        arcanes: build.arcanes.map((item) => (item ? { description: arcaneDescription(item) } : null)),
        // 全槽位极性（v2.5+）与无 MOD 基准面板（用于变动数值着色）
        slot_polarities: rabbitWarframeSlotPolarityRows(),
        panel_base: {
          health: Number(activeWarframeRecord()?.basePanel?.health || 0), shield: Number(activeWarframeRecord()?.basePanel?.shield || 0),
          armor: Number(activeWarframeRecord()?.basePanel?.armor || 0), energy: Number(activeWarframeRecord()?.basePanel?.energy || 0),
          abilityStrength: 1, abilityDuration: 1, abilityRange: 1, abilityEfficiency: 1,
        },
      },
    },
  };
}

function rabbitExportFields() {
  const usage = rabbitTextLines(ui["rabbit-usage"].value);
  const cautions = rabbitTextLines(ui["rabbit-cautions"].value);
  if (!usage.length || !cautions.length) throw new Error("使用要点和注意事项都至少填写一行；没有可填写“无”");
  const summary = ui["rabbit-summary"].value.trim();
  return {
    title: ui["rabbit-build-title"].value.trim(),
    archetype: ui["rabbit-archetype"].value,
    summary_zh: summary,
    description_zh: summary,
    usage_zh: usage,
    cautions_zh: cautions,
  };
}

function openRabbitDialog(mode, kind) {
  if (kind === "weapon" && !state.buildWeapon || kind === "warframe" && !state.warframeBuild.frame) return toast("请先选择当前配装目标");
  rabbitDialogKind = kind;
  const exporting = mode === "export";
  ui["rabbit-export-form"].hidden = !exporting;
  ui["rabbit-import-panel"].hidden = exporting;
  ui["rabbit-dialog-title"].textContent = exporting ? "导出到 Warframe Rabbit" : "从 Warframe Rabbit 导入";
  ui["rabbit-target"].value = kind === "weapon" ? weaponName(state.buildWeapon) : warframeName(activeWarframeRecord());
  ui["rabbit-archetype"].replaceChildren(...RABBIT_ARCHETYPES[kind].map(([value, label]) => {
    const option = document.createElement("option"); option.value = value; option.textContent = label; return option;
  }));
  ui["rabbit-export-status"].textContent = "";
  ui["rabbit-export-status"].className = "";
  ui["rabbit-import-status"].textContent = "";
  ui["rabbit-import-status"].className = "";
  ui["rabbit-code-result"].hidden = true;
  if (exporting) {
    ui["rabbit-build-title"].value = "";
    ui["rabbit-summary"].value = "";
    ui["rabbit-usage"].value = "";
    ui["rabbit-cautions"].value = "";
    window.setTimeout(() => ui["rabbit-build-title"].focus(), 0);
  } else {
    ui["rabbit-import-code"].value = "";
    window.setTimeout(() => ui["rabbit-import-code"].focus(), 0);
  }
  ui["rabbit-dialog-scrim"].hidden = false;
  ui["rabbit-dialog"].hidden = false;
  document.body.classList.add("is-modal-open");
}

function closeRabbitDialog() {
  if (ui["rabbit-dialog"].hidden) return;
  ui["rabbit-dialog"].hidden = true;
  ui["rabbit-dialog-scrim"].hidden = true;
  document.body.classList.remove("is-modal-open");
}

async function generateRabbitCommand(event) {
  event.preventDefault();
  const status = ui["rabbit-export-status"];
  status.className = "";
  status.textContent = "正在生成配装…";
  ui["rabbit-generate"].disabled = true;
  try {
    const fields = rabbitExportFields();
    const config = rabbitDialogKind === "weapon" ? rabbitWeaponConfig() : rabbitWarframeConfig();
    const meta = rabbitDialogKind === "weapon" ? await rabbitWeaponMeta(fields) : await rabbitWarframeMeta(fields);
    const capacity = rabbitExportCapacity(rabbitDialogKind);
    if (capacity.valid === false || capacity.remaining === null || capacity.remaining < 0) throw new Error("当前配装容量不足，剩余容量必须大于等于 0 才能导出");
    const command = `配卡上传 ${await rabbitEncode(RABBIT_FULL_PREFIX, rabbitCompactUpload(meta, config))}`;
    ui["rabbit-code"].value = command;
    ui["rabbit-code-count"].textContent = `${command.length} / ${RABBIT_COMMAND_LIMIT}`;
    ui["rabbit-code-count"].classList.toggle("is-over", command.length > RABBIT_COMMAND_LIMIT);
    ui["rabbit-copy"].disabled = command.length > RABBIT_COMMAND_LIMIT;
    ui["rabbit-code-result"].hidden = false;
    if (command.length > RABBIT_COMMAND_LIMIT) throw new Error("上传指令超过 QQ 2900 字符预算，请缩短人工描述");
    status.textContent = "Rabbit 上传指令已生成";
  } catch (error) {
    status.className = "is-error";
    status.textContent = error.message || "Rabbit 配装生成失败";
  } finally {
    ui["rabbit-generate"].disabled = false;
  }
}

async function copyRabbitCommand() {
  const command = ui["rabbit-code"].value;
  if (!command || command.length > RABBIT_COMMAND_LIMIT) return;
  try {
    await navigator.clipboard.writeText(command);
  } catch (_error) {
    ui["rabbit-code"].select();
    document.execCommand("copy");
  }
  toast("已复制 Warframe Rabbit 上传指令");
}

async function applyRabbitWeaponConfig(wrapper) {
  const weapon = state.catalog?.weapons?.find((item) => item.path === wrapper.target);
  if (!weapon) throw new Error("Rabbit 配装中的武器不在当前武器目录里");
  setActiveTool("build");
  selectBuildWeapon(weapon);
  const config = wrapper.config || {};
  if (Array.isArray(config.kitgunParts) && config.kitgunParts.length === 3) {
    state.assemblyFor = "build";
    openKitgunAssembly(weapon);
    [state.kitgunParts.chamber, state.kitgunParts.grip, state.kitgunParts.loader] = config.kitgunParts;
    renderKitgunAssembly();
  }
  state.buildConfigs[state.activeConfig] = config;
  applyBuildConfig(config);
  persistActiveBuildConfig();
  scheduleLiveBuild();
}

async function applyRabbitWarframeConfig(wrapper) {
  await loadWarframeCatalog();
  const target = warframeResolve([...warframeRows("warframes"), ...warframeRows("warframeForms")], wrapper.target);
  const frame = target?.parentFrameId ? warframeResolve(warframeRows("warframes"), target.parentFrameId) : target;
  if (!frame) throw new Error("Rabbit 配装中的战甲或第二形态不在当前目录里");
  setActiveTool("warframe");
  selectWarframeFrame(frame);
  switchWarframeForm(target.parentFrameId ? warframeId(target) : "main");
  const build = state.warframeBuild;
  build.configs[build.activeConfig] = wrapper.config || {};
  applyWarframeConfig(build.configs[build.activeConfig]);
  persistWarframeConfig();
}

async function importRabbitConfig() {
  const status = ui["rabbit-import-status"];
  status.className = "";
  status.textContent = "正在解析 Rabbit 配装…";
  ui["rabbit-import-apply"].disabled = true;
  try {
    const wrapper = await rabbitDecode(ui["rabbit-import-code"].value);
    if (Number(wrapper.schema) !== 1 || !["weapon", "warframe"].includes(wrapper.kind) || !wrapper.target || !wrapper.config) throw new Error("Rabbit 配装配置结构无效");
    if (wrapper.kind !== rabbitDialogKind) throw new Error(wrapper.kind === "weapon" ? "这是武器配装码，请从武器配装页导入" : "这是战甲配装码，请从战甲配装页导入");
    if (wrapper.kind === "weapon") await applyRabbitWeaponConfig(wrapper);
    else await applyRabbitWarframeConfig(wrapper);
    closeRabbitDialog();
    toast("Rabbit 配装已导入当前配置槽");
  } catch (error) {
    status.className = "is-error";
    status.textContent = error.message || "Rabbit 配装导入失败";
  } finally {
    ui["rabbit-import-apply"].disabled = false;
  }
}

function issueLabel(value) {
  const issue = String(value || "");
  if (issue === "weapon has no fire modes") return "本地武器数据没有攻击模式";
  if (issue === "weapon has no compatible supported MODs") return "没有兼容且已支持的 MOD";
  const direct = issue.match(/^fire mode (\d+) has no direct damage types$/);
  if (direct) return `模式 ${Number(direct[1]) + 1} 缺少直接伤害类型`;
  const baseline = issue.match(/^fire mode (\d+) has no positive (\w+) baseline$/);
  if (baseline) return `模式 ${Number(baseline[1]) + 1} 缺少可用于${METRIC_LABELS[baseline[2]] || baseline[2]}的正数基础值`;
  if (issue === "headshotChance requires an enemy with a verified head proxy") return "所选目标缺少可验证的爆头倍率，爆头率必须设为 0";
  if (issue.includes("innateElement is only valid")) return "当前武器没有可选的自带元素";
  if (issue.includes("innateElement must be one of")) return "自带元素不属于当前武器候选范围";
  if (issue.includes("innateElementValue must be")) return "自带元素强度必须在 25%–60% 之间";
  return issue;
}

function create(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function imageNode(src, className, alt = "", loading = "lazy") {
  const node = create("img", className);
  // 本地素材加一次性版本号冲掉旧 max-age 缓存条目（曾致重烘焙的 mod 框体
  // 素材不被重新下载）；服务器已对静态资源回 no-cache，今后改动普通刷新即可生效
  node.src = src.startsWith("/") || src.startsWith("assets/") ? src + (src.includes("?") ? "&" : "?") + "v=20260831" : src;
  node.alt = alt;
  node.loading = loading;
  node.decoding = loading === "eager" ? "sync" : "async";
  node.addEventListener("error", () => {
    node.dataset.assetError = "true";
    node.alt = node.alt || "素材加载失败";
  }, { once: true });
  return node;
}

function weaponName(weapon) {
  return weapon?.nameZh || weapon?.nameEn || weapon?.nameInternal || "未知武器";
}

function weaponOptionLabel(weapon) {
  const names = [weapon.nameZh, weapon.nameEn].filter(Boolean);
  const base = [...new Set(names)].join(" · ") || weapon.nameInternal;
  return weapon.analysisAvailable !== false ? base : `[不可用] ${base}`;
}

function fillWeapons() {
  const fragment = document.createDocumentFragment();
  for (const weapon of state.catalog.weapons) {
    const option = document.createElement("option");
    option.value = weaponOptionLabel(weapon);
    option.label = weapon.analysisAvailable !== false
      ? `${TYPE_LABELS[weapon.weaponType] || weapon.weaponType} · 倾向 ${dispositionLabel(weapon)}`
      : `不可用 · ${issueLabel(weapon.analysisIssue || weapon.issue)}`;
    fragment.append(option);
  }
  ui["weapon-options"].replaceChildren(fragment);
}

function buildWeaponOptionLabel(weapon) {
  const base = [weapon.nameZh, weapon.nameEn].filter(Boolean);
  const label = [...new Set(base)].join(" · ") || weapon.nameInternal;
  // 组合枪/组合近战基体自身不可直接配装（无开火模式），但装配腔体/剑刃后
  // 后端会绕过可用性门槛，选择器徽标同样豁免，与武器选择弹窗的口径一致。
  const isAssembly = String(weapon?.nameEn || "").trim() === "Kitgun" || isZawBase(weapon);
  return weapon.buildAvailable === false && !isAssembly ? `[配装不可用] ${label}` : label;
}

function fillBuildWeapons() {
  const fragment = document.createDocumentFragment();
  for (const weapon of state.catalog.weapons.filter((entry) => !entry.hiddenFromBuildPicker)) {
    const option = document.createElement("option");
    option.value = buildWeaponOptionLabel(weapon);
    const isAssembly = String(weapon.nameEn || "").trim() === "Kitgun" || isZawBase(weapon);
    option.label = weapon.buildAvailable === false && !isAssembly
      ? `不可用 · ${issueLabel(weapon.buildIssue || weapon.issue)}`
      : isAssembly
        ? `${TYPE_LABELS[weapon.weaponType] || weapon.weaponType} · 装配后按腔体/剑刃倾向`
        : weaponTypeCaption(weapon);
    fragment.append(option);
  }
  ui["build-weapon-options"].replaceChildren(fragment);
}

function triggerLabel(value, index = 0) {
  const tail = String(value || "").split("/").pop().replace(/^Loadout_Trigger/, "");
  return TRIGGER_LABELS[tail] || (index === 0 ? "主模式" : `模式 ${index + 1}`);
}

function variantLabel(value) {
  return VARIANT_LABELS[value] || String(value || "VT_NORMAL").replace(/^VT_/, "");
}

function resolveWeapon(value) {
  const query = String(value || "").trim().toLocaleLowerCase();
  if (!query) return null;
  return state.catalog.weapons.find((weapon) => [
    weaponOptionLabel(weapon), weapon.path, weapon.nameZh, weapon.nameEn, weapon.nameInternal,
  ].filter(Boolean).some((candidate) => candidate.toLocaleLowerCase() === query)) || null;
}

function resolveBuildWeapon(value) {
  const query = String(value || "").trim().toLocaleLowerCase();
  if (!query) return null;
  return state.catalog.weapons.find((weapon) => [
    buildWeaponOptionLabel(weapon), weapon.path, weapon.nameZh, weapon.nameEn, weapon.nameInternal,
  ].filter(Boolean).some((candidate) => candidate.toLocaleLowerCase() === query)) || null;
}

function formatDisposition(value) {
  const number = finite(value);
  return number === null ? "--" : number.toFixed(2);
}

// 10-23 起紫卡倾向统一 1.2（data/mechanics/riven-disposition.json）；
// 旧的逐武器倾向附在括号里，便于对照已有紫卡。
// 武器选择器里的副标题：显赫武器没有紫卡，不显示倾向，改写携带它的战甲。
function weaponTypeCaption(weapon, withDots = false) {
  const type = TYPE_LABELS[weapon.weaponType] || weapon.weaponType;
  if (weapon.exalted) {
    const frames = (weapon.exalted.frames || []).map((frame) => frame.nameZh || frame.nameEn).filter(Boolean);
    return `${type} · 显赫武器${frames.length ? `（${frames.join(" / ")}）` : ""}`;
  }
  return `${type} · 倾向 ${dispositionLabel(weapon)}${withDots ? ` ${dispositionDots(weapon.disposition)}` : ""}`;
}

function dispositionLabel(weapon) {
  return formatDisposition(weapon?.disposition);
}

function dispositionDots(value) {
  const number = finite(value);
  if (number === null) return "○○○○○";
  const filled = clamp(Math.round(1 + (number - 0.5) * 4), 1, 5);
  return "●".repeat(filled) + "○".repeat(5 - filled);
}

function hashText(value) {
  let hash = 2166136261;
  for (const character of String(value)) {
    hash ^= character.codePointAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function activeStats() {
  return [...ui["stat-rows"].querySelectorAll(".stat-row")].map((row) => {
    const code = row.querySelector(".stat-code").value;
    return {
      row,
      code,
      definition: statDefinitions().find((entry) => entry.code === code) || null,
      value: finite(row.querySelector(".stat-value").value),
      negative: row.querySelector(".sign-toggle").classList.contains("is-negative"),
    };
  });
}

function statDefinitions() {
  return state.weapon ? (state.catalog.statsByType[state.weapon.rivenType || state.weapon.weaponType] || []) : [];
}

function statShape() {
  const rows = activeStats();
  const negative = rows.filter((entry) => entry.negative).length;
  return { total: rows.length, negative, positive: rows.length - negative };
}

function isFactionRivenDefinition(definition) {
  return RIVEN_FACTION_CODES.includes(String(definition?.code || "").toUpperCase());
}

function factionRivenMultiplier(value, negative = false) {
  const delta = Number(value || 0) / 100;
  return 1 + (negative ? -delta : delta);
}

function factionRivenDelta(multiplier) {
  return Math.abs((Number(multiplier) - 1) * 100);
}

// Riven stat window (wiki, Riven Mods, Attribute Value Formula): base value x a
// 90-110% roll x disposition x the card's weight; the engine
// (optimizer.riven_stat_window) and the Bot use the same numbers.
const RIVEN_BONUS_WEIGHTS = { 2: [0.99, 1.2375], 3: [0.75, 0.9375] };
const RIVEN_MALUS_WEIGHTS = { 2: 0.495, 3: 0.75 };

function rivenStatWindow(baseValue, disposition, positiveCount, negativeCount, negative) {
  const positives = positiveCount === 3 ? 3 : 2;
  const weight = negative ? RIVEN_MALUS_WEIGHTS[positives] : RIVEN_BONUS_WEIGHTS[positives][negativeCount ? 1 : 0];
  const nominal = Math.abs(Number(baseValue || 0) * Number(disposition || 0) * weight);
  return { low: nominal * 0.9, high: nominal * 1.1 };
}

function deriveRange(definition, negative) {
  if (!definition || !state.weapon) return null;
  const shape = statShape();
  return rivenStatWindow(definition.baseValue, state.weapon.disposition, shape.positive, shape.negative, negative);
}

function formatStatNumber(value, definition, negative = false) {
  if (value === null || !definition) return "--";
  if (isFactionRivenDefinition(definition)) {
    return `x${factionRivenMultiplier(value, negative).toFixed(2)}`;
  }
  const sign = negative ? "−" : "+";
  const unit = definition.unit === "percent" ? "%" : "";
  return `${sign}${value.toFixed(1)}${unit}`;
}

function setSliderVisual(input) {
  const low = finite(input.min) ?? 0;
  const high = finite(input.max) ?? 1;
  const value = finite(input.value) ?? low;
  input.style.setProperty("--progress", `${high === low ? 0 : ((value - low) / (high - low)) * 100}%`);
}

// 词条中位指示器：当前数值相对「当前武器+当前词条组合」范围中点的偏差。
// 范围随武器倾向（disposition）与词条形态（3正/2正1负/2正…）缩放，这里直接
// 用 deriveRange 的 low/high 取中点，负词条按「数值越低越好」反向标注。
function updateMedianIndicator(row, entry, value) {
  const indicator = row.querySelector(".stat-median-indicator");
  if (!indicator) return;
  const range = deriveRange(entry.definition, entry.negative);
  const number = Number(value);
  if (!range || !Number.isFinite(number) || number <= 0) {
    indicator.hidden = true;
    return;
  }
  const median = (range.low + range.high) / 2;
  const deviation = (number / median - 1) * 100;
  const tolerance = 0.5;
  if (Math.abs(deviation) <= tolerance) {
    indicator.hidden = true;
    return;
  }
  const better = entry.negative ? deviation < 0 : deviation > 0;
  indicator.hidden = false;
  indicator.textContent = `${deviation > 0 ? "↑" : "↓"}${Math.abs(deviation).toFixed(1)}%`;
  indicator.classList.toggle("is-better", better);
  indicator.classList.toggle("is-worse", !better);
  indicator.title = `相对中位数${deviation > 0 ? "高" : "低"} ${Math.abs(deviation).toFixed(1)}%（中位 ${median.toFixed(1)}）`;
}

function refreshRanges(preserveRatio = true) {
  for (const entry of activeStats()) {
    const input = entry.row.querySelector(".stat-value");
    const output = entry.row.querySelector(".stat-output");
    const unit = entry.row.querySelector(".stat-unit");
    const lowLabel = entry.row.querySelector(".range-min");
    const highLabel = entry.row.querySelector(".range-max");
    const range = deriveRange(entry.definition, entry.negative);
    if (!range) {
      input.disabled = true;
      output.disabled = true;
      output.value = "";
      lowLabel.textContent = highLabel.textContent = "--";
      const indicator = entry.row.querySelector(".stat-median-indicator");
      if (indicator) indicator.hidden = true;
      continue;
    }
    const oldLow = finite(input.min);
    const oldHigh = finite(input.max);
    const oldValue = finite(input.value);
    const ratio = preserveRatio && oldLow !== null && oldHigh !== null && oldValue !== null && oldHigh > oldLow
      ? clamp((oldValue - oldLow) / (oldHigh - oldLow), 0, 1)
      : 0.55;
    const value = range.low + (range.high - range.low) * ratio;
    input.disabled = false;
    input.min = range.low.toFixed(3);
    input.max = range.high.toFixed(3);
    input.step = definitionStep(entry.definition);
    input.value = value.toFixed(3);
    const faction = isFactionRivenDefinition(entry.definition);
    lowLabel.textContent = faction ? `x${factionRivenMultiplier(range.low, entry.negative).toFixed(2)}` : range.low.toFixed(1);
    highLabel.textContent = faction ? `x${factionRivenMultiplier(range.high, entry.negative).toFixed(2)}` : range.high.toFixed(1);
    output.disabled = false;
    output.min = faction ? factionRivenMultiplier(range.low, entry.negative).toFixed(2) : range.low.toFixed(3);
    output.max = faction ? factionRivenMultiplier(range.high, entry.negative).toFixed(2) : range.high.toFixed(3);
    output.step = faction ? "0.01" : definitionStep(entry.definition);
    output.value = faction ? factionRivenMultiplier(value, entry.negative).toFixed(2) : value.toFixed(1);
    output.classList.toggle("is-negative", entry.negative);
    if (unit) unit.textContent = faction ? "x" : "";
    updateMedianIndicator(entry.row, entry, value);
    setSliderVisual(input);
  }
  updateCardPreview();
  updateAnalyzeAvailability();
}

function definitionStep(definition) {
  return definition?.unit === "flat" ? "0.01" : "0.1";
}

function fillStatSelect(select, preferredCode) {
  const previous = preferredCode || select.value;
  // 负面行只能选可作负面的词条（元素/融合/穿透等只会是正面）。
  const negativeRow = Boolean(select.closest(".stat-row")?.querySelector(".sign-toggle")?.classList.contains("is-negative"));
  const activeEntries = activeStats();
  const used = new Set(activeEntries.filter((entry) => entry.row.querySelector(".stat-code") !== select).map((entry) => entry.code));
  // 融合词条每卡限 1 条：其他行已有融合词条时，本行禁选所有融合词条。
  const fusionUsedElsewhere = activeEntries.some(
    (entry) => entry.row.querySelector(".stat-code") !== select && entry.definition?.isFusion,
  );
  const options = statDefinitions().map((definition) => {
    const option = document.createElement("option");
    option.value = definition.code;
    const outOfObjective = definition.objectiveSupported ? "" : " · 评分外";
    // 融合词条标 ★（只能通过词条融合获得，不能直接洗出）。
    const fusionMark = definition.isFusion ? "★" : "";
    option.textContent = `${fusionMark}${definition.label}${outOfObjective}`;
    option.disabled = (
      (used.has(definition.code) && definition.code !== previous)
      || (definition.isFusion && fusionUsedElsewhere && definition.code !== previous)
      || (negativeRow && !definition.canNegative)
    );
    if (negativeRow && !definition.canNegative) option.title = "该词条不能作为负面";
    if (definition.isFusion) {
      const recipe = definition.fusionRecipe || {};
      option.title = `融合词条（${recipe.primaryLabel || "?"} + ${recipe.secondaryLabel || "?"} 合成）`;
    }
    return option;
  });
  select.replaceChildren(...options);
  if (options.some((option) => option.value === previous)) select.value = previous;
}

function refreshStatSelects() {
  for (const entry of activeStats()) fillStatSelect(entry.row.querySelector(".stat-code"), entry.code);
}

function chooseUnusedCode(preferred, negative = false) {
  const definitions = statDefinitions().filter((entry) => !negative || entry.canNegative);
  const used = new Set(activeStats().map((entry) => entry.code));
  if (preferred && definitions.some((entry) => entry.code === preferred) && !used.has(preferred)) return preferred;
  return (definitions.find((entry) => entry.objectiveSupported && !used.has(entry.code)) || definitions.find((entry) => !used.has(entry.code)) || definitions[0])?.code;
}

function setRowNegative(row, negative) {
  const button = row.querySelector(".sign-toggle");
  button.classList.toggle("is-positive", !negative);
  button.classList.toggle("is-negative", negative);
  button.textContent = negative ? "−" : "+";
  button.setAttribute("aria-pressed", String(negative));
}

function addStat(preferredCode, preferredNegative = false) {
  if (activeStats().length >= 4) {
    toast("紫卡最多录入 4 条词条");
    return null;
  }
  const fragment = ui["stat-row-template"].content.cloneNode(true);
  const row = fragment.querySelector(".stat-row");
  const select = row.querySelector(".stat-code");
  const input = row.querySelector(".stat-value");
  const negative = preferredNegative || statShape().positive >= 3;
  setRowNegative(row, negative);
  const code = chooseUnusedCode(preferredCode, negative);
  fillStatSelect(select, code);
  select.value = code;

  row.querySelector(".sign-toggle").addEventListener("click", () => toggleSign(row));
  row.querySelector(".remove-stat").addEventListener("click", () => removeStat(row));
  select.addEventListener("change", () => {
    const definition = statDefinitions().find((entry) => entry.code === select.value);
    const negativeRow = row.querySelector(".sign-toggle").classList.contains("is-negative");
    if (negativeRow && !definition?.canNegative) {
      // 选项已禁用，这里只兜底（例如键盘/脚本改值）：退回原词条。
      const fallback = chooseUnusedCode(null, true);
      if (fallback) select.value = fallback;
      toast(`${definition?.label || "该词条"} 不能作为负面词条`);
    } else if (!negativeRow && definition?.canNegative && statShape().positive > 3 && statShape().negative === 0) {
      // 4 条正面不是合法紫卡：本行换成可作负面的词条时恢复为负面。
      setRowNegative(row, true);
    }
    refreshStatSelects();
    refreshRanges(false);
  });
  input.addEventListener("input", () => {
    const entry = activeStats().find((item) => item.row === row);
    const number = row.querySelector(".stat-number");
    const raw = finite(input.value);
    number.value = raw === null ? "" : (isFactionRivenDefinition(entry?.definition)
      ? factionRivenMultiplier(raw, entry.negative).toFixed(2)
      : raw.toFixed(1));
    number.classList.toggle("is-negative", Boolean(entry?.negative));
    updateMedianIndicator(row, entry, raw);
    setSliderVisual(input);
    updateCardPreview();
  });
  const number = row.querySelector(".stat-number");
  number.addEventListener("input", () => {
    const entered = finite(number.value);
    if (entered === null) return;
    const entry = activeStats().find((item) => item.row === row);
    const value = isFactionRivenDefinition(entry?.definition) ? factionRivenDelta(entered) : entered;
    const low = finite(input.min) ?? 0;
    const high = finite(input.max) ?? value;
    input.value = String(clamp(value, low, high));
    updateMedianIndicator(row, entry, clamp(value, low, high));
    setSliderVisual(input);
    updateCardPreview();
  });
  number.addEventListener("change", () => {
    // 失焦时把输入归一到合法区间并重写显示值
    const entry = activeStats().find((item) => item.row === row);
    const low = finite(input.min) ?? 0;
    const high = finite(input.max) ?? low;
    const entered = finite(number.value);
    const raw = isFactionRivenDefinition(entry?.definition) && entered !== null ? factionRivenDelta(entered) : entered;
    const value = clamp(raw ?? low, low, high);
    input.value = String(value);
    number.value = isFactionRivenDefinition(entry?.definition)
      ? factionRivenMultiplier(value, entry.negative).toFixed(2)
      : value.toFixed(1);
    updateMedianIndicator(row, entry, value);
    setSliderVisual(input);
    updateCardPreview();
  });
  ui["stat-rows"].append(fragment);
  refreshStatSelects();
  refreshRanges(false);
  return row;
}

function toggleSign(row) {
  const entries = activeStats();
  const current = entries.find((entry) => entry.row === row);
  if (!current) return;
  if (!current.negative) {
    if (!current.definition?.canNegative) {
      toast(`${current.definition?.label || "该词条"} 不能作为负面词条`);
      return;
    }
    if (entries.some((entry) => entry.negative)) {
      toast("一张紫卡最多只有 1 条负面词条");
      return;
    }
    if (statShape().positive <= 2) {
      toast("至少需要 2 条正面词条");
      return;
    }
  }
  setRowNegative(row, !current.negative);
  refreshStatSelects();
  refreshRanges(true);
}

function removeStat(row) {
  if (activeStats().length <= 2) {
    toast("至少保留 2 条词条");
    return;
  }
  row.remove();
  refreshStatSelects();
  refreshRanges(true);
}

// 偏好复合元素键 → 伤害类型（与后端 ELEMENT_TARGETS 同口径），仅用于图标显示。
const ELEMENT_TARGET_TO_DAMAGE_TYPE = {
  heat: "DT_FIRE", cold: "DT_FREEZE", electricity: "DT_ELECTRICITY", toxin: "DT_POISON",
  blast: "DT_EXPLOSION", radiation: "DT_RADIATION", gas: "DT_GAS", magnetic: "DT_MAGNETIC",
  viral: "DT_VIRAL", corrosive: "DT_CORROSIVE",
};

// 分析页元素选择：天生元素（赤毒/信条/终幕，默认毒、不记忆）。
// 偏好复合元素已按用户要求移除（对赤毒/信条/终幕无意义——先祖元素
// 天生参与组合，偏好约束反而经常不可达）。
const ANALYSIS_PREFERRED_ELEMENT_KEY = "wf-riven-portable-analysis-preferred-element-v1";
const PREFERRED_ELEMENT_OPTIONS = [
  ["", "不限定"],
  ["corrosive", "腐蚀"], ["viral", "病毒"], ["heat", "火焰"], ["cold", "冰冻"],
  ["electricity", "电击"], ["toxin", "毒素"], ["radiation", "辐射"],
  ["magnetic", "磁力"], ["gas", "毒气"], ["blast", "爆炸"],
];
function analysisPreferredElement() {
  // 兼容旧 localStorage 残值：读到的值不再消费，恒返回空（不限定）。
  return "";
}
function analysisInnateElementDefault(candidates) {
  // 赤毒/信条/终幕的先祖元素：默认毒（DT_POISON），候选不含毒时取第一个。
  return candidates.includes("DT_POISON") ? "DT_POISON" : (candidates[0] || "");
}
function refreshAnalysisElementFields() {
  const field = ui["analysis-innate-element-field"];
  const innateSelect = ui["analysis-innate-element-select"];
  if (!field || !innateSelect) return;
  const candidates = Array.isArray(state.weapon?.innateElementCandidates) ? state.weapon.innateElementCandidates : [];
  field.hidden = !candidates.length;
  if (candidates.length) {
    const previous = innateSelect.value;
    innateSelect.replaceChildren(...candidates.map((damageType) => {
      const option = document.createElement("option");
      option.value = damageType;
      option.textContent = DAMAGE_TYPE_LABELS[damageType] || damageType;
      return option;
    }));
    // 天生元素不记忆：换武器时重置为默认（毒）。
    innateSelect.value = candidates.includes(previous) ? previous : analysisInnateElementDefault(candidates);
  }
  setAnalysisElementIcons();
  refreshAnalysisMeleeRoute();
}
// 近战攻击路线（走 A / 震地两种高度 / 战刃重投引爆）：只对近战显示，战刃项只对战刃显示。
function refreshAnalysisMeleeRoute() {
  const field = ui["analysis-melee-route-field"];
  const select = ui["analysis-melee-route-select"];
  if (!field || !select) return;
  const weapon = state.weapon || {};
  const melee = ["melee", "zaw"].includes(String(weapon.weaponType || "").toLowerCase()) || weapon.slot === "melee";
  field.hidden = !melee;
  refreshMeleeRouteOptions(select, weapon, "analysis");
  if (!melee) select.value = "";
}
function refreshMeleeRouteOptions(select, weapon, surface) {
  if (!select) return;
  const tags = new Set((weapon?.compatTags || []).map((tag) => String(tag).toUpperCase()));
  if (isZawBase(weapon) && state.assemblyFor === surface) {
    const tag = zawAssemblyStanceTag();
    if (tag) tags.add(tag);
  }
  for (const [route, allowed] of [["glaive", tags.has("GLAIVES_STANCE")], ["slamContinuous", tags.has("HAMMERS_STANCE")]]) {
    const option = select.querySelector(`option[value="${route}"]`);
    if (option) { option.hidden = !allowed; option.disabled = !allowed; }
    if (!allowed && select.value === route) select.value = "";
  }
}
function setAnalysisElementIcons() {
  const innate = ui["analysis-innate-element-select"]?.value || "";
  const innateIcon = ui["analysis-innate-element-icon"];
  if (innateIcon) {
    innateIcon.src = ELEMENT_ICONS[innate] || "";
    innateIcon.hidden = !ELEMENT_ICONS[innate];
    innateIcon.alt = DAMAGE_TYPE_LABELS[innate] || "";
  }
}

function selectWeapon(weapon, writeInput = true) {
  const changed = weapon?.path !== state.weapon?.path;
  state.weapon = weapon;
  // 普通武器接管分析页时，收起可能挂在分析区的共享装配面板
  const analysisHost = document.getElementById("analysis-assembly-slot");
  const assemblyPanel = document.getElementById("kitgun-assembly");
  if (analysisHost && assemblyPanel && assemblyPanel.parentElement === analysisHost) {
    assemblyPanel.hidden = true;
    if (state.assemblyFor === "analysis") {
      state.assemblyFor = "build";
      state.kitgunBase = null;
      state.kitgunParts = null;
    }
  }
  if (writeInput) ui.weapon.value = weapon ? weaponOptionLabel(weapon) : "";
  if (!weapon) {
    ui["weapon-caption"].textContent = "请选择目录中的完整武器名称";
    ui["disposition-value"].textContent = "--";
    ui["disposition-dots"].textContent = "○○○○○";
    ui["weapon-issue"].hidden = true;
    refreshRanges(false);
    return;
  }
  ui["weapon-caption"].textContent = `${TYPE_LABELS[weapon.weaponType] || weapon.weaponType} · ${weapon.nameInternal}`;
  ui["disposition-value"].textContent = formatDisposition(weapon.disposition);
  ui["disposition-dots"].textContent = dispositionDots(weapon.disposition);
  ui["weapon-issue"].hidden = weapon.analysisAvailable !== false;
  ui["weapon-issue-text"].textContent = issueLabel(weapon.analysisIssue || weapon.issue);
  refreshAnalysisElementFields();
  if (changed) {
    const previous = activeStats().map((entry) => ({ code: entry.code, negative: entry.negative }));
    ui["stat-rows"].replaceChildren();
    for (const entry of previous.length >= 2 ? previous : [{}, {}, {}]) addStat(entry.code, entry.negative);
    state.requestedFireMode = null;
    clearResult();
  } else {
    refreshStatSelects();
    refreshRanges(false);
  }
  updateCardPreview();
}

function updateCardPreview() {
  refreshAnalysisFavoriteButton();
  const entries = activeStats();
  const seedSource = `${state.weapon?.path || "empty"}:${entries.map((entry) => `${entry.code}:${entry.value}:${entry.negative}`).join("|")}`;
  const seed = hashText(seedSource);
  const filled = entries.filter((entry) => entry.definition && entry.value !== null);
  ui["card-name"].textContent = state.weapon ? rivenCardName(state.weapon, filled, statDefinitions()) : "未命名紫卡";
  const arts = state.weapon ? rivenFaceArts(filled, statDefinitions()) : [];
  const artKey = arts.join("|");
  if (ui["riven-card"].dataset.faces !== artKey) {
    ui["riven-card"].dataset.faces = artKey;
    ui["riven-card"].querySelector(".riven-card-art")?.remove();
    if (arts.length) {
      const art = create("div", "riven-card-art");
      art.setAttribute("aria-hidden", "true");
      art.append(...rivenFaceCanvases(arts, "riven-art-bg", "riven-art-fg"));
      ui["riven-card"].prepend(art);
    }
  }
  ui["card-mr"].textContent = String(8 + (seed % 9));
  ui["card-rerolls"].textContent = String((seed >>> 4) % 1000);
  const polarityNames = RIVEN_CARD_POLARITIES;
  const polarity = polarityNames[(seed >>> 10) % polarityNames.length];
  ui["card-polarity"].src = POLARITY_IMAGES[polarity];
  ui["card-polarity"].alt = `${polarity} 极性`;

  const lines = entries.filter((entry) => entry.definition && entry.value !== null).map((entry) => {
    const line = create("span", entry.negative ? "is-negative" : "");
    // 融合词条（Advanced Traits）：金框样式 + hover 合成路径。
    if (entry.definition.isFusion) {
      line.classList.add("is-fusion");
      const recipe = entry.definition.fusionRecipe || {};
      line.title = `融合词条 · 合成路径：${recipe.primaryLabel || recipe.primary || "?"} + ${recipe.secondaryLabel || recipe.secondary || "?"} → ${entry.definition.label}`;
    }
    line.textContent = `${formatStatNumber(entry.value, entry.definition, entry.negative)} ${entry.definition.label}`;
    return line;
  });
  ui["card-stats"].replaceChildren(...(lines.length ? lines : [create("span", "card-empty", "等待录入词条")]));
  ui["riven-card"].classList.toggle("is-active", Boolean(state.weapon && lines.length));
  requestAnimationFrame(fitRivenCardText);
}

// 卡名、词条行按卡宽缩小字号直到放得下（长武器名 / 系统字体或最小字号偏大时不出框）。
function fitRivenCardText() {
  const fit = (node, min) => {
    node.style.fontSize = "";
    let size = parseFloat(getComputedStyle(node).fontSize);
    while (node.clientWidth && node.scrollWidth > node.clientWidth && size > min) {
      size -= 0.5;
      node.style.fontSize = `${size}px`;
    }
  };
  fit(ui["card-name"], 11);
  ui["card-stats"].querySelectorAll("span").forEach((node) => fit(node, 10));
}

function rivenWeaponDisplayName(weapon) {
  let name = String(weapon?.nameZh || weapon?.nameEn || weapon?.nameInternal || "Riven").trim();
  name = name.replace(/\s+Prime$/i, "").replace(/\s+Prime版$/i, "").trim();
  return name || "Riven";
}

function updateAnalyzeAvailability() {
  const shape = statShape();
  const validShape = shape.total >= 2 && shape.total <= 4 && (shape.positive === 2 || shape.positive === 3) && shape.negative <= 1
    && activeStats().every((entry) => !entry.negative || entry.definition?.canNegative);
  const isAssembly = state.assemblyFor === "analysis" && state.kitgunBase && state.kitgunBase.path === state.weapon?.path;
  const weaponReady = Boolean(state.weapon) && (isAssembly ? assemblyWeaponReady() : state.weapon.analysisAvailable !== false);
  ui["analyze-button"].disabled = !weaponReady || !validShape || ui["analyze-button"].classList.contains("is-loading");
  ui["add-stat"].disabled = shape.total >= 4 || !state.weapon;
}

function solveProfile() {
  // 解算档位：两个选择器（分析页内联 / 配装页字段）共享 localStorage，
  // 任一处改动即全局生效。
  const value = window.localStorage.getItem("wf-solve-profile");
  return ["ultra", "fast", "standard", "deep"].includes(value) ? value : "standard";
}

function scopeFillValue(id) {
  const raw = document.getElementById(id)?.value;
  const parsed = Number(raw);
  if (raw === "" || raw === undefined || raw === null || !Number.isFinite(parsed)) return undefined;
  return clamp(Math.round(parsed), 0, 8);
}

function readStoredList(key) {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) || "[]");
    return Array.isArray(value) ? value.filter((item) => typeof item === "string" && item) : [];
  } catch {
    return [];
  }
}

function writeStoredList(key, list) {
  try { window.localStorage.setItem(key, JSON.stringify(list)); } catch { /* 本机记忆不可用时只在本次会话生效 */ }
}

function readStoredFlag(key) {
  try { return window.localStorage.getItem(key) === "1"; } catch { return false; }
}

// 本武器禁选 + 全局屏蔽（只发目录里存在、且不在本武器必选里的卡）。
function scopeForbiddenPaths() {
  const known = new Set((state.catalog?.manualMods || []).map((mod) => mod.path));
  const paths = [...new Set([...state.forbiddenMods, ...state.globalForbiddenMods])]
    .filter((path) => known.has(path) && !state.requiredMods.includes(path));
  return paths.length ? paths : undefined;
}

function scopeMenuButtons(path, after) {
  const entries = [
    ["required", state.requiredMods.includes(path), "✓ 必选（点击移除）", "加入必选"],
    ["forbidden", state.forbiddenMods.includes(path), "✓ 本武器禁选（点击移除）", "本武器禁选"],
    ["global", state.globalForbiddenMods.includes(path), "✓ 全局屏蔽（点击移除）", "全局屏蔽（所有武器）"],
  ];
  return entries.map(([kind, active, on, off]) => {
    const button = create("button", "", active ? on : off);
    button.type = "button";
    button.addEventListener("click", () => { toggleScopeMod(path, kind); closeScopeMenu(); after?.(kind, active); });
    return button;
  });
}

function toggleScopeMod(path, kind) {
  // kind: "required" | "forbidden" | "global" — 本武器必选/禁选互斥；
  // 全局屏蔽跨武器生效，加入时同时移出本武器必选。
  if (kind === "global") {
    const list = state.globalForbiddenMods;
    const index = list.indexOf(path);
    if (index >= 0) list.splice(index, 1);
    else {
      list.push(path);
      state.requiredMods = state.requiredMods.filter((p) => p !== path);
    }
    writeStoredList("wf-global-forbidden-mods", list);
    renderScopeLists();
    persistActiveBuildConfig();
    scheduleLiveBuild();
    return;
  }
  if (kind === "required") {
    state.globalForbiddenMods = state.globalForbiddenMods.filter((p) => p !== path);
    writeStoredList("wf-global-forbidden-mods", state.globalForbiddenMods);
  }
  const other = kind === "required" ? "forbiddenMods" : "requiredMods";
  state[other] = state[other].filter((p) => p !== path);
  const list = kind === "required" ? state.requiredMods : state.forbiddenMods;
  const index = list.indexOf(path);
  if (index >= 0) list.splice(index, 1);
  else list.push(path);
  renderScopeLists();
  persistActiveBuildConfig();
  scheduleLiveBuild();
}

function renderScopeLists() {
  const required = document.getElementById("build-required-list");
  const forbidden = document.getElementById("build-forbidden-list");
  if (!required || !forbidden) return;
  const chip = (path, kind) => {
    const mod = state.modAssets?.mods?.[path] || { nameZh: path, nameEn: "" };
    const node = create("span", `scope-chip is-${kind}`);
    node.append(document.createTextNode(mod.nameZh || mod.nameEn || path));
    const remove = create("button", "", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", "移除");
    remove.addEventListener("click", () => toggleScopeMod(path, kind));
    node.append(remove);
    return node;
  };
  required.replaceChildren(
    create("span", "scope-empty", "必选："),
    ...(state.requiredMods.length
      ? state.requiredMods.map((p) => chip(p, "required"))
      : [create("span", "scope-empty", "无（长按/右键 MOD 加入）")])
  );
  forbidden.replaceChildren(
    create("span", "scope-empty", "禁选："),
    ...(state.forbiddenMods.length
      ? state.forbiddenMods.map((p) => chip(p, "forbidden"))
      : [create("span", "scope-empty", "无")])
  );
  const global = document.getElementById("build-global-forbidden-list");
  if (global) {
    global.replaceChildren(
      create("span", "scope-empty", "全局屏蔽："),
      ...(state.globalForbiddenMods.length
        ? state.globalForbiddenMods.map((p) => chip(p, "global"))
        : [create("span", "scope-empty", "无（所有武器生效）")])
    );
  }
  const faction = document.getElementById("build-exclude-faction");
  if (faction) faction.checked = state.excludeFactionMods;
  // 数量范围输出回显
  const lo = scopeFillValue("build-min-fill");
  const hi = scopeFillValue("build-max-fill");
  const output = document.getElementById("build-fill-output");
  if (output) {
    output.textContent = lo === undefined && hi === undefined
      ? "不限制"
      : `${lo ?? 0} – ${hi ?? 8}`;
  }
}

function setSolveProfile(profile) {
  const next = ["ultra", "fast", "standard", "deep"].includes(profile) ? profile : "standard";
  window.localStorage.setItem("wf-solve-profile", next);
  for (const id of ["analysis-profile-select", "solve-profile-select"]) {
    const select = document.getElementById(id);
    if (select) select.value = next;
  }
}

function payloadFromForm() {
  if (!state.weapon) throw new Error("请从武器目录中选择一把武器");
  const isAssembly = state.assemblyFor === "analysis" && state.kitgunBase && state.kitgunBase.path === state.weapon.path;
  if (isAssembly && !assemblyWeaponReady()) throw new Error("组合武器需要先完成三件部件装配");
  if (!isAssembly && state.weapon.analysisAvailable === false) throw new Error(state.weapon.analysisIssue || state.weapon.issue || "该武器暂不可分析");
  const entries = activeStats();
  const shape = statShape();
  if (entries.length < 2 || entries.length > 4 || ![2, 3].includes(shape.positive) || shape.negative > 1) {
    throw new Error("需要 2 或 3 条正面词条，并且最多 1 条负面词条");
  }
  if (new Set(entries.map((entry) => entry.code)).size !== entries.length) throw new Error("同一词条不能重复录入");
  const stats = entries.map((entry) => {
    if (!entry.definition || entry.value === null) throw new Error("存在未完成的词条");
    const range = deriveRange(entry.definition, entry.negative);
    if (!range || entry.value < range.low - 0.11 || entry.value > range.high + 0.11) throw new Error(`${entry.definition.label} 数值超出当前范围`);
    return { code: entry.code, value: Number(entry.value.toFixed(3)), negative: entry.negative };
  });
  const payload = { weapon: state.weapon.path, disposition: state.weapon.disposition, stats, profile: solveProfile() };
  const headshots = Number(ui["analysis-headshot-chance"]?.value || 0);
  if (!Number.isFinite(headshots) || headshots < 0 || headshots > 100) throw new Error("弱点命中率必须在 0% 到 100% 之间");
  payload.headshotChance = headshots / 100;
  // 天生元素（赤毒/信条/终幕）：候选存在时随请求下发，参与分析与配装。
  const innateCandidates = Array.isArray(state.weapon.innateElementCandidates) ? state.weapon.innateElementCandidates : [];
  if (innateCandidates.length) {
    const innate = ui["analysis-innate-element-select"]?.value || analysisInnateElementDefault(innateCandidates);
    if (innate) payload.innateElement = innate;
  }
  // 偏好复合元素已移除（分析页不再下发 elementTarget）。
  const meleeRoute = ui["analysis-melee-route-field"]?.hidden ? "" : ui["analysis-melee-route-select"]?.value;
  if (meleeRoute) payload.meleeRoute = meleeRoute;
  if (typeof state.requestedFireMode === "number") payload.fireMode = state.requestedFireMode;
  if (isAssembly) {
    payload.kitgunParts = [state.kitgunParts.chamber, state.kitgunParts.grip, state.kitgunParts.loader];
  }
  return payload;
}

function showFormMessage(message) {
  ui["form-message"].hidden = !message;
  ui["form-message"].textContent = message || "";
}

function setResultState(name) {
  ui["result-idle"].hidden = name !== "idle";
  ui["result-loading"].hidden = name !== "loading";
  ui["result-error"].hidden = name !== "error";
  ui["result-content"].hidden = name !== "content";
  ui["result-badge"].textContent = { idle: "WAITING", loading: "SOLVING", error: "ERROR", content: "COMPLETE" }[name];
  ui["result-badge"].classList.toggle("is-live", name === "content");
}

function clearResult() {
  state.result = null;
  state.lastPayload = null;
  state.submittedStats = [];
  ui["export-button"].disabled = true;
  setResultState("idle");
}

async function submitAnalysis(event) {
  event?.preventDefault();
  if (ui["analyze-button"].classList.contains("is-loading")) return;
  let payload;
  try {
    payload = payloadFromForm();
  } catch (error) {
    showFormMessage(error.message);
    toast(error.message);
    return;
  }
  showFormMessage("");
  state.lastPayload = payload;
  state.submittedStats = activeStats().map((entry) => ({ code: entry.code, negative: entry.negative }));
  ui["analyze-button"].classList.add("is-loading");
  ui["analyze-button"].disabled = true;
  setResultState("loading");
  // ── 进度上报（阶段心跳 + 已用时间）：区分「还在跑」与「卡死」─────────
  const progressToken = `an-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  payload.progressToken = progressToken;
  const STAGE_LABELS = {
    baseline: "基准配装与武器靶",
    actual: "当前紫卡配装求解",
    recommendation: "词条优先级排序",
    quality: "词条贡献",
    payload: "结果构建",
  };
  const TOTAL_STAGES = Object.keys(STAGE_LABELS).length;
  const startedAt = performance.now();
  let lastStage = "";
  const beatTimer = window.setInterval(() => {
    const elapsed = (performance.now() - startedAt) / 1000;
    let beat = null;
    fetch(`/api/analyze/progress?id=${encodeURIComponent(progressToken)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((row) => { if (row) beat = row; return row; })
      .catch(() => {})
      .finally(() => {
        const stageList = beat?.stages || [];
        const stage = beat?.currentStage || stageList[stageList.length - 1] || "";
        const pct = beat ? Math.round(beat.percent) : null;
        const stageLabel = STAGE_LABELS[stage] || (stage ? stage : "准备中");
        const elapsedText = elapsed < 60 ? `${elapsed.toFixed(0)}s` : `${Math.floor(elapsed / 60)}m${Math.round(elapsed % 60)}s`;
        // 无心跳数据（旧后端/轮询失败）：只显示阶段文案循环 + 计时。
        if (beat) {
          const bar = `${"█".repeat(Math.round((pct || 0) / 10))}${"░".repeat(10 - Math.round((pct || 0) / 10))}`;
          ui["loading-copy"].textContent = `${stageLabel} ${bar} ${pct}% · ${elapsedText}${beat.evaluations ? ` · 已评估 ${beat.evaluations} 个候选` : ""}${beat.secondsSinceBeat > 30 ? " · 长时间无计算进展" : ""}`;
        } else {
          ui["loading-copy"].textContent = `${STAGE_LABELS[stage] || "解算中"} · 已用 ${elapsedText}`;
        }
        lastStage = stage;
      });
  }, 500);
  const messages = ["比对武器档案与词条贡献", "求解包含当前紫卡的 8 槽配装", "整理 T0–T3 词条优先级"];
  let messageIndex = 0;
  state.loadingTimer = window.setInterval(() => {
    // 阶段文案由心跳接管；无心跳时保留旧轮播（500ms 心跳失败场景）。
    messageIndex = (messageIndex + 1) % messages.length;
  }, 900);
  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body?.error?.message || `分析失败（${response.status}）`);
    state.result = body;
    state.buildMode = "actual";
    renderResult();
    rememberAnalysisResult();
    ui["export-button"].disabled = false;
    setResultState("content");
    ui["result-content"].scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    ui["error-message"].textContent = error.message || "分析失败";
    setResultState("error");
  } finally {
    window.clearInterval(state.loadingTimer);
    window.clearInterval(beatTimer);
    state.loadingTimer = null;
    ui["analyze-button"].classList.remove("is-loading");
    updateAnalyzeAvailability();
  }
}

function formatPercent(value) {
  const number = finite(value);
  return number === null ? "--" : `${number >= 0 ? "+" : ""}${number.toFixed(1)}%`;
}

function formatQuality(value) {
  const number = finite(value);
  return number === null ? "--" : `${number.toFixed(1)}%`;
}

function renderScore() {
  // 不再有 0–100 评分与理论上限：头条是相对无紫卡基线的实际增益，
  // 同一武器的所有紫卡都在同一个固定靶上比较。
  const gain = finite(state.result.actualGain);
  ui["score-value"].textContent = formatPercent(gain);
  ui["score-value"].classList.toggle("is-long", ui["score-value"].textContent.length > 6);
  const target = state.result.evaluationTarget || {};
  // 硬度积分靶：三个血量节点（无紫卡基线身体命中的击杀时间），KPM 为几何平均。
  const nodes = state.result.targetCalibration?.hardnessNodes || [];
  const ttkText = nodes.length ? nodes.map((node) => Number(node.ttkSeconds).toFixed(1)).join("/") : null;
  const grade = ui["grade-value"];
  grade.classList.toggle("ttk-nodes", nodes.length > 0);
  grade.replaceChildren();
  if (nodes.length) {
    grade.append(create("em", "", "基线击杀"), ...nodes.map((node) => create("span", "", `${Number(node.ttkSeconds).toFixed(1)} s`)));
  } else {
    grade.textContent = "--";
  }
  const resultWeapon = state.result?.weapon;
  const displayWeapon = resultWeapon && (resultWeapon.nameZh || resultWeapon.nameEn) ? resultWeapon : state.weapon;
  ui["weapon-result-name"].textContent = `${weaponName(displayWeapon)} · ${TYPE_LABELS[state.weapon.weaponType] || state.weapon.weaponType}`;
  ui["actual-gain"].textContent = formatPercent(gain);
  const kpm = (build) => {
    const value = finite(build?.objectiveScore);
    return value === null ? "--" : value.toFixed(1);
  };
  ui["optimal-gain"].textContent = kpm(state.result.baseline);
  ui["roll-quality"].textContent = kpm(state.result.actual);
  ui["result-disposition"].textContent = formatDisposition(state.result.disposition);
  const circumference = 2 * Math.PI * 51;
  const fill = gain === null ? 0 : Math.max(0, gain) / (Math.max(0, gain) + 100);
  ui["orbit-value"].style.strokeDasharray = String(circumference);
  ui["orbit-value"].style.strokeDashoffset = String(circumference * (1 - fill));
  ui["score-orbit"].dataset.grade = "";
  const calibration = state.result.targetCalibration || {};
  const weaponMechanics = state.result.weaponMechanics || {};
  ui["score-value"].title = [
    target.level != null ? `评价等级：${target.level}` : null,
    ttkText ? `靶血量取本武器无紫卡基线身体命中 ${ttkText}s 击杀的三个节点，KPM 为几何平均` : null,
    state.result.modelStatus ? `模型：${state.result.modelStatus}` : null,
    weaponMechanics.status ? `武器机制：${weaponMechanics.status}` : null,
  ].filter(Boolean).join(" · ");
  const contextNote = ui["score-context-note"];
  if (contextNote) {
    const bits = [];
    const enemyName = target.enemyName || target.enemyPath?.rsplit?.("/", 1)?.pop?.() || "";
    if (enemyName) bits.push(`靶 ${enemyName}`);
    if (target.level != null) bits.push(`Lv${target.level}`);
    if (target.steelPath) bits.push("钢铁之路");
    if (target.enemyEnhancements?.noOverguard) bits.push("无超宏");
    if (ttkText) bits.push(`硬度积分：基线 ${ttkText}s 击杀（同武器所有紫卡与弱点率共用）`);
    if (state.result.unsupported?.includes?.("ultra-profile-baseline-approximate")) bits.push("超快：基线为近似，增益仅供参考");
    if (state.result.modelStatus && state.result.modelStatus !== "modeled") {
      bits.push(`模型 ${state.result.modelStatus}`);
    }
    if (weaponMechanics.status && weaponMechanics.status !== "modeled") {
      bits.push(`武器机制 ${weaponMechanics.status}`);
    }
    contextNote.textContent = bits.join(" · ");
    contextNote.hidden = bits.length === 0;
  }
}

function renderContributions() {
  const details = Array.isArray(state.result.details) ? state.result.details : [];
  const max = Math.max(1, ...details.map((entry) => Math.abs(finite(entry.delta) ?? 0)));
  // 融合词条码集合（贡献行的金框标注——与 updateCardPreview 的 is-fusion 同源）。
  const fusionDefs = statDefinitions().filter((d) => d.isFusion);
  const fusionByCode = new Map(fusionDefs.map((d) => [d.code, d]));
  const rows = details.map((detail) => {
    const negative = state.submittedStats.find((entry) => entry.code === detail.code)?.negative;
    const delta = detail.delta == null ? null : finite(detail.delta);
    const reoptimized = finite(detail.reoptimizedDelta);
    const fusionDef = fusionByCode.get(detail.code) || null;
    const row = create("article", `contribution-row${delta !== null && delta < 0 ? " is-harmful" : ""}${fusionDef ? " is-fusion" : ""}`);
    const head = create("div", "contribution-head");
    const title = create("div");
    title.append(create("span", "contribution-sign", negative ? "−" : "+"), create("strong", "", `${detail.label || detail.code}${fusionDef ? " ★" : ""}`));
    if (fusionDef) {
      const recipe = fusionDef.fusionRecipe || {};
      title.title = `融合词条 · 合成路径：${recipe.primaryLabel || recipe.primary || "?"} + ${recipe.secondaryLabel || recipe.secondary || "?"} → ${fusionDef.label}`;
    }
    const value = create("div", "contribution-values");
    // F08：主数值是「同一配卡移除此词条」的消融口径；重优化收益（删词条
    // 并重选 MOD）单独展示，两者不再混为一谈。
    value.append(
      create("b", "", delta === null ? "未计算" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`),
      create("span", "", `数值 ${formatQuality(detail.quality)}`),
    );
    if (!detail.inactiveReason && delta !== null && reoptimized !== null && Math.abs(reoptimized - delta) > 0.05) {
      const tag = create("span", "contribution-reopt", `重优化 ${reoptimized >= 0 ? "+" : ""}${reoptimized.toFixed(1)}%`);
      tag.title = "移除该词条并允许重选普通 MOD 后的目标指标变化（联合收益口径）";
      value.append(tag);
    }
    head.append(title, value);
    const track = create("div", "contribution-track");
    const fill = create("i");
    fill.style.width = `${delta === null ? 0 : Math.max(delta === 0 ? 2 : 7, Math.abs(delta) / max * 100)}%`;
    track.append(fill);
    row.append(head, track);
    if (detail.inactiveReason || detail.condition) row.append(create("small", "contribution-condition", detail.inactiveReason || detail.condition));
    return row;
  });
  ui["contribution-list"].replaceChildren(...(rows.length ? rows : [create("p", "empty-copy", "没有可显示的贡献明细")]))
}

const DIAGNOSTIC_CODE_LABELS = {
  'arbucep-body-contact-explicit-target-packets-no-head-events': 'Arbucep 按每枚弹体命中原目标身体及中心爆炸计算，不额外假定头部事件',
  'battacor-ray-hit-avatar-radial-CO-miss-bystanders-excluded': '武使之力范围包的异况用于射线命中的原目标，不将同一资格扩给旁观目标',
  'scourge-prime-original-surviving-host-attachment-policy': '祸根 Prime 的每秒嵌入伤害仅作用于仍存活的原宿主，下次投掷取消旧矛跳伤',
  'scourge-prime-contact-main55-body-geometry-policy': '祸根 Prime 主爆炸采用明确接触目标的身体覆盖策略，弱点事件不额外假定',
  'embedded-death-native-jitter-mean-delay-assumed': '嵌入计时结束后还有原生死亡调度延迟，当前采用其均值',
  'cluster-child-flight-and-contact-grouping-approximated': '集束子弹按逐枚直击、再爆炸结算；飞行与同目标覆盖采用所选近似',
  'cluster-nonstandard-source-CO-base-query-unverified': '集束子弹按普通武器来源计算异况基数，特殊外部来源仍有未校准项',
  'embedded-field-attached-target-coverage-assumed': '附着伤害场按持续覆盖原目标计算，原目标死亡后不自动覆盖下一敌人',
  'embedded-field-live-damage-status-retained-crit-and-source-context': '附着场每跳读取当前伤害、元素、触发及异况加成；暴击与特殊来源缓存保留弹体快照',
  'embedded-field-nonstandard-source-CO-base-query-unverified': '附着场的特殊外部来源基数尚未校准',
  'phantasma-child-ideal-contact-and-arrival-time-assumed': '幻离子子弹按所选到达时间命中原目标身体，并计中心爆炸覆盖',
  'phantasma-child-overlap-off-until-explicit-geometry-policy': '幻离子分裂子弹默认不计命中；可在攻击策略中选择理想覆盖',
  'phantasma-child-body-geometry-and-flight-policy-explicit': '幻离子子弹的真实飞行、遮挡和命中部位取决于场景',
  'trumna-single-target-first-contact-policy-additional-bounce-coverage-excluded': 'Trumna 当前只计首次有效接触，后续弹跳是否再次覆盖原目标需另行确定',
  'sepulcrum-one-live-lock-ideal-contact-policy-geometric-arrival-assumed': 'Sepulcrum 单目标锁定按一枚主导弹计算，飞行与命中位置采用理想接触',
  'zymos-child-overlap-off-until-explicit-geometry-policy': '邪莫斯追踪子弹默认不计命中；可选择返回仍存活原目标的策略',
  'zymos-original-surviving-host-body-contact-policy': '邪莫斯追踪子弹按返回原目标身体计算；原目标死亡后不转移到下一敌人',
  'zymos-selected-frame-and-flight-timing': '邪莫斯子弹按所选帧间隔与飞行时间到达，真实时间受帧率和场景影响',
  'zymos-callback-firecount-independent-current-source-query': '邪莫斯子弹继承的直击伤害按创建时的武器加成与多重重新计算',
  'zymos-two-source-enervate-snapshots-use-marginal-probabilities': '邪莫斯在两次创建阶段分别读取次要·激昂；跨时刻状态相关性采用概率近似',
  'zymos-child-external-source-context-defaults': '邪莫斯按普通玩家武器来源计算；未提供的外部角色临时加成不额外假定',
  "radial-arming-distance-assumed-armed": "未填写射击距离，当前假定投射物已满足爆炸解锁距离",
  "mutalist-cernos-swarm-first-update-versus-enter-phase-unmodeled": "异融西诺斯毒雾按进入与首次更新各结算一次伤害，实际帧内先后仍待核实",
  "mutalist-cernos-swarm-shared-weapon-replacement-ms-order-unverified": "异融西诺斯按同源最后一个有效毒雾计算；同帧多重的中间进入次数尚未校准",
  "mutalist-cernos-swarm-special-source-upgrades-unmodeled": "异融西诺斯毒雾已计算基础伤害与普通元素，其他特殊来源加成尚未核实",
  "mutalist-cernos-swarm-status-kill-arcane-dispatch-unverified": "异融西诺斯毒雾的异常及击杀类赋能通知路径尚未完整核实",
  "source-owned-field-upgrades-snapshot-at-embed": "持续场的加成按嵌入时快照计算，场存续期间变化的加成尚未动态读取",
  "source-owned-field-same-frame-enter-update-and-replacement-order-approximated": "持续场的进入、首次更新与替换采用固定顺序近似",
  "larkspur-contact-flight-and-scene-geometry-idealized": "翠雀蓄力弹按命中目标后立即爆炸计算，飞行与场景碰撞采用中心命中假设",
  "larkspur-maxlife1-launch-expiry-recipient-excluded-from-contact-model": "翠雀蓄力弹飞行超时的空中爆炸未另计目标覆盖",
  "larkspur-projectile-speed-mods-obstacles-and-out-of-range-contact-unmodeled": "翠雀蓄力弹的弹速、障碍物和超射程命中率尚未模拟",
  "larkspur-flight-time-dynamic-buff-snapshot-unverified": "翠雀蓄力弹飞行期间的动态加成快照时点尚未核实",
  "larkspur-main-explosion-CO-neutral-fallback-unverified": "翠雀蓄力爆炸的异况加成路径尚未核实，当前不计该加成",
  "larkspur-main-explosion-weakpoint-events-neutral-fallback-unverified": "翠雀蓄力爆炸的弱点事件资格仍待校准；普通命中与暴击通知已按原生路径计算",
  "mandonel-field-first-enter-update-frame-phase-approximated": "辐光弩炮伤害场的进入与首次更新折叠到命中时刻计算",
  "mandonel-on-hit-two-yield-coalescing-simultaneous-shots-unmodeled": "辐光弩炮同帧命中合并为一个场；跨帧合并边界尚未精确模拟",
  "mandonel-field-avatar-special-upgrades-and-event-routing-unverified": "辐光弩炮伤害场的特殊角色加成及赋能事件路径尚未核实",
  "finite-field-target-generation-bound-centered-coverage-approximated": "独立伤害场按原目标中心覆盖计算，不自动覆盖下一只目标",
  "grimoire-alt-select-coverage-strategy": "魔典副射击：选择范围策略以评估链伤害及到期爆炸；不计额外接触伤害",
  "grimoire-alt-original-target-eligible-window-assumed": "链伤害使用所选有效覆盖窗口，只作用于仍存活的原目标",
  "grimoire-alt-chain-first-update-at-launch-assumed": "覆盖策略从发射时的首次有效选择开始，每秒至多一次链伤害",
  "grimoire-alt-expiry-original-target-distance-assumed": "到期爆炸按所选原目标与爆心距离计算，不转移到其他敌人",
  "grimoire-alt-expiry-distance-not-selected": "未指定到期距离，不计魔典副射击的到期爆炸",
  "grimoire-alt-launch-expiry-recipient-position-unmodeled": "魔典副射击到期爆炸是否覆盖目标尚未模拟，当前未计该爆炸",
  "grimoire-alt-chain-target-reselection-and-recursive-geometry-unmodeled": "魔典副射击的周期链目标选择与弹道覆盖尚未模拟",
  "grimoire-alt-direct-contact-repeat-lifecycle-unverified": "魔典副射击重复接触同一目标的规则尚未完整核实",
  "grimoire-alt-single-orb-ms-to-chain-budget-routing-unmodeled": "魔典副射击保持一枚弹体；多重增加链目标预算的效果尚未计入",
  "grimoire-alt-chain-source-buffs-CO-and-events-unverified": "魔典副射击链伤害的动态加成、异况及事件路径尚未核实",
  "scourge-prime-active-spear-throw-recall-rethrow-cadence-unmodeled": "祸根 Prime 的投掷、回收与再次投掷时序尚未完整校准",
  "scourge-prime-stopped-embedded-script-payload-unmodeled": "祸根 Prime 停止与嵌入脚本伤害尚未完整计入",
  "scourge-prime-contact-geometry-and-source-snapshot-unverified": "祸根 Prime 接触位置与动态来源快照仍有近似",
  "scourge-prime-main55-CO-weakpoint-events-unverified": "祸根 Prime 的 55 主爆炸及相关触发资格仍待接入",
  "nox-player-embed-tick-and-death-clock-unmodeled": "Nox 玩家原型的嵌入周期伤害与死亡爆炸时序尚未建模",
  "nox-player-overlap-script-can-terminate-owner-unverified": "Nox 胶团的接触触发器可能提前终止弹体，当前尚未计入这条路径",
  "nox-player-source-and-event-routing-unverified": "Nox 玩家原型的伤害来源及事件资格尚未完整校准",
  "finite-field-two-yield-coalescing-and-enter-update-frame-phase-approximated": "独立伤害场的延迟创建、同帧命中合并及首次更新顺序采用近似",
  "scourge-prime-throw-reload-rethrow-input-policy-idealized": "祸根 Prime 按投掷、完成普通装填、再次投掷的操作策略计算",
  "scourge-prime-accepted-contact-flight-geometry-idealized": "祸根 Prime 按投掷命中目标中心计算，未模拟弹道偏离",
  "scourge-prime-main55-CO-weakpoint-events-neutral-fallback-unverified": "祸根 Prime 主爆炸已计入普通命中与暴击通知；异况和弱点事件资格仍待校准",
  "scourge-prime-pickup-recall-shortcuts-and-animation-interruption-unmodeled": "祸根 Prime 的拾取、召回捷径与动画取消尚未模拟",
  "scourge-prime-old-spear-deferred-die-and-embedded-damage-excluded": "祸根 Prime 旧枪矛延迟销毁及嵌入脚本的额外伤害暂未计入",
  "embedded-field-CO-and-hit-consumers-unverified": "持续场的异况加成及命中类赋能路径尚未完成原生校准，当前保留已有参考模型",
  "trumna-alt-bounce-and-expiry-recipients-unmodeled": "Trumna 副射击当前计算一次命中爆炸；后续弹跳与到期爆炸的实际覆盖尚未模拟",
  "sepulcrum-lock-target-emission-and-hit-selection-unmodeled": "Sepulcrum 副射击的锁定目标与发射数量、命中部位尚未完整建模，不将多目标预算视为单体必定多次命中",
  "cluster-contact-and-radial-qualification-body-approximation": "集束子弹的直击与范围包原生类型不同；当前采用单体身体命中近似，部分暴击修正和命中事件资格仍待校准",
  "tenet-plinx-static-magazine-policy-charge-entry-capacity-snapshot-unmodeled": "信条·普林克斯按固定配装弹匣计算；蓄力过程中临时弹匣增益变化尚未模拟",
  "tenet-plinx-cadence-player-wait-policy-not-native-max-rate": "信条·普林克斯按射击恢复后等待空电延迟与满充的保守策略计算，未声称最快循环",
  "tenet-plinx-flat-add-native-damage-provider-order-fail-closed": "信条·普林克斯的固定数值基础伤害加成乘区尚未核实，含此类效果的配置暂停评分",
  "tenet-plinx-ideal-accepted-embed-contact-geometry": "信条·普林克斯按弹体命中并嵌入目标中心计算",
  "tenet-plinx-unembedded500-alternative-excluded": "信条·普林克斯当前采用嵌入爆炸，不叠加互斥的空中死亡爆炸",
  "tenet-plinx-CO-weakpoint-arcane-event-qualification-unverified": "信条·普林克斯的部分异况、弱点与赋能事件资格仍待校准",
  "arbucep-projectile-contact-and-radial-centre-coverage-idealized": "Arbucep 当前假定各弹体直击和爆炸中心均命中单体目标",
  "arbucep-packet-condition-overload-neutral-pending-routing": "Arbucep 各弹体的异况加成路径尚未核实，当前不计该加成",
  "arbucep-packet-weakpoint-events-neutral-pending-routing": "Arbucep 各弹体的弱点加成和事件路径尚未核实，当前按普通命中计算",
  "arbucep-innate-mushroom-and-ammo-deco-script-unmodeled": "Arbucep 菌菇及弹药装饰脚本效果尚未计入",
  "projectile-lanes-fractional-count-16-stratified-trajectories-approximation": "小数多重按 16 条离散弹体序列轨迹近似，保留每颗弹体的元素顺序",
  "battacor-radial-condition-overload-routing-unverified": "武使之力副射击范围伤害的异况加成路径尚未核实，当前不计该加成",
  "battacor-radial-per-trigger-multiplicity-unverified": "武使之力多重射线产生多少次范围包尚未核实，当前按每次副射击一个范围包计算",
  "battacor-radial-hit-arcane-dispatch-unverified": "武使之力范围包的命中类赋能触发路径尚未核实",
  "battacor-first-charge-dynamic-buff-snapshot-timing-unverified": "武使之力蓄力期间变化的临时加成按完成时读取，原生快照时点仍待核实",
  "battacor-primary-dot-charge-during-alt-windup-unmodeled": "武使之力蓄力期间，先前主射击持续伤害击杀额外补充蓄能的情况尚未计入",
  "zymos-child-spawn-and-targeting-unmodeled": "邪莫斯孢子子弹体的创建条件与目标选择尚未完整建模",
  "zymos-child-damage-inheritance-and-event-routing-unverified": "邪莫斯子弹体的伤害继承和状态／击杀触发路径尚未核实",
  "phantasma-main-explosion-CO-neutral-fallback-unverified": "幻离子主爆炸已计入；其异况加成路径尚未核实，当前不计该加成",
  "phantasma-main-explosion-weakpoint-events-neutral-fallback-unverified": "幻离子主爆炸不计普通头部增伤，额外弱点暴击与弱点击杀资格尚未核实",
  "phantasma-nonstandard-ability-parent-source-crit-routing-unverified": "幻离子主爆炸已按普通武器来源计入穿刺与冰冻暴击修正；能力或特殊来源的情况仍待核实",
  "phantasma-cluster-child-payload-unmodeled": "幻离子分裂子弹体的伤害和命中次数仍未计入",
  "phantasma-charge-ammo-scale-and-contact-routing-approximated": "幻离子副射击的蓄力耗弹与伤害缩放仍采用当前近似路径",
  "efv8-main-explosion-CO-neutral-fallback-unverified": "艾弗旺-8 火星的副射击爆炸已计入；异况加成路径尚未核实，当前不计该加成",
  "efv8-release-flight-and-recipient-coverage-idealized": "艾弗旺-8 火星副射击假定爆炸中心命中目标，忽略真实飞行和覆盖损失",
  "acceltra-arming-distance-default-assumed-armed": "迅发电浆炮未填写距离时假定已飞行6米解锁爆炸；小于6米仅计算接触伤害",
  "acceltra-main-explosion-CO-neutral-fallback-unverified": "迅发电浆炮主爆炸的异况加成路径尚未核实，当前不计该加成",
  "acceltra-main-explosion-weakpoint-events-neutral-fallback-unverified": "迅发电浆炮主爆炸按普通范围包处理，不额外授予弱点事件资格",
  "acceltra-contact-death-timing-and-target-centre-coverage-idealized": "迅发电浆炮假定已武装投射物在目标中心死亡爆炸，真实碰撞时序与覆盖损失尚未模拟",
  "acceltra-embedded-alternative-payload-excluded": "迅发电浆炮继承的另一条嵌入死亡伤害不属于普通弹体路径，未重复计入",
  "alternox-host-death-lifecycle-unverified": "电幻步枪的附着目标死亡后，电场和末次爆炸是否保留尚未核实；当前按该目标死亡后停止计算",
  "alternox-multishot-active-cap-unresolved": "电幻步枪同时存在多个电球的替换规则尚未核实；超过单球上限时暂按一颗计算，可能低估伤害",
  "alternox-instant-detonation-order-idealized": "电幻步枪零等待引爆按直击、首跳电场、爆炸的顺序计算",
  "alternox-same-time-expiry-order-fixed-explosion-first": "电幻步枪到期与电场跳伤同一时刻时，当前先结算爆炸，不再追加该跳电场伤害",
  "cryotra-field-host-death-and-spatial-persistence-unverified": "急冻喷枪的目标死亡后冷场是否保留尚未核实；当前只计算目标存活期间的冷场",
  "cryotra-field-overlap-unverified": "急冻喷枪多个冷场的重叠规则尚未核实；当前按每颗命中投射物独立叠加",
  "cryotra-field-condition-overload-unverified": "急冻喷枪冷场是否受到异况增伤尚未核实，当前冷场不计该加成",
  "cryotra-embed-expiry-boundary-order-unverified": "急冻喷枪冷场按附着后0至4秒共5跳计算，5秒到期同刻的处理尚未核实",
  "companion-projectile-damage-sequence-unmodeled": "解构者的冲击、穿刺、切割三种投射物序列尚未完整建模，当前伤害与触发类型可能有偏差",
  "sentinel-fired-up-expiry-resume-unverified": "过热射击按命中逐层增加，5秒无命中后清空；过期后再命中的层数恢复规则仍待核实",
  "sentinel-fired-up-panel-shows-cap; replay-starts-empty-and-resets-after-no-hit-duration": "过热射击面板显示上限，战斗回放从零层开始，按实际命中逐层增加",
  "cortege-firefield-mod-routing-unverified": "Cortege按5次主射击击杀蓄能，并计入副射击爆炸；残留火场的MOD伤害传递仍待核实，暂未计入",
  "cortege-firefield-spatial-overlap-unverified": "Cortege多个火场的空间重叠和目标覆盖尚未验证",
  "cortege-firefield-clock-boundary-unverified": "Cortege火场按目标冷却触发，首次接触和到期同帧顺序仍待核实",
  "companion-projectile-bounce-return-timing-unverified": "分离弹体已按冲击、穿刺、切割轮换；弹跳、回收和再次发射的实际时序仍待核实",
  "companion-active-projectile-refire-limit-unmodeled": "分离最多同时在场3枚弹体；回收与再次发射的占用限制尚未完整建模",
  "companion-projectile-sequence-multishot-unmodeled": "弹体序列当前仅支持每次发射1枚；额外多重会影响后续轮换顺序，结果为近似",
  "melee-initial-combo-recovery-rate-unverified": "当前武器缺少可核实的初始连击恢复速度，暂不计消耗后的恢复量",
  "melee-combo-recovery-event-integration-and-impact-consumption": "初始连击按游戏数据随时间恢复，按重击命中时读取和消耗；未逐帧模拟输入与回调顺序",
  "angstrum-full-charge-ideal-projectile-coverage": "安格斯壮普通模式按满弹匣蓄力齐射，弹数、逐弹伤害和扣弹均随装填量变化；假定所有火箭与爆炸中心命中单目标",
  "angstrum-charge-release-and-flight-timing-unverified": "安格斯壮采用完整蓄力；提前松手、飞行时间与实际散布覆盖仍待验证",
  "angstrum-charge-completion-buff-snapshot-boundary-unverified": "安格斯壮的临时增益按蓄力完成时读取；同帧快照边界仍待验证",
  "angstrum-ammo-efficiency-integer-accounting-unverified": "安格斯壮启用弹药效率时采用期望耗弹；真实整数扣弹和不足一发的蓄力行为尚待核实",
  "continuous-slam-user-cadence-0.2s-minimum-height-no-recovery": "连续震地按0.2秒一次、最低高度和取消后摇计算；实际频率取决于操作",
  "mausolon-radial-multishot-routing-unverified": "葬铭的多重射击如何产生范围伤害事件仍有待核实；当前沿用每个弹头的范围伤害模型",
  'quanta-player-shot-detonation-unmodeled': '量子切割器副模式按立方体碰撞引爆；另外射击立方体的强化引爆尚未计入',
  'quanta-idle-detonation-unmodeled': '未碰撞立方体的 9 秒自然引爆未计入当前单目标接触模型',
  'quanta-standoff-cube-and-chain-overlap-assumed': '强化引爆假设立方体先避开敌人碰撞，敌人和同批立方体均处于有效爆炸覆盖内',
  'quanta-paid-primary-one-pulse-hit-assumed': '另计一次主射击的弹药与完整光束周期，假定这一脉冲命中立方体；光束本身不额外伤害敌人',
  'quanta-shot-native-delay-approximated-by-mean': '立方体被射击后的原生引爆延迟为 0.075–0.15 秒，当前采用均值 0.1125 秒',
  'quanta-cube-chain-unmodeled': '立方体之间的连锁引爆与射击转换尚未计入',

  'spread-hit-loss-not-modeled': '散布暂不参与命中、伤害及评分计算',
  'hema-player-health-cost-not-modeled': '血肢换弹消耗角色生命；当前仅计算输出，未模拟角色生命资源',
  'talons-single-throw-deployment-overflow-unmodeled': '单次投掷超过 8 枚部署上限，超出部分暂不计伤',
  'stug-projectile-stack-lifecycle-unmodeled': '史特克当前按孤立胶团结算；后续胶团命中旧胶团后的合并和叠层引爆尚未计入',
  'stug-embed-ticks-unmodeled': '史特克嵌入期间的小额伤害跳数尚未核实，当前只计 1.5 秒后的爆炸',
  'stug-bouncing-child-contact-unmodeled': '史特克灵化胶团引爆后的子弹弹跳、碰撞和最终爆炸尚未计入',
  'stug-full-charge-stack-unmodeled': '史特克蓄满副射击形成初始堆层的规则尚未计入',
  'talons-multishot-spatial-hit-loss-unmodeled': '鹰爪多重投掷的分散落点与范围命中损失尚未计入',
  'talons-natural-status-reference-calibrated': '鹰爪自然触发率原生字段缺失，暂用固定参考版本的 10%',

  "kitgun-radial-damage-unapplied": "组合枪爆炸范围伤害部分未计入单目标计算",
  "kitgun-chain-damage-unapplied": "组合枪光束的链式伤害未计入",
  "kitgun-cluster-damage-unapplied": "组合枪孢子分裂弹的二次伤害未计入",
  "loadout-over-capacity": "配装超出容量上限",
  "enemy-base-level-unverified": "该敌人的基准等级没有官方记录，等级缩放可能有偏差",
  "ultra-profile-baseline-approximate": "超快档：基准配装是近似结果，增益仅供参考",
  "ultra-profile-contributions-center-node": "超快档：词条贡献只按中间血量节点计算",
  "ultra-profile-negative-ranking-not-cached": "超快档：没有计算负面词条排名",
  "ultra-profile-recommendation-not-cached": "超快档：没有计算推荐词条",
};

// 多部件武器数据缺口（weapon-radial-or-field-damage-not-in-export-<part>）：
// Rabbit 2D 导出不含这些武器的爆炸/残留场数据，最终伤害缺该部分（排序可用，绝对值偏低）。
function multipartDiagnosticLabel(code) {
  const match = String(code).match(/^weapon-radial-or-field-damage-not-in-export-(radial|field)$/);
  if (!match) return null;
  return match[1] === "radial"
    ? "该武器的爆炸伤害部分暂缺数据，最终伤害偏低（配装排序仍有效）"
    : "该武器的残留场伤害部分暂缺数据，最终伤害偏低（配装排序仍有效）";
}

// 灵化分支诊断码（incarnon-<分支id>-<原因>）翻译成人话，原因口径与后端注明一致。
const INCARNON_DIAGNOSTIC_REASONS = {
  "runtime-scripts-not-applied": "含游戏内动态脚本效果（形态/叠层联动），该部分不参与解算",
  "conditional-effects-not-applied": "含未激活的条件效果，该部分不参与解算",
  "unresolved-references": "含未解析的数据引用",
  "NONE-not-evaluated": "部分词条没有可计算的数值，不参与计算",
};

function incarnonDiagnosticLabel(code) {
  const match = String(code).match(/^incarnon-([a-z0-9-]+?)-(runtime-scripts-not-applied|conditional-effects-not-applied|unresolved-references|NONE-not-evaluated)$/);
  if (!match) return null;
  const reason = INCARNON_DIAGNOSTIC_REASONS[match[2]];
  return reason ? `灵化分支 ${match[1]}：${reason}` : null;
}

// 诊断面板只给用户看与结果有关的说明：搜索参数、内部路径、英文实现备注
// 这类只对开发有意义的条目不展示；已知代码与路径翻译成中文。
const HIDDEN_DIAGNOSTIC = /^optimizer-(assumption|objective|profile|search|trigger-policy):/;

function itemNameByPath(path) {
  const pools = [state.catalog?.manualMods, state.catalog?.manualModVariants, state.catalog?.arcanes, state.catalog?.utilityMods, state.catalog?.stances];
  for (const pool of pools) {
    const row = Array.isArray(pool) ? pool.find((entry) => entry?.path === path) : null;
    if (row) return row.nameZh || row.nameEn || path.split("/").pop();
  }
  return path.split("/").pop();
}

function userDiagnostic(line) {
  let text = String(line || "").trim();
  if (!text || HIDDEN_DIAGNOSTIC.test(text)) return null;
  text = text.replace(/^optimizer-(auto-incarnon|auto-arcane|scope|arcanes|stance):\s*/, "");
  const item = text.match(/^(\/Lotus\/\S+):\s*(.+)$/);
  if (item && !/[一-鿿]/.test(item[2])) {
    return `${itemNameByPath(item[1])}：${/PM_HEAVY_MELEE/.test(item[2]) ? "只对重击生效，不计入当前攻击" : "部分效果暂未计入"}`;
  }
  if (/^[A-Z][A-Z0-9_]+$/.test(text)) return MOD_EFFECT_LABELS[text] ? `${MOD_EFFECT_LABELS[text]}（暂未计入）` : null;
  if (!/[一-鿿]/.test(text)) return null;
  return text;
}

function userDiagnostics(value) {
  return normalizeLabels(value).map(userDiagnostic).filter(Boolean);
}

function normalizeLabels(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.flatMap(normalizeLabels);
  if (typeof value === "string") return [DIAGNOSTIC_CODE_LABELS[value] || incarnonDiagnosticLabel(value) || multipartDiagnosticLabel(value) || value];
  if (typeof value === "object") return [value.label || value.nameZh || value.nameEn || DIAGNOSTIC_CODE_LABELS[value.code] || incarnonDiagnosticLabel(value.code) || multipartDiagnosticLabel(value.code) || value.code].filter(Boolean);
  return [String(value)];
}

function renderTiers() {
  const routes = state.result?.recommendedRoutes;
  const route = routes?.[state.recRoute];
  const routeTiers = Array.isArray(route?.tiers) ? route.tiers : null;
  const tiers = routeTiers
    ?? (Array.isArray(state.result?.recommendedPositiveTiers) ? state.result.recommendedPositiveTiers : []);
  // 双路数据存在时显示切换器；否则（近战/投掷重击口径）保持单列表
  const hasRoutes = Boolean(routes && routes.status && routes.direct);
  if (ui["tier-filters"]) ui["tier-filters"].hidden = !hasRoutes;
  const group = ui["tier-route"];
  if (group) {
    for (const button of group.querySelectorAll("button")) {
      const active = button.dataset.route === state.recRoute;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    }
  }
  // 路线比较注记：两条路线都是「预留紫卡位」的最佳配装分数，直接可比。
  const note = ui["tier-route-note"];
  if (note) {
    if (hasRoutes && finite(routes.status.score) !== null && finite(routes.direct.score) !== null) {
      const statusScore = Number(routes.status.score);
      const directScore = Number(routes.direct.score);
      const better = statusScore >= directScore ? "触发" : "直伤";
      note.textContent = `含紫卡最佳配装：触发 ${formatMetric(statusScore)} / 直伤 ${formatMetric(directScore)} · 当前${better}路线伤害更高`;
      note.hidden = false;
    } else {
      note.hidden = true;
    }
  }
  const rows = tiers.map((tier) => {
    const row = create("article", "tier-row");
    row.dataset.tier = tier.tier;
    const badge = create("div", "tier-badge", tier.tier);
    const stats = create("div", "tier-stats");
    for (const stat of (tier.stats || []).slice(0, 3)) {
      const chip = create("span");
      chip.append(create("strong", "", stat.label || stat.code), create("small", "", `+${(finite(stat.gain) ?? 0).toFixed(1)}%`));
      stats.append(chip);
    }
    row.append(badge, stats);
    return row;
  });
  ui["tier-list"].replaceChildren(...(rows.length ? rows : [create("p", "empty-copy", "当前武器没有正收益推荐词条")]))
  const recommended = normalizeLabels(state.result.recommendedNegative);
  const fatal = normalizeLabels(state.result.fatalNegative);
  ui["recommended-negative"].textContent = recommended.join(" / ") || "无";
  // 武器级致命负面：负面词条按理论数值放进推荐正面的紫卡，配装围绕它重搜后
  // 仍亏损超过 35% 才算致命。提交的紫卡负面在其中时单独点明。
  const own = normalizeLabels(state.result.submittedFatalNegative);
  // 随数值变化的致命负（如 3+1 触发时间跨过 −100%）：负值不超过阈值时不致命。
  const above = state.result.fatalNegativeAbove || {};
  const fatalText = fatal.map((label) => {
    const limit = finite(above[label]);
    if (limit === null) return label;
    return `${label}（负值超过 ${limit.toFixed(1)}% 时致命，不超过时${recommended.includes(label) ? "为推荐负" : "不致命"}）`;
  });
  ui["fatal-negative"].textContent = (fatalText.join(" / ") || "无") + (own.length ? `（当前紫卡的负面 ${own.join(" / ")} 属于致命负面）` : "");
  ui["fatal-box"].classList.toggle("is-clear", !fatal.length);
  ui["fatal-box"].title = "负面词条按理论数值评估：配装可以围绕负面重新搭配，重搜后仍亏损超过 35% 的才算致命";
}

function formatMetric(value) {
  const number = finite(value);
  if (number === null) return "--";
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 2 }).format(number);
}

function buildMetrics(build, weapon = state.weapon) {
  // KPM 是解算的真实目标，永远排第一（后端 objectiveScore 字段；
  // 旧响应无此字段时自动回落到既有指标）。
  const preferred = ["melee", "zaw"].includes(weapon?.weaponType)
    ? ["objectiveScore", "attackDps", "heavyDamage", "heavyAttackDps", "shotDamage"]
    : ["objectiveScore", "shotDamage", "burstDps", "sustainedDps"];
  return preferred.filter((key) => finite(build?.[key]) !== null).slice(0, 5);
}

// The optimization value and quality-score value can use different units.
function metricLabel(key, build = null) {
  if (key !== "objectiveScore") return METRIC_LABELS[key];
  const metric = build?.objectiveMetric || state.result?.metric || state.result?.searchQuality?.objectiveMetric || "killsPerMinute";
  return ({ killsPerMinute: "标准靶 KPM", windowedDps: "标准靶 DPS", heavyDamage: "标准靶重击伤害" })[metric] || METRIC_LABELS[metric] || metric;
}

function renderMetrics(build, target = ui["damage-metrics"], weapon = state.weapon) {
  const previousValues = new Map([...target.querySelectorAll(".damage-metric")].map((card) => {
    const label = card.querySelector("span")?.textContent;
    return [label, card.dataset.liveValue ?? null];
  }));
  const nodes = buildMetrics(build, weapon).map((key) => {
    const card = create("article", "damage-metric");
    card.title = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(build[key]);
    const text = formatMetric(build[key]);
    card.dataset.liveValue = text;
    const label = metricLabel(key, build);
    const value = create("strong", "", text);
    if (previousValues.has(label) && previousValues.get(label) !== text) value.classList.add("is-flash");
    card.append(create("span", "", label), value);
    return card;
  });
  target.replaceChildren(...nodes);
}

function renderFireModes(build, target = ui["fire-mode-strip"], options = {}) {
  const modes = Array.isArray(build?.alternateModes) ? build.alternateModes : [];
  const note = target === ui["fire-mode-strip"] ? ui["fire-mode-strip-note"] : null;
  if (!modes.length) {
    target.hidden = true;
    target.replaceChildren();
    if (note) note.hidden = true;
    return;
  }
  // 分析结果页的备选模式可点击：点击后以该模式重新解算（当前解算模式见卡头）。
  const interactive = options.interactive === true;
  const nodes = modes.map((mode, index) => {
    const modeIndex = finite(mode.fireMode) !== null ? Number(mode.fireMode) : null;
    const selectable = interactive && modeIndex !== null && mode.available !== false;
    const item = create(selectable ? "button" : "div", `fire-mode-item${mode.available === false ? " is-unavailable" : ""}${selectable ? " is-selectable" : ""}`);
    if (selectable) {
      item.type = "button";
      item.dataset.fireMode = String(modeIndex);
      item.title = "按此射击模式重新解算";
    }
    const name = modeIndex !== null ? `模式 ${modeIndex + 1}${mode.isIncarnonForm ? " · 灵化形态" : ""}` : (mode.name || mode.id || `副模式 ${index + 1}`);
    const metrics = mode.metrics || mode;
    const metricKey = METRIC_KEYS.find((key) => finite(metrics[key]) !== null);
    const detail = mode.available === false ? (mode.issue || "不可用") : (metricKey ? `${METRIC_LABELS[metricKey]} ${formatMetric(metrics[metricKey])}` : "已解算");
    item.append(create("span", "", `${name} · ${triggerLabel(mode.trigger, modeIndex ?? index)}`), create("strong", "", detail));
    return item;
  });
  target.replaceChildren(...nodes);
  target.hidden = false;
  if (note) note.hidden = !interactive;
}

function polarityNode(polarity, className, loading = "lazy") {
  const source = POLARITY_IMAGES[polarity];
  if (source) return imageNode(source, className, `${polarity} 极性`, loading);
  const node = create("span", `${className} polarity-glyph`, "");
  if (polarity) node.setAttribute("aria-label", `${POLARITY_NAMES?.[polarity] || polarity} 极性素材缺失`);
  return node;
}

function rankPips(rank, maxRank, frames = {}, loading = "lazy") {
  const wrap = create("div", "mod-rank-pips");
  wrap.dataset.rank = String(Math.max(0, Math.floor(Number(rank) || 0)));
  const total = Math.max(1, Math.min(10, Math.floor(Number(maxRank) || Number(rank) || 1)));
  const active = Math.max(0, Math.min(total, Math.floor(Number(rank) || 0)));
  const assetBacked = Boolean(frames.rankActive && frames.rankEmpty);
  if (assetBacked) {
    wrap.classList.add("is-asset-backed");
    if (frames.rankComplete) wrap.style.setProperty("--rank-complete", `url("${frames.rankComplete}")`);
  }
  for (let index = 0; index < total; index += 1) {
    if (assetBacked) wrap.append(imageNode(index < active ? frames.rankActive : frames.rankEmpty, `mod-rank-pip${index < active ? " is-active" : ""}`, "", loading));
    else wrap.append(create("i", index < active ? "is-active" : "", "★"));
  }
  if (active >= total) wrap.classList.add("is-max");
  return wrap;
}

// 立绘伪 3D 分层路径推导：仅 mods/stances art 目录下的 PNG 有拆分素材
// （split_mod_art.py 生成 X.bg.jpg / X.fg.png）；其余来源（图标等）返回 null。
function splitArtLayers(artSource) {
  if (!artSource || !/^\/assets\/(mods|stances)\/art\/.+\.png$/i.test(artSource)) return null;
  return { bg: artSource.replace(/\.png$/i, ".bg.jpg"), fg: artSource.replace(/\.png$/i, ".fg.png") };
}

// —— 紫卡卡面 ——
// 卡名：正面词条按随机系数（数值 ÷ 该词条基础值，倾向与正负结构对同卡词条相同）
// 从高到低排序（分不出高低时按卡上顺序），最高为前缀、次高为核心、最低为后缀（3 正 “Prefix-coresuffix”，
// 2 正 “Coresuffix”）；音节取自紫卡模板 UpgradeEntries 的 Prefix/SuffixTag，
// 融合词条也有音节（09-22 模板），同样参与命名（wiki Riven Mods#Naming）。
function rivenCardName(weapon, stats, definitions) {
  const byCode = new Map((definitions || []).map((definition) => [String(definition.code), definition]));
  const ranked = (stats || [])
    .filter((stat) => !stat.negative)
    .map((stat) => ({ definition: byCode.get(String(stat.code)), value: Number(stat.value) }))
    .filter(({ definition, value }) => definition?.namePrefix && definition?.nameSuffix && Number(definition.baseValue) > 0 && value > 0)
    .map((entry) => ({ ...entry, base: Number(entry.definition.baseValue), roll: entry.value / Number(entry.definition.baseValue) }))
    // 数值只有 1 位小数精度：系数差在这个误差内（满 roll 的两条常见）分不出高低，
    // 按卡上的词条顺序排（stable sort 保持原序）。
    .sort((a, b) => (Math.abs(a.roll - b.roll) <= 0.05 / a.base + 0.05 / b.base ? 0 : b.roll - a.roll));
  const capital = (text) => text.charAt(0).toUpperCase() + text.slice(1);
  let suffix = "";
  if (ranked.length >= 3) {
    suffix = `${capital(ranked[0].definition.namePrefix)}-${ranked[1].definition.namePrefix}${ranked[ranked.length - 1].definition.nameSuffix}`;
  } else if (ranked.length === 2) {
    suffix = `${capital(ranked[0].definition.namePrefix)}${ranked[1].definition.nameSuffix}`;
  } else if (ranked.length === 1) {
    suffix = `${capital(ranked[0].definition.namePrefix)}${ranked[0].definition.nameSuffix}`;
  }
  return `${rivenWeaponDisplayName(weapon)} ${suffix}`.trim();
}

// 卡图：游戏内紫卡图标用 OmegaIconProcedural 材质（IconProcedural + IMAGE_BLEND），
// 在卡上每个词条（含负面）对应 MOD 的卡图之间轮切，过渡按灰度遮罩
// /Lotus/Interface/Graphics/OmegaModTransition.png 的阈值逐块溶解（BlendPoint）。
// 停留与过渡时长在原生 UI 代码里、数据包中没有，按游戏内观感取值。
const RIVEN_FACE_HOLD_MS = 3000;
const RIVEN_FACE_FADE_MS = 900;
const RIVEN_FACE_EDGE = 0.08;
const RIVEN_FACE_SIZE = 256;
let rivenFaceMask = null;
const rivenFaceImages = new Map();

function rivenFaceArts(stats, definitions) {
  const byCode = new Map((definitions || []).map((definition) => [String(definition.code), definition]));
  const arts = [];
  for (const stat of stats || []) {
    const art = byCode.get(String(stat.code))?.art;
    if (art && !arts.includes(art)) arts.push(art);
  }
  return arts;
}

function rivenFacePixels(src) {
  if (!rivenFaceImages.has(src)) {
    rivenFaceImages.set(src, new Promise((resolve) => {
      const image = new Image();
      image.decoding = "async";
      image.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = RIVEN_FACE_SIZE;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        context.drawImage(image, 0, 0, RIVEN_FACE_SIZE, RIVEN_FACE_SIZE);
        resolve(context.getImageData(0, 0, RIVEN_FACE_SIZE, RIVEN_FACE_SIZE).data);
      };
      image.onerror = () => resolve(null);
      image.src = src;
    }));
  }
  return rivenFaceImages.get(src);
}

async function loadRivenFaceMask() {
  if (!rivenFaceMask) {
    rivenFaceMask = rivenFacePixels("/assets/riven/omega-transition.png").then((data) => {
      if (!data) return null;
      const mask = new Float32Array(RIVEN_FACE_SIZE * RIVEN_FACE_SIZE);
      for (let i = 0; i < mask.length; i += 1) mask[i] = data[i * 4] / 255;
      return mask;
    });
  }
  return rivenFaceMask;
}

// 返回两张 canvas（mod-art-bg 背景层 / mod-art-fg 主体抠图层，沿用普通卡的
// 伪 3D 视差与 hover 样式）；卡片离开文档后动画自动停止。
function rivenFaceCanvases(arts, bgClass = "mod-art mod-art-bg", fgClass = "mod-art-fg") {
  const make = (className) => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = RIVEN_FACE_SIZE;
    canvas.className = className;
    return canvas;
  };
  const bg = make(bgClass);
  const fg = make(fgClass);
  if (arts.length) animateRivenFace([bg, fg], arts);
  return [bg, fg];
}

async function animateRivenFace(canvases, arts) {
  const layers = await Promise.all(arts.map((art) => {
    const split = splitArtLayers(art);
    return Promise.all([rivenFacePixels(split?.bg || art), rivenFacePixels(split?.fg || art)]);
  }));
  const faces = layers.filter(([bg, fg]) => bg && fg);
  if (!faces.length) return;
  const contexts = canvases.map((canvas) => canvas.getContext("2d"));
  const frames = contexts.map((context) => context.createImageData(RIVEN_FACE_SIZE, RIVEN_FACE_SIZE));
  const draw = (from, to, t, mask) => {
    const threshold = t * (1 + 2 * RIVEN_FACE_EDGE) - RIVEN_FACE_EDGE;
    for (let layer = 0; layer < 2; layer += 1) {
      const a = faces[from][layer];
      const b = faces[to][layer];
      const out = frames[layer].data;
      if (!mask || t <= 0 || t >= 1) out.set(t >= 1 ? b : a);
      else {
        for (let i = 0, p = 0; i < mask.length; i += 1, p += 4) {
          const w = Math.min(1, Math.max(0, (threshold - mask[i]) / RIVEN_FACE_EDGE + 0.5));
          out[p] = a[p] + (b[p] - a[p]) * w;
          out[p + 1] = a[p + 1] + (b[p + 1] - a[p + 1]) * w;
          out[p + 2] = a[p + 2] + (b[p + 2] - a[p + 2]) * w;
          out[p + 3] = a[p + 3] + (b[p + 3] - a[p + 3]) * w;
        }
      }
      contexts[layer].putImageData(frames[layer], 0, 0);
    }
  };
  draw(0, 0, 0, null);
  if (faces.length < 2) return;
  const mask = await loadRivenFaceMask();
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches || !mask;
  let current = 0;
  const next = () => {
    if (!canvases[0].isConnected) return;
    const target = (current + 1) % faces.length;
    if (still || document.hidden) {
      draw(target, target, 1, null);
      current = target;
      setTimeout(next, RIVEN_FACE_HOLD_MS);
      return;
    }
    const started = performance.now();
    const step = (now) => {
      if (!canvases[0].isConnected) return;
      const t = Math.min(1, (now - started) / RIVEN_FACE_FADE_MS);
      draw(current, target, t, mask);
      if (t < 1) requestAnimationFrame(step);
      else {
        current = target;
        setTimeout(next, RIVEN_FACE_HOLD_MS);
      }
    };
    requestAnimationFrame(step);
  };
  setTimeout(next, RIVEN_FACE_HOLD_MS);
}

// 紫卡卡片内容层：与 modContentLayers 同结构（背景、立绘窗、高光），立绘换成轮切卡面。
function rivenContentLayers(frames, arts, loading = "eager") {
  const nodes = [];
  if (frames.background) nodes.push(imageNode(frames.background, "mod-background", "", loading));
  const artWindow = create("div", "mod-art-window");
  if (arts.length) artWindow.append(...rivenFaceCanvases(arts));
  else if (frames.art) artWindow.append(imageNode(frames.art, "mod-art", "紫卡", loading));
  artWindow.append(create("span", "mod-art-shade"));
  nodes.push(artWindow, create("span", "mod-glare"));
  return nodes;
}

// 内容层：进入 .mod-content（被裁剪）：背景、立绘窗（非 compact 卡挂伪 3D 双层+高光）
function modContentLayers(frames, metadata, mod, artClass = "mod-art", loading = "lazy", splitArt = false) {
  const nodes = [];
  if (frames.background) nodes.push(imageNode(frames.background, "mod-background", "", loading));
  const artSource = metadata?.art || mod?.art || mod?.iconAsset || frames.art;
  const layers = splitArtLayers(artSource);
  const split = splitArt ? layers : null;
  const artWindow = create("div", "mod-art-window");
  if (artSource) {
    const bg = imageNode(layers?.bg || artSource, split ? `${artClass} mod-art-bg` : artClass, metadata?.nameZh || mod?.nameZh || "MOD 素材", loading);
    if (layers) {
      // 拆分素材缺失时回退原始整图：只损失分层视差，不影响卡面显示
      bg.addEventListener("error", () => {
        delete bg.dataset.assetError;
        bg.classList.remove("mod-art-bg");
        bg.src = artSource;
        bg.addEventListener("error", () => { bg.dataset.assetError = "true"; }, { once: true });
      }, { once: true });
    }
    artWindow.append(bg);
    if (split) artWindow.append(imageNode(split.fg, "mod-art-fg", "", loading));
  } else artWindow.append(create("div", "mod-art-missing", "素材缺失"));
  artWindow.append(create("span", "mod-art-shade"));
  nodes.push(artWindow);
  if (split) nodes.push(create("span", "mod-glare"));
  return nodes;
}

// 框体层：作为 .game-mod-card 的直接子节点盖在内容之上（z-index 10）
function modFrameLayers(frames, loading = "lazy") {
  const nodes = [];
  if (frames.frameTop) nodes.push(imageNode(frames.frameTop, "mod-frame-top", "", loading));
  if (frames.frameBottom) nodes.push(imageNode(frames.frameBottom, "mod-frame-bottom", "", loading));
  if (frames.sideLight) {
    const side = create("div", "mod-side-lights");
    side.append(imageNode(frames.sideLight, "mod-side-light mod-side-light-left", "", loading));
    side.append(imageNode(frames.sideLightRight || frames.sideLight, "mod-side-light mod-side-light-right", "", loading));
    nodes.push(side);
  }
  return nodes;
}

// 整卡伪 3D 倾斜的承载层（卡框自身 transform 被展开/收起动画占用，倾斜包一层）
function modTiltWrap(frame) {
  const tilt = create("div", "mod-tilt");
  tilt.append(frame);
  return tilt;
}

function modCostBadge(drain, polarity, loading = "lazy", colorClass = "", relation = "") {
  const badge = create("div", "mod-cost");
  const drainBox = create("div", `mod-drain${colorClass}${relation ? ` is-${relation}` : ""}`);
  drainBox.append(create("b", "", String(drain)));
  if (polarity) drainBox.append(polarityNode(polarity, "mod-polarity", loading));
  badge.append(drainBox);
  return badge;
}

function renderEffectLines(mod, details = false) {
  const lines = modEffectLines({ ...mod, rank: mod.rank ?? mod.maxRank ?? 0 });
  const frag = document.createDocumentFragment();
  // Folded cards stay compact; expanded previews keep every official line.
  const max = details ? lines.length : 4;
  const shown = lines.slice(0, max);
  shown.forEach((line) => {
    const p = create("p", "mod-effect-line");
    const value = line.value === undefined ? "" : `${line.value >= 0 ? "+" : ""}${(line.value * 100).toFixed(1)}%`;
    // In-game / Overframe order: percentage first, then the element icon, then
    // the label text (e.g. "+90% ❄ 冰冻伤害").
    const fullText = cleanOfficialText(line.value === undefined ? String(line.label) : `${value} ${line.label}`);
    if (!fullText) return;
    const lead = fullText.match(/^\s*([+-]?\d+(?:\.\d+)?%)\s*/);
    const iconEl = line.icon ? imageNode(line.icon, "mod-effect-icon", "", "lazy") : null;
    // 标记不在数值后面时（"…暴击时造成 <DT_SLASH_COLOR>"）图标跟着元素名走。
    const named = iconEl && line.iconName ? fullText.indexOf(line.iconName) : -1;
    if (named > 0 && !(lead && named === lead[0].length)) {
      p.classList.add("is-inline");
      p.append(document.createTextNode(fullText.slice(0, named)), iconEl, document.createTextNode(fullText.slice(named)));
    } else if (iconEl && lead) {
      p.append(document.createTextNode(`${lead[1]} `), iconEl);
      const rest = fullText.slice(lead[0].length).trim();
      if (rest) p.append(document.createTextNode(rest));
    } else {
      if (iconEl) p.append(iconEl);
      p.append(document.createTextNode(fullText));
    }
    frag.append(p);
  });
  if (lines.length > max) {
    const more = create("p", "mod-effect-line is-more", `…另有 ${lines.length - max} 条效果`);
    frag.append(more);
  }
  // Folded cards are intentionally quiet: never leak conditional/internal
  // diagnostics into the game-style card.  The expanded picker preview asks
  // for details and receives the complete official set text there.
  const setId = String(mod?.modSet || "");
  const setName = String(mod?.setName || modAssetFields(mod)?.setName || setId).trim();
  // 套装标签行已移除（用户反馈卡面不需要"套装：xx"标签，保留详细加成说明即可）
  if (details) {
    const officialDescription = cleanOfficialText(mod.description || modAssetFields(mod)?.description || "");
    // The catalog may join the same official lines with semicolons. Compare
    // complete text segments across all rendered lines, not one line against
    // the whole paragraph; preserve only genuinely additional instructions.
    const textKey = (text) => cleanOfficialText(String(text)).replace(/<[^>]+>/g, "").replace(/[\s；;，,。.!！:：]+/g, "");
    const displayedText = textKey(shown.map((line) => line.value === undefined ? line.label : `${line.value >= 0 ? "+" : ""}${(line.value * 100).toFixed(1)}% ${line.label}`).join(" "));
    const extraDescription = splitEffectSegments(officialDescription).flatMap((text) => text.split(/[；;\n]/)).filter((text) => textKey(text) && !displayedText.includes(textKey(text))).join("；");
    if (extraDescription) frag.append(create("p", "mod-effect-line is-description is-set-detail", extraDescription));
    const setText = isSacrificeSetMod(mod) ? "" : modSetText(mod);
    if (setText) frag.append(create("p", "mod-effect-line is-set is-set-detail", setText));
    // 镀层「实战满叠层」摘要不再渲染进卡面（会挤占卡面空间）——它保留在
    // 悬停 title（modEffectText）里，鼠标悬停即可看到满层数值。
  }
  // A card with no public text remains visually empty; diagnostics belong in
  // the title/diagnostics panel, never as gray pseudo-effects on the artwork.
  return frag;
}

// 牺牲系列（SacrificeSetMod）的套装效果是对卡面数值的直接乘算，属于重复信息。
function isSacrificeSetMod(mod) {
  return mod?.modSet === "SacrificeSetMod" || mod?.modSet === "UmbraSetMod";
}

// 计算态摘要行：镀层「实战满叠层」/ 套装「当前套装数值」。仅供悬停浮窗追加，
// 卡面不渲染；牺牲套装恒为空（增幅已乘进卡面数值）。
function modStackedSummary(mod) {
  if (!mod || isSacrificeSetMod(mod)) return "";
  const stacks = Math.max(...(mod.steadyStacks || []).map((item) => Number(item?.stacks) || 0), 0);
  if (!stacks || !Array.isArray(mod.displayEffects)) return "";
  // The kernel emits base and conditional effects as separate rows, even when
  // both share one upgradeType. Skip the leading base rows; never subtract the
  // base value from an already-separate stacked row.
  const baseRowCount = Array.isArray(mod.effects) ? mod.effects.filter((effect) => effect?.supported !== false).length : 0;
  const stacked = mod.displayEffects.slice(baseRowCount).flatMap((effect) => {
    const value = Number(effect?.value);
    return Number.isFinite(value) && Math.abs(value) > 1e-9
      ? [`${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}% ${effectLabel(effect)}`]
      : [];
  });
  return stacked.length ? `满层 ${stacks} 层：${stacked.join("；")}` : "";
}

function rivenStatDefinitions() {
  const type = state.buildWeapon?.rivenType || state.buildWeapon?.weaponType;
  return state.catalog?.statsByType?.[type] || [];
}

function rivenNominalRange(definition, negative, positiveCount, negativeCount) {
  const disposition = Number(state.buildWeapon?.disposition || 1);
  return rivenStatWindow(definition.baseValue, disposition, positiveCount, negativeCount, negative);
}

function renderRivenBuilder(target) {
  target.className = "mod-picker-grid is-riven-builder";
  const defs = rivenStatDefinitions();
  const panel = create("div", "riven-builder");
  const head = create("div", "riven-builder-head");
  head.append(create("strong", "", "构建紫卡"), create("small", "", "2–3 条正面词条 + 最多 1 条负面 · 数值范围随当前武器倾向"));
  panel.append(head);
  const rowsWrap = create("div", "riven-builder-rows");
  state.rivenBuilderStats.forEach((entry, index) => {
    const def = defs.find((d) => d.code === entry.code) || null;
    const row = create("div", `riven-builder-row${entry.negative ? " is-negative" : ""}`);
    const sign = create("button", "sign-toggle is-positive", entry.negative ? "−" : "+");
    sign.type = "button";
    sign.title = "切换正负面";
    sign.addEventListener("click", () => {
      const negativeCount = state.rivenBuilderStats.filter((s) => s.negative).length;
      const positiveCount = state.rivenBuilderStats.length - negativeCount;
      if (!entry.negative && def?.isFusion) return toast("融合词条仅正面");
      if (!entry.negative && !def?.canNegative) return toast(`${def?.label || "该词条"} 不能作为负面词条`);
      if (!entry.negative && (negativeCount >= 1 || positiveCount <= 2)) return toast("负面最多 1 条且需保留 2 条正面");
      entry.negative = !entry.negative;
      renderManualMods();
    });
    const select = document.createElement("select");
    select.className = "riven-stat-code";
    // 已被其他行占用的词条置灰（同一词条不能重复录入，与分析页同口径）。
    const usedCodes = new Set(state.rivenBuilderStats.filter((_s, i) => i !== index).map((s) => s.code));
    // 融合词条每卡限 1 条：其他行已有融合词条时，本行禁选所有融合词条。
    const fusionUsedElsewhere = state.rivenBuilderStats.some((_s, i) => i !== index && (defs.find((d) => d.code === _s.code)?.isFusion));
    defs.forEach((d) => {
      const option = document.createElement("option");
      option.value = d.code;
      option.textContent = d.isFusion ? `★${d.label || d.code}` : (d.label || d.code);
      option.selected = d.code === entry.code;
      // 负面行只能选可作负面的词条（元素/融合/穿透等只会是正面）。
      const positiveOnly = entry.negative && !d.canNegative;
      option.disabled = usedCodes.has(d.code) || (d.isFusion && fusionUsedElsewhere && d.code !== entry.code) || positiveOnly;
      if (positiveOnly) option.title = "该词条不能作为负面";
      if (d.isFusion) {
        const recipe = d.fusionRecipe || {};
        option.title = `融合词条（${recipe.primaryLabel || "?"} + ${recipe.secondaryLabel || "?"} 合成）· 仅正面，每卡限 1 条`;
      }
      select.append(option);
    });
    select.value = entry.code;
    select.addEventListener("change", () => {
      if (usedCodes.has(select.value)) return toast("同一词条不能重复录入");
      const chosen = defs.find((d) => d.code === select.value);
      if (entry.negative && !chosen?.canNegative) {
        select.value = entry.code;
        return toast(`${chosen?.label || "该词条"} 不能作为负面词条`);
      }
      entry.code = select.value;
      renderManualMods();
    });
    const shape = state.rivenBuilderStats.filter((s) => s.negative).length;
    const positives = state.rivenBuilderStats.length - shape;
    const range = def ? rivenNominalRange(def, entry.negative, positives, shape) : null;
    if (range) {
      entry.value = clamp(Number(entry.value ?? (range.low + (range.high - range.low) * 0.7)), range.low, range.high);
    }
    const slider = document.createElement("input");
    slider.type = "range";
    if (range) {
      slider.min = range.low.toFixed(3);
      slider.max = range.high.toFixed(3);
      slider.step = "0.1";
      slider.value = String(entry.value);
    }
    slider.addEventListener("input", () => { entry.value = Number(slider.value); readout.textContent = formatStatNumber(entry.value, def, entry.negative); });
    const readout = create("output", "riven-stat-output", formatStatNumber(entry.value, def, entry.negative));
    const remove = create("button", "remove-stat", "×");
    remove.type = "button";
    remove.title = "删除词条";
    remove.addEventListener("click", () => {
      if (state.rivenBuilderStats.length <= 2) return toast("紫卡至少 2 条词条");
      state.rivenBuilderStats.splice(index, 1);
      renderManualMods();
    });
    row.append(sign, select, slider, readout, remove);
    rowsWrap.append(row);
  });
  panel.append(rowsWrap);
  const actions = create("div", "riven-builder-actions");
  const add = create("button", "button button-quiet", "＋ 添加词条");
  add.type = "button";
  add.addEventListener("click", () => {
    if (state.rivenBuilderStats.length >= 4) return toast("紫卡最多 4 条词条");
    const used = new Set(state.rivenBuilderStats.map((s) => s.code));
    // 已有 3 条正面时第 4 条只能是负面：从可作负面的词条里选。
    const negative = state.rivenBuilderStats.length >= 3 && state.rivenBuilderStats.every((s) => !s.negative);
    const next = defs.find((d) => !used.has(d.code) && (!negative || d.canNegative));
    if (!next) return toast("没有更多可用词条");
    state.rivenBuilderStats.push({ code: next.code, value: null, negative });
    renderManualMods();
  });
  actions.append(add);
  // ── 最优紫卡求解（anytime 预算驱动，后端 /api/recommend-riven）──────
  const solveWrap = create("div", "riven-solve");
  const budget = document.createElement("select");
  budget.className = "riven-solve-budget";
  budget.title = "求解预算：时间越长搜索越完整（结果随时可用）";
  for (const seconds of [10, 20, 30, 60]) {
    const option = document.createElement("option");
    option.value = String(seconds);
    option.textContent = `${seconds}s`;
    option.selected = seconds === 10;
    budget.append(option);
  }
  budget.value = String(state.rivenSolveBudget || 10);
  budget.addEventListener("change", () => {
    state.rivenSolveBudget = Number(budget.value);
    persistActiveBuildConfig();
  });
  const solve = create("button", "button button-quiet", "◈ 计算最优");
  solve.type = "button";
  solve.title = "在当前配装语境下搜索 KPM 最高的紫卡词条组合（top 10）";
  solve.addEventListener("click", () => requestRivenRecommendation(Number(budget.value), panel));
  solveWrap.append(budget, solve);
  actions.append(solveWrap);
  // 紫卡极性只会是 Madurai / Vazarin / Naramon 三种之一（揭示时随机、洗卡不变）。
  const existingPolarity = state.manualSlots[state.modPickerSlot]?.rivenPolarity;
  if (!RIVEN_POLARITY_CHOICES.includes(state.rivenBuilderPolarity)) {
    state.rivenBuilderPolarity = RIVEN_POLARITY_CHOICES.includes(existingPolarity) ? existingPolarity : randomRegularPolarity();
  }
  const polarityPicker = create("div", "riven-polarity-picker");
  polarityPicker.append(create("small", "", "紫卡极性"));
  for (const polarity of RIVEN_POLARITY_CHOICES) {
    const button = create("button", `riven-polarity-option${state.rivenBuilderPolarity === polarity ? " is-active" : ""}`);
    button.type = "button";
    button.title = POLARITY_NAMES[polarity] || polarity;
    button.setAttribute("aria-pressed", String(state.rivenBuilderPolarity === polarity));
    button.append(imageNode(POLARITY_IMAGES[polarity], "riven-polarity-icon", POLARITY_NAMES[polarity] || polarity, "eager"));
    button.addEventListener("click", () => {
      state.rivenBuilderPolarity = polarity;
      polarityPicker.querySelectorAll(".riven-polarity-option").forEach((peer) => {
        const active = peer === button;
        peer.classList.toggle("is-active", active);
        peer.setAttribute("aria-pressed", String(active));
      });
    });
    polarityPicker.append(button);
  }
  actions.append(polarityPicker);
  const favorite = create("button", "button button-quiet riven-builder-favorite", "☆ 收藏");
  favorite.type = "button";
  favorite.title = "把这组词条存进紫卡收藏夹（跨武器查看）";
  const builderStats = () => state.rivenBuilderStats.map((s) => ({ code: s.code, value: Number(s.value || 0), negative: Boolean(s.negative) }));
  const paintFavorite = () => {
    const saved = Boolean(state.buildWeapon && findFavorite(state.buildWeapon.path, builderStats()));
    favorite.textContent = saved ? "★ 已收藏" : "☆ 收藏";
    favorite.classList.toggle("is-active", saved);
  };
  favorite.addEventListener("click", () => {
    toggleFavorite(state.buildWeapon, builderStats(), { polarity: state.rivenBuilderPolarity });
    paintFavorite();
  });
  panel.addEventListener("input", paintFavorite);
  paintFavorite();
  actions.append(favorite);
  const insert = create("button", "button button-primary", "放入当前槽位");
  insert.type = "button";
  insert.addEventListener("click", () => {
    const slot = state.modPickerSlot;
    if (state.manualLocks[slot]) return toast("当前槽位已锁定");
    const stats = state.rivenBuilderStats.map((s) => ({ code: s.code, value: Number(s.value || 0), negative: Boolean(s.negative) }));
    if (new Set(stats.map((s) => s.code)).size !== stats.length) return toast("同一词条不能重复录入");
    const negatives = stats.filter((s) => s.negative).length;
    const positives = stats.length - negatives;
    if (positives < 2 || positives > 3 || negatives > 1) return toast("需要 2–3 条正面词条，且最多 1 条负面");
    state.manualSlots[slot] = {
      __riven: true,
      path: "__riven__",
      nameZh: `${state.buildWeapon?.nameZh || "紫卡"} (自定义)`,
      nameEn: "Custom Riven",
      maxRank: 8,
      rank: 8,
      stats,
      // 紫卡落槽即掷出一个固定常规极性（游戏内 riven 洗卡极性随机且可用
      // 极化卡改）：与本武器绑定、随配置持久化，之后不再受槽位极化影响。
      rivenPolarity: state.rivenBuilderPolarity,
    };
    // 槽位上已有的极化若是为旧紫卡准备的，跟随新紫卡的极性。
    const nativeSlot = nativeSlotPolarities()[slot];
    if (Object.hasOwn(state.formaSlots, slot) && RIVEN_POLARITY_CHOICES.includes(state.formaSlots[slot])) {
      if (state.rivenBuilderPolarity === nativeSlot) delete state.formaSlots[slot];
      else state.formaSlots[slot] = state.rivenBuilderPolarity;
    }
    if (!ensureCapacityFit().fits) toast("容量不足：即使极化也装不下这张紫卡，请降低其他 MOD 等级", "error");
    refreshFormaCount();
    renderManualSlots();
    persistActiveBuildConfig();
    scheduleLiveManualSimulation();
    closeModPicker();
    toast("紫卡已放入槽位");
  });
  actions.append(insert);
  const hint = create("small", "riven-builder-hint", "词条数值范围 = 武器倾向 × 词条基准值 × 词条数系数");
  actions.append(hint);
  panel.append(actions);
  // 上一次求解结果（同一会话内重新打开面板时保留显示）。
  if (state.rivenRecommendation) {
    panel.append(renderRivenRecommendation(state.rivenRecommendation));
  }
  target.replaceChildren(panel);
}

// ── 最优紫卡求解：请求 + 结果渲染 ──────────────────────────────────────
async function requestRivenRecommendation(budgetSeconds, hostElement) {
  if (state.rivenSolving) return toast("最优求解进行中，请稍候");
  let payload;
  let requestedConfig;
  try {
    // 复用配装表单的全部语境（武器/敌人/约束/赋能/灵化/架势），与
    // 「填充最优」同一套基准——最优紫卡是在当前限制下的最优配装之上定义的。
    payload = buildPayloadFromForm();
    requestedConfig = structuredClone(captureBuildConfig());
  } catch (error) {
    return toast(error.message || "无法读取当前配装语境");
  }
  delete payload.riven;
  payload.budgetSeconds = budgetSeconds;
  payload.topLimit = 10;
  payload.triggerPolicy = "assumed_max";
  payload.optimizeWithArcanes = true;
  state.rivenSolving = true;
  const existing = hostElement.querySelector(".riven-solve-results");
  const list = create("div", "riven-solve-results");
  list.append(create("p", "riven-solve-progress", `正在按当前配卡搜索紫卡（预算 ${budgetSeconds} 秒，已装备赋能与 MOD 按满触发计算）…`));
  if (existing) existing.replaceWith(list);
  else hostElement.append(list);
  try {
    const response = await fetch("/api/recommend-riven", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => null);
      throw new Error(error?.error?.message || `求解失败（${response.status}）`);
    }
    const result = await response.json();
    if (state.buildWeapon?.path !== payload.weapon) return;
    state.rivenRecommendation = { ...result, budgetSeconds, requestedConfig };
    const fresh = renderRivenRecommendation(state.rivenRecommendation);
    list.replaceWith(fresh);
  } catch (error) {
    list.replaceChildren(create("p", "riven-solve-error", error.message || "求解失败"));
  } finally {
    state.rivenSolving = false;
  }
}

function renderRivenRecommendation(recommendation) {
  // 返回带 .riven-solve-results 外框的完整节点（可直接 append 到面板）。
  const wrap = create("div", "riven-solve-results");
  const combos = recommendation.combos || [];
  if (!combos.length) {
    wrap.append(create("p", "riven-solve-error", "没有找到可行的词条组合"));
    return wrap;
  }
  const head = create("div", "riven-solve-head");
  const metricLabel = { killsPerMinute: "KPM", shotDamage: "单次伤害", burstDps: "爆发 DPS", sustainedDps: "持续 DPS", attackDps: "攻击 DPS" }[recommendation.metric] || recommendation.metric || "KPM";
  head.append(
    create("strong", "", "最优词条 TOP 10"),
    create("small", "", `基准 ${metricLabel} ${formatMetric(recommendation.baselineScore)} · 用时 ${recommendation.elapsed.toFixed(1)}s · ${recommendation.evaluations.toLocaleString()} 次评估`),
  );
  wrap.append(head);
  const rows = create("div", "riven-solve-list");
  combos.forEach((combo, index) => {
    const row = create("button", `riven-solve-row${index === 0 ? " is-top" : ""}`);
    row.type = "button";
    row.title = "应用此紫卡与对应配装";
    const rank = create("span", "riven-solve-rank", String(index + 1));
    const stats = create("div", "riven-solve-stats");
    for (const stat of combo.stats) {
      stats.append(create("em", stat.negative ? "is-negative" : "", `${stat.negative ? "−" : "+"}${stat.label} ${stat.value.toFixed(1)}${stat.unit === "percent" ? "%" : ""}`));
    }
    const score = create("span", "riven-solve-score");
    score.append(
      create("b", "", formatMetric(combo.score)),
      create("i", combo.gain >= 0 ? "is-positive" : "is-negative", `${combo.gain >= 0 ? "+" : ""}${combo.gain.toFixed(1)}%`),
    );
    row.append(rank, stats, score);
    row.addEventListener("click", () => applyRecommendedRiven(combo));
    rows.append(row);
  });
  wrap.append(rows);
  return wrap;
}

function applyRecommendedRiven(combo) {
  const recommendation = state.rivenRecommendation;
  if (recommendation?.weapon?.path !== state.buildWeapon?.path) return toast("该结果属于另一把武器，请重新求解");
  const build = combo.build;
  if (!build?.mods || !Number.isInteger(build.riven?.slot) || !Array.isArray(build.riven.stats)) {
    return toast("求解结果缺少完整配装，请重新求解");
  }
  const negatives = combo.stats.filter((s) => s.negative).length;
  const positives = combo.stats.length - negatives;
  if (positives < 2 || positives > 3 || negatives > 1) {
    return toast("该组合词条结构无法回填");
  }
  const config = {
    ...(recommendation.requestedConfig || captureBuildConfig()),
    mode: "manual", fireMode: recommendation.fireMode,
    incarnonChoices: recommendation.incarnonChoices,
    mods: build.mods.map((mod) => ({ path: mod.path, rank: mod.rank, slot: mod.slot })),
    riven: structuredClone(build.riven), exilus: build.exilus,
    triggerPolicy: recommendation.triggerPolicy || recommendation.requestedConfig?.triggerPolicy || "emergent",
    optimizeWithArcanes: recommendation.optimizeWithArcanes,
  };
  applyBuildConfig(config);
  syncAutoFormaFromSlots();
  persistActiveBuildConfig();
  closeModPicker();
  scheduleLiveBuild();
  toast(`已应用第 ${recommendation.combos?.indexOf(combo) + 1 || "?"} 名紫卡与配装`);
}

function createCustomRivenSlotCard(mod, index, slotPolarity = null) {
  const card = create("article", "mod-slot is-riven-slot");
  card.dataset.rarity = "RIVEN";
  const frame = create("div", "game-mod-card riven-mod-card");
  const frames = state.modAssets?.rarityFrames?.RIVEN || {};
  const content = create("div", "mod-content");
  const definitions = rivenStatDefinitions();
  content.append(...rivenContentLayers(frames, rivenFaceArts(mod.stats, definitions)));
  const description = create("div", "mod-description");
  description.append(modNameNode(state.buildWeapon ? rivenCardName(state.buildWeapon, mod.stats, definitions) : (mod.nameZh || "自定义紫卡")));
  (mod.stats || []).forEach((stat) => {
    description.append(create("p", `mod-effect-line${stat.negative ? " is-negative" : ""}`, rivenStatLabel(stat)));
  });
  content.append(description);
  frame.append(content);
  const compat = create("div", "mod-item-compat");
  compat.append(create("p", "", "裂罅"));
  if (frames.lowerTab) compat.style.setProperty("--lower-tab", `url("${frames.lowerTab}")`);
  frame.append(compat);
  frame.append(rankPips(8, 8));
  // 消耗/极性徽章：紫卡固定极性（落槽时掷出）与槽位极性比对——
  // 匹配减半（18→9）/不匹配 ×1.25 / 槽位无极性全值；徽章显示紫卡固定极性。
  const rivenEffective = modEffectiveDrain(mod, slotPolarity, index);
  const rivenPol = rivenFixedPolarity(mod, index);
  const badge = modCostBadge(rivenEffective.drain, rivenPol, "eager", " is-riven-drain", rivenEffective.relation === "match" ? "match" : rivenEffective.relation === "mismatch" ? "mismatch" : "");
  frame.append(badge);
  frame.append(...modFrameLayers(frames, "eager"));
  card.append(modTiltWrap(frame), create("span", "slot-number", String(index + 1).padStart(2, "0")));
  return card;
}

function rivenStatLabel(stat) {
  const defs = rivenStatDefinitions();
  const def = defs.find((d) => d.code === stat.code);
  const label = def?.label || stat.code;
  const value = Number(stat.value || 0);
  const sign = stat.negative ? "−" : "+";
  const unit = def?.unit === "percent" ? "%" : "";
  return `${sign}${value.toFixed(1)}${unit} ${label}`;
}

function modConditionalText(mod) {
  const meta = modAssetFields(mod);
  if (meta.conditionZh) {
    if (conditionAlreadyListed(meta)) return "";
    return cleanOfficialText(meta.conditionZh);
  }
  const conds = Array.isArray(mod?.conditionalEffects) ? mod.conditionalEffects : [];
  if (!conds.length) return "";
  const parts = [];
  for (const cond of conds.slice(0, 2)) {
    const effects = Array.isArray(cond?.effects) ? cond.effects : [];
    const summary = effects.slice(0, 2).map((effect) => {
      // Script placeholders are not a second visible stat.  Rendering a
      // NONE/0 row is what produced the literal "NONE +0.0%" on cards such as
      // Rolling Guard; its official localized text is already rendered above.
      if (String(effect?.upgradeType || "").toUpperCase() === "NONE") return "";
      const value = Number(effect?.valuePerRank);
      const label = cleanOfficialText(effectLabel(effect));
      if (!Number.isFinite(value)) return label;
      const total = value * ((mod.rank ?? mod.maxRank ?? 0) + 1);
      return `${label} ${total >= 0 ? "+" : ""}${(total * 100).toFixed(1)}%`;
    }).join("，");
    if (summary) parts.push(summary);
  }
  return parts.join("；");
}

function modNameNode(name) {
  const nameEl = create("strong", "mod-name", name);
  if (nameEl.textContent.length > 14) nameEl.classList.add("is-overflow");
  return nameEl;
}

function modVariant(mod, metadata) {
  const nameEn = String(metadata?.nameEn || mod?.nameEn || "");
  const nameZh = String(metadata?.nameZh || mod?.nameZh || "");
  const path = String(metadata?.path || mod?.path || "");
  if (/\/Lotus\/Upgrades\/Mods\/Warframe\/Kahl\/KahlAvatar(?:AbilityDuration|PowerMax|AbilityStrength|AbilityRange|HealthMax)Mod$/i.test(path)) return "ARCHON";
  if (/^Galvanized[\s]/i.test(nameEn) || nameZh.startsWith("镀层")) return "GALVANIZED";
  if (/^Amalgam[\s]/i.test(nameEn) || nameZh.startsWith("并合")) return "AMALGAM";
  return "";
}

function modCompatLabel(mod, metadata) {
  const compat = String(mod?.compatibility || metadata?.compatibility || "");
  let compatZh = "";
  const tags = {
    "/Lotus/Weapons/Tenno/LotusLongGun": "步枪",
    "/Lotus/Weapons/Tenno/Rifle/LotusRifle": "步枪",
    "/Lotus/Weapons/Tenno/Rifle/LotusAssaultRifle": "步枪",
    "/Lotus/Weapons/Tenno/Shotgun/LotusShotgun": "霰弹枪",
    "/Lotus/Weapons/Tenno/Pistol/LotusPistol": "手枪",
    "/Lotus/Weapons/Tenno/LotusPistol": "手枪",
    "/Lotus/Weapons/Tenno/Melee/PlayerMeleeWeapon": "近战",
    "/Lotus/Weapons/Tenno/Melee/LotusHeavyBladeMeleeWeapon": "近战",
    "/Lotus/Weapons/Tenno/Melee/LotusBladeWhipWeapon": "近战",
    "/Lotus/Weapons/Tenno/Melee/LotusGlaiveWeaponBase": "近战",
  };
  if (tags[compat]) compatZh = tags[compat];
  else if (/Rifle|LongGun|AssaultRifle|Bow|Launcher/i.test(compat)) compatZh = "步枪";
  else if (/Shotgun/i.test(compat)) compatZh = "霰弹枪";
  else if (/Pistol/i.test(compat)) compatZh = "手枪";
  else if (/Melee/i.test(compat)) compatZh = "近战";
  else {
    const category = modCategory(mod);
    if (category === "melee" || category === "damage" || category === "critical" || category === "multishot" || category === "element" || category === "status" || category === "speed" || category === "handling") {
      compatZh = ["melee", "zaw"].includes(state.buildWeapon?.weaponType) ? "近战" : "武器";
    } else compatZh = "MOD";
  }
  const compatibilityTags = mod?.compatibilityTags || metadata?.compatibilityTags || [];
  if (compatibilityTags.includes("SEMI_AUTO")) compatZh = `半自动${compatZh}`;
  if (mod?.modSet) return `套装: ${compatZh}`;
  return compatZh;
}

function createNormalModCard(mod, slotIndex, options = {}) {
  const metadata = modAssetFields(mod);
  const rarity = mod.rarity || metadata.rarity || "COMMON";
  const variant = modVariant(mod, metadata);
  const frameKey = variant || rarity;
  const frames = state.modAssets?.rarityFrames?.[frameKey] || state.modAssets?.rarityFrames?.[rarity] || state.modAssets?.rarityFrames?.RARE || {};
  const loading = slotIndex ? "eager" : "lazy";
  const card = create("article", `mod-slot${options.compact ? " is-compact" : ""}`);
  card.dataset.rarity = frameKey;
  if (!options.compact) card.title = modEffectText(mod);
  const frame = create("div", "game-mod-card");
  const content = create("div", "mod-content");
  content.append(...modContentLayers(frames, metadata, mod, "mod-art", loading, !options.compact));

  const maxRank = Math.max(0, Math.min(10, Math.floor(finite(mod.maxRank) ?? finite(metadata.maxRank) ?? 0)));
  const rank = clamp(finite(mod.rank) ?? maxRank, 0, maxRank);
  const polarity = metadata.polarity || mod.polarity || null;
  let drain;
  let relation = "";
  const slotPolarity = options.slotPolarity;
  if (mod.__riven) {
    drain = 18;
  } else if (slotPolarity) {
    const effective = modEffectiveDrain(mod, slotPolarity);
    drain = effective.drain;
    relation = effective.relation;
  } else {
    // `baseDrain` is the rank-0 cost; do not treat it as max-rank cost.
    const baseDrain = finite(mod.baseDrain) ?? finite(metadata.baseDrain);
    const maxDrain = finite(metadata.drain) ?? finite(mod.drain);
    if (baseDrain !== null) {
      const rankedDrain = Math.round(Math.abs(baseDrain) + rank);
      drain = baseDrain < 0 ? -rankedDrain : rankedDrain;
    } else {
      drain = Math.max(0, Math.round((maxDrain ?? 0) - (maxRank - rank)));
    }
  }

  const description = create("div", "mod-description");
  description.append(
    modNameNode(metadata.nameZh || mod.nameZh || metadata.nameEn || mod.nameEn || mod.nameInternal || "MOD"),
    renderEffectLines(mod, !options.compact),
  );
  content.append(description);
  frame.append(content);
  // 以下元素锚定整张卡（不参与内容裁剪），与 Overframe 一致
  const compat = create("div", "mod-item-compat");
  compat.append(create("p", "", options.compatLabel || modCompatLabel(mod, metadata)));
  if (frames.lowerTab) compat.style.setProperty("--lower-tab", `url("${frames.lowerTab}")`);
  frame.append(compat);
  if (maxRank > 0) frame.append(rankPips(rank, maxRank, frames, loading));
  frame.append(modCostBadge(drain, polarity, loading, "", relation));
  const gain = create("div", "mod-gain-badge");
  gain.hidden = true;
  frame.append(gain);
  frame.append(...modFrameLayers(frames, loading));
  card.append(modTiltWrap(frame), create("span", "slot-number", String(slotIndex).padStart(2, "0")));
  // 槽位类型标记属于卡面，折叠/展开时始终跟随卡片顶部。
  if (options.slotMarker) frame.append(imageNode(options.slotMarker, "mod-slot-kind-marker", options.slotMarkerLabel || "特殊槽 MOD", loading));
  return card;
}

function rivenCardLines(build = null) {
  const source = Array.isArray(build?.rivenLines)
    ? build.rivenLines
    : (Array.isArray(build?.rivenStats) ? build.rivenStats : activeStats().filter((entry) => entry.definition && entry.value !== null));
  return source.map((line) => {
    const code = String(line?.code || "").toUpperCase();
    const definition = statDefinitions().find((item) => item.code === code) || line?.definition || null;
    const value = finite(line?.value ?? line?.rawValue);
    if (value === null) return null;
    const negative = Boolean(line?.negative);
    return `${formatStatNumber(value, definition || { unit: line?.unit || "" }, negative)} ${line?.label || definition?.label || code}`.trim();
  }).filter(Boolean);
}

function createRivenModCard(slotIndex, build = null) {
  const card = create("article", "mod-slot is-riven-slot");
  card.dataset.rarity = "RIVEN";
  const frame = create("div", "game-mod-card riven-mod-card");
  const frames = state.modAssets?.rarityFrames?.RIVEN || {};
  const content = create("div", "mod-content");
  content.append(...rivenContentLayers(frames, rivenFaceArts(activeStats().filter((entry) => entry.definition && entry.value !== null), statDefinitions())));
  const description = create("div", "mod-description");
  description.append(modNameNode(ui["card-name"].textContent || "紫卡"));
  const lines = rivenCardLines(build);
  if (lines.length) description.append(...lines.map((line) => create("p", "mod-effect-line", line)));
  content.append(description);
  frame.append(content);
  const compat = create("div", "mod-item-compat");
  compat.append(create("p", "", "裂罅"));
  if (frames.lowerTab) compat.style.setProperty("--lower-tab", `url("${frames.lowerTab}")`);
  frame.append(compat);
  frame.append(rankPips(8, 8));
  const badge = modCostBadge(18, null, "eager", " is-riven-drain");
  const polaritySrc = ui["card-polarity"].getAttribute("src") || POLARITY_IMAGES.AP_ATTACK;
  badge.querySelector(".mod-drain").append(imageNode(polaritySrc, "mod-polarity", "紫卡极性", "eager"));
  frame.append(badge);
  frame.append(...modFrameLayers(frames, "eager"));
  card.append(modTiltWrap(frame), create("span", "slot-number", String(slotIndex).padStart(2, "0")));
  return card;
}

// —— 伪 3D 视差（复刻游戏内 hover：卡随鼠标方向微倾，卡面主体/背景分层位移）——
// .mod-tilt 承载整卡倾斜（卡框 transform 被展开/收起动画占用）；立绘双层与高光
// 由 --par-x/--par-y 驱动（见 app.css）。compact 选择器卡与浮出预览弹窗不参与。
let tiltCard = null;
let tiltRaf = 0;
let tiltPoint = null;
function clearTilt() {
  if (!tiltCard) return;
  const tilt = tiltCard.closest(".mod-tilt");
  if (tilt) {
    tilt.style.transition = "transform .2s ease-out";
    tilt.style.transform = "";
    setTimeout(() => { if (!tilt.style.transform) tilt.style.transition = ""; }, 220);
  }
  tiltCard = null;
  tiltPoint = null;
}
function applyTilt() {
  tiltRaf = 0;
  if (!tiltCard || !tiltPoint) return;
  // 卡已不再悬停（例如倾斜把卡边转出光标后 hover 丢失）：立即复位，杜绝残留倾斜。
  if (!tiltCard.matches(":hover")) { clearTilt(); return; }
  const rect = tiltCard.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const nx = Math.max(-1, Math.min(1, ((tiltPoint.x - rect.left) / rect.width - 0.5) * 2));
  const ny = Math.max(-1, Math.min(1, ((tiltPoint.y - rect.top) / rect.height - 0.5) * 2));
  tiltCard.style.setProperty("--par-x", nx.toFixed(3));
  tiltCard.style.setProperty("--par-y", ny.toFixed(3));
  const tilt = tiltCard.closest(".mod-tilt");
  if (!tilt) return;
  // 边缘衰减：光标距可视边缘 <6px 时倾斜为 0、18px 外满幅——倾斜本身会让卡边
  // 移动几 px，若边缘处仍有倾斜，卡边会被甩出光标 → :hover 丢失 → 收起→又命中→
  // 自激振荡（卡面"开开关关猛抽"）。衰减带保证倾斜量永远不足以把边推出光标。
  const fade = (d) => Math.max(0, Math.min(1, (d - 6) / 12));
  const fx = fade(Math.min(tiltPoint.x - rect.left, rect.right - tiltPoint.x));
  const fy = fade(Math.min(tiltPoint.y - rect.top, rect.bottom - tiltPoint.y));
  tilt.style.transition = "";
  tilt.style.transform = `perspective(720px) rotateX(${(-ny * 5 * fy).toFixed(2)}deg) rotateY(${(nx * 5 * fx).toFixed(2)}deg)`;
}
document.addEventListener("mousemove", (event) => {
  const card = event.target?.closest?.(".mod-slot:not(.is-compact) .game-mod-card");
  const next = card && !card.closest(".mod-preview-pop") ? card : null;
  if (next !== tiltCard) {
    clearTilt();
    tiltCard = next;
  }
  if (!tiltCard) return;
  tiltPoint = { x: event.clientX, y: event.clientY };
  if (!tiltRaf) tiltRaf = requestAnimationFrame(applyTilt);
});
document.addEventListener("mouseleave", clearTilt);

function renderMods(build, target = ui["mod-grid"], slotCount = 8) {
  const mods = Array.isArray(build?.mods) ? build.mods : [];
  const includesRiven = build?.includesRiven !== false;
  // Slot-driven layout: each mod renders at its own slot index; empty slots stay
  // in place instead of collapsing the row (matches in-game / Overframe grids).
  const cells = Array.from({ length: slotCount }, () => null);
  for (const mod of mods) {
    const slot = Math.trunc(Number(mod?.slot));
    const index = Number.isInteger(slot) && slot >= 0 && slot < slotCount ? slot : mods.indexOf(mod);
    if (index >= 0 && index < slotCount) cells[index] = mod;
  }
  if (includesRiven) {
    const declaredSlot = build?.riven?.slot;
    const rivenSlot = Number.isInteger(declaredSlot) && declaredSlot >= 0 && declaredSlot < slotCount && !cells[declaredSlot]
      ? declaredSlot : cells.map((cell, i) => (cell ? -1 : i)).filter((i) => i >= 0).pop();
    if (rivenSlot !== undefined && rivenSlot >= 0) cells[rivenSlot] = "__riven__";
  }
  const nodes = cells.map((mod, index) => {
    if (mod === "__riven__") return createRivenModCard(index + 1, build);
    if (mod) return createNormalModCard(mod, index + 1);
    const empty = create("article", "mod-slot is-empty");
    empty.append(create("div", "empty-mod-slot", "空槽位"), create("span", "slot-number", String(index + 1).padStart(2, "0")));
    return empty;
  });
  target.replaceChildren(...nodes);
}

function modMatchesBuildWeapon(mod) {
  const weapon = state.buildWeapon;
  if (!weapon || !mod) return false;
  const normalize = (value) => String(value || "").replace(/\\/g, "/").replace(/\/$/, "").toLocaleLowerCase();
  const compatibility = normalize(mod.compatibility);
  const ancestry = new Set([...(weapon.ancestry || []), weapon.path].map(normalize).filter(Boolean));
  if (compatibility && !ancestry.has(compatibility)) return false;
  const tags = new Set((weapon.compatTags || []).map((tag) => String(tag).toLocaleLowerCase()));
  const required = (mod.compatibilityTags || []).map((tag) => String(tag).toLocaleLowerCase()).filter(Boolean);
  const blocked = new Set((mod.incompatibilityTags || []).map((tag) => String(tag).toLocaleLowerCase()).filter(Boolean));
  return (!required.length || required.some((tag) => tags.has(tag))) && ![...blocked].some((tag) => tags.has(tag));
}

const MOD_CATEGORY_LABELS = {
  all: "全部",
  damage: "伤害",
  critical: "暴击",
  multishot: "多重",
  element: "元素",
  status: "异常",
  speed: "射速 / 攻速",
  handling: "弹匣 / 装填",
  set: "套装",
  utility: "其他",
};

function modCategory(mod) {
  if (mod?.category && MOD_CATEGORY_LABELS[mod.category]) return mod.category;
  if (mod?.modSet) return "set";
  const effects = Array.isArray(mod?.effects) ? mod.effects : [];
  const types = new Set(effects.map((effect) => String(effect?.upgradeType || "").toUpperCase()));
  const damageTypes = new Set(["DT_FIRE", "DT_FREEZE", "DT_ELECTRICITY", "DT_POISON", "DT_MAGNETIC", "DT_RADIATION", "DT_VIRAL", "DT_CORROSIVE", "DT_EXPLOSION", "DT_GAS"]);
  if (effects.some((effect) => damageTypes.has(String(effect?.damageType || "").toUpperCase()))) return "element";
  if (["WEAPON_CRIT_CHANCE", "WEAPON_CRIT_DAMAGE", "WEAPON_NOCRIT_DAMAGE"].some((type) => types.has(type))) return "critical";
  if (types.has("WEAPON_FIRE_ITERATIONS")) return "multishot";
  if (["WEAPON_PROC_CHANCE", "WEAPON_PROC_DAMAGE", "WEAPON_PROC_TIME", "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE"].some((type) => types.has(type))) return "status";
  if (types.has("WEAPON_FIRE_RATE")) return "speed";
  if (["WEAPON_RELOAD_SPEED", "WEAPON_CLIP_MAX", "WEAPON_AMMO_MAX"].some((type) => types.has(type))) return "handling";
  if (["WEAPON_DAMAGE_AMOUNT", "WEAPON_MELEE_DAMAGE", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "GAMEPLAY_FACTION_DAMAGE"].some((type) => types.has(type))) return "damage";
  return "utility";
}

// MOD 互斥家族键：modFamily + 武器兼容类别。镀层/普通/Prime/并合同名卡共享
// modFamily 且兼容同一武器（如镀层步枪才能与步枪才能）——一张配装只能带一张；
// 跨武器类别的同名家族（膛线=步枪 / 抵近射击=霰弹枪）互不冲突。
function modExclusiveFamily(mod) {
  const family = String(mod?.modFamily || mod?.nameTag || mod?.nameEn || mod?.nameInternal || mod?.path || "").toLocaleLowerCase();
  const compatibility = String(mod?.compatibility || "").toLocaleLowerCase();
  return `${family}#${compatibility}`;
}

function manualModRecords() {
  const weapon = state.buildWeapon;
  if (state.modPickerKind === "sentinel") return sentinelModRecords();
  if (state.modPickerKind === "stance") {
    return stanceRecords().filter((stance) => stanceMatchesBuildWeapon(stance) && specialRecordMatchesSearch(stance));
  }
  if (state.modPickerKind === "exilus") {
    return utilityModRecords().filter((mod) => utilityMatchesBuildWeapon(mod) && specialRecordMatchesSearch(mod));
  }
  const rows = state.catalog?.manualMods || weapon?.compatibleMods || state.catalog?.mods || [];
  if (!Array.isArray(rows)) return [];
  const query = String(ui["manual-mod-search"]?.value || "").trim().toLocaleLowerCase();
  const used = new Set(state.manualSlots.filter(Boolean).map((item) => item.path));
  // 已装备卡的互斥家族：同名（镀层/普通/Prime）卡在选择器中一并隐藏。
  const usedFamilies = new Set(state.manualSlots.filter(Boolean).map((item) => modExclusiveFamily(item)).filter(Boolean));
  const filtered = rows.filter((mod) => {
    const family = modExclusiveFamily(mod);
    if (family && usedFamilies.has(family) && !used.has(mod.path)) return false;
    const effectText = modEffectText({ ...mod, rank: mod.maxRank ?? 0 });
    const haystack = [mod.nameZh, mod.nameEn, mod.nameInternal, mod.path, effectText].filter(Boolean).join(" ").toLocaleLowerCase();
    return (!query || haystack.includes(query)) && (state.manualModCategory === "all" || modCategory(mod) === state.manualModCategory) && !used.has(mod.path) && mod.selectable !== false && modMatchesBuildWeapon(mod);
  }).slice(0, 160);
  if (state.modGainsSort) {
    const gains = state.modGains || {};
    const gainOf = (mod) => {
      const info = gains[mod.path];
      if (!info || info.gainPercent === null || info.gainPercent === undefined) return -Infinity;
      return Number(info.gainPercent);
    };
    filtered.sort((a, b) => (gainOf(b) - gainOf(a)) || String(a.nameZh || "").localeCompare(String(b.nameZh || ""), "zh"));
  }
  return filtered;
}

function specialRecordMatchesSearch(record) {
  const query = String(ui["manual-mod-search"]?.value || "").trim().toLocaleLowerCase();
  if (!query) return true;
  const kind = state.modPickerKind === "stance" ? "stance" : "exilus";
  return [record.nameZh, record.nameEn, record.nameInternal, record.path, specialModSummary(record, kind)]
    .filter(Boolean).join(" ").toLocaleLowerCase().includes(query);
}

function stanceBestCombo(stance) {
  if (stance?.bestComboData && typeof stance.bestComboData === "object") return stance.bestComboData;
  const combos = Array.isArray(stance?.combos) ? stance.combos : [];
  if (typeof stance?.bestCombo === "string") {
    const selected = combos.find((combo) => combo.kind === stance.bestCombo || combo.name === stance.bestCombo);
    if (selected) return selected;
  }
  return combos.reduce((best, combo) => Number(combo.dpsMultiplier || 0) > Number(best?.dpsMultiplier || 0) ? combo : best, null);
}

function specialModSummary(mod, kind = state.modPickerKind) {
  if (kind === "stance" || mod?.compatTag || mod?.bestComboData || mod?.combos || mod?.builtIn || mod?.locked) {
    const combo = stanceBestCombo(mod);
    return combo ? `${combo.name || combo.kind || "普通连段"} · ${Number(combo.totalMultiplier || 0).toFixed(2)}x / ${Number(combo.duration || 0).toFixed(2)}s` : "天生架势";
  }
  return modEffectText(mod) || `${mod.sourceKind || "功能槽"} · 容量 ${Number(mod.drain || 0)}`;
}

// 功能槽卡片的兼容标签按 wiki 类型显示：Rifle/Shotgun/Pistol/Melee。
function utilityCompatLabel(mod) {
  const path = String(mod?.path || "");
  const family = path.split("/")[4] || "";
  if (family === "Rifle") return "步枪";
  if (family === "Shotgun") return "霰弹枪";
  if (family === "Pistol") return "手枪";
  if (family === "Melee") return "近战";
  if (family === "Warframe" || family === "OrokinChallenge") return "战甲";
  if (path.includes("/EmpoweredHeavyMelee/")) return "近战";
  if (family === "Sets") return mod?.slotKind === "primary" ? "主武器" : mod?.slotKind === "melee" ? "近战" : mod?.slotKind === "secondary" ? "次要武器" : "战甲";
  const slot = String(mod?.slotKind || "");
  return { primary: "主武器", secondary: "手枪", melee: "近战", warframe: "战甲" }[slot] || "功能";
}

function createSpecialModCard(mod, kind, compact = false, slotPolarityOverride) {
  const maxRank = Number(mod.maxRank ?? mod.rank ?? 0);
  // 卡面：目录 iconAsset 优先，缺失时从资源索引按路径解析（Prime 版与
  // 普通版共用同一张官方卡面，导出记录不带 icon 字段）。
  const art = catalogIconAsset(mod) || modAssetFields(mod).art || "";
  const card = createNormalModCard({ ...mod, art, maxRank, rank: Number(mod.rank ?? maxRank) }, 0, {
    compact,
    compatLabel: kind === "stance" ? "架势" : utilityCompatLabel(mod),
    slotPolarity: slotPolarityOverride !== undefined ? slotPolarityOverride : weaponSpecialSlotPolarity(kind),
  });
  card.querySelector(".slot-number")?.remove();
  const description = card.querySelector(".mod-description");
  const summary = specialModSummary(mod, kind);
  if (description && summary) {
    description.querySelector(".mod-effect-line.is-empty")?.remove();
    if (!description.querySelector(".mod-effect-line")) description.append(create("p", "mod-effect-line", summary));
  }
  return card;
}

// 分析结果（仅近战/组合近战）：在 MOD 网格右侧垂直居中展示本次解算使用的
// 架势与架势槽。数据源 stance 由后端给出（默认普攻 DPS 倍率最高架势，架势槽
// 视为已极化匹配），卡面素材从前端目录的 stance 记录补齐。
function renderAnalysisStance() {
  const target = ui["analysis-stance"];
  if (!target) return;
  const stance = state.result?.stance;
  if (!stance?.path) {
    target.hidden = true;
    target.replaceChildren();
    return;
  }
  const record = stanceRecords().find((row) => row.path === stance.path) || {};
  const merged = { ...record, ...stance };
  const slotPolarity = normalizedSpecialPolarity(state.weapon?.specialSlots?.stance?.slotPolarity);
  const head = create("div", "analysis-stance-head");
  head.append(imageNode("/assets/game/slots/IconStance.png", "analysis-stance-icon", "", "lazy"), create("span", "", "架势槽"));
  if (slotPolarity) {
    const polarity = POLARITY_IMAGES[slotPolarity]
      ? imageNode(POLARITY_IMAGES[slotPolarity], "analysis-stance-polarity", POLARITY_NAMES[slotPolarity] || slotPolarity, "lazy")
      : create("span", "analysis-stance-polarity", "");
    polarity.title = `槽位极性：${POLARITY_NAMES[slotPolarity] || slotPolarity}`;
    head.append(polarity);
  }
  if (stance.builtIn) head.append(create("b", "analysis-stance-lock", "天生"));
  const gain = Number(stance.capacityGain || 0);
  if (gain > 0) head.append(create("b", "analysis-stance-gain", `容量 +${gain}`));
  const cardWrap = create("div", "analysis-stance-card");
  cardWrap.append(createSpecialModCard(merged, "stance", true, slotPolarity));
  const bits = [];
  const multiplier = Number(stance.dpsMultiplier || 0);
  if (multiplier > 0 && !stance.builtIn) bits.push(`普攻连段 ×${multiplier.toFixed(2)}`);
  bits.push(stance.builtIn ? "显赫武器天生架势" : "已按匹配极性计入解算");
  target.replaceChildren(head, cardWrap, create("p", "analysis-stance-summary", bits.join(" · ")));
  target.hidden = false;
}

// Preset quick-picks follow Riven-Mirror's fast-select: concrete card lists
// per weapon family, resolved against the live candidate catalog.
const MOD_PRESETS = {
  rifle: [
    { id: "damage", label: "基础伤害", cards: ["Serration", "Heavy Caliber"] },
    { id: "crit", label: "暴击流", cards: ["Point Strike", "Vital Sense"] },
    { id: "multishot", label: "多重射击", cards: ["Split Chamber", "Argon Scope", "Bladed Rounds"] },
    { id: "status", label: "触发流", cards: ["Rime Rounds", "Malignant Force", "Thermite Rounds", "High Voltage"] },
    { id: "speed", label: "射速", cards: ["Vile Acceleration", "Speed Trigger"] },
    { id: "element", label: "元素", cards: ["Primed Cryo Rounds", "Hellfire", "Stormbringer", "Infected Clip"] },
    { id: "goldCorrosive", label: "镀层腐蚀", cards: ["Galvanized Aptitude", "Galvanized Shot", "Rime Rounds", "Malignant Force"] },
    { id: "goldViral", label: "镀层病毒", cards: ["Primed Cryo Rounds", "Infected Clip", "Galvanized Chamber"] },
    { id: "goldCrit", label: "镀层暴击", cards: ["Galvanized Scope", "Galvanized Crosshairs", "Vital Sense"] },
  ],
  melee: [
    { id: "damage", label: "近战伤害", cards: ["Primed Pressure Point", "Sacrificial Pressure", "Condition Overload"] },
    { id: "crit", label: "暴击流", cards: ["Sacrificial Steel", "Blood Rush", "Organ Shatter"] },
    { id: "speed", label: "攻速", cards: ["Primed Fury", "Berserker Fury", "Gladiator Vice"] },
    { id: "status", label: "触发流", cards: ["Weeping Wounds", "Drifting Contact", "Voltaic Strike", "Virulent Scourge"] },
    { id: "element", label: "元素", cards: ["Primed Fever Strike", "Volcanic Edge", "Virulent Scourge", "North Wind"] },
  ],
};

function presetFamilyFor(weapon) {
  const type = weapon?.weaponType;
  if (["melee", "zaw"].includes(type)) return "melee";
  return "rifle";
}

function applyPreset(preset) {
  const rows = (state.catalog?.manualMods || []).filter((mod) => modMatchesBuildWeapon(mod) && mod.selectable !== false);
  const findByName = (name) => rows.find((mod) => mod.nameEn === name || mod.nameZh === name)
    || rows.find((mod) => String(mod.nameEn || "").includes(name) || String(mod.nameZh || "").includes(name));
  let slot = 0;
  let filled = 0;
  const missing = [];
  for (const cardName of preset.cards) {
    const mod = findByName(cardName);
    if (!mod) { missing.push(cardName); continue; }
    while (slot < state.manualSlots.length && state.manualSlots[slot]) slot += 1;
    if (slot >= state.manualSlots.length) break;
    if (state.manualSlots.some((m) => m && m.path === mod.path)) continue;
    state.manualSlots[slot] = { ...mod, rank: mod.maxRank ?? 0 };
    slot += 1;
    filled += 1;
  }
  ensureCapacityFit();
  renderManualSlots();
  persistActiveBuildConfig();
  scheduleLiveManualSimulation();
  const notes = missing.length ? `（${missing.length} 张不在候选内）` : "";
  toast(filled ? `已按「${preset.label}」填入 ${filled} 张卡${notes}` : `没有匹配「${preset.label}」的可用 MOD${notes}`);
}

function renderManualModCategories() {
  const target = ui["manual-mod-categories"];
  if (!target) return;
  target.hidden = state.modPickerKind !== "normal";
  if (target.hidden) { target.replaceChildren(); return; }
  const rows = (state.catalog?.manualMods || []).filter((mod) => modMatchesBuildWeapon(mod));
  const counts = new Map([["all", rows.length]]);
  rows.forEach((mod) => counts.set(modCategory(mod), (counts.get(modCategory(mod)) || 0) + 1));
  if (state.manualModCategory !== "__riven__" && !counts.has(state.manualModCategory)) state.manualModCategory = "all";
  const nodes = [];
  // Preset quick-picks first (Riven-Mirror style fast-select).
  const presets = MOD_PRESETS[presetFamilyFor(state.buildWeapon)] || [];
  for (const preset of presets) {
    const button = create("button", "mod-preset-chip", `⚡ ${preset.label}`);
    button.type = "button";
    button.title = `按「${preset.label}」一键填充空槽`;
    button.addEventListener("click", () => applyPreset(preset));
    nodes.push(button);
  }
  // Riven tab: build/carry a Riven mod into the loadout.
  const rivenTab = create("button", state.manualModCategory === "__riven__" ? "is-active mod-riven-chip" : "mod-riven-chip", "◈ 紫卡");
  rivenTab.type = "button";
  rivenTab.title = "构建紫卡并放入槽位";
  rivenTab.addEventListener("click", () => { state.manualModCategory = "__riven__"; renderManualMods(); });
  nodes.push(rivenTab);
  if (nodes.length) nodes.push(create("span", "mod-category-divider"));
  for (const [key, label] of Object.entries(MOD_CATEGORY_LABELS)) {
    if (!counts.has(key) || counts.get(key) <= 0) continue;
    const button = create("button", key === state.manualModCategory ? "is-active" : "", `${label} ${counts.get(key)}`);
    button.type = "button";
    button.dataset.category = key;
    button.setAttribute("aria-pressed", String(key === state.manualModCategory));
    button.addEventListener("click", () => { state.manualModCategory = key; renderManualMods(); });
    nodes.push(button);
  }
  const sortButton = create("button", `mod-sort-toggle${state.modGainsSort ? " is-active" : ""}`, state.modGainsSort ? "↓ 收益排序" : "↕ 收益排序");
  sortButton.type = "button";
  sortButton.title = "按真实模拟收益降序排列候选";
  sortButton.addEventListener("click", () => {
    state.modGainsSort = !state.modGainsSort;
    renderManualMods();
  });
  nodes.push(sortButton);
  target.replaceChildren(...nodes);
}

function warframeModCategory(mod) {
  const kind = warframeModKind(mod);
  if (kind === "aura") return "aura";
  if (kind === "exilus") return "exilus";
  if (mod?.modSet) return "set";
  if (mod?.compatibleFrames?.length || mod?.compatibilityType === "frame-specific" || /\/Powersuits\//i.test(String(mod?.path || ""))) return "exclusive";
  return "normal";
}

function warframeCategoryMatches(mod, category) {
  if (!category || category === "all") return true;
  if (category === "aura" || category === "exilus") return warframeModKind(mod) === category;
  if (category === "set") return Boolean(mod?.modSet);
  if (category === "exclusive") return Boolean(mod?.compatibleFrames?.length || mod?.compatibilityType === "frame-specific" || /\/Powersuits\//i.test(String(mod?.path || "")));
  return !mod?.modSet && warframeModKind(mod) === "normal" && !warframeCategoryMatches(mod, "exclusive");
}

function dedupeWarframeMods(rows) {
  const best = new Map();
  for (const row of rows) {
    const key = [row.nameEn || row.nameZh || row.id, row.slotKind, (row.compatibleFrames || []).join(","), row.modSet || ""].join("|");
    const previous = best.get(key);
    if (!previous || Number(row.maxRank || 0) > Number(previous.maxRank || 0)) best.set(key, row);
  }
  return [...best.values()];
}

function customDamageSupported() {
  const options = state.catalog?.buildOptions || {};
  return options.customDamageModel === true
    || state.catalog?.capabilities?.customDamageModel === true
    || (Array.isArray(options.damageModels) && options.damageModels.includes("custom"));
}

function updateCustomDamageControls() {
  const select = ui["build-damage-model"];
  const option = select?.querySelector('option[value="custom"]');
  const supported = customDamageSupported();
  if (option) {
    option.disabled = !supported;
    option.title = supported ? "按自己填写的生命、护甲和护盾计算" : "当前版本不支持自定义防御";
  }
  const active = select?.value === "custom";
  if (ui["custom-defense-fields"]) ui["custom-defense-fields"].hidden = !active;
  if (ui["custom-defense-note"]) ui["custom-defense-note"].textContent = supported
    ? "按这里填写的数值计算，不使用敌人库的数据。"
    : "当前版本不支持自定义防御，已禁用。";
  if (active && !supported && select) select.value = "panel";

  // Keep defense pools and resistance types coherent for custom snapshots.
  [
    ["build-custom-armor", "build-custom-armor-type"],
    ["build-custom-shield", "build-custom-shield-type"],
  ].forEach(([poolId, typeId]) => {
    const pool = ui[poolId];
    const type = ui[typeId];
    if (!pool || !type) return;
    const hasPool = Number(pool.value || 0) > 0;
    const none = type.querySelector('option[value="RK_NONE"]');
    if (none) none.disabled = hasPool;
    if (!hasPool) type.value = "RK_NONE";
    else if (type.value === "RK_NONE") {
      const firstConcrete = [...type.options].find((option) => option.value !== "RK_NONE" && !option.disabled);
      if (firstConcrete) type.value = firstConcrete.value;
    }
    type.setCustomValidity(hasPool && type.value === "RK_NONE" ? "正数防御池必须选择具体类型" : "");
  });
}

function catalogRows(value, key) {
  if (Array.isArray(value)) return value;
  return Array.isArray(value?.[key]) ? value[key] : [];
}

function catalogIconAsset(record, kind = "") {
  const direct = record?.iconAsset || record?.art;
  if (direct) return direct;
  const raw = String(record?.icon || "");
  if (raw.startsWith("/assets/")) return raw;
  const basename = raw.split("/").filter(Boolean).pop();
  return kind === "arcane" && basename ? `/assets/arcanes/${basename}` : "";
}

function warframeShardAssets(record) {
  const explicitBase = String(record?.baseIconAsset || "");
  const explicitGlow = String(record?.glowIconAsset || "");
  if (explicitBase || explicitGlow) {
    return { base: explicitBase || explicitGlow, glow: record?.tau ? explicitGlow : "" };
  }
  const icon = catalogIconAsset(record) || record?.iconAsset || "";
  if (!icon) return { base: "", glow: "" };
  if (!record?.tau) return { base: icon, glow: "" };
  const base = icon.replace(/Mythic|Glow/gi, "");
  return { base, glow: icon };
}

function stanceRecords() {
  return catalogRows(state.catalog?.stances, "stances");
}

function utilityModRecords() {
  const records = new Map((state.catalog?.manualMods || []).map((mod) => [mod.path, mod]));
  return catalogRows(state.catalog?.utilityMods, "mods").map((mod) => {
    const joined = records.get(mod.path) || {};
    const asset = state.modAssets?.mods?.[mod.path] || {};
    const maxRank = Number(mod.maxRank ?? mod.rank ?? joined.maxRank ?? asset.maxRank ?? 0);
    const description = cleanOfficialText(mod.description || joined.description || "");
    const effectsZhByRank = Array.isArray(mod.effectsZhByRank) ? mod.effectsZhByRank.map((rank) => (Array.isArray(rank) ? rank.map(cleanOfficialText) : rank)) : mod.effectsZhByRank;
    // 卡面兜底：目录行 iconAsset 缺失（export-fixup 补丁卡）时用资源索引的
    // art（Prime 与普通版共用同一张官方卡面）。
    const iconAsset = mod.iconAsset || asset.art || joined.iconAsset || null;
    return { ...joined, ...mod, maxRank, rank: Number(mod.selectedRank ?? maxRank), description, effectsZhByRank, iconAsset, ...(iconAsset ? { art: iconAsset } : {}) };
  });
}

function exaltedWeaponRecords() {
  return catalogRows(state.catalog?.exaltedWeapons, "weapons");
}

function exaltedRecordForBuildWeapon() {
  const weapon = state.buildWeapon;
  if (!weapon) return null;
  const path = String(weapon.path || "");
  const names = new Set([weapon.nameEn, weapon.nameZh, weapon.nameInternal].filter(Boolean).map((name) => String(name).toLocaleLowerCase()));
  return exaltedWeaponRecords().find((record) => {
    const paths = [record.path, record.sourcePath, record.portablePath, ...(record.portablePaths || [])].filter(Boolean).map(String);
    const recordNames = [record.name, record.nameEn, record.nameZh].filter(Boolean).map((name) => String(name).toLocaleLowerCase());
    return paths.includes(path) || recordNames.some((name) => names.has(name));
  }) || null;
}

function isMeleeBuild(weapon = state.buildWeapon) {
  return ["melee", "zaw"].includes(weapon?.weaponType) || weapon?.slot === "melee";
}

function stanceMatchesBuildWeapon(stance) {
  if (!isMeleeBuild() || !stance?.path) return false;
  // Zaw 基体自身没有架势兼容标签：按当前装配的剑刃 + 握把推导武器类别匹配。
  const zawTag = isZawBase(state.buildWeapon) ? zawAssemblyStanceTag() : null;
  if (isZawBase(state.buildWeapon)) {
    return Boolean(zawTag) && String(stance.compatTag || "").toLocaleLowerCase() === zawTag.toLocaleLowerCase();
  }
  const allowed = state.buildWeapon?.specialSlots?.stance?.compatiblePaths;
  if (Array.isArray(allowed)) return allowed.includes(stance.path);
  const tag = String(stance.compatTag || "").toLocaleLowerCase();
  const tags = new Set((state.buildWeapon?.compatTags || []).map((item) => String(item).toLocaleLowerCase()));
  return Boolean(tag && tags.has(tag));
}

function utilityMatchesBuildWeapon(mod) {
  // 与后端 optimizer._mod_matches_weapon 同口径的兼容判定：先看家族
  // compatibility（基类 ancestry 匹配），再看 compatibilityTags /
  // incompatibilityTags。数据来自冻结目录行（utilityMods 已并入这些字段），
  // 避免「前端能选、后端报 exilus is not compatible」的断层。
  const compat = String(mod?.compatibility || "").trim();
  if (compat) {
    const ancestry = new Set([...(state.buildWeapon?.ancestry || []), state.buildWeapon?.path].filter(Boolean).map((p) => String(p).replace(/\/+$/, "").toLocaleLowerCase()));
    if (!ancestry.has(compat.replace(/\/+$/, "").toLocaleLowerCase())) return false;
  }
  const weaponTags = new Set((state.buildWeapon?.compatTags || []).map((tag) => String(tag).toLocaleLowerCase()));
  const required = (mod?.compatibilityTags || []).map((tag) => String(tag).toLocaleLowerCase());
  const blocked = (mod?.incompatibilityTags || []).map((tag) => String(tag).toLocaleLowerCase());
  if (required.length && !required.some((tag) => weaponTags.has(tag))) return false;
  if (blocked.some((tag) => weaponTags.has(tag))) return false;
  const slot = String(mod?.slotKind || "").toLocaleLowerCase();
  const weaponSlot = String(state.buildWeapon?.slot || "").toLocaleLowerCase();
  if (slot === "melee") return isMeleeBuild();
  if (slot === "secondary") return weaponSlot === "secondary" || state.buildWeapon?.weaponType === "pistol";
  if (slot === "primary") {
    if (!(weaponSlot === "primary" || ["rifle", "shotgun", "archgun"].includes(state.buildWeapon?.weaponType))) return false;
    // 主武器再按家族细分：霰弹枪家族只能上霰弹枪，步枪家族只能上步枪类
    // （与后端 optimizer._mod_matches_weapon 一致，套装卡两家通用）。
    const family = String(mod?.path || "").split("/")[4] || "";
    const weaponType = String(state.buildWeapon?.weaponType || "").toLocaleLowerCase();
    if (family === "Shotgun") return weaponType === "shotgun";
    if (family === "Rifle") return weaponType === "rifle";
    return true;
  }
  return false;
}

function hydrateRankedSelection(value, records, slotKind = "weapon") {
  const path = typeof value === "string" ? value : value?.path;
  if (!path) return null;
  const record = records.find((item) => item.path === path) || { path };
  const override = value && typeof value === "object" ? value : {};
  const maxRank = Number(override.maxRank ?? record.maxRank ?? record.rank ?? override.rank ?? 0);
  const rank = clamp(Number(override.rank ?? record.rank ?? maxRank), 0, maxRank);
  return {
    ...record,
    catalogDrain: record.drain,
    ...override,
    path: record.path || path,
    rank,
    maxRank,
    slotKind: override.slotKind || record.slotKind || slotKind,
  };
}

function resetSpecialSelections() {
  const stanceSlot = state.buildWeapon?.specialSlots?.stance;
  const exalted = exaltedRecordForBuildWeapon();
  const defaultPath = stanceSlot?.path || exalted?.builtInStancePath || exalted?.builtInStance || null;
  const defaultStance = defaultPath
    ? stanceRecords().find((stance) => stance.path === defaultPath)
    : stanceRecords().find(stanceMatchesBuildWeapon);
  state.stanceLocked = Boolean(stanceSlot?.locked || stanceSlot?.builtIn || exalted?.noExternalStance);
  const defaultSelection = isMeleeBuild() && (defaultStance || defaultPath)
    ? {
      ...(defaultStance || {}),
      ...stanceSlot,
      path: defaultPath || defaultStance.path,
      nameZh: defaultStance?.nameZh || stanceSlot?.nameZh || exalted?.builtInStanceName || exalted?.nameZh,
      nameEn: defaultStance?.nameEn || stanceSlot?.nameEn || exalted?.builtInStanceName || exalted?.nameEn || exalted?.name,
      builtIn: state.stanceLocked,
    }
    : null;
  state.stanceSelection = stanceSelectionWithSlot(defaultSelection);
  state.exilusSelection = null;
  state.weaponArcane = null;
  state.weaponArcane2 = null;
  state.frameArcanes = [null, null];
  syncArcaneSelections();
}

function restoreSpecialSelections(config) {
  resetSpecialSelections();
  if (!state.stanceLocked && config?.stancePath) {
    const stance = stanceRecords().find((item) => item.path === config.stancePath);
  if (stance && stanceMatchesBuildWeapon(stance)) state.stanceSelection = stanceSelectionWithSlot(stance);
  }
  state.exilusSelection = hydrateRankedSelection(config?.exilus, utilityModRecords(), state.buildWeapon?.specialSlots?.exilus?.kind || "weapon");

  const hasNewArcanes = Object.hasOwn(config || {}, "weaponArcane") || Array.isArray(config?.frameArcanes);
  if (hasNewArcanes) {
    state.weaponArcane = hydrateRankedSelection(config.weaponArcane, arcaneRecords(), "weapon");
    if (weaponArcaneSlotCount() > 1) state.weaponArcane2 = hydrateRankedSelection(config.weaponArcane2, arcaneRecords(), "weapon");
    const frames = (config.frameArcanes || []).slice(0, 2).map((item) => hydrateRankedSelection(item, arcaneRecords(), "warframe"));
    state.frameArcanes = [frames[0] || null, frames[1] || null];
  } else {
    const legacy = normalizeArcaneSelections(config?.arcanes || config?.arcaneSelections);
    state.weaponArcane = legacy.find((item) => item.slotKind !== "warframe") || null;
    if (weaponArcaneSlotCount() > 1) state.weaponArcane2 = legacy.filter((item) => item.slotKind !== "warframe")[1] || null;
    const frames = legacy.filter((item) => item.slotKind === "warframe").slice(0, 2);
    state.frameArcanes = [frames[0] || null, frames[1] || null];
  }
  syncArcaneSelections();
}

function arcaneRecords() {
  return Array.isArray(state.catalog?.arcanes) ? state.catalog.arcanes : [];
}

// 战甲赋能只在它的武器效果能落到当前武器上时可选：精确只给次要武器，
// 狂怒只给近战，蜘蛛只给主/副武器（weaponScopes 由后端按效果的 validType 给出）。
function frameArcaneAppliesToWeapon(arcane, weapon = state.buildWeapon) {
  if (!weapon) return true;
  const scopes = Array.isArray(arcane?.weaponScopes) ? arcane.weaponScopes : null;
  if (!scopes) return true;
  const ancestry = new Set([weapon.path, ...(weapon.ancestry || [])].filter(Boolean).map((p) => String(p).replace(/\/$/, "")));
  const melee = ["melee", "zaw"].includes(weapon.weaponType);
  const archgunShared = (type) => weapon.weaponType === "archgun"
    && ["/Lotus/Weapons/Tenno/LotusLongGun", "/Lotus/Weapons/Tenno/Pistol/LotusPistol"].includes(type);
  return scopes.some((scope) => (!scope.meleeOnly || melee)
    && (!scope.validType || ancestry.has(scope.validType) || archgunShared(scope.validType)));
}

function arcaneMatchesBuildWeapon(arcane) {
  if (arcane?.slotKind === "warframe") return frameArcaneAppliesToWeapon(arcane);
  const weapon = state.buildWeapon;
  if (!weapon) return false;
  const compatibility = String(arcane?.compatibility || "").replace(/\\/g, "/").replace(/\/$/, "").toLowerCase();
  const ancestry = new Set([weapon.path, ...(weapon.ancestry || [])].filter(Boolean).map((p) => String(p).replace(/\/$/, "").toLowerCase()));
  if (arcane?.equipmentType === "Kitgun Arcane" && weapon.weaponType !== "kitgun" && ![...ancestry].some((p) => p.includes("modular"))) return false;
  const archgunShared = weapon.weaponType === "archgun" && [
    "/lotus/weapons/tenno/lotuslonggun", "/lotus/weapons/tenno/pistol/lotuspistol",
  ].includes(compatibility);
  if (compatibility && !ancestry.has(compatibility) && !archgunShared) return false;
  const tags = new Set((weapon.compatTags || []).map((tag) => String(tag).toLowerCase()));
  const required = arcane.compatibilityTags || [];
  const blocked = arcane.incompatibilityTags || [];
  return (!required.length || required.some((tag) => tags.has(String(tag).toLowerCase())))
    && !blocked.some((tag) => tags.has(String(tag).toLowerCase()));
}

// ── Arcane picker (modal list + search + hover preview) ───────────────────
function arcanePickerRows(kind) {
  const query = String(ui["arcane-picker-search"]?.value || "").trim().toLocaleLowerCase();
  return arcaneRecords().filter((arcane) => {
    const matchesKind = kind === "warframe" ? arcane.slotKind === "warframe" : arcane.slotKind !== "warframe";
    if (!matchesKind || !arcaneMatchesBuildWeapon(arcane)) return false;
    if (!query) return true;
    return [arcane.nameZh, arcane.nameEn, arcane.path].filter(Boolean).join(" ").toLocaleLowerCase().includes(query);
  });
}

function arcaneEffectHint(arcane) {
  if (arcane.eventModel === "enervate-joint-probability") return "命中叠暴击 · 强暴击计数重置 · 已计入事件计算";
  if (arcane.descriptionSource && arcane.effectsZhByRank?.length) {
    const typeLabels = { "Bow Arcane": "弓箭专用", "Shotgun Arcane": "霰弹枪专用", "Kitgun Arcane": "组合枪专用", "Primary Arcane": "主要武器", "Secondary Arcane": "次要武器", "Melee Arcane": "近战武器", "Warframe Arcane": "战甲赋能" };
    return typeLabels[arcane.equipmentType] || arcane.trigger?.conditionZh || "效果与触发条件见下方";
  }
  const trigger = arcane.trigger || {};
  const bits = [];
  if (trigger.conditionZh) bits.push(damageTokenText(trigger.conditionZh));
  if (trigger.chance != null) bits.push(`${Math.round(Number(trigger.chance) * 100)}% 触发`);
  if (trigger.maxStacks != null) bits.push(`${trigger.maxStacks} 层`);
  if (trigger.duration != null) bits.push(`${Number(trigger.duration).toFixed(1)}s`);
  if (arcane.runtime) bits.push("运行时脚本");
  return bits.join(" · ") || "静态效果";
}

function warframeEffectValue(effect, rank) {
  const values = effect?.valuesByRank || effect?.levelValues || effect?.values;
  if (Array.isArray(values) && values.length) return Number(values[Math.min(rank, values.length - 1)]);
  const base = finite(effect?.valueBase ?? effect?.baseValue) ?? 0;
  const perRank = finite(effect?.valuePerRank ?? effect?.value) ?? 0;
  return base + perRank * rank;
}

function warframeArcaneHint(arcane) {
  const rank = clamp(Number(arcane?.rank ?? arcane?.maxRank ?? 0), 0, Number(arcane?.maxRank ?? arcane?.rank ?? 0));
  const effects = [...(Array.isArray(arcane?.effects) ? arcane.effects : [])];
  if (state.warframeBuild.applyConditionals) {
    for (const conditional of Array.isArray(arcane?.conditionalEffects) ? arcane.conditionalEffects : []) effects.push(...(conditional?.effects || []));
  }
  const bits = effects.slice(0, 3).flatMap((effect) => {
    const value = warframeEffectValue(effect, rank);
    const label = effect.labelZh || effect.label || effectLabel(effect);
    if (!label || !Number.isFinite(value)) return [];
    const percent = effect.unit !== "flat" && Math.abs(value) <= 10;
    return [`${label} ${value >= 0 ? "+" : ""}${percent ? `${(value * 100).toFixed(1).replace(/\.0$/, "")}%` : value.toFixed(2).replace(/\.00$/, "")}`];
  });
  return bits.join(" · ") || arcaneEffectHint(arcane);
}

// 赋能描述：等级变化时优先取逐级效果行（effectsZhByRank[rank]），
// 让描述与解算使用的等级同步；无逐级数据时退回目录静态描述。
function arcaneDescription(arcane) {
  const rank = arcane?.rank;
  const byRank = Array.isArray(arcane?.effectsZhByRank) ? arcane.effectsZhByRank : [];
  if (Number.isInteger(Number(rank)) && byRank.length) {
    const line = byRank[Math.min(Math.max(Number(rank), 0), byRank.length - 1)];
    const text = Array.isArray(line) ? line.join("\n") : String(line || "");
    const cleaned = cleanOfficialText(text).split(String.fromCharCode(92) + "n").join(String.fromCharCode(10));
    if (cleaned) return cleaned;
  }
  return damageTokenText(arcane?.description || arcane?.effect || arcaneEffectHint(arcane));
}

function renderArcanePicker() {
  const list = ui["arcane-picker-list"];
  if (!list) return;
  const kind = state.arcanePickerKind === "warframe" ? "warframe" : "weapon";
  const rows = arcanePickerRows(kind);
  ui["arcane-picker-sub"].textContent = kind === "warframe" ? `战甲赋能 · ${rows.length} 个` : `武器赋能 · ${rows.length} 个`;
  list.replaceChildren(...(rows.length ? rows.map((arcane) => {
    const option = create("button", "arcane-option");
    option.type = "button";
    option.setAttribute("role", "option");
    if (state.arcaneSelections.some((item) => item.path === arcane.path)) option.classList.add("is-selected");
    const copy = create("span", "arcane-option-copy");
    copy.append(create("strong", "", arcane.nameZh || arcane.nameEn || arcane.path));
    copy.append(create("small", "", arcaneEffectHint(arcane)));
    const description = arcaneDescription(arcane);
    if (description) copy.append(create("em", "arcane-option-effect", description));
    option.append(copy);
    const iconAsset = catalogIconAsset(arcane, "arcane");
    if (iconAsset) {
      const icon = imageNode(iconAsset, "arcane-option-icon", "", "lazy");
      icon.addEventListener("error", () => icon.remove(), { once: true });
      option.prepend(icon);
    }
    option.title = `${arcane.nameZh || arcane.nameEn} · ${description ? `${description} · ` : ""}${arcaneEffectHint(arcane)}`;
    option.addEventListener("click", () => {
      state.arcanePickerTarget = arcane.path;
      closeArcanePicker();
      addArcaneSelection(arcane.path);
    });
    return option;
  }) : [create("p", "empty-copy", "没有符合条件的赋能")]));
}

function openArcanePicker(kind, slotIndex = 0) {
  if (!ui["arcane-picker"]) return;
  state.arcanePickerKind = kind;
  state.arcanePickerSlot = clamp(Number(slotIndex) || 0, 0, kind === "warframe" ? 1 : weaponArcaneSlotCount() - 1);
  ui["arcane-picker"].hidden = false;
  ui["mod-picker-scrim"].hidden = false;
  document.body.classList.add("is-modal-open");
  if (ui["arcane-picker-search"]) ui["arcane-picker-search"].value = "";
  renderArcanePicker();
  ui["arcane-picker-search"]?.focus();
}

function closeArcanePicker() {
  if (!ui["arcane-picker"] || ui["arcane-picker"].hidden) return;
  ui["arcane-picker"].hidden = true;
  if (ui["mod-picker"].hidden && ui["weapon-picker"].hidden) {
    ui["mod-picker-scrim"].hidden = true;
    document.body.classList.remove("is-modal-open");
  }
}

function fillArcanes() { renderArcanePicker(); }

const WEAPON_PICKER_CATEGORIES = {
  all: "全部", rifle: "步枪", shotgun: "霰弹枪", pistol: "手枪", melee: "近战", zaw: "组合近战", kitgun: "组合枪", archgun: "空战武器(地面)", companion: "同伴武器", exalted: "显赫武器",
};

// 显赫武器单列一类，不混进它基类（近战 / 手枪 / 步枪）的分类里。
function weaponPickerCategoryOf(weapon) {
  return weapon.exalted ? "exalted" : weapon.weaponType;
}

function weaponPickerRows() {
  const rows = (state.catalog?.weapons || []).filter((weapon) => !weapon.hiddenFromBuildPicker);
  const query = String(ui["weapon-picker-search"]?.value || "").trim().toLocaleLowerCase();
  const isKitgun = (weapon) => String(weapon.nameEn || "").trim() === "Kitgun";
  const isZaw = (weapon) => isZawBase(weapon);
  const kitgunPrimes = rows.filter((w) => isKitgun(w) && w.slot === "primary");
  const kitgunSecondaries = rows.filter((w) => isKitgun(w) && w.slot === "secondary");
  const zaws = rows.filter((w) => isZaw(w));
  const merged = new Map();
  if (kitgunPrimes.length) merged.set("kitgun-primary", kitgunPrimes.find((w) => w.buildAvailable !== false) || kitgunPrimes[0]);
  if (kitgunSecondaries.length) merged.set("kitgun-secondary", kitgunSecondaries.find((w) => w.buildAvailable !== false) || kitgunSecondaries[0]);
  if (zaws.length) merged.set("zaw", zaws.find((w) => w.buildAvailable !== false) || zaws[0]);
  const assemblyCategory = state.weaponPickerCategory;
  const showAssembly = (entryKey) => {
    if (assemblyCategory === "all") return true;
    if (assemblyCategory === "kitgun") return entryKey.startsWith("kitgun-");
    if (assemblyCategory === "zaw") return entryKey === "zaw";
    return false;
  };
  return rows.filter((weapon) => {
    if (isKitgun(weapon) || isZaw(weapon)) return false;
    const haystack = [weapon.nameZh, weapon.nameEn, weapon.nameInternal, weapon.path].filter(Boolean).join(" ").toLocaleLowerCase();
    return (!query || haystack.includes(query)) && (assemblyCategory === "all" || weaponPickerCategoryOf(weapon) === assemblyCategory);
  }).concat(
    [...merged.entries()].filter(([key, weapon]) => {
      const haystack = [weapon.nameZh, weapon.nameEn, weapon.nameInternal, weapon.path, "组合枪", "组合近战", "kitgun", "zaw", "装配"].filter(Boolean).join(" ").toLocaleLowerCase();
      return showAssembly(key) && (!query || haystack.includes(query));
    }).map(([, weapon]) => weapon),
  );
}

// 武器 StoreIcon 匹配（frontend/assets/weapons/）。
// 候选序列：内部 basename 优先（资产文件按内部名保存——信条/赤毒/科达
// 变体与 Infested/Tenno 专题武器的 nameEn 与内部名完全不同，旧实现只用
// nameEn 造成大面积缺图、「Prime 有图普通版没图」的观感），nameEn 变体
// 兜底；全部候选失败时 img onerror 降级到类型色块占位。
function weaponIconCandidates(weapon) {
  const internal = String(weapon.path || "").split("/").pop() || "";
  const name = String(weapon.nameEn || "");
  const raw = [];
  if (internal) raw.push(internal);
  if (name) {
    raw.push(
      name.replace(/ /g, ""),
      name.replace(/ /g, "").replace(/'/g, ""),
      name.replace(/ /g, "").replace(/-/g, ""),
    );
  }
  const seen = new Set();
  const out = [];
  for (const pattern of raw) {
    if (!pattern) continue;
    // 原样优先（资产命名不完全统一：MK1Bo.png 用大写 MK1，Mk1Strun 用 Mk1），
    // MK1→Mk1 改写作为追加候选兜底。
    for (const variant of [pattern, pattern.replace(/^MK1(?=[A-Z])/, "Mk1")]) {
      if (!variant || seen.has(variant)) continue;
      seen.add(variant);
      out.push(`${variant}.png`);
    }
  }
  return out;
}

function renderWeaponPicker() {
  const list = ui["weapon-picker-list"];
  const cats = ui["weapon-picker-categories"];
  if (!list || !cats) return;
  const rows = (state.catalog?.weapons || []).filter((weapon) => !weapon.hiddenFromBuildPicker);
  const isKitgun = (weapon) => String(weapon.nameEn || "").trim() === "Kitgun";
  const isZaw = (weapon) => isZawBase(weapon);
  const regularRows = rows.filter((w) => !isKitgun(w) && !isZaw(w));
  const kitgunEntries = new Set(rows.filter(isKitgun).map((w) => w.slot));
  const zawEntries = rows.some(isZaw) ? 1 : 0;
  const assemblyCount = kitgunEntries.size + zawEntries;
  const counts = new Map([["all", regularRows.length + assemblyCount]]);
  rows.forEach((weapon) => {
    if (isKitgun(weapon) || isZaw(weapon)) return;
    counts.set(weaponPickerCategoryOf(weapon), (counts.get(weaponPickerCategoryOf(weapon)) || 0) + 1);
  });
  if (kitgunEntries.size) counts.set("kitgun", kitgunEntries.size);
  if (zawEntries) counts.set("zaw", zawEntries);
  if (!counts.has(state.weaponPickerCategory)) state.weaponPickerCategory = "all";
  cats.replaceChildren(...Object.entries(WEAPON_PICKER_CATEGORIES).filter(([key]) => counts.has(key)).map(([key, label]) => {
    const button = create("button", key === state.weaponPickerCategory ? "is-active" : "", `${label} ${counts.get(key)}`);
    button.type = "button";
    button.addEventListener("click", () => { state.weaponPickerCategory = key; renderWeaponPicker(); });
    return button;
  }));
  const filtered = weaponPickerRows().slice(0, 120);
  const forAnalysis = state.weaponPickerTarget === "analysis";
  ui["weapon-picker-sub"].textContent = `${filtered.length} / ${counts.get("all")} 把武器`;
  list.replaceChildren(...(filtered.length ? filtered.map((weapon) => {
    const option = create("button", "weapon-option");
    option.type = "button";
    option.setAttribute("role", "option");
    const selectedWeapon = forAnalysis ? state.weapon : state.buildWeapon;
    if (selectedWeapon?.path === weapon.path) option.classList.add("is-selected");
    const copy = create("span", "weapon-option-copy");
    const isKitgun = String(weapon.nameEn || "").trim() === "Kitgun";
    const isZaw = isZawBase(weapon);
    const isAssembly = isKitgun || isZaw;
    let kitgunDispo = null;
    if (isAssembly && state.kitgunParts?.chamber) {
      const partList = isZaw ? state.catalog?.zawParts?.strikes : state.catalog?.kitgunParts?.chambers;
      const part = (partList || []).find((c) => c.path === state.kitgunParts.chamber);
      kitgunDispo = isZaw ? (part?.disposition ?? null) : (weapon.slot === "primary" ? (part?.primaryDisposition ?? part?.disposition ?? null) : (part?.disposition ?? null));
    }
    // 武器缩略图（StoreIcons ~80% 命中率；miss 时 img onerror 降级到类型色块）。
    const thumb = create("div", "weapon-thumb");
    const typeColor = {
      rifle: "#5b8dc9", shotgun: "#c05555", pistol: "#7db85b", melee: "#c9b05b",
      bow: "#8d6fc9", zaw: "#c9b05b",
    }[weapon.weaponType] || "rgba(148,163,184,.3)";
    const iconCandidates = weaponIconCandidates(weapon);
    if (iconCandidates.length) {
      const img = create("img", "");
      img.alt = "";
      img.loading = "lazy";
      let candidateIndex = 0;
      const tryNext = () => {
        if (candidateIndex >= iconCandidates.length) {
          img.remove();
          const placeholder = create("div", "weapon-thumb-placeholder");
          placeholder.style.background = typeColor;
          thumb.append(placeholder);
          return;
        }
        img.src = `/assets/weapons/${iconCandidates[candidateIndex++]}`;
      };
      img.addEventListener("error", tryNext);
      tryNext();
      thumb.append(img);
    } else {
      const placeholder = create("div", "weapon-thumb-placeholder");
      placeholder.style.background = typeColor;
      thumb.append(placeholder);
    }
    copy.append(
      create("strong", "", isAssembly ? (isZaw ? "组合近战（Zaw · 装配）" : `组合枪（${weapon.slot === "primary" ? "主武器" : "副武器"} · 装配）`) : weaponName(weapon)),
      create("small", "", isAssembly
        ? `${isZaw ? "剑刃×握把×配重" : "腔体×握把×装填器"} · 倾向 ${kitgunDispo ? formatDisposition(kitgunDispo) : isZaw ? "跟剑刃" : "跟腔体"}${kitgunDispo ? " " + dispositionDots(kitgunDispo) : ""}`
        : weaponTypeCaption(weapon, true)),
    );
    option.append(thumb, copy);
    if (weapon.buildAvailable === false && !isAssembly && !forAnalysis) {
      copy.append(create("em", "", `不可用 · ${issueLabel(weapon.buildIssue || weapon.issue)}`));
      option.disabled = true;
    }
    if (forAnalysis && !isAssembly && weapon.analysisAvailable === false) {
      copy.append(create("em", "", `不可分析 · ${issueLabel(weapon.analysisIssue || weapon.issue)}`));
      option.disabled = true;
    }
    if (isAssembly) {
      copy.append(create("em", "", isZaw ? "选择剑刃后即可解算" : "组装腔体后即可解算"));
    }
    option.addEventListener("click", () => {
      closeWeaponPicker();
      if (forAnalysis) {
        if (isAssembly) selectAnalysisAssembly(weapon);
        else selectWeapon(weapon);
        return;
      }
      ui["build-weapon"].value = buildWeaponOptionLabel(weapon);
      state.assemblyFor = "build";
      selectBuildWeapon(weapon);
      if (isAssembly) openKitgunAssembly(weapon);
    });
    return option;
  }) : [create("p", "empty-copy", "没有符合条件的武器")]));
}

function placeAssemblyPanel(context) {
  const panel = document.getElementById("kitgun-assembly");
  const host = document.getElementById(
    context === "analysis" ? "analysis-assembly-slot" : "build-assembly-slot"
  );
  if (panel && host && panel.parentElement !== host) host.append(panel);
}

function openKitgunAssembly(baseWeapon) {
  // 装配面板在分析页与配装页之间共享一个实例，按发起方迁移挂载点。
  placeAssemblyPanel(state.assemblyFor);
  state.kitgunBase = baseWeapon;
  state.kitgunParts = { chamber: null, grip: null, loader: null };
  renderKitgunAssembly();
}

function selectAnalysisAssembly(weapon) {
  // 分析页选择组合枪/组合近战基体：进入装配流程，倾向跟随腔体/剑刃。
  state.assemblyFor = "analysis";
  const zaw = isZawBase(weapon);
  state.weapon = { ...weapon, disposition: null };
  ui.weapon.value = zaw ? "组合近战（Zaw · 装配）" : `组合枪（${weapon.slot === "primary" ? "主武器" : "副武器"} · 装配）`;
  ui["weapon-caption"].textContent = "完成装配后按腔体/剑刃倾向解算词条范围";
  ui["disposition-value"].textContent = "--";
  ui["disposition-dots"].textContent = "○○○○○";
  ui["weapon-issue"].hidden = true;
  openKitgunAssembly(weapon);
  refreshRanges(false);
  updateCardPreview();
  updateAnalyzeAvailability();
  clearResult();
}

function assemblyChamberDisposition() {
  // 组合武器的紫卡倾向：组合枪跟腔体（主手用 primaryDisposition，缺失时回落
  // 副手倾向），组合近战跟剑刃。
  const zaw = isZawBase(state.kitgunBase);
  const parts = zaw ? (state.catalog?.zawParts || {}) : (state.catalog?.kitgunParts || {});
  const list = zaw ? parts.strikes : parts.chambers;
  const chosen = (list || []).find((part) => part.path === state.kitgunParts?.chamber);
  if (!chosen) return null;
  if (zaw) return chosen.disposition ?? null;
  return state.kitgunBase?.slot === "primary"
    ? (chosen.primaryDisposition ?? chosen.disposition ?? null)
    : (chosen.disposition ?? null);
}

function analysisAssemblyDisposition() {
  // 分析页与配装页同口径：倾向跟随当前装配的腔体/剑刃。
  return assemblyChamberDisposition();
}

function syncAnalysisAssembly() {
  if (state.assemblyFor !== "analysis" || !state.weapon) return;
  refreshAnalysisMeleeRoute();
  const ready = assemblyWeaponReady();
  const disposition = analysisAssemblyDisposition();
  state.weapon = { ...state.weapon, disposition: ready ? disposition : null };
  ui["disposition-value"].textContent = ready ? formatDisposition(disposition) : "--";
  ui["disposition-dots"].textContent = ready ? dispositionDots(disposition) : "○○○○○";
  ui["weapon-caption"].textContent = ready
    ? `${TYPE_LABELS[state.weapon.weaponType] || state.weapon.weaponType} · 装配完成 · 倾向随腔体/剑刃`
    : "完成装配后按腔体/剑刃倾向解算词条范围";
  refreshRanges(false);
  updateCardPreview();
  updateAnalyzeAvailability();
}

function isZawBase(weapon) {
  return weapon?.weaponType === "zaw" || (weapon?.slot === "melee" && String(weapon.nameEn || "").trim() === "Zaw");
}

function updateAssemblyIssueBanner() {
  const weapon = state.buildWeapon;
  if (!weapon) return;
  const isAssembly = String(weapon.nameEn || "").trim() === "Kitgun" || isZawBase(weapon);
  if (!isAssembly) return;
  const ready = assemblyWeaponReady();
  const banner = ui["build-weapon-issue"];
  const text = ui["build-weapon-issue-text"];
  if (!banner || !text) return;
  if (ready) {
    banner.hidden = true;
    text.textContent = "";
  } else {
    banner.hidden = false;
    text.textContent = isZawBase(weapon)
      ? "组合近战需要先装配剑刃 / 握把 / 配重（见上方装配面板）"
      : "组合枪需要先装配腔体 / 握把 / 装填器（见上方装配面板）";
  }
}

// Zaw 剑刃导出单手/双手两种武器类别，类别决定可用架势标签，
// 与普通近战武器 compatTags 里的 *_STANCE 口径一致。
const ZAW_CLASS_STANCE_TAGS = {
  Dagger: "DAGGERS_STANCE",
  Hammer: "HAMMERS_STANCE",
  "Heavy Blade": "HEAVY_BLADE_STANCE",
  Machete: "MACHETES_STANCE",
  Nikana: "NIKANAS_STANCE",
  Polearm: "POLEARMS_STANCE",
  Rapier: "RAPIER_STANCE",
  Scythe: "SCYTHES_STANCE",
  Staff: "STAVES_STANCE",
  Sword: "SWORDS_STANCE",
};

function zawAssemblyStanceTag() {
  // 由当前装配的剑刃 + 握把推导武器类别对应的架势标签；未选齐时返回 null。
  if (!isZawBase(state.kitgunBase)) return null;
  const strikes = state.catalog?.zawParts?.strikes || [];
  const grips = state.catalog?.zawParts?.grips || [];
  const strike = strikes.find((item) => item.path === state.kitgunParts?.chamber);
  const grip = grips.find((item) => item.path === state.kitgunParts?.grip);
  if (!strike?.path || !grip?.path) return null;
  const handed = String(grip.handed || "two") === "one" ? "one" : "two";
  const weaponClass = String((handed === "two" ? strike.twoHanded : strike.oneHanded) || "Sword");
  return ZAW_CLASS_STANCE_TAGS[weaponClass] || null;
}

function syncBuildAssemblyDisposition() {
  // 配装页的倾向读数跟随装配部件；仅在装配面板归属配装页且基体就是
  // 当前配装武器时写回，避免分析页装配串改配装页状态。
  const weapon = state.buildWeapon;
  if (!weapon) return;
  const isAssembly = String(weapon.nameEn || "").trim() === "Kitgun" || isZawBase(weapon);
  if (!isAssembly || state.assemblyFor !== "build" || state.kitgunBase?.path !== weapon.path) return;
  const ready = assemblyWeaponReady();
  const disposition = ready ? assemblyChamberDisposition() : null;
  state.buildWeapon = { ...weapon, disposition: ready ? disposition : null };
  ui["build-disposition"].textContent = ready ? formatDisposition(disposition) : "--";
  ui["build-disposition-dots"].textContent = ready ? dispositionDots(disposition) : "○○○○○";
}

function syncZawAssemblyStance() {
  refreshAnalysisMeleeRoute();
  refreshMeleeRouteOptions(document.getElementById("build-melee-route-select"), state.buildWeapon, "build");
  // Zaw 部件改变武器类别后，当前架势可能不再兼容：兼容则保留，否则改选
  // 新类别的默认架势（与 resetSpecialSelections 同口径）。
  if (!isZawBase(state.buildWeapon) || state.assemblyFor !== "build") return;
  if (state.stanceLocked) return;
  if (state.stanceSelection && stanceMatchesBuildWeapon(state.stanceSelection)) {
    refreshStanceSelection();
  } else {
    const fallback = stanceRecords().find(stanceMatchesBuildWeapon) || null;
    state.stanceSelection = stanceSelectionWithSlot(fallback);
  }
  renderSpecialSlots();
}

function renderKitgunAssembly() {
  const panel = document.getElementById("kitgun-assembly");
  if (!panel) return;
  const base = state.kitgunBase;
  if (!base) { panel.hidden = true; return; }
  const zaw = isZawBase(base);
  const parts = zaw ? (state.catalog?.zawParts || {}) : (state.catalog?.kitgunParts || {});
  panel.hidden = false;
  if (ui["kitgun-assembly-title"]) ui["kitgun-assembly-title"].textContent = zaw ? "组合近战装配（Zaw）" : "组合枪装配";
  const slotFilter = base.slot === "primary" ? "primary" : "secondary";
  let groups;
  if (zaw) {
    groups = [
      { key: "chamber", label: "剑刃 Strike", rows: parts.strikes || [] },
      { key: "grip", label: "握把 Grip", rows: parts.grips || [] },
      { key: "loader", label: "配重 Link", rows: parts.links || [] },
    ];
  } else {
    const grips = (parts.grips || []).filter((g) => g.slot === slotFilter);
    const chambers = (parts.chambers || []).filter((c) => {
      if (slotFilter === "primary") return Number(c.primaryModes || 0) > 0;
      return Number(c.secondaryModes || 0) > 0;
    });
    groups = [
      { key: "chamber", label: "腔体 Chamber", rows: chambers },
      { key: "grip", label: "握把 Grip", rows: grips },
      { key: "loader", label: "装填器 Loader", rows: parts.loaders || [] },
    ];
  }
  const body = panel.querySelector(".kitgun-assembly-body");
  const nodes = groups.map((group) => {
    const section = create("div", "kitgun-part-group");
    section.append(create("h4", "", group.label));
    (group.rows.length ? group.rows : [{ path: null, nameZh: "无可用部件" }]).forEach((part) => {
      const chip = create("button", `kitgun-part-chip${state.kitgunParts?.[group.key] === part.path ? " is-active" : ""}`);
      chip.type = "button";
      chip.textContent = part.nameZh || part.nameEn || "—";
      chip.disabled = !part.path;
      chip.title = zaw ? zawPartHint(part, group.key) : kitgunPartHint(part, group.key, base.slot);
      chip.addEventListener("mouseenter", () => showKitgunPartPreview(part, group.key, chip, base.slot, zaw));
      chip.addEventListener("mouseleave", hideKitgunPartPreview);
      chip.addEventListener("click", () => {
        state.kitgunParts[group.key] = part.path;
        renderKitgunAssembly();
        updateAssemblyIssueBanner();
        if (state.kitgunParts.chamber && state.kitgunParts.grip && state.kitgunParts.loader) {
          if (state.assemblyFor === "analysis") {
            // 分析页装配：只更新词条范围/倾向，不写配装配置、不触发配装模拟
            syncAnalysisAssembly();
          } else {
            syncZawAssemblyStance();
            persistActiveBuildConfig();
            scheduleLiveManualSimulation();
          }
        }
      });
      section.append(chip);
    });
    return section;
  });
  body.replaceChildren(...nodes);
  const ready = state.kitgunParts?.chamber && state.kitgunParts?.grip && state.kitgunParts?.loader;
  const summary = panel.querySelector(".kitgun-assembly-summary");
  if (summary) {
    const name = (list2, p) => (list2 || []).find((x) => x.path === p)?.nameZh || "";
    if (zaw) {
      const strike = (parts.strikes || []).find((c) => c.path === state.kitgunParts?.chamber);
      const dispo = strike?.disposition;
      summary.textContent = ready
        ? `已装配：${name(parts.strikes, state.kitgunParts.chamber)} + ${name(parts.grips, state.kitgunParts.grip)} + ${name(parts.links, state.kitgunParts.loader)}${dispo ? ` · 紫卡倾向 ${formatDisposition(dispo)}` : ""}`
        : `选择剑刃 / 握把 / 配重各一件完成组装${dispo ? ` · 当前剑刃倾向 ${formatDisposition(dispo)}` : ""}`;
    } else {
      const chamber = (parts.chambers || []).find((c) => c.path === state.kitgunParts?.chamber);
      const dispo = base.slot === "primary" ? (chamber?.primaryDisposition ?? chamber?.disposition) : chamber?.disposition;
      summary.textContent = ready
        ? `已装配：${name(parts.chambers, state.kitgunParts.chamber)} + ${name(parts.grips, state.kitgunParts.grip)} + ${name(parts.loaders, state.kitgunParts.loader)}${dispo ? ` · 紫卡倾向 ${formatDisposition(dispo)}` : ""}`
        : `选择腔体 / 握把 / 装填器各一件完成组装${dispo ? ` · 当前腔体倾向 ${formatDisposition(dispo)}` : ""}`;
    }
  }
  syncBuildAssemblyDisposition();
}

function zawPartHint(part, kind) {
  if (!part?.path) return "";
  const bits = [];
  if (kind === "chamber") {
    if (part.damage?.total) bits.push(`伤害 ${part.damage.total}`);
    if (part.critChance != null) bits.push(`暴击 ${(part.critChance * 100).toFixed(0)}%`);
    if (part.procChance != null) bits.push(`触发 ${(part.procChance * 100).toFixed(0)}%`);
    if (part.disposition) bits.push(`倾向 ${Number(part.disposition).toFixed(2)}`);
    if (part.oneHanded || part.twoHanded) bits.push(`单手 ${part.oneHanded || "—"} / 双手 ${part.twoHanded || "—"}`);
  } else if (kind === "grip") {
    if (part.damageBonus != null) bits.push(`${part.damageBonus > 0 ? "+" : ""}${part.damageBonus} 伤害`);
    if (part.baseSpeed != null) bits.push(`基础攻速 ${part.baseSpeed}`);
    if (part.handed) bits.push(part.handed === "one" ? "单手" : "双手");
  } else {
    if (part.speedBonus != null) bits.push(`${part.speedBonus > 0 ? "+" : ""}${part.speedBonus} 攻速`);
    if (part.critChance) bits.push(`${part.critChance > 0 ? "+" : ""}${(part.critChance * 100).toFixed(0)}% 暴击`);
    if (part.statusChance) bits.push(`${part.statusChance > 0 ? "+" : ""}${(part.statusChance * 100).toFixed(0)}% 触发`);
    if (part.damageBonus != null) bits.push(`${part.damageBonus > 0 ? "+" : ""}${part.damageBonus} 伤害`);
  }
  return bits.join(" · ");
}

function kitgunPartHint(part, kind, slot) {
  if (!part?.path) return "";
  if (kind === "chamber") {
    const mode = (part.modes?.[slot] || [])[0];
    const bits = [];
    if (mode) {
      if (mode.total) bits.push(`直击 ${mode.total}`);
      if (mode.radial?.total) bits.push(`爆炸 ${mode.radial.total}${mode.radial.radius ? `（半径 ${Number(mode.radial.radius).toFixed(1)}m）` : ""}`);
      if (mode.critChance != null) bits.push(`暴击 ${(mode.critChance * 100).toFixed(1)}%`);
      if (mode.procChance != null) bits.push(`触发 ${(mode.procChance * 100).toFixed(1)}%`);
      if ((mode.unsupported || []).includes("kitgun-chain-damage-unapplied")) bits.push("含链式伤害");
      if ((mode.unsupported || []).includes("kitgun-cluster-damage-unapplied")) bits.push("含分裂弹");
    }
    const disposition = slot === "primary" ? (part.primaryDisposition ?? part.disposition) : part.disposition;
    if (disposition) bits.push(`倾向 ${Number(disposition).toFixed(2)}`);
    return bits.join(" · ");
  }
  const rows = Array.isArray(part.overrides) ? part.overrides : [];
  const sample = rows[0] || {};
  const bits = [];
  if (sample.damage != null) bits.push(`${kind === "grip" ? "伤害修正" : "伤害"} ${sample.damage > 0 ? "+" : ""}${sample.damage}`);
  if (sample.fireRate != null && kind === "grip") bits.push(`射速 ${sample.fireRate} rpm`);
  if (sample.critChance != null) bits.push(`暴击 ${(sample.critChance * 100).toFixed(1)}%`);
  if (sample.magazineSize != null) bits.push(`弹匣 ${sample.magazineSize}`);
  if (sample.reloadTime != null) bits.push(`装填 ${Number(sample.reloadTime).toFixed(1)}s`);
  return bits.join(" · ") || `${rows.length} 条枪型修正`;
}

let kitgunPreviewEl = null;
function hideKitgunPartPreview() {
  if (kitgunPreviewEl) { kitgunPreviewEl.remove(); kitgunPreviewEl = null; }
}

function showKitgunPartPreview(part, kind, anchor, slot, zaw = false) {
  if (!matchMedia("(hover: hover)").matches || !part?.path) return;
  hideKitgunPartPreview();
  const pop = create("div", "mod-preview-pop kitgun-part-pop");
  const title = create("div", "kitgun-pop-title");
  title.append(create("strong", "", part.nameZh || part.nameEn || "部件"));
  const disposition = !zaw && kind === "chamber" && slot === "primary" ? (part.primaryDisposition ?? part.disposition) : part.disposition;
  if (disposition) title.append(create("small", "", `紫卡倾向 ${Number(disposition).toFixed(2)}`));
  pop.append(title);
  const body = create("div", "kitgun-pop-body");
  if (zaw) {
    if (kind === "chamber") {
      const rows = [
        ["总伤害", part.damage?.total != null ? part.damage.total.toFixed(1) : null],
        ["暴击几率", part.critChance != null ? `${(part.critChance * 100).toFixed(1)}%` : null],
        ["暴击倍率", part.critMultiplier != null ? `${Number(part.critMultiplier).toFixed(2)}x` : null],
        ["触发", part.procChance != null ? `${(part.procChance * 100).toFixed(1)}%` : null],
        ["攻速修正", part.speedMod != null ? `${part.speedMod > 0 ? "+" : ""}${Number(part.speedMod).toFixed(3)}` : null],
        ["单手形态", part.oneHanded || null],
        ["双手形态", part.twoHanded || null],
      ].filter(([, v]) => v != null);
      rows.forEach(([k, v]) => body.append(create("div", "kitgun-pop-row", `${k} ${v}`)));
      const types = Object.entries(part.damage?.types || {}).sort((a, b) => b[1] - a[1]);
      if (types.length) {
        const typeRow = create("div", "kitgun-pop-row is-types");
        types.forEach(([code, v]) => {
          const chip = create("span", "effect-chip");
          if (ELEMENT_ICONS[code]) chip.append(imageNode(ELEMENT_ICONS[code], "effect-chip-icon", "", "lazy"));
          chip.append(document.createTextNode(`${DAMAGE_TYPE_LABELS[code] || code.replace(/^DT_/, "")} ${(part.damage?.total ? (v / part.damage.total * 100).toFixed(0) : "?")}%`));
          typeRow.append(chip);
        });
        body.append(typeRow);
      }
    } else if (kind === "grip") {
      const rows = [
        [part.damageBonus != null ? `${part.damageBonus > 0 ? "+" : ""}${part.damageBonus} 伤害` : null],
        [part.baseSpeed != null ? `基础攻速 ${part.baseSpeed}` : null],
        [part.handed ? (part.handed === "one" ? "单手形态" : "双手形态") : null],
      ];
      rows.forEach(([label]) => { if (label) body.append(create("div", "kitgun-pop-row", label)); });
    } else {
      const rows = [
        [part.speedBonus != null ? `${part.speedBonus > 0 ? "+" : ""}${part.speedBonus} 攻速` : null],
        [part.critChance ? `${part.critChance > 0 ? "+" : ""}${(part.critChance * 100).toFixed(0)}% 暴击` : null],
        [part.statusChance ? `${part.statusChance > 0 ? "+" : ""}${(part.statusChance * 100).toFixed(0)}% 触发` : null],
        [part.damageBonus != null ? `${part.damageBonus > 0 ? "+" : ""}${part.damageBonus} 伤害` : null],
      ];
      rows.forEach(([label]) => { if (label) body.append(create("div", "kitgun-pop-row", label)); });
    }
  } else if (kind === "chamber") {
    const modes = part.modes?.[slot] || [];
    modes.slice(0, 2).forEach((mode, i) => {
      const sec = create("div", "kitgun-pop-mode");
      sec.append(create("h5", "", modes.length > 1 ? `模式 ${i + 1}` : "基础面板"));
      const rows = [
        ["直击伤害", mode.total != null ? mode.total.toFixed(1) : null],
        ["爆炸伤害", mode.radial?.total != null ? `${Number(mode.radial.total).toFixed(1)}${mode.radial.radius ? ` · 半径 ${Number(mode.radial.radius).toFixed(1)}m` : ""}${mode.radial.falloff != null ? ` · 衰减 ${(Number(mode.radial.falloff) * 100).toFixed(0)}%` : ""}（未计入单目标）` : null],
        ["暴击几率", mode.critChance != null ? `${(mode.critChance * 100).toFixed(1)}%` : null],
        ["暴击倍率", mode.critMultiplier != null ? `${Number(mode.critMultiplier).toFixed(2)}x` : null],
        ["触发", mode.procChance != null ? `${(mode.procChance * 100).toFixed(1)}%` : null],
        ["射速", mode.fireRate != null ? `${Number(mode.fireRate).toFixed(2)}/s` : null],
        ...((mode.unsupported || []).length ? [["计算说明", mode.unsupported.map((u) => DIAGNOSTIC_CODE_LABELS[u] || u).join("；")]] : []),
      ].filter(([, v]) => v != null);
      rows.forEach(([k, v]) => sec.append(create("div", "kitgun-pop-row", `${k} ${v}`)));
      const types = Object.entries(mode.types || {}).sort((a, b) => b[1] - a[1]);
      if (types.length) {
        const typeRow = create("div", "kitgun-pop-row is-types");
        types.forEach(([code, v]) => {
          const chip = create("span", "effect-chip");
          if (ELEMENT_ICONS[code]) chip.append(imageNode(ELEMENT_ICONS[code], "effect-chip-icon", "", "lazy"));
          chip.append(document.createTextNode(`${DAMAGE_TYPE_LABELS[code] || code.replace(/^DT_/, "")} ${(mode.total ? (v / mode.total * 100).toFixed(0) : "?")}%`));
          typeRow.append(chip);
        });
        sec.append(typeRow);
      }
      body.append(sec);
    });
  } else {
    (part.overrides || []).slice(0, 8).forEach((o) => {
      const sec = create("div", "kitgun-pop-mode");
      sec.append(create("h5", "", KITGUN_GUNTYPE_LABELS[o.gunType] || o.gunType));
      const rows = [
        [o.damage != null ? `${o.damage > 0 ? "+" : ""}${o.damage} 伤害` : null, o.damage != null],
        [o.fireRate != null ? `${o.fireRate} rpm 射速` : null, o.fireRate != null && kind === "grip"],
        [o.critChance != null ? `${(o.critChance * 100).toFixed(1)}% 暴击` : null, o.critChance != null],
        [o.critMultiplier != null ? `${Number(o.critMultiplier).toFixed(2)}x 暴伤` : null, o.critMultiplier != null],
        [o.procChance != null ? `${(o.procChance * 100).toFixed(1)}% 触发` : null, o.procChance != null],
        [o.magazineSize != null ? `弹匣 ${o.magazineSize}` : null, o.magazineSize != null],
        [o.reloadTime != null ? `装填 ${Number(o.reloadTime).toFixed(1)}s` : null, o.reloadTime != null],
      ];
      rows.forEach(([label, ok]) => { if (ok && label) sec.append(create("div", "kitgun-pop-row", label)); });
      body.append(sec);
    });
  }
  pop.append(body);
  document.body.append(pop);
  kitgunPreviewEl = pop;
  const rect = anchor.getBoundingClientRect();
  const width = 300;
  const popHeight = Math.min(pop.offsetHeight || 400, window.innerHeight - 24);
  let left = rect.right + 12;
  if (left + width > window.innerWidth - 8) left = Math.max(8, rect.left - width - 12);
  let top = clamp(rect.top - 10, 8, Math.max(8, window.innerHeight - popHeight - 12));
  pop.style.left = `${left}px`;
  pop.style.top = `${top}px`;
  requestAnimationFrame(() => pop.classList.add("is-open"));
}

const KITGUN_GUNTYPE_LABELS = {
  GT_RIFLE: "步枪型", GT_SHOTGUN: "霰弹型", GT_BEAM: "光束型", GT_SNIPER: "狙击型", GT_LAUNCHER: "发射器型", GT_PROJECTILE: "投射型",
};

function kitgunPartsPayload() {
  const base = state.kitgunBase;
  const parts = state.kitgunParts;
  if (!base || !parts) return undefined;
  if (!parts.chamber || !parts.grip || !parts.loader) return undefined;
  return [parts.chamber, parts.grip, parts.loader];
}

function assemblyWeaponReady() {
  const base = state.kitgunBase;
  const parts = state.kitgunParts;
  if (!base || !parts) return false;
  return Boolean(parts.chamber && parts.grip && parts.loader);
}

function openWeaponPicker(target = "build") {
  if (!ui["weapon-picker"]) return;
  state.weaponPickerTarget = target === "analysis" ? "analysis" : "build";
  ui["weapon-picker"].hidden = false;
  ui["mod-picker-scrim"].hidden = false;
  document.body.classList.add("is-modal-open");
  if (ui["weapon-picker-search"]) ui["weapon-picker-search"].value = "";
  renderWeaponPicker();
  ui["weapon-picker-search"]?.focus();
}

function closeWeaponPicker() {
  if (!ui["weapon-picker"] || ui["weapon-picker"].hidden) return;
  ui["weapon-picker"].hidden = true;
  if (ui["mod-picker"].hidden) {
    ui["mod-picker-scrim"].hidden = true;
    document.body.classList.remove("is-modal-open");
  }
}

// 外部加成目录由后端下发（catalog.buildOptions.externalBuffs）：战甲技能写
// 「战甲 · 技能」，光环写 Mod 名；每条列出加成的具体项目与乘区说明。
const EXTERNAL_BUFF_GROUPS = [
  ["ability", "战甲技能"],
  ["aura", "小队光环"],
  ["other", "其他来源"],
  ["generic", "通用数值"],
];
const EXTERNAL_BUFF_ALIASES = { mallet: "octavia-amp", "vigoruous-swap": "vigorous-swap" };
const EXTERNAL_BUFF_ELEMENT_LABELS = {
  DT_FIRE: "火焰", DT_FREEZE: "冰冻", DT_ELECTRICITY: "电击", DT_POISON: "毒素", DT_EXPLOSION: "爆炸",
  DT_RADIATION: "辐射", DT_GAS: "毒气", DT_MAGNETIC: "磁力", DT_VIRAL: "病毒", DT_CORROSIVE: "腐蚀",
};

function externalBuffCatalog() {
  return state.catalog?.buildOptions?.externalBuffs || [];
}

function externalBuffSpec(id) {
  return externalBuffCatalog().find((spec) => spec.id === id) || null;
}

// 保存过的旧配置：改名的 id 映射过来，下线的（Unairu 虚灵只加指挥官、
// 闪耀助燃的技能已移除）丢弃；旧的直接数值换算成强度 / 人数。
function normalizeExternalBuffs(items) {
  const rows = [];
  for (const raw of Array.isArray(items) ? items.slice(0, 40) : []) {
    const id = EXTERNAL_BUFF_ALIASES[raw?.id] || raw?.id;
    const spec = externalBuffSpec(id);
    if (!spec || rows.some((row) => row.id === id)) continue;
    const row = { id };
    const value = raw.value == null ? null : Number(raw.value);
    if (spec.squad) row.count = clamp(Math.round(Number(raw.count ?? (value != null ? value / spec.base : 1)) || 1), 1, 4);
    else if (spec.strength) row.strength = clamp(Number(raw.strength ?? (value != null ? value / spec.base : 1)) || 0, 0, 10);
    else row.value = clamp(Number(value ?? spec.base) || 0, 0, spec.maximum ?? 50);
    if (spec.elements?.length) row.element = spec.elements.includes(raw.element) ? raw.element : spec.elements[0];
    rows.push(row);
  }
  return rows;
}

function externalBuffValue(spec, item) {
  if (!spec || !item) return 0;
  let value = spec.squad ? spec.base * (item.count || 1) : spec.strength ? spec.base * (item.strength ?? 1) : Number(item.value ?? spec.base);
  if (spec.maximum != null) value = Math.min(value, spec.maximum);
  if (spec.group === "aura" && spec.id !== "coaction-drift") {
    const drift = state.externalBuffs.find((row) => row.id === "coaction-drift");
    value *= 1 + (drift ? externalBuffValue(externalBuffSpec("coaction-drift"), drift) : 0);
  }
  return value;
}

function externalBuffApplies(effect, weapon = state.buildWeapon) {
  if (!effect.applies || !weapon) return true;
  const ancestry = new Set([...(weapon.ancestry || []), weapon.path].filter(Boolean));
  if (weapon.weaponType === "zaw") ancestry.add("/Lotus/Types/Game/LotusMeleeWeapon");
  return effect.applies.some((path) => ancestry.has(path));
}

function externalBuffAmount(spec, value) {
  const number = (x) => Number(x.toFixed(x >= 10 ? 0 : x >= 1 ? 2 : 3)).toString();
  if (spec.unit === "count") return `+${number(value)}`;
  if (spec.unit === "multiplier") return `+${number(value)} 倍`;
  return `${spec.negative ? "−" : "+"}${number(value * 100)}%`;
}

function externalBuffSummary(spec, item) {
  const value = externalBuffValue(spec, item);
  return spec.effects.map((effect) => {
    const amount = value * effect.scale;
    let label = effect.label;
    if (spec.elements?.length && item?.element) label = `${EXTERNAL_BUFF_ELEMENT_LABELS[item.element] || item.element}${label}`;
    let text = `${label} ${externalBuffAmount(spec, amount)}`;
    if (spec.meleeScale) text += `（近战 ${externalBuffAmount(spec, amount * spec.meleeScale)}）`;
    if (spec.sniperScale) text += `（狙击枪 ${externalBuffAmount(spec, amount * spec.sniperScale)}）`;
    return { text, applies: externalBuffApplies(effect) };
  });
}

function renderExternalBuffs() {
  const target = document.getElementById("external-buff-list");
  if (!target) return;
  const catalog = externalBuffCatalog();
  const touch = () => { persistActiveBuildConfig(); scheduleLiveManualSimulation(); renderExternalBuffs(); };
  const groups = EXTERNAL_BUFF_GROUPS.map(([group, title]) => {
    const specs = catalog.filter((spec) => spec.group === group);
    if (!specs.length) return null;
    const section = create("div", "external-buff-group");
    section.append(create("h4", "external-buff-group-title", title));
    for (const spec of specs) {
      const current = state.externalBuffs.find((item) => item.id === spec.id) || null;
      const summary = externalBuffSummary(spec, current || {});
      const applies = summary.some((part) => part.applies);
      const row = create("div", `external-buff-row${current ? " is-enabled" : ""}${applies ? "" : " is-inapplicable"}`);
      const label = create("label", "external-buff-toggle");
      const check = document.createElement("input");
      check.type = "checkbox";
      check.checked = Boolean(current);
      check.addEventListener("change", () => {
        if (check.checked) state.externalBuffs.push(normalizeExternalBuffs([{ id: spec.id }])[0]);
        else state.externalBuffs = state.externalBuffs.filter((item) => item.id !== spec.id);
        touch();
      });
      const copy = create("span", "external-buff-copy");
      const head = create("strong", "", spec.label);
      if (!applies) head.append(create("em", "external-buff-tag", "当前武器不生效"));
      copy.append(head, create("span", "external-buff-effects", summary.map((part) => part.text).join(" · ")), create("small", "", spec.detail));
      label.append(check, copy);
      row.append(label);
      const controls = create("span", "external-buff-controls");
      if (current) {
        if (spec.squad) {
          const select = document.createElement("select");
          select.title = "携带该光环的队员人数（同一光环可叠加）";
          for (let n = 1; n <= 4; n += 1) select.append(new Option(`${n} 人`, String(n), false, n === current.count));
          select.addEventListener("change", () => { current.count = Number(select.value); touch(); });
          controls.append(select);
        } else if (spec.strength) {
          const field = create("label", "external-buff-number");
          const input = document.createElement("input");
          input.type = "number"; input.min = "0"; input.max = "1000"; input.step = "5";
          input.value = String(Math.round((current.strength ?? 1) * 100));
          input.title = "施放者的技能强度（%）";
          input.addEventListener("change", () => { current.strength = clamp(Number(input.value) || 0, 0, 1000) / 100; touch(); });
          field.append(create("span", "", "强度"), input, create("span", "", "%"));
          controls.append(field);
        } else {
          const field = create("label", "external-buff-number");
          const input = document.createElement("input");
          const scale = spec.unit === "percent" ? 100 : 1;
          input.type = "number"; input.min = "0"; input.max = String((spec.maximum ?? 50) * scale); input.step = scale === 100 ? "1" : "0.1";
          input.value = String(+(Number(current.value ?? spec.base) * scale).toFixed(2));
          input.title = "直接填写数值";
          input.addEventListener("change", () => { current.value = clamp(Number(input.value) || 0, 0, (spec.maximum ?? 50) * scale) / scale; touch(); });
          field.append(input, create("span", "", scale === 100 ? "%" : spec.unit === "multiplier" ? "倍" : ""));
          controls.append(field);
        }
        if (spec.elements?.length) {
          const select = document.createElement("select");
          select.title = "额外命中的元素";
          for (const element of spec.elements) select.append(new Option(EXTERNAL_BUFF_ELEMENT_LABELS[element] || element, element, false, element === current.element));
          select.addEventListener("change", () => { current.element = select.value; touch(); });
          controls.append(select);
        }
      }
      row.append(controls);
      section.append(row);
    }
    return section;
  }).filter(Boolean);
  target.replaceChildren(...groups);
  renderExternalBuffGain();
}

async function renderExternalBuffGain() {
  // 开 / 关外部加成各跑一次实时解算，取击杀速度（回放口径，含额外命中与光环削甲）。
  const panel = document.querySelector(".external-buff-panel .fold-body");
  if (!panel) return;
  let gainEl = panel.querySelector(".external-buff-gain");
  if (!gainEl) {
    gainEl = create("div", "external-buff-gain");
    panel.append(gainEl);
  }
  if (!state.externalBuffs.length) { gainEl.hidden = true; return; }
  const payload = modGainsPayload();
  if (!payload) return;
  const token = (renderExternalBuffGain.token || 0) + 1;
  renderExternalBuffGain.token = token;
  const kpmText = (value) => (value < 10 ? Number(value.toPrecision(3)).toString() : formatMetric(value));
  try {
    const post = async (buffs, kind) => {
      const res = await fetch("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, externalBuffs: buffs, ...liveTag(kind, token) }) });
      const body = await res.json();
      if (!res.ok) throw new Error("simulate failed");
      const sim = body.simulation || body;
      const kpm = finite(sim.benchmarkTimeline?.killsPerMinute);
      return kpm !== null ? { value: kpm, unit: "KPM" } : { value: finite(sim.targetDamage?.dps) ?? finite(sim.moddedStats?.sustainedDps) ?? 0, unit: "DPS" };
    };
    const [withBuffs, without] = await Promise.all([post(externalBuffsPayload(), "buff-gain-on"), post([], "buff-gain-off")]);
    if (token !== renderExternalBuffGain.token) return;
    if (without.value > 0) {
      const percent = (withBuffs.value / without.value - 1) * 100;
      gainEl.hidden = false;
      gainEl.replaceChildren(
        create("span", "", "外部加成总收益"),
        create("b", `external-buff-gain-value${percent < 0 ? " is-negative" : ""}`, `${percent >= 0 ? "+" : ""}${percent.toFixed(1)}%`),
        create("small", "", `关闭 ${kpmText(without.value)} → 开启 ${kpmText(withBuffs.value)} ${withBuffs.unit}`),
      );
    }
  } catch (_error) {
    gainEl.hidden = true;
  }
}

function externalBuffsPayload() {
  return state.externalBuffs.map((item) => {
    const row = { id: item.id };
    for (const key of ["strength", "count", "value", "element"]) if (item[key] != null) row[key] = item[key];
    return row;
  });
}

function rivenPayload() {
  const rivenIndex = state.manualSlots.findIndex((mod) => mod && mod.__riven && Array.isArray(mod.stats) && mod.stats.length);
  const rivenSlot = rivenIndex >= 0 ? state.manualSlots[rivenIndex] : null;
  if (!rivenSlot) return null;
  return {
    stats: rivenSlot.stats.map((stat) => ({ code: stat.code, value: Number(stat.value || 0), negative: Boolean(stat.negative) })),
    // 后端容量校验用：紫卡固定极性 + 所占槽位（极性比对决定 18/9/22.5 消耗）。
    polarity: rivenFixedPolarity(rivenSlot, rivenIndex),
    slot: rivenIndex,
  };
}

function specialSlotAsset(kind, item) {
  return item?.slotAsset
    || state.buildWeapon?.specialSlots?.[kind]?.slotAsset
    || (kind === "stance" ? "/assets/game/slots/IconStance.png" : "/assets/game/slots/IconExilus.png");
}

function renderSpecialModSlot(kind, item) {
  const locked = kind === "stance" && state.stanceLocked;
  const label = kind === "stance" ? "架势" : "功能槽";
  const slot = create("article", `special-mod-slot${locked ? " is-locked" : ""}${item ? " is-filled" : ""}`);
  slot.dataset.kind = kind;
  const slotPolarity = weaponSpecialSlotPolarity(kind);
  slot.tabIndex = locked || state.buildInputMode === "auto" ? -1 : 0;
  slot.setAttribute("role", "button");
  slot.setAttribute("aria-label", `${label}${item ? `：${item.nameZh || item.nameEn || item.path}` : "：空"}`);
  const head = create("div", "special-slot-head");
  head.append(imageNode(specialSlotAsset(kind, item), "special-slot-kind-icon", "", "lazy"), create("strong", "", label));
  const polarity = create("button", "slot-polarity-chip special-slot-polarity-button");
  polarity.type = "button";
  polarity.disabled = locked || state.buildInputMode === "auto";
  const specialRelation = item ? modEffectiveDrain(item, slotPolarity).relation : "";
  const specialForma = Object.hasOwn(state.formaSlots, specialSlotIndex(kind));
  polarity.classList.toggle("is-matched", specialRelation === "match");
  polarity.classList.toggle("is-mismatch", specialRelation === "mismatch");
  polarity.classList.toggle("is-forma", specialForma);
  polarity.title = `槽位极性：${POLARITY_NAMES[slotPolarity] || "无"}${polarity.disabled ? "" : " · 点击切换"}`;
  polarity.setAttribute("aria-label", polarity.title);
  polarity.append(warframePolarityNode(slotPolarity, "slot-polarity-icon"));
  polarity.addEventListener("click", (event) => { event.stopPropagation(); cycleSpecialSlotPolarity(kind); });
  head.append(polarity);
  if (locked) head.append(create("span", "special-slot-lock", "天生锁定"));
  slot.append(head);
  if (item) {
    slot.append(createSpecialModCard(item, kind, false, slotPolarity));
    slot.append(create("p", "special-slot-summary", specialModSummary(item, kind)));
    if (kind === "exilus") {
      const controls = create("div", "special-slot-controls");
      const maxRank = Number(item.maxRank ?? item.rank ?? 0);
      const rank = clamp(Number(item.rank ?? maxRank), 0, maxRank);
      const down = create("button", "rank-stepper-btn", "−");
      const up = create("button", "rank-stepper-btn", "+");
      const remove = create("button", "special-slot-remove", "×");
      down.type = up.type = remove.type = "button";
      remove.title = "移除功能槽 MOD";
      remove.setAttribute("aria-label", "移除功能槽 MOD");
      down.disabled = rank <= 0;
      up.disabled = rank >= maxRank;
      const update = (next) => {
        state.exilusSelection.rank = clamp(next, 0, maxRank);
        renderSpecialSlots(); persistActiveBuildConfig(); scheduleLiveManualSimulation();
      };
      down.addEventListener("click", (event) => { event.stopPropagation(); update(rank - 1); });
      up.addEventListener("click", (event) => { event.stopPropagation(); update(rank + 1); });
      remove.addEventListener("click", (event) => {
        event.stopPropagation(); state.exilusSelection = null; renderSpecialSlots(); persistActiveBuildConfig(); scheduleLiveManualSimulation();
      });
      controls.append(down, create("span", "rank-stepper-value", `R${rank}/${maxRank}`), up, remove);
      slot.append(controls);
    }
  } else {
    const empty = create("div", "special-slot-empty");
    empty.append(create("span", "", "＋"), create("small", "", "未装备"));
    slot.append(empty);
  }
  const open = () => {
    if (locked) return toast("显赫武器使用天生架势，不能更换");
    openSpecialModPicker(kind);
  };
  slot.addEventListener("click", open);
  slot.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  return slot;
}

function renderSpecialSlots() {
  const target = ui["special-mod-slots"];
  if (!target) return;
  const specs = [];
  if (isMeleeBuild()) specs.push(["stance", state.stanceSelection]);
  if (state.buildWeapon) specs.push(["exilus", state.exilusSelection]);
  // 与 MOD 槽同一套 diff 复用：签名不变的功能槽节点不重绘（图片不重载）
  const existing = Array.from(target.children);
  specs.forEach(([kind, item], position) => {
    const locked = kind === "stance" && state.stanceLocked;
    const slotPolarity = weaponSpecialSlotPolarity(kind) || "";
    const signature = [kind, item?.path || "", item ? Number(item.rank ?? item.maxRank ?? 0) : "", locked ? 1 : 0, slotPolarity, item?.capacityGain ?? "", item?.polarityRelation ?? "", state.buildInputMode].join("|");
    const prev = existing[position];
    if (prev && prev.dataset.signature === signature) return;
    const node = renderSpecialModSlot(kind, item);
    node.dataset.signature = signature;
    if (prev) target.replaceChild(node, prev);
    else target.append(node);
  });
  while (target.children.length > specs.length) target.lastElementChild.remove();
  if (ui["special-loadout"]) ui["special-loadout"].hidden = !state.buildWeapon;
}

function renderArcaneSlot(kind, slotIndex, item) {
  const label = kind === "warframe" ? `战甲赋能 ${slotIndex + 1}` : "武器赋能";
  const source = item && typeof item === "object" ? item : null;
  const catalogRecord = source ? arcaneRecords().find((arcane) => arcane.path === source.path) : null;
  const record = source ? { ...(catalogRecord || {}), ...source, path: catalogRecord?.path || source.path } : null;
  const slot = create("article", `arcane-workbench-slot${record ? " is-filled" : ""}`);
  const rarity = String(record?.rarity || "").toUpperCase();
  slot.dataset.rarity = rarity || "EMPTY";
  // 贡献徽章定位锚点（paintEquippedGains 按 __arcane__:<path> 查找）。
  if (record) slot.dataset.arcanePath = record.path;
  const visual = create("div", "arcane-slot-visual");
  const frame = record ? (ARCANE_FRAMES[rarity] || ARCANE_FRAMES.COMMON) : "/assets/arcanes/NoArcaneIcon.png";
  visual.append(imageNode(frame, "arcane-slot-frame", "", "lazy"));
  const iconAsset = catalogIconAsset(record, "arcane");
  if (iconAsset) visual.append(imageNode(iconAsset, "arcane-slot-icon", record.nameZh || record.nameEn || "赋能", "lazy"));
  const copy = create("div", "arcane-slot-copy");
  copy.append(create("small", "arcane-slot-label", label));
  copy.append(create("strong", "", record ? (record.nameZh || record.nameEn || record.path) : "空槽位"));
  if (record) {
    copy.append(create("span", "arcane-slot-rank", `等级 ${Number(record.rank ?? record.maxRank ?? 0)}/${Number(record.maxRank ?? record.rank ?? 0)}`));
    const description = arcaneDescription(record);
    const text = create("p", "arcane-slot-description", description);
    text.title = description;
    copy.append(text);
    const note = arcaneStateControls(record).note;
    if (kind === "warframe" && !frameArcaneAppliesToWeapon(record)) {
      slot.classList.add("is-inapplicable");
      copy.append(create("p", "arcane-slot-note is-warning", "对当前武器无效，不参与解算"));
    } else if (note) {
      copy.append(create("p", "arcane-slot-note", note));
    }
  } else {
    copy.append(create("p", "arcane-slot-description", "未装备"));
  }
  slot.append(visual, copy);
  slot.tabIndex = state.buildInputMode === "auto" ? -1 : 0;
  slot.setAttribute("role", "button");
  const open = () => openArcanePicker(kind, slotIndex);
  slot.addEventListener("click", open);
  slot.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  if (record) {
    const controls = create("div", "arcane-slot-controls");
    const maxRank = Number(record.maxRank ?? item.rank ?? 0);
    const rank = clamp(Number(item.rank ?? maxRank), 0, maxRank);
    const down = create("button", "rank-stepper-btn", "−");
    const up = create("button", "rank-stepper-btn", "+");
    const remove = create("button", "arcane-slot-remove", "×");
    down.type = up.type = remove.type = "button";
    down.disabled = rank <= 0;
    up.disabled = rank >= maxRank;
    const update = (next) => {
      const target = kind === "warframe" ? state.frameArcanes[slotIndex] : (slotIndex === 1 ? state.weaponArcane2 : state.weaponArcane);
      target.rank = clamp(next, 0, maxRank);
      syncArcaneSelections(); renderArcaneSelections(); persistActiveBuildConfig(); scheduleLiveManualSimulation();
    };
    down.addEventListener("click", (event) => { event.stopPropagation(); update(rank - 1); });
    up.addEventListener("click", (event) => { event.stopPropagation(); update(rank + 1); });
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      if (kind === "warframe") state.frameArcanes[slotIndex] = null;
      else if (slotIndex === 1) state.weaponArcane2 = null;
      else state.weaponArcane = null;
      syncArcaneSelections(); renderArcaneSelections(); persistActiveBuildConfig(); scheduleLiveManualSimulation();
    });
    controls.append(down, create("span", "rank-stepper-value", `R${rank}`), up, remove);
    slot.append(controls);
    // 触发型赋能提供「强制触发 / 限定层数」开关：默认关闭时由后端按武器面板
    // 推导触发期望；打开后按手动状态（满层全程 / 固定层数全程）参与解算。
    const stateControls = arcaneStateControls(record);
    const applies = kind !== "warframe" || frameArcaneAppliesToWeapon(record);
    const hasTrigger = applies && Boolean(stateControls.force || stateControls.stacks);
    if (hasTrigger) {
      const maxStacks = Math.max(1, Number(stateControls.stacks ?? 1) || 1);
      const entry = () => (kind === "warframe" ? state.frameArcanes[slotIndex] : (slotIndex === 1 ? state.weaponArcane2 : state.weaponArcane));
      const commit = () => { syncArcaneSelections(); renderArcaneSelections(); persistActiveBuildConfig(); scheduleLiveManualSimulation(); };
      const toggles = create("div", "arcane-slot-toggles");
      if (stateControls.force) {
        const force = create("button", `arcane-flag-toggle${item.forceProc ? " is-active" : ""}`, "强制触发");
        force.type = "button";
        force.title = "视为赋能始终触发并按满层计算";
        force.setAttribute("aria-pressed", String(Boolean(item.forceProc)));
        force.addEventListener("click", (event) => {
          event.stopPropagation();
          const target = entry();
          if (!target) return;
          target.forceProc = !target.forceProc;
          if (target.forceProc) target.fixedStacks = null;
          commit();
        });
        toggles.append(force);
      }
      if (maxStacks > 1) {
        const fixedActive = Number.isInteger(item.fixedStacks) && item.fixedStacks > 0;
        const fixed = create("button", `arcane-flag-toggle${fixedActive ? " is-active" : ""}`, "限定层数");
        fixed.type = "button";
        fixed.title = "固定赋能层数参与解算（全程覆盖）";
        fixed.setAttribute("aria-pressed", String(fixedActive));
        fixed.addEventListener("click", (event) => {
          event.stopPropagation();
          const target = entry();
          if (!target) return;
          if (Number.isInteger(target.fixedStacks) && target.fixedStacks > 0) target.fixedStacks = null;
          else { target.fixedStacks = maxStacks; target.forceProc = false; }
          commit();
        });
        toggles.append(fixed);
        if (fixedActive) {
          const current = clamp(Number(item.fixedStacks ?? maxStacks), 1, maxStacks);
          const sdown = create("button", "rank-stepper-btn", "−");
          const sup = create("button", "rank-stepper-btn", "+");
          sdown.type = sup.type = "button";
          sdown.disabled = current <= 1;
          sup.disabled = current >= maxStacks;
          const setStacks = (next) => {
            const target = entry();
            if (!target) return;
            target.fixedStacks = clamp(next, 1, maxStacks);
            commit();
          };
          sdown.addEventListener("click", (event) => { event.stopPropagation(); setStacks(current - 1); });
          sup.addEventListener("click", (event) => { event.stopPropagation(); setStacks(current + 1); });
          const unit = stateControls.stackLabel && stateControls.stackLabel !== "层数" ? ` · ${stateControls.stackLabel}` : " 层";
          toggles.append(sdown, create("span", "rank-stepper-value", `${current}${unit}`), sup);
        }
      }
      slot.append(toggles);
    }
  }
  return slot;
}

function weaponArcaneSlotCount() {
  // 空战武器（地面）：两个武器赋能槽（主+副赋能池同时触发——wfsim
  // arcane_slots=2 / arcane_pools=[primary, secondary]）。
  return state.buildWeapon?.weaponType === "archgun" ? 2 : 1;
}

function renderArcaneSelections() {
  const target = ui["build-arcane-list"];
  if (!target) return;
  if (isCompanionWeapon()) {
    // 机械武器不能装赋能（wiki Arcane_Enhancement / Sentinel）。
    target.replaceChildren(create("p", "empty-copy companion-arcane-note", "守护武器不能装赋能；战甲赋能也不作用于守护的攻击。"));
    return;
  }
  if (target.querySelector(".companion-arcane-note")) target.replaceChildren();
  const specs = [
    ["weapon", 0, state.weaponArcane],
  ];
  if (weaponArcaneSlotCount() > 1) specs.push(["weapon", 1, state.weaponArcane2]);
  // 显赫武器：战甲赋能来自关联战甲的配置（见显赫武器面板），这里不提供槽位。
  if (!isExaltedWeapon()) specs.push(["warframe", 0, state.frameArcanes[0]], ["warframe", 1, state.frameArcanes[1]]);
  // diff 复用：未变化的赋能槽不重绘（图标/框图不重载）
  const existing = Array.from(target.children);
  specs.forEach(([kind, slotIndex, item], position) => {
    const signature = [kind, slotIndex, item?.path || "", item ? Number(item.rank ?? item.maxRank ?? 0) : "", item?.forceProc ? 1 : 0, item?.fixedStacks ?? "", state.buildInputMode, state.buildWeapon?.path || ""].join("|");
    const prev = existing[position];
    if (prev && prev.dataset.signature === signature) return;
    const node = renderArcaneSlot(kind, slotIndex, item);
    node.dataset.signature = signature;
    if (prev) target.replaceChild(node, prev);
    else target.append(node);
  });
  while (target.children.length > specs.length) target.lastElementChild.remove();
}

function addArcaneSelection(path) {
  const target = path || state.arcanePickerTarget;
  if (!target) return toast("先选择一个赋能");
  const slotIndex = state.arcanePickerSlot || 0;
  const current = state.arcanePickerKind === "warframe"
    ? state.frameArcanes[slotIndex]
    : (slotIndex === 1 ? state.weaponArcane2 : state.weaponArcane);
  if (state.arcaneSelections.some((item) => item.path === target && item !== current)) return toast("该赋能已经添加");
  const record = arcaneRecords().find((item) => item.path === target) || {};
  const isFrame = record.slotKind === "warframe";
  const selection = {
    ...record,
    path: target,
    rank: Number(record.maxRank ?? 0),
    slotKind: record.slotKind || "weapon",
  };
  if (isFrame) state.frameArcanes[slotIndex] = selection;
  else if (slotIndex === 1) state.weaponArcane2 = selection;
  else state.weaponArcane = selection;
  syncArcaneSelections();
  renderArcaneSelections();
  persistActiveBuildConfig();
  scheduleLiveManualSimulation();
}

function manualModLabel(mod) { return mod.nameZh || mod.nameEn || mod.nameInternal || mod.path || "MOD"; }

const MOD_EFFECT_LABELS = {
  WEAPON_DAMAGE_AMOUNT: "基础伤害", WEAPON_PERCENT_BASE_DAMAGE_ADDED: "基础伤害", WEAPON_MELEE_DAMAGE: "近战伤害",
  WEAPON_CRIT_CHANCE: "暴击几率", WEAPON_CRIT_DAMAGE: "暴击伤害",
  WEAPON_FIRE_ITERATIONS: "多重射击", WEAPON_FIRE_RATE: "射速 / 攻速", WEAPON_PROC_CHANCE: "触发几率",
  WEAPON_RELOAD_SPEED: "装填速度", WEAPON_CLIP_MAX: "弹匣容量", WEAPON_AMMO_MAX: "弹药上限", GAMEPLAY_FACTION_DAMAGE: "派系伤害",
  WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE: "对异常目标伤害", WEAPON_PROC_DAMAGE: "异常伤害",
  WEAPON_PROJECTILE_SPEED: "投射物速度", WEAPON_RANGE: "攻击范围",
  WEAPON_MELEE_COMBO_INITIAL_BONUS: "初始连击", WEAPON_MELEE_COMBO_USAGE_EFFICIENCY: "连击效率",
  WEAPON_INIT_DAMAGE_MOD: "首发伤害",
};

const ELEMENT_ICONS = {
  DT_IMPACT: "/assets/elements/impact.png", DT_PUNCTURE: "/assets/elements/puncture.png", DT_SLASH: "/assets/elements/slash.png",
  DT_FIRE: "/assets/elements/heat.png", DT_FREEZE: "/assets/elements/cold.png", DT_ELECTRICITY: "/assets/elements/electricity.png",
  DT_POISON: "/assets/elements/toxin.png", DT_EXPLOSION: "/assets/elements/blast.png", DT_RADIATION: "/assets/elements/radiation.png",
  DT_GAS: "/assets/elements/gas.png", DT_MAGNETIC: "/assets/elements/magnetic.png", DT_VIRAL: "/assets/elements/viral.png",
  DT_CORROSIVE: "/assets/elements/corrosive.png", DT_RADIANT: "/assets/elements/void.png", DT_TRUE: "/assets/elements/true.png",
};
// 伤害类型文字配色：与 wiki 同源（--dt-*-text-color，暗色主题实测值）。
const DAMAGE_TYPE_COLORS = {
  DT_IMPACT: "#80C4C4", DT_PUNCTURE: "#C6B098", DT_SLASH: "#E69CA0",
  DT_FIRE: "#FB9733", DT_FREEZE: "#5BBCEC", DT_ELECTRICITY: "#B37FE7", DT_POISON: "#00CC22",
  DT_EXPLOSION: "#DD704E", DT_RADIATION: "#CEAC49", DT_GAS: "#00CC66",
  DT_MAGNETIC: "#9797E6", DT_VIRAL: "#F093B9", DT_CORROSIVE: "#93C203",
  DT_RADIANT: "#15C8AB", DT_TRUE: "#DDA700",
};

function setElementControlIcon(select, image) {
  if (!select || !image) return;
  const source = ELEMENT_ICONS[select.selectedOptions[0]?.dataset.damageType || select.value] || "";
  image.src = source;
  image.hidden = !source;
  image.alt = select.selectedOptions[0]?.textContent || "";
}

function refreshInnateElementControls(weapon = state.buildWeapon, preferred = null) {
  const field = ui["build-innate-element-field"];
  const valueField = ui["build-innate-element-value-field"];
  const select = ui["build-innate-element-select"];
  if (!field || !valueField || !select) return;
  const candidates = Array.isArray(weapon?.innateElementCandidates) ? weapon.innateElementCandidates : [];
  const requested = preferred || select.value;
  select.replaceChildren();
  candidates.forEach((damageType) => {
    const option = document.createElement("option");
    option.value = damageType;
    option.textContent = DAMAGE_TYPE_LABELS[damageType] || damageType;
    select.append(option);
  });
  const enabled = candidates.length > 0;
  field.hidden = !enabled;
  valueField.hidden = !enabled;
  select.disabled = !enabled;
  if (!enabled) {
    select.value = "";
    ui["build-innate-element-icon"].hidden = true;
    return;
  }
  select.value = candidates.includes(requested) ? requested : defaultInnateElement(weapon);
  setElementControlIcon(select, ui["build-innate-element-icon"]);
  const value = clamp(Number(ui["build-innate-element-value"]?.value || 60), 25, 60);
  if (ui["build-innate-element-value"]) ui["build-innate-element-value"].value = String(value);
  if (ui["build-innate-element-output"]) ui["build-innate-element-output"].textContent = `${value}%`;
  setSliderVisual(ui["build-innate-element-value"]);
}

function defaultInnateElement(weapon = state.buildWeapon) {
  const candidates = Array.isArray(weapon?.innateElementCandidates) ? weapon.innateElementCandidates : [];
  // Heat is the conventional progenitor default and is present in all three
  // frozen Kuva/Tenet/Coda candidate sets. Fall back to the first exported
  // candidate if a future weapon changes that list.
  return candidates.includes("DT_FIRE") ? "DT_FIRE" : (candidates[0] || "");
}
const ARCANE_FRAMES = {
  COMMON: "/assets/arcanes/frames/Common.webp",
  UNCOMMON: "/assets/arcanes/frames/Uncommon.webp",
  RARE: "/assets/arcanes/frames/Rare.webp",
  LEGENDARY: "/assets/arcanes/frames/Legendary.webp",
};

const ELEMENT_DAMAGE_LABELS = {
  DT_IMPACT: "冲击伤害", DT_PUNCTURE: "穿刺伤害", DT_SLASH: "切割伤害", DT_FIRE: "火焰伤害", DT_FREEZE: "冰冻伤害",
  DT_ELECTRICITY: "电击伤害", DT_POISON: "毒素伤害", DT_EXPLOSION: "爆炸伤害", DT_RADIATION: "辐射伤害",
  DT_GAS: "毒气伤害", DT_MAGNETIC: "磁力伤害", DT_VIRAL: "病毒伤害", DT_CORROSIVE: "腐蚀伤害", DT_TRUE: "真实伤害",
};

function effectLabel(effect) {
  const damageType = String(effect?.damageType || "").toUpperCase();
  if (damageType && DAMAGE_TYPE_LABELS[damageType]) {
    return ELEMENT_DAMAGE_LABELS[damageType] || DAMAGE_TYPE_LABELS[damageType];
  }
  return MOD_EFFECT_LABELS[effect?.upgradeType] || String(effect?.upgradeType || "效果").replace(/^WEAPON_/, "").replaceAll("_", " ");
}

function modAssetFields(mod) {
  const asset = state.modAssets?.mods?.[mod?.path] || {};
  const catalog = state.catalog?.manualMods?.find((entry) => entry.path === mod?.path) || {};
  // The frozen Warframe sidecar is newer and more specific than the shared
  // weapon-art index.  Merge art/frame metadata underneath the selected row so
  // stale generic fields can never overwrite rank, slot type, text or sets.
  const merged = { ...asset, ...catalog };
  for (const [key, value] of Object.entries(mod || {})) {
    if (value !== null && value !== undefined && value !== "") merged[key] = value;
  }
  return merged;
}

// Some official i18n entries carry a literal "\n" (backslash + n) instead of a
// real newline. Split on both so each visual line renders separately.
function splitEffectSegments(text) {
  return String(text)
    .replace(/<LINE_SEPARATOR>/gi, "\n")
    .split(/\\n|\n/)
    .map((seg) => seg.trim())
    // Internal formatter tokens are not card text.  Keep the official value,
    // drop only the marker itself (and zero-value implementation placeholders).
    .map((seg) => seg.replace(/<LOWER_IS_BETTER>/gi, "").replace(/\bNONE\s*[+]?[\-+]?0(?:\.0+)?%?/gi, "").trim())
    .filter(Boolean);
}

function localizedEffectLines(mod) {
  const meta = modAssetFields(mod);
  const rank = Math.max(0, Math.floor(Number(mod?.rank ?? mod?.maxRank ?? 0) || 0));
  const byRank = Array.isArray(meta.effectsZhByRank) && meta.effectsZhByRank.length
    ? meta.effectsZhByRank
    : (Array.isArray(mod?.effectsZhByRank) ? mod.effectsZhByRank : []);
  const index = byRank.length ? Math.min(rank, byRank.length - 1) : 0;
  const ranked = Array.isArray(byRank[index]) ? byRank[index] : [];
  const source = ranked.length
    ? ranked
    : (Array.isArray(meta.effectsZh) && meta.effectsZh.length
      ? meta.effectsZh
      : (Array.isArray(mod?.effectsZh) ? mod.effectsZh : []));
  // Umbra/Sacrificial cards change their printed values with the actual
  // equipped set count. Other set bonuses stay on their separate set line.
  const setMultiplier = isSacrificeSetMod(mod) ? modSetMultiplier(mod) : 1;
  return source.flatMap((text) => splitEffectSegments(text).map((seg) => {
    const iconKey = (seg.match(/DT_[A-Z_]+(?=_COLOR)/) || [])[0];
    return {
      label: damageTokenText(applySetMultiplierToOfficialLine(seg, setMultiplier))
        .replace(/<[^>]+>/g, ""),
      icon: ELEMENT_ICONS[iconKey] || null,
      iconName: DAMAGE_TYPE_LABELS[iconKey] || null,
    };
  }));
}

function officialEffectText(mod) {
  const lines = localizedEffectLines(mod);
  if (lines.length) return lines.map((line) => line.label).join("\n");
  const meta = modAssetFields(mod);
  return String(mod?.description || meta?.description || "")
    .replace(/<[^>]+>/g, "")
    .trim();
}

// True when conditionZh is already embedded in an effectsZh line (e.g.
// "击杀时：\n+30% 多重射击…"), so callers must not append it a second time.
function conditionAlreadyListed(meta) {
  const cond = String(meta?.conditionZh || "").replace(/<\/?DT_[A-Z_]+_COLOR>/g, "").trim();
  if (!cond) return false;
  const effects = Array.isArray(meta?.effectsZh) ? meta.effectsZh : [];
  return effects.some((text) =>
    splitEffectSegments(text).some((seg) => seg.replace(/<\/?DT_[A-Z_]+_COLOR>/g, "").includes(cond))
  );
}

function modEffectLines(mod) {
  const meta = modAssetFields(mod);
  // Official per-level lines (from warframe-items i18n) always win when present.
  // displayEffects is the solved state and is rendered below as a separate line.
  const localized = localizedEffectLines(mod);
  if (localized.length) return localized;
  if (Array.isArray(mod.displayEffects) && mod.displayEffects.length) {
    return mod.displayEffects.map((effect) => {
      const value = Number(effect?.value);
      const damageType = String(effect?.damageType || "").toUpperCase();
      return {
        label: effectLabel(effect),
        ...(Number.isFinite(value) ? { value } : {}),
        icon: ELEMENT_ICONS[damageType] || null,
        damageType: effect?.damageType || null,
      };
    });
  }
  const rank = Number(mod.rank ?? mod.maxRank ?? 0);
  const lines = [];
  for (const effect of (mod.effects || [])) {
    if (effect?.supported === false) continue;
    // NONE rows are script/formatter placeholders, not user-facing stats.
    // A real localized description is already preferred above; only retain an
    // explicit text payload when a sidecar has one for an otherwise NONE row.
    if (String(effect?.upgradeType || "").toUpperCase() === "NONE") {
      const explicit = cleanOfficialText(effect?.descriptionZh || effect?.description || "");
      if (explicit) lines.push({ label: explicit });
      continue;
    }
    const label = effectLabel(effect);
    const value = Number(effect.valuePerRank);
    if (!Number.isFinite(value)) { lines.push({ label }); continue; }
    const total = value * (rank + 1);
    lines.push({ label, value: total, icon: ELEMENT_ICONS[String(effect.damageType || "").toUpperCase()] || null, damageType: effect.damageType || null });
  }
  if (!lines.length) {
    const description = String(mod?.description || meta?.description || "")
      .replace(/<[^>]+>/g, "")
      .replace(/\\n/g, "\n")
      .trim();
    if (description) return splitEffectSegments(description).map((label) => ({ label }));
  }
  return lines;
}

function cleanOfficialText(value) {
  return damageTokenText(value || "")
    .replace(/<LOWER_IS_BETTER>/gi, "")
    .replace(/\bNONE\s*[+]?[-+]?0(?:\.0+)?%?/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function modRuntimeText(mod) {
  const stacks = Array.isArray(mod?.steadyStacks) ? mod.steadyStacks : [];
  const effects = Array.isArray(mod?.displayEffects) ? mod.displayEffects : [];
  if (!stacks.length || !effects.length) return "";
  const count = Math.max(...stacks.map((item) => Number(item?.stacks) || 0), 0);
  const values = effects.map((effect) => {
    const value = Number(effect?.value);
    return Number.isFinite(value)
      ? `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}% ${effectLabel(effect)}`
      : effectLabel(effect);
  }).filter(Boolean);
  return count && values.length ? `满层上限 ${count} 层（实际战斗按触发爬升）：${values.join("；")}` : "";
}

const SET_PLACEHOLDER_VALUES = (stats, displayValues = {}, pieces = 1) => {
  const values = {};
  const normalizedPieces = Math.max(1, Number(pieces) || 1);
  const display = displayValues && typeof displayValues === "object" ? displayValues : {};
  const pickDisplay = (key) => {
    const entry = display[key] ?? display[key.toLowerCase()];
    if (Array.isArray(entry) && entry.length) return entry[Math.min(normalizedPieces - 1, entry.length - 1)];
    return entry;
  };
  const format = (raw, key = "") => {
    const value = Number(raw);
    if (!Number.isFinite(value)) return "";
    if (/^(STAT|val)/i.test(key) && Math.abs(value) < 1) return `${(value * 100).toFixed(0)}`;
    return `${Number.isInteger(value) ? value : value.toFixed(1).replace(/\.0$/, "")}`;
  };
  for (const key of ["STAT1", "STAT2", "STAT3", "STAT4", "val", "RANGE", "COOLDOWN", "DURATION", "COUNT", "DELAY", "RADIUS", "DAMAGE"]) {
    const picked = pickDisplay(key);
    if (picked !== undefined && picked !== null) values[key] = format(picked, key);
  }
  if (!Array.isArray(stats)) return Object.keys(values).length ? values : null;
  let statIndex = 1;
  let valIndex = 1;
  for (const stat of stats) {
    const raw = stat?.value ?? stat?.valuePerRank ?? stat?.baseValue;
    const value = Number(raw);
    if (Number.isFinite(value) && value !== 0) {
      const scaled = stat?.valuePerRank !== undefined ? value * normalizedPieces : value;
      if (!values[`STAT${statIndex}`]) values[`STAT${statIndex++}`] = format(scaled, `STAT${statIndex}`);
      if (!values[`val${valIndex}`]) values[`val${valIndex++}`] = values[`STAT${statIndex - 1}`];
    }
    if (Number.isFinite(Number(stat?.duration)) && Number(stat.duration) > 0 && !values.DURATION) {
      values.DURATION = `${Number(stat.duration).toFixed(0)}`;
    }
    if (Number.isFinite(Number(stat?.maxStacks)) && Number(stat.maxStacks) > 0 && !values.COUNT) {
      values.COUNT = `${Math.round(stat.maxStacks)}`;
    }
  }
  return Object.keys(values).length ? values : null;
};

function fillSetPlaceholders(text, stats, displayValues = {}, pieces = 1) {
  const values = SET_PLACEHOLDER_VALUES(stats, displayValues, pieces);
  const base = String(text)
    .replace(/\|STAT(\d)\|/g, (m, d) => values?.[`STAT${d}`] ?? "—")
    .replace(/\|val(\d)?\|/g, (m, d) => (values ? ((d ? values[`val${d}`] : (values.val ?? values.val1)) ?? "—") : "—"))
    .replace(/\|DURATION\|/g, values?.DURATION ?? "—")
    .replace(/\|COUNT\|/g, values?.COUNT ?? "—")
    .replace(/\|RANGE\|/g, values?.RANGE ?? "—")
    .replace(/\|COOLDOWN\|/g, values?.COOLDOWN ?? values?.DURATION ?? "—")
    .replace(/\|DELAY\|/g, values?.DELAY ?? "—")
    .replace(/\|RADIUS\|/g, values?.RADIUS ?? "—")
    .replace(/\|DAMAGE\|/g, values?.DAMAGE ?? "—");
  return base.replace(/%%/g, "%");
}

function activeSetPieces(mod) {
  if (!mod?.modSet) return 1;
  // The shared card renderer is used by both workbenches.  When the Warframe
  // tab is active, count the actual Aura/Exilus/normal loadout instead of the
  // weapon's eight-slot buffer; otherwise Umbra and other set cards display
  // a stale piece count even though the backend used the right set size.
  const slots = state.activeTool === "warframe"
    ? [state.warframeBuild?.aura, state.warframeBuild?.exilus, ...(state.warframeBuild?.normalMods || [])]
    : [...state.manualSlots, state.exilusSelection];
  return Math.max(1, slots.filter((item) => item?.modSet === mod.modSet).length);
}

function modSetMultiplier(mod) {
  const values = Array.isArray(mod?.modSetValues) ? mod.modSetValues : [];
  const pieces = activeSetPieces(mod);
  if (!values.length || pieces < 2) return 1;
  return 1 + Number(values[Math.min(pieces - 2, values.length - 1)] || 0);
}

function applySetMultiplierToOfficialLine(text, multiplier) {
  if (multiplier === 1) return String(text);
  const source = String(text);
  const scaled = source.replace(/([+]?)(\d+(?:\.\d+)?)%/g, (_match, sign, raw) => {
    const value = Number(raw) * multiplier;
    const rounded = Math.abs(value - Math.round(value)) < 1e-9 ? String(Math.round(value)) : value.toFixed(1);
    return sign + rounded + "%";
  });
  if (!/Sentient|感知者/i.test(source)) return scaled;
  return scaled.replace(/x(\d+(?:\.\d+)?)/gi, (_match, raw) => {
    const value = 1 + (Number(raw) - 1) * multiplier;
    return "x" + value.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  });
}

function modSetText(mod) {
  if (!mod?.modSet) return "";
  const meta = modAssetFields(mod);
  const parts = [];
  const pieces = activeSetPieces(mod);
  const maxPieces = Number(mod.setMaxPieces || meta.setMaxPieces || 0);
  const setDescription = mod.setDescription || mod.setDesc || meta.setDesc;
  const setStats = mod.setStats || mod.setStatsByRank || meta.setStats;
  const displayValues = mod.setDisplayValues || meta.setDisplayValues || {};
  if (setDescription) {
    // Keep the official wording intact in the catalog; this line is only the
    // separate current-piece preview. Unknown runtime values are shown as an
    // em dash instead of leaking raw |TOKEN| placeholders.
    const cleaned = cleanOfficialText(fillSetPlaceholders(String(setDescription), setStats, displayValues, pieces));
    parts.push(cleaned);
    if (maxPieces > 1) {
      parts.push(`当前 ${Math.min(pieces, maxPieces)}/${maxPieces} 件`);
    }
  }
  if (!isSacrificeSetMod(mod) && Array.isArray(mod.modSetValues) && mod.modSetValues.length) {
    if (pieces < 2) {
      parts.push(`当前 ${pieces}/${maxPieces || 2} 件：未触发套装增幅`);
    } else {
      // BuffSet 曲线按件数取值：N 件 → 第 N-2 项。
      const active = mod.modSetValues[Math.min(pieces - 2, mod.modSetValues.length - 1)];
      parts.push(`当前 ${Math.min(pieces, maxPieces || pieces)}/${maxPieces || pieces} 件；套装生效：卡面数值 ×${(1 + active).toFixed(2)}`);
    }
  } else if (!setDescription && mod.setMaxPieces) {
    parts.push(mod.setSupported === false
      ? `套装 ${mod.setMaxPieces} 件效果依赖战斗中的条件，暂不支持模拟（当前 ${Math.min(pieces, maxPieces)} 件）`
      : `套装当前 ${Math.min(pieces, maxPieces)}/${maxPieces} 件生效`);
  }
  return parts.join("；");
}

function modEffectText(mod) {
  const meta = modAssetFields(mod);
  const lines = modEffectLines(mod).map((line) => {
    if (line.value === undefined) return line.label;
    return `${line.label} ${line.value >= 0 ? "+" : ""}${(line.value * 100).toFixed(1)}%`;
  });
  const condition = meta.conditionZh;
  const setText = isSacrificeSetMod(mod) ? "" : modSetText(mod);
  // Localized rank text is the official card text. Computed values stay separate.
  const official = officialEffectText(mod);
  const conditionLine = condition && !conditionAlreadyListed(meta) ? damageTokenText(condition) : "";
  const officialText = String(official || "");
  const uniqueLines = lines.filter((line) => !officialText.includes(String(line)));
  const unsupportedNote = Array.isArray(mod?.unsupportedNotes) && mod.unsupportedNotes.length ? "该词条不参与计算" : "";
  // Unsupported diagnostics stay in the hover title/diagnostics channel, not
  // in the rendered card: "mod-effect-line is-unsupported", "该词条不参与计算"。
  const combined = [...(official ? [official] : []), ...uniqueLines, setText, conditionLine, modStackedSummary(mod), unsupportedNote].filter(Boolean)
    .map(cleanOfficialText)
    .filter(Boolean);
  return combined.length ? combined.join("；") : "暂无效果说明";
}

// ── Slot polarity & capacity system ────────────────────────────────────────
// The frozen export carries each weapon's real slot polarities (e.g. Boltor
// starts Vazarin-heavy). Forma (极化) overrides a slot's polarity; matches
// halve drain, mismatches add ×1.25. UI mirrors Overframe: green segments for
// polarized slots, auto-polarize option, reverse polarity allowed while the
// total stays within capacity.

function weaponSlotPolarities() {
  const base = Array.isArray(state.buildWeapon?.polarities) ? state.buildWeapon.polarities : [];
  const slotCount = Number(ui["build-slot-count"]?.value || 8);
  const slots = [];
  for (let i = 0; i < slotCount; i += 1) {
    const declared = Object.hasOwn(state.formaSlots, i) ? state.formaSlots[i] : base[i];
    slots.push(!declared || declared === "AP_UNIVERSAL" ? null : declared);
  }
  return slots;
}

function specialSlotIndex(kind) {
  if (kind === "stance") return isMeleeBuild() ? 8 : null;
  if (kind === "exilus") return isMeleeBuild() ? 9 : 8;
  return null;
}

function normalizedSpecialPolarity(value) {
  const token = typeof value === "string" ? value.trim().toUpperCase() : "";
  return !token || token === "AP_UNIVERSAL" || token === "AP_NONE" || token === "NONE" || token === "NULL"
    ? null
    : token;
}

function weaponSpecialSlotPolarity(kind) {
  const index = specialSlotIndex(kind);
  if (index === null) return null;
  const special = state.buildWeapon?.specialSlots?.[kind] || {};
  if (Object.hasOwn(state.formaSlots, index)) return normalizedSpecialPolarity(state.formaSlots[index]);
  return normalizedSpecialPolarity(special.slotPolarity);
}

function specialSlotPolaritiesPayload() {
  const result = {};
  for (const kind of ["stance", "exilus"]) {
    const index = specialSlotIndex(kind);
    if (index === null || !state.buildWeapon) continue;
    if (Object.hasOwn(state.formaSlots, index)) {
      result[kind] = state.formaSlots[index] || "AP_UNIVERSAL";
      continue;
    }
    const native = state.buildWeapon.specialSlots?.[kind]?.slotPolarity;
    result[kind] = typeof native === "string" && native ? native : "AP_UNIVERSAL";
  }
  return result;
}

function polarityMatches(modPolarity, slotPolarity) {
  if (!modPolarity || modPolarity === "AP_UNIVERSAL" || !slotPolarity || slotPolarity === "AP_UNIVERSAL") return false;
  return modPolarity === "AP_ANY" || slotPolarity === "AP_ANY" || modPolarity === slotPolarity;
}

// 紫卡极性：游戏内揭示时在 Madurai / Vazarin / Naramon 三者中随机，洗卡不变。
const RIVEN_POLARITY_CHOICES = ["AP_ATTACK", "AP_DEFENSE", "AP_TACTIC"];
function randomRegularPolarity() {
  return RIVEN_POLARITY_CHOICES[Math.floor(Math.random() * RIVEN_POLARITY_CHOICES.length)];
}
// 取紫卡固定极性：无记录时（旧配置/极端路径）按稳定伪随机补一个，
// 保证同一武器+同一槽位的旧数据渲染结果稳定。
function rivenFixedPolarity(mod, slotIndex = 0) {
  if (mod?.rivenPolarity && RIVEN_POLARITY_CHOICES.includes(mod.rivenPolarity)) return mod.rivenPolarity;
  const seed = `${state.buildWeapon?.path || ""}#${slotIndex}`;
  let hash = 0;
  for (const ch of seed) hash = (hash * 31 + ch.codePointAt(0)) >>> 0;
  return RIVEN_POLARITY_CHOICES[hash % RIVEN_POLARITY_CHOICES.length];
}

function modBaseDrain(mod) {
  if (mod?.__riven) return 18;
  const meta = state.modAssets?.mods?.[mod?.path] || {};
  // Ordinary utility rows expose full max-rank drain; stances expose signed baseDrain.
  const maxRank = finite(mod?.maxRank) ?? finite(meta.maxRank) ?? 0;
  const rank = clamp(finite(mod?.rank) ?? maxRank, 0, maxRank);
  const fullDrain = finite(meta.drain) ?? finite(mod?.catalogDrain) ?? finite(mod?.drain);
  if (fullDrain !== null) return fullDrain - maxRank + rank;
  const base = finite(mod?.baseDrain) ?? finite(meta.baseDrain);
  if (base !== null) return base < 0 ? -(Math.abs(base) + rank) : base + rank;
  return 0;
}

function modEffectiveDrain(mod, slotPolarity, slotIndex) {
  const base = modBaseDrain(mod);
  if (mod?.__riven) {
    // 紫卡拥有落槽时掷出的固定常规极性（rivenFixedPolarity）：与槽位极性
    // 独立比对——匹配减半 / 不匹配 ×1.25 / 槽位无极性全值。槽位极化只改
    // 变槽位极性本身，不再「声明」紫卡极性（紫卡极性不随极化变动）。
    const rivenPol = rivenFixedPolarity(mod, slotIndex);
    if (slotPolarity && slotPolarity !== "AP_UNIVERSAL") {
      if (polarityMatches(rivenPol, slotPolarity)) return { drain: Math.ceil(base / 2), relation: "match" };
      return { drain: Math.ceil(base * 1.25), relation: "mismatch" };
    }
    return { drain: base, relation: "neutral" };
  }
  const modPol = modPolarityOf(mod);
  if (modPol && modPol !== "AP_UNIVERSAL" && slotPolarity && slotPolarity !== "AP_UNIVERSAL") {
    const matches = polarityMatches(modPol, slotPolarity);
    if (base < 0) {
      const factor = matches ? 2 : 0.5;
      return { drain: -Math.ceil(Math.abs(base) * factor), relation: matches ? "match" : "mismatch" };
    }
    if (matches) return { drain: Math.ceil(base / 2), relation: "match" };
    return { drain: Math.ceil(base * 1.25), relation: "mismatch" };
  }
  return { drain: base, relation: "neutral" };
}

function stanceSelectionWithSlot(stance, override = {}) {
  if (!stance) return null;
  const slot = state.buildWeapon?.specialSlots?.stance || {};
  const merged = { ...slot, ...stance, ...override, slotPolarity: weaponSpecialSlotPolarity("stance") };
  const maxRank = Number(merged.maxRank ?? merged.rank ?? 0);
  const rank = clamp(Number(merged.rank ?? maxRank), 0, maxRank);
  const selected = { ...merged, rank, maxRank, slotPolarity: merged.slotPolarity ?? slot.slotPolarity };
  if (selected.builtIn || selected.locked) return selected;
  const effective = modEffectiveDrain(selected, selected.slotPolarity);
  const relation = effective.relation === "match" ? "matched" : effective.relation === "mismatch" ? "mismatched" : "unpolarized";
  const stancePolarityMatches = !Object.hasOwn(stance, "slotPolarity")
    || normalizedSpecialPolarity(stance.slotPolarity) === weaponSpecialSlotPolarity("stance");
  const explicitGain = Object.hasOwn(override, "capacityGain")
    ? override.capacityGain
    : Object.hasOwn(stance, "capacityGain") && stancePolarityMatches
      ? stance.capacityGain
    : undefined;
  const explicitRelation = Object.hasOwn(override, "polarityRelation")
    ? override.polarityRelation
    : Object.hasOwn(stance, "polarityRelation") && stancePolarityMatches
      ? stance.polarityRelation
    : undefined;
  return {
    ...selected,
    capacityGain: Number.isFinite(Number(explicitGain)) ? Number(explicitGain) : Math.max(0, -effective.drain),
    polarityRelation: explicitRelation || relation,
  };
}

function weaponCapacityLimit() {
  const stance = state.stanceSelection;
  const effective = stance && !stance.builtIn
    ? modEffectiveDrain(stance, weaponSpecialSlotPolarity("stance"))
    : null;
  const gain = effective && effective.drain < 0
    ? -effective.drain
    : Number(stance?.capacityGain ?? state.buildWeapon?.specialSlots?.stance?.capacityGain ?? 0);
  return 60 + Math.max(0, Number.isFinite(gain) ? Math.trunc(gain) : 0);
}

function computeCapacity() {
  const slots = weaponSlotPolarities();
  const limit = weaponCapacityLimit();
  const perSlot = [];
  let used = 0;
  state.manualSlots.forEach((mod, index) => {
    if (!mod) {
      perSlot.push({ index, drain: 0, relation: "empty", forma: Boolean(state.formaSlots[index]) });
      return;
    }
    const { drain, relation } = modEffectiveDrain(mod, slots[index], index);
    used += drain;
    perSlot.push({ index, drain, relation, forma: Boolean(state.formaSlots[index]) });
  });
  if (state.exilusSelection) {
    const slotPolarity = weaponSpecialSlotPolarity("exilus");
    const { drain, relation } = modEffectiveDrain(state.exilusSelection, slotPolarity);
    used += drain;
    perSlot.push({ index: "exilus", drain, relation, forma: false });
  }
  return { used, limit, perSlot, slots, over: used > limit };
}

function renderCapacityBar() {
  const bar = ui["capacity-bar"];
  const readout = ui["capacity-readout"];
  if (!bar || !readout) return;
  const { used, limit, perSlot, over } = computeCapacity();
  const segUsed = Math.ceil(limit / 5);
  const nodes = [];
  for (let i = 0; i < segUsed; i += 1) nodes.push(create("i", "cap-seg"));
  const fillRatio = Math.min(used / limit, 1);
  const filledSegs = Math.round(fillRatio * segUsed);
  let polarizedCap = 0;
  perSlot.filter((s) => s.forma && s.drain > 0).forEach((s) => { polarizedCap += s.drain; });
  const greenSegs = Math.round(Math.min(polarizedCap / limit, 1) * segUsed);
  nodes.forEach((seg, i) => {
    if (i < filledSegs) seg.classList.add(over ? "is-over" : "is-used");
    if (i >= filledSegs - greenSegs && i < filledSegs && greenSegs > 0) seg.classList.add("is-polarized");
  });
  bar.replaceChildren(...nodes);
  bar.classList.toggle("is-over", over);
  readout.innerHTML = "";
  // In-game style: capacity drains from the limit towards 0 — show what REMAINS.
  const remaining = limit - used;
  if (over) {
    readout.append(document.createTextNode("容量不足 "));
    readout.append(create("b", "", `超出 ${used - limit}`));
  } else {
    readout.append(document.createTextNode("剩余容量 "));
    readout.append(create("b", "", `${remaining} / ${limit}`));
  }
  readout.title = `已消耗 ${used} / ${limit}（匹配极性减半，不匹配 ×1.25）`;
  readout.classList.toggle("is-over", over);
  const needed = ui["forma-needed"];
  if (needed) {
    // Over capacity (e.g. after re-polarizing a slot by hand): how many more
    // Forma the current layout needs, from the same minimal plan.
    const plan = over ? workbenchFormaPlan() : null;
    needed.hidden = !over;
    needed.textContent = !over ? "" : plan?.fits ? `还需极化 ×${plan.formas}` : "极化也装不下";
  }
}

// ── Minimal Forma ──────────────────────────────────────────────────────────
// The solver scores builds as if every card sat in a matching slot; the real
// build only has to fit the capacity. minimalFormaPlan finds the fewest Forma
// that make it fit — the same exact DP over slots as the backend's
// optimizer.forma_plan. Ties go to fewer moved cards, then less drain. Cards
// carrying a base element keep their relative order (it decides which
// combined elements form); fixed cards never move.
const BASE_ELEMENT_TYPES = new Set(["DT_FIRE", "DT_FREEZE", "DT_ELECTRICITY", "DT_POISON"]);
const RIVEN_BASE_ELEMENT_CODES = new Set(["4", "5", "6", "7"]);
const UMBRA_POLARITIES = new Set(["AP_UMBRA", "AP_ULTIMATE"]);

function modHasBaseElement(mod) {
  if (!mod) return false;
  if (mod.__riven) return (mod.stats || []).some((stat) => !stat.negative && RIVEN_BASE_ELEMENT_CODES.has(String(stat.code)));
  const meta = state.modAssets?.mods?.[mod.path] || {};
  const effects = [...(Array.isArray(mod.effects) ? mod.effects : []), ...(Array.isArray(meta.effects) ? meta.effects : [])];
  return effects.some((effect) => BASE_ELEMENT_TYPES.has(String(effect?.damageType || "").toUpperCase()) && Number(effect?.valuePerRank ?? 1) > 0);
}

function polarizedDrain(drain, polarity, slot) {
  if (!polarity || !slot) return drain;
  const matched = polarity === slot || polarity === "AP_ANY" || slot === "AP_ANY";
  const factor = drain >= 0 ? (matched ? 0.5 : 1.25) : (matched ? 2 : 0.5);
  const adjusted = Math.ceil(Math.abs(drain) * factor);
  return drain < 0 ? -adjusted : adjusted;
}

// slots: polarity per slot (null = none). items: { origin, polarity, drain,
// elemental, fixed }. extras: per cardless slot (stance / Exilus) the
// alternatives [formas, umbra, drainDelta], index 0 = leave it.
function minimalFormaPlan({ slots, items, limit, extras = [], allowMove = true }) {
  const n = slots.length;
  const list = items.filter((item) => item.origin >= 0 && item.origin < n);
  const elementalFixed = !allowMove || list.some((item) => item.elemental && item.fixed);
  const fixedAt = new Map();
  list.forEach((item, index) => {
    if (item.fixed || !allowMove || (item.elemental && elementalFixed)) fixedAt.set(item.origin, index);
  });
  const pinned = new Set(fixedAt.values());
  const movable = list.map((_item, index) => index).filter((index) => !pinned.has(index)).sort((a, b) => list[a].origin - list[b].origin);
  const chain = movable.filter((index) => list[index].elemental);
  const free = movable.filter((index) => !list[index].elemental);
  const bit = new Map(free.map((index, position) => [index, 1 << position]));
  const full = (1 << free.length) - 1;
  const openAfter = slots.map((_slot, k) => slots.reduce((count, _s, j) => count + (j > k && !fixedAt.has(j) ? 1 : 0), 0));
  const popcount = (value) => { let count = 0; for (let v = value; v; v &= v - 1) count += 1; return count; };
  const keyOf = (e, mask, formas, moves) => `${e}|${mask}|${formas}|${moves}`;
  let layer = new Map([[keyOf(0, 0, 0, 0), { drain: 0, e: 0, mask: 0, formas: 0, moves: 0, back: null }]]);
  const history = [];
  for (let j = 0; j < n; j += 1) {
    const next = new Map();
    const push = (e, mask, formas, moves, drain, back) => {
      const key = keyOf(e, mask, formas, moves);
      const current = next.get(key);
      if (!current || drain < current.drain) next.set(key, { drain, e, mask, formas, moves, back });
    };
    for (const [key, node] of layer) {
      const options = [];
      if (fixedAt.has(j)) options.push([fixedAt.get(j), node.e, node.mask]);
      else {
        options.push([null, node.e, node.mask]);
        if (node.e < chain.length) options.push([chain[node.e], node.e + 1, node.mask]);
        for (const index of free) if (!(node.mask & bit.get(index))) options.push([index, node.e, node.mask | bit.get(index)]);
      }
      for (const [index, e2, mask2] of options) {
        if (!fixedAt.has(j) && (chain.length - e2) + (free.length - popcount(mask2)) > openAfter[j]) continue;
        if (index === null) { push(e2, mask2, node.formas, node.moves, node.drain, { key, index: null, formed: false }); continue; }
        const item = list[index];
        const moves = node.moves + (item.origin !== j ? 1 : 0);
        const plain = polarizedDrain(item.drain, item.polarity, slots[j]);
        push(e2, mask2, node.formas, moves, node.drain + plain, { key, index, formed: false });
        const matched = polarizedDrain(item.drain, item.polarity, item.polarity);
        if (item.polarity && matched !== plain) push(e2, mask2, node.formas + 1, moves, node.drain + matched, { key, index, formed: true });
      }
    }
    history.push(next);
    layer = next;
  }
  const combos = extras.reduce((acc, options) => acc.flatMap((combo) => options.map((option, index) => [...combo, [index, option]])), [[]]);
  let best = null;
  for (const [key, node] of layer) {
    if (node.e !== chain.length || node.mask !== full) continue;
    for (const combo of combos) {
      const formas = node.formas + combo.reduce((sum, [, option]) => sum + option[0], 0);
      const used = node.drain + combo.reduce((sum, [, option]) => sum + option[2], 0);
      const fits = used <= limit;
      const rank = [fits ? 0 : 1, fits ? 0 : used, formas, node.moves, used];
      const differs = best ? rank.findIndex((value, i) => value !== best.rank[i]) : -1;
      if (!best || (differs >= 0 && rank[differs] < best.rank[differs])) best = { rank, key, combo, used, fits };
    }
  }
  const placement = Array(n).fill(null);
  const forma = Array(n).fill(null);
  if (!best) return { formas: 0, umbra: 0, moves: 0, drain: 0, fits: true, placement, forma, extras: extras.map(() => 0) };
  let key = best.key;
  for (let j = n - 1; j >= 0; j -= 1) {
    const { back } = history[j].get(key);
    placement[j] = back.index === null ? null : list[back.index].origin;
    if (back.formed) forma[j] = list[back.index].polarity;
    key = back.key;
  }
  return {
    formas: forma.filter(Boolean).length + best.combo.reduce((sum, [, option]) => sum + option[0], 0),
    umbra: forma.filter((value) => UMBRA_POLARITIES.has(value)).length + best.combo.reduce((sum, [, option]) => sum + option[1], 0),
    moves: placement.filter((origin, j) => origin !== null && origin !== j).length,
    drain: best.used,
    fits: best.fits,
    placement,
    forma,
    extras: best.combo.map(([index]) => index),
  };
}

function nativeSlotPolarities() {
  const base = Array.isArray(state.buildWeapon?.polarities) ? state.buildWeapon.polarities : [];
  return weaponSlotPolarities().map((_slot, index) => normalizedSpecialPolarity(base[index]));
}

function stanceCapacityGain(stance, slotPolarity) {
  const effective = modEffectiveDrain(stance, slotPolarity);
  return effective.drain < 0 ? -effective.drain : Math.max(0, Number(stance?.capacityGain ?? 0) || 0);
}

// Plan input from the workbench. fresh: start from the weapon's native slot
// polarities and let unlocked cards move (fill / "最少极化"); otherwise keep
// every card and every Forma already placed and only add Forma.
function workbenchFormaPlan({ fresh = false } = {}) {
  const slots = fresh ? nativeSlotPolarities() : weaponSlotPolarities();
  const items = [];
  state.manualSlots.forEach((mod, index) => {
    if (!mod || index >= slots.length) return;
    if (mod.__riven && !RIVEN_POLARITY_CHOICES.includes(mod.rivenPolarity)) mod.rivenPolarity = rivenFixedPolarity(mod, index);
    const polarity = normalizedSpecialPolarity(modPolarityOf(mod, index));
    items.push({ origin: index, polarity, drain: modBaseDrain(mod), elemental: modHasBaseElement(mod), fixed: !fresh || Boolean(state.manualLocks[index]) });
  });
  const extras = [];
  const kinds = [];
  let limit = 60;
  const stance = state.stanceSelection;
  if (stance && !stance.builtIn && !stance.locked) {
    const current = weaponSpecialSlotPolarity("stance");
    const polarity = normalizedSpecialPolarity(modPolarityOf(stance));
    const gain = stanceCapacityGain(stance, current);
    limit += gain;
    const matchedGain = polarity ? stanceCapacityGain(stance, polarity) : gain;
    if (polarity && matchedGain > gain) { extras.push([[0, 0, 0], [1, UMBRA_POLARITIES.has(polarity) ? 1 : 0, gain - matchedGain]]); kinds.push(["stance", polarity]); }
  } else {
    limit = weaponCapacityLimit();
  }
  if (state.exilusSelection) {
    const current = weaponSpecialSlotPolarity("exilus");
    const polarity = normalizedSpecialPolarity(modPolarityOf(state.exilusSelection));
    const drain = modEffectiveDrain(state.exilusSelection, current).drain;
    const matched = polarity ? modEffectiveDrain(state.exilusSelection, polarity).drain : drain;
    extras.push(matched < drain ? [[0, 0, drain], [1, UMBRA_POLARITIES.has(polarity) ? 1 : 0, matched]] : [[0, 0, drain]]);
    kinds.push(["exilus", polarity]);
  }
  const plan = minimalFormaPlan({ slots, items, limit, extras, allowMove: fresh });
  plan.special = kinds.map(([kind, polarity], index) => ({ kind, polarity, formed: plan.extras[index] === 1 }));
  return plan;
}

function applyFormaPlan(plan, { fresh = false } = {}) {
  const native = nativeSlotPolarities();
  if (fresh) {
    const before = state.manualSlots.slice();
    plan.placement.forEach((origin, slot) => { state.manualSlots[slot] = origin === null ? null : before[origin]; });
    for (const key of Object.keys(state.formaSlots)) if (Number(key) < native.length) delete state.formaSlots[key];
  }
  plan.forma.forEach((polarity, slot) => {
    if (!polarity) return;
    if (polarity === native[slot]) delete state.formaSlots[slot];
    else state.formaSlots[slot] = polarity;
  });
  for (const { kind, polarity, formed } of plan.special || []) {
    if (formed && polarity) state.formaSlots[specialSlotIndex(kind)] = polarity;
  }
  refreshStanceSelection();
  refreshFormaCount();
}

// Fresh minimal plan for the current cards (solver fill, riven apply and the
// 「最少极化」button).
function applyMinimalForma() {
  const plan = workbenchFormaPlan({ fresh: true });
  applyFormaPlan(plan, { fresh: true });
  return plan;
}

function refreshFormaCount() {
  const native = nativeSlotPolarities();
  let regular = 0;
  let umbra = 0;
  let special = 0;
  for (const [key, value] of Object.entries(state.formaSlots)) {
    const index = Number(key);
    if (index >= native.length) { special += 1; continue; }
    if (UMBRA_POLARITIES.has(value)) umbra += 1;
    else regular += 1;
  }
  state.formaCount = regular + umbra + special;
  if (ui["forma-count"]) {
    ui["forma-count"].textContent = String(state.formaCount);
    const parts = [regular && `普通 ×${regular}`, umbra && `Umbra ×${umbra}`, special && `架势/功能槽 ×${special}`].filter(Boolean);
    ui["forma-counter"]?.setAttribute("title", state.formaCount ? `当前配装的极化：${parts.join("、")}` : "当前配装不需要极化");
  }
}

const POLARITY_NAMES = { AP_ATTACK: "Madurai", AP_DEFENSE: "Vazarin", AP_TACTIC: "Naramon", AP_UMBRA: "Umbra", AP_POWER: "力量", AP_WARD: "Unairu", AP_PRECEPT: "Penjaga", AP_UNIVERSAL: "无极性", AP_ANY: "任意" };

// Small corner chip rendered on each workbench slot: shows the slot's polarity
// (game-native), highlights match/mismatch of the equipped MOD, and cycles the
// forma polarity on click.
function slotPolarityChip(index, perSlotInfo) {
  const slots = weaponSlotPolarities();
  const pol = slots[index] || null;
  const info = perSlotInfo || {};
  const chip = create("button", `slot-polarity-chip${info.relation === "match" ? " is-matched" : ""}${info.relation === "mismatch" ? " is-mismatch" : ""}${info.forma ? " is-forma" : ""}`);
  chip.type = "button";
  if (POLARITY_IMAGES[pol]) {
    chip.append(imageNode(POLARITY_IMAGES[pol], "slot-polarity-icon", "", "lazy"));
  } else {
    chip.append(create("span", "slot-polarity-icon", ""));
  }
  const isRivenSlot = Boolean(state.manualSlots[index]?.__riven);
  const rivenPol = isRivenSlot ? rivenFixedPolarity(state.manualSlots[index], index) : null;
  chip.title = `槽位 ${index + 1} 极性 · ${POLARITY_NAMES[pol] || pol}${info.forma ? "（已极化）" : ""}${info.relation === "mismatch" ? " · MOD 不匹配（消耗 ×1.25）" : info.relation === "match" ? " · 匹配（消耗减半）" : ""}${isRivenSlot ? ` · 紫卡极性：${POLARITY_NAMES[rivenPol] || rivenPol} · 点击在原生极性与紫卡极性之间切换（紫卡极性在紫卡编辑里修改）` : " · 点击切换极化"}`;
  chip.setAttribute("aria-label", chip.title);
  chip.addEventListener("click", (event) => {
    event.stopPropagation();
    cycleSlotPolarity(index);
  });
  return chip;
}

// (capacityWithSlot removed: manual mode no longer hard-blocks on capacity —
// ensureCapacityFit polarizes dynamically instead.)

function cycleSlotPolarity(index) {
  const mod = state.manualSlots[index];
  const order = [null, "AP_ATTACK", "AP_DEFENSE", "AP_TACTIC", "AP_UMBRA", "AP_POWER", "AP_WARD", "AP_PRECEPT", "AP_ANY"];
  const current = weaponSlotPolarities()[index] || null;
  if (mod?.__riven) {
    // 紫卡槽只在「原生极性」与「紫卡自身极性」之间切换：紫卡极性固定
    // （Madurai / Vazarin / Naramon 之一），给它的槽极化成别的极性没有意义。
    const native = nativeSlotPolarities()[index] || null;
    const own = rivenFixedPolarity(mod, index);
    setSlotPolarity(index, current === own ? native : own);
    return;
  }
  if (!mod) {
    // 空槽自由循环极化（用来还原账号里武器已有的极化）。
    const currentIndex = Math.max(0, order.indexOf(current));
    const next = order[(currentIndex + 1) % order.length];
    setSlotPolarity(index, next);
    return;
  }
  // Occupied slot: cycle toward the mod's polarity (auto-polarize)
  const modPol = modPolarity(mod);
  const next = modPol && current !== modPol
    ? modPol
    : order[(Math.max(0, order.indexOf(current)) + 1) % order.length];
  setSlotPolarity(index, next);
}

function cycleSpecialSlotPolarity(kind) {
  const index = specialSlotIndex(kind);
  if (index === null || !state.buildWeapon) return;
  if (kind === "stance" && state.stanceLocked) return toast("显赫武器使用天生架势，不能极化");
  const current = weaponSpecialSlotPolarity(kind);
  const item = kind === "stance" ? state.stanceSelection : state.exilusSelection;
  const modPol = item ? modPolarityOf(item) : null;
  const currentIndex = WARFRAME_POLARITIES.indexOf(current);
  const next = modPol && current !== modPol
    ? modPol
    : WARFRAME_POLARITIES[(Math.max(0, currentIndex) + 1) % WARFRAME_POLARITIES.length];
  const native = normalizedSpecialPolarity(state.buildWeapon.specialSlots?.[kind]?.slotPolarity);
  if (next === native) delete state.formaSlots[index];
  else state.formaSlots[index] = next || "AP_UNIVERSAL";
  if (kind === "stance") refreshStanceSelection();
  refreshFormaCount();
  persistActiveBuildConfig();
  renderSpecialSlots();
  renderCapacityBar();
  scheduleLiveManualSimulation();
}

function refreshStanceSelection() {
  if (!state.stanceSelection || state.stanceLocked) return;
  const { capacityGain: _capacityGain, polarityRelation: _polarityRelation, slotPolarity: _slotPolarity, ...stance } = state.stanceSelection;
  state.stanceSelection = stanceSelectionWithSlot(stance);
}
const AP_TACTIC_KEY = "AP_TACTIC";

function setSlotPolarity(index, polarity) {
  const rawBase = (state.buildWeapon?.polarities || [])[index];
  const base = !rawBase || rawBase === "AP_UNIVERSAL" ? null : rawBase;
  if (polarity === base) delete state.formaSlots[index];
  else state.formaSlots[index] = polarity || "AP_UNIVERSAL";
  refreshFormaCount();
  persistActiveBuildConfig();
  renderManualSlots();
  scheduleLiveManualSimulation();
}

function slotPolaritiesPayload() {
  return weaponSlotPolarities();
}

// 拖拽幽灵图：克隆被拖卡面，半透明跟随光标（替代系统默认的整元素截图）。
// 克隆体定位在视口外保持可渲染供 setDragImage 取样；dragend 或超时兜底清理。
let modDragGhost = null;
let modDragSource = null;
let pointerModDrag = null;
let pointerModDragMove = null;
let pointerModDragEnd = null;
function dragSourceIndex(kind, event) {
  if (modDragSource?.kind === kind && Number.isInteger(modDragSource.index)) return modDragSource.index;
  const transfer = event.dataTransfer;
  const encoded = transfer?.getData("application/x-wf-slot") || transfer?.getData("text/plain") || "";
  const match = String(encoded).match(/^(?:[a-z]+:)?(\d+)$/i);
  return match ? Number(match[1]) : null;
}
function beginModDrag(kind, index, event, slot) {
  modDragSource = { kind, index };
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("application/x-wf-slot", `${kind}:${index}`);
  event.dataTransfer.setData("text/plain", `${kind}:${index}`);
  slot.classList.add("is-dragging");
  document.body.classList.add("is-mod-dragging");
  const ghost = createModDragGhost(slot);
  if (ghost) event.dataTransfer.setDragImage(ghost, ghost.offsetWidth / 2, Math.min(45, ghost.offsetHeight / 2));
}
function finishModDrag() {
  modDragSource = null;
  document.querySelectorAll(".is-dragging, .is-drop-target").forEach((node) => node.classList.remove("is-dragging", "is-drop-target"));
  document.body.classList.remove("is-mod-dragging");
  removeModDragGhost();
}
function pointerDragTarget(kind, event) {
  const target = document.elementFromPoint(event.clientX, event.clientY)?.closest(".manual-slot");
  if (!target) return null;
  const index = Number(target.dataset.slot);
  const valid = kind === "weapon"
    ? Number.isInteger(index) && index >= 0 && index < state.manualSlots.length && !state.manualLocks[index]
    : Number.isInteger(index) && index >= 0 && index < state.warframeBuild.normalMods.length && !state.warframeBuild.normalLocks[index];
  return valid ? { node: target, index } : null;
}
function startPointerModDrag(kind, index, event, slot) {
  if (pointerModDrag || (kind === "weapon" ? state.manualLocks[index] || !state.manualSlots[index] : state.warframeBuild.normalLocks[index] || !state.warframeBuild.normalMods[index])) return;
  event.preventDefault();
  event.stopPropagation();
  modDragSource = { kind, index };
  pointerModDrag = { kind, index, slot, target: null };
  slot.classList.add("is-dragging");
  // 拖拽期间冻结所有 MOD 卡的悬停展开：展开中的镀层/紫卡卡面会把上方
  // 槽位的命中区域整个盖住（卡面 pointer-events:auto），既让 drop 高亮
  // 落到错误的槽位，也会在松手后把展开态留在错误的卡上。
  document.body.classList.add("is-mod-dragging");
  const ghost = createModDragGhost(slot);
  if (ghost) {
    ghost.classList.add("is-pointer-drag");
    ghost.style.left = `${event.clientX - 102}px`;
    ghost.style.top = `${event.clientY - 45}px`;
  }
  pointerModDragMove = (move) => {
    if (!pointerModDrag) return;
    const next = pointerDragTarget(kind, move);
    if (pointerModDrag.target?.node !== next?.node) {
      pointerModDrag.target?.node.classList.remove("is-drop-target");
      pointerModDrag.target = next;
      next?.node.classList.add("is-drop-target");
    }
    if (modDragGhost) {
      modDragGhost.style.left = `${move.clientX - 102}px`;
      modDragGhost.style.top = `${move.clientY - 45}px`;
    }
  };
  pointerModDragEnd = (up) => {
    const drag = pointerModDrag;
    if (!drag) return;
    const target = drag.target || pointerDragTarget(kind, up);
    const shouldSwap = Boolean(target && target.index !== index);
    const targetIndex = target?.index;
    // Clear the active gesture before rendering. Rendering may synchronously
    // replace the source node; leaving this state live makes the next drag
    // look like a rejected nested gesture and Chrome shows the forbidden cursor.
    pointerModDrag = null;
    if (pointerModDragMove) document.removeEventListener("pointermove", pointerModDragMove);
    if (pointerModDragEnd) document.removeEventListener("pointerup", pointerModDragEnd);
    document.removeEventListener("pointercancel", pointerModDragEnd);
    pointerModDragMove = null;
    pointerModDragEnd = null;
    finishModDrag();
    if (shouldSwap) {
      if (kind === "weapon") {
        [state.manualSlots[index], state.manualSlots[targetIndex]] = [state.manualSlots[targetIndex], state.manualSlots[index]];
        ensureCapacityFit();
        renderManualSlots();
        persistActiveBuildConfig();
        scheduleLiveManualSimulation();
      } else {
        const build = state.warframeBuild;
        [build.normalMods[index], build.normalMods[targetIndex]] = [build.normalMods[targetIndex], build.normalMods[index]];
        renderWarframeLoadout();
        persistWarframeConfig();
        scheduleWarframeCalculation();
      }
    }
  };
  document.addEventListener("pointermove", pointerModDragMove);
  document.addEventListener("pointerup", pointerModDragEnd, { once: true });
  document.addEventListener("pointercancel", pointerModDragEnd, { once: true });
}
function removeModDragGhost() {
  modDragGhost?.remove();
  modDragGhost = null;
}
function createModDragGhost(slot) {
  removeModDragGhost();
  const card = slot.querySelector(".mod-slot");
  if (!card) return null;
  const ghost = create("div", "mod-drag-ghost");
  const clone = card.cloneNode(true);
  clone.classList.remove("is-expanded");
  ghost.append(clone);
  document.body.append(ghost);
  modDragGhost = ghost;
  document.addEventListener("dragend", finishModDrag, { once: true });
  window.setTimeout(removeModDragGhost, 4000);
  return ghost;
}

// 槽位签名：覆盖卡面所有可见内容（卡/等级/紫卡词条、槽极性、锁定、等级步进开关、
// 超容量、运行时摘要）。签名一致即复用旧 DOM 节点——图片不重载、入场动画不重播，
// 极化/拖放/功能槽/赋能改动不会再"整排闪一下"。
function manualSlotSignature(mod, index, slotPolarities, capacity) {
  const common = [
    slotPolarities[index] || "none",
    state.manualLocks[index] ? 1 : 0,
    capacity.over ? 1 : 0,
    ui["manual-level-toggle"]?.checked ? 1 : 0,
  ].join("|");
  if (!mod) return `empty|${common}`;
  if (mod.__riven) return `riven|${mod.nameZh || ""}|${JSON.stringify(mod.stats || [])}|${mod.rivenPolarity || ""}|${common}`;
  return `mod|${mod.path}|${Number(mod.rank ?? mod.maxRank ?? 0)}|${common}|${modRuntimeText(mod)}`;
}

function buildManualSlotNode(mod, index, slotPolarities, capacity) {
    const slot = create("article", `manual-slot${index === state.manualSlot ? " is-selected" : ""}${state.manualLocks[index] ? " is-locked" : ""}`);
    slot.dataset.slot = String(index);
    slot.addEventListener("click", () => {
      if (state.manualSlot !== index) {
        const previous = state.manualSlot;
        state.manualSlot = index;
        // 选中态是纯视觉变化：只换 class，不重建整排卡片——全量 replaceChildren
        // 会让 8 张卡的图片销毁重载，看起来就像"整体刷新了一下"。
        const slots = ui["manual-slots"];
        slots?.children[previous]?.classList.remove("is-selected");
        slots?.children[index]?.classList.add("is-selected");
      }
      if (!state.manualLocks[index]) openModPicker(index);
      else toast("当前槽位已锁定，先解锁再更换 MOD");
    });
    slot.addEventListener("dragover", (event) => {
      const from = dragSourceIndex("weapon", event);
      if (!Number.isInteger(from) || from === index || !state.manualSlots[from] || state.manualLocks[from] || state.manualLocks[index]) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      slot.classList.add("is-drop-target");
    });
    slot.addEventListener("dragenter", (event) => {
      const from = dragSourceIndex("weapon", event);
      if (!Number.isInteger(from) || from === index || !state.manualSlots[from] || state.manualLocks[from] || state.manualLocks[index]) return;
      event.preventDefault();
    });
    slot.addEventListener("dragleave", () => slot.classList.remove("is-drop-target"));
    slot.addEventListener("drop", (event) => {
      event.preventDefault();
      slot.classList.remove("is-drop-target");
      const from = dragSourceIndex("weapon", event);
      if (!Number.isInteger(from) || from === index || !state.manualSlots[from] || state.manualLocks[from] || state.manualLocks[index]) return;
      [state.manualSlots[from], state.manualSlots[index]] = [state.manualSlots[index], state.manualSlots[from]];
      ensureCapacityFit();
      renderManualSlots(); persistActiveBuildConfig(); scheduleLiveManualSimulation();
    });
    if (!mod) {
      const empty = create("button", "manual-slot-empty-card");
      empty.type = "button";
      const pol = slotPolarities[index];
      empty.append(create("span", "manual-slot-empty-plus", "＋"), create("small", "", `槽位 ${index + 1}`));
      if (pol && pol !== "AP_UNIVERSAL") {
        const polIcon = POLARITY_IMAGES[pol]
          ? imageNode(POLARITY_IMAGES[pol], "empty-slot-polarity", "", "lazy")
          : create("i", "empty-slot-polarity empty-slot-polarity-glyph", "○");
        polIcon.title = `槽位极性 ${POLARITY_NAMES[pol] || pol}${state.formaSlots[index] ? "（已极化）" : ""}`;
        empty.append(polIcon);
      }
      empty.addEventListener("click", (event) => { event.stopPropagation(); state.manualSlot = index; renderManualSlots(); openModPicker(index); });
      slot.append(empty, slotPolarityChip(index, capacity.perSlot[index]));
      return slot;
    }
    const preview = mod.__riven ? createCustomRivenSlotCard(mod, index, slotPolarities[index]) : createNormalModCard(mod, index + 1, { slotPolarity: slotPolarities[index] });
    preview.classList.add("manual-slot-preview");
    slot.append(preview, slotPolarityChip(index, capacity.perSlot[index]));
    const runtimeText = modRuntimeText(mod);
    if (runtimeText) slot.append(create("p", "mod-runtime-summary", runtimeText));
    if (!mod.__riven && capacity.over) preview.classList.add("is-over-capacity");
    if (!mod.__riven) {
      // 右键 / 长按已装备的卡：禁选或全局屏蔽时顺手把它从槽位剔除，
      // 自动配装随即按新约束重算。
      bindScopeModMenu(slot, mod, (kind, wasActive) => {
        if (kind === "required" || wasActive || state.manualSlots[index]?.path !== mod.path) return;
        if (state.manualLocks[index]) { toast("槽位已锁定，已加入屏蔽但未移除"); return; }
        state.manualSlots[index] = null;
        renderManualSlots();
        persistActiveBuildConfig();
      });
    }
    // 紫卡槽同样给调整工具栏（拖动/锁定/移除）；等级步进不适用——
    // 自定义紫卡词条数值由编辑器直接给出，没有等级缩放。
    const actions = create("div", "manual-slot-actions");
    const drag = create("button", "manual-slot-drag", "⋮⋮");
    drag.type = "button";
    drag.title = "拖动槽位";
    drag.setAttribute("aria-label", "拖动槽位");
    drag.draggable = true;
    drag.addEventListener("click", (event) => event.stopPropagation());
    drag.addEventListener("pointerdown", (event) => event.stopPropagation());
    drag.addEventListener("pointerdown", (event) => startPointerModDrag("weapon", index, event, slot));
    drag.addEventListener("dragstart", (event) => {
      if (state.manualLocks[index] || !state.manualSlots[index]) { event.preventDefault(); return; }
      beginModDrag("weapon", index, event, slot);
    });
    drag.addEventListener("dragend", () => {
      finishModDrag();
    });
    actions.append(drag);
    if (!mod.__riven && ui["manual-level-toggle"]?.checked) {
      const maxRank = Number(mod.maxRank ?? 0);
      const currentRank = () => clamp(Number(mod.rank ?? mod.maxRank ?? 0), 0, maxRank);
      const rankStepper = create("div", "rank-stepper");
      rankStepper.title = "调整 MOD 等级";
      const applyRank = (next) => {
        next = clamp(next, 0, maxRank);
        const before = currentRank();
        if (next === before) return;
        mod.rank = next;
        const { fits, polarized } = ensureCapacityFit();
        if (!fits) {
          mod.rank = before;
          renderManualSlots();
          toast(`容量不足：升到 ${next} 级后即使全部极化也装不下`);
          return;
        }
        renderManualSlots();
        if (polarized) toast(`已自动极化 ${polarized} 个槽位以容纳该等级`);
        persistActiveBuildConfig();
        scheduleLiveManualSimulation();
      };
      const rankDec = create("button", "rank-stepper-btn", "−");
      rankDec.type = "button";
      rankDec.title = "降低一级";
      rankDec.disabled = currentRank() <= 0;
      const rankValue = create("span", "rank-stepper-value", `${currentRank()}/${maxRank}`);
      const rankInc = create("button", "rank-stepper-btn", "+");
      rankInc.type = "button";
      rankInc.title = "提升一级";
      rankInc.disabled = currentRank() >= maxRank;
      [rankDec, rankInc].forEach((btn) => {
        btn.addEventListener("click", (event) => { event.stopPropagation(); applyRank(currentRank() + (btn === rankInc ? 1 : -1)); });
        btn.addEventListener("pointerdown", (event) => event.stopPropagation());
      });
      rankStepper.append(rankDec, rankValue, rankInc);
      actions.append(rankStepper);
    }
    const lock = create("button", "manual-slot-lock", state.manualLocks[index] ? "解锁" : "锁定");
    lock.type = "button";
    lock.title = state.manualLocks[index] ? "解锁槽位" : "锁定槽位";
    lock.addEventListener("click", (event) => { event.stopPropagation(); state.manualLocks[index] = !state.manualLocks[index]; renderManualSlots(); });
    const remove = create("button", "manual-slot-remove", "移除");
    remove.type = "button";
    remove.title = "移除 MOD";
    remove.addEventListener("click", (event) => { event.stopPropagation(); if (!state.manualLocks[index]) { state.manualSlots[index] = null; renderManualSlots(); persistActiveBuildConfig(); scheduleLiveManualSimulation(); } });
    actions.append(lock, remove);
    slot.append(actions);
    return slot;
}

function renderManualSlots() {
  const slotPolarities = weaponSlotPolarities();
  const capacity = computeCapacity();
  const container = ui["manual-slots"];
  const existing = Array.from(container.children);
  // 逐位 diff：签名一致的槽位复用旧节点（不离开 DOM，零闪烁）；只有内容真正
  // 变化的槽位才重建。replaceChild 逐位进行，节点永不换位（槽位本就是按下标定位）。
  state.manualSlots.forEach((mod, index) => {
    const signature = manualSlotSignature(mod, index, slotPolarities, capacity);
    const prev = existing[index];
    if (prev && prev.dataset.signature === signature) return;
    const node = buildManualSlotNode(mod, index, slotPolarities, capacity);
    node.dataset.signature = signature;
    if (prev) container.replaceChild(node, prev);
    else container.append(node);
  });
  // 复用节点可能带旧的选中态，统一按 state 校准（纯 class 操作，不重排）
  Array.from(container.children).forEach((node, index) => {
    node.classList.toggle("is-selected", index === state.manualSlot);
  });
  // 收益角标就地补绘（新节点上的角标是 hidden 占位）
  paintEquippedGains();
  ui["manual-build-summary"].textContent = state.buildInputMode === "auto"
    ? "自动配置会搜索并回填槽位"
    : `${state.manualSlots.filter(Boolean).length}/${state.manualSlots.length} 已选 · 点击空槽选择 MOD`;
  renderCapacityBar();
}

function openModPicker(slotIndex) {
  if (!ui["mod-picker"] || state.buildInputMode === "auto") return;
  state.modPickerKind = "normal";
  state.modPickerSlot = clamp(Number(slotIndex) || 0, 0, state.manualSlots.length - 1);
  // 紫卡构建器的极性默认取该槽已有紫卡的极性（没有时再随机）。
  state.rivenBuilderPolarity = state.manualSlots[state.modPickerSlot]?.__riven
    ? rivenFixedPolarity(state.manualSlots[state.modPickerSlot], state.modPickerSlot)
    : null;
  ui["mod-picker"].classList.remove("is-special-picker");
  if (ui["mod-picker-title"]) ui["mod-picker-title"].textContent = "选择 MOD";
  ui["mod-picker-sub"].textContent = `填充到槽位 ${state.modPickerSlot + 1}`;
  ui["mod-picker"].hidden = false;
  ui["mod-picker-scrim"].hidden = false;
  document.body.classList.add("is-modal-open");
  renderManualMods();
  ui["manual-mod-search"]?.focus();
  scheduleModGains();
}

function openSpecialModPicker(kind) {
  if (!ui["mod-picker"] || state.buildInputMode === "auto") return;
  if (kind === "stance" && state.stanceLocked) return toast("显赫武器使用天生架势，不能更换");
  state.modPickerKind = kind === "stance" ? "stance" : "exilus";
  ui["mod-picker"].classList.add("is-special-picker");
  if (ui["mod-picker-title"]) ui["mod-picker-title"].textContent = state.modPickerKind === "stance" ? "选择架势" : "选择功能槽 MOD";
  ui["mod-picker-sub"].textContent = state.modPickerKind === "stance" ? "仅显示当前近战兼容架势" : "仅显示当前武器兼容功能卡";
  ui["mod-picker"].hidden = false;
  ui["mod-picker-scrim"].hidden = false;
  document.body.classList.add("is-modal-open");
  if (ui["manual-mod-search"]) ui["manual-mod-search"].value = "";
  renderManualMods();
  ui["manual-mod-search"]?.focus();
}

let modGainsRequestId = 0;
let equippedGainsRequestId = 0;
// 实时请求带「频道 + 序号」：同一页面同一类请求来了新的，后端就跳过还在排队的旧请求、
// 中止正在跑的旧搜索（否则每次改动都要排队算完一遍再被丢弃）。频道按页面区分。
const LIVE_PAGE_ID = Math.random().toString(36).slice(2, 10);
function liveTag(kind, seq) {
  return { liveChannel: `${LIVE_PAGE_ID}:${kind}`, liveSeq: seq };
}
let modGainsTimer = null;
let modGainsSignature = "";

function modGainsPayload() {
  try {
    return buildPayloadFromForm();
  } catch (_error) {
    return null;
  }
}

function scheduleModGains() {
  // Debounced: rapid category/search changes coalesce into one request; the
  // backend cache makes repeated identical payloads free.
  window.clearTimeout(modGainsTimer);
  modGainsTimer = window.setTimeout(() => { modGainsTimer = null; runModGains(); }, 300);
}

async function runModGains() {
  if (state.modPickerKind !== "normal") return;
  const requestId = ++modGainsRequestId;
  const payload = modGainsPayload();
  if (!payload) return;
  const rows = manualModRecords();
  const candidates = rows.slice(0, 80).map((mod) => mod.path);
  if (!candidates.length) return;
  const targetSlot = state.modPickerSlot;
  // 签名必须覆盖全部影响解算的载荷字段（2026-09-24 修复）：arcanes 缺席
  // 导致「加赋能后重开选择器」命中旧签名跳过重取——贡献是旧赋能语境的。
  const signature = JSON.stringify([payload, targetSlot, candidates.slice().sort()]);
  if (signature === modGainsSignature && state.modGains && Object.keys(state.modGains).length) {
    paintModGains();
    return;
  }
  try {
    const response = await fetch("/api/mod-gains", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, candidates, targetSlot, ...liveTag("mod-gains", requestId) }),
    });
    const body = await response.json();
    if (!response.ok || requestId !== modGainsRequestId) return;
    if (state.modPickerSlot !== targetSlot || ui["mod-picker"].hidden) return;
    state.modGains = body.gains || {};
    modGainsSignature = signature;
    paintModGains();
    if (state.modGainsSort) renderManualMods();
  } catch (_error) {
    /* gains are an enhancement; failures stay silent */
  }
}

async function scheduleEquippedGains() {
  const requestId = ++equippedGainsRequestId;
  const payload = modGainsPayload();
  if (!payload) return;
  // 装备贡献候选：MOD + 紫卡 + 已配赋能（__arcane__:<path> 通道，后端移除
  // 该赋能测损失）。赋能随 buildPayloadFromForm 的 arcanes 字段一起下发。
  const equipped = state.manualSlots.filter(Boolean).map((mod) => mod.__riven ? "__riven__" : mod.path);
  const arcaneKeys = (payload.arcanes || []).filter(Boolean).map((item) => `__arcane__:${item.path}`);
  const allCandidates = [...equipped, ...arcaneKeys];
  if (!allCandidates.length) { state.equippedGains = null; paintEquippedGains(); return; }
  try {
    const response = await fetch("/api/mod-gains", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, candidates: allCandidates, mode: "equipped", ...liveTag("equipped-gains", requestId) }),
    });
    const body = await response.json();
    if (!response.ok || requestId !== equippedGainsRequestId) return;
    state.equippedGains = body.gains || {};
    paintEquippedGains();
  } catch (_error) {
    /* equipped gains are an enhancement; failures stay silent */
  }
}

function paintEquippedGains() {
  const gains = state.equippedGains || {};
  const renderBadge = (host, info, { negate = true, capacityHint = false } = {}) => {
    let badge = host.querySelector(".mod-gain-badge");
    if (!badge) {
      badge = create("div", "mod-gain-badge");
      host.append(badge);
    }
    if (!info || info.gainPercent === null || info.gainPercent === undefined) {
      // 有明确原因的（超容量等）显示短标签而不是隐藏——用户需要知道为什么没数字。
      if (capacityHint && info?.reason === "over-capacity") {
        badge.hidden = false;
        badge.textContent = "超容量";
        badge.classList.add("is-negative");
        badge.title = `换入后容量 ${info.capacity} / ${info.capacityLimit}：装不下`;
        return;
      }
      badge.hidden = true;
      badge.removeAttribute("title");
      return;
    }
    // equipped mode returns (without - with); contribution is the negation
    const percent = negate ? -Number(info.gainPercent) : Number(info.gainPercent);
    badge.hidden = false;
    badge.textContent = `${percent >= 0 ? "+" : ""}${percent.toFixed(1)}%`;
    badge.classList.toggle("is-negative", percent < 0);
    badge.removeAttribute("title");
  };
  document.querySelectorAll("#manual-slots .game-mod-card").forEach((card) => {
    const slot = card.closest(".manual-slot");
    const index = Number(slot?.dataset.slot);
    const mod = state.manualSlots[index];
    if (!mod) return;
    const key = mod.__riven ? "__riven__" : mod.path;
    renderBadge(card, gains[key], { negate: true });
  });
  // 赋能槽贡献徽章（__arcane__ 通道）：与 MOD 同一增益服务。
  document.querySelectorAll("#build-arcane-list .arcane-option, #build-arcane-list [data-arcane-path]").forEach((node) => {
    const path = node.dataset.arcanePath || node.closest("[data-arcane-path]")?.dataset.arcanePath;
    if (!path) return;
    const info = gains[`__arcane__:${path}`];
    if (!info) return;
    let badge = node.querySelector(".mod-gain-badge");
    if (!badge) {
      badge = create("div", "mod-gain-badge arcane-gain-badge");
      node.append(badge);
    }
    if (info.gainPercent === null || info.gainPercent === undefined) {
      badge.hidden = true;
      return;
    }
    const percent = -Number(info.gainPercent);
    badge.hidden = false;
    badge.textContent = `${percent >= 0 ? "+" : ""}${percent.toFixed(1)}%`;
    badge.classList.toggle("is-negative", percent < 0);
  });
}

function paintModGains() {
  const gains = state.modGains || {};
  const target = ui["manual-mod-list"];
  if (!target) return;
  target.querySelectorAll(".manual-mod-option").forEach((option) => {
    const card = option.querySelector(".game-mod-card") || option;
    const path = option.dataset.modPath;
    const gainInfo = gains[path];
    let badge = card.querySelector(".mod-gain-badge");
    if (!badge) {
      badge = create("div", "mod-gain-badge");
      card.append(badge);
    }
    if (!gainInfo || gainInfo.gainPercent === null || gainInfo.gainPercent === undefined) {
      if (gainInfo?.reason === "over-capacity") {
        badge.hidden = false;
        badge.textContent = "超容量";
        badge.classList.add("is-negative");
        badge.title = `换入后容量 ${gainInfo.capacity} / ${gainInfo.capacityLimit}：装不下`;
        return;
      }
      badge.hidden = true;
      badge.removeAttribute("title");
      return;
    }
    const percent = Number(gainInfo.gainPercent);
    badge.hidden = false;
    badge.textContent = `${percent >= 0 ? "+" : ""}${percent.toFixed(1)}%`;
    badge.classList.toggle("is-negative", percent < 0);
    // 超容量但显示贡献（2026-09-24 口径）：数值照排，附加装配受限提示。
    badge.removeAttribute("title");
    if (gainInfo.reason === "over-capacity") {
      badge.title = `贡献 ${percent >= 0 ? "+" : ""}${percent.toFixed(1)}%（当前装不下：容量 ${gainInfo.capacity} / ${gainInfo.capacityLimit}）`;
    }
  });
}

function closeModPicker() {
  if (!ui["mod-picker"] || ui["mod-picker"].hidden) return;
  modGainsRequestId += 1;
  hideModPreview();
  ui["mod-picker"].hidden = true;
  ui["mod-picker-scrim"].hidden = true;
  document.body.classList.remove("is-modal-open");
  const query = ui["manual-mod-search"]?.value || "";
  state.modPickerKind = "normal";
  ui["mod-picker"].classList.remove("is-special-picker");
  if (query) ui["manual-mod-search"].value = "";
}

function resultBuildView(result) {
  const stats = result?.moddedStats || {};
  const target = result?.targetDamage || {};
  const mods = Array.isArray(result?.build?.mods)
    ? result.build.mods
    : (Array.isArray(result?.selection?.mods) ? result.selection.mods : []);
  return {
    ...(result?.build || {}),
    mods,
    includesRiven: result?.build?.includesRiven === true,
    damageTypes: result?.build?.damageTypes || stats.damageTypes || stats.damage_types || {},
    shotDamage: result?.build?.shotDamage ?? target.perShot,
    burstDps: result?.build?.burstDps ?? stats.burstDps ?? stats.burst_dps,
    sustainedDps: result?.build?.sustainedDps ?? target.dps ?? stats.sustainedDps ?? stats.sustained_dps,
    attackDps: result?.build?.attackDps ?? target.dps,
    rivenLines: result?.build?.rivenLines || [],
  };
}

// Manual edits: polarization is an OUTPUT of the build, not a constraint on
// it. When the loadout exceeds capacity, add the fewest Forma that make it fit
// (cards stay where the user put them). Nothing changes when it cannot fit.
// Returns { fits, polarized }.
function ensureCapacityFit() {
  if (!computeCapacity().over) return { fits: true, polarized: 0 };
  const plan = workbenchFormaPlan();
  if (!plan.fits) return { fits: false, polarized: 0 };
  applyFormaPlan(plan);
  return { fits: !computeCapacity().over, polarized: plan.formas };
}

function applyModToPickerSlot(mod) {
  if (state.modPickerKind === "sentinel") return applySentinelMod(mod);
  if (state.modPickerKind !== "normal") return applySpecialMod(mod);
  const slot = state.modPickerSlot;
  if (state.manualLocks[slot]) return toast("当前槽位已锁定");
  const candidate = { ...mod, rank: ui["manual-level-toggle"]?.checked === false ? 0 : (mod.rank ?? mod.maxRank ?? 0) };
  // 同名互斥：镀层/普通/Prime 同家族卡（如镀层步枪才能与步枪才能）一张配装
  // 只能带一张——选择器已隐藏，这里兜底拦截（防止填充/导入路径绕过）。
  const candidateFamily = modExclusiveFamily(candidate);
  if (candidateFamily) {
    const conflict = state.manualSlots.some((item, index) => item && index !== slot && item.path !== candidate.path && modExclusiveFamily(item) === candidateFamily);
    if (conflict) return toast("同名 MOD（镀层/普通/Prime）一张配装只能携带一张");
  }
  const previous = state.manualSlots[slot] || null;
  state.manualSlots[slot] = candidate;
  const { fits, polarized } = ensureCapacityFit();
  if (!fits) {
    state.manualSlots[slot] = previous;
    toast("容量不足：即使极化全部槽位也装不下这张 MOD，请降低等级或移除其他 MOD");
    return;
  }
  renderManualSlots();
  persistActiveBuildConfig();
  scheduleLiveManualSimulation();
  closeModPicker();
  if (polarized) toast(`容量不足，已自动极化 ${polarized} 个槽位来容纳该 MOD`);
}

function modPickerCard(mod, kind = state.modPickerKind) {
  const isWarframe = state.activeTool === "warframe" && ["normal", "aura", "exilus"].includes(kind);
  const card = isWarframe
    ? createNormalModCard({ ...mod, rank: mod.maxRank ?? mod.rank ?? 0 }, 0, {
      compact: true,
      compatLabel: warframeCompatLabel(mod),
      slotMarker: warframeSlotMarker(mod),
      slotMarkerLabel: warframeModKind(mod) === "aura" ? "光环 MOD" : "功能槽 MOD",
      ...(kind !== "normal" ? { slotPolarity: state.warframeBuild.slotPolarities[kind] } : {}),
    })
    : kind === "normal"
      ? createNormalModCard({ ...mod, rank: mod.maxRank ?? mod.rank ?? 0 }, 0, { compact: true, compatLabel: modCompatLabel(mod, modAssetFields(mod)) })
      : kind === "sentinel"
        ? createNormalModCard({ ...mod, rank: mod.maxRank ?? 0 }, 0, { compact: true, compatLabel: mod.exclusiveTo ? "专属守则" : (mod.kind === "precept" ? "守护守则" : "守护") })
        : createSpecialModCard(mod, kind, true, weaponSpecialSlotPolarity(kind));
  card.classList.add("manual-option-card");
  card.querySelector(".slot-number")?.remove();
  return card;
}

function applySpecialMod(mod) {
  if (state.modPickerKind === "stance") {
    if (state.stanceLocked) return toast("显赫武器使用天生架势，不能更换");
    state.stanceSelection = stanceSelectionWithSlot(mod, { rank: Number(mod.maxRank ?? 0) });
  } else {
    const maxRank = Number(mod.maxRank ?? mod.rank ?? 0);
    state.exilusSelection = { ...mod, maxRank, rank: maxRank };
  }
  renderSpecialSlots();
  persistActiveBuildConfig();
  scheduleLiveManualSimulation();
  closeModPicker();
}

let modPreviewElement = null;
function hideModPreview() {
  if (modPreviewElement) { modPreviewElement.remove(); modPreviewElement = null; }
}

function showModPreview(mod, anchor, kind = state.modPickerKind) {
  if (!matchMedia("(hover: hover)").matches) return;
  hideModPreview();
  const preview = create("div", "mod-preview-pop");
  const warframePicker = state.activeTool === "warframe"
    && !ui["warframe-picker"]?.hidden
    && ["normal", "aura", "exilus"].includes(kind);
  const card = warframePicker
    ? createNormalModCard({ ...mod, rank: mod.rank ?? mod.maxRank ?? 0 }, 0, {
      compact: false,
      compatLabel: warframeCompatLabel(mod),
      slotMarker: warframeSlotMarker(mod),
      slotMarkerLabel: warframeModKind(mod) === "aura" ? "光环 MOD" : "功能槽 MOD",
      ...(kind !== "normal" ? { slotPolarity: state.warframeBuild.slotPolarities[kind] } : {}),
    })
    : kind === "normal"
      ? createNormalModCard({ ...mod, rank: mod.rank ?? mod.maxRank ?? 0 }, 0, { compact: false, compatLabel: modCompatLabel(mod, modAssetFields(mod)) })
      : kind === "sentinel"
        ? createNormalModCard({ ...mod, rank: mod.maxRank ?? 0 }, 0, { compact: false, compatLabel: mod.exclusiveTo ? "专属守则" : (mod.kind === "precept" ? "守护守则" : "守护") })
        : createSpecialModCard(mod, kind, false, weaponSpecialSlotPolarity(kind));
  card.querySelector(".slot-number")?.remove();
  card.querySelector(".game-mod-card")?.classList.add("is-expanded");
  preview.append(card);
  document.body.append(preview);
  modPreviewElement = preview;
  const rect = anchor.getBoundingClientRect();
  const cardRect = preview.querySelector(".game-mod-card")?.getBoundingClientRect() || { width: 184, height: 260 };
  const expandedW = Math.min(cardRect.width * 1.1, 320);
  let left = rect.right + 12;
  if (left + expandedW > window.innerWidth - 8) left = Math.max(8, rect.left - expandedW - 12);
  let top = rect.top - 20;
  const maxTop = window.innerHeight - 300;
  top = Math.max(8, Math.min(top, maxTop));
  preview.style.left = `${left}px`;
  preview.style.top = `${top}px`;
  // expand immediately inside the preview
  requestAnimationFrame(() => preview.classList.add("is-open"));
}

function bindModPreview(option, mod, kind = state.modPickerKind) {
  option.addEventListener("mouseenter", () => showModPreview(mod, option, kind));
  option.addEventListener("mouseleave", hideModPreview);
  option.addEventListener("focus", () => showModPreview(mod, option, kind));
  option.addEventListener("blur", hideModPreview);
}

let scopeMenuElement = null;

function closeScopeMenu() {
  scopeMenuElement?.remove();
  scopeMenuElement = null;
}

function bindScopeModMenu(option, mod, after) {
  const open = (x, y) => {
    closeScopeMenu();
    hideModPreview();
    const menu = create("div", "scope-context-menu");
    menu.append(...scopeMenuButtons(mod.path, after));
    menu.style.left = `${Math.min(x, window.innerWidth - 170)}px`;
    menu.style.top = `${Math.min(y, window.innerHeight - 130)}px`;
    document.body.append(menu);
    scopeMenuElement = menu;
    // 点击任意处关闭
    setTimeout(() => {
      document.addEventListener("pointerdown", function handler(event) {
        if (!menu.contains(event.target)) {
          closeScopeMenu();
          document.removeEventListener("pointerdown", handler);
        }
      }, { once: false });
    }, 0);
  };
  option.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    open(event.clientX, event.clientY);
  });
  // 长按（触屏）：500ms 未松手即打开
  let pressTimer = null;
  option.addEventListener("pointerdown", (event) => {
    if (event.pointerType === "mouse") return;
    pressTimer = window.setTimeout(() => { pressTimer = null; open(event.clientX, event.clientY); }, 500);
  });
  const cancel = () => { if (pressTimer) { window.clearTimeout(pressTimer); pressTimer = null; } };
  option.addEventListener("pointerup", cancel);
  option.addEventListener("pointercancel", cancel);
  option.addEventListener("pointerleave", cancel);
}

function renderManualMods() {
  // createNormalModCard remains the single source for card geometry/assets.
  renderManualModCategories();
  const target = ui["manual-mod-list"];
  if (!target) return;
  if (state.manualModCategory === "__riven__") {
    renderRivenBuilder(target);
    return;
  }
  const rows = manualModRecords();
  const isGrid = state.modPickerView === "grid";
  target.className = `mod-picker-grid${isGrid ? "" : " is-list"}`;
  const nodes = rows.map((mod) => {
    const option = create(isGrid ? "button" : "button", "manual-mod-option");
    option.type = "button";
    option.setAttribute("role", "option");
    option.dataset.modPath = mod.path;
    if (isGrid) {
      option.append(modPickerCard(mod, state.modPickerKind));
    } else {
      const copy = create("span", "manual-option-copy");
      copy.append(
        create("strong", "", manualModLabel(mod)),
        create("small", "", state.modPickerKind === "normal"
          ? `${MOD_CATEGORY_LABELS[modCategory(mod)] || "其他"} · ${mod.maxRank ?? "?"} 级 · 容量 ${modBaseDrain({ ...mod, rank: mod.maxRank ?? mod.rank ?? 0 })}`
          : specialModSummary(mod, state.modPickerKind)),
      );
      const effectRow = create("em", "manual-option-effects");
      for (const line of modEffectLines({ ...mod, rank: mod.maxRank ?? mod.rank ?? 0 }).slice(0, 4)) {
        const chip = create("span", "effect-chip");
        if (line.icon) chip.append(imageNode(line.icon, "effect-chip-icon", "", "lazy"));
        chip.append(document.createTextNode(`${line.label} ${line.value === undefined ? "" : `${line.value >= 0 ? "+" : ""}${(line.value * 100).toFixed(1)}%`}`));
        effectRow.append(chip);
      }
      if (mod.modSet && !isSacrificeSetMod(mod)) {
        const chip = create("span", "effect-chip is-set");
        chip.append(create("i", "effect-chip-dot"), document.createTextNode(modSetText(mod) || "套装卡"));
        effectRow.append(chip);
      }
      if (state.modPickerKind !== "normal" && mod.description) {
        const chip = create("span", "effect-chip is-description", String(mod.description).replace(/<[^>]+>/g, ""));
        effectRow.append(chip);
      }
      if (!effectRow.childNodes.length) effectRow.append(document.createTextNode("暂无效果说明"));
      copy.append(effectRow);
      option.append(copy);
    }
    bindModPreview(option, mod, state.modPickerKind);
    // Legacy call signature is intentionally retained for compatibility with
    // extensions that monkey-patch the picker preview hook.
    // bindModPreview(option, mod);
    option.addEventListener("click", () => { hideModPreview(); applyModToPickerSlot(mod); });
    if (state.modPickerKind === "normal") {
      // 右键 / 长按 → 必选/禁选菜单（「限制」面板的入口）。
      bindScopeModMenu(option, mod);
      if (state.requiredMods.includes(mod.path)) option.classList.add("is-scope-required");
      if (state.forbiddenMods.includes(mod.path) || state.globalForbiddenMods.includes(mod.path)) option.classList.add("is-scope-forbidden");
    }
    return option;
  });
  target.replaceChildren(...(nodes.length ? nodes : [create("p", "empty-copy", "没有符合条件的 MOD")]));
  if (state.modPickerKind === "normal") paintModGains();
}

function fillManualFromResult(result) {
  const mods = Array.isArray(result?.build?.mods) ? result.build.mods : (Array.isArray(result?.selection?.mods) ? result.selection.mods : []);
  const records = new Map([...(state.catalog?.manualMods || []), ...(state.catalog?.manualModVariants || [])].map((mod) => [mod.path, mod]));
  const aliases = state.catalog?.manualModAliases || {};
  state.manualSlots = Array.from({ length: 8 }, (_, index) => {
    const mod = mods.find((candidate, position) => (Number.isInteger(candidate?.slot) ? candidate.slot : position) === index);
    if (!mod?.path) return null;
    // Solver may reference a progression variant (Beginner/Intermediate/Expert);
    // resolve to the canonical card so the slot never silently drops the pick.
    const record = records.get(mod.path) || records.get(aliases[mod.path]) || mod;
    const maxRank = Number(mod.maxRank ?? record.maxRank ?? record.rank ?? 0);
    const rank = clamp(Number(mod.rank ?? record.rank ?? maxRank), 0, maxRank);
    return { ...record, ...mod, path: record.path || mod.path, maxRank, rank };
  });
  const riven = result?.build?.riven;
  if (riven && Array.isArray(riven.stats) && Number.isInteger(riven.slot)) {
    state.manualSlots[riven.slot] = { __riven: true, nameZh: "紫卡", stats: riven.stats.map(x => ({...x})), rivenPolarity: riven.polarity || "AP_ATTACK" };
  }
  fillSpecialFromResult(result);
  syncAutoFormaFromSlots();
  renderManualSlots();
}

function modPolarity(mod, slotIndex = 0) {
  return modPolarityOf(mod, slotIndex);
}

// Solver results score every card as if it sat in a matching slot; give the
// filled build the fewest Forma that actually fit it (elements keep order).
function syncAutoFormaFromSlots() {
  applyMinimalForma();
}

function fillSpecialFromResult(result) {
  const source = result?.build || result?.selection || result || {};
  const read = (key) => source[key] ?? result?.[key];
  const stanceValue = read("stance");
  const stancePath = read("stancePath") || stanceValue?.path;
  if (!state.stanceLocked && stancePath) {
    const stance = stanceRecords().find((item) => item.path === stancePath);
    if (stance && stanceMatchesBuildWeapon(stance)) {
      state.stanceSelection = stanceSelectionWithSlot(stance, {
        ...(stanceValue && typeof stanceValue === "object" ? stanceValue : {}),
        path: stance.path,
        rank: Number(stanceValue?.rank ?? stance.maxRank ?? stance.rank ?? 0),
        maxRank: Number(stanceValue?.maxRank ?? stance.maxRank ?? stance.rank ?? 0),
      });
    }
  }
  if (Object.hasOwn(source, "exilus") || Object.hasOwn(result || {}, "exilus")) {
    state.exilusSelection = hydrateRankedSelection(read("exilus"), utilityModRecords(), state.buildWeapon?.specialSlots?.exilus?.kind || "weapon");
  }
  if (Object.hasOwn(source, "weaponArcane") || Object.hasOwn(result || {}, "weaponArcane")) {
    state.weaponArcane = hydrateRankedSelection(read("weaponArcane"), arcaneRecords(), "weapon");
  }
  if (weaponArcaneSlotCount() > 1 && (Object.hasOwn(source, "weaponArcane2") || Object.hasOwn(result || {}, "weaponArcane2"))) {
    state.weaponArcane2 = hydrateRankedSelection(read("weaponArcane2"), arcaneRecords(), "weapon");
  }
  if (Array.isArray(read("frameArcanes"))) {
    const frames = read("frameArcanes").slice(0, 2).map((item) => hydrateRankedSelection(item, arcaneRecords(), "warframe"));
    state.frameArcanes = [frames[0] || null, frames[1] || null];
  } else if (Array.isArray(read("arcanes"))) {
    const selected = normalizeArcaneSelections(read("arcanes"));
    state.weaponArcane = hydrateRankedSelection(selected.find((item) => item.slotKind !== "warframe"), arcaneRecords(), "weapon");
    if (weaponArcaneSlotCount() > 1) state.weaponArcane2 = hydrateRankedSelection(selected.filter((item) => item.slotKind !== "warframe")[1], arcaneRecords(), "weapon");
    const frames = selected.filter((item) => item.slotKind === "warframe").slice(0, 2).map((item) => hydrateRankedSelection(item, arcaneRecords(), "warframe"));
    state.frameArcanes = [frames[0] || null, frames[1] || null];
  }
  syncArcaneSelections();
  renderSpecialSlots();
  renderArcaneSelections();
}

function scheduleLiveBuild() {
  const assemblyWeapon = String(state.buildWeapon?.nameEn || "").trim() === "Kitgun" || isZawBase(state.buildWeapon);
  const usable = state.buildWeapon?.available === true || (assemblyWeapon && assemblyWeaponReady());
  if (!usable) return;
  if (!assemblyWeapon && state.buildWeapon.buildAvailable === false) return;
  window.clearTimeout(state.liveTimer);
  state.liveTimer = window.setTimeout(() => {
    state.liveTimer = null;
    submitWeaponBuild(null, true);
  }, state.buildInputMode === "manual" ? 240 : 420);
}

const scheduleLiveManualSimulation = scheduleLiveBuild;

function renderProbabilityVisual(probability) {
  return;
}

function renderStatusBreakdown(source) {
  const procs = source?.statusProcs || {};
  const statusDamage = source?.statusDamage || {};
  const dot = statusDamage?.dot || source?.dot || {};
  const nonDot = statusDamage?.nonDot || {};
  const steady = source?.statusSustained || {};
  const dotPerType = dot?.perType || {};
  const nonDotPerType = nonDot?.perType || {};
  const codes = [...new Set([...Object.keys(procs), ...Object.keys(dotPerType), ...Object.keys(nonDotPerType)])];
  const target = ui["probability-content"];
  if (!target) return;
  if (!codes.length) { target.replaceChildren(create("p", "empty-copy", "当前配装不会触发异常状态")); return; }
  const totalExpected = codes.reduce((sum, code) => sum + Math.max(Number(procs[code]) || 0, 0), 0);
  const wrap = create("div", "status-breakdown");
  wrap.append(create("h4", "status-breakdown-title", "异常触发与持续伤害"));
  // 口径标注（R2 API 分层）：本块的「稳态」数字来自闭式稳态模型
  // （sustained_status_damage），与战斗演算块的步进窗口模型
  // （windowed_status_damage，KPM/回放数据源）口径不同——闭式假设触发
  // 已满层，步进从零层爬升并逐 tick 重读护甲/病毒。排序参考一致，
  // 绝对值以演算块为准。
  const note = create("p", "status-breakdown-note", "稳态口径：假设触发满层（闭式）；战斗演算块为逐 tick 步进口径，绝对值以演算块为准");
  wrap.append(note);
  const rows = codes.map((code) => {
    const chance = Number(procs[code]) || 0;
    const share = totalExpected > 0 ? (Math.max(chance, 0) / totalExpected) : 0;
    const dotInfo = dotPerType[code];
    const nonDotInfo = nonDotPerType[code];
    const row = create("div", `status-row${dotInfo || nonDotInfo ? " has-dot" : ""}`);
    const icon = ELEMENT_ICONS[code] ? imageNode(ELEMENT_ICONS[code], "status-row-icon", "", "lazy") : create("i", "status-row-icon");
    const name = create("strong", "", DAMAGE_TYPE_LABELS[code] || code.replace(/^DT_/, ""));
    const chanceEl = create("b", "status-row-chance", chance ? `${(chance * 100).toFixed(1)}%` : "—");
    chanceEl.title = `每次攻击期望触发 ${chance.toFixed(3)} 次${totalExpected > 0 ? ` · 占比 ${(share * 100).toFixed(1)}%` : ""}`;
    row.append(icon, name, chanceEl);
    const detail = create("span", "status-row-dot");
    if (totalExpected > 0) detail.append(create("i", "", `占比 ${(share * 100).toFixed(1)}%`));
    if (dotInfo) {
      detail.append(
        create("i", "", `单次触发 ${formatMetric(Number(dotInfo.perProc || 0))}`),
        create("i", "", `稳态 ${formatMetric(Number(steady?.dotByType?.[code] || 0))}/s`),
      );
    }
    if (nonDotInfo) detail.append(
      create("i", "", `单体 ${formatMetric(Number(nonDotInfo.perProc || 0))}`),
      create("i", "", `延迟 ${Number(nonDotInfo.delaySeconds || 0).toFixed(1)}s`),
      create("i", "", `稳态 ${formatMetric(Number(steady?.nonDotByType?.[code] || 0))}/s`),
    );
    if (!dotInfo && !nonDotInfo) detail.append(create("i", "", "稳态增益已计入"));
    row.append(detail);
    return row;
  });
  wrap.append(...rows);
  const modifiers = [
    Number(steady.viralDamageMultiplier) > 1 ? `病毒 x${Number(steady.viralDamageMultiplier).toFixed(2)}` : "",
    Number(steady.magneticDamageMultiplier) > 1 ? `磁力 x${Number(steady.magneticDamageMultiplier).toFixed(2)}` : "",
    Number(steady.corrosiveArmourStrip) > 0 ? `腐蚀削甲 ${(Number(steady.corrosiveArmourStrip) * 100).toFixed(0)}%` : "",
    Number(steady.heatArmourStrip) > 0 ? `火焰削甲 ${(Number(steady.heatArmourStrip) * 100).toFixed(0)}%` : "",
    Number(steady.coldCriticalDamageBonus) > 0 ? `冰冻暴伤 +${(Number(steady.coldCriticalDamageBonus) * 100).toFixed(0)}%` : "",
    Number(steady.punctureCriticalChanceBonus) > 0 ? `穿刺暴率 +${(Number(steady.punctureCriticalChanceBonus) * 100).toFixed(0)}%` : "",
    Number(steady.magneticBreakPotential) > 0 ? `磁力破盾 ${formatMetric(Number(steady.magneticBreakPotential))}` : "",
  ].filter(Boolean);
  const directBonus = Number(steady.statusDirectBonusDps || 0);
  const nonDotProc = Number(steady.procNonDotDps || 0);
  wrap.append(create("small", "status-breakdown-total", `DoT ${formatMetric(Number(steady.dotDps || 0))}/s · 非 DoT ${formatMetric(Number(steady.nonDotDps || 0))}/s${directBonus ? `（异常增伤 ${formatMetric(directBonus)}/s` + (nonDotProc ? ` + 直接触发 ${formatMetric(nonDotProc)}/s` : "") + "）" : ""} · 状态合计 ${formatMetric(Number(steady.statusDps || 0))}/s${modifiers.length ? ` · ${modifiers.join(" · ")}` : ""}`));
  target.replaceChildren(wrap);
}

function drawTimelineVisual(timeline, killTimeline) {
  // Legacy 赋能时间线：渲染目标优先战斗演算块容器（结果区重构后
  // timeline-content 已移入 combat-charts 的兜底节点）。
  const target = document.getElementById("timeline-content") || document.getElementById("combat-charts");
  if (!target) return;
  const points = Array.isArray(timeline?.points) ? timeline.points : (Array.isArray(timeline) ? timeline : []);
  const kill = killTimeline && Array.isArray(killTimeline.points) ? killTimeline : null;
  if (points.length < 2 && !kill) {
    target.replaceChildren(create("p", "empty-copy", "没有时间线数据，只显示汇总结果"));
    return;
  }
  const W = 860, H = 280, pad = { l: 52, r: 18, t: 22, b: 32 };
  const dpsSeries = [
    { label: "总 DPS", color: "#73cfdf", values: points.map((p) => Number(p.expectedDps ?? p.dps ?? 0)), width: 2.6, glow: true },
    { label: "无赋能基线", color: "#7b8494", values: points.map((p) => Number(p.baselineDps || 0)), width: 1.4, dashed: true },
    ...state.arcaneSelections.map((arcane, i) => ({
      label: arcane.nameZh || `赋能 ${i + 1}`,
      color: ["#d9a6ff", "#f0c36b", "#77d58c", "#7fc8e8"][i] || "#d9a6ff",
      values: points.map((p) => Number(p.arcanes?.[i]?.uptime || 0) * Math.max(...points.map((r) => Number(r.expectedDps || 0)), 1)),
      coverage: Number(points.at(-1)?.arcanes?.[i]?.uptime || 0),
      width: 1.6,
    })),
  ];
  const maxDps = Math.max(...dpsSeries.flatMap((s) => s.values), 1);
  const killBoundary = kill?.killTime == null ? Number(kill?.points.at(-1)?.time ?? 0) : Number(kill.killTime);
  // A kill timeline ends at the kill, even when the DPS samples contain a
  // longer trailing window. This keeps sub-second kills readable.
  const sampleEnd = Number(points.at(-1)?.time ?? 0) || 0;
  const rawEnd = kill && killBoundary > 0 ? killBoundary : sampleEnd;
  const tMax = Math.max(Math.min(rawEnd, 30), 0.1);
  const timeDigits = tMax < 1 ? 2 : 1;
  const hpMax = kill ? kill.targetHp : 0;
  const xOf = (t) => pad.l + (W - pad.l - pad.r) * (clamp(Number(t) || 0, 0, tMax) / tMax);
  const yDps = (v) => pad.t + (H - pad.t - pad.b) * (1 - v / maxDps);
  const yHp = (v) => pad.t + (H - pad.t - pad.b) * (1 - (hpMax ? v / hpMax : 0));
  const svgNS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "timeline-svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "赋能 DPS 与击杀时间线");
  const defs = document.createElementNS(svgNS, "defs");
  const mkGradient = (id, color) => {
    const grad = document.createElementNS(svgNS, "linearGradient");
    grad.id = id; grad.setAttribute("x1", "0"); grad.setAttribute("y1", "0"); grad.setAttribute("x2", "0"); grad.setAttribute("y2", "1");
    const stop1 = document.createElementNS(svgNS, "stop");
    stop1.setAttribute("offset", "0%"); stop1.setAttribute("stop-color", color); stop1.setAttribute("stop-opacity", "0.35");
    const stop2 = document.createElementNS(svgNS, "stop");
    stop2.setAttribute("offset", "100%"); stop2.setAttribute("stop-color", color); stop2.setAttribute("stop-opacity", "0.02");
    grad.append(stop1, stop2); defs.append(grad);
  };
  mkGradient("tl-dps-fill", "#73cfdf");
  svg.append(defs);
  const el = (tag, attrs = {}, text) => {
    const node = document.createElementNS(svgNS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    if (text != null) node.textContent = text;
    return node;
  };
  // horizontal gridlines + y ticks
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.t + (H - pad.t - pad.b) * (i / 4);
    svg.append(el("line", { x1: pad.l, x2: W - pad.r, y1: y, y2: y, stroke: "rgba(148,163,184,.12)", "stroke-width": 1, "stroke-dasharray": i === 4 ? "" : "3 5" }));
    const v = maxDps * (1 - i / 4);
    svg.append(el("text", { x: pad.l - 8, y: y + 3.5, "text-anchor": "end", class: "tl-axis" }, formatMetric(v)));
  }
  // x ticks
  const xSteps = 5;
  for (let i = 0; i <= xSteps; i += 1) {
    const t = tMax * i / xSteps;
    const x = xOf(t);
    svg.append(el("line", { x1: x, x2: x, y1: H - pad.b, y2: H - pad.b + 5, stroke: "rgba(148,163,184,.4)", "stroke-width": 1 }));
    svg.append(el("text", { x, y: H - pad.b + 17, "text-anchor": "middle", class: "tl-axis" }, `${t.toFixed(timeDigits)}s`));
  }
  // kill bars (remaining HP) as rounded rects
  if (kill) {
    const bars = kill.points.filter((p) => p.time <= tMax);
    // A one-hit kill has one sample.  It must not become a viewport-wide bar
    // centred on t=0 and spill through the y axis.
    const barW = Math.min(24, Math.max(1.5, (W - pad.l - pad.r) / Math.max(bars.length, 1) - 0.6));
    bars.forEach((p) => {
      const y = yHp(p.remaining);
      const h = Math.max(H - pad.b - y, 0);
      const ratio = hpMax ? p.remaining / hpMax : 0;
      const barCenter = clamp(xOf(p.time), pad.l + barW / 2, W - pad.r - barW / 2);
      svg.append(el("rect", {
        x: barCenter - barW / 2, y, width: barW, height: h, rx: Math.min(1.5, barW / 3),
        fill: p.remaining <= 0 ? "rgba(239,113,131,.8)" : `rgba(120,160,200,${(0.10 + 0.28 * ratio).toFixed(3)})`,
      }));
    });
    if (kill.killTime !== null && kill.killTime !== undefined) {
      const kx = xOf(kill.killTime);
      svg.append(el("line", { x1: kx, x2: kx, y1: pad.t - 4, y2: H - pad.b, stroke: "#ef7183", "stroke-width": 1.5, "stroke-dasharray": "5 4" }));
      svg.append(el("text", { x: Math.min(kx + 7, W - pad.r - 100), y: pad.t + 6, class: "tl-kill-label" }, `击杀 ${kill.killTime.toFixed(2)}s · ${kill.shotsToKill}发`));
    }
  }
  // DPS area fill + lines
  dpsSeries.forEach((series, si) => {
    const pathPts = series.values.map((v, i) => {
      const t = Number(points[i]?.time ?? (tMax * i / Math.max(points.length - 1, 1)));
      return [xOf(Math.min(t, tMax)), yDps(v)];
    });
    if (!pathPts.length) return;
    if (si === 0) {
      const area = `M${pathPts.map((p) => p.join(" ")).join(" L")} L${pathPts.at(-1)[0]} ${H - pad.b} L${pathPts[0][0]} ${H - pad.b} Z`;
      svg.append(el("path", { d: area, fill: "url(#tl-dps-fill)" }));
    }
    const d = `M${pathPts.map((p) => p.join(" ")).join(" L")}`;
    svg.append(el("path", { d, fill: "none", stroke: series.color, "stroke-width": series.width, "stroke-linecap": "round", "stroke-linejoin": "round", ...(series.dashed ? { "stroke-dasharray": "5 6" } : {}), ...(series.glow ? { style: "filter:drop-shadow(0 0 5px rgba(115,207,223,.55))" } : {}) }));
    if (si === 0) svg.append(el("circle", { cx: pathPts.at(-1)[0], cy: pathPts.at(-1)[1], r: 3.2, fill: "#73cfdf", style: "filter:drop-shadow(0 0 4px rgba(115,207,223,.8))" }));
  });
  // hover: crosshair + tooltip + focus dot
  const hoverLayer = el("g", { style: "display:none" });
  const crossLine = el("line", { y1: pad.t, y2: H - pad.b, stroke: "rgba(243,245,248,.55)", "stroke-width": 1, "stroke-dasharray": "2 3" });
  const focusDot = el("circle", { r: 4, fill: "#fff", stroke: "#73cfdf", "stroke-width": 2 });
  hoverLayer.append(crossLine, focusDot);
  svg.append(hoverLayer);
  const wrap = create("div", "timeline-combo");
  const tip = create("div", "timeline-tip");
  wrap.append(svg, tip);
  svg.addEventListener("mousemove", (evt) => {
    const rect = svg.getBoundingClientRect();
    const px = (evt.clientX - rect.left) * (W / rect.width);
    const t = clamp((px - pad.l) / (W - pad.l - pad.r) * tMax, 0, tMax);
    const dpsPoint = points.length > 1 ? points.reduce((best, p) => (Math.abs(p.time - t) < Math.abs(best.time - t) ? p : best), points[0]) : null;
    const killPoint = kill ? kill.points.reduce((best, p) => (Math.abs(p.time - t) < Math.abs(best.time - t) ? p : best), kill.points[0]) : null;
    const lines = [`t = ${t.toFixed(2)}s`];
    if (dpsPoint) lines.push(`DPS ${formatMetric(Number(dpsPoint.expectedDps ?? dpsPoint.dps ?? 0))}`);
    if (killPoint) lines.push(`目标剩余 ${formatMetric(Number(killPoint.remaining))} / ${formatMetric(Number(kill.targetHp))}`, `已射击 ${killPoint.shots} 发`);
    const arcaneStates = Array.isArray(dpsPoint?.arcanes) ? dpsPoint.arcanes : [];
    arcaneStates.forEach((arcaneState, ai) => {
      const record = state.arcaneSelections[ai];
      if (!record) return;
      const name = arcaneRecords().find((a) => a.path === record.path)?.nameZh || `赋能 ${ai + 1}`;
      const stacks = Number(arcaneState.expectedStacks || 0);
      const uptime = Number(arcaneState.uptime || 0);
      lines.push(`${name} · ${stacks.toFixed(2)} 层 · 覆盖 ${(uptime * 100).toFixed(0)}%`);
    });
    tip.innerHTML = "";
    lines.forEach((l) => tip.append(create("div", "", l)));
    tip.style.left = `${clamp((evt.clientX - rect.left), 70, Math.max(70, rect.width - 70))}px`;
    tip.style.top = "10px";
    if (rect.width > 0 && Number.isFinite(t)) {
      hoverLayer.style.display = "";
      const x = xOf(t);
      crossLine.setAttribute("x1", x); crossLine.setAttribute("x2", x);
      if (dpsPoint) {
        const y = yDps(Number(dpsPoint.expectedDps ?? dpsPoint.dps ?? 0));
        focusDot.setAttribute("cx", x); focusDot.setAttribute("cy", y);
      }
    }
  });
  svg.addEventListener("mouseleave", () => { hoverLayer.style.display = "none"; tip.innerHTML = ""; });
  const legend = create("div", "timeline-legend");
  const legendItems = dpsSeries.map((s) => {
    const item = create("span", "", `${s.label}${s.coverage == null ? "" : ` · 覆盖 ${(s.coverage * 100).toFixed(1)}%`}`);
    item.style.setProperty("--series-color", s.color);
    return item;
  });
  if (kill) {
    const hpLegend = create("span", "", `目标剩余 HP（${formatMetric(kill.targetHp)}）`);
    hpLegend.style.setProperty("--series-color", "#78a0c8");
    legendItems.push(hpLegend);
  }
  legendItems.forEach((i) => legend.append(i));
  const gain = Number(points.at(-1)?.gainPercent || 0);
  const captionBits = [];
  if (points.length > 1) captionBits.push(`${Number(timeline?.durationSeconds || 0).toFixed(timeDigits)}s 赋能收益 ${gain >= 0 ? "+" : ""}${gain.toFixed(1)}%`);
  if (kill && kill.killTime !== null && kill.killTime !== undefined) captionBits.push(`击杀时间 ${kill.killTime.toFixed(2)}s（${kill.shotsToKill} 发）`);
  target.replaceChildren(wrap, legend, create("small", "timeline-caption", captionBits.join(" · ") || "时间线"));
}


function renderManualResultVisual(result) {
  const source = result?.simulation || result;
  const runtimeMods = new Map((source?.selection?.mods || []).map((mod) => [mod.path, mod]));
  if (runtimeMods.size) {
    state.manualSlots = state.manualSlots.map((mod) => mod && runtimeMods.has(mod.path)
      ? { ...mod, ...runtimeMods.get(mod.path) }
      : mod);
    renderManualSlots();
  }
  // 结果区两块（用户指定的分离布局）：配装解算块只放异常状态分布；
  // 战斗演算块（KPM 头条 + 逐条展开的回放图组）在下方独立呈现。
  renderExaltedEnergy(source.exalted);
  renderProbabilityVisual(source.probability || source.probabilityDistribution || {});
  renderStatusBreakdown(source);
  const hasBenchmark = Array.isArray(source.benchmarkTimeline?.points) && source.benchmarkTimeline.points.length > 1;
  const combatPanel = document.getElementById("combat-panel");
  if (combatPanel) combatPanel.hidden = !hasBenchmark;
  if (hasBenchmark) {
    drawBenchmarkReplay(source.benchmarkTimeline);
  } else {
    // 无标准靶数据（旧口径 / 解算失败兜底）：legacy 赋能时间线仍在演算块渲染。
    const host = document.getElementById("combat-charts");
    if (host) {
      const legacy = document.getElementById("timeline-content") || create("div", "");
      if (!legacy.isConnected) host.replaceChildren(legacy);
      drawTimelineVisual(source.timeline || [], source.killTimeline || null);
    }
  }
  updateEnemyStatsPanel(result);
  ui["manual-results"].hidden = false;
}

// ── 标准靶 KPM 回放视图（wfsim UI.md「一行一条曲线」口径的移植）─────────
// 窗口步进模型下发每步的池余量/异常层数/DPS 分量。原先一张大图叠 6 种异常
// + 三段池 + 两个 DPS 分量根本没法看；现在拆成独立的图，每图一个 y 轴，
// 全部默认展开、可单独折叠，共享同一条悬停光标与因子快照 tooltip：
//   1. 三段池堆叠面积（超宏/护盾/生命）——目标死亡即刷新（InstantRespawn）
//   2. DPS 分量（直伤面积 + DoT 线）
//   3. 每种异常一条层数曲线（病毒/磁力/腐蚀/热/穿刺/冰）各自一行小图
const BENCH_STACK_LABELS = {
  viral: "病毒", magnetic: "磁力", corrosive: "腐蚀", heat: "热", puncture: "穿刺", cold: "冰冻",
};
const BENCH_STACK_COLORS = {
  viral: "#f093b9", magnetic: "#9797e6", corrosive: "#93c203", heat: "#fb9733", puncture: "#c6b098", cold: "#5bbcec",
};

function drawBenchmarkReplay(bench) {
  const host = document.getElementById("combat-charts");
  if (!host) return;
  const points = bench.points || [];
  if (!points.length) { host.replaceChildren(); return; }
  const tMax = Number(points.at(-1)?.time || bench.windowSeconds || 30);
  const ehp = Number(bench.targetTotalEhp || 0) || 1;
  const ctx = bench.context || {};
  const svgNS = "http://www.w3.org/2000/svg";
  // 固定视口 + CSS 等比缩放（preserveAspectRatio 默认），坐标不飘：
  // 之前的 "none" 拉伸把 y 轴 0 点挤到中间。宽度用 100% 自适应，高度固定。
  const W = 880, H = 110, pad = { l: 56, r: 18, t: 8, b: 16 };
  const el = (tag, attrs = {}, text) => {
    const node = document.createElementNS(svgNS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
    if (text != null) node.textContent = text;
    return node;
  };
  const xOf = (t) => pad.l + (W - pad.l - pad.r) * (clamp(Number(t) || 0, 0, tMax) / tMax);

  const activeStacks = Object.keys(BENCH_STACK_LABELS).filter((k) =>
    points.some((p) => Number(p.stacks?.[k] || 0) > 0.05)
  );
  const maxDps = Math.max(...points.map((p) => Number(p.directDps || 0) + Number(p.dotDps || 0)), 1);
  const maxStack = Math.max(10, ...points.flatMap((p) => activeStacks.map((k) => Number(p.stacks?.[k] || 0))));

  // The target generation counter is authoritative, including shield-bypass kills.
  const killTimes = [];
  let previousGeneration = 0;
  for (const point of points) {
    const generation = Number(point.generation || 0);
    if (generation > previousGeneration) killTimes.push(Number(point.time));
    previousGeneration = generation;
  }

  const charts = [];

  // 1. DPS 分量（放最上——最常看）
  charts.push({
    key: "dps",
    label: "DPS（直伤面积 · DoT 虚线）",
    render(svg) {
      const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - clamp(v / maxDps, 0, 1));
      const directArea = points.map((p, i) => `${i === 0 ? "M" : "L"}${xOf(p.time).toFixed(1)} ${y(Number(p.directDps || 0)).toFixed(1)}`).join(" ")
        + ` L${xOf(points.at(-1).time).toFixed(1)} ${H - pad.b} L${xOf(points[0].time).toFixed(1)} ${H - pad.b} Z`;
      svg.append(el("path", { d: directArea, fill: "rgba(115,207,223,.22)" }));
      const total = points.map((p, i) => `${i === 0 ? "M" : "L"}${xOf(p.time).toFixed(1)} ${y(Number(p.directDps || 0) + Number(p.dotDps || 0)).toFixed(1)}`).join(" ");
      svg.append(el("path", { d: total, fill: "none", stroke: "#73cfdf", "stroke-width": 2, "stroke-linecap": "round" }));
      const dot = points.map((p, i) => `${i === 0 ? "M" : "L"}${xOf(p.time).toFixed(1)} ${y(Number(p.dotDps || 0)).toFixed(1)}`).join(" ");
      svg.append(el("path", { d: dot, fill: "none", stroke: "#f0c36b", "stroke-width": 1.4, "stroke-dasharray": "4 4" }));
      return { axis: [formatMetric(maxDps), "", "0"], tooltip: (p) => `直伤 ${formatMetric(Number(p.directDps || 0))}/s · DoT ${formatMetric(Number(p.dotDps || 0))}/s` };
    },
  });

  // 2. 目标剩余血量（当前身体三池的剩余百分比，从上到下耗尽后刷新）
  charts.push({
    key: "pools",
    label: "目标剩余（击杀时刷新）",
    render(svg) {
      // 归一化到当前身体总 EHP：三条曲线分别是 超宏/护盾/生命 的剩余量，
      // 全满 = 1.0（顶格），每次归零竖线处刷新。
      const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - clamp(v / ehp, 0, 1));
      const line = (key, fill, stroke) => {
        const d = points.map((p, i) => `${i === 0 ? "M" : "L"}${xOf(p.time).toFixed(1)} ${y(Number(p[key] || 0)).toFixed(1)}`).join(" ");
        svg.append(el("path", { d, fill, stroke: "none", opacity: 0.45 }));
        svg.append(el("path", { d, fill: "none", stroke, "stroke-width": 1.2, opacity: 0.9 }));
      };
      line("overguard", "rgba(217,166,255,.30)", "#d9a6ff");
      line("shield", "rgba(91,188,236,.28)", "#5bbcec");
      line("health", "rgba(120,160,200,.25)", "#78a0c8");
      return {
        axis: ["满", "", "0"],
        tooltip: (p) => `剩余 超宏 ${formatMetric(Number(p.overguard || 0))} · 护盾 ${formatMetric(Number(p.shield || 0))} · 生命 ${formatMetric(Number(p.health || 0))}`,
      };
    },
  });

  if (points.some((p) => p.armour !== undefined)) charts.push({
    key: "armor", label: "实际护甲 / Heat 削甲",
    render(svg) {
      const maxArmor = Math.max(1, ...points.map((p) => Number(p.armour || 0)));
      const line = (key, ceiling, color) => {
        const path = points.map((p, i) => `${i ? "L" : "M"}${xOf(p.time).toFixed(1)} ${(pad.t + (H-pad.t-pad.b) * (1-clamp(Number(p[key] || 0)/ceiling,0,1))).toFixed(1)}`).join(" ");
        svg.append(el("path", { d: path, fill: "none", stroke: color, "stroke-width": 1.6 }));
      };
      line("armour", maxArmor, "#93c203"); line("heatArmourStrip", 1, "#fb9733");
      return { axis: [formatMetric(maxArmor), "", "0"], tooltip: (p) => `护甲 ${formatMetric(p.armour)} · Heat 削甲 ${(Number(p.heatArmourStrip||0)*100).toFixed(0)}% · 总削甲 ${(Number(p.totalArmourStrip||0)*100).toFixed(0)}%` };
    },
  });
  if (points.some((p) => p.form === "base" || p.form === "incarnon")) charts.push({
    key: "incarnon-ammo", label: "灵化循环 · 弹药 / 充能",
    render(svg) {
      const ceiling = Math.max(1, ...points.map((p) => Number(p.ammo || 0)));
      const d = points.map((p,i) => `${i ? "L" : "M"}${xOf(p.time).toFixed(1)} ${(pad.t+(H-pad.t-pad.b)*(1-clamp(Number(p.ammo||0)/ceiling,0,1))).toFixed(1)}`).join(" ");
      svg.append(el("path",{d,fill:"none",stroke:"#c792ea","stroke-width":1.5}));
      return { axis:[String(ceiling),"","0"],tooltip:(p)=>`${p.form==="base"?"基础形态":"灵化形态"} · 余弹 ${Number(p.ammo||0).toFixed(1)} · 弱点充能 ${Number(p.gauge||0).toFixed(1)} · 已射击 ${p.shots}` };
    },
  });

  // 3. 每种异常一行
  for (const key of activeStacks) {
    charts.push({
      key: `stack-${key}`,
      label: `${BENCH_STACK_LABELS[key]} 层数`,
      color: BENCH_STACK_COLORS[key],
      render(svg) {
        const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - clamp(v / maxStack, 0, 1));
        const d = points.map((p, i) => `${i === 0 ? "M" : "L"}${xOf(p.time).toFixed(1)} ${y(Number(p.stacks?.[key] || 0)).toFixed(1)}`).join(" ");
        svg.append(el("path", { d, fill: "none", stroke: BENCH_STACK_COLORS[key], "stroke-width": 1.6, "stroke-linecap": "round" }));
        return { axis: [String(Math.round(maxStack)), "", "0"], tooltip: (p) => `${BENCH_STACK_LABELS[key]} ${Number(p.stacks?.[key] || 0).toFixed(1)} 层` };
      },
    });
  }

  // 4. 触发源覆盖率折线（triggerSeries：后端 emergent 模拟的赋能/镀层/灵化
  //    on-kill 层数曲线）。每条曲线一张子图，标题带 avg/uptime 摘要。
  const triggerSeriesData = Array.isArray(bench.triggerSeries) ? bench.triggerSeries : [];
  const TRIGGER_COLORS = ["#e6c86e", "#8fd694", "#c792ea", "#6ec5e8", "#e69b6e", "#9be86e"];
  triggerSeriesData.forEach((series, index) => {
    const values = series.series || [];
    if (!values.length) return;
    // 2026-09-24：装备了就显示——全零曲线（如冷门触发条件的战甲赋能）
    // 保留展示（用户确认装备生效是可见性的一部分），不再静默隐藏。
    const maxStacks = Math.max(1, Number(series.maxStacks) || 1, ...values);
    const avg = Number(series.avgStacks || 0);
    const uptime = Number(series.uptime || 0);
    charts.push({
      key: `trigger-${series.id}`,
      description: [series.conditionText, series.simulationMode === 'fixed' ? '本次使用指定层数/覆盖率，不由上述事件累积。' : ''].filter(Boolean).join(' '),
      label: `${series.label}（${series.kind === "enervate" ? "期望层数" : "均值"} ${avg.toFixed(1)} · 覆盖 ${(uptime * 100).toFixed(0)}%）`,
      color: TRIGGER_COLORS[index % TRIGGER_COLORS.length],
      render(svg) {
        const y = (v) => pad.t + (H - pad.t - pad.b) * (1 - clamp(v / maxStacks, 0, 1));
        const d = values.map((v, i) => `${i === 0 ? "M" : "L"}${xOf(points[i]?.time || i * tMax / values.length).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
        svg.append(el("path", { d, fill: "none", stroke: TRIGGER_COLORS[index % TRIGGER_COLORS.length], "stroke-width": 1.6, "stroke-linecap": "round" }));
        return { axis: [String(Math.round(maxStacks)), "", "0"], tooltip: (p, i) => `${series.label}：${(values[i] || 0).toFixed(1)}${series.kind === "enervate" ? " 期望层（无固定层数上限）" : ` / ${Math.round(maxStacks)} 层`}` };
      },
    });
  });

  // 共享光标状态
  const crossLines = [];
  const sections = charts.map((chart) => {
    const section = create("details", "combat-chart-row");
    section.open = true;
    const head = create("summary", "combat-chart-head");
    head.append(create("strong", "", chart.label));
    if (chart.color) {
      const swatch = create("i", "combat-chart-swatch");
      swatch.style.background = chart.color;
      head.append(swatch);
    }
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("class", "timeline-svg combat-chart-svg");
    // preserveAspectRatio 默认（等比）——y 轴 0 在底、曲线不飘。
    const { axis, tooltip } = chart.render(svg) || {};
    // 网格 + y 轴标注（3 条线：顶/中/底）
    for (let i = 0; i <= 2; i += 1) {
      const yy = pad.t + (H - pad.t - pad.b) * (i / 2);
      svg.append(el("line", { x1: pad.l, x2: W - pad.r, y1: yy, y2: yy, stroke: "rgba(148,163,184,.10)", "stroke-width": 1, "stroke-dasharray": i === 2 ? "" : "3 5" }));
      if (axis && axis[i] !== undefined && axis[i] !== "") {
        svg.append(el("text", { x: pad.l - 8, y: yy + 3.5, "text-anchor": "end", class: "tl-axis" }, String(axis[i])));
      }
    }
    // 击杀竖线
    for (const kt of killTimes) {
      svg.append(el("line", { x1: xOf(kt), x2: xOf(kt), y1: pad.t, y2: H - pad.b, stroke: "#ef7183", "stroke-width": 1, "stroke-dasharray": "4 4", opacity: 0.55 }));
    }
    // 时间轴刻度（只在最后一行画）
    if (chart === charts.at(-1)) {
      for (let i = 0; i <= 6; i += 1) {
        const t = tMax * i / 6;
        svg.append(el("text", { x: xOf(t), y: H - pad.b + 13, "text-anchor": "middle", class: "tl-axis" }, `${t.toFixed(0)}s`));
      }
    }
    // 光标
    const hoverLayer = el("g", { style: "display:none" });
    const crossLine = el("line", { y1: pad.t, y2: H - pad.b, stroke: "rgba(243,245,248,.6)", "stroke-width": 1, "stroke-dasharray": "2 3" });
    hoverLayer.append(crossLine);
    svg.append(hoverLayer);
    crossLines.push({ layer: hoverLayer, line: crossLine });
    // 悬停：光标全图同步；气泡跟随鼠标所在的那张图
    const chartTip = create("div", "timeline-tip combat-chart-tip");
    chartTip.hidden = true;
    section.append(chartTip);
    svg.addEventListener("mousemove", (evt) => {
      const rect = svg.getBoundingClientRect();
      const px = (evt.clientX - rect.left) * (W / rect.width);
      const t = clamp((px - pad.l) / (W - pad.l - pad.r) * tMax, 0, tMax);
      const x = xOf(t);
      for (const entry of crossLines) {
        entry.layer.style.display = "";
        entry.line.setAttribute("x1", x);
        entry.line.setAttribute("x2", x);
      }
      const nearest = points.reduce((best, q) => (Math.abs(q.time - t) < Math.abs(best.time - t) ? q : best), points[0]);
      const idx = points.indexOf(nearest);
      const tipLines = [
        `t = ${Number(nearest.time).toFixed(2)}s · ${nearest.pool === "overguard" ? "超宏" : nearest.pool === "shield" ? "护盾" : "生命"}池`,
      ];
      if (tooltip) tipLines.push(tooltip(nearest, idx));
      const stackBits = activeStacks.filter((k) => Number(nearest.stacks?.[k] || 0) > 0.05).map((k) => `${BENCH_STACK_LABELS[k]} ${Number(nearest.stacks[k]).toFixed(1)}`);
      if (stackBits.length && chart.key !== "pools" && !chart.key.startsWith("stack-")) tipLines.push(stackBits.join(" · "));
      chartTip.hidden = false;
      chartTip.replaceChildren(...tipLines.map((l) => create("div", "", l)));
      // 气泡贴近光标（视口坐标 → section 内相对坐标），左右翻转防溢出。
      const sectionRect = section.getBoundingClientRect();
      const relX = clamp(evt.clientX - sectionRect.left + 12, 4, Math.max(4, sectionRect.width - 180));
      chartTip.style.left = `${relX}px`;
      chartTip.style.top = "4px";
    });
    svg.addEventListener("mouseleave", () => {
      for (const entry of crossLines) entry.layer.style.display = "none";
      chartTip.hidden = true;
    });
    section.prepend(head);
    if (chart.description) section.append(create('p', 'combat-chart-condition muted', chart.description));
    section.append(svg);
    return section;
  });

  host.replaceChildren(...sections);

  // KPI 头条（wfsim「the kill score is reported as a RATE」口径：率 + 总量并排）
  const kpm = Number(bench.killsPerMinute || 0);
  const kills = Number(bench.killsInWindow || 0);
  const lastAvg = points.length ? points.reduce((sum, p) => sum + Number(p.directDps || 0), 0) / points.length : 0;
  const dotAvg = points.length ? points.reduce((sum, p) => sum + Number(p.dotDps || 0), 0) / points.length : 0;
  const kpmEl = document.getElementById("kpm-value");
  const killsEl = document.getElementById("kills-value");
  const directEl = document.getElementById("direct-dps-value");
  const dotEl = document.getElementById("dot-dps-value");
  const ehpEl = document.getElementById("target-ehp-value");
  if (kpmEl) kpmEl.textContent = kpm.toFixed(2);
  if (killsEl) killsEl.textContent = kills.toFixed(2);
  if (directEl) directEl.textContent = formatMetric(lastAvg);
  if (dotEl) dotEl.textContent = formatMetric(dotAvg);
  if (ehpEl) ehpEl.textContent = formatMetric(ehp);
  const note = document.getElementById("combat-context-note");
  if (note) {
    // 演算条件跟随实际选择（后端 context 回显）；无 context 时回退标准靶说明。
    const parts = [];
    if (ctx.enemyName) parts.push(String(ctx.enemyName));
    if (ctx.level != null) parts.push(`${ctx.level} 级`);
    if (ctx.steelPath) parts.push("钢铁之路");
    const enh = ctx.enhancements || {};
    if (enh.eximus) parts.push("卓越者");
    if (enh.archimedea) parts.push("科研");
    if (enh.empowered) parts.push("强化");
    const caveats = ["期望触发数模型（非随机模拟）"];
    caveats.push('散布暂不参与命中和伤害计算');
    if (bench.fieldDuration) caveats.push(`空仓换弹首发毒云延时已触发 ${bench.fieldDuration.boostedShots} 次`);
    if (bench.zymosChildren) caveats.push("追踪子弹按返回原目标的所选策略计算，目标死亡后的子弹不转移到下一敌人");
    if (bench.quantaStrategy) caveats.push("立方体强化引爆已计入主射击消耗与动作；采用所选脱离碰撞与理想连锁覆盖");
    if (bench.manualDetonation) caveats.push(`每批 ${bench.manualDetonation.batchSize} 次投掷，等待 ${bench.manualDetonation.delaySeconds}s 起爆 · 已起爆 ${bench.manualDetonation.detonations} 批`);
    if (bench.delayedAttackEvents) caveats.push(`已结算 ${bench.delayedAttackEvents} 次延迟爆炸`);
    if (bench.syndicateEvents?.length) caveats.push(`集团爆发 ${bench.syndicateEvents.length} 次，实际伤害 ${formatMetric(bench.syndicateWindow || 0)}`);
    if (bench.unsupported?.length) caveats.push(`另有 ${bench.unsupported.length} 项效果暂未计入，见提示`);
    note.textContent = `${parts.join(" · ") || "标准靶"} · ${tMax.toFixed(0)}s 窗口 · ${caveats.join(" · ")}`;
    note.title = normalizeLabels([...(bench.unsupported || []), ...(bench.limitations || [])]).join('；');
  }
}

function renderBuild() {
  const build = state.result?.[state.buildMode] || {};
  for (const button of ui["build-mode"].querySelectorAll("button")) {
    const active = button.dataset.mode === state.buildMode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  }
  ui["build-slot"].textContent = `${TYPE_LABELS[state.weapon.weaponType] || state.weapon.weaponType} BUILD`;
  const resultWeapon = state.result?.weapon;
  const displayWeapon = resultWeapon && (resultWeapon.nameZh || resultWeapon.nameEn) ? resultWeapon : state.weapon;
  ui["build-weapon-name"].textContent = weaponName(displayWeapon);
  const fireModeEntry = typeof state.result.fireMode === "number"
    ? (state.weapon?.fireModes || []).find((entry) => Number(entry.index) === state.result.fireMode)
    : null;
  ui["build-fire-mode"].textContent =
    typeof state.result.fireMode === "number"
      ? `模式 ${state.result.fireMode + 1}${fireModeEntry?.isIncarnonForm ? " · 灵化形态" : ""}`
      : state.result.fireMode || "主模式";
  const optimizationMetric = state.result.searchStatus?.metric || state.result.metric;
  ui["build-metric"].textContent = METRIC_LABELS[optimizationMetric] || optimizationMetric || "战斗伤害";
  // 放下这套配装最少需要的极化次数（只展示结果）：架势 / 功能槽 / Umbra 在提示里细分。
  const forma = build?.forma;
  const formaEl = ui["build-forma"];
  if (formaEl) {
    if (forma && Number.isFinite(Number(forma.total))) {
      const total = Number(forma.total);
      const parts = [];
      if (forma.regular) parts.push(`常规 ×${forma.regular}`);
      if (forma.umbra) parts.push(`Umbra ×${forma.umbra}`);
      if (forma.stance) parts.push(`架势槽 ×${forma.stance}`);
      if (forma.exilus) parts.push(`功能槽 ×${forma.exilus}`);
      formaEl.textContent = `极化 ×${total}`;
      formaEl.title = total ? `按武器原生极性，放下这套配装最少需要极化：${parts.join("、")}` : "这套配装不需要极化";
      formaEl.hidden = false;
    } else {
      formaEl.hidden = true;
    }
  }
  renderMetrics(build);
  renderFireModes(build, ui["fire-mode-strip"], { interactive: true });
  renderMods(build);
  renderAnalysisStance();
  renderAnalysisIncarnonRoute();
}

// 显示中的配装（基准 / 当前紫卡）所用的灵化路线：当前紫卡的配装可能按紫卡
// 改选了路线（后端逐阶筛选），基准配装始终是武器默认路线。
function analysisBuildIncarnonChoices() {
  return state.result?.[state.buildMode]?.incarnonChoices || state.result?.incarnonChoices;
}

// 诊断里的灵化路线：进化编号附中文分支名（与路线徽标同源）。
function incarnonRouteText() {
  const choices = analysisBuildIncarnonChoices();
  const tiers = Array.isArray(state.weapon?.incarnon) ? state.weapon.incarnon : [];
  if (!choices || typeof choices !== "object") return "";
  return tiers
    .map((tier) => {
      const selectedId = choices[`tier${Number(tier.tier)}`];
      const option = selectedId && (tier.options || []).find((row) => row.id === selectedId);
      return option ? `${selectedId} ${option.label || ""}`.trim() : "";
    })
    .filter(Boolean)
    .join("，");
}

// 灵化武器的最佳配装必须标注进化路线（Evo 2-X / 3-X / 4-X）：同把灵化武器
// 不同路线的面板差异巨大，不标注就不知道配卡的基准是什么。
function renderAnalysisIncarnonRoute() {
  const target = ui["analysis-incarnon-route"];
  if (!target) return;
  const choices = analysisBuildIncarnonChoices();
  const tiers = Array.isArray(state.weapon?.incarnon) ? state.weapon.incarnon : [];
  if (!choices || typeof choices !== "object" || !Object.keys(choices).length || !tiers.length) {
    target.hidden = true;
    target.replaceChildren();
    return;
  }
  const nodes = [];
  for (const tier of tiers) {
    const tierNumber = Number(tier.tier);
    const selectedId = choices[`tier${tierNumber}`];
    if (!selectedId) continue;
    const option = (tier.options || []).find((row) => row.id === selectedId);
    const branchIndex = option
      ? String(option.index ?? ((tier.options || []).indexOf(option) + 1))
      : "?";
    const chip = create("span", "incarnon-route-chip");
    chip.title = option?.description || "";
    chip.append(
      create("b", "", `进化 ${tierNumber}-${branchIndex}`),
      create("i", "", option?.label || selectedId),
    );
    nodes.push(chip);
  }
  if (!nodes.length) {
    target.hidden = true;
    target.replaceChildren();
    return;
  }
  const rerouted = state.buildMode === "actual" && state.result?.incarnonRouteScreen?.adopted;
  const head = create("span", "incarnon-route-head", rerouted ? "灵化路线（按紫卡改选）" : "灵化路线");
  head.title = rerouted
    ? "当前紫卡的配装按这张紫卡逐阶筛选后改用的进化分支；无紫卡基准仍用武器默认路线"
    : "本次解算使用的进化分支（Evo N-分支号）";
  target.replaceChildren(head, ...nodes);
  target.hidden = false;
}

const WARFRAME_CONFIG_STORAGE_KEY = "wf-riven-portable-warframe-configs-v1";
const WARFRAME_POLARITIES = [null, "AP_ATTACK", "AP_DEFENSE", "AP_TACTIC", "AP_UMBRA", "AP_POWER", "AP_WARD", "AP_PRECEPT", "AP_ANY"];
let warframeRequestId = 0;
let warframeRequestTimer = null;

function warframeRows(key) {
  return Array.isArray(state.warframeCatalog?.[key]) ? state.warframeCatalog[key] : [];
}

function warframeId(record) {
  return String(record?.id || record?.path || record?.nameInternal || "");
}

function warframeName(record) {
  return record?.nameZh || record?.nameEn || record?.nameInternal || warframeId(record) || "--";
}

function warframeFormRecords(frame = state.warframeBuild.frame) {
  const parentId = warframeId(frame);
  return warframeRows("warframeForms").filter((row) => row.parentFrameId === parentId);
}

function activeWarframeRecord() {
  const build = state.warframeBuild;
  if (build.activeForm === "main") return build.frame;
  return warframeFormRecords().find((row) => warframeId(row) === build.activeForm) || build.frame;
}

function isAlternateWarframeForm(record = activeWarframeRecord()) {
  return Boolean(record?.isAlternateForm && record?.parentFrameId);
}

function warframeFormOptions() {
  const build = state.warframeBuild;
  if (!build.frame) return [];
  return [
    { id: "main", record: build.frame, alternate: false, label: "本体" },
    ...warframeFormRecords().map((record) => ({ id: warframeId(record), record, alternate: true, label: record.formLabelZh || record.formLabelEn || "第二形态" })),
  ];
}

// Read one saved A/B/C config from either the legacy carrier-only store or the
// additive per-form store. parentConfig is only used for inherited effects;
// it is never merged into the alternate form's own MOD/Arcane calculations.
function warframeStoredConfig(frameId, configName) {
  const store = exaltedWarframeStore();
  const form = warframeRows("warframeForms").find((row) => warframeId(row) === frameId);
  const parentFrameId = form?.parentFrameId || null;
  const entry = store[parentFrameId || frameId] || {};
  const config = configName
    ? (parentFrameId ? entry.forms?.[frameId]?.[configName] : entry[configName]) || null
    : null;
  return {
    config,
    parentConfig: parentFrameId && configName ? entry[configName] || null : null,
    parentFrameId,
    saved: Boolean(config),
  };
}

function loadWarframeFormConfigs(frame) {
  const saved = state.warframeBuild.store[warframeId(frame)] || {};
  const result = { main: { A: saved.A || null, B: saved.B || null, C: saved.C || null } };
  for (const form of warframeFormRecords(frame)) {
    const configs = saved.forms?.[warframeId(form)] || {};
    result[warframeId(form)] = { A: configs.A || null, B: configs.B || null, C: configs.C || null };
  }
  return result;
}

function warframeDescription(record) {
  const lines = damageTokenText(record?.descriptionZh || record?.description || record?.effect || "")
    .replace(/\\n/g, "\n")
    .replace(/<LINE_SEPARATOR>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/<[^>]+>/g, "")
    .replace(/<LOWER_IS_BETTER>/gi, "")
    .replace(/\bNONE\s*[+]?[-+]?0(?:\.0+)?%?/gi, "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return lines.filter((line, index) => lines.indexOf(line) === index).join("\n");
}

function warframeLocalizedDescription(record, fallback = "官方中文资料暂缺") {
  const text = warframeDescription(record);
  return /[\u3400-\u9fff]/.test(text) ? text : fallback;
}

// 战甲赋能描述随等级变化：effectsZhByRank 是官方逐级文本（warframe_build_data
// 冻结快照），rank 步进时取对应行；无逐级数据退回满级静态描述。
function warframeArcaneDescription(item) {
  const rank = Number(item?.rank);
  const byRank = Array.isArray(item?.effectsZhByRank) ? item.effectsZhByRank : [];
  if (Number.isInteger(rank) && byRank.length) {
    const line = byRank[Math.min(Math.max(rank, 0), byRank.length - 1)];
    const text = Array.isArray(line) ? line.join("\n") : String(line || "");
    const cleaned = warframeDescription({ description: text });
    if (cleaned) return cleaned;
  }
  return warframeLocalizedDescription(item);
}

function warframeSourceLabel(record) {
  if (!record) return "";
  if (record.kind === "native") return "来源：Helminth 原生技能";
  const origin = String(record.originFrame || record.sourceFrame || "");
  const frame = warframeRows("warframes").find((row) => warframeId(row) === origin || row.path === origin);
  return frame ? `来源：${warframeName(frame)}` : (origin ? `来源：${origin.split("/").filter(Boolean).pop()}` : "来源：战甲技能");
}

function warframePassiveText(record) {
  return damageTokenText(record?.passive || record?.passiveDescription || "")
    .replace(/<[^>]+>/g, "")
    .replace(/\|[A-Z][A-Z0-9_]*\|%?/gi, "对应数值")
    .replace(/\s+([%，。；、])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function warframeSelection(record) {
  if (!record) return null;
  const path = warframeId(record);
  return path ? { path, rank: Number(record.rank ?? record.maxRank ?? 0) } : null;
}

function warframeResolve(rows, value) {
  const id = typeof value === "string" ? value : warframeId(value);
  return id ? rows.find((row) => warframeId(row) === id) || null : null;
}

function frameSlotPolarities(frame) {
  const source = frame?.slotPolarities || {};
  const normal = Array.isArray(source.normal) ? source.normal.slice(0, 8) : (Array.isArray(frame?.normalPolarities) ? frame.normalPolarities.slice(0, 8) : []);
  return {
    aura: source.aura ?? frame?.auraPolarity ?? null,
    exilus: source.exilus ?? frame?.exilusPolarity ?? null,
    normal: Array.from({ length: 8 }, (_, index) => normal[index] || null),
  };
}

function normalizeFrameSlotPolarities(frame) {
  const source = frameSlotPolarities(frame);
  return {
    aura: source.aura,
    exilus: source.exilus,
    normal: Array.from({ length: 8 }, (_, index) => source.normal[index] || null),
  };
}

function emptyWarframeSnapshot(frame = activeWarframeRecord()) {
  return {
    aura: null,
    exilus: null,
    normalMods: Array.from({ length: 8 }, () => null),
    normalLocks: Array.from({ length: 8 }, () => false),
    arcanes: [null, null],
    shards: Array.from({ length: 5 }, () => null),
    slotPolarities: frameSlotPolarities(frame),
    helminthSlot: null,
    helminthAbility: null,
    invigoration: [],
    applyConditionals: false,
  };
}

function captureWarframeConfig() {
  const build = state.warframeBuild;
  const alternate = isAlternateWarframeForm();
  return {
    schema: 1,
    buildLabel: state.warframeCatalog?.buildLabel || "OFFLINE",
    aura: warframeSelection(build.aura),
    exilus: warframeSelection(build.exilus),
    normalMods: build.normalMods.map(warframeSelection),
    normalLocks: build.normalLocks.map(Boolean),
    arcanes: build.arcanes.map(warframeSelection),
    // Inherited carrier effects are resolved at calculation time, never
    // duplicated into the Shadow's own saved config.
    shards: alternate ? [] : build.shards.map((row) => row ? { path: warframeId(row), tau: Boolean(row.tau) } : null),
    slotPolarities: {
      aura: build.slotPolarities.aura || null,
      exilus: build.slotPolarities.exilus || null,
      normal: build.slotPolarities.normal.slice(0, 8),
    },
    helminthSlot: build.helminthSlot,
    helminthAbility: build.helminthAbility ? warframeId(build.helminthAbility) : null,
    invigoration: alternate ? [] : build.invigoration.map(warframeId),
    applyConditionals: Boolean(build.applyConditionals),
  };
}

function readWarframeStore() {
  try {
    const parsed = JSON.parse(localStorage.getItem(WARFRAME_CONFIG_STORAGE_KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (_error) {
    return {};
  }
}

function persistWarframeConfig() {
  const build = state.warframeBuild;
  const frameId = warframeId(build.frame);
  if (!frameId) return;
  build.formConfigs ||= { main: { A: null, B: null, C: null } };
  build.formConfigs.main ||= { A: null, B: null, C: null };
  build.formConfigs[build.activeForm] ||= { A: null, B: null, C: null };
  build.configs = build.formConfigs[build.activeForm];
  build.configs[build.activeConfig] = captureWarframeConfig();
  const entry = {
    A: build.formConfigs.main.A || null,
    B: build.formConfigs.main.B || null,
    C: build.formConfigs.main.C || null,
    forms: {},
  };
  for (const form of warframeFormRecords()) {
    const id = warframeId(form);
    const configs = build.formConfigs[id] || { A: null, B: null, C: null };
    entry.forms[id] = { A: configs.A || null, B: configs.B || null, C: configs.C || null };
  }
  build.store[frameId] = entry;
  try { localStorage.setItem(WARFRAME_CONFIG_STORAGE_KEY, JSON.stringify(build.store)); } catch (_error) { /* private mode */ }
}

function applyWarframeConfig(config) {
  const blank = emptyWarframeSnapshot();
  const source = config && typeof config === "object" ? config : blank;
  const mods = warframeRows("mods");
  const hydrate = (value, rows = mods) => {
    const row = warframeResolve(rows, value);
    if (!row) return null;
    return { ...row, rank: clamp(Number(value?.rank ?? row.maxRank ?? 0), 0, Number(row.maxRank ?? 0)) };
  };
  const normal = Array.isArray(source.normalMods) ? source.normalMods : [];
  const normalLocks = Array.isArray(source.normalLocks) ? source.normalLocks : [];
  const arcanes = Array.isArray(source.arcanes) ? source.arcanes : [];
  const shards = Array.isArray(source.shards) ? source.shards : [];
  const savedPolarities = source.slotPolarities && typeof source.slotPolarities === "object" ? source.slotPolarities : null;
  const savedNormalPolarities = Array.isArray(savedPolarities?.normal) ? savedPolarities.normal : null;
  const hydratedNormal = Array.from({ length: 8 }, (_, index) => hydrate(normal[index]));
  Object.assign(state.warframeBuild, {
    aura: hydrate(source.aura),
    exilus: hydrate(source.exilus),
    normalMods: hydratedNormal,
    normalLocks: Array.from({ length: 8 }, (_, index) => Boolean(normalLocks[index] && hydratedNormal[index])),
    arcanes: Array.from({ length: 2 }, (_, index) => hydrate(arcanes[index], warframeRows("arcanes"))),
    shards: Array.from({ length: 5 }, (_, index) => hydrate(shards[index], warframeRows("shards"))),
    slotPolarities: savedNormalPolarities
      ? {
        aura: Object.hasOwn(savedPolarities, "aura") ? savedPolarities.aura : blank.slotPolarities.aura,
        exilus: Object.hasOwn(savedPolarities, "exilus") ? savedPolarities.exilus : blank.slotPolarities.exilus,
        normal: Array.from({ length: 8 }, (_, index) => savedNormalPolarities[index] === undefined ? blank.slotPolarities.normal[index] : savedNormalPolarities[index]),
      }
      : blank.slotPolarities,
    helminthSlot: Number.isInteger(source.helminthSlot) ? source.helminthSlot : null,
    helminthAbility: warframeResolve(warframeRows("helminth"), source.helminthAbility),
    invigoration: (Array.isArray(source.invigoration) ? source.invigoration : source.invigoration ? [source.invigoration] : [])
      .map((value) => warframeResolve(warframeRows("invigoration"), value)).filter(Boolean).slice(0, 2),
    applyConditionals: Boolean(source.applyConditionals),
    result: null,
  });
  if (isAlternateWarframeForm()) {
    const inherited = state.warframeBuild.formConfigs.main?.[state.warframeBuild.activeConfig] || {};
    const inheritedShards = Array.isArray(inherited.shards) ? inherited.shards : [];
    const inheritedInvigoration = Array.isArray(inherited.invigoration) ? inherited.invigoration : [];
    state.warframeBuild.shards = Array.from({ length: 5 }, (_, index) => hydrate(inheritedShards[index], warframeRows("shards")));
    state.warframeBuild.invigoration = inheritedInvigoration
      .map((value) => warframeResolve(warframeRows("invigoration"), value)).filter(Boolean).slice(0, 2);
    state.warframeBuild.helminthSlot = null;
    state.warframeBuild.helminthAbility = null;
  }
  renderWarframeWorkbench();
  scheduleWarframeCalculation();
}

function selectWarframeFrame(frame) {
  if (!frame) return;
  persistWarframeConfig();
  const build = state.warframeBuild;
  build.frame = frame;
  build.activeConfig = "A";
  build.activeForm = "main";
  build.formConfigs = loadWarframeFormConfigs(frame);
  build.configs = build.formConfigs.main;
  applyWarframeConfig(build.configs.A);
}

function switchWarframeForm(formId) {
  const build = state.warframeBuild;
  const option = warframeFormOptions().find((row) => row.id === formId);
  if (!option || formId === build.activeForm) return;
  persistWarframeConfig();
  build.activeForm = formId;
  build.formConfigs[formId] ||= { A: null, B: null, C: null };
  build.configs = build.formConfigs[formId];
  // Invalidate any in-flight carrier result before the form's new request.
  warframeRequestId += 1;
  applyWarframeConfig(build.configs[build.activeConfig]);
  const label = option.alternate ? `${option.label}第二套配装` : "本体配装";
  if (ui["warframe-config-status"]) ui["warframe-config-status"].textContent = `${label} · 配置 ${build.activeConfig}`;
}

function switchWarframeConfig(name) {
  const build = state.warframeBuild;
  if (!/^[ABC]$/.test(name) || name === build.activeConfig) return;
  persistWarframeConfig();
  build.activeConfig = name;
  applyWarframeConfig(build.configs[name]);
  if (ui["warframe-config-status"]) ui["warframe-config-status"].textContent = `配置 ${name}${build.configs[name] ? "已载入" : "为空"}`;
}

function copyWarframeConfig() {
  persistWarframeConfig();
  const build = state.warframeBuild;
  const names = ["A", "B", "C"];
  const target = names[(names.indexOf(build.activeConfig) + 1) % names.length];
  build.configs[target] = JSON.parse(JSON.stringify(build.configs[build.activeConfig] || captureWarframeConfig()));
  persistWarframeConfig();
  if (ui["warframe-config-status"]) ui["warframe-config-status"].textContent = `已复制到配置 ${target}`;
}

function exportWarframeConfig() {
  persistWarframeConfig();
  const build = state.warframeBuild;
  const active = activeWarframeRecord();
  const payload = {
    schema: 1,
    kind: "warframe-build",
    buildLabel: state.warframeCatalog?.buildLabel || "OFFLINE",
    frameId: warframeId(active),
    parentFrameId: isAlternateWarframeForm(active) ? warframeId(build.frame) : null,
    formId: build.activeForm,
    formKind: active?.formKind || "main",
    configId: build.activeConfig,
    config: build.configs[build.activeConfig] || captureWarframeConfig(),
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `wf-warframe-${String(active?.nameEn || "build").replace(/[^a-z0-9_-]+/gi, "-")}-${build.activeConfig}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function importWarframeConfig(file) {
  if (!file) return;
  const reader = new FileReader();
  reader.addEventListener("load", () => {
    try {
      const parsed = JSON.parse(String(reader.result || ""));
      const config = parsed.config || parsed;
      if (!config || Number(parsed.schema ?? config.schema ?? 1) !== 1) throw new Error("战甲配置文件格式不兼容");
      const build = state.warframeBuild;
      const target = parsed.frameId
        ? warframeResolve([...warframeRows("warframes"), ...warframeRows("warframeForms")], parsed.frameId)
        : activeWarframeRecord();
      const frame = target?.parentFrameId ? warframeResolve(warframeRows("warframes"), target.parentFrameId) : target;
      if (!frame) throw new Error("导入文件中的战甲或第二形态不在当前目录里");
      const active = build.activeConfig;
      const formId = target.parentFrameId ? warframeId(target) : "main";
      if (warframeId(frame) !== warframeId(build.frame)) {
        persistWarframeConfig();
        build.frame = frame;
        build.formConfigs = loadWarframeFormConfigs(frame);
      }
      build.activeForm = formId;
      build.formConfigs[formId] ||= { A: null, B: null, C: null };
      build.configs = build.formConfigs[formId];
      build.activeConfig = active;
      build.configs[active] = config;
      applyWarframeConfig(config);
      persistWarframeConfig();
      if (ui["warframe-config-status"]) ui["warframe-config-status"].textContent = `已导入配置 ${active}`;
      toast(`已导入 ${warframeName(target)} 配置 ${active}`, "success");
    } catch (error) {
      toast(error.message || "战甲配置导入失败", "error");
    } finally {
      if (ui["warframe-config-import-file"]) ui["warframe-config-import-file"].value = "";
    }
  });
  reader.readAsText(file);
}

function closeConfigActionMenus(except = null) {
  document.querySelectorAll(".config-action-menu.is-open").forEach((menu) => {
    if (menu === except) return;
    menu.classList.remove("is-open");
    menu.querySelector(".config-action-trigger")?.setAttribute("aria-expanded", "false");
  });
}

function bindConfigActionMenus() {
  document.querySelectorAll(".config-action-menu").forEach((menu) => {
    const trigger = menu.querySelector(".config-action-trigger");
    if (!trigger) return;
    trigger.addEventListener("click", (event) => {
      event.preventDefault();
      const open = !menu.classList.contains("is-open");
      closeConfigActionMenus(menu);
      menu.classList.toggle("is-open", open);
      trigger.setAttribute("aria-expanded", String(open));
    });
    menu.querySelectorAll("[role=menuitem]").forEach((item) => item.addEventListener("click", () => closeConfigActionMenus()));
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest(".config-action-menu")) closeConfigActionMenus();
  });
}

function fillWarframeCatalogControls() {
  const frames = warframeRows("warframes").slice().sort((a, b) => warframeName(a).localeCompare(warframeName(b), "zh"));
  if (frames.length) selectWarframeFrame(frames[0]);
}

async function loadWarframeCatalog() {
  if (state.warframeCatalog) return state.warframeCatalog;
  if (state.warframeCatalogPromise) return state.warframeCatalogPromise;
  ui["warframe-catalog-status"].textContent = "LOADING";
  ui["warframe-loading"].querySelector("p").textContent = "正在载入战甲目录";
  state.warframeCatalogPromise = fetch("/api/warframe/catalog")
    .then(async (response) => {
      const body = await response.json();
      if (!response.ok) throw new Error(body?.error?.message || `目录加载失败（${response.status}）`);
      state.warframeCatalog = body;
      state.warframeBuild.store = readWarframeStore();
      fillWarframeCatalogControls();
      ui["warframe-catalog-status"].textContent = `${body.counts?.warframes ?? warframeRows("warframes").length} WARFRAMES`;
      ui["warframe-loading"].hidden = true;
      ui["warframe-build-content"].hidden = false;
      return body;
    })
    .catch((error) => {
      state.warframeCatalogPromise = null;
      ui["warframe-catalog-status"].textContent = "UNAVAILABLE";
      ui["warframe-loading"].querySelector("p").textContent = error.message || "战甲目录加载失败";
      throw error;
    });
  return state.warframeCatalogPromise;
}

function warframeModKind(mod) {
  // `slotKind` is authoritative.  Never infer a Warframe card from a stale
  // generic `type`/`category` field (the old merge made normal cards look like
  // weapon utility cards in the picker).
  const kind = String(mod?.slotKind || "").toLocaleLowerCase();
  if (kind === "aura" || Number(mod?.baseDrain) < 0) return "aura";
  if (kind === "exilus") return "exilus";
  return "normal";
}

function warframeCompatLabel(mod) {
  const kind = warframeModKind(mod);
  if (kind === "aura") return "光环";
  const explicit = mod?.frameIds || mod?.warframes || mod?.compatibleFrames;
  if (explicit && (!Array.isArray(explicit) || explicit.length)) {
    return (Array.isArray(explicit) ? explicit : [explicit]).map((value) => {
      const token = warframeFamilyToken(value);
      const frame = warframeRows("warframes").find((row) => warframeFamilyToken(row.nameEn) === token || warframeFamilyToken(row.id) === token || warframeFamilyToken(row.path) === token);
      return frame ? warframeName(frame) : String(value).split("/").filter(Boolean).pop();
    }).filter(Boolean).join(" / ");
  }
  return "战甲";
}

function warframeFamilyToken(value) {
  const token = String(value || "").trim().toLocaleLowerCase();
  const leaf = token.split("/").pop() || token;
  return leaf.replace(/\s+prime$/, "").replace(/prime$/, "").replace(/[^a-z0-9\u3400-\u9fff]/g, "");
}

function warframeModFitsFrame(mod) {
  const explicit = mod?.frameIds || mod?.warframes || mod?.compatibleFrames;
  // Empty compatibility arrays mean the mod is generic, not incompatible.
  if (!explicit || (Array.isArray(explicit) && explicit.length === 0)) return true;
  const allowed = new Set((Array.isArray(explicit) ? explicit : [explicit]).map(warframeFamilyToken));
  const frame = activeWarframeRecord();
  return [frame?.id, frame?.path, frame?.nameEn, frame?.nameZh, frame?.nameInternal]
    .filter(Boolean).some((value) => allowed.has(warframeFamilyToken(value)));
}

function warframeSlotMarker(mod) {
  const kind = warframeModKind(mod);
  return kind === "aura" ? "/assets/game/slots/icon-aura.png" : kind === "exilus" ? "/assets/game/slots/IconExilus.png" : "";
}

function warframeSlotRelation(item, polarity) {
  if (!item || !polarity) return "neutral";
  return modEffectiveDrain(item, polarity).relation;
}

function warframeSlotForma(kind, index) {
  const build = state.warframeBuild;
  const current = kind === "normal" ? build.slotPolarities.normal[index] : build.slotPolarities[kind];
  const native = kind === "normal" ? frameSlotPolarities(activeWarframeRecord()).normal[index] : frameSlotPolarities(activeWarframeRecord())[kind];
  return Boolean(current && current !== native);
}

function warframePolarityNode(value, className = "special-slot-polarity") {
  return POLARITY_IMAGES[value]
    ? imageNode(POLARITY_IMAGES[value], className, POLARITY_NAMES[value] || value, "lazy")
    : create("span", `${className} special-slot-polarity-glyph`, "");
}

function cycleWarframePolarity(kind, index = 0) {
  const polarities = state.warframeBuild.slotPolarities;
  const current = kind === "normal" ? polarities.normal[index] : polarities[kind];
  const item = kind === "normal" ? state.warframeBuild.normalMods[index] : state.warframeBuild[kind];
  // Prefer the actual selected card record, then the asset index.  Some
  // sidecar rows do not carry polarity after hydration, which previously made
  // the first click fall through to the generic cycle.
  const modPolarity = item ? modPolarityOf(item) : null;
  const currentIndex = WARFRAME_POLARITIES.indexOf(current);
  // First click on an occupied slot is an auto-match action.  Only after the
  // slot already matches does it enter the normal polarity cycle.
  const next = modPolarity && current !== modPolarity
    ? modPolarity
    : WARFRAME_POLARITIES[(Math.max(0, currentIndex) + 1) % WARFRAME_POLARITIES.length];
  if (kind === "normal") polarities.normal[index] = next;
  else polarities[kind] = next;
  patchWarframeSlot(kind, index);
  persistWarframeConfig();
  scheduleWarframeCalculation();
}

function modPolarityOf(mod, slotIndex = 0) {
  // 紫卡返回落槽时掷出的固定常规极性：自动极化/槽位循环都能按它对齐。
  if (mod?.__riven) return rivenFixedPolarity(mod, slotIndex);
  return mod?.polarity || state.modAssets?.mods?.[mod?.path]?.polarity || null;
}

function warframeRankControls(item, onChange, onRemove, className = "manual-slot-actions") {
  const controls = create("div", className);
  const maxRank = Math.max(0, Number(item.maxRank ?? item.rank ?? 0));
  const rank = clamp(Number(item.rank ?? maxRank), 0, maxRank);
  const down = create("button", "rank-stepper-btn", "−");
  const up = create("button", "rank-stepper-btn", "+");
  const remove = create("button", "manual-slot-remove", "×");
  down.type = up.type = remove.type = "button";
  down.disabled = rank <= 0;
  up.disabled = rank >= maxRank;
  down.title = "降低一级";
  up.title = "提升一级";
  remove.title = "移除";
  [down, up, remove].forEach((button) => button.addEventListener("click", (event) => event.stopPropagation()));
  down.addEventListener("click", () => onChange(rank - 1));
  up.addEventListener("click", () => onChange(rank + 1));
  remove.addEventListener("click", onRemove);
  controls.append(down, create("span", "rank-stepper-value", `R${rank}/${maxRank}`), up, remove);
  return controls;
}

function warframeSpecialCard(item, kind, slotPolarity) {
  const card = createNormalModCard(item, 0, { compatLabel: warframeCompatLabel(item), slotPolarity, slotRelation: warframeSlotRelation(item, slotPolarity), slotForma: warframeSlotForma(kind), slotMarker: warframeSlotMarker(item), slotMarkerLabel: kind === "aura" ? "光环 MOD" : "功能槽 MOD" });
  card.querySelector(".slot-number")?.remove();
  return card;
}

function renderWarframeSpecialSlot(kind) {
  const build = state.warframeBuild;
  const item = build[kind];
  const label = kind === "aura" ? "光环" : "功能槽";
  const slot = create("article", `special-mod-slot warframe-special-slot${item ? " is-filled" : ""}`);
  slot.tabIndex = 0;
  slot.setAttribute("role", "button");
  const head = create("div", "special-slot-head");
  const slotIcon = kind === "aura" ? "/assets/game/slots/icon-aura.png" : "/assets/game/slots/IconExilus.png";
  head.append(imageNode(slotIcon, "warframe-slot-glyph", label, "lazy"), create("strong", "", label));
  const polarity = create("button", "slot-polarity-chip special-slot-polarity-button");
  polarity.type = "button";
  const specialRelation = warframeSlotRelation(item, build.slotPolarities[kind]);
  polarity.classList.toggle("is-matched", specialRelation === "match");
  polarity.classList.toggle("is-mismatch", specialRelation === "mismatch");
  polarity.classList.toggle("is-forma", warframeSlotForma(kind));
  polarity.title = `槽位极性：${POLARITY_NAMES[build.slotPolarities[kind]] || "无"} · 点击切换`;
  polarity.setAttribute("aria-label", polarity.title);
  polarity.append(warframePolarityNode(build.slotPolarities[kind], "slot-polarity-icon"));
  polarity.addEventListener("click", (event) => { event.stopPropagation(); cycleWarframePolarity(kind); });
  head.append(polarity);
  slot.append(head);
  if (item) {
    slot.append(warframeSpecialCard(item, kind, build.slotPolarities[kind]));
    slot.append(warframeRankControls(item, (rank) => {
      item.rank = rank; renderWarframeLoadout(); persistWarframeConfig(); scheduleWarframeCalculation();
    }, () => {
      build[kind] = null; renderWarframeLoadout(); persistWarframeConfig(); scheduleWarframeCalculation();
    }, "special-slot-controls"));
  } else {
    const empty = create("div", "special-slot-empty");
    empty.append(create("span", "", "＋"), create("small", "", "未装备"));
    slot.append(empty);
  }
  const open = () => openWarframePicker(kind);
  slot.addEventListener("click", open);
  slot.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  return slot;
}

function renderWarframeNormalSlot(index) {
  const build = state.warframeBuild;
  const item = build.normalMods[index];
  const locked = Boolean(build.normalLocks[index]);
  const slot = create("article", `manual-slot warframe-normal-slot${item ? " is-filled" : ""}${locked ? " is-locked" : ""}`);
  slot.dataset.slot = String(index);
  slot.tabIndex = 0;
  slot.setAttribute("role", "button");
  slot.addEventListener("dragover", (event) => {
    const from = dragSourceIndex("warframe", event);
    if (!Number.isInteger(from) || from === index || !build.normalMods[from] || build.normalLocks[from] || locked) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    slot.classList.add("is-drop-target");
  });
  slot.addEventListener("dragenter", (event) => {
    const from = dragSourceIndex("warframe", event);
    if (!Number.isInteger(from) || from === index || !build.normalMods[from] || build.normalLocks[from] || locked) return;
    event.preventDefault();
  });
  slot.addEventListener("dragleave", () => slot.classList.remove("is-drop-target"));
  slot.addEventListener("drop", (event) => {
    event.preventDefault();
    event.stopPropagation();
    slot.classList.remove("is-drop-target");
    const from = dragSourceIndex("warframe", event);
    if (!Number.isInteger(from) || from === index || !build.normalMods[from] || build.normalLocks[from] || locked) return;
    [build.normalMods[from], build.normalMods[index]] = [build.normalMods[index], build.normalMods[from]];
    renderWarframeLoadout();
    persistWarframeConfig();
    scheduleWarframeCalculation();
  });
  const polarity = build.slotPolarities.normal[index];
  const relation = warframeSlotRelation(item, polarity);
  const chip = create("button", `slot-polarity-chip${relation === "match" ? " is-matched" : ""}${relation === "mismatch" ? " is-mismatch" : ""}${warframeSlotForma("normal", index) ? " is-forma" : ""}`);
  chip.type = "button";
  chip.title = `槽位 ${index + 1} 极性：${POLARITY_NAMES[polarity] || "无"} · 点击切换`;
  chip.append(warframePolarityNode(polarity, "slot-polarity-icon"));
  chip.addEventListener("click", (event) => { event.stopPropagation(); cycleWarframePolarity("normal", index); });
  if (item) {
    const card = createNormalModCard(item, index + 1, { slotPolarity: polarity, slotRelation: warframeSlotRelation(item, polarity), slotForma: warframeSlotForma("normal", index), compatLabel: warframeCompatLabel(item), slotMarker: warframeSlotMarker(item), slotMarkerLabel: warframeModKind(item) === "exilus" ? "功能槽 MOD" : "" });
    card.classList.add("manual-slot-preview");
    slot.append(card, chip);
    const actions = create("div", "manual-slot-actions");
    const drag = create("button", "manual-slot-drag", "⋮⋮");
    drag.type = "button";
    drag.title = "拖动槽位";
    drag.setAttribute("aria-label", "拖动槽位");
    drag.draggable = true;
    drag.addEventListener("click", (event) => event.stopPropagation());
    drag.addEventListener("pointerdown", (event) => event.stopPropagation());
    drag.addEventListener("pointerdown", (event) => startPointerModDrag("warframe", index, event, slot));
    drag.addEventListener("dragstart", (event) => {
      if (locked || !build.normalMods[index]) { event.preventDefault(); return; }
      beginModDrag("warframe", index, event, slot);
    });
    drag.addEventListener("dragend", () => {
      finishModDrag();
    });
    const maxRank = Math.max(0, Number(item.maxRank ?? item.rank ?? 0));
    const currentRank = () => clamp(Number(item.rank ?? maxRank), 0, maxRank);
    const rankStepper = create("div", "rank-stepper");
    const rankDown = create("button", "rank-stepper-btn", "−");
    const rankUp = create("button", "rank-stepper-btn", "+");
    rankDown.type = rankUp.type = "button";
    rankDown.title = "降低一级";
    rankUp.title = "提升一级";
    rankDown.disabled = locked || currentRank() <= 0;
    rankUp.disabled = locked || currentRank() >= maxRank;
    [rankDown, rankUp].forEach((button) => button.addEventListener("click", (event) => {
      event.stopPropagation();
      item.rank = clamp(currentRank() + (button === rankUp ? 1 : -1), 0, maxRank);
      renderWarframeLoadout();
      persistWarframeConfig();
      scheduleWarframeCalculation();
    }));
    rankStepper.append(rankDown, create("span", "rank-stepper-value", `${currentRank()}/${maxRank}`), rankUp);
    const lock = create("button", "manual-slot-lock", locked ? "解锁" : "锁定");
    lock.type = "button";
    lock.title = locked ? "解锁槽位" : "锁定槽位";
    lock.addEventListener("click", (event) => {
      event.stopPropagation();
      build.normalLocks[index] = !locked;
      renderWarframeLoadout();
      persistWarframeConfig();
    });
    const remove = create("button", "manual-slot-remove", "移除");
    remove.type = "button";
    remove.title = "移除 MOD";
    remove.disabled = locked;
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      if (locked) return;
      build.normalMods[index] = null;
      renderWarframeLoadout();
      persistWarframeConfig();
      scheduleWarframeCalculation();
    });
    actions.append(drag, rankStepper, lock, remove);
    slot.append(actions);
  } else {
    const empty = create("div", "manual-slot-empty-card");
    empty.append(create("span", "manual-slot-empty-plus", "＋"), create("small", "", `槽位 ${index + 1}`));
    // 天生极性标渲染在空槽底框内部（与武器配装 tab 的空槽样式一致）
    if (polarity && POLARITY_IMAGES[polarity]) {
      const polIcon = imageNode(POLARITY_IMAGES[polarity], "empty-slot-polarity", "", "lazy");
      polIcon.title = `天生槽位极性：${POLARITY_NAMES[polarity] || polarity}${warframeSlotForma("normal", index) ? "（已极化）" : ""}`;
      empty.append(polIcon);
    }
    slot.append(empty, chip);
  }
  const open = () => locked ? toast("当前槽位已锁定，先解锁再更换 MOD") : openWarframePicker("normal", index);
  slot.addEventListener("click", open);
  slot.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  return slot;
}

function renderWarframeArcaneSlot(index) {
  const build = state.warframeBuild;
  const item = build.arcanes[index];
  const slot = create("article", `arcane-workbench-slot${item ? " is-filled" : ""}`);
  slot.tabIndex = 0;
  slot.setAttribute("role", "button");
  const visual = create("div", "arcane-slot-visual");
  const rarity = String(item?.rarity || "COMMON").toUpperCase();
  visual.append(imageNode(item ? (ARCANE_FRAMES[rarity] || ARCANE_FRAMES.COMMON) : "/assets/arcanes/NoArcaneIcon.png", "arcane-slot-frame", "", "lazy"));
  const icon = item && catalogIconAsset(item, "arcane");
  if (icon) visual.append(imageNode(icon, "arcane-slot-icon", warframeName(item), "lazy"));
  if (!item) visual.append(create("span", "arcane-slot-plus", "+"));
  const copy = create("div", "arcane-slot-copy");
  copy.append(create("small", "arcane-slot-label", `战甲赋能 ${index + 1}`), create("strong", "", item ? warframeName(item) : "空槽位"), create("p", "arcane-slot-description", item ? warframeArcaneDescription(item) : "未装备"));
  if (item && warframeArcaneHint(item)) copy.append(create("p", "arcane-slot-description warframe-arcane-runtime", warframeArcaneHint(item)));
  slot.append(visual, copy);
  if (item) slot.append(warframeRankControls(item, (rank) => {
    item.rank = rank; renderWarframeLoadout(); persistWarframeConfig(); scheduleWarframeCalculation();
  }, () => {
    build.arcanes[index] = null; renderWarframeLoadout(); persistWarframeConfig(); scheduleWarframeCalculation();
  }, "arcane-slot-controls"));
  const open = () => openWarframePicker("arcane", index);
  slot.addEventListener("click", open);
  slot.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  return slot;
}

function renderWarframeShardSlot(index) {
  const build = state.warframeBuild;
  const item = build.shards[index];
  const inherited = isAlternateWarframeForm();
  const slot = create("article", `warframe-shard-slot${item ? " is-filled" : ""}${item?.tau ? " is-tau" : ""}${inherited ? " is-inherited" : ""}`);
  slot.tabIndex = 0;
  slot.setAttribute("role", "button");
  const visual = create("div", "warframe-shard-visual");
  const assets = item && warframeShardAssets(item);
  if (assets?.base) {
    visual.append(imageNode(assets.base, "warframe-shard-base", warframeName(item), "lazy"));
    if (assets.glow) visual.append(imageNode(assets.glow, "warframe-shard-glow", "", "lazy"));
  }
  else visual.append(create("span", "", "+"));
  const copy = create("div", "warframe-shard-copy");
  copy.append(create("small", "", `${inherited ? "继承" : "源力石"} ${index + 1}`), create("strong", "", item ? warframeName(item) : "空槽位"), create("p", "", item ? warframeDescription(item) : inherited ? "本体未安装" : "未安装"));
  slot.append(visual, copy);
  if (item && !inherited) {
    const remove = create("button", "warframe-shard-remove", "×");
    remove.type = "button";
    remove.title = "移除源力石";
    remove.addEventListener("click", (event) => {
      event.stopPropagation(); build.shards[index] = null; renderWarframeLoadout(); persistWarframeConfig(); scheduleWarframeCalculation();
    });
    slot.append(remove);
  }
  const open = () => openWarframePicker("shard", index);
  slot.addEventListener("click", open);
  slot.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  return slot;
}

function warframeLoadoutSignature(kind, index) {
  const build = state.warframeBuild;
  const item = kind === "normal" ? build.normalMods[index] : kind === "arcane" ? build.arcanes[index] : kind === "shard" ? build.shards[index] : build[kind];
  const polarity = kind === "normal" ? build.slotPolarities.normal[index] : ["aura", "exilus"].includes(kind) ? build.slotPolarities[kind] : "";
  const relation = ["normal", "aura", "exilus"].includes(kind) ? warframeSlotRelation(item, polarity) : "";
  const forma = ["normal", "aura", "exilus"].includes(kind) ? warframeSlotForma(kind, index) : "";
  return [
    kind, index, build.activeForm, warframeId(item), Number(item?.rank ?? item?.maxRank ?? 0), item?.rarity || "", item?.tau ? 1 : 0,
    polarity || "none", relation, forma, kind === "normal" && build.normalLocks[index] ? 1 : 0,
    item?.modSet || "", item?.modSet && activeSetPieces(item), item && warframeArcaneHint(item), item && warframeShardAssets(item)?.base,
  ].join("|");
}

function patchWarframeCollection(container, descriptors) {
  if (!container) return;
  descriptors.forEach((descriptor, index) => {
    const current = container.children[index];
    if (current?.dataset.warframeSignature === descriptor.signature) return;
    const node = descriptor.create();
    node.dataset.warframeSignature = descriptor.signature;
    if (current) current.replaceWith(node);
    else container.append(node);
  });
  while (container.children.length > descriptors.length) container.lastElementChild.remove();
}

function patchWarframeSlot(kind, index = 0) {
  const container = kind === "normal" ? ui["warframe-normal-slots"] : ui["warframe-special-slots"];
  if (!container) return;
  const position = kind === "normal" ? index : kind === "aura" ? 0 : 1;
  const signature = warframeLoadoutSignature(kind, index);
  const current = container.children[position];
  if (current?.dataset.warframeSignature === signature) return;
  const node = kind === "normal" ? renderWarframeNormalSlot(index) : renderWarframeSpecialSlot(kind);
  node.dataset.warframeSignature = signature;
  if (current) current.replaceWith(node);
  else container.append(node);
}

function renderWarframeLoadout() {
  if (!state.warframeBuild.frame) return;
  patchWarframeCollection(ui["warframe-special-slots"], ["aura", "exilus"].map((kind) => ({
    signature: warframeLoadoutSignature(kind, 0),
    create: () => renderWarframeSpecialSlot(kind),
  })));
  patchWarframeCollection(ui["warframe-normal-slots"], Array.from({ length: 8 }, (_, index) => ({
    signature: warframeLoadoutSignature("normal", index),
    create: () => renderWarframeNormalSlot(index),
  })));
  patchWarframeCollection(ui["warframe-arcane-slots"], Array.from({ length: 2 }, (_, index) => ({
    signature: warframeLoadoutSignature("arcane", index),
    create: () => renderWarframeArcaneSlot(index),
  })));
  patchWarframeCollection(ui["warframe-shard-slots"], Array.from({ length: 5 }, (_, index) => ({
    signature: warframeLoadoutSignature("shard", index),
    create: () => renderWarframeShardSlot(index),
  })));
}

function renderWarframeFormSwitch() {
  const build = state.warframeBuild;
  const options = warframeFormOptions();
  const host = ui["warframe-form-switch"];
  if (!host) return;
  host.hidden = options.length <= 1;
  ui["warframe-form-tabs"].replaceChildren(...options.map((option) => {
    const active = option.id === build.activeForm;
    const button = create("button", `warframe-form-tab${active ? " is-active" : ""}${option.alternate ? " is-alternate" : ""}`);
    button.type = "button";
    button.dataset.warframeForm = option.id;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(active));
    button.setAttribute("aria-label", `${warframeName(option.record)} · ${option.alternate ? "第二套配装" : "本体配装"}`);
    const visual = create("span", "warframe-form-tab-visual");
    const portrait = option.record.portraitAsset || option.record.iconAsset;
    if (portrait) visual.append(imageNode(portrait, "", warframeName(option.record), "lazy"));
    else visual.append(create("i", "", option.alternate ? "S" : "W"));
    const copy = create("span", "warframe-form-tab-copy");
    copy.append(
      create("small", "", option.alternate ? "SECOND LOADOUT" : "WARFRAME"),
      create("strong", "", warframeName(option.record)),
      create("em", "", option.alternate ? `${option.label} · 独立 MOD / 赋能 / 技能` : "本体 MOD / 赋能 / 技能"),
    );
    button.append(visual, copy, create("b", "warframe-form-tab-badge", option.alternate ? "第二套" : "本体"));
    button.addEventListener("click", () => switchWarframeForm(option.id));
    return button;
  }));
  const active = activeWarframeRecord();
  ui["warframe-form-switch-note"].textContent = isAlternateWarframeForm(active)
    ? "幽影独立配装 · 源力石与活化继承同配置槽的本体"
    : "本体与第二形态分别保存独立 A / B / C 配置";
}

function renderWarframeProfile() {
  const build = state.warframeBuild;
  const rootFrame = build.frame;
  const frame = activeWarframeRecord();
  if (!rootFrame || !frame) return;
  const alternate = isAlternateWarframeForm(frame);
  renderWarframeFormSwitch();
  ui["warframe-tool"].dataset.activeForm = alternate ? "shadow" : "main";
  ui["warframe-result-kicker"].textContent = alternate ? "SHADOW BUILD · RANK 30" : "WARFRAME BUILD · RANK 30";
  ui["warframe-frame-select"].value = warframeId(rootFrame);
  ui["warframe-frame-select-name"].textContent = warframeName(rootFrame);
  // 描述已在下方档案卡完整显示，选择器里只留操作提示。
  ui["warframe-frame-select-description"].textContent = "点击更换战甲";
  const frameVisual = ui["warframe-frame-select-visual"];
  if (frameVisual) {
    frameVisual.replaceChildren();
    const selectorPortrait = rootFrame.portraitAsset || rootFrame.iconAsset;
    if (selectorPortrait) frameVisual.append(imageNode(selectorPortrait, "warframe-selector-icon", warframeName(rootFrame), "lazy"));
    else frameVisual.append(create("i", "", "W"));
  }
  ui["warframe-profile-name"].textContent = warframeName(frame);
  ui["warframe-result-name"].textContent = warframeName(frame);
  ui["warframe-profile-description"].textContent = warframeLocalizedDescription(frame, "暂无形态简介");
  ui["warframe-passive"].textContent = warframePassiveText(frame) || (alternate ? "无独立被动 · 源力石与活化继承同配置槽的本体" : "--");
  const portrait = frame.portraitAsset || frame.iconAsset;
  ui["warframe-portrait"].hidden = !portrait;
  if (portrait) { ui["warframe-portrait"].src = portrait; ui["warframe-portrait"].alt = warframeName(frame); }
  ui["warframe-frame-caption"].textContent = `${state.warframeCatalog?.buildLabel || "OFFLINE"} · 固定满级 30 · ${alternate ? "第二套配装" : "本体配置"}`;
  ui["warframe-apply-conditionals"].checked = build.applyConditionals;
  ui["warframe-helminth-slot"].value = build.helminthSlot === null ? "" : String(build.helminthSlot);
  const replacedAbility = !alternate && build.helminthSlot !== null ? frame.abilities?.[Number(build.helminthSlot)] : null;
  ui["warframe-helminth-slot-open"].disabled = alternate;
  ui["warframe-helminth-slot-name"].textContent = alternate ? "固定技能组" : replacedAbility ? warframeName(replacedAbility) : "不替换";
  ui["warframe-helminth-slot-description"].textContent = alternate ? "幽影不能进行 Helminth 替换" : replacedAbility ? warframeLocalizedDescription(replacedAbility, `第 ${Number(build.helminthSlot) + 1} 个主动技能`) : "保留战甲原本的四个主动技能";
  const slotVisual = ui["warframe-helminth-slot-visual"];
  if (slotVisual) {
    slotVisual.replaceChildren();
    const icon = replacedAbility?.iconAsset || replacedAbility?.icon;
    if (icon) slotVisual.append(imageNode(icon, "warframe-selector-icon", warframeName(replacedAbility), "lazy"));
    else slotVisual.append(create("i", "", "—"));
  }
  ui["warframe-helminth-ability"].value = build.helminthAbility ? warframeId(build.helminthAbility) : "";
  ui["warframe-helminth-ability-open"].disabled = alternate || build.helminthSlot === null;
  ui["warframe-helminth-ability-name"].textContent = alternate ? "不可替换" : build.helminthAbility ? warframeName(build.helminthAbility) : "选择技能";
  ui["warframe-helminth-ability-source"].textContent = alternate ? "使用幽影自己的四个技能" : build.helminthAbility ? warframeSourceLabel(build.helminthAbility) : "先选择替换技能槽";
  const helminthVisual = ui["warframe-helminth-ability-visual"];
  if (helminthVisual) {
    helminthVisual.replaceChildren();
    const icon = build.helminthAbility?.iconAsset;
    if (icon) helminthVisual.append(imageNode(icon, "warframe-selector-icon", warframeName(build.helminthAbility), "lazy"));
    else helminthVisual.append(create("i", "", "H"));
  }
  ui["warframe-helminth-description"].textContent = alternate ? "本体的 Helminth 配置与幽影固定技能组互不影响。" : build.helminthAbility ? warframeLocalizedDescription(build.helminthAbility, "该技能只替换一个主动技能槽。") : "未替换技能。";
  ui["warframe-invigoration-open"].disabled = alternate;
  ui["warframe-invigoration-name"].textContent = (alternate ? "继承本体 · " : "") + (build.invigoration.length ? build.invigoration.map(warframeName).join(" + ") : "未选择");
  ui["warframe-invigoration-description"].textContent = alternate ? "读取同配置槽的本体活化，不在幽影上重复装备" : build.invigoration.length ? build.invigoration.map((row) => warframeLocalizedDescription(row, "增幅效果")).join("；") : "一项攻势 + 一项辅助";
  ui["warframe-shard-inheritance-note"].textContent = alternate ? "继承本体 · 只读" : "普通 / Tau · 5 槽";
  ui["warframe-config-tabs"].querySelectorAll("[data-warframe-config]").forEach((button) => {
    const active = button.dataset.warframeConfig === build.activeConfig;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
}

function renderWarframeWorkbench() {
  renderWarframeExaltedCard();
  renderWarframeProfile();
  renderWarframeLoadout();
}

function warframePickerRowsBase() {
  const build = state.warframeBuild;
  const kind = state.warframePickerKind;
  const usedMods = new Set([build.aura, build.exilus, ...build.normalMods].filter(Boolean).map(warframeId));
  const usedArcanes = new Set(build.arcanes.filter(Boolean).map(warframeId));
  const query = String(ui["warframe-picker-search"]?.value || "").trim().toLocaleLowerCase();
  let rows;
  if (kind === "frame") rows = warframeRows("warframes");
  else if (kind === "helminth") rows = warframeRows("helminth");
  else if (kind === "helminthSlot") rows = [
    { id: "", slot: null, nameZh: "不替换", nameEn: "None", description: "保留战甲原本的四个主动技能" },
    ...(activeWarframeRecord()?.abilities || []).slice(0, 4).map((ability, slot) => ({ ...ability, id: `helminth-slot-${slot}`, slot })),
  ];
  else if (["aura", "exilus", "normal"].includes(kind)) {
    rows = dedupeWarframeMods(warframeRows("mods").filter((row) => (kind === "normal" ? warframeModKind(row) !== "aura" : warframeModKind(row) === kind) && warframeModFitsFrame(row)));
    const current = kind === "normal" ? build.normalMods[state.warframePickerSlot] : build[kind];
    if (current) usedMods.delete(warframeId(current));
    rows = rows.filter((row) => !usedMods.has(warframeId(row)));
  } else if (kind === "arcane") {
    rows = warframeRows("arcanes");
    if (build.arcanes[state.warframePickerSlot]) usedArcanes.delete(warframeId(build.arcanes[state.warframePickerSlot]));
    rows = rows.filter((row) => !usedArcanes.has(warframeId(row)));
  } else if (kind === "shard") rows = warframeRows("shards");
  else {
    // 活化增幅：保留已选项在列表中（不过滤），后续渲染时标记 is-selected
    rows = warframeRows("invigoration");
  }
  return rows.filter((row) => !query || [warframeName(row), row.nameEn, warframeId(row), warframeDescription(row), warframeSourceLabel(row)].filter(Boolean).join(" ").toLocaleLowerCase().includes(query));
}

function warframePickerRows() {
  const rows = warframePickerRowsBase();
  const kind = state.warframePickerKind;
  const category = state.warframePickerCategory || "all";
  return ["aura", "exilus", "normal"].includes(kind) && category !== "all"
    ? rows.filter((row) => warframeCategoryMatches(row, category))
    : rows;
}

function renderWarframePicker() {
  const kind = state.warframePickerKind;
  const rows = warframePickerRows();
  const isMod = ["aura", "exilus", "normal"].includes(kind);
  const categoryTarget = ui["warframe-picker-categories"];
  if (categoryTarget) {
    categoryTarget.hidden = !isMod;
    if (isMod) {
      const labels = { all: "全部", aura: "光环", exilus: "战甲", exclusive: "专属", set: "套装", normal: "常规" };
      const active = state.warframePickerCategory || "all";
      categoryTarget.replaceChildren(...Object.entries(labels).map(([key, label]) => {
        const categoryRows = warframePickerRowsForCategory(kind, key);
        const button = create("button", key === active ? "is-active" : "", `${label} ${categoryRows.length}`);
        button.type = "button";
        button.addEventListener("click", () => { state.warframePickerCategory = key; renderWarframePicker(); });
        return button;
      }));
    } else categoryTarget.replaceChildren();
  }
  ui["warframe-picker-list"].className = `mod-picker-grid${isMod ? "" : " is-warframe-image-list"}`;
  const nodes = rows.slice(0, 240).map((row) => {
    if (isMod) {
      const option = create("button", "manual-mod-option");
      option.type = "button";
      option.dataset.modPath = warframeId(row);
      const card = modPickerCard(row, kind);
      card.classList.add("manual-option-card");
      card.querySelector(".slot-number")?.remove();
      option.append(card);
      bindModPreview(option, row, kind);
      option.addEventListener("click", () => applyWarframePickerRow(row));
      return option;
    }
    const isSelected = kind === "invigoration" && state.warframeBuild.invigoration.some((selected) => warframeId(selected) === warframeId(row));
    const option = create("button", `warframe-image-option${kind === "frame" ? " is-frame-option" : ""}${["helminth", "helminthSlot"].includes(kind) ? " is-ability-option" : ""}${isSelected ? " is-selected" : ""}`);
    option.type = "button";
    const icon = kind === "shard" ? "" : (catalogIconAsset(row, kind === "arcane" ? "arcane" : "") || row.iconAsset);
    const visual = create("span", "warframe-image-option-visual");
    if (kind === "arcane") {
      const rarity = String(row.rarity || "COMMON").toUpperCase();
      visual.append(imageNode(ARCANE_FRAMES[rarity] || ARCANE_FRAMES.COMMON, "warframe-picker-arcane-frame", "", "lazy"));
    }
    if (kind === "shard") {
      const assets = warframeShardAssets(row);
      if (assets.base) visual.append(imageNode(assets.base, "warframe-picker-shard-base", "", "lazy"));
      if (assets.glow) visual.append(imageNode(assets.glow, "warframe-picker-shard-glow", "", "lazy"));
    }
    if (icon) visual.append(imageNode(icon, "warframe-picker-icon", warframeName(row), "lazy"));
    else if (kind !== "shard" || !warframeShardAssets(row)?.base) visual.append(create("i", "", "◇"));
    const copy = create("span", "warframe-image-option-copy");
    const sub = kind === "helminth" ? warframeSourceLabel(row) : kind === "helminthSlot" ? (row.slot === null ? "保留原技能" : `原技能 ${Number(row.slot) + 1}`) : (kind === "frame" ? "满级 30" : (row.tau ? "Tau 级" : (row.rarity || row.category || "静态效果")));
    copy.append(create("strong", "", warframeName(row)), create("small", "", sub), create("p", "", warframeDescription(row) || "暂无说明"));
    option.append(visual, copy);
    option.addEventListener("click", () => applyWarframePickerRow(row));
    return option;
  });
  if (kind === "invigoration" && state.warframeBuild.invigoration.length) {
    const clear = create("button", "warframe-image-option is-clear");
    clear.type = "button";
    clear.append(create("span", "warframe-image-option-visual", "×"), create("span", "warframe-image-option-copy", "不应用活化增幅"));
    clear.addEventListener("click", () => {
      state.warframeBuild.invigoration = [];
      closeWarframePicker();
      renderWarframeWorkbench();
      persistWarframeConfig();
      scheduleWarframeCalculation();
    });
    nodes.unshift(clear);
  }
  ui["warframe-picker-list"].replaceChildren(...(nodes.length ? nodes : [create("p", "empty-copy", "没有符合条件的记录")]));
  if (kind === "invigoration") {
    const categories = new Set(state.warframeBuild.invigoration.map((row) => String(row.category || "").toLocaleLowerCase()));
    const pending = !categories.has("offensive") ? "还需选择攻势增幅" : !categories.has("utility") ? "还需选择辅助增幅" : "攻势与辅助均已选择";
    ui["warframe-picker-sub"].textContent = `${pending} · ${rows.length} 条可选记录`;
  } else if (kind === "shard") {
    // 组合源力石（翠绿/琥珀/紫红）说明：它们已在列表中，来源是 Helminth 的
    // 聚变合成——绯红+碧蓝→紫红、金黄+碧蓝→翠绿、3×绯红→琥珀。
    ui["warframe-picker-sub"].textContent = `${rows.length} 条 · 组合源力石由聚变合成：绯红+碧蓝→紫红 · 金黄+碧蓝→翠绿 · 3×绯红→琥珀`;
  } else ui["warframe-picker-sub"].textContent = `${rows.length} 条可选记录`;
}

function warframePickerRowsForCategory(kind, category) {
  if (!category || category === "all") return warframePickerRowsBase();
  return warframePickerRowsBase().filter((row) => warframeCategoryMatches(row, category));
}

function openWarframePicker(kind, slot = 0) {
  if (isAlternateWarframeForm() && ["helminthSlot", "helminth", "shard", "invigoration"].includes(kind)) {
    const message = kind === "shard" ? "源力石继承同配置槽的本体，请切换到本体后编辑" : kind === "invigoration" ? "活化继承同配置槽的本体，请切换到本体后编辑" : "幽影使用固定技能组，不能进行 Helminth 替换";
    return toast(message);
  }
  const titles = { frame: "选择战甲", helminthSlot: "选择替换技能", helminth: "选择 Helminth 技能", aura: "选择光环 MOD", exilus: "选择战甲 MOD（功能槽）", normal: "选择战甲 MOD", arcane: "选择战甲赋能", shard: "选择执刑官源力石", invigoration: "选择活化增幅" };
  state.warframePickerKind = kind;
  state.warframePickerSlot = Number(slot) || 0;
  state.warframePickerCategory = "all";
  ui["warframe-picker-title"].textContent = titles[kind] || "选择";
  ui["warframe-picker-search"].value = "";
  ui["warframe-picker"].hidden = false;
  ui["mod-picker-scrim"].hidden = false;
  document.body.classList.add("is-modal-open");
  renderWarframePicker();
  ui["warframe-picker-search"].focus();
}

function closeWarframePicker() {
  if (!ui["warframe-picker"] || ui["warframe-picker"].hidden) return;
  hideModPreview();
  ui["warframe-picker"].hidden = true;
  if (ui["mod-picker"].hidden && ui["weapon-picker"].hidden && ui["arcane-picker"].hidden && ui["enemy-picker"].hidden) {
    ui["mod-picker-scrim"].hidden = true;
    document.body.classList.remove("is-modal-open");
  }
}

function applyWarframePickerRow(row) {
  const build = state.warframeBuild;
  const kind = state.warframePickerKind;
  const selected = { ...row, rank: Number(row.maxRank ?? row.rank ?? 0) };
  if (kind === "frame") {
    const frame = warframeResolve(warframeRows("warframes"), row);
    if (frame) selectWarframeFrame(frame);
    closeWarframePicker();
    return;
  }
  if (kind === "helminthSlot") {
    build.helminthSlot = row.slot === null ? null : Number(row.slot);
    if (build.helminthSlot === null) build.helminthAbility = null;
  } else if (kind === "helminth") {
    build.helminthAbility = selected;
  } else if (["aura", "exilus"].includes(kind)) build[kind] = selected;
  else if (kind === "normal") build.normalMods[state.warframePickerSlot] = selected;
  else if (kind === "arcane") build.arcanes[state.warframePickerSlot] = selected;
  else if (kind === "shard") build.shards[state.warframePickerSlot] = selected;
  else {
    const category = String(selected.category || "").toLocaleLowerCase();
    build.invigoration = build.invigoration.filter((row) => !category || String(row.category || "").toLocaleLowerCase() !== category);
    build.invigoration.push(selected);
    build.invigoration = build.invigoration.slice(-2);
  }
  const keepInvigorationOpen = kind === "invigoration" && new Set(build.invigoration.map((item) => String(item.category || "").toLocaleLowerCase())).size < 2;
  if (!keepInvigorationOpen) closeWarframePicker();
  renderWarframeWorkbench();
  persistWarframeConfig();
  scheduleWarframeCalculation();
  if (keepInvigorationOpen) renderWarframePicker();
}

function warframePayload() {
  const build = state.warframeBuild;
  return {
    frameId: warframeId(activeWarframeRecord()),
    aura: warframeSelection(build.aura),
    exilus: warframeSelection(build.exilus),
    normalMods: build.normalMods.flatMap((row, slot) => row ? [{ ...warframeSelection(row), slot }] : []),
    slotPolarities: build.slotPolarities,
    arcanes: build.arcanes.filter(Boolean).map(warframeSelection),
    shards: build.shards.filter(Boolean).map((row) => ({ ...(row.id ? { id: row.id } : { path: row.path }), tau: Boolean(row.tau) })),
    helminthReplacement: build.helminthSlot !== null && build.helminthAbility ? { slot: build.helminthSlot, abilityId: warframeId(build.helminthAbility) } : null,
    invigoration: build.invigoration.map((row) => row.id ? { id: row.id } : { path: row.path }),
    applyConditionals: Boolean(build.applyConditionals),
  };
}

function scheduleWarframeCalculation() {
  window.clearTimeout(warframeRequestTimer);
  if (!state.warframeBuild.frame) return;
  warframeRequestTimer = window.setTimeout(calculateWarframeBuild, 90);
}

async function calculateWarframeBuild() {
  const requestId = ++warframeRequestId;
  const content = ui["warframe-build-content"];
  content.classList.add("is-solving");
  try {
    const response = await fetch("/api/warframe/calculate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(warframePayload()) });
    const body = await response.json();
    if (!response.ok) throw new Error(body?.error?.message || `战甲解算失败（${response.status}）`);
    if (requestId !== warframeRequestId) return;
    state.warframeBuild.result = body;
    renderWarframeResult(body);
    setWarframeMessage("");
  } catch (error) {
    if (requestId === warframeRequestId) setWarframeMessage(error.message || "战甲解算失败");
  } finally {
    if (requestId === warframeRequestId) content.classList.remove("is-solving");
  }
}

function setWarframeMessage(message) {
  ui["warframe-message"].hidden = !message;
  ui["warframe-message"].textContent = message || "";
}

function warframePanelValue(key, value) {
  if (!Number.isFinite(Number(value))) return "--";
  if (["abilityStrength", "abilityDuration", "abilityRange", "abilityEfficiency", "damageReduction"].includes(key)) return `${(Number(value) * 100).toFixed(1).replace(/\.0$/, "")}%`;
  if (key === "sprint") return `${Number(value).toFixed(2)}x`;
  return Math.round(Number(value)).toLocaleString("zh-CN");
}

function warframeAbilityDescription(ability) {
  const template = warframeLocalizedDescription(ability, ability?.alteredDescription || "");
  const scalars = Array.isArray(ability?.scalars) ? ability.scalars : [];
  if (!template || !scalars.length) return template;
  const replacements = {};
  for (const scalar of scalars) {
    const rendered = warframeScalarValueText(scalar);
    if (!rendered || rendered === "--") continue;
    for (const key of [scalar.id, scalar.key, scalar.label].filter(Boolean)) replacements[key] = rendered;
  }
  return template.replace(/\{([^{}]+)\}|\[\[([^\]]+)\]\]/g, (match, brace, wiki) => replacements[brace || wiki] || match);
}

function warframeScalarLabel(scalar) {
  const raw = String(scalar?.labelZh || scalar?.label || scalar?.id || "").trim();
  if (raw && !/^技能数值\s*\d+$/.test(raw) && !/^value\s*\d+$/i.test(raw)) return raw;
  const text = String(scalar?.label || scalar?.id || "").toLocaleLowerCase();
  if (text.includes("damage")) return text.includes("second") || text.includes("/s") ? "每秒伤害" : "伤害";
  if (text.includes("duration") || text.includes("time")) return "持续时间";
  if (text.includes("range") || text.includes("radius")) return "作用范围";
  if (text.includes("energy")) return "能量消耗";
  if (text.includes("chance")) return "几率";
  if (text.includes("target") || text.includes("enemy") || text.includes("charge")) return "目标/次数";
  return "未分类字段";
}

function warframeScalarScaleLabel(scale) {
  return ({ strength: "技能强度", duration: "技能持续", range: "技能范围", efficiency: "技能效率", drain: "效率 / 持续" })[scale] || "固定值";
}

// Overframe 多状态技能的状态分组名（如 Wisp 储能池的 Vitality/Haste/Shock）。
// 冻结数据里 scalarGroups.labelZh 常为未翻译占位，这里在前端补一份译名；
// 未收录的状态名按原样显示（英文），仍能区分状态归属。
const WARFRAME_SCALAR_GROUP_ZH = {
  "vitality": "活力", "haste": "急速", "shock": "震荡",
  "day form": "昼形态", "night form": "夜形态",
  "accuse": "指控", "deny": "否认", "gaze": "凝视", "sentry": "哨戒",
  "cloak": "隐匿", "dashwire": "天索", "noise": "诱饵",
  "maim": "创伤", "mend": "治疗", "pacify": "安抚", "provoke": "激怒",
  "rage": "狂怒", "rest": "休眠", "sleep": "睡眠",
  "protective": "防护", "targeted": "锁定",
  "pageflight": "页面飞行", "tragedy": "悲剧", "triumph": "凯旋",
  "wordwarden": "守护言语",
  "tether-flechette orb": "束缚-飞镖球", "vector-overdrive pad": "矢量-超载台",
  "merulina": "美露琳娜", "yareli": "Yareli", "chroma": "Chroma",
};
function warframeScalarGroupLabel(ability, scalar) {
  const variant = String(scalar?.variant || "").trim();
  if (!variant) return String(scalar?.group || "").trim() === "未分类字段" ? "" : String(scalar?.group || "").trim();
  const groups = Array.isArray(ability?.scalarGroups) ? ability.scalarGroups : [];
  const meta = groups.find((row) => String(row?.labelEn || "").toLocaleLowerCase() === variant.toLocaleLowerCase());
  const zh = WARFRAME_SCALAR_GROUP_ZH[variant.toLocaleLowerCase()];
  if (zh) return zh;
  if (meta?.labelZh && meta.labelZh !== "未分类字段") return String(meta.labelZh);
  return variant;
}

function warframeNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return Number.isInteger(number) ? number.toLocaleString("zh-CN") : number.toFixed(2).replace(/\.00$/, "");
}

function warframeScalarValueText(scalar, key = null) {
  if (scalar?.displayValue !== undefined && scalar.displayValue !== null) return String(scalar.displayValue);
  const parts = scalar?.valueParts && typeof scalar.valueParts === "object" ? scalar.valueParts : {};
  const keys = Array.isArray(scalar?.valueKeys) && scalar.valueKeys.length ? scalar.valueKeys : Object.keys(parts);
  const values = keys.map((name) => Number(parts[name])).filter(Number.isFinite);
  if (!values.length && Number.isFinite(Number(scalar?.value))) values.push(Number(scalar.value));
  if (!values.length) return "--";
  const template = String(scalar?.valueTemplate || "{}");
  let index = 0;
  let rendered = template.replace(/\{\}/g, () => warframeNumber(values[index++]));
  if (!rendered || rendered === "{}") rendered = values.map(warframeNumber).join(" / ");
  const unit = String(scalar?.unit || "");
  return unit && !rendered.endsWith(unit) ? `${rendered}${unit}` : rendered;
}

function warframeScalarBaseText(scalar) {
  if (scalar?.displayValue !== undefined && scalar.displayValue !== null) return String(scalar.displayValue);
  const parts = scalar?.parts && typeof scalar.parts === "object" ? scalar.parts : {};
  const keys = Array.isArray(scalar?.valueKeys) && scalar.valueKeys.length ? scalar.valueKeys : Object.keys(parts);
  const values = keys.map((name) => Number(parts[name])).filter(Number.isFinite);
  if (!values.length && Number.isFinite(Number(scalar?.base))) values.push(Number(scalar.base));
  if (!values.length) return "--";
  const template = String(scalar?.valueTemplate || "{}");
  let index = 0;
  const rendered = template.replace(/\{\}/g, () => warframeNumber(values[index++])) || values.map(warframeNumber).join(" / ");
  const unit = String(scalar?.unit || "");
  return unit && !rendered.endsWith(unit) ? `${rendered}${unit}` : rendered;
}

// 技能数值相对基础的变化方向：isEnergy 字段（能量类消耗）越低越好，
// 其余字段（伤害/持续/范围等）越高越好。固定值（isStatic / scale none）
// 或缺数据返回 ""（保持默认色）。
function warframeScalarDelta(scalar) {
  if (scalar?.isStatic || String(scalar?.scale || "none") === "none") return "";
  const value = Number(scalar?.value);
  const base = Number(scalar?.base);
  if (!Number.isFinite(value) || !Number.isFinite(base) || !base) return "";
  const tolerance = Math.abs(base) * 1e-6;
  if (Math.abs(value - base) <= tolerance) return "";
  const higher = value > base;
  return scalar?.isEnergy ? (higher ? "worse" : "better") : (higher ? "better" : "worse");
}

// 能量/资源消耗行：任意计费字段相对基础的总体方向（低=好）。
function warframeAbilityCostDelta(cost) {
  const fields = ["activation", "airborneActivation", "drainPerSecond", "boostedDrainPerSecond", "perTarget", "perShot", "chargedShot", "perAllyPerSecond", "perEnemyPerSecond", "perAbilityPerSecond", "perDodge", "cooldownSeconds"];
  let better = false;
  let worse = false;
  for (const field of fields) {
    const value = Number(cost?.[field]);
    const baseKey = `base${field[0].toUpperCase()}${field.slice(1)}`;
    const base = Number(cost?.[baseKey]);
    if (!Number.isFinite(value) || !Number.isFinite(base) || !base) continue;
    const tolerance = Math.abs(base) * 1e-6;
    if (value < base - tolerance) better = true;
    else if (value > base + tolerance) worse = true;
  }
  if (better && !worse) return "better";
  if (worse && !better) return "worse";
  return "";
}

function warframeAbilityCost(cost) {
  const resource = String(cost?.resource || "energy");
  const resources = {
    energy: ["能量消耗", "能量"], shield: ["护盾消耗", "护盾"], health: ["生命消耗", "生命值"],
    mutation: ["突变消耗", "层突变"], restraint: ["克制值变化", "克制值"], deathWell: ["死亡之井", "死亡之井"], cooldown: ["技能冷却", "秒"],
  };
  const [label, unit] = resources[resource] || ["技能消耗", resource];
  const parts = [];
  const baseParts = [];
  const add = (field, prefix, suffix = ` ${unit}`) => {
    if (!Number.isFinite(Number(cost?.[field]))) return;
    parts.push(`${prefix}${warframeNumber(cost[field])}${suffix}`);
    const baseKey = `base${field[0].toUpperCase()}${field.slice(1)}`;
    if (Number.isFinite(Number(cost?.[baseKey]))) baseParts.push(`${prefix}${warframeNumber(cost[baseKey])}${suffix}`);
  };
  if (resource === "cooldown") add("cooldownSeconds", "冷却 ", " 秒");
  else {
    if (Number(cost?.activation) > 0) add("activation", "施放 ");
    add("airborneActivation", "空中施放 ");
    add("drainPerSecond", "持续 ", ` ${unit}/秒`);
    add("boostedDrainPerSecond", "强化持续 ", ` ${unit}/秒`);
    add("perTarget", "每个目标 ");
    add("perShot", "每次射击 ");
    add("chargedShot", "满蓄力射击 ");
    add("perAllyPerSecond", "每名友军 ", ` ${unit}/秒`);
    add("perEnemyPerSecond", "每名敌人 ", ` ${unit}/秒`);
    add("perAbilityPerSecond", "每个技能 ", ` ${unit}/秒`);
    add("perDodge", "每次闪避 ");
    add("reviveMaximum", "立即复活最多 ");
  }
  if (Number.isFinite(Number(cost?.targetCap))) parts.push(`最多计费 ${warframeNumber(cost.targetCap)} 个目标`);
  if (Number.isFinite(Number(cost?.maximumHealthPercent))) parts.push(`最多 ${warframeNumber(cost.maximumHealthPercent)}% 最大生命值`);
  if (Number.isFinite(Number(cost?.minimumRemaining))) parts.push(`最低保留 ${warframeNumber(cost.minimumRemaining)} 生命值`);
  if (Number.isFinite(Number(cost?.stacks))) parts.push(`${warframeNumber(cost.stacks)} 层突变`);
  if (Number.isFinite(Number(cost?.perChargePercent))) parts.push(`每 1% 充能消耗 ${warframeNumber(cost.perChargePercent)} 生命值`);
  if (Number.isFinite(Number(cost?.maximumTotal))) parts.push(`完全充能最多 ${warframeNumber(cost.maximumTotal)} 生命值`);
  if (Number.isFinite(Number(cost?.restoreOnActivationPercent))) parts.push(`启用时恢复 ${warframeNumber(cost.restoreOnActivationPercent)}% 克制值`);
  if (Number.isFinite(Number(cost?.restorePerSecondPercent))) parts.push(`每秒恢复 ${warframeNumber(cost.restorePerSecondPercent)}% 克制值`);
  if (Number.isFinite(Number(cost?.requiredPercent))) parts.push(`需要至少 ${warframeNumber(cost.requiredPercent)}% 死亡之井`);
  if (Number.isFinite(Number(cost?.drainPerSecondPercent))) parts.push(`每秒消耗 ${warframeNumber(cost.drainPerSecondPercent)}% 死亡之井`);
  if (cost?.variableChannel) parts.push("持续引导会继续消耗能量");
  return { label, text: parts.join(" · ") || "以官方描述中的特殊资源规则为准", base: baseParts.join(" · "), note: String(cost?.noteZh || "") };
}

function renderWarframeResult(result) {
  if (result.passive) ui["warframe-passive"].textContent = warframePassiveText(result);
  const capacity = result.capacityBreakdown || {};
  ui["warframe-capacity-readout"].textContent = `${capacity.remaining ?? "--"} / ${capacity.limit ?? 60}`;
  const used = Number(capacity.used || 0);
  const limit = Math.max(1, Number(capacity.limit || 60));
  ui["warframe-capacity-bar"].style.width = `${clamp(used / limit * 100, 0, 100)}%`;
  ui["warframe-capacity-bar"].classList.toggle("is-over", capacity.valid === false);
  const forma = result.formaBreakdown || {};
  const formaTotal = Object.values(forma).reduce((sum, value) => sum + (Number(value) || 0), 0);
  ui["warframe-forma-readout"].textContent = formaTotal ? `×${formaTotal}` : "无需";
  ui["warframe-forma-readout"].title = `光环 ${forma.aura || 0} · 功能槽 ${forma.exilus || 0} · 普通 ${forma.normal || 0}`;
  ui["warframe-effect-status"].textContent = state.warframeBuild.applyConditionals ? "触发效果已按完整效果应用" : "触发效果关闭";
  const base = result.basePanel || {};
  const final = result.finalPanel || {};
  // 派生项的基础值：后端只在 finalPanel 里给 damageReduction/ehp，
  // 基础值按同一公式从基础护甲/生命值推导，保证颜色对比有意义。
  const baseArmor = Number(base.armor ?? base.armour);
  const baseHealth = Number(base.health);
  if (Number.isFinite(baseArmor) && baseArmor > 0) {
    base.damageReduction = baseArmor / (baseArmor + 300);
    if (Number.isFinite(baseHealth) && baseHealth > 0) {
      base.ehp = baseHealth / Math.max(1e-9, 1 - base.damageReduction);
    }
  }
  const stats = [
    ["health", "生命值"], ["shield", "护盾"], ["armor", "护甲"], ["energy", "能量"], ["sprint", "冲刺速度"],
    ["abilityStrength", "技能强度"], ["abilityDuration", "技能持续"], ["abilityRange", "技能范围"], ["abilityEfficiency", "技能效率"], ["damageReduction", "护甲减伤"], ["ehp", "生命等效 EHP"],
  ];
  ui["warframe-panel-grid"].replaceChildren(...stats.map(([key, label]) => {
    const cell = create("div", "warframe-panel-stat");
    const finalValue = warframePanelValue(key, final[key]);
    const isPercentStat = ["abilityStrength", "abilityDuration", "abilityRange", "abilityEfficiency"].includes(key);
    const baseValue = isPercentStat ? "100%" : warframePanelValue(key, base[key]);
    // 颜色语义：比基础更好=绿，更差=红，不变/缺数据=默认色。
    // 所有面板项（含技能效率百分比）都是「数值越高越好」；能量消耗是
    // 单独的技能卡行，不在此表内。
    const finalNum = Number(final[key]);
    const baseNum = isPercentStat ? 1 : Number(base[key]);
    if (Number.isFinite(finalNum) && Number.isFinite(baseNum)) {
      const tolerance = Math.abs(baseNum) * 1e-6;
      if (finalNum > baseNum + tolerance) cell.classList.add("is-improved");
      else if (finalNum < baseNum - tolerance) cell.classList.add("is-worse");
    }
    cell.append(create("span", "", label), create("strong", "", finalValue), create("small", "", `基础 ${baseValue}`));
    return cell;
  }));
  renderWarframeExaltedCard();
  const globalScale = `强度 ${warframePanelValue("abilityStrength", final.abilityStrength)} · 持续 ${warframePanelValue("abilityDuration", final.abilityDuration)} · 范围 ${warframePanelValue("abilityRange", final.abilityRange)} · 效率 ${warframePanelValue("abilityEfficiency", final.abilityEfficiency)}`;
  const sourceAbilities = Array.isArray(activeWarframeRecord()?.abilities) ? activeWarframeRecord().abilities : [];
  const abilities = Array.isArray(result.abilityScalars) ? result.abilityScalars : sourceAbilities;
  ui["warframe-ability-grid"].replaceChildren(...abilities.map((ability, index) => {
    const source = sourceAbilities[index] || {};
    ability = { ...source, ...ability, iconAsset: ability.iconAsset || source.iconAsset || source.icon };
    const replaced = state.warframeBuild.helminthSlot === index && state.warframeBuild.helminthAbility;
    const card = create("article", `warframe-ability-card${replaced || ability.altered || ability.helminth ? " is-helminth" : ""}`);
    const head = create("div", "warframe-ability-head");
    const icon = ability.iconAsset || ability.icon;
    if (icon) head.append(imageNode(icon, "", warframeName(ability), "lazy"));
    head.append(create("strong", "", warframeName(ability)));
    if (replaced || ability.altered || ability.helminth) head.append(create("b", "", "HELMINTH"));
    card.append(head, create("p", "warframe-ability-description", warframeAbilityDescription(ability) || "暂无官方描述"));
    const scalarList = create("div", "warframe-ability-scalars");
    const cost = ability.energyCost || {};
    const scalars = Array.isArray(ability.scalars) ? ability.scalars : [];
    const hasEnergyFields = scalars.some((scalar) => scalar.isEnergy || /energy cost|energy drain/i.test(String(scalar.label || "")));
    const hasExtraCostFields = ["perTarget", "perShot", "chargedShot", "perAllyPerSecond", "perEnemyPerSecond", "perAbilityPerSecond", "airborneActivation"].some((key) => Number.isFinite(Number(cost[key]))) || String(cost.resource || "energy") !== "energy";
    if (!hasEnergyFields || hasExtraCostFields) {
      const costDisplay = warframeAbilityCost(cost);
      const costRow = create("div", `warframe-ability-energy is-${String(cost.resource || "energy").replace(/[^a-z]/gi, "")}`);
      // 能量/资源消耗：数值越低越好——比基础低=绿（省），比基础高=红（贵）。
      const costDelta = warframeAbilityCostDelta(cost);
      if (costDelta === "better") costRow.classList.add("is-improved");
      else if (costDelta === "worse") costRow.classList.add("is-worse");
      costRow.append(create("span", "", costDisplay.label), create("strong", "", costDisplay.text), create("small", "", costDisplay.note || (costDisplay.base ? `基础 ${costDisplay.base}` : "官方资源规则")));
      scalarList.append(costRow);
    }
    let currentGroup = "";
    if (scalars.length) scalars.forEach((scalar) => {
      if (hasExtraCostFields && scalar.isEnergy && /energy cost/i.test(String(scalar.label || "")) && Number(scalar.value) === 0) return;
      // 多状态技能（如 Wisp 储能池的活力/急速/震荡）按 variant 分组展示；
      // 旧数据的 group 字段常是未翻译占位（「未分类字段」），variant 才是
      // Overframe 的原始状态名。scalarGroups 提供顺序与中文译名。
      const group = warframeScalarGroupLabel(ability, scalar);
      if (group && group !== currentGroup) {
        scalarList.append(create("p", "warframe-ability-scalar-group", group));
        currentGroup = group;
      } else if (group && group === currentGroup) {
        // 同组延续：无需重复标题
      } else if (!group && currentGroup) {
        currentGroup = "";
      }
      const row = create("div", [scalar.isStatic || scalar.scale === "none" ? "is-static" : "", scalar.isEnergy ? "is-energy" : "", scalar.scale === "range" ? "is-range" : ""].filter(Boolean).join(" "));
      // 数值颜色只按「相对基础变好/变坏/不变」区分：能量类字段越低越好，
      // 其余（伤害/持续/范围等）越高越好；固定值保持默认色。
      const delta = warframeScalarDelta(scalar);
      if (delta === "better") row.classList.add("is-improved");
      else if (delta === "worse") row.classList.add("is-worse");
      row.append(create("span", "", warframeScalarLabel(scalar)), create("strong", "", warframeScalarValueText(scalar)), create("small", "", `${warframeScalarScaleLabel(scalar.scale)} · 基础 ${warframeScalarBaseText(scalar)}`));
      scalarList.append(row);
    });
    else {
      scalarList.append(create("p", "", "该技能没有可调整的数值，以官方描述为准"));
    }
    card.append(scalarList, create("small", "warframe-ability-global", globalScale));
    return card;
  }));
  const validation = result.validation || {};
  const diagnostics = [...(validation.errors || []), ...(validation.warnings || [])].filter(Boolean);
  ui["warframe-diagnostic-count"].textContent = String(diagnostics.length);
  ui["warframe-diagnostic-list"].replaceChildren(...(diagnostics.length ? diagnostics.map((line) => create("p", "", String(line))) : [create("p", "", "本次容量、槽位和资料校验通过。")])) ;
}

function setActiveTool(name) {
  if (!ui[`${name}-tool`]) return;
  state.activeTool = name;
  ui["analysis-tool"].hidden = name !== "analysis";
  ui["build-tool"].hidden = name !== "build";
  ui["warframe-tool"].hidden = name !== "warframe";
  if (name === "analysis") requestAnimationFrame(fitRivenCardText);
  ui["page-title"].textContent = name === "warframe" ? "战甲配装" : name === "build" ? "武器配装" : "紫卡分析";
  for (const button of document.querySelectorAll("[data-tab]")) {
    const active = button.dataset.tab === name;
    button.classList.toggle("is-active", active);
    if (button.getAttribute("role") === "tab") button.setAttribute("aria-selected", String(active));
  }
  for (const button of [ui["sample-button"], ui["reset-button"], ui["export-button"]]) button.hidden = name !== "analysis";
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  if (name === "warframe") loadWarframeCatalog().catch(() => {});
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function bindWarframeEvents() {
  ui["warframe-frame-open"]?.addEventListener("click", () => openWarframePicker("frame"));
  ui["warframe-apply-conditionals"]?.addEventListener("change", () => {
    state.warframeBuild.applyConditionals = Boolean(ui["warframe-apply-conditionals"].checked);
    persistWarframeConfig();
    scheduleWarframeCalculation();
  });
  ui["warframe-helminth-slot-open"]?.addEventListener("click", () => openWarframePicker("helminthSlot"));
  ui["warframe-helminth-ability-open"]?.addEventListener("click", () => openWarframePicker("helminth"));
  ui["warframe-invigoration-open"]?.addEventListener("click", () => openWarframePicker("invigoration"));
  ui["warframe-config-tabs"]?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-warframe-config]");
    if (button) switchWarframeConfig(button.dataset.warframeConfig);
  });
  ui["warframe-config-copy"]?.addEventListener("click", copyWarframeConfig);
  ui["warframe-config-export-json"]?.addEventListener("click", exportWarframeConfig);
  ui["warframe-config-export-rabbit"]?.addEventListener("click", () => openRabbitDialog("export", "warframe"));
  ui["warframe-config-import-json"]?.addEventListener("click", () => ui["warframe-config-import-file"]?.click());
  ui["warframe-config-import-rabbit"]?.addEventListener("click", () => openRabbitDialog("import", "warframe"));
  ui["warframe-config-import-file"]?.addEventListener("change", () => importWarframeConfig(ui["warframe-config-import-file"].files?.[0]));
  ui["warframe-clear"]?.addEventListener("click", () => {
    applyWarframeConfig(null);
    persistWarframeConfig();
  });
  ui["warframe-picker-search"]?.addEventListener("input", renderWarframePicker);
  ui["warframe-picker-close"]?.addEventListener("click", closeWarframePicker);
  ui["mod-picker-scrim"]?.addEventListener("click", closeWarframePicker);
  bindConfigActionMenus();
}

function metricOptionsFor(weapon) {
  const kind = ["melee", "zaw"].includes(weapon?.weaponType) ? "melee" : "gun";
  return state.catalog?.buildOptions?.metrics?.[kind] || [];
}

function refreshProjectileStrategyControls() {
  const path = state.buildWeapon?.path;
  const alternate = Number(ui["build-fire-mode-select"]?.value || 0) === 1;
  const quanta = new Set([
    "/Lotus/Weapons/Corpus/LongGuns/CrpShockRifle/CrpShockRifle",
    "/Lotus/Weapons/Corpus/LongGuns/CrpShockRifle/QuantaVandal",
    "/Lotus/Weapons/Corpus/BoardExec/Primary/CrpBEQuanta/CrpBEQuanta",
  ]);
  const phantasma = new Set([
    "/Lotus/Weapons/Tenno/LongGuns/RevenantShotgun/RevenantShotgun",
    "/Lotus/Weapons/Tenno/LongGuns/PrimePhantasma/PhantasmaPrimeShotgun",
  ]);
  const grimoire = document.getElementById('build-grimoire-strategy-fields');
  if (grimoire) grimoire.hidden = !(alternate && path === '/Lotus/Weapons/Tenno/Grimoire/TnGrimoire');
  const grimoireEnabled = document.querySelector('[data-combat-state="grimoireStrategy"]')?.value === 'single-occupant';
  for (const input of document.querySelectorAll('#build-grimoire-strategy-fields input')) input.disabled = !grimoireEnabled;
  const cubes = document.getElementById("build-quanta-strategy-fields");
  const children = document.getElementById("build-phantasma-child-fields");
  if (cubes) cubes.hidden = !(alternate && quanta.has(path));
  if (children) children.hidden = !(alternate && phantasma.has(path));
  const overlap = document.querySelector('[data-combat-state="phantasmaChildOverlap"]');
  const arrival = document.querySelector('[data-combat-state="phantasmaChildArrivalSeconds"]');
  if (arrival) arrival.disabled = overlap?.value !== 'ideal-contact';
  const zymos = document.getElementById('build-zymos-child-fields');
  if (zymos) zymos.hidden = alternate || path !== '/Lotus/Weapons/Infested/Pistols/InfUzi/InfUziWeapon';
  const zymosEnabled = document.querySelector('[data-combat-state="zymosChildOverlap"]')?.value === 'ideal-contact';
  for (const input of document.querySelectorAll('#build-zymos-child-fields input')) input.disabled = !zymosEnabled;
}

function refreshBuildMetrics() {
  refreshProjectileStrategyControls();
  const mode = state.buildWeapon?.fireModes?.find((entry) => String(entry.index) === ui["build-fire-mode-select"].value);
  const availability = mode?.metricAvailability || {};
  const previous = ui["build-metric-select"].value;
  const options = metricOptionsFor(state.buildWeapon).map((metric) => {
    const status = availability[metric.id];
    const available = status === undefined || status === true || status?.available !== false;
    const option = document.createElement("option");
    option.value = metric.id;
    option.disabled = !available;
    const label = METRIC_LABELS[metric.id] || metric.label;
    option.textContent = available ? label : `${label} · 不可用`;
    option.title = issueLabel(status?.issue);
    return option;
  });
  ui["build-metric-select"].replaceChildren(...options);
  const selected = options.find((option) => option.value === previous && !option.disabled) || options.find((option) => !option.disabled);
  if (selected) ui["build-metric-select"].value = selected.value;
}

function renderIncarnonChoices() {
  const panel = ui["build-incarnon-panel"];
  const target = ui["build-incarnon-tiers"];
  if (!panel || !target) return;
  const tiers = Array.isArray(state.buildWeapon?.incarnon) ? state.buildWeapon.incarnon : [];
  panel.hidden = !tiers.length;
  if (!tiers.length) {
    state.incarnonChoices = {};
    target.replaceChildren();
    return;
  }
  const selectable = (tier) => tier.selectable ?? Number(tier.tier) !== 1;
  const allowed = new Set(tiers.filter(selectable).map((tier) => `tier${tier.tier}`));
  state.incarnonChoices = Object.fromEntries(Object.entries(state.incarnonChoices).filter(([key]) => allowed.has(key)));
  for (const tier of tiers) {
    // Tier I is a fixed unlock/passive description, never a submitted choice.
    if (!selectable(tier)) continue;
    const key = `tier${tier.tier}`;
    if (!tier.options.some((option) => option.id === state.incarnonChoices[key])) {
      state.incarnonChoices[key] = tier.options.some((option) => option.id === tier.recommended)
        ? tier.recommended
        : tier.options[0]?.id;
    }
  }
  target.replaceChildren(...tiers.map((tier) => {
    const key = `tier${tier.tier}`;
    const field = create("fieldset", "incarnon-tier");
    const legend = create("legend", "", tier.label);
    const options = create("div", "incarnon-options");
    if (!selectable(tier)) {
      field.classList.add("is-fixed");
      for (const option of tier.options) {
        const copy = create("div", "incarnon-fixed-option");
        copy.append(create("strong", "", `${option.label} · 固定`));
        appendIncarnonDetails(copy, option);
        options.append(copy);
      }
      field.append(legend, options);
      return field;
    }
    for (const option of tier.options) {
      const label = create("label", `incarnon-option${option.complete ? "" : " is-partial"}`);
      const input = document.createElement("input");
      input.type = "radio"; input.name = `incarnon-${tier.tier}`; input.value = option.id;
      input.checked = state.incarnonChoices[key] === option.id;
      input.addEventListener("change", () => {
        state.incarnonChoices[key] = option.id;
        persistActiveBuildConfig();
        scheduleLiveBuild();
      });
      const copy = create("span");
      const title = create("strong", "", `${option.label}${option.id === tier.recommended ? " · 推荐" : ""}`);
      copy.append(title);
      appendIncarnonDetails(copy, option);
      label.append(input, copy);
      options.append(label);
    }
    field.append(legend, options);
    return field;
  }));
}

function appendIncarnonDetails(copy, option) {
  if (!option.details?.length) {
    copy.append(create("small", "", option.description));
    if (option.unsupported?.length) copy.append(create("em", "", option.unsupported.join("；")));
    return;
  }
  for (const detail of option.details) {
    const line = create("small", "incarnon-detail", String(detail.text || "").replace(/[。.]:?：/g, "："));
    if (detail.calculation) {
      line.append(create("em", detail.modeled ? "is-modeled" : "is-unmodeled", detail.calculation));
    }
    copy.append(line);
  }
}

function selectBuildWeapon(weapon, writeInput = true) {
  if (state.buildWeapon && state.buildWeapon.path !== weapon?.path) persistActiveBuildConfig();
  state.buildWeapon = weapon;
  state.buildResult = null;
  if (ui["build-manual-detonation"]) ui["build-manual-detonation"].hidden = weapon?.path !== "/Lotus/Weapons/Tenno/ThrowingWeapons/U18ThrowingKnives/U18throwingknives";
  const battacorCharges = document.getElementById("build-battacor-charges-field");
  if (battacorCharges) battacorCharges.hidden = weapon?.path !== "/Lotus/Weapons/Corpus/LongGuns/CrpSentExperimentRifle/CrpSentExperimentRifle";
  const isKitgunBase = weapon && String(weapon.nameEn || "").trim() === "Kitgun";
  const isZawWeapon = isZawBase(weapon);
  const isAssemblyBase = isKitgunBase || isZawWeapon;
  const variantField = ui["build-variant-select"]?.closest(".field");
  if (variantField) variantField.hidden = isAssemblyBase;
  if (writeInput) ui["build-weapon"].value = weapon ? buildWeaponOptionLabel(weapon) : "";
  // 组合枪/组合近战的倾向跟随装配部件（腔体/剑刃），未装配完成时显示 "--"；
  // 普通武器保持目录基体倾向。
  const assemblyDispo = isAssemblyBase && state.kitgunBase?.path === weapon?.path && assemblyWeaponReady()
    ? assemblyChamberDisposition()
    : null;
  const shownDisposition = isAssemblyBase ? assemblyDispo : weapon?.disposition;
  if (isAssemblyBase && weapon) state.buildWeapon = { ...weapon, disposition: shownDisposition };
  ui["build-disposition"].textContent = formatDisposition(shownDisposition);
  ui["build-disposition-dots"].textContent = dispositionDots(shownDisposition);
  // 显赫武器没有紫卡：暂时隐藏倾向栏。
  const dispositionCard = ui["build-disposition"].closest(".build-disposition-card");
  if (dispositionCard) dispositionCard.hidden = Boolean(weapon?.exalted);
  ui["build-weapon-caption"].textContent = weapon
    ? `${TYPE_LABELS[weapon.weaponType] || weapon.weaponType} · ${weapon.nameInternal}`
    : "请选择目录中的完整武器名称";
  if (ui["weapon-build-archetype"]) {
    ui["weapon-build-archetype"].hidden = true;
    ui["weapon-build-archetype"].textContent = "";
  }
  const assemblyReadyNow = isAssemblyBase && assemblyWeaponReady();
  const issueText = assemblyReadyNow
    ? ""
    : isAssemblyBase
      ? (isZawWeapon ? "组合近战需要先装配剑刃 / 握把 / 配重（见上方装配面板）" : "组合枪需要先装配腔体 / 握把 / 装填器（见上方装配面板）")
      : issueLabel(weapon?.buildIssue || weapon?.issue);
  ui["build-weapon-issue"].hidden = !weapon || !issueText;
  ui["build-weapon-issue-text"].textContent = issueText;

  const group = weapon?.variantGroupPath || weapon?.path;
  const variants = weapon ? state.catalog.weapons.filter((entry) => (entry.variantGroupPath || entry.path) === group && !entry.hiddenFromBuildPicker) : [];
  ui["build-variant-select"].replaceChildren(...variants.map((variant) => {
    const option = document.createElement("option");
    option.value = variant.path;
    option.disabled = variant.buildAvailable === false;
    option.textContent = `${weaponName(variant)} · ${variantLabel(variant.variantType)}${variant.buildAvailable === false ? " · 不可用" : ""}`;
    return option;
  }));
  ui["build-variant-select"].disabled = variants.length < 2;
  if (weapon) ui["build-variant-select"].value = weapon.path;
  ui["build-variant-caption"].textContent = variants.length > 1 ? `该基型共有 ${variants.length} 个版本` : "该武器没有其他可选版本";

  const fireModes = Array.isArray(weapon?.fireModes) ? weapon.fireModes : [];
  const modeSource = fireModes.length ? fireModes : (isAssemblyBase ? [{ index: 0, trigger: "" }] : []);
  ui["build-fire-mode-select"].replaceChildren(...(modeSource.length ? modeSource : [{ index: 0, available: false }]).map((mode) => {
    const option = document.createElement("option");
    option.value = String(mode.index ?? 0);
    option.disabled = mode.available === false;
    const detail = mode.available === false ? `不可用 · ${issueLabel(mode.issue) || "无直接伤害"}` : isAssemblyBase && !fireModes.length ? "由装配部件决定" : `${triggerLabel(mode.trigger, mode.index)}${mode.isAlternateFire ? " · 副开火" : ""}${mode.isIncarnonForm ? " · 灵化形态" : ""}`;
    option.textContent = `模式 ${(mode.index ?? 0) + 1} · ${detail}`;
    return option;
  }));
  // 灵化武器默认选中灵化形态（与紫卡分析/黑猫口径一致），其余武器取首个可用模式。
  const incarnonMode = modeSource.find((mode) => mode.isIncarnonForm && mode.available !== false);
  const firstMode = modeSource.find((mode) => mode.available !== false);
  const defaultMode = incarnonMode || firstMode;
  if (defaultMode) ui["build-fire-mode-select"].value = String(defaultMode.index);
  refreshBuildMetrics();
  // New weapon starts with the deterministic Heat progenitor default; a saved
  // config applied below may override it.
  setControlValue("build-innate-element-value", 60);
  refreshInnateElementControls(weapon, defaultInnateElement(weapon));
  const buildAvailable = weapon?.buildAvailable !== false || isAssemblyBase;
  const weaponUsable = isAssemblyBase || weapon?.available;
  if (weaponUsable && !buildAvailable) {
    ui["build-weapon-issue"].hidden = false;
    ui["build-weapon-issue-text"].textContent = issueLabel(weapon.buildIssue) || "没有可用的配装候选";
  }
  showBuildMessage("");
  setWeaponBuildState("idle");
  state.manualSlots = Array.from({ length: 8 }, () => null);
  state.incarnonChoices = {};
  state.manualSlot = 0;
  state.formaSlots = {};
  refreshFormaCount();
  if (!isAssemblyBase) {
    state.kitgunBase = null;
    state.kitgunParts = null;
  } else if (state.kitgunBase && state.kitgunBase.path !== weapon.path) {
    state.kitgunParts = { chamber: null, grip: null, loader: null };
  }
  const kitgunPanel = document.getElementById("kitgun-assembly");
  if (kitgunPanel && !isAssemblyBase) kitgunPanel.hidden = true;
  loadBuildConfigsForWeapon(weapon);
  applyBuildConfig(state.buildConfigs[state.activeConfig]);
  renderIncarnonChoices();
  renderManualSlots();
  renderManualMods();
  renderExternalBuffs(); // which buffs reach this weapon (Warcry: melee only…)
  if ((weapon?.available || isAssemblyBase) && buildAvailable && (!isAssemblyBase || assemblyWeaponReady())) scheduleLiveBuild();
}

function showBuildMessage(message) {
  ui["build-form-message"].hidden = !message;
  ui["build-form-message"].textContent = message || "";
}

// 敌人强化开关（卓越者 / 敌人强化+人数 / 科研超宏词条）：全部默认关闭，
// 引擎按 wiki 与 LotusDifficultyTable 快照的静态公式回放。
function enemyEnhancementsPayload() {
  const empowered = Boolean(ui["build-enemy-empowered"]?.checked);
  return {
    eximus: Boolean(ui["build-enemy-eximus"]?.checked),
    empowered,
    playerCount: empowered ? clamp(Number(ui["build-enemy-player-count"]?.value || 1), 1, 4) : null,
    archimedea: Boolean(ui["build-enemy-archimedea"]?.checked),
  };
}

function syncEmpoweredPlayerCount() {
  const select = ui["build-enemy-player-count"];
  if (select) select.disabled = !ui["build-enemy-empowered"]?.checked;
}

// 敌人当前数据面板：直接读本次解算的 targetDamage（引擎已按等级/钢铁之路/
// 强化开关/削甲折算），等效生命值 = 生命/(1-减伤) + 护盾 + 超宏。
function updateEnemyStatsPanel(result) {
  const panel = ui["build-enemy-stats"];
  if (!panel) return;
  const sim = result?.simulation || result || {};
  const target = sim.targetDamage;
  // ── 即时口径行（2026-09-24）：等级/强化标签来自表单状态，不等解算
  // 返回——选项或等级一改立刻刷新（防御数值仍随后端缩放返回更新）。
  updateEnemyStatsContext();
  if (!target || !Number.isFinite(Number(target.health))) {
    panel.hidden = true;
    return;
  }
  const health = Number(target.health) || 0;
  const shield = Number(target.shield) || 0;
  const armour = Number(target.armour) || 0;
  const reduction = Number(target.armourReduction) || 0;
  const overguard = Number(target.overguard) || 0;
  const ehp = health / Math.max(1 - reduction, 0.0001) + shield + overguard;
  const set = (key, text) => {
    const node = panel.querySelector(`[data-enemy-stat="${key}"]`);
    if (node) node.textContent = text;
  };
  set("health", formatMetric(health));
  set("shield", formatMetric(shield));
  set("armour", formatMetric(armour));
  set("reduction", `${(reduction * 100).toFixed(1)}%`);
  set("overguard", formatMetric(overguard));
  set("ehp", formatMetric(ehp));
  panel.hidden = false;
}

function updateEnemyStatsContext() {
  // 等级与强化标签全部来自当前表单：可即时渲染，与解算结果无关。
  const panel = ui["build-enemy-stats"];
  if (!panel) return;
  const tags = [];
  if (ui["build-enemy-eximus"]?.checked) tags.push("卓越者");
  if (ui["build-enemy-empowered"]?.checked) tags.push(`强化·${ui["build-enemy-player-count"]?.value || 1}人`);
  if (ui["build-enemy-archimedea"]?.checked) tags.push("科研超宏");
  if (ui["build-steel-path"]?.checked) tags.push("钢铁之路");
  const ctx = ui["build-enemy-stats-context"];
  if (ctx) ctx.textContent = [`Lv ${ui["build-enemy-level"]?.value || 160}`, ...tags].join(" · ");
}

function setWeaponBuildState(name) {
  ui["weapon-build-idle"].hidden = name !== "idle";
  ui["weapon-build-loading"].hidden = name !== "loading";
  ui["weapon-build-error"].hidden = name !== "error";
  ui["weapon-build-content"].hidden = name !== "content";
  if (ui["live-hud"]) ui["live-hud"].dataset.state = name;
}

function buildPayloadFromForm() {
  const damageModel = ui["build-damage-model"]?.value || "panel";
  if (damageModel === "custom" && !customDamageSupported()) throw new Error("当前版本不支持自定义防御");
  const mods = state.manualSlots.flatMap((mod, slot) => (mod && !mod.__riven) ? [{
    path: mod.path,
    slot,
    rank: Number(mod.rank ?? mod.maxRank ?? 0),
  }] : []);
  const customDefense = {
    health: Number(ui["build-custom-health"]?.value || 0),
    armor: Number(ui["build-custom-armor"]?.value || 0),
    shield: Number(ui["build-custom-shield"]?.value || 0),
    healthType: ui["build-custom-health-type"]?.value.trim() || "",
    armorType: ui["build-custom-armor-type"]?.value.trim() || "",
    shieldType: ui["build-custom-shield-type"]?.value.trim() || "",
  };
  const weapon = state.buildWeapon;
  if (!weapon) throw new Error("请从武器目录中选择一把武器");
  const isAssemblyWeapon = String(weapon.nameEn || "").trim() === "Kitgun" || isZawBase(weapon);
  if ((!weapon.available || weapon.buildAvailable === false) && !(isAssemblyWeapon && assemblyWeaponReady())) throw new Error(weapon.buildIssue || weapon.issue || "该武器暂不可配装");
  if (damageModel === "custom" && (!customDefense.healthType || !customDefense.armorType || !customDefense.shieldType)) {
    throw new Error("custom defense requires health, armor, and shield types; use RK_NONE for zero pools");
  }
  return {
    weapon: weapon.path,
    fireMode: Number(ui["build-fire-mode-select"].value || 0),
    metric: ui["build-metric-select"].value,
    profile: solveProfile(),
    requiredMods: state.requiredMods.length ? [...state.requiredMods] : undefined,
    forbiddenMods: scopeForbiddenPaths(),
    excludeFactionMods: state.excludeFactionMods || undefined,
    sentinel: sentinelPayload(),
    exaltedFrame: exaltedPayload(),
    companionPlayerStacks: isCompanionWeapon() && state.companionPlayerStacks ? true : undefined,
    minFill: scopeFillValue("build-min-fill"),
    maxFill: scopeFillValue("build-max-fill"),
    optimizeWithArcanes: !ui["build-optimize-arcanes"]?.checked ? false : undefined,
    // 自动选择（默认关闭）：武器赋能 / 灵化进化路线交给求解，结果填回槽位。
    autoArcane: ui["build-auto-arcane"]?.checked ? true : undefined,
    autoIncarnon: ui["build-auto-incarnon"]?.checked && Array.isArray(state.buildWeapon?.incarnon) && state.buildWeapon.incarnon.length ? true : undefined,
    // 触发类效果口径：emergent（按实际爬升，窗口模型模拟）/ assumed_max（恒满）。
    triggerPolicy: document.getElementById("trigger-policy-select")?.value || "emergent",
    elementTarget: ui["build-element-select"].value || null,
    innateElement: ui["build-innate-element-select"]?.value || null,
    innateElementValue: Number(ui["build-innate-element-value"]?.value || 60) / 100,
    slotCount: Number(ui["build-slot-count"].value),
    slotPolarities: slotPolaritiesPayload(),
    specialSlotPolarities: specialSlotPolaritiesPayload(),
    mode: state.buildInputMode,
    mods,
    enemy: ui["build-enemy-select"]?.value || null,
    level: Number(ui["build-enemy-level"]?.value || 160),
    steelPath: Boolean(ui["build-steel-path"]?.checked),
    enemyEnhancements: enemyEnhancementsPayload(),
    armourStrip: Number(ui["build-armour-strip"]?.value || 0),
    headshotChance: Number(ui["build-headshot-chance"]?.value || 0),
    distance: Number(ui["build-distance"]?.value || 0) || null,
    detonationBatchSize: ui["build-manual-detonation"]?.hidden === false ? Number(ui["build-detonation-batch"]?.value || 1) : 1,
    detonationDelaySeconds: ui["build-manual-detonation"]?.hidden === false ? Number(ui["build-detonation-delay"]?.value || 0) : 0,
    combatState: combatStatePayload(),
    comboTier: Number(ui["build-combo-tier"]?.value || 0),
    heavyAttack: Boolean(ui["build-heavy-attack"]?.checked),
    damageModel,
    customDefense,
    defenseSnapshot: damageModel === "custom" ? customDefense : null,
    stancePath: state.stanceSelection?.path || null,
    exilus: compactRankedSelection(state.exilusSelection),
    arcanes: state.arcaneSelections.map(arcaneSimulationSelection),
    externalBuffs: externalBuffsPayload(),
    riven: rivenPayload(),
    kitgunParts: kitgunPartsPayload(),
    incarnonChoices: { ...state.incarnonChoices },
    aiming: Boolean(ui["build-aiming"]?.checked),
    // 回放按弱点充能、切换时间与实际弹池结算。
    incarnonCycle: Boolean(ui["build-incarnon-cycle"]?.checked),
  };
}

function renderDamageTypes(result) {
  const entries = Object.entries(resultBuildView(result).damageTypes || {}).filter(([, value]) => finite(value) !== null && Number(value) > 0).sort((a, b) => Number(b[1]) - Number(a[1]));
  const total = entries.reduce((sum, [, value]) => sum + Number(value), 0) || 1;
  const nodes = entries.map(([code, value]) => {
    const item = create("article", "damage-type-item");
    const head = create("div");
    head.append(create("strong", "", DAMAGE_TYPE_LABELS[code] || code.replace(/^DT_/, "")), create("span", "", `${(Number(value) / total * 100).toFixed(1)}%`));
    const track = create("i");
    track.style.setProperty("--damage-width", `${Number(value) / total * 100}%`);
    item.append(head, track);
    return item;
  });
  ui["weapon-build-damage-types"].replaceChildren(...(nodes.length ? nodes : [create("p", "empty-copy", "没有可显示的伤害构成")]));
}

const LIVE_HUD_FORMATS = {
  totalDamage: (v) => formatMetric(v),
  averageHit: (v) => formatMetric(v),
  sustainedDps: (v) => formatMetric(v),
  // 暴击/触发超过 100% 是有意义的数值（暴击升橙/红暴层级、触发多跳），
  // 如实显示实际百分比，不再用 100%+ 截断。
  critChance: (v) => `${(v * 100).toFixed(1)}%`,
  statusChance: (v) => `${(v * 100).toFixed(1)}%`,
  fireRate: (v) => v.toFixed(2),
};

function flashValue(node, next) {
  const previous = node.dataset.liveValue;
  const text = String(next);
  if (previous !== undefined && previous !== text) {
    node.classList.remove("is-flash");
    void node.offsetWidth;
    node.classList.add("is-flash");
  }
  node.dataset.liveValue = text;
  node.textContent = text;
}

function updateLiveHud(result) {
  const sim = result?.simulation || result || {};
  const stats = sim.moddedStats || sim.stats || {};
  const targetDamage = sim.targetDamage || {};
  const read = (camel, snake = camel) => finite(stats[camel]) ?? finite(stats[snake]);
  const values = {
    totalDamage: finite(targetDamage.perShot) ?? read("totalDamage", "total_damage"),
    averageHit: read("averageHit", "average_hit"),
    // Target-aware DPS: faction buffs (Roar) and target defenses only exist in
    // the target model, so prefer targetDamage.dps there.
    sustainedDps: finite(targetDamage.dps) ?? read("sustainedDps", "sustained_dps"),
    critChance: read("critChance", "crit_chance"),
    statusChance: read("statusChance", "status_chance"),
    fireRate: read("fireRate", "fire_rate"),
  };
  ui["live-hud-metrics"]?.querySelectorAll("[data-live]").forEach((node) => {
    const key = node.dataset.live;
    const value = values[key];
    node.hidden = value === null;
    if (value !== null) flashValue(node, (LIVE_HUD_FORMATS[key] || String)(value));
  });
  const pulse = ui["live-hud-pulse"];
  if (pulse) {
    pulse.classList.remove("is-solving");
    void pulse.offsetWidth;
    pulse.classList.add("is-settled");
    window.setTimeout(() => pulse.classList.remove("is-settled"), 700);
  }
}

function markLiveHudSolving() {
  ui["live-hud-pulse"]?.classList.add("is-solving");
}

function renderWeaponStats(stats) {
  stats = stats || {};
  const value = (camel, snake = camel) => stats[camel] ?? stats[snake];
  const melee = ["melee", "zaw"].includes(state.buildWeapon?.weaponType);
  const firstShotBonus = Number(value("firstShotDamageBonus")) || 0;
  const rows = [
    ["面板伤害", value("totalDamage", "total_damage"), (value) => formatMetric(value)],
    ["平均命中", value("averageHit", "average_hit"), (value) => formatMetric(value)],
    // 膛室家族首发加成存在时展示「首发单发」期望（暴击已平均化）。
    ...(firstShotBonus > 0 ? [["首发单发", value("firstShotHit"), (value) => formatMetric(value)]] : []),
    ["暴击几率", value("critChance", "crit_chance"), (value) => `${(value * 100).toFixed(1)}%`],
    ["暴击倍率", value("critMultiplier", "crit_multiplier"), (value) => `${value.toFixed(2)}x`],
    ["触发几率", value("statusChance", "status_chance"), (value) => `${(value * 100).toFixed(1)}%`],
    ...(!melee ? [["多重射击", value("multishot"), (value) => `${value.toFixed(2)}x`]] : []),
    ["攻速 / 射速", value("fireRate", "fire_rate"), (value) => value.toFixed(2)],
    ...(!melee ? [
      ["弹匣", value("magazine"), (value) => value.toFixed(1)],
      // Reload speed -100% or below never finishes a reload (engine: 1e9 s).
      ["装填", value("reloadTime", "reload_time"), (value) => (value >= 1e8 ? "无法完成" : `${value.toFixed(2)}s`)],
    ] : [
      ["初始连击", value("initialCombo", "initial_combo"), (value) => value.toFixed(0)],
      ["连击持续", value("comboDuration", "combo_duration"), (value) => `${value.toFixed(1)}s`],
      ["重击效率", value("heavyAttackEfficiency", "heavy_attack_efficiency"), (value) => `${(value * 100).toFixed(1)}%`],
      ["重击伤害", value("heavyDamage", "heavy_damage"), (value) => formatMetric(value)],
    ]),
  ].filter(([, value]) => finite(value) !== null && Number(value) > 0);
  ui["weapon-build-stat-band"].replaceChildren(...rows.map(([label, value, format]) => {
    const item = create("div");
    item.append(create("span", "", label), create("strong", "", format(Number(value))));
    return item;
  }));
  ui["weapon-build-stat-band"].hidden = !rows.length;
}

function renderWeaponBuildDiagnostics(result) {
  const lines = [
    ...(result.projectileEvents?.events || result.build?.projectileEvents?.events || [])
      .filter((event) => event.kind === "scriptRadial" && event.baseSource === "shieldDamageData")
      .map(() => "触发条件：装备深埋之憾后，感染量子切割器球体被破坏时，按球体吸收弹丸得到的伤害及 MOD 等级倍率引爆。实际吸收伤害尚未恢复，此效果未计入评分。"),
    ...userDiagnostics(result.unsupported).map((item) => `未完整支持：${item}`),
    ...userDiagnostics(result.skipped).map((item) => `计算说明：${item}`),
  ];
  const unique = [...new Set(lines)];
  ui["weapon-build-diagnostic-count"].textContent = String(unique.length);
  ui["weapon-build-diagnostic-list"].replaceChildren(...(unique.length ? unique.map((line) => create("p", "", line)) : [create("p", "", "本次计算没有额外诊断项")]));
}

// 手动配装的构成标注：按已装备卡的词条构成分类——暴击类词条为直伤倾向，
// 触发类词条为触发倾向，两类并存标「双修」（引擎按 KPM 全量求解，实战口径
// 即双修混搭，此标注仅描述配装构成）。
const ARCHETYPE_CRIT_TYPES = new Set(["WEAPON_CRIT_CHANCE", "WEAPON_CRIT_DAMAGE", "WEAPON_DOUBLE_CRIT_CHANCE"]);
const ARCHETYPE_STATUS_TYPES = new Set(["WEAPON_PROC_CHANCE", "WEAPON_PROC_DAMAGE", "WEAPON_PROC_TIME", "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE"]);
function manualBuildArchetype() {
  let crit = 0;
  let status = 0;
  for (const mod of state.manualSlots) {
    if (!mod || mod.__riven) continue;
    const types = new Set((mod.effects || []).map((e) => String(e?.upgradeType || "")));
    if ([...types].some((t) => ARCHETYPE_CRIT_TYPES.has(t))) crit += 1;
    if ([...types].some((t) => ARCHETYPE_STATUS_TYPES.has(t))) status += 1;
  }
  if (crit && status) return "双修";
  if (crit) return "直伤";
  if (status) return "触发";
  return "";
}

function renderWeaponBuild(result) {
  const weapon = state.buildWeapon;
  const build = resultBuildView(result);
  ui["weapon-build-type"].textContent = `${TYPE_LABELS[weapon.weaponType] || weapon.weaponType} BUILD`;
  ui["weapon-build-name"].textContent = weaponName(weapon);
  ui["weapon-build-fire-mode"].textContent = ui["build-fire-mode-select"].selectedOptions[0]?.textContent || `模式 ${Number(result.fireMode) + 1}`;
  // 流派钳制已移除（实战双修口径）：自动模式统一标「双修」，手动模式按
  // 装备构成标注（直伤/触发/双修）。
  const archetype = state.buildInputMode === "manual"
    ? manualBuildArchetype()
    : (result.buildArchetype === "hybrid" || result.buildArchetype ? "双修" : "");
  if (ui["weapon-build-archetype"]) {
    ui["weapon-build-archetype"].hidden = !archetype;
    ui["weapon-build-archetype"].textContent = archetype ? `构成 ${archetype}` : "";
  }
  const innate = result.innateElement;
  const innateText = innate ? `自带${DAMAGE_TYPE_LABELS[innate.damageType] || innate.damageType} ${(Number(innate.percent || innate.value * 100)).toFixed(0)}%` : "无自带元素";
  ui["weapon-build-element-note"].textContent = `${result.elementTarget ? `元素目标：${result.elementTarget.label}（配装包含）` : "未限定元素"} · ${innateText}`;
  ui["weapon-build-slot-summary"].textContent = `${result.slotCount ?? Number(ui["build-slot-count"]?.value || 8)} SLOTS`;
  updateLiveHud(result);
  renderWeaponStats(result.moddedStats);
  // 伤害数值只保留顶部随动 HUD 与面板属性带：原先这里的「单发/爆发/持续」
  // 指标条与 HUD 完全重复，移除以节省纵向空间（用户要求）。
  renderDamageTypes(result);
  renderFireModes({ alternateModes: result.alternateModes }, ui["weapon-build-fire-modes"]);
  if (state.buildInputMode === "auto") {
    fillManualFromResult(result);
    fillSpecialFromResult(result);
    refreshAutoBuildDetail(result);
  } else {
    renderManualResultVisual(result);
  }
  renderWeaponBuildDiagnostics(result);
  updateEnemyStatsPanel(result);
  scheduleEquippedGains();
}

// ── 部件贡献（Shapley）────────────────────────────────────────────────────
// 枚举已装备 MOD 与紫卡的全部组合（后端 /api/part-values），给出每个部件
// 在所有装配顺序下的平均等效倍率、拿掉它/只装它，以及两两配合。
let partValuesRequest = 0;
let partValuesTimer = null;

function partValuesKey(payload) {
  return JSON.stringify({ ...payload, liveChannel: undefined, liveSeq: undefined });
}

function schedulePartValues() {
  if (!ui["part-values"]?.open || state.buildInputMode !== "manual") return;
  window.clearTimeout(partValuesTimer);
  partValuesTimer = window.setTimeout(() => requestPartValues(), 600);
}

async function requestPartValues() {
  let payload;
  try {
    payload = buildPayloadFromForm();
  } catch (error) {
    ui["part-values-status"].textContent = issueLabel(error.message) || "当前配装无法计算";
    return;
  }
  if (!(payload.mods || []).length && !payload.riven) {
    ui["part-values-content"].replaceChildren();
    ui["part-values-status"].textContent = "先装配 MOD 再计算";
    return;
  }
  const key = partValuesKey(payload);
  if (state.partValues?.key === key) return renderPartValues(state.partValues.result);
  const requestId = ++partValuesRequest;
  ui["part-values-run"].disabled = true;
  ui["part-values-status"].textContent = "正在枚举全部组合…";
  try {
    const response = await fetch("/api/part-values", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const body = await response.json();
    if (!response.ok) throw new Error(body?.error?.message || `计算失败（${response.status}）`);
    if (requestId !== partValuesRequest) return;
    state.partValues = { key, result: body };
    renderPartValues(body);
  } catch (error) {
    if (requestId === partValuesRequest) ui["part-values-status"].textContent = issueLabel(error.message) || "计算失败";
  } finally {
    if (requestId === partValuesRequest) ui["part-values-run"].disabled = false;
  }
}

function partValueName(row) {
  if (row.kind === "riven") return "紫卡";
  return row.nameZh || row.nameEn || String(row.key || "").split("/").pop();
}

function signedPercent(value) {
  if (!Number.isFinite(Number(value))) return "--";
  const number = Number(value);
  return `${number >= 0 ? "+" : "−"}${Math.abs(number) >= 100 ? Math.abs(number).toFixed(0) : Math.abs(number).toFixed(1)}%`;
}

function renderPartValues(result) {
  const target = ui["part-values-content"];
  if (!target || !result) return;
  const log = result.scale === "log";
  const rows = [...result.parts].sort((a, b) => b.shapley - a.shapley);
  const total = log ? Math.log(result.fullValue / result.emptyValue) : result.fullValue - result.emptyValue;
  const table = create("div", "part-values-table");
  const head = create("div", "part-values-row is-head");
  head.append(create("span", "", "部件"), create("span", "", log ? "占总提升" : "占总提升"), create("b", "", log ? "等效倍率" : "平均贡献"), create("b", "", "拿掉它"), create("b", "", "只装它"));
  table.append(head);
  for (const row of rows) {
    const line = create("div", "part-values-row");
    const share = total > 0 ? clamp(row.shapley / total, 0, 1) : 0;
    const bar = create("span", "part-values-bar");
    const fill = create("i");
    fill.style.width = `${(share * 100).toFixed(1)}%`;
    bar.append(fill);
    bar.title = `占全装相对裸武器提升的 ${(share * 100).toFixed(1)}%（对数尺度）`;
    line.append(
      create("span", "", `${row.slot !== undefined && row.slot !== null ? `${Number(row.slot) + 1}. ` : ""}${partValueName(row)}`),
      bar,
      create("b", "", log ? `×${Number(row.multiplier).toFixed(2)}` : `${(Number(row.share || 0) * 100).toFixed(1)}%`),
      create("b", "", signedPercent(row.removeLossPercent)),
      create("b", "", row.alonePercent === null || row.alonePercent === undefined ? "--" : signedPercent(row.alonePercent)),
    );
    table.append(line);
  }
  const pairs = create("div", "part-values-pairs");
  const synergy = result.pairs.filter((pair) => pair.interaction > 1e-9).slice(0, 3);
  const dilution = result.pairs.filter((pair) => pair.interaction < -1e-9).slice(0, 3);
  const pairText = (pair) => `${partValueName(result.parts[pair.a])} + ${partValueName(result.parts[pair.b])}`;
  const pairValue = (pair) => (log ? `×${Number(pair.multiplier).toFixed(2)}` : formatMetric(pair.interaction));
  if (synergy.length) {
    pairs.append(create("small", "", "配合最好"));
    for (const pair of synergy) {
      const line = create("p", "is-synergy");
      line.append(document.createTextNode(`${pairText(pair)} `), create("b", "", pairValue(pair)));
      pairs.append(line);
    }
  }
  if (dilution.length) {
    pairs.append(create("small", "", "互相稀释"));
    for (const pair of dilution) {
      const line = create("p", "is-dilution");
      line.append(document.createTextNode(`${pairText(pair)} `), create("b", "", pairValue(pair)));
      pairs.append(line);
    }
  }
  const note = create("p", "part-values-note", log
    ? `等效倍率 = 该部件在所有装配顺序下带来的平均倍数，全部相乘等于全装 / 裸武器（×${formatMetric(result.fullValue / result.emptyValue)}）。配合：两件一起装比各自单独带来的更多（>1）或更少（<1）。赋能、功能槽、架势与灵化保持当前设置。`
    : "裸武器在当前目标上无法击杀，改按击杀数的平均贡献与占比显示。赋能、功能槽、架势与灵化保持当前设置。");
  target.replaceChildren(table, pairs, note);
  ui["part-values-status"].textContent = `${result.evaluations} 种组合 · ${Number(result.seconds).toFixed(1)} 秒`;
}

// /api/build (auto mode) returns optimizer output without statusProcs/dot/
// timeline. Re-run the filled slots through /api/simulate once so the 异常状态
// and 时间线 panels always show real per-status data.
async function refreshAutoBuildDetail(buildResult) {
  const requestId = state.liveRequestId;
  try {
    const payload = buildPayloadFromForm();
    const response = await fetch("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const body = await response.json();
    if (!response.ok || requestId !== state.liveRequestId) return;
    renderManualResultVisual(body);
  } catch {
    renderManualResultVisual(buildResult);
  }
}

// 派系防御类别：Update 36（伤害 2.0 合并）后，生命/护甲/护盾的材质类别并入派系，
// 克制关系按派系生效；后端已按引擎同口径下发 factionModifiers（正=弱点，负=抗性）。
const FACTION_CLASS_LABELS = {
  RK_GRINEER_FACTION: "Grineer", RK_GRINEER_KUVA_FACTION: "Grineer·赤毒",
  RK_CORPUS_FACTION: "Corpus", RK_CORPUS_AMALGAM_FACTION: "Corpus 并合",
  RK_INFESTED_FACTION: "感染体", RK_INFESTED_DEIMOS_FACTION: "感染体·魔胎",
  RK_OROKIN_FACTION: "Orokin", RK_OROKIN_EMPIRE_FACTION: "Orokin 帝国",
  RK_SENTIENT_FACTION: "Sentient", RK_NARMER_FACTION: "合一众",
  RK_MITW_FACTION: "低语者", RK_LASRIA_FACTION: "炽蛇军",
  RK_PROTOINFESTED_FACTION: "Techrot", RK_ZARIMAN_FACTION: "双衍王境",
  RK_NEUTRAL: "派系中立",
};

function enemyDefenseMeta(enemy) {
  const modifiers = enemy?.factionModifiers || {};
  const weak = [];
  const resist = [];
  for (const [dt, value] of Object.entries(modifiers)) {
    if (!DAMAGE_TYPE_LABELS[dt]) continue;
    if (value > 0) weak.push(dt);
    else if (value < 0) resist.push(dt);
  }
  const classLabel = FACTION_CLASS_LABELS[enemy?.factionResistance]
    || (Object.keys(modifiers).length ? String(enemy?.faction || "") : FACTION_CLASS_LABELS.RK_NEUTRAL);
  return { classLabel, weak, resist };
}

function damageTypeChip(dt) {
  const chip = create("span", "dt-chip");
  const icon = ELEMENT_ICONS[dt];
  if (icon) {
    const img = create("img", "dt-chip-icon");
    img.src = icon; img.alt = ""; img.loading = "lazy";
    chip.append(img);
  }
  const label = create("span", "dt-chip-label", DAMAGE_TYPE_LABELS[dt] || dt);
  label.style.color = DAMAGE_TYPE_COLORS[dt] || "";
  chip.append(label);
  return chip;
}

function defenseChipRow(enemy) {
  const { classLabel, weak, resist } = enemyDefenseMeta(enemy);
  const row = create("span", "enemy-defense");
  row.append(create("em", "enemy-defense-class", classLabel));
  if (weak.length) {
    row.append(create("i", "enemy-defense-tag is-weak", "弱"));
    weak.forEach((dt) => row.append(damageTypeChip(dt)));
  }
  if (resist.length) {
    row.append(create("i", "enemy-defense-tag is-resist", "抗"));
    resist.forEach((dt) => row.append(damageTypeChip(dt)));
  }
  if (!weak.length && !resist.length && classLabel === "派系中立") {
    row.append(create("i", "enemy-defense-tag", "无克制"));
  }
  return row;
}

function defenseChipText(enemy) {
  const { classLabel, weak, resist } = enemyDefenseMeta(enemy);
  const parts = [classLabel];
  if (weak.length) parts.push(`弱${weak.map((dt) => DAMAGE_TYPE_LABELS[dt]).join("/")}`);
  if (resist.length) parts.push(`抗${resist.map((dt) => DAMAGE_TYPE_LABELS[dt]).join("/")}`);
  if (!weak.length && !resist.length) parts.push("无克制");
  return parts.join(" · ");
}

function enemyMissingValues(enemy) {
  // 「数值缺失」只隐藏真正缺少等级缩放锚点的目标。没有 HEAD 代理的
  // 载具/炮台/摄像头等是游戏内无独立弱点区，不应误归入数据缺失。
  const missing = [];
  if (enemy?.scalingSupported === false) missing.push("数值缩放缺失");
  return missing;
}

// 敌人特殊机制标注（用户要求）：天生精英/BOSS 的 DoT 限制、超宏、伤害衰减
// 等在选择器里写明。数据来自 enemy 记录的 overguardNote/damageAttenuation/
// statusImmunities 等字段。
function enemySpecialNotes(enemy) {
  const notes = [];
  if (!enemy) return notes;
  // 天生超宏（凶魂家族等）
  if (enemy.overguardNote === "innate-scaled" && Number(enemy.overguard) > 0) {
    notes.push(`天生超宏 ${Number(enemy.overguard)} 基值（按等级曲线缩放）`);
  }
  if (enemy.overguardNote === "missing-value") {
    notes.push("有超宏但数值缺失（解算不含超宏）");
  }
  // 伤害衰减（BOSS 类）
  if (enemy.damageAttenuation || enemy.hasDamageAttenuation) {
    notes.push("伤害衰减（BOSS 机制，高伤递减）");
  }
  if (enemy.dynamicDamageResistance) {
    notes.push("动态抗性（受击后自适应");
  }
  // 状态免疫（wiki status_immunities 类——当前导出未带，未来接入）
  const immunities = enemy.statusImmunities || enemy.nullifiedStatusEffects;
  if (Array.isArray(immunities) && immunities.length) {
    notes.push(`免疫异常：${immunities.map((t) => DAMAGE_TYPE_LABELS[t] || t).join("/")}`);
  }
  return notes;
}

function enemyNotesRow(enemy) {
  const notes = enemySpecialNotes(enemy);
  if (!notes.length) return null;
  const row = create("span", "enemy-special-notes");
  notes.forEach((note) => row.append(create("em", "enemy-special-badge", note)));
  return row;
}

function enemyHeadshotText(enemy) {
  if (enemy?.hasHeadProxy && enemy?.headshotMultiplier) {
    return `爆头×${Number(enemy.headshotMultiplier).toFixed(1)}`;
  }
  return enemy?.headshotStatus === "not-applicable" ? "无独立弱点区" : "弱点倍率缺失";
}

function fillBuildEnemies() {
  const allRows = (state.catalog?.enemies || []).filter((enemy) => enemy.complete !== false && Number(enemy.health) > 0 && Number.isFinite(Number(enemy.baseLevel)));
  if (!ui["build-enemy-list"]) return;
  const missingRows = allRows.filter((enemy) => enemyMissingValues(enemy).length);
  const rows = state.enemyShowMissing ? allRows : allRows.filter((enemy) => !enemyMissingValues(enemy).length);
  const toggle = ui["build-enemy-show-missing"];
  if (toggle) {
    if (ui["build-enemy-missing-count"]) ui["build-enemy-missing-count"].textContent = String(missingRows.length);
    toggle.classList.toggle("is-active", state.enemyShowMissing);
    toggle.setAttribute("aria-pressed", String(state.enemyShowMissing));
    toggle.hidden = !missingRows.length;
    if (!toggle.dataset.bound) {
      toggle.dataset.bound = "1";
      toggle.addEventListener("click", () => {
        state.enemyShowMissing = !state.enemyShowMissing;
        fillBuildEnemies();
      });
    }
  }
  const factionGroup = (faction) => {
    const key = String(faction || "").toLocaleLowerCase();
    if (key.includes("grineer") || key === "ash" || key === "garuda") return "Grineer";
    if (key.includes("corpus")) return "Corpus";
    if (key.includes("infest") || key === "techrot") return "感染体";
    if (key.includes("orokin")) return "Orokin";
    if (key.includes("narmer")) return "合一众";
    if (key.includes("sentient")) return "Sentient";
    if (key.includes("tenno")) return "Tenno";
    if (key === "duviri") return "双衍王境";
    if (key === "mitw") return "低语者";
    if (key === "scaldra") return "炽蛇军";
    return "其他";
  };
  if (!ui["build-enemy-select"].value && rows.length) ui["build-enemy-select"].value = rows[0].path;
  const query = String(ui["build-enemy-search"]?.value || "").trim().toLocaleLowerCase();
  const preferredFactions = ["Grineer", "Corpus", "感染体", "Orokin", "合一众", "Sentient", "Tenno", "双衍王境", "低语者", "炽蛇军", "其他"];
  const presentFactions = new Set(rows.map((enemy) => factionGroup(enemy.faction)));
  const factions = ["all", ...preferredFactions.filter((faction) => presentFactions.has(faction))];
  ui["build-enemy-factions"].replaceChildren(...factions.map((faction) => {
    const button = create("button", faction === state.enemyFaction ? "is-active" : "", faction === "all" ? "全部" : faction);
    button.type = "button";
    button.addEventListener("click", () => { state.enemyFaction = faction; fillBuildEnemies(); });
    return button;
  }));
  const filtered = rows.filter((enemy) => {
    const defenseText = defenseChipText(enemy);
    const missingText = enemyMissingValues(enemy).join(" ");
    const haystack = [enemy.displayName, enemy.nameZh, enemy.nameEn, enemy.nameInternal, enemy.path, enemy.faction, defenseText, enemy.armourType, enemy.shieldType, enemy.hasHeadProxy ? "爆头" : "", missingText].filter(Boolean).join(" ").toLocaleLowerCase();
    return (state.enemyFaction === "all" || factionGroup(enemy.faction) === state.enemyFaction) && (!query || haystack.includes(query));
  });
  ui["build-enemy-count"].textContent = `${filtered.length} / ${rows.length}`;
  ui["build-enemy-list"].replaceChildren(...filtered.slice(0, 300).map((enemy) => {
    const defenseText = defenseChipText(enemy);
    const missing = enemyMissingValues(enemy);
    const headText = enemyHeadshotText(enemy);
    const option = create("button", `enemy-option${ui["build-enemy-select"].value === enemy.path ? " is-selected" : ""}`);
    option.type = "button"; option.setAttribute("role", "option");
    option.title = `${defenseText}；${headText}${enemy.hasHeadProxy ? "" : "，爆头率只能为 0"}${missing.includes("数值缩放缺失") ? "；基准等级无官方记录，等级缩放不可靠" : ""}`;
    const thumb = createEnemyThumbnail(enemy, factionGroup(enemy.faction));
    // 名称清理：只显示 zh/en 展示名，不显示 nameInternal（内部字段残余）。
    const displayName = enemy.nameZh || enemy.nameEn || enemy.displayName || "";
    const info = create("div", "enemy-option-info");
    info.append(
      create("strong", "", displayName),
      create("span", "", `${factionGroup(enemy.faction)} · 基础等级 ${enemy.baseLevel}${headText ? ` · ${headText}` : ""}`),
      defenseChipRow(enemy),
    );
    option.append(thumb, info);
    const notesRow = enemyNotesRow(enemy);
    if (notesRow) option.append(notesRow);
    missing.forEach((label) => option.append(create("em", "enemy-missing-badge", label)));
    option.addEventListener("click", () => {
      ui["build-enemy-select"].value = enemy.path;
      ui["build-damage-model"].value = "target";
      fillBuildEnemies();
      updateCustomDamageControls();
      persistActiveBuildConfig();
      closeEnemyPicker();
      scheduleLiveManualSimulation();
    });
    return option;
  }));
  if (!ui["build-enemy-select"].value && rows.length) ui["build-enemy-select"].value = rows[0].path;
  refreshEnemyTargetSummary();
  // ── 等级/钢铁之路即时刷新（2026-09-24）：靶子摘要与靶信息口径行
  // 随表单立刻更新——不再等下一次解算返回（解算期间 UI 不冻结）。
  ui["build-enemy-level"]?.removeEventListener?.("input", onTargetFormInput);
  ui["build-enemy-level"]?.addEventListener("input", onTargetFormInput);
  ui["build-steel-path"]?.removeEventListener?.("change", onTargetFormInput);
  ui["build-steel-path"]?.addEventListener("change", onTargetFormInput);
  for (const id of ("build-enemy-eximus", "build-enemy-empowered", "build-enemy-archimedea")) {
    ui[id]?.removeEventListener?.("change", onTargetFormInput);
    ui[id]?.addEventListener("change", onTargetFormInput);
  }
  ui["build-enemy-player-count"]?.removeEventListener?.("change", onTargetFormInput);
  ui["build-enemy-player-count"]?.addEventListener("change", onTargetFormInput);
}

function onTargetFormInput() {
  refreshEnemyTargetSummary();
  updateEnemyStatsContext();
}

function refreshEnemyTargetSummary() {
  if (!ui["build-enemy-current"]) return;
  const rows = state.catalog?.enemies || [];
  const enemy = rows.find((entry) => entry.path === ui["build-enemy-select"]?.value);
  if (!enemy) {
    ui["build-enemy-current"].textContent = "--";
    ui["build-enemy-current-meta"].textContent = "点击选择目标";
    return;
  }
  ui["build-enemy-current"].textContent = enemy.displayName || enemy.nameZh || enemy.nameEn || enemy.nameInternal || "--";
  const meta = ui["build-enemy-current-meta"];
  meta.replaceChildren();
  meta.append(create("span", "", `Lv ${ui["build-enemy-level"]?.value || enemy.baseLevel}`), defenseChipRow(enemy));
  const notesRow = enemyNotesRow(enemy);
  if (notesRow) meta.append(notesRow);
  if (enemy.hasHeadProxy && enemy.headshotMultiplier) {
    meta.append(create("span", "enemy-headshot", enemyHeadshotText(enemy)));
  } else {
    const label = enemyHeadshotText(enemy);
    meta.append(create("span", `enemy-headshot${label === "弱点倍率缺失" ? " is-missing" : ""}`, label));
  }
  if (enemy.scalingSupported === false) {
    meta.append(create("span", "enemy-headshot is-missing", "数值缩放缺失"));
  }
}

function openEnemyPicker() {
  if (!ui["enemy-picker"]) return;
  ui["enemy-picker"].hidden = false;
  ui["mod-picker-scrim"].hidden = false;
  document.body.classList.add("is-modal-open");
  if (ui["build-enemy-search"]) ui["build-enemy-search"].value = "";
  fillBuildEnemies();
  ui["build-enemy-search"]?.focus();
}

function closeEnemyPicker() {
  if (!ui["enemy-picker"] || ui["enemy-picker"].hidden) return;
  ui["enemy-picker"].hidden = true;
  if (ui["mod-picker"].hidden && ui["weapon-picker"].hidden && ui["arcane-picker"].hidden) {
    ui["mod-picker-scrim"].hidden = true;
    document.body.classList.remove("is-modal-open");
  }
}

function refreshScenarioLabels() {
  if (ui["build-armour-strip-output"]) ui["build-armour-strip-output"].textContent = `${(Number(ui["build-armour-strip"].value) * 100).toFixed(0)}%`;
  if (ui["build-headshot-output"]) ui["build-headshot-output"].textContent = `${(Number(ui["build-headshot-chance"].value) * 100).toFixed(0)}%`;
  setSliderVisual(ui["build-armour-strip"]);
  setSliderVisual(ui["build-headshot-chance"]);
}

// 自动选择的武器赋能 / 灵化路线填回槽位：之后的手动回放与下次求解都用它
// （下次求解以它为基准路线，所以结果不会倒退）。只改状态，不触发新的求解。
function applyAutoLoadout(body) {
  const auto = body?.autoLoadout;
  if (!auto) return;
  let changed = false;
  if (auto.incarnon && body.incarnonChoices && typeof body.incarnonChoices === "object") {
    const next = { ...body.incarnonChoices };
    if (JSON.stringify(next) !== JSON.stringify(state.incarnonChoices)) {
      state.incarnonChoices = next;
      renderIncarnonChoices();
      changed = true;
    }
  }
  if (auto.arcane) {
    const chosen = (auto.arcane.chosen || []).map((row) => hydrateRankedSelection(row, arcaneRecords(), "weapon"));
    const first = chosen[0] || null;
    const second = weaponArcaneSlotCount() > 1 ? (chosen[1] || null) : state.weaponArcane2;
    if (first?.path !== state.weaponArcane?.path || second?.path !== state.weaponArcane2?.path) {
      state.weaponArcane = first;
      state.weaponArcane2 = second;
      syncArcaneSelections();
      renderArcaneSelections();
      changed = true;
    }
  }
  if (changed) persistActiveBuildConfig();
}

async function submitWeaponBuild(event, live = false) {
  event?.preventDefault();
  let payload;
  try {
    payload = buildPayloadFromForm();
  } catch (error) {
    showBuildMessage(issueLabel(error.message));
    toast(issueLabel(error.message), "error");
    return;
  }
  showBuildMessage("");
  const requestId = ++state.liveRequestId;
  if (!state.buildResult || !live) setWeaponBuildState("loading");
  if (live) markLiveHudSolving();
  try {
    const response = await fetch(state.buildInputMode === "manual" ? "/api/simulate" : "/api/build", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, ...liveTag("build", requestId) }) });
    const body = await response.json();
    if (!response.ok) throw new Error(body?.error?.message || `配装失败（${response.status}）`);
    if (requestId !== state.liveRequestId) return;
    state.buildResult = body;
    applyAutoLoadout(body);
    renderWeaponBuild(body);
    setWeaponBuildState("content");
    schedulePartValues();
  } catch (error) {
    if (requestId === state.liveRequestId) {
      const message = issueLabel(error.message) || "配装失败";
      ui["weapon-build-error-message"].textContent = message;
      if (live) {
        // Keep the last good numbers on screen but surface the failure clearly.
        ui["live-hud-pulse"]?.classList.remove("is-solving");
        toast(`实时解算失败：${message}`, "error");
      } else {
        setWeaponBuildState("error");
      }
    }
  }
}

function diagnosticLines() {
  const lines = [];
  // 靶子与灵化路线说明由后端放在 skipped 开头（“靶子：”“灵化路线：”），原样置顶。
  const notes = userDiagnostics(state.result.skipped);
  const pinned = notes.filter((item) => /^(靶子|攻击路线|灵化路线|开火模式)：/.test(item));
  const route = incarnonRouteText();
  for (const item of pinned) lines.push(item.startsWith("灵化路线：") && route ? `${item}（${route}）` : item);
  for (const item of userDiagnostics(state.result.unsupported)) lines.push(item.startsWith("超快档：") ? `计算说明：${item}` : `未完整支持：${item}`);
  for (const item of notes) if (!pinned.includes(item)) lines.push(`计算说明：${item}`);
  return [...new Set(lines)];
}

function renderDiagnostics() {
  const lines = diagnosticLines();
  ui["diagnostic-count"].textContent = String(lines.length);
  ui["diagnostic-list"].replaceChildren(...(lines.length ? lines.map((line) => create("p", "", line)) : [create("p", "", "本次计算没有额外诊断项")]))
}

function renderResult() {
  renderScore();
  renderContributions();
  renderTiers();
  renderBuild();
  renderDiagnostics();
}

function sample() {
  const weapon = state.catalog.weapons.find((entry) => entry.analysisAvailable !== false && entry.nameEn === "Boltor Prime")
    || state.catalog.weapons.find((entry) => entry.analysisAvailable !== false && entry.weaponType === "rifle")
    || state.catalog.weapons.find((entry) => entry.analysisAvailable !== false);
  selectWeapon(weapon);
  ui["stat-rows"].replaceChildren();
  const preferred = ["D", "0", "1", "Z"];
  preferred.forEach((code, index) => addStat(code, index === 3));
  refreshRanges(false);
  for (const entry of activeStats()) {
    const input = entry.row.querySelector(".stat-value");
    const low = finite(input.min);
    const high = finite(input.max);
    if (low !== null && high !== null) input.value = (low + (high - low) * 0.64).toFixed(3);
  }
  refreshRanges(true);
  showFormMessage("");
  clearResult();
  toast("已载入一组可分析的紫卡示例");
}

function reset() {
  const weapon = state.catalog.weapons.find((entry) => entry.analysisAvailable !== false && entry.nameEn === "Boltor Prime")
    || state.catalog.weapons.find((entry) => entry.analysisAvailable !== false);
  selectWeapon(weapon);
  ui["stat-rows"].replaceChildren();
  ["D", "0", "1"].forEach((code) => addStat(code, false));
  refreshRanges(false);
  showFormMessage("");
  clearResult();
}

function exportResult() {
  if (!state.result) return;
  const blob = new Blob([JSON.stringify({ input: state.lastPayload, result: state.result }, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `riven-${state.weapon?.nameInternal || "analysis"}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

// ── 守护（同伴武器 + 机械守护本体）────────────────────────────────────
// 同伴武器由 AI 开火：只瞄准躯干、不开镜（爆头 / 开镜条件无效），不能装赋能；
// 镀层叠层只来自玩家本人用同类武器的击杀（开关）。守护本体不自动配卡：
// 用户手选 10 个槽位，后端 /api/sentinel/evaluate 给出属性，影响武器伤害的
// 本体 MOD（过热射击 / 星界连结 / 重大连结）随配装请求一起计入。
const SENTINEL_SLOTS = 10;
const SENTINEL_ELEMENTS = [["DT_FIRE", "火焰"], ["DT_FREEZE", "冰冻"], ["DT_ELECTRICITY", "电击"], ["DT_POISON", "毒素"]];

function isCompanionWeapon(weapon = state.buildWeapon) {
  return weapon?.weaponType === "companion";
}

function sentinelCatalog() {
  return state.catalog?.sentinel || { sentinels: [], mods: [], capacity: { reactor: 60 } };
}

function sentinelRecord(path) {
  return sentinelCatalog().sentinels.find((row) => row.path === path) || null;
}

function sentinelModRecord(path) {
  return sentinelCatalog().mods.find((row) => row.path === path) || null;
}

function emptySentinelState() {
  return { path: null, slots: Array.from({ length: SENTINEL_SLOTS }, () => null), polarities: Array.from({ length: SENTINEL_SLOTS }, () => null), options: { firedUp: true, astralBond: false, momentousElement: "" } };
}

// 守护槽极化：polarities[i] 为 null 表示保持本体原生极性；"AP_UNIVERSAL" 表示极化成无极性。
const SENTINEL_FORMA_ORDER = ["AP_UNIVERSAL", "AP_ATTACK", "AP_DEFENSE", "AP_TACTIC", "AP_WARD", "AP_PRECEPT", "AP_ANY"];

function sentinelSlotPolarity(index, record = sentinelRecord(state.sentinel?.path)) {
  const override = state.sentinel?.polarities?.[index];
  const polarity = override ?? record?.slots?.[index] ?? null;
  return polarity === "AP_UNIVERSAL" ? null : polarity;
}

function sentinelPolarityRelation(mod, polarity) {
  if (!mod?.polarity || !polarity) return "";
  return polarityMatches(mod.polarity, polarity) ? "match" : "mismatch";
}

function cycleSentinelPolarity(index) {
  const record = sentinelRecord(state.sentinel?.path);
  if (!record) return;
  const native = record.slots?.[index] || "AP_UNIVERSAL";
  const current = sentinelSlotPolarity(index, record) || "AP_UNIVERSAL";
  const mod = sentinelSlotMod(state.sentinel.slots[index]);
  const next = mod?.polarity && current !== mod.polarity
    ? mod.polarity
    : SENTINEL_FORMA_ORDER[(Math.max(0, SENTINEL_FORMA_ORDER.indexOf(current)) + 1) % SENTINEL_FORMA_ORDER.length];
  state.sentinel.polarities[index] = next === native ? null : next;
  sentinelChanged();
}

function sentinelPolarityChip(index, record, mod) {
  const polarity = sentinelSlotPolarity(index, record);
  const forma = state.sentinel.polarities[index] != null;
  const relation = sentinelPolarityRelation(mod, polarity);
  const chip = create("button", `slot-polarity-chip${relation === "match" ? " is-matched" : ""}${relation === "mismatch" ? " is-mismatch" : ""}${forma ? " is-forma" : ""}`);
  chip.type = "button";
  chip.append(POLARITY_IMAGES[polarity] ? imageNode(POLARITY_IMAGES[polarity], "slot-polarity-icon", "", "lazy") : create("span", "slot-polarity-icon", ""));
  chip.title = `槽位 ${index + 1} 极性 · ${POLARITY_NAMES[polarity] || "无极性"}${forma ? "（已极化）" : ""}${relation === "mismatch" ? " · MOD 不匹配（消耗 ×1.25）" : relation === "match" ? " · 匹配（消耗减半）" : ""} · 点击切换极化`;
  chip.setAttribute("aria-label", chip.title);
  chip.addEventListener("click", (event) => { event.stopPropagation(); cycleSentinelPolarity(index); });
  return chip;
}

function compatibleSentinels(weapon = state.buildWeapon) {
  const family = new Set([weapon?.path, ...(weapon?.ancestry || [])].filter(Boolean));
  return sentinelCatalog().sentinels.filter((row) => !(row.incompatibleWeapons || []).some((path) => family.has(path)));
}

function defaultSentinelFor(weapon) {
  return sentinelCatalog().sentinels.find((row) => row.defaultWeapon === weapon?.path) || null;
}

// 守护 MOD 进 modAssets 索引，卡面复用 createNormalModCard。
function registerSentinelAssets() {
  if (!state.modAssets) return;
  state.modAssets.mods = state.modAssets.mods || {};
  for (const mod of sentinelCatalog().mods) {
    const zh = (mod.levelStatsZh || []).map((line) => [line]);
    state.modAssets.mods[mod.path] = {
      ...(state.modAssets.mods[mod.path] || {}),
      art: mod.art,
      artSource: "official-rgb-alpha",
      nameZh: mod.nameZh,
      nameEn: mod.nameEn,
      rarity: String(mod.rarity || "Common").toUpperCase(),
      polarity: mod.polarity,
      maxRank: mod.maxRank,
      drain: (mod.baseDrain || 0) + (mod.maxRank || 0),
      effectsZh: zh.length ? zh[zh.length - 1] : null,
      effectsZhByRank: zh.length ? zh : null,
      description: zh.length ? zh[zh.length - 1] : [],
    };
  }
}

function sentinelSlotMod(item) {
  const record = item ? sentinelModRecord(item.path) : null;
  return record ? { ...record, rank: item.rank ?? record.maxRank, rarity: String(record.rarity || "Common").toUpperCase() } : null;
}

// ── 显赫武器：关联战甲（战甲配装页已保存的 A/B/C 配置）与能量续航 ──
// 计算一律按无限能量；续航只作指示：能量不回复时能持续多久 / 能放几次，
// 启动不了或续不上后续连击时给持久提示（后端 vendor/wfarsenal/exalted.py）。
function isExaltedWeapon(weapon = state.buildWeapon) {
  return Boolean(weapon?.exalted);
}

function exaltedFrames(weapon = state.buildWeapon) {
  return weapon?.exalted?.frames || [];
}

function exaltedWarframeStore() {
  return { ...readWarframeStore(), ...(state.warframeBuild?.store || {}) };
}

function captureExaltedLink() {
  return isExaltedWeapon() && state.exaltedLink ? { ...state.exaltedLink } : undefined;
}

function restoreExaltedLink(config) {
  const frames = exaltedFrames();
  const saved = config?.exaltedLink;
  const frameId = frames.some((frame) => frame.id === saved?.frameId) ? saved.frameId : frames[0]?.id || null;
  const configName = saved && (saved.configName === "" || /^[ABC]$/.test(saved.configName || "")) ? saved.configName : "A";
  state.exaltedLink = isExaltedWeapon() && frameId ? { frameId, configName } : null;
  state.exaltedResult = null;
}

function exaltedPayload() {
  if (!isExaltedWeapon() || !state.exaltedLink) return undefined;
  const { frameId, configName } = state.exaltedLink;
  const saved = warframeStoredConfig(frameId, configName);
  return { frameId, configName: configName || null, config: saved.config, parentConfig: saved.parentConfig };
}

function exaltedChanged() {
  renderExaltedPanel();
  persistActiveBuildConfig();
  scheduleLiveBuild();
}

const EXALTED_TIER_NOTES = {
  weapon: "按普通武器口径计算；基础伤害取技能满级数值并按技能强度缩放",
  strength: "伤害受技能强度缩放，强度读取自关联战甲",
  cast: "每次施放 = 一次攻击：伤害按技能强度缩放，5 秒内连续施放每次 +20 连击，伤害随连击倍率 1:1 增长（最高 12×）",
  always: "常驻武器，不消耗能量；技能提供的基础伤害仍按关联形态的强度缩放",
};

function renderExaltedPanel() {
  const panel = document.getElementById("build-exalted-panel");
  if (!panel) return;
  const exalted = isExaltedWeapon();
  panel.hidden = !exalted;
  syncHeadshotLock();
  if (!exalted) return;
  if (!state.exaltedLink) restoreExaltedLink(null);
  const frameSelect = document.getElementById("build-exalted-frame");
  frameSelect.replaceChildren(...exaltedFrames().map((frame) => {
    const option = document.createElement("option");
    option.value = frame.id;
    option.textContent = frame.nameZh || frame.nameEn || frame.id;
    return option;
  }));
  frameSelect.value = state.exaltedLink?.frameId || "";
  const linkedFrameId = state.exaltedLink?.frameId;
  const configSelect = document.getElementById("build-exalted-config");
  configSelect.replaceChildren(...["A", "B", "C", ""].map((name) => {
    const saved = name ? warframeStoredConfig(linkedFrameId, name).saved : false;
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name ? `配置 ${name}${saved ? "" : "（未保存）"}` : "满级无 MOD";
    option.title = name && !saved ? "战甲配装页这个配置还没保存过，按满级无 MOD 计算" : "";
    return option;
  }));
  configSelect.value = state.exaltedLink?.configName ?? "A";
  document.getElementById("build-exalted-caption").textContent = EXALTED_TIER_NOTES[state.buildWeapon.exalted.tier] || "";
  renderExaltedReadout(state.exaltedResult);
}

function renderExaltedReadout(exalted) {
  const host = document.getElementById("build-exalted-readout");
  if (!host) return;
  const panel = exalted?.panel;
  if (!panel) {
    host.replaceChildren(create("small", "", "计算一次后显示战甲面板"));
    return;
  }
  const pct = (value) => `${Math.round(Number(value || 0) * 1000) / 10}%`;
  const cells = [["强度", pct(panel.abilityStrength)], ["持续", pct(panel.abilityDuration)], ["效率", pct(panel.abilityEfficiency)], ["范围", pct(panel.abilityRange)]];
  if (Number(panel.castingSpeed)) cells.push(["施法速度", `+${Math.round(Number(panel.castingSpeed) * 100)}%`]);
  cells.push(exalted.energy?.kind === "shield" ? ["护盾", Math.round(panel.shield || 0)] : ["能量", Math.round(panel.energy || 0)]);
  host.replaceChildren(...cells.map(([label, value]) => {
    const cell = create("span", "exalted-stat");
    cell.append(create("small", "", label), create("b", "", String(value)));
    return cell;
  }));
}

// 战甲配置带来的光环与战甲赋能：只有武器计算已支持的才计入，其余仅展示。
function renderExaltedLoadout(exalted) {
  const host = document.getElementById("build-exalted-loadout");
  if (!host) return;
  const loadout = exalted?.loadout;
  const rows = [];
  if (loadout?.aura) rows.push(["光环", loadout.aura]);
  for (const arcane of loadout?.arcanes || []) rows.push(["战甲赋能", arcane]);
  host.hidden = !loadout;
  if (!loadout) return;
  if (!rows.length) {
    host.replaceChildren(create("small", "", "该配置没有光环和战甲赋能"));
    return;
  }
  host.replaceChildren(...rows.map(([label, item]) => {
    const row = create("div", `exalted-loadout-row${item.counted ? " is-counted" : ""}`);
    row.append(create("small", "", label), create("strong", "", item.nameZh || String(item.path || "").split("/").pop()),
      create("em", "", item.counted ? "计入" : "仅展示"));
    row.title = item.counted ? "已计入显赫武器伤害" : "对这把武器没有可计算的效果，只作配装展示";
    return row;
  }));
}

async function openExaltedFrameConfig() {
  const link = state.exaltedLink;
  if (!link?.frameId) return;
  setActiveTool("warframe");
  try {
    await loadWarframeCatalog();
  } catch (_error) {
    return;
  }
  const form = warframeRows("warframeForms").find((row) => warframeId(row) === link.frameId);
  const rootId = form?.parentFrameId || link.frameId;
  const frame = warframeRows("warframes").find((row) => warframeId(row) === rootId);
  if (frame && warframeId(state.warframeBuild.frame) !== rootId) selectWarframeFrame(frame);
  switchWarframeForm(form ? warframeId(form) : "main");
  if (/^[ABC]$/.test(link.configName || "")) switchWarframeConfig(link.configName);
}

function renderExaltedEnergy(exalted) {
  state.exaltedResult = exalted || null;
  renderExaltedReadout(state.exaltedResult);
  renderExaltedLoadout(state.exaltedResult);
  renderArcaneSelections();
  const host = document.getElementById("build-exalted-energy");
  if (!host) return;
  const energy = exalted?.energy;
  host.hidden = !energy;
  if (!energy) return;
  const ability = exalted.ability?.nameZh || exalted.ability?.nameEn || "";
  const frame = exalted.frame || {};
  const source = frame.configured ? `${frame.frameName} · 配置 ${frame.configName || ""}` : `${frame.frameName || "战甲"} · 满级无 MOD`;
  const head = create("div", "result-section-title");
  const title = create("div");
  title.append(create("span", "", "ENERGY"), create("h3", "", "能量续航"));
  head.append(title, create("small", "", `${ability ? `${ability} · ` : ""}${source}`));
  const nodes = [head];
  for (const text of energy.warnings || []) nodes.push(create("p", "exalted-warning", text));
  const list = create("ul", "exalted-energy-lines");
  for (const text of energy.lines || []) list.append(create("li", "", text));
  const cast = exalted.cast;
  if (cast) {
    list.append(create("li", "", `每次施放期望伤害：首次 ${formatMetric(cast.firstCast)} · 满连击 12× ${formatMetric(cast.fullCombo)}`));
    if (cast.secondsPerCast) list.append(create("li", "", `每次施放 ${cast.secondsPerCast.toFixed(2)} 秒（施法速度 ${Math.round((cast.castingSpeed || 1) * 100)}%${(cast.castingSpeed || 1) !== 1 ? "，动画按施法速度缩短" : ""}）`));
    if (cast.per100Energy) list.append(create("li", "", `满连击时每 100 能量伤害 ${formatMetric(cast.per100Energy)}（平均每次 ${formatMetric(cast.averageCost)} 能量）`));
  }
  nodes.push(list, create("p", "scope-hint", "续航按能量不回复估算；伤害与 KPM 一律按无限能量计算。"));
  host.replaceChildren(...nodes);
}

function bindExaltedControls() {
  document.getElementById("build-exalted-open-frame")?.addEventListener("click", () => { openExaltedFrameConfig(); });
  document.getElementById("build-exalted-frame")?.addEventListener("change", (event) => {
    state.exaltedLink = { frameId: event.target.value, configName: state.exaltedLink?.configName ?? "A" };
    exaltedChanged();
  });
  document.getElementById("build-exalted-config")?.addEventListener("change", (event) => {
    state.exaltedLink = { frameId: state.exaltedLink?.frameId || exaltedFrames()[0]?.id, configName: event.target.value };
    exaltedChanged();
  });
}

// 战甲配装页：所选战甲带显赫武器时，在战甲面板下方显示实时摘要（随当前配置的
// 强度 / 效率 / 能量变化），并可跳转到武器配装编辑。
function renderWarframeExaltedCard() {
  const host = document.getElementById("warframe-exalted-card");
  if (!host) return;
  const frameId = warframeId(activeWarframeRecord());
  const weapons = (state.catalog?.weapons || []).filter((weapon) => weapon.exalted?.frames?.some((frame) => frame.id === frameId));
  host.hidden = !weapons.length;
  if (!weapons.length) return;
  const live = new Map((state.warframeBuild?.result?.exalted || []).map((row) => [row.path, row]));
  const head = create("div", "exalted-card-head");
  head.append(create("strong", "", "显赫武器"), create("small", "", `按当前配置 ${state.warframeBuild.activeConfig} 实时计算`));
  const rows = weapons.map((weapon) => {
    const summary = live.get(weapon.path);
    const row = create("div", "exalted-card-row");
    const text = create("div", "exalted-card-text");
    text.append(create("strong", "", weapon.nameZh || weapon.nameEn));
    const facts = [];
    if (summary) {
      if (Number.isFinite(summary.baseDamage)) facts.push(`单次基础伤害 ${formatMetric(summary.baseDamage)}${summary.strengthScaled ? "（已按强度缩放）" : ""}`);
      if (Number.isFinite(summary.bonus)) facts.push(`基础伤害加成 +${Math.round(summary.bonus * 100)}%`);
      if (Number.isFinite(summary.secondsPerCast)) facts.push(`每次施放 ${summary.secondsPerCast.toFixed(2)} 秒`);
      const lines = summary.energy?.lines || [];
      if (lines.length) facts.push(lines[lines.length - 1]);
    }
    text.append(create("small", "", facts.join(" · ") || "计算中…"));
    for (const warning of summary?.energy?.warnings || []) text.append(create("small", "exalted-card-warning", warning));
    if (summary?.headshotIssue) text.append(create("small", "exalted-card-note", summary.headshotIssue));
    const button = create("button", "button button-quiet", "在武器配装中编辑");
    button.type = "button";
    button.addEventListener("click", () => {
      persistWarframeConfig();
      setActiveTool("build");
      selectBuildWeapon(weapon);
      state.exaltedLink = { frameId, configName: state.warframeBuild.activeConfig };
      exaltedChanged();
    });
    row.append(text, button);
    return row;
  });
  host.replaceChildren(head, ...rows);
}

function captureSentinelConfig() {
  if (!isCompanionWeapon()) return undefined;
  const sentinel = state.sentinel || emptySentinelState();
  return {
    path: sentinel.path,
    slots: sentinel.slots.map((item) => item ? { path: item.path, rank: item.rank } : null),
    polarities: [...(sentinel.polarities || [])],
    options: { ...sentinel.options },
    playerStacks: Boolean(state.companionPlayerStacks),
  };
}

function restoreSentinelConfig(config) {
  state.sentinel = emptySentinelState();
  state.companionPlayerStacks = false;
  if (!isCompanionWeapon()) return;
  const saved = config?.sentinel;
  const compatible = compatibleSentinels();
  const path = saved && "path" in saved ? saved.path : defaultSentinelFor(state.buildWeapon)?.path || null;
  state.sentinel.path = compatible.some((row) => row.path === path) ? path : null;
  if (saved) {
    state.sentinel.options = { ...state.sentinel.options, ...(saved.options || {}) };
    state.companionPlayerStacks = saved.playerStacks === true;
    (Array.isArray(saved.polarities) ? saved.polarities : []).slice(0, SENTINEL_SLOTS).forEach((polarity, index) => {
      if (SENTINEL_FORMA_ORDER.includes(polarity)) state.sentinel.polarities[index] = polarity;
    });
    (saved.slots || []).slice(0, SENTINEL_SLOTS).forEach((item, index) => {
      const record = item && sentinelModRecord(item.path);
      if (record && sentinelModFits(record)) state.sentinel.slots[index] = { path: record.path, rank: clamp(Number(item.rank ?? record.maxRank), 0, record.maxRank) };
    });
  } else if (state.sentinel.path) {
    // 新选守护：按游戏默认预装的守则（突击模式等）。
    const defaults = (sentinelRecord(state.sentinel.path)?.defaultPrecepts || []).map(sentinelModRecord).filter(Boolean);
    defaults.slice(0, SENTINEL_SLOTS).forEach((record, index) => { state.sentinel.slots[index] = { path: record.path, rank: record.maxRank }; });
  }
}

function sentinelModFits(record, sentinelPath = state.sentinel?.path) {
  return !record.exclusiveTo || record.exclusiveTo.includes(sentinelPath);
}

function sentinelPayload() {
  if (!isCompanionWeapon() || !state.sentinel?.path) return undefined;
  return {
    path: state.sentinel.path,
    mods: state.sentinel.slots.map((item, slot) => item ? { path: item.path, rank: item.rank, slot } : null).filter(Boolean),
    polarities: [...state.sentinel.polarities],
    options: {
      firedUp: state.sentinel.options.firedUp !== false,
      astralBond: state.sentinel.options.astralBond === true,
      momentousElement: state.sentinel.options.momentousElement || undefined,
    },
  };
}

function sentinelChanged() {
  renderCompanionPanel();
  renderSentinelBench();
  persistActiveBuildConfig();
  scheduleSentinelEvaluate();
  scheduleLiveBuild();
}

// 守护武器（AI 只瞄躯干、不开镜）与无法爆头的显赫武器：爆头率锁定为 0。
function syncHeadshotLock() {
  const companion = isCompanionWeapon();
  const exaltedIssue = state.buildWeapon?.exalted?.headshotIssue || "";
  const locks = {
    "build-headshot-chance": companion ? "守护只瞄准躯干、不会开镜，对守护武器无效" : exaltedIssue ? `${exaltedIssue}，爆头率固定为 0` : "",
    "build-aiming": companion ? "守护只瞄准躯干、不会开镜，对守护武器无效" : "",
  };
  for (const [id, reason] of Object.entries(locks)) {
    const input = document.getElementById(id);
    if (!input) continue;
    const label = input.closest("label");
    input.disabled = Boolean(reason);
    label?.classList.toggle("is-companion-disabled", Boolean(reason));
    if (reason) label?.setAttribute("title", reason);
    else if (label?.title?.includes("爆头率固定") || label?.title?.includes("守护只瞄准")) label.removeAttribute("title");
    if (reason && id === "build-headshot-chance" && Number(input.value) !== 0) {
      input.value = "0";
      refreshScenarioLabels();
    }
  }
}

function renderCompanionPanel() {
  const panel = document.getElementById("build-companion-panel");
  if (!panel) return;
  const companion = isCompanionWeapon();
  panel.hidden = !companion;
  syncHeadshotLock();
  if (!companion) return;
  const select = document.getElementById("build-sentinel-select");
  const rows = compatibleSentinels();
  const options = [["", "不带守护本体（只算武器）"], ...rows.map((row) => [row.path, `${row.nameZh}${row.defaultWeapon === state.buildWeapon?.path ? "（默认武器）" : ""}`])];
  select.replaceChildren(...options.map(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    return option;
  }));
  select.value = state.sentinel?.path || "";
  document.getElementById("build-companion-player-stacks").checked = Boolean(state.companionPlayerStacks);
  const host = document.getElementById("build-sentinel-options");
  const equipped = new Set((state.sentinel?.slots || []).filter(Boolean).map((item) => item.path));
  const nodes = [];
  const toggle = (key, label, title) => {
    const row = create("label", "check-field");
    row.title = title;
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = key === "firedUp" ? state.sentinel.options.firedUp !== false : state.sentinel.options[key] === true;
    input.addEventListener("change", () => { state.sentinel.options[key] = input.checked; sentinelChanged(); });
    row.append(input, create("span", "", label));
    return row;
  };
  const byName = (name) => sentinelCatalog().mods.find((mod) => mod.nameEn === name);
  if (equipped.has(byName("Fired Up")?.path)) nodes.push(toggle("firedUp", "过热射击按满层计算（每次命中 +5% 火焰，满 100%）", "连续命中约 20 次叠满；5 秒没有命中才清零。关闭则不计入。"));
  if (equipped.has(byName("Astral Bond")?.path)) nodes.push(toggle("astralBond", "星界连结生效（指挥官最近 10 秒造成过伤害）", "+60% 伤害、+30% 虚空伤害，持续 10 秒；需要指挥官 / 漂泊者持续输出。"));
  const momentous = byName("Momentous Bond");
  if (equipped.has(momentous?.path)) {
    const row = create("label", "field");
    row.append(create("span", "", "重大连结（击杀 Eximus 后 30 秒，随机元素 +120%）"));
    const select = document.createElement("select");
    for (const [value, label] of [["", "不计入"], ...SENTINEL_ELEMENTS]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      select.append(option);
    }
    select.value = state.sentinel.options.momentousElement || "";
    select.addEventListener("change", () => { state.sentinel.options.momentousElement = select.value; sentinelChanged(); });
    row.append(select);
    nodes.push(row);
  }
  host.replaceChildren(...nodes);
}

function renderSentinelBench() {
  const bench = document.getElementById("sentinel-bench");
  if (!bench) return;
  bench.hidden = !isCompanionWeapon();
  if (bench.hidden) return;
  const record = sentinelRecord(state.sentinel?.path);
  const portrait = document.getElementById("sentinel-portrait");
  portrait.hidden = !record?.portrait;
  if (record?.portrait) portrait.src = record.portrait;
  document.getElementById("sentinel-name").textContent = record ? `${record.nameZh} · ${record.nameEn}` : "未带守护本体";
  const slots = document.getElementById("sentinel-slots");
  if (!record) {
    slots.replaceChildren(create("p", "empty-copy", "左侧「守护」里选择守护本体后，可在这里配置 10 个守护 MOD 槽位。"));
    document.getElementById("sentinel-stats").replaceChildren();
    document.getElementById("sentinel-warning").hidden = true;
    renderSentinelCapacity(null);
    return;
  }
  const nodes = state.sentinel.slots.map((item, index) => {
    const polarity = sentinelSlotPolarity(index, record);
    const slot = create("article", "manual-slot sentinel-slot");
    const mod = sentinelSlotMod(item);
    const chip = sentinelPolarityChip(index, record, mod);
    if (!mod) {
      const empty = create("button", "manual-slot-empty-card");
      empty.type = "button";
      empty.append(create("span", "manual-slot-empty-plus", "＋"), create("small", "", `槽位 ${index + 1}`));
      empty.addEventListener("click", () => openSentinelPicker(index));
      slot.append(empty, chip);
      return slot;
    }
    const card = createNormalModCard(mod, index + 1, { slotPolarity: polarity, compatLabel: mod.exclusiveTo ? `${record.nameZh} 专属` : (mod.kind === "precept" ? "守护守则" : "守护") });
    card.classList.add("manual-slot-preview");
    if (mod.weaponRole) card.classList.add("is-weapon-relevant");
    card.addEventListener("click", () => openSentinelPicker(index));
    const actions = create("div", "manual-slot-actions");
    const down = create("button", "manual-slot-rank", "−");
    down.type = "button";
    down.title = "降低等级";
    down.addEventListener("click", (event) => { event.stopPropagation(); item.rank = Math.max(0, item.rank - 1); sentinelChanged(); });
    const up = create("button", "manual-slot-rank", "+");
    up.type = "button";
    up.title = "提高等级";
    up.addEventListener("click", (event) => { event.stopPropagation(); item.rank = Math.min(mod.maxRank, item.rank + 1); sentinelChanged(); });
    const remove = create("button", "manual-slot-remove", "×");
    remove.type = "button";
    remove.title = "移除";
    remove.addEventListener("click", (event) => { event.stopPropagation(); state.sentinel.slots[index] = null; sentinelChanged(); });
    actions.append(down, create("span", "manual-slot-rank-value", `${item.rank}/${mod.maxRank}`), up, remove);
    slot.append(card, chip, actions);
    return slot;
  });
  slots.replaceChildren(...nodes);
  renderSentinelStats();
}

function renderSentinelCapacity(panel) {
  const bar = document.getElementById("sentinel-capacity-bar");
  const readout = document.getElementById("sentinel-capacity-readout");
  if (!bar || !readout) return;
  const used = panel?.capacity?.used ?? 0;
  const total = panel?.capacity?.total ?? (sentinelCatalog().capacity?.reactor || 60);
  const segs = Math.ceil(total / 5);
  const filled = Math.round(Math.min(used / total, 1) * segs);
  bar.replaceChildren(...Array.from({ length: segs }, (_, i) => create("i", `cap-seg${i < filled ? (used > total ? " is-over" : " is-used") : ""}`)));
  readout.textContent = used > total ? `容量不足 超出 ${used - total}` : `${total - used} / ${total}`;
  readout.title = panel?.formaCount ? `已极化 ${panel.formaCount} 个槽位（点槽位右上角的极性切换）` : "点槽位右上角的极性切换极化";
}

function renderSentinelStats() {
  const host = document.getElementById("sentinel-stats");
  const warning = document.getElementById("sentinel-warning");
  const panel = state.sentinelPanel?.sentinel === state.sentinel?.path ? state.sentinelPanel : null;
  renderSentinelCapacity(panel);
  if (!host) return;
  if (!panel) {
    host.replaceChildren(create("p", "empty-copy", "属性计算中…"));
    return;
  }
  warning.hidden = panel.attackPrecept;
  warning.textContent = panel.attackPrecept ? "" : "没有装备攻击类守则（突击模式 / 精算射击 / 重击者 / 目标感应）：游戏里守护不会开火，武器伤害只作参考。";
  const fmt = (value) => Math.round(value).toLocaleString();
  const row = (label, stat, percent = false) => {
    const node = create("div", "sentinel-stat");
    const changed = Math.abs(stat.modded - stat.base) > 1e-9;
    node.append(create("span", "", label), create("b", changed ? "is-changed" : "", percent ? `${stat.modded >= 0 ? "+" : ""}${(stat.modded * 100).toFixed(0)}%` : fmt(stat.modded)));
    if (!percent && changed) node.append(create("small", "", `基础 ${fmt(stat.base)}`));
    return node;
  };
  const stats = panel.stats;
  const nodes = [row("生命", stats.health), row("护盾", stats.shield), row("护甲", stats.armor)];
  if (stats.shieldRecharge.modded) nodes.push(row("护盾回复", stats.shieldRecharge, true));
  if (stats.shieldDelay.modded) nodes.push(row("回盾延迟", stats.shieldDelay, true));
  const weaponMods = (panel.weaponMods || []).map(sentinelModRecord).filter(Boolean);
  const note = create("p", "sentinel-note", weaponMods.length
    ? `计入武器伤害：${weaponMods.map((mod) => mod.nameZh).join("、")}（开关在左侧「守护」）`
    : "当前本体 MOD 不改变武器伤害。属性为 30 级（基础 ×3.5，wiki 守护数值表）。");
  host.replaceChildren(create("div", "sentinel-stat-grid", ""), note);
  host.firstChild.append(...nodes);
}

let sentinelEvaluateTimer = null;
let sentinelEvaluateSeq = 0;
function scheduleSentinelEvaluate() {
  window.clearTimeout(sentinelEvaluateTimer);
  const payload = sentinelPayload();
  if (!payload) { state.sentinelPanel = null; return; }
  sentinelEvaluateTimer = window.setTimeout(async () => {
    const seq = ++sentinelEvaluateSeq;
    try {
      const response = await fetch("/api/sentinel/evaluate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sentinel: payload }) });
      const body = await response.json();
      if (seq !== sentinelEvaluateSeq) return;
      if (!response.ok) throw new Error(body?.error?.message || "守护属性计算失败");
      state.sentinelPanel = body;
    } catch (error) {
      state.sentinelPanel = null;
      toast(error.message, "error");
    }
    renderSentinelStats();
  }, 160);
}

function openSentinelPicker(slotIndex) {
  if (!ui["mod-picker"] || !state.sentinel?.path) return;
  state.modPickerKind = "sentinel";
  state.sentinelPickerSlot = slotIndex;
  ui["mod-picker"].classList.add("is-special-picker");
  if (ui["mod-picker-title"]) ui["mod-picker-title"].textContent = "选择守护 MOD";
  ui["mod-picker-sub"].textContent = `${sentinelRecord(state.sentinel.path)?.nameZh || "守护"} · 槽位 ${slotIndex + 1}`;
  ui["mod-picker"].hidden = false;
  ui["mod-picker-scrim"].hidden = false;
  document.body.classList.add("is-modal-open");
  if (ui["manual-mod-search"]) ui["manual-mod-search"].value = "";
  renderManualMods();
  ui["manual-mod-search"]?.focus();
}

function sentinelModRecords() {
  const query = String(ui["manual-mod-search"]?.value || "").trim().toLocaleLowerCase();
  const used = new Set(state.sentinel.slots.filter(Boolean).map((item) => item.path));
  const current = state.sentinel.slots[state.sentinelPickerSlot]?.path;
  return sentinelCatalog().mods
    .filter((mod) => sentinelModFits(mod) && (!used.has(mod.path) || mod.path === current))
    .filter((mod) => !query || [mod.nameZh, mod.nameEn, ...(mod.levelStatsZh || []).slice(-1)].join(" ").toLocaleLowerCase().includes(query))
    .sort((a, b) => Number(Boolean(b.weaponRole)) - Number(Boolean(a.weaponRole)) || Number(Boolean(b.exclusiveTo)) - Number(Boolean(a.exclusiveTo)) || String(a.nameZh).localeCompare(String(b.nameZh), "zh"))
    .map((mod) => ({ ...mod, rarity: String(mod.rarity || "Common").toUpperCase() }));
}

function applySentinelMod(mod) {
  const slot = state.sentinelPickerSlot ?? 0;
  state.sentinel.slots = state.sentinel.slots.map((item, index) => index !== slot && item?.path === mod.path ? null : item);
  state.sentinel.slots[slot] = { path: mod.path, rank: mod.maxRank };
  closeModPicker();
  sentinelChanged();
}

function bindCompanionControls() {
  document.getElementById("build-sentinel-select")?.addEventListener("change", (event) => {
    const path = event.target.value || null;
    state.sentinel = emptySentinelState();
    state.sentinel.path = path;
    const defaults = (sentinelRecord(path)?.defaultPrecepts || []).map(sentinelModRecord).filter(Boolean);
    defaults.slice(0, SENTINEL_SLOTS).forEach((record, index) => { state.sentinel.slots[index] = { path: record.path, rank: record.maxRank }; });
    sentinelChanged();
  });
  document.getElementById("build-companion-player-stacks")?.addEventListener("change", (event) => {
    state.companionPlayerStacks = Boolean(event.target.checked);
    persistActiveBuildConfig();
    scheduleLiveBuild();
  });
}

// ── 紫卡收藏夹（跨武器，本机记忆）──────────────────────────────────
// 每条收藏：武器 path + 词条 {code,value,negative} + 极性 + 备注 + 最近一次
// 分析摘要。入口：分析页紫卡右上角星标、配装页紫卡构建器、顶栏「收藏夹」。
const FAVORITES_KEY = "wf-riven-favorites";

function readFavorites() {
  try {
    const value = JSON.parse(window.localStorage.getItem(FAVORITES_KEY) || "[]");
    return Array.isArray(value) ? value.filter((item) => item && typeof item.weaponPath === "string" && Array.isArray(item.stats)) : [];
  } catch {
    return [];
  }
}

function writeFavorites(list) {
  state.favorites = list;
  try { window.localStorage.setItem(FAVORITES_KEY, JSON.stringify(list)); } catch { toast("本机存储不可用，收藏只在本次打开期间有效", "error"); }
  renderFavoritesBadge();
}

function favoriteKey(weaponPath, stats) {
  const parts = [...stats].map((s) => `${s.code}:${s.negative ? "-" : "+"}:${Number(s.value).toFixed(1)}`).sort();
  return `${weaponPath}|${parts.join(",")}`;
}

function findFavorite(weaponPath, stats) {
  const key = favoriteKey(weaponPath, stats);
  return (state.favorites || []).find((item) => favoriteKey(item.weaponPath, item.stats) === key) || null;
}

function catalogWeapon(path) {
  return state.catalog?.weapons?.find((weapon) => weapon.path === path) || null;
}

function favoriteDefinitions(weapon) {
  return state.catalog?.statsByType?.[weapon?.rivenType || weapon?.weaponType] || [];
}

function toggleFavorite(weapon, stats, extra = {}) {
  if (!weapon || stats.length < 2) {
    toast("至少录入 2 条完整词条再收藏");
    return null;
  }
  const list = [...(state.favorites || [])];
  const existing = findFavorite(weapon.path, stats);
  if (existing) {
    writeFavorites(list.filter((item) => item.id !== existing.id));
    toast("已从收藏夹移除");
    return false;
  }
  const now = Date.now();
  list.unshift({
    id: `fav-${now.toString(36)}-${Math.random().toString(36).slice(2, 6)}`,
    weaponPath: weapon.path,
    stats: stats.map((s) => ({ code: s.code, value: Number(Number(s.value).toFixed(3)), negative: Boolean(s.negative) })),
    polarity: extra.polarity || null,
    note: "",
    createdAt: now,
    analysis: extra.analysis || null,
  });
  writeFavorites(list);
  toast("已加入紫卡收藏夹");
  return true;
}

function analysisRivenStats() {
  return activeStats()
    .filter((entry) => entry.definition && entry.value !== null)
    .map((entry) => ({ code: entry.code, value: entry.value, negative: entry.negative }));
}

function analysisSummary() {
  // 只有当前词条就是刚分析过的那组时才附带结果。
  const payload = state.lastPayload;
  if (!state.result || !payload || payload.weapon !== state.weapon?.path) return null;
  const current = favoriteKey(payload.weapon, analysisRivenStats());
  if (current !== favoriteKey(payload.weapon, payload.stats || [])) return null;
  return { gain: finite(state.result.actualGain), kpm: finite(state.result.actual?.objectiveScore), at: Date.now() };
}

function refreshAnalysisFavoriteButton() {
  const button = document.getElementById("analysis-favorite");
  if (!button) return;
  const saved = Boolean(state.weapon && findFavorite(state.weapon.path, analysisRivenStats()));
  button.classList.toggle("is-active", saved);
  button.textContent = saved ? "★" : "☆";
  button.title = saved ? "已收藏（点击取消）" : "收藏这张紫卡";
  button.setAttribute("aria-pressed", String(saved));
}

function rememberAnalysisResult() {
  // 已收藏的紫卡分析完成后，把最新结果写回收藏。
  const summary = analysisSummary();
  const saved = summary && state.weapon && findFavorite(state.weapon.path, analysisRivenStats());
  if (!saved) return;
  writeFavorites(state.favorites.map((item) => item.id === saved.id ? { ...item, analysis: summary } : item));
}

function renderFavoritesBadge() {
  const count = document.getElementById("favorites-count");
  if (count) count.textContent = String((state.favorites || []).length);
  refreshAnalysisFavoriteButton();
  if (document.getElementById("favorites-drawer")?.hidden === false) renderFavorites();
}

function favoriteStatLabel(stat, definitions) {
  const def = definitions.find((d) => d.code === stat.code);
  if (!def) return `${stat.negative ? "−" : "+"}${Number(stat.value).toFixed(1)} ${stat.code}`;
  return `${formatStatNumber(Number(stat.value), def, stat.negative)} ${def.label || stat.code}`;
}

function createFavoriteRivenCard(weapon, stats, polarity) {
  const definitions = favoriteDefinitions(weapon);
  const frames = state.modAssets?.rarityFrames?.RIVEN || {};
  const card = create("article", "mod-slot is-riven-slot favorite-riven-card");
  card.dataset.rarity = "RIVEN";
  const frame = create("div", "game-mod-card riven-mod-card");
  const content = create("div", "mod-content");
  content.append(...rivenContentLayers(frames, rivenFaceArts(stats, definitions), "lazy"));
  const description = create("div", "mod-description");
  description.append(modNameNode(rivenCardName(weapon, stats, definitions)));
  for (const stat of stats) description.append(create("p", `mod-effect-line${stat.negative ? " is-negative" : ""}`, favoriteStatLabel(stat, definitions)));
  content.append(description);
  frame.append(content);
  const compat = create("div", "mod-item-compat");
  compat.append(create("p", "", "裂罅"));
  if (frames.lowerTab) compat.style.setProperty("--lower-tab", `url("${frames.lowerTab}")`);
  frame.append(compat, rankPips(8, 8));
  frame.append(...modFrameLayers(frames, "lazy"));
  card.append(modTiltWrap(frame));
  return card;
}

function loadFavoriteIntoAnalysis(item) {
  const weapon = catalogWeapon(item.weaponPath);
  if (!weapon) return toast("当前目录里没有这把武器");
  if (weapon.analysisAvailable === false) return toast(weapon.analysisIssue || "这把武器暂不支持紫卡分析");
  closeFavorites();
  setActiveTool("analysis");
  selectWeapon(weapon);
  ui["stat-rows"].replaceChildren();
  for (const stat of item.stats) addStat(stat.code, stat.negative);
  refreshRanges(false);
  const rows = activeStats();
  item.stats.forEach((stat, index) => {
    const input = rows[index]?.row.querySelector(".stat-value");
    if (input) input.value = String(stat.value);
  });
  refreshRanges(true);
  updateCardPreview();
  clearResult();
  refreshAnalysisFavoriteButton();
  toast("已载入收藏的紫卡，点「开始分析」重新评估");
}

function loadFavoriteIntoBuild(item) {
  const weapon = catalogWeapon(item.weaponPath);
  if (!weapon) return toast("当前目录里没有这把武器");
  closeFavorites();
  setActiveTool("build");
  if (state.buildWeapon?.path !== weapon.path) selectBuildWeapon(weapon);
  const current = state.manualSlots.findIndex((slot) => slot?.__riven);
  const empty = state.manualSlots.findIndex((slot) => !slot);
  const target = current >= 0 ? current : (empty >= 0 ? empty : state.manualSlots.length - 1);
  if (state.manualLocks[target]) return toast("目标槽位已锁定，先解锁再装入");
  state.manualSlots[target] = {
    __riven: true,
    path: "__riven__",
    nameZh: `${weapon.nameZh || "紫卡"} (自定义)`,
    nameEn: "Custom Riven",
    maxRank: 8,
    rank: 8,
    rivenPolarity: item.polarity || state.manualSlots[target]?.rivenPolarity || randomRegularPolarity(),
    stats: item.stats.map((s) => ({ ...s })),
  };
  if (!ensureCapacityFit().fits) toast("容量不足：即使极化也装不下这张紫卡", "error");
  renderManualSlots();
  persistActiveBuildConfig();
  scheduleLiveManualSimulation();
  toast(`紫卡已装入槽位 ${target + 1}`);
}

function favoriteFilters() {
  return {
    scope: document.querySelector("#favorites-scope .is-active")?.dataset.scope || "all",
    type: document.getElementById("favorites-type")?.value || "",
    query: (document.getElementById("favorites-search")?.value || "").trim().toLowerCase(),
  };
}

function renderFavorites() {
  const list = document.getElementById("favorites-list");
  if (!list) return;
  const { scope, type, query } = favoriteFilters();
  const current = state.activeTool === "build" ? state.buildWeapon : state.weapon;
  const currentButton = document.querySelector('#favorites-scope [data-scope="current"]');
  if (currentButton) currentButton.textContent = current ? `当前武器 · ${weaponName(current)}` : "当前武器";
  const rows = (state.favorites || []).filter((item) => {
    const weapon = catalogWeapon(item.weaponPath);
    if (scope === "current" && item.weaponPath !== current?.path) return false;
    if (type && (weapon?.weaponType || "") !== type) return false;
    if (query) {
      const text = `${weapon?.nameZh || ""} ${weapon?.nameEn || ""} ${item.note || ""}`.toLowerCase();
      if (!text.includes(query)) return false;
    }
    return true;
  });
  const groups = new Map();
  for (const item of rows) {
    if (!groups.has(item.weaponPath)) groups.set(item.weaponPath, []);
    groups.get(item.weaponPath).push(item);
  }
  const nodes = [];
  for (const [path, items] of groups) {
    const weapon = catalogWeapon(path);
    const group = create("section", "favorites-group");
    const head = create("header", "favorites-group-head");
    head.append(create("strong", "", weapon ? weaponName(weapon) : path.split("/").pop()),
      create("small", "", `${TYPE_LABELS[weapon?.weaponType] || weapon?.weaponType || "未知"} · 倾向 ${weapon ? formatDisposition(weapon.disposition) : "--"} · ${items.length} 张`));
    group.append(head);
    const grid = create("div", "favorites-grid");
    for (const item of items) {
      const entry = create("article", "favorite-entry");
      entry.append(weapon ? createFavoriteRivenCard(weapon, item.stats, item.polarity) : create("p", "empty-copy", "武器已不在目录"));
      const side = create("div", "favorite-side");
      const summary = create("p", "favorite-summary");
      if (item.analysis && item.analysis.gain !== null && item.analysis.gain !== undefined) {
        const kpm = item.analysis.kpm !== null && item.analysis.kpm !== undefined ? ` · ${Number(item.analysis.kpm).toFixed(1)} KPM` : "";
        summary.append(create("b", item.analysis.gain < 0 ? "is-negative" : "", formatPercent(item.analysis.gain)),
          create("small", "", ` 实际增益${kpm} · ${new Date(item.analysis.at).toLocaleDateString()}`));
      } else {
        summary.append(create("small", "", "尚未分析（载入分析后会自动记下结果）"));
      }
      const note = document.createElement("input");
      note.className = "favorite-note";
      note.type = "text";
      note.maxLength = 60;
      note.placeholder = "备注（例：价格、来源）";
      note.value = item.note || "";
      note.addEventListener("change", () => {
        writeFavorites(state.favorites.map((other) => other.id === item.id ? { ...other, note: note.value.trim() } : other));
      });
      const actions = create("div", "favorite-actions");
      const analyze = create("button", "button button-quiet", "分析");
      analyze.type = "button";
      analyze.disabled = !weapon || weapon.analysisAvailable === false;
      analyze.addEventListener("click", () => loadFavoriteIntoAnalysis(item));
      const build = create("button", "button button-quiet", "装到配装");
      build.type = "button";
      build.disabled = !weapon;
      build.addEventListener("click", () => loadFavoriteIntoBuild(item));
      const remove = create("button", "button button-quiet favorite-remove", "删除");
      remove.type = "button";
      remove.addEventListener("click", () => {
        if (remove.dataset.armed !== "1") {
          remove.dataset.armed = "1";
          remove.textContent = "确认删除";
          window.setTimeout(() => { remove.dataset.armed = ""; remove.textContent = "删除"; }, 2500);
          return;
        }
        writeFavorites(state.favorites.filter((other) => other.id !== item.id));
      });
      actions.append(analyze, build, remove);
      const lines = create("ul", "favorite-stats");
      const definitions = favoriteDefinitions(weapon);
      for (const stat of item.stats) lines.append(create("li", stat.negative ? "is-negative" : "", favoriteStatLabel(stat, definitions)));
      side.append(lines, summary, note, actions);
      entry.append(side);
      grid.append(entry);
    }
    group.append(grid);
    nodes.push(group);
  }
  const total = (state.favorites || []).length;
  list.replaceChildren(...(nodes.length ? nodes : [create("p", "empty-copy", total
    ? "没有符合筛选条件的收藏"
    : "还没有收藏。分析页紫卡右上角的 ☆，或配装页紫卡构建器里的「☆ 收藏」，都能把紫卡存到这里。")]));
  const stat = document.getElementById("favorites-stat");
  if (stat) stat.textContent = `${rows.length} / ${total} 张 · ${new Set((state.favorites || []).map((item) => item.weaponPath)).size} 把武器`;
}

function openFavorites() {
  const drawer = document.getElementById("favorites-drawer");
  if (!drawer) return;
  const types = document.getElementById("favorites-type");
  if (types && types.options.length <= 1) {
    for (const type of ["rifle", "shotgun", "pistol", "melee", "archgun", "companion"]) {
      const option = document.createElement("option");
      option.value = type;
      option.textContent = TYPE_LABELS[type] || type;
      types.append(option);
    }
  }
  drawer.hidden = false;
  document.getElementById("favorites-scrim").hidden = false;
  document.getElementById("favorites-button")?.setAttribute("aria-expanded", "true");
  renderFavorites();
  document.getElementById("favorites-search")?.focus();
}

function closeFavorites() {
  const drawer = document.getElementById("favorites-drawer");
  if (!drawer || drawer.hidden) return;
  drawer.hidden = true;
  document.getElementById("favorites-scrim").hidden = true;
  document.getElementById("favorites-button")?.setAttribute("aria-expanded", "false");
}

function exportFavorites() {
  const blob = new Blob([JSON.stringify({ kind: "wf-riven-favorites", version: 1, favorites: state.favorites || [] }, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `riven-favorites-${new Date().toISOString().slice(0, 10)}.json`;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function importFavorites(file) {
  file.text().then((text) => {
    const body = JSON.parse(text);
    const incoming = Array.isArray(body) ? body : body?.favorites;
    if (!Array.isArray(incoming)) throw new Error("文件里没有收藏列表");
    const known = new Set((state.favorites || []).map((item) => favoriteKey(item.weaponPath, item.stats)));
    const added = incoming.filter((item) => item && typeof item.weaponPath === "string" && Array.isArray(item.stats)
      && !known.has(favoriteKey(item.weaponPath, item.stats)))
      .map((item) => ({ ...item, id: item.id || `fav-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}` }));
    writeFavorites([...added, ...(state.favorites || [])]);
    toast(`导入 ${added.length} 张紫卡（重复的已跳过）`);
  }).catch((error) => toast(`导入失败：${error.message}`, "error"));
}

function bindFavorites() {
  state.favorites = readFavorites();
  renderFavoritesBadge();
  document.getElementById("favorites-button")?.addEventListener("click", openFavorites);
  document.getElementById("favorites-close")?.addEventListener("click", closeFavorites);
  document.getElementById("favorites-scrim")?.addEventListener("click", closeFavorites);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeFavorites(); });
  for (const button of document.querySelectorAll("#favorites-scope [data-scope]")) {
    button.addEventListener("click", () => {
      document.querySelectorAll("#favorites-scope [data-scope]").forEach((peer) => peer.classList.toggle("is-active", peer === button));
      renderFavorites();
    });
  }
  document.getElementById("favorites-type")?.addEventListener("change", renderFavorites);
  document.getElementById("favorites-search")?.addEventListener("input", renderFavorites);
  document.getElementById("favorites-export")?.addEventListener("click", exportFavorites);
  const importInput = document.getElementById("favorites-import-file");
  document.getElementById("favorites-import")?.addEventListener("click", () => importInput?.click());
  importInput?.addEventListener("change", () => { if (importInput.files?.[0]) importFavorites(importInput.files[0]); importInput.value = ""; });
  document.getElementById("analysis-favorite")?.addEventListener("click", () => {
    toggleFavorite(state.weapon, analysisRivenStats(), { analysis: analysisSummary() });
    refreshAnalysisFavoriteButton();
  });
  // 词条改动后星标跟随（收藏按「武器 + 词条 + 一位小数数值」识别）。
  ui["stat-rows"]?.addEventListener("input", refreshAnalysisFavoriteButton);
  ui["stat-rows"]?.addEventListener("change", refreshAnalysisFavoriteButton);
}

function toast(message, type = "info") {
  // type: info / success / error —— 顶部居中横幅，颜色随深浅主题联动。
  const node = create("div", `toast is-${type}`, message);
  ui["toast-region"].append(node);
  requestAnimationFrame(() => node.classList.add("is-visible"));
  window.setTimeout(() => {
    node.classList.remove("is-visible");
    window.setTimeout(() => node.remove(), 220);
  }, 2600);
}

function bindEvents() {
  for (const button of document.querySelectorAll("[data-tab]")) button.addEventListener("click", () => setActiveTool(button.dataset.tab));
  // 分析页武器输入与配装页一致：只读，点击打开弹窗选择器
  ui.weapon.addEventListener("click", () => openWeaponPicker("analysis"));
  ui.weapon.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openWeaponPicker("analysis");
  });
  ui["add-stat"].addEventListener("click", () => addStat());
  ui["riven-form"].addEventListener("submit", submitAnalysis);
  ui["retry-button"].addEventListener("click", submitAnalysis);
  // 分析页元素选择：改动即重算（偏好复合元素已移除，只留天生元素）。
  ui["analysis-innate-element-select"]?.addEventListener("change", () => {
    setAnalysisElementIcons();
    if (!ui["result-content"].hidden) submitAnalysis();
  });
  ui["analysis-melee-route-select"]?.addEventListener("change", () => {
    if (!ui["result-content"].hidden) submitAnalysis();
  });
  ui["sample-button"].addEventListener("click", sample);
  bindFavorites();
  bindCompanionControls();
  bindExaltedControls();
  ui["reset-button"].addEventListener("click", reset);
  setupComputeSettings();
  ui["theme-toggle"]?.addEventListener("click", () => {
    applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
  });
  applyTheme(document.documentElement.dataset.theme || "dark");
  ui["export-button"].addEventListener("click", exportResult);
  ui["build-mode"].addEventListener("click", (event) => {
    const button = event.target.closest("button[data-mode]");
    if (!button || !state.result) return;
    state.buildMode = button.dataset.mode;
    renderBuild();
  });
  ui["tier-route"]?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-route]");
    if (!button) return;
    state.recRoute = button.dataset.route;
    renderTiers();
  });
  // 结果页备选射击模式：点击后以该模式重新解算（当前模式见卡头）。
  ui["fire-mode-strip"]?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-fire-mode]");
    if (!button || ui["analyze-button"].classList.contains("is-loading")) return;
    state.requestedFireMode = Number(button.dataset.fireMode);
    submitAnalysis();
  });
  ui["build-weapon"].addEventListener("click", openWeaponPicker);
  ui["build-weapon"].addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openWeaponPicker();
  });
  ui["weapon-picker-close"]?.addEventListener("click", closeWeaponPicker);
  ui["weapon-picker-search"]?.addEventListener("input", renderWeaponPicker);
  ui["build-weapon"].addEventListener("input", () => {
    const weapon = resolveBuildWeapon(ui["build-weapon"].value);
    if (weapon) selectBuildWeapon(weapon, false);
    else if (state.buildWeapon && ui["build-weapon"].value !== buildWeaponOptionLabel(state.buildWeapon)) selectBuildWeapon(null, false);
  });
  ui["build-weapon"].addEventListener("change", () => selectBuildWeapon(resolveBuildWeapon(ui["build-weapon"].value), false));
  ui["build-variant-select"].addEventListener("change", () => {
    const weapon = state.catalog.weapons.find((entry) => entry.path === ui["build-variant-select"].value);
    if (weapon) selectBuildWeapon(weapon);
  });
  ui["build-fire-mode-select"].addEventListener("change", () => {
    refreshBuildMetrics();
    scheduleLiveBuild();
  });
  // 解算档位：两处选择器联动，localStorage 持久化。
  for (const id of ["analysis-profile-select", "solve-profile-select"]) {
    document.getElementById(id)?.addEventListener("change", (event) => {
      setSolveProfile(event.target.value);
    });
  }
  setSolveProfile(solveProfile());
  // 「限制」面板：数量范围与赋能开关即时生效并持久化。
  for (const id of ["build-min-fill", "build-max-fill"]) {
    document.getElementById(id)?.addEventListener("input", () => {
      renderScopeLists();
      persistActiveBuildConfig();
    });
  }
  for (const id of ["build-optimize-arcanes", "build-auto-arcane", "build-auto-incarnon"]) {
    document.getElementById(id)?.addEventListener("change", () => {
      if (id === "build-auto-arcane" && ui[id].checked) ui["build-optimize-arcanes"].checked = true;
      if (id === "build-optimize-arcanes" && !ui[id].checked) ui["build-auto-arcane"].checked = false;
      persistActiveBuildConfig();
      scheduleLiveBuild();
    });
  }
  document.getElementById("build-exclude-faction")?.addEventListener("change", (event) => {
    state.excludeFactionMods = Boolean(event.target.checked);
    try { window.localStorage.setItem("wf-exclude-faction-mods", state.excludeFactionMods ? "1" : "0"); } catch { /* 本次会话生效 */ }
    scheduleLiveBuild();
  });
  ui["build-element-select"]?.addEventListener("change", () => {
    setElementControlIcon(ui["build-element-select"], ui["build-element-icon"]);
  });
  ui["build-innate-element-select"]?.addEventListener("change", () => {
    setElementControlIcon(ui["build-innate-element-select"], ui["build-innate-element-icon"]);
    persistActiveBuildConfig();
    scheduleLiveBuild();
  });
  ui["build-innate-element-value"]?.addEventListener("input", () => {
    const value = clamp(Number(ui["build-innate-element-value"].value || 60), 25, 60);
    ui["build-innate-element-output"].textContent = `${value}%`;
    setSliderVisual(ui["build-innate-element-value"]);
    persistActiveBuildConfig();
    scheduleLiveBuild();
  });
  // ── 灵化循环口径开关（2026-09-24）：常驻灵化（默认）vs 真实循环。
  ui["build-incarnon-cycle"]?.addEventListener("change", () => {
    const note = ui["build-incarnon-cycle-note"];
    if (note) note.textContent = ui["build-incarnon-cycle"].checked ? "真实循环（弱点充能 / 实际弹池）" : "常驻灵化（默认）";
    persistActiveBuildConfig();
    scheduleLiveBuild();
  });
  ui["build-slot-count"].addEventListener("input", () => {
    ui["build-slot-output"].textContent = ui["build-slot-count"].value;
    setSliderVisual(ui["build-slot-count"]);
    scheduleLiveBuild();
  });
  ui["build-config-tabs"]?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-config]");
    if (button) switchBuildConfig(button.dataset.config);
  });
  ui["build-config-copy"]?.addEventListener("click", copyBuildConfig);
  ui["build-config-compare"]?.addEventListener("click", compareBuildConfigs);
  ui["build-config-export-json"]?.addEventListener("click", exportBuildConfig);
  ui["build-config-export-rabbit"]?.addEventListener("click", () => openRabbitDialog("export", "weapon"));
  ui["build-config-import-json"]?.addEventListener("click", () => ui["build-config-import-file"]?.click());
  ui["build-config-import-rabbit"]?.addEventListener("click", () => openRabbitDialog("import", "weapon"));
  ui["build-config-import-file"]?.addEventListener("change", () => importBuildConfig(ui["build-config-import-file"].files?.[0]));
  ui["rabbit-export-form"]?.addEventListener("submit", generateRabbitCommand);
  ui["rabbit-copy"]?.addEventListener("click", copyRabbitCommand);
  ui["rabbit-import-apply"]?.addEventListener("click", importRabbitConfig);
  ui["rabbit-dialog-close"]?.addEventListener("click", closeRabbitDialog);
  ui["rabbit-dialog-scrim"]?.addEventListener("click", closeRabbitDialog);
  for (const button of document.querySelectorAll("[data-build-mode]")) button.addEventListener("click", () => {
    state.buildInputMode = button.dataset.buildMode;
    setBuildModeUI(state.buildInputMode);
    closeModPicker();
    renderManualSlots();
    renderSpecialSlots();
    renderArcaneSelections();
    scheduleLiveBuild();
  });
  ui["manual-mod-search"].addEventListener("input", renderManualMods);
  ui["manual-level-toggle"].addEventListener("change", () => { renderManualSlots(); scheduleLiveManualSimulation(); });
  ui["manual-clear"].addEventListener("click", () => { state.manualSlots = Array.from({ length: 8 }, () => null); renderManualSlots(); persistActiveBuildConfig(); scheduleLiveManualSimulation(); });
  ui["build-reset-all"]?.addEventListener("click", () => {
    if (!window.confirm("确定清除所有武器的已保存配置（A/B/C）与本机缓存吗？此操作不可撤销。")) return;
    try { localStorage.removeItem(BUILD_CONFIG_STORAGE_KEY); } catch (_error) { /* offline/private mode */ }
    state.buildStore = {};
    state.buildConfigs = { A: null, B: null, C: null };
    state.activeConfig = "A";
    state.formaSlots = {};
    refreshFormaCount();
    state.manualSlots = Array.from({ length: 8 }, () => null);
    resetSpecialSelections();
    state.incarnonChoices = {};
    renderManualSlots();
    renderSpecialSlots();
    renderArcaneSelections();
    renderIncarnonChoices();
    updateConfigTabs();
    if (ui["build-config-status"]) ui["build-config-status"].textContent = "已清除全部本机配置";
    toast("已清空全部已保存配置");
  });
  ui["fill-optimal-button"]?.addEventListener("click", async () => {
    const assemblyWeapon = String(state.buildWeapon?.nameEn || "").trim() === "Kitgun" || isZawBase(state.buildWeapon);
    const usable = assemblyWeapon ? assemblyWeaponReady() : (state.buildWeapon?.available && state.buildWeapon.buildAvailable !== false);
    if (!usable) return toast(assemblyWeapon ? "请先完成部件装配" : "该武器暂不可求解");
    const button = ui["fill-optimal-button"];
    button.disabled = true;
    const originalLabel = button.innerHTML;
    button.textContent = "求解中…";
    const previousMode = state.buildInputMode;
    try {
      const payload = { ...buildPayloadFromForm(), mode: "auto", mods: [] };
      const response = await fetch("/api/build", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const body = await response.json();
      if (!response.ok) throw new Error(body?.error?.message || "求解失败");
      applyAutoLoadout(body);
      fillManualFromResult(body);
      persistActiveBuildConfig();
      scheduleLiveManualSimulation();
      toast(state.formaCount ? `已回填最优配装，最少需要极化 ${state.formaCount} 次` : "已回填最优配装，无需极化");
    } catch (error) {
      toast(issueLabel(error.message) || "求解失败", "error");
    } finally {
      button.disabled = false;
      button.innerHTML = originalLabel;
      if (state.buildInputMode !== previousMode) setBuildModeUI(previousMode);
    }
  });
  ui["part-values-run"]?.addEventListener("click", () => { state.partValues = null; requestPartValues(); });
  ui["part-values"]?.addEventListener("toggle", () => { if (ui["part-values"].open) requestPartValues(); });
  ui["forma-optimize"]?.addEventListener("click", () => {
    if (!state.manualSlots.some(Boolean)) return toast("还没有装配 MOD");
    const before = JSON.stringify([state.manualSlots.map((mod) => mod?.path || (mod?.__riven ? "riven" : null)), state.formaSlots]);
    const plan = applyMinimalForma();
    renderManualSlots();
    persistActiveBuildConfig();
    if (JSON.stringify([state.manualSlots.map((mod) => mod?.path || (mod?.__riven ? "riven" : null)), state.formaSlots]) !== before) scheduleLiveManualSimulation();
    if (!plan.fits) return toast("即使全部极化也超出容量，请降低等级或移除 MOD", "error");
    toast(plan.formas ? `已按最少极化重排：极化 ${plan.formas} 次${plan.moves ? `，调换 ${plan.moves} 张 MOD 的位置` : ""}` : "当前 MOD 不需要极化");
  });
  // 战斗演算「重演」按钮：清空 liveTimer 立即重跑一次 simulate（敌人/等级/
  // 强化/触发口径改动后 KPM 立刻刷新，不等防抖）。
  document.getElementById("combat-replay-button")?.addEventListener("click", () => {
    window.clearTimeout(state.liveTimer);
    state.liveTimer = null;
    const button = document.getElementById("combat-replay-button");
    if (button) {
      button.disabled = true;
      window.setTimeout(() => { button.disabled = false; }, 800);
    }
    submitWeaponBuild(null, true);
  });
  // 触发口径切换（emergent/assumed_max）：改动即重演。
  document.getElementById("trigger-policy-select")?.addEventListener("change", () => {
    window.clearTimeout(state.liveTimer);
    state.liveTimer = null;
    submitWeaponBuild(null, true);
  });
  ui["mod-picker-close"]?.addEventListener("click", closeModPicker);
  ui["mod-picker-scrim"]?.addEventListener("click", closeModPicker);
  ui["mod-picker-view"]?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-view]");
    if (!button) return;
    state.modPickerView = button.dataset.view;
    ui["mod-picker-view"].querySelectorAll("button").forEach((peer) => {
      const active = peer.dataset.view === state.modPickerView;
      peer.classList.toggle("is-active", active);
      peer.setAttribute("aria-pressed", String(active));
    });
    renderManualMods();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { closeModPicker(); closeWeaponPicker(); closeArcanePicker(); closeEnemyPicker(); closeWarframePicker(); closeRabbitDialog(); }
  });
  window.addEventListener("hashchange", () => {
    const tool = location.hash.replace("#", "");
    if (["analysis", "build", "warframe"].includes(tool)) setActiveTool(tool);
  });
  ui["build-enemy-open"]?.addEventListener("click", openEnemyPicker);
  ui["enemy-picker-close"]?.addEventListener("click", closeEnemyPicker);
  // 战斗场景 / 外部加成已移出左侧表单，改由右侧面板容器自行委托持久化与实时解算。
  ui["build-setup-folds"]?.addEventListener("input", () => { updateCustomDamageControls(); refreshEnemyTargetSummary(); persistActiveBuildConfig(); scheduleLiveManualSimulation(); });
  ui["build-setup-folds"]?.addEventListener("change", () => { persistActiveBuildConfig(); scheduleLiveManualSimulation(); });
  ui["build-armour-strip"].addEventListener("input", () => { refreshScenarioLabels(); scheduleLiveManualSimulation(); });
  ui["build-aiming"]?.addEventListener("change", () => { persistActiveBuildConfig(); scheduleLiveManualSimulation(); });
  ui["build-headshot-chance"].addEventListener("input", () => { refreshScenarioLabels(); scheduleLiveManualSimulation(); });
  ui["build-damage-model"]?.addEventListener("change", () => {
    updateCustomDamageControls();
    if (ui["build-damage-model"].value === "custom" && !customDamageSupported()) showBuildMessage("当前版本不支持自定义防御");
    else showBuildMessage("");
  });
  ui["build-enemy-search"]?.addEventListener("input", fillBuildEnemies);
  ui["build-enemy-empowered"]?.addEventListener("change", syncEmpoweredPlayerCount);
  ui["arcane-picker-search"]?.addEventListener("input", renderArcanePicker);
  ui["arcane-picker-close"]?.addEventListener("click", closeArcanePicker);
  bindWarframeEvents();
  ui["weapon-build-form"]?.addEventListener("input", () => { updateCustomDamageControls(); persistActiveBuildConfig(); scheduleLiveManualSimulation(); });
  ui["weapon-build-form"]?.addEventListener("change", () => { refreshProjectileStrategyControls(); persistActiveBuildConfig(); scheduleLiveManualSimulation(); });
  ui["weapon-build-form"].addEventListener("submit", submitWeaponBuild);
  if (matchMedia("(pointer: fine)").matches) {
    ui["riven-stage"].addEventListener("pointermove", (event) => {
      const bounds = ui["riven-stage"].getBoundingClientRect();
      const x = (event.clientX - bounds.left) / bounds.width - 0.5;
      const y = (event.clientY - bounds.top) / bounds.height - 0.5;
      ui["riven-card"].style.transform = `rotateX(${(-y * 5).toFixed(2)}deg) rotateY(${(x * 7).toFixed(2)}deg) translateY(-2px)`;
      ui["riven-card"].style.setProperty("--par-x", (x * 2).toFixed(3));
      ui["riven-card"].style.setProperty("--par-y", (y * 2).toFixed(3));
    });
    ui["riven-stage"].addEventListener("pointerleave", () => {
      ui["riven-card"].style.transform = "";
      ui["riven-card"].style.removeProperty("--par-x");
      ui["riven-card"].style.removeProperty("--par-y");
    });
  }
}

async function bootstrap() {
  try {
    state.buildStore = readBuildStore();
    const [catalogResponse, assetsResponse] = await Promise.all([fetch("/api/catalog?v=20260831h"), fetch("/assets/mods/index.json?v=20260831h")]);
    if (!catalogResponse.ok) throw new Error("本地目录加载失败");
    state.catalog = await catalogResponse.json();
    state.modAssets = assetsResponse.ok ? await assetsResponse.json() : null;
    registerSentinelAssets();
    fillWeapons();
    fillBuildWeapons();
    fillBuildEnemies();
    updateCustomDamageControls();
    syncEmpoweredPlayerCount();
    const elementOptions = state.catalog.buildOptions?.elementTargets || [];
    ui["build-element-select"].append(...elementOptions.map((element) => {
      const option = document.createElement("option");
      option.value = element.id;
      option.textContent = element.label;
      option.dataset.damageType = element.damageType || "";
      return option;
    }));
    setElementControlIcon(ui["build-element-select"], ui["build-element-icon"]);
    ui["weapon-count"].textContent = String(state.catalog.counts.weapons);
    ui["coverage-count"].textContent = String(state.catalog.counts.analysisAvailable ?? state.catalog.counts.available);
    const pickerUnavailable = (state.catalog.counts.buildPickerWeapons ?? state.catalog.counts.weapons) - (state.catalog.counts.buildPickerAvailable ?? state.catalog.counts.buildAvailable);
    ui["build-weapon-caption"].textContent = `${state.catalog.counts.buildPickerAvailable ?? state.catalog.counts.buildAvailable} 把可配装 · ${pickerUnavailable} 把已注明不可用`;
    ui["build-label"].textContent = state.catalog.buildLabel;
    ui["health-label"].textContent = "本地引擎已连接";
    ui["health-dot"].classList.add("is-live");
    bindEvents();
    setBuildModeUI(state.buildInputMode);
    renderExternalBuffs();
    reset();
    const buildWeapon = state.catalog.weapons.find((entry) => entry.buildAvailable && entry.path === state.buildStore.__lastSelection?.weapon)
      || state.catalog.weapons.find((entry) => entry.buildAvailable && entry.nameEn === "Boltor Prime")
      || state.catalog.weapons.find((entry) => entry.buildAvailable);
    selectBuildWeapon(buildWeapon);
    refreshScenarioLabels();
    setSliderVisual(ui["build-slot-count"]);
    ui["app-shell"].hidden = false;
    requestAnimationFrame(() => ui["app-shell"].classList.add("is-ready"));
    ui["boot-screen"].classList.add("is-leaving");
    window.setTimeout(() => { ui["boot-screen"].hidden = true; }, 280);
    if (!state.modAssets) toast("MOD 素材索引加载失败，配装仍可计算");
    const hashTool = location.hash.replace("#", "");
    if (["build", "analysis", "warframe"].includes(hashTool)) setActiveTool(hashTool);
  } catch (error) {
    ui["boot-screen"].querySelector("p").textContent = error.message || "本地数据加载失败";
    ui["boot-screen"].classList.add("has-error");
  }
}

bootstrap();
