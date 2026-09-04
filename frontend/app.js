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
  frameArcanes: [null, null],
  incarnonChoices: {},
  manualModCategory: "all",
  enemyFaction: "all",
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
    configs: { A: null, B: null, C: null },
    store: {},
    result: null,
  },
};

const ui = Object.fromEntries([
  "app-shell", "boot-screen", "page-title",
  "health-dot", "health-label", "build-label", "weapon-count", "coverage-count",
  "footer-schema", "sample-button", "reset-button", "export-button", "riven-form",
  "weapon", "weapon-options", "build-weapon-options", "weapon-caption", "disposition-value", "disposition-dots",
  "weapon-issue", "weapon-issue-text", "stat-rows", "stat-row-template", "add-stat",
  "form-message", "analyze-button", "riven-stage", "riven-card", "card-name",
  "card-polarity", "card-stats", "card-mr", "card-rerolls",
  "result-badge", "result-idle", "result-loading", "result-error", "result-content",
  "loading-copy", "error-message", "retry-button", "score-orbit", "orbit-value",
  "score-value", "grade-value", "weapon-result-name", "actual-gain", "optimal-gain",
  "roll-quality", "result-disposition", "contribution-list", "tier-list",
  "tier-filters", "tier-route", "tier-route-note",
  "recommended-negative", "fatal-negative", "fatal-box", "build-mode", "build-slot",
  "build-weapon-name", "build-fire-mode", "build-metric", "damage-metrics",
  "fire-mode-strip", "fire-mode-strip-note", "mod-grid", "analysis-stance", "build-forma", "diagnostics", "diagnostic-count", "diagnostic-list",
  "analysis-tool", "build-tool", "warframe-tool", "weapon-build-form", "build-weapon",
  "build-weapon-caption", "build-disposition", "build-disposition-dots",
  "build-variant-select", "build-variant-caption",
  "build-fire-mode-select", "build-metric-select", "build-element-select", "build-element-icon",
  "build-innate-element-field", "build-innate-element-select", "build-innate-element-icon",
  "build-innate-element-value-field", "build-innate-element-value", "build-innate-element-output",
  "build-incarnon-panel", "build-incarnon-tiers", "build-incarnon-note",
  "build-slot-count", "build-slot-output", "build-weapon-issue",
  "build-weapon-issue-text", "build-form-message",
  "build-enemy-select", "build-enemy-search", "build-enemy-factions", "build-enemy-list", "build-enemy-count", "build-enemy-level", "build-steel-path", "build-armour-strip", "build-armour-strip-output",
  "build-enemy-show-missing", "build-enemy-missing-count",
  "build-enemy-eximus", "build-enemy-empowered", "build-enemy-player-count", "build-enemy-archimedea",
  "build-enemy-stats", "build-enemy-stats-context",
  "build-setup-folds", "build-enemy-open", "build-enemy-current", "build-enemy-current-meta", "enemy-picker", "enemy-picker-close",
  "build-headshot-chance", "build-headshot-output", "build-distance", "build-combo-tier", "build-heavy-attack", "build-damage-model",
  "build-config-tabs", "build-config-status", "build-config-copy", "build-config-compare", "build-config-import", "build-config-export", "build-config-import-json", "build-config-import-rabbit", "build-config-export-json", "build-config-export-rabbit", "build-config-import-file", "build-config-compare-output",
  "custom-defense-fields", "build-custom-health", "build-custom-armor", "build-custom-shield", "build-custom-health-type", "build-custom-armor-type", "build-custom-shield-type", "custom-defense-note",
  "build-arcane-list", "special-loadout", "special-mod-slots",
  "arcane-picker", "arcane-picker-close", "arcane-picker-sub", "arcane-picker-search", "arcane-picker-list",
  "manual-slots", "manual-mod-search", "manual-mod-categories", "manual-mod-list", "manual-level-toggle", "manual-clear", "manual-build-summary",
  "mod-picker", "mod-picker-scrim", "mod-picker-close", "mod-picker-title", "mod-picker-sub", "mod-picker-view",
  "fill-optimal-button",
  "capacity-bar", "capacity-readout", "forma-count", "forma-increase", "forma-decrease", "forma-needed", "build-reset-all", "kitgun-assembly-title", "theme-toggle",
  "weapon-picker", "weapon-picker-close", "weapon-picker-sub", "weapon-picker-search", "weapon-picker-categories", "weapon-picker-list",
  "live-hud", "live-hud-pulse", "live-hud-metrics", "build-bench", "build-detail",
  "weapon-build-idle", "weapon-build-loading",
  "weapon-build-error", "weapon-build-error-message", "weapon-build-content",
  "weapon-build-type", "weapon-build-name", "weapon-build-fire-mode", "weapon-build-archetype",
  "weapon-build-metric", "weapon-build-stat-band", "weapon-build-damage-metrics",
  "weapon-build-element-note", "weapon-build-damage-types", "weapon-build-fire-modes",
  "weapon-build-slot-summary", "weapon-build-build-label",
  "manual-results", "manual-result-grid", "probability-content", "timeline-content",
  "weapon-build-diagnostic-count", "weapon-build-diagnostic-list", "toast-region",
  "warframe-catalog-status", "warframe-frame-select", "warframe-frame-open", "warframe-frame-select-visual", "warframe-frame-select-name", "warframe-frame-select-description", "warframe-frame-caption", "warframe-portrait", "warframe-profile-name", "warframe-profile-description", "warframe-passive",
  "warframe-apply-conditionals", "warframe-helminth-slot", "warframe-helminth-slot-open", "warframe-helminth-slot-visual", "warframe-helminth-slot-name", "warframe-helminth-slot-description", "warframe-helminth-ability", "warframe-helminth-ability-open", "warframe-helminth-ability-visual", "warframe-helminth-ability-name", "warframe-helminth-ability-source", "warframe-helminth-description", "warframe-invigoration-open", "warframe-invigoration-name", "warframe-invigoration-description",
  "warframe-config-tabs", "warframe-config-status", "warframe-config-copy", "warframe-config-import", "warframe-config-export", "warframe-config-import-json", "warframe-config-import-rabbit", "warframe-config-export-json", "warframe-config-export-rabbit", "warframe-config-import-file", "warframe-clear", "warframe-message", "warframe-result-name", "warframe-capacity-readout", "warframe-capacity-bar", "warframe-forma-readout", "warframe-loading", "warframe-build-content",
  "warframe-special-slots", "warframe-normal-slots", "warframe-arcane-slots", "warframe-shard-slots", "warframe-effect-status", "warframe-panel-grid", "warframe-active-effects", "warframe-ability-grid",
  "warframe-diagnostics", "warframe-diagnostic-count", "warframe-diagnostic-list", "warframe-picker", "warframe-picker-title", "warframe-picker-sub", "warframe-picker-search", "warframe-picker-close", "warframe-picker-categories", "warframe-picker-list",
  "rabbit-dialog-scrim", "rabbit-dialog", "rabbit-dialog-title", "rabbit-dialog-close", "rabbit-export-form", "rabbit-import-panel", "rabbit-target", "rabbit-archetype", "rabbit-build-title", "rabbit-summary", "rabbit-usage", "rabbit-cautions", "rabbit-export-status", "rabbit-generate", "rabbit-code-result", "rabbit-code-count", "rabbit-code", "rabbit-copy", "rabbit-import-code", "rabbit-import-status", "rabbit-import-apply",
].map((id) => [id, document.getElementById(id)]));

const TYPE_LABELS = {
  rifle: "步枪", shotgun: "霰弹枪", pistol: "手枪", kitgun: "组合枪",
  melee: "近战", zaw: "组合近战", archgun: "Archwing 枪械",
};

const METRIC_LABELS = {
  shotDamage: "单发伤害", burstDps: "爆发 DPS", sustainedDps: "持续 DPS",
  attackDps: "攻击 DPS", heavyDamage: "重击伤害", heavyAttackDps: "重击 DPS",
  statusSustainedDps: "持续 DPS（触发+直伤）", targetSustainedDps: "目标持续 DPS",
};

const METRIC_KEYS = ["shotDamage", "burstDps", "sustainedDps", "attackDps", "heavyDamage", "heavyAttackDps"];
const DAMAGE_TYPE_LABELS = {
  DT_IMPACT: "冲击", DT_PUNCTURE: "穿刺", DT_SLASH: "切割",
  DT_FIRE: "火焰", DT_FREEZE: "冰冻", DT_ELECTRICITY: "电击", DT_POISON: "毒素",
  DT_EXPLOSION: "爆炸", DT_RADIATION: "辐射", DT_GAS: "毒气",
  DT_MAGNETIC: "磁力", DT_VIRAL: "病毒", DT_CORROSIVE: "腐蚀",
  DT_RADIANT: "虚空", DT_FINISHER: "处决", DT_TRUE: "真实",
};
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
const RIVEN_SUFFIXES = ["Acri-visitis", "Crita-hexalis", "Sati-cronitox", "Visi-ignitis", "Hexa-critatio"];

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
    configId: state.activeConfig,
    configSchema: BUILD_CONFIG_SCHEMA,
    mods,
    formaSlots: Object.keys(state.formaSlots).length ? { ...state.formaSlots } : undefined,
    // Special-slot Forma is exported explicitly as well as in formaSlots so
    // consumers do not have to infer stance/Exilus from ordinary-slot indexes.
    specialSlotPolarities: Object.keys(specialSlotPolaritiesPayload()).length ? specialSlotPolaritiesPayload() : undefined,
    riven: rivenMod ? { slot: rivenSlot, stats: rivenMod.stats.map((s) => ({ code: s.code, value: Number(s.value || 0), negative: Boolean(s.negative) })) } : null,
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
    frameArcanes: state.frameArcanes.filter(Boolean).map(compactRankedSelection),
    externalBuffs: state.externalBuffs.map((buff) => ({ ...buff })),
    incarnonChoices: { ...state.incarnonChoices },
  };
}

function persistActiveBuildConfig() {
  if (!state.buildWeapon) return;
  state.buildConfigs[state.activeConfig] = captureBuildConfig();
  state.buildStore[state.buildWeapon.path] = state.buildConfigs;
  writeBuildStore();
  if (ui["build-config-status"]) ui["build-config-status"].textContent = `配置 ${state.activeConfig} 已保存`;
}

function loadBuildConfigsForWeapon(weapon) {
  const stored = weapon?.path ? state.buildStore[weapon.path] : null;
  state.buildConfigs = { A: stored?.A || null, B: stored?.B || null, C: stored?.C || null };
  state.activeConfig = "A";
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
    if (isWarframe ? warframeCount >= 2 : weaponCount >= 1) return [];
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
  const maxStacks = Math.max(1, Number(item.trigger?.maxStacks ?? 1) || 1);
  if (item.forceProc) return { ...base, stacks: maxStacks, uptime: 1 };
  if (Number.isInteger(item.fixedStacks) && item.fixedStacks > 0) {
    return { ...base, stacks: clamp(item.fixedStacks, 1, maxStacks), uptime: 1 };
  }
  return base;
}

function syncArcaneSelections() {
  state.arcaneSelections = [state.weaponArcane, ...state.frameArcanes].filter(Boolean).map((item) => ({ ...item }));
}

function applyBuildConfig(config) {
  if (!config || typeof config !== "object") {
    state.manualSlots = Array.from({ length: 8 }, () => null);
    resetSpecialSelections();
    state.incarnonChoices = {};
    renderManualSlots();
    renderManualMods();
    renderSpecialSlots();
    renderArcaneSelections();
    return;
  }
  setControlValue("build-fire-mode-select", config.fireMode ?? 0);
  refreshBuildMetrics();
  setControlValue("build-metric-select", config.metric || ui["build-metric-select"]?.value || "");
  setControlValue("build-element-select", config.elementTarget || "");
  setControlValue("build-innate-element-select", config.innateElement || defaultInnateElement(state.buildWeapon));
  setControlValue("build-innate-element-value", clamp(Math.round(Number(config.innateElementValue ?? 0.60) * 100), 25, 60));
  setControlValue("build-slot-count", clamp(Number(config.slotCount ?? 8), 4, 8));
  setControlValue("build-enemy-select", config.enemy || ui["build-enemy-select"]?.value || "");
  fillBuildEnemies();
  setControlValue("build-enemy-level", config.level ?? 160);
  setControlValue("build-armour-strip", config.armourStrip ?? 0);
  setControlValue("build-headshot-chance", config.headshotChance ?? 0);
  setControlValue("build-distance", config.distance ?? 0);
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
      stats: config.riven.stats.map((s) => ({ ...s })),
    };
  }
  restoreSpecialSelections(config);
  state.externalBuffs = Array.isArray(config.externalBuffs) ? config.externalBuffs.slice(0, 12).map((item) => ({ ...item })) : [];
  state.formaSlots = {};
  if (config.formaSlots && typeof config.formaSlots === "object") {
    for (const [key, value] of Object.entries(config.formaSlots)) {
      const index = Number(key);
      if (Number.isInteger(index) && index >= 0 && index < 10 && typeof value === "string" && value) state.formaSlots[index] = value;
    }
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
  state.formaCount = Object.keys(state.formaSlots).length;
  if (ui["forma-count"]) ui["forma-count"].textContent = String(state.formaCount);
  state.rivenBuilderStats = Array.isArray(config.riven?.stats) ? config.riven.stats.map((s) => ({ ...s })) : [];
  state.incarnonChoices = config.incarnonChoices && typeof config.incarnonChoices === "object" ? { ...config.incarnonChoices } : {};
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
      if (!config || ![1, BUILD_CONFIG_SCHEMA].includes(schema)) throw new Error("配置 schema 不兼容");
      state.buildConfigs[state.activeConfig] = config;
      applyBuildConfig(config);
      persistActiveBuildConfig();
      toast(`已导入配置 ${state.activeConfig}`);
    } catch (error) {
      toast(error.message || "配置导入失败");
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
  return [
    ...(catalog.manualMods || []), ...(catalog.manualModVariants || []), ...(catalog.utilityMods || []),
    ...(catalog.stances || []), ...(catalog.arcanes || []),
    ...(parts.chambers || []), ...(parts.grips || []), ...(parts.loaders || []),
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
  };
  const parts = kitgunPartsPayload();
  if (parts) config.kitgunParts = parts;
  return { schema: 1, kind: "weapon", target: state.buildWeapon?.path || "", config };
}

function rabbitWarframeConfig() {
  const source = captureWarframeConfig();
  const config = {
    schema: 1,
    buildLabel: source.buildLabel,
    aura: source.aura,
    exilus: source.exilus,
    normalMods: source.normalMods,
    arcanes: source.arcanes,
    shards: source.shards,
    slotPolarities: source.slotPolarities,
    helminthSlot: source.helminthSlot,
    helminthAbility: source.helminthAbility,
    invigoration: source.invigoration,
    applyConditionals: source.applyConditionals,
  };
  return { schema: 1, kind: "warframe", target: warframeId(state.warframeBuild.frame), config };
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
  if (!response.ok) throw new Error(result?.error?.message || `Rabbit 武器快照失败（${response.status}）`);
  return result;
}

async function rabbitCurrentWarframeResult() {
  const response = await fetch("/api/warframe/calculate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(warframePayload()) });
  const result = await response.json();
  if (!response.ok) throw new Error(result?.error?.message || `Rabbit 战甲快照失败（${response.status}）`);
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
  const native = frameSlotPolarities(build.frame);
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
  const native = frameSlotPolarities(build.frame);
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
  const source = Array.isArray(build.frame?.abilities) ? build.frame.abilities : [];
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
  const sourceAbility = build.helminthSlot === null ? null : build.frame?.abilities?.[build.helminthSlot];
  return {
    schema: 1,
    kind: "warframe",
    build_label: state.warframeCatalog?.buildLabel || "OFFLINE",
    game_version: state.warframeCatalog?.buildLabel || "OFFLINE",
    target: { id: warframeId(build.frame), name_zh: warframeName(build.frame), name_en: build.frame?.nameEn || "" },
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
          health: Number(build.frame?.basePanel?.health || 0), shield: Number(build.frame?.basePanel?.shield || 0),
          armor: Number(build.frame?.basePanel?.armor || 0), energy: Number(build.frame?.basePanel?.energy || 0),
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
  ui["rabbit-target"].value = kind === "weapon" ? weaponName(state.buildWeapon) : warframeName(state.warframeBuild.frame);
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
  status.textContent = "正在生成配装快照…";
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
  if (!weapon) throw new Error("Rabbit 配装中的武器不在当前冻结目录");
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
  const frame = warframeResolve(warframeRows("warframes"), wrapper.target);
  if (!frame) throw new Error("Rabbit 配装中的战甲不在当前冻结目录");
  setActiveTool("warframe");
  selectWarframeFrame(frame);
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
      ? `${TYPE_LABELS[weapon.weaponType] || weapon.weaponType} · 倾向 ${formatDisposition(weapon.disposition)}`
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
        : `${TYPE_LABELS[weapon.weaponType] || weapon.weaponType} · 倾向 ${formatDisposition(weapon.disposition)}`;
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
  return state.weapon ? (state.catalog.statsByType[state.weapon.weaponType] || []) : [];
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

function deriveRange(definition, negative) {
  if (!definition || !state.weapon) return null;
  const shape = statShape();
  let multiplier;
  if (negative) {
    multiplier = shape.positive === 3 ? 0.757525 : 0.5;
  } else {
    multiplier = shape.positive === 3 ? 0.757525 : 1;
    if (shape.negative) multiplier *= 1.25;
  }
  const nominal = Math.abs(definition.baseValue * state.weapon.disposition * multiplier);
  return { low: nominal * 0.89, high: nominal * 1.089 };
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
  const used = new Set(activeStats().filter((entry) => entry.row.querySelector(".stat-code") !== select).map((entry) => entry.code));
  const options = statDefinitions().map((definition) => {
    const option = document.createElement("option");
    option.value = definition.code;
    option.textContent = definition.objectiveSupported ? definition.label : `${definition.label} · 评分外`;
    option.disabled = used.has(definition.code) && definition.code !== previous;
    return option;
  });
  select.replaceChildren(...options);
  if (options.some((option) => option.value === previous)) select.value = previous;
}

function refreshStatSelects() {
  for (const entry of activeStats()) fillStatSelect(entry.row.querySelector(".stat-code"), entry.code);
}

function chooseUnusedCode(preferred) {
  const definitions = statDefinitions();
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
  fillStatSelect(select, chooseUnusedCode(preferredCode));
  select.value = chooseUnusedCode(preferredCode);
  setRowNegative(row, negative);

  row.querySelector(".sign-toggle").addEventListener("click", () => toggleSign(row));
  row.querySelector(".remove-stat").addEventListener("click", () => removeStat(row));
  select.addEventListener("change", () => {
    const definition = statDefinitions().find((entry) => entry.code === select.value);
    if (row.querySelector(".sign-toggle").classList.contains("is-negative") && !definition?.canNegative) {
      setRowNegative(row, false);
      toast(`${definition.label} 不能作为负面词条`);
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
  const entries = activeStats();
  const seedSource = `${state.weapon?.path || "empty"}:${entries.map((entry) => `${entry.code}:${entry.value}:${entry.negative}`).join("|")}`;
  const seed = hashText(seedSource);
  const baseName = rivenWeaponDisplayName(state.weapon);
  ui["card-name"].textContent = `${baseName} ${RIVEN_SUFFIXES[seed % RIVEN_SUFFIXES.length]}`;
  ui["card-name"].style.setProperty("--name-length", String(ui["card-name"].textContent.length));
  ui["card-mr"].textContent = String(8 + (seed % 9));
  ui["card-rerolls"].textContent = String((seed >>> 4) % 1000);
  const polarityNames = RIVEN_CARD_POLARITIES;
  const polarity = polarityNames[(seed >>> 10) % polarityNames.length];
  ui["card-polarity"].src = POLARITY_IMAGES[polarity];
  ui["card-polarity"].alt = `${polarity} 极性`;

  const lines = entries.filter((entry) => entry.definition && entry.value !== null).map((entry) => {
    const line = create("span", entry.negative ? "is-negative" : "");
    line.textContent = `${formatStatNumber(entry.value, entry.definition, entry.negative)} ${entry.definition.label}`;
    return line;
  });
  ui["card-stats"].replaceChildren(...(lines.length ? lines : [create("span", "card-empty", "等待录入词条")]));
  ui["riven-card"].classList.toggle("is-active", Boolean(state.weapon && lines.length));
}

function rivenWeaponDisplayName(weapon) {
  let name = String(weapon?.nameZh || weapon?.nameEn || weapon?.nameInternal || "Riven").trim();
  name = name.replace(/\s+Prime$/i, "").replace(/\s+Prime版$/i, "").trim();
  return name || "Riven";
}

function updateAnalyzeAvailability() {
  const shape = statShape();
  const validShape = shape.total >= 2 && shape.total <= 4 && (shape.positive === 2 || shape.positive === 3) && shape.negative <= 1;
  const isAssembly = state.assemblyFor === "analysis" && state.kitgunBase && state.kitgunBase.path === state.weapon?.path;
  const weaponReady = Boolean(state.weapon) && (isAssembly ? assemblyWeaponReady() : state.weapon.analysisAvailable !== false);
  ui["analyze-button"].disabled = !weaponReady || !validShape;
  ui["add-stat"].disabled = shape.total >= 4 || !state.weapon;
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
  const payload = { weapon: state.weapon.path, disposition: state.weapon.disposition, stats };
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
  const messages = ["比对武器档案与词条贡献", "求解包含当前紫卡的 8 槽配装", "整理 T0–T3 词条优先级"];
  let messageIndex = 0;
  state.loadingTimer = window.setInterval(() => {
    messageIndex = (messageIndex + 1) % messages.length;
    ui["loading-copy"].textContent = messages[messageIndex];
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
    ui["export-button"].disabled = false;
    setResultState("content");
    ui["result-content"].scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    ui["error-message"].textContent = error.message || "分析失败";
    setResultState("error");
  } finally {
    window.clearInterval(state.loadingTimer);
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
  const score = clamp(finite(state.result.score) ?? 0, 0, 100);
  ui["score-value"].textContent = score.toFixed(1);
  ui["grade-value"].textContent = state.result.grade || "--";
  const resultWeapon = state.result?.weapon;
  const displayWeapon = resultWeapon && (resultWeapon.nameZh || resultWeapon.nameEn) ? resultWeapon : state.weapon;
  ui["weapon-result-name"].textContent = `${weaponName(displayWeapon)} · ${TYPE_LABELS[state.weapon.weaponType] || state.weapon.weaponType}`;
  ui["actual-gain"].textContent = formatPercent(state.result.actualGain);
  ui["optimal-gain"].textContent = formatPercent(state.result.optimalGain);
  ui["roll-quality"].textContent = formatQuality(state.result.rollQuality);
  ui["result-disposition"].textContent = formatDisposition(state.result.disposition);
  const circumference = 2 * Math.PI * 51;
  ui["orbit-value"].style.strokeDasharray = String(circumference);
  ui["orbit-value"].style.strokeDashoffset = String(circumference * (1 - score / 100));
  ui["score-orbit"].dataset.grade = String(state.result.grade || "").charAt(0).toUpperCase();
}

function renderContributions() {
  const details = Array.isArray(state.result.details) ? state.result.details : [];
  const max = Math.max(1, ...details.map((entry) => Math.abs(finite(entry.delta) ?? 0)));
  const rows = details.map((detail) => {
    const negative = state.submittedStats.find((entry) => entry.code === detail.code)?.negative;
    const delta = finite(detail.delta) ?? 0;
    const row = create("article", `contribution-row${delta < 0 ? " is-harmful" : ""}`);
    const head = create("div", "contribution-head");
    const title = create("div");
    title.append(create("span", "contribution-sign", negative ? "−" : "+"), create("strong", "", detail.label || detail.code));
    const value = create("div", "contribution-values");
    value.append(create("b", "", `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`), create("span", "", `数值 ${formatQuality(detail.quality)}`));
    head.append(title, value);
    const track = create("div", "contribution-track");
    const fill = create("i");
    fill.style.width = `${Math.max(delta === 0 ? 2 : 7, Math.abs(delta) / max * 100)}%`;
    track.append(fill);
    row.append(head, track);
    return row;
  });
  ui["contribution-list"].replaceChildren(...(rows.length ? rows : [create("p", "empty-copy", "没有可显示的贡献明细")]))
}

const DIAGNOSTIC_CODE_LABELS = {
  "kitgun-radial-damage-unapplied": "组合枪爆炸范围伤害部分未计入单目标计算",
  "kitgun-chain-damage-unapplied": "组合枪光束的链式伤害未计入",
  "kitgun-cluster-damage-unapplied": "组合枪孢子分裂弹的二次伤害未计入",
  "loadout-over-capacity": "配装超出 60 容量上限",
};

// 灵化分支诊断码（incarnon-<分支id>-<原因>）翻译成人话，原因口径与后端注明一致。
const INCARNON_DIAGNOSTIC_REASONS = {
  "runtime-scripts-not-applied": "含游戏内动态脚本效果（形态/叠层联动），该部分不参与解算",
  "conditional-effects-not-applied": "含未激活的条件效果，该部分不参与解算",
  "unresolved-references": "含未解析的数据引用",
  "NONE-not-evaluated": "脚本占位词条不参与解算",
};

function incarnonDiagnosticLabel(code) {
  const match = String(code).match(/^incarnon-([a-z0-9-]+?)-(runtime-scripts-not-applied|conditional-effects-not-applied|unresolved-references|NONE-not-evaluated)$/);
  if (!match) return null;
  const reason = INCARNON_DIAGNOSTIC_REASONS[match[2]];
  return reason ? `灵化分支 ${match[1]}：${reason}` : null;
}

function normalizeLabels(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value.flatMap(normalizeLabels);
  if (typeof value === "string") return [DIAGNOSTIC_CODE_LABELS[value] || incarnonDiagnosticLabel(value) || value];
  if (typeof value === "object") return [value.label || value.nameZh || value.nameEn || DIAGNOSTIC_CODE_LABELS[value.code] || incarnonDiagnosticLabel(value.code) || value.code].filter(Boolean);
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
  ui["fatal-negative"].textContent = fatal.join(" / ") || "无";
  ui["fatal-box"].classList.toggle("is-clear", !fatal.length);
}

function formatMetric(value) {
  const number = finite(value);
  if (number === null) return "--";
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 2 }).format(number);
}

function buildMetrics(build, weapon = state.weapon) {
  const preferred = ["melee", "zaw"].includes(weapon?.weaponType)
    ? ["attackDps", "heavyDamage", "heavyAttackDps", "shotDamage"]
    : ["shotDamage", "burstDps", "sustainedDps"];
  return preferred.filter((key) => finite(build?.[key]) !== null).slice(0, 4);
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
    const value = create("strong", "", text);
    if (previousValues.has(METRIC_LABELS[key]) && previousValues.get(METRIC_LABELS[key]) !== text) value.classList.add("is-flash");
    card.append(create("span", "", METRIC_LABELS[key]), value);
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
    if (iconEl && lead) {
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
    const setText = isSacrificeSetMod(mod) ? "" : modSetText(mod);
    if (setText) frag.append(create("p", "mod-effect-line is-set is-set-detail", setText));
    const summary = modStackedSummary(mod);
    if (summary) frag.append(create("p", "mod-effect-line is-calculated", summary));
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
  const type = state.buildWeapon?.weaponType;
  return state.catalog?.statsByType?.[type] || [];
}

function rivenNominalRange(definition, negative, positiveCount, negativeCount) {
  const disposition = Number(state.buildWeapon?.disposition || 1);
  let multiplier;
  if (negative) multiplier = positiveCount === 3 ? 0.757525 : 0.5;
  else {
    multiplier = positiveCount === 3 ? 0.757525 : 1.0;
    if (negativeCount) multiplier *= 1.25;
  }
  const nominal = Math.abs(Number(definition.baseValue || 0) * disposition * multiplier);
  return { low: nominal * 0.89, high: nominal * 1.089 };
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
      if (!entry.negative && (negativeCount >= 1 || positiveCount <= 2)) return toast("负面最多 1 条且需保留 2 条正面");
      entry.negative = !entry.negative;
      renderManualMods();
    });
    const select = document.createElement("select");
    select.className = "riven-stat-code";
    defs.forEach((d) => {
      const option = document.createElement("option");
      option.value = d.code;
      option.textContent = d.label || d.code;
      option.selected = d.code === entry.code;
      select.append(option);
    });
    select.value = entry.code;
    select.addEventListener("change", () => { entry.code = select.value; renderManualMods(); });
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
    const next = defs.find((d) => !used.has(d.code) && (state.rivenBuilderStats.filter((s) => s.negative).length < 1 || !d.canNegative));
    if (!next) return toast("没有更多可用词条");
    const negative = state.rivenBuilderStats.length >= 3 && state.rivenBuilderStats.every((s) => !s.negative) && next.canNegative;
    state.rivenBuilderStats.push({ code: next.code, value: null, negative });
    renderManualMods();
  });
  actions.append(add);
  const insert = create("button", "button button-primary", "放入当前槽位");
  insert.type = "button";
  insert.addEventListener("click", () => {
    const slot = state.modPickerSlot;
    if (state.manualLocks[slot]) return toast("当前槽位已锁定");
    const stats = state.rivenBuilderStats.map((s) => ({ code: s.code, value: Number(s.value || 0), negative: Boolean(s.negative) }));
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
    };
    renderManualSlots();
    persistActiveBuildConfig();
    scheduleLiveManualSimulation();
    closeModPicker();
    toast("紫卡已放入槽位");
  });
  actions.append(insert);
  const hint = create("small", "riven-builder-hint", "词条范围 = 官方 wiki 公式（倾向 × 基准 × 结构系数）；渲染使用 Omega 框系素材");
  actions.append(hint);
  panel.append(actions);
  target.replaceChildren(panel);
}

function createCustomRivenSlotCard(mod, index, slotPolarity = null) {
  const card = create("article", "mod-slot is-riven-slot");
  card.dataset.rarity = "RIVEN";
  const frame = create("div", "game-mod-card riven-mod-card");
  const frames = state.modAssets?.rarityFrames?.RIVEN || {};
  const content = create("div", "mod-content");
  content.append(...modContentLayers(frames, {}, {}, "mod-art", "eager"));
  const description = create("div", "mod-description");
  description.append(modNameNode(mod.nameZh || "自定义紫卡"));
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
  // 消耗/极性随槽位极化声明联动：formaSlots 声明非万能极性即视为紫卡匹配，
  // 消耗减半（18→9），徽章显示声明的极性；未声明保持 18 与占位图标。
  const rivenEffective = modEffectiveDrain(mod, slotPolarity, index);
  const declaredPolarity = state.formaSlots?.[index] || null;
  const badge = modCostBadge(rivenEffective.drain, declaredPolarity, "eager", " is-riven-drain", rivenEffective.relation === "match" ? "match" : "");
  if (!declaredPolarity) {
    badge.querySelector(".mod-drain").append(imageNode(POLARITY_IMAGES.AP_ATTACK, "mod-polarity", "紫卡极性", "eager"));
  }
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
    return cleanOfficialText(meta.conditionZh).replace(/<\/?DT_[A-Z_]+_COLOR>/g, "");
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
  content.append(...modContentLayers(frames, {}, {}, "mod-art", "eager"));
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
    const rivenSlot = cells.map((cell, i) => (cell ? -1 : i)).filter((i) => i >= 0).pop();
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

function manualModRecords() {
  const weapon = state.buildWeapon;
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
  const filtered = rows.filter((mod) => {
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
  const card = createNormalModCard({ ...mod, art: catalogIconAsset(mod), maxRank, rank: Number(mod.rank ?? maxRank) }, 0, {
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
    option.title = supported ? "使用后端提供的自定义防御快照" : "当前离线后端未实现自定义防御快照";
  }
  const active = select?.value === "custom";
  if (ui["custom-defense-fields"]) ui["custom-defense-fields"].hidden = !active;
  if (ui["custom-defense-note"]) ui["custom-defense-note"].textContent = supported
    ? "该快照会原样发送给后端，不会套用幻影装置敌人数据。"
    : "当前离线后端未声明支持，已禁用自定义模型。";
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
    const maxRank = Number(mod.maxRank ?? mod.rank ?? joined.maxRank ?? 0);
    const description = cleanOfficialText(mod.description || joined.description || "");
    const effectsZhByRank = Array.isArray(mod.effectsZhByRank) ? mod.effectsZhByRank.map((rank) => (Array.isArray(rank) ? rank.map(cleanOfficialText) : rank)) : mod.effectsZhByRank;
    return { ...joined, ...mod, maxRank, rank: Number(mod.selectedRank ?? maxRank), description, effectsZhByRank };
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
    const frames = (config.frameArcanes || []).slice(0, 2).map((item) => hydrateRankedSelection(item, arcaneRecords(), "warframe"));
    state.frameArcanes = [frames[0] || null, frames[1] || null];
  } else {
    const legacy = normalizeArcaneSelections(config?.arcanes || config?.arcaneSelections);
    state.weaponArcane = legacy.find((item) => item.slotKind !== "warframe") || null;
    const frames = legacy.filter((item) => item.slotKind === "warframe").slice(0, 2);
    state.frameArcanes = [frames[0] || null, frames[1] || null];
  }
  syncArcaneSelections();
}

function arcaneRecords() {
  return Array.isArray(state.catalog?.arcanes) ? state.catalog.arcanes : [];
}

function arcaneMatchesBuildWeapon(arcane) {
  if (arcane?.slotKind === "warframe") return true;
  const compatibility = String(arcane?.compatibility || "").toLocaleLowerCase();
  if (!compatibility) return true;
  if (compatibility.includes("powersuit") || compatibility.includes("operatoramp")) return false;
  if (compatibility.includes("melee")) return isMeleeBuild();
  if (compatibility.includes("pistol")) return state.buildWeapon?.slot === "secondary" || state.buildWeapon?.weaponType === "pistol";
  if (/longgun|rifle|shotgun|bulletweapon/.test(compatibility)) return state.buildWeapon?.slot === "primary" || ["rifle", "shotgun", "archgun"].includes(state.buildWeapon?.weaponType);
  return true;
}

// ── Arcane picker (modal list + search + hover preview) ───────────────────
function arcanePickerRows(kind) {
  const query = String(ui["arcane-picker-search"]?.value || "").trim().toLocaleLowerCase();
  return arcaneRecords().filter((arcane) => {
    const matchesKind = kind === "warframe" ? arcane.slotKind === "warframe" : arcane.slotKind !== "warframe";
    if (!matchesKind || (kind !== "warframe" && !arcaneMatchesBuildWeapon(arcane))) return false;
    if (!query) return true;
    return [arcane.nameZh, arcane.nameEn, arcane.path].filter(Boolean).join(" ").toLocaleLowerCase().includes(query);
  });
}

function arcaneEffectHint(arcane) {
  const trigger = arcane.trigger || {};
  const bits = [];
  if (trigger.conditionZh) bits.push(String(trigger.conditionZh).replace(/<\/?DT_[A-Z_]+_COLOR>/g, ""));
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

function arcaneDescription(arcane) {
  return String(arcane?.description || arcane?.effect || arcaneEffectHint(arcane))
    .replace(/<\/?DT_[A-Z_]+_COLOR>/g, "");
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
  state.arcanePickerSlot = clamp(Number(slotIndex) || 0, 0, kind === "warframe" ? 1 : 0);
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

const EXTERNAL_BUFFS = [
  { id: "roar", label: "战吼 Roar", group: "终伤", base: 0.5, note: "派系乘区，受强度" },
  { id: "eclipse", label: "黯然失色 Eclipse", group: "终伤", base: 2.0, note: "光照 +200% 终伤" },
  { id: "molecular-prime", label: "分子填充 Molecular Prime", group: "终伤", base: 1.0, note: "双倍伤害" },
  { id: "void-strike", label: "虚空重击 Void Strike", group: "终伤", base: 12.0, note: "Madurai，按时间窗" },
  { id: "unairu-wisp", label: "Unairu 虚灵", group: "终伤", base: 1.0, note: "4 层 +100%" },
  { id: "arbitration", label: "仲裁加成", group: "终伤", base: 3.0, note: "+300%" },
  { id: "base-damage", label: "通用基伤", group: "基伤", base: 1.0, note: "与基伤 mod 同乘区" },
  { id: "vex-armor", label: "怨怒护甲 Vex Armor", group: "基伤", base: 2.75, note: "Chroma，受强度" },
  { id: "shooting-gallery", label: "靶场 Shooting Gallery", group: "基伤", base: 0.25, note: "Mesa，受强度" },
  { id: "mallet", label: "强音增幅 Mallet", group: "基伤", base: 2.0, note: "Octavia 放大" },
  { id: "metamorphosis", label: "昼夜交替 Metamorphosis", group: "基伤", base: 0.25, note: "Equinox" },
  { id: "vigoruous-swap", label: "强力切换 Vigorous Swap", group: "基伤", base: 1.65, note: "11 层" },
  { id: "dead-eye", label: "死亡之眼 Dead Eye", group: "基伤", base: 0.525, note: "集团光环" },
  { id: "fireball-frenzy", label: "狂热火球", group: "元素", base: 1.0, note: "+100% 火焰" },
  { id: "flash-accelerant", label: "闪耀助燃", group: "元素", base: 0.5, note: "+50% 火焰" },
  { id: "freeze-force", label: "寒冰之力", group: "元素", base: 1.0, note: "+100% 冰冻" },
  { id: "shock-trooper", label: "电击奇兵", group: "元素", base: 1.0, note: "+100% 电击" },
  { id: "smite-infusion", label: "惩击洗礼", group: "元素", base: 1.0, note: "+100% 辐射" },
  { id: "venom-dose", label: "猛毒附加", group: "元素", base: 1.0, note: "+100% 腐蚀" },
  { id: "crit-chance", label: "通用暴击", group: "暴击/触发", base: 1.0, note: "暴击几率" },
  { id: "covenant", label: "庇佑圣约 Covenant", group: "暴击/触发", base: 0.5, note: "Harrow 满层" },
  { id: "crit-damage", label: "通用暴伤", group: "暴击/触发", base: 1.0, note: "暴击伤害" },
  { id: "status", label: "通用触发", group: "暴击/触发", base: 1.0, note: "触发几率" },
  { id: "multishot", label: "通用多重", group: "射击", base: 1.0, note: "多重射击" },
  { id: "fire-rate", label: "通用射速", group: "射击", base: 1.0, note: "射速/攻速" },
  { id: "warcry", label: "咆哮 Warcry", group: "射击", base: 0.5, note: "Valkyr 攻速" },
  { id: "reload", label: "通用装填", group: "射击", base: 1.0, note: "装填速度" },
  { id: "magazine", label: "通用弹匣", group: "射击", base: 1.0, note: "弹匣容量" },
];
const EXTERNAL_BUFF_GROUPS = ["终伤", "基伤", "元素", "暴击/触发", "射击"];

const WEAPON_PICKER_CATEGORIES = {
  all: "全部", rifle: "步枪", shotgun: "霰弹枪", pistol: "手枪", melee: "近战", zaw: "组合近战", kitgun: "组合枪", archgun: "Archwing",
};

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
    return (!query || haystack.includes(query)) && (assemblyCategory === "all" || weapon.weaponType === assemblyCategory);
  }).concat(
    [...merged.entries()].filter(([key, weapon]) => {
      const haystack = [weapon.nameZh, weapon.nameEn, weapon.nameInternal, weapon.path, "组合枪", "组合近战", "kitgun", "zaw", "装配"].filter(Boolean).join(" ").toLocaleLowerCase();
      return showAssembly(key) && (!query || haystack.includes(query));
    }).map(([, weapon]) => weapon),
  );
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
    counts.set(weapon.weaponType, (counts.get(weapon.weaponType) || 0) + 1);
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
    copy.append(
      create("strong", "", isAssembly ? (isZaw ? "组合近战（Zaw · 装配）" : `组合枪（${weapon.slot === "primary" ? "主武器" : "副武器"} · 装配）`) : weaponName(weapon)),
      create("small", "", isAssembly
        ? `${isZaw ? "剑刃×握把×配重" : "腔体×握把×装填器"} · 倾向 ${kitgunDispo ? formatDisposition(kitgunDispo) : isZaw ? "跟剑刃" : "跟腔体"}${kitgunDispo ? " " + dispositionDots(kitgunDispo) : ""}`
        : `${TYPE_LABELS[weapon.weaponType] || weapon.weaponType} · 倾向 ${formatDisposition(weapon.disposition)} ${dispositionDots(weapon.disposition)}`),
    );
    option.append(copy);
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

function renderExternalBuffs() {
  const target = document.getElementById("external-buff-list");
  if (!target) return;
  const groups = EXTERNAL_BUFF_GROUPS.map((groupName) => {
    const section = create("div", "external-buff-group");
    section.append(create("h4", "external-buff-group-title", groupName));    EXTERNAL_BUFFS.filter((buff) => buff.group === groupName).forEach((buff) => {
      const row = create("label", "external-buff-row");
      const enabled = state.externalBuffs.some((item) => item.id === buff.id);
      const current = state.externalBuffs.find((item) => item.id === buff.id);
      const check = document.createElement("input");
      check.type = "checkbox";
      check.checked = enabled;
      check.addEventListener("change", () => {
        if (check.checked) {
          state.externalBuffs.push({ id: buff.id, value: buff.base });
        } else {
          state.externalBuffs = state.externalBuffs.filter((item) => item.id !== buff.id);
        }
        renderExternalBuffs();
        persistActiveBuildConfig();
        scheduleLiveManualSimulation();
      });
      const copy = create("span", "external-buff-copy");
      copy.append(create("strong", "", buff.label));
      copy.append(create("small", "", buff.note));
      row.append(check, copy);
      if (enabled) {
        const slider = document.createElement("input");
        slider.type = "range";
        slider.min = "0";
        slider.max = "50";
        slider.step = "0.05";
        slider.value = String((current?.value ?? buff.base) / buff.base);
        slider.title = "数值倍率（上限 5000%）";
        const number = document.createElement("input");
        number.type = "number";
        number.min = "0";
        number.max = "5000";
        number.step = "1";
        number.value = String(Math.round((current?.value ?? buff.base) * 100));
        number.title = "直接输入百分比（0–5000）";
        const apply = (raw) => {
          const percent = clamp(Number(raw), 0, 5000);
          current.value = percent / 100;
          slider.value = String(clamp(current.value / buff.base, 0, 50));
          number.value = String(Math.round(percent));
          readout.textContent = `+${Math.round(percent)}%`;
          scheduleLiveManualSimulation();
        };
        slider.addEventListener("input", () => apply(buff.base * Number(slider.value) * 100));
        number.addEventListener("change", () => apply(number.value));
        const readout = create("b", "external-buff-value", `+${Math.round((current?.value ?? buff.base) * 100)}%`);
        row.append(slider, number, readout);
      } else {
        row.append(create("span", "external-buff-spacer"), create("b", "external-buff-value is-muted", `+${Math.round(buff.base * 100)}%`));
      }
      section.append(row);
    });
    return section;
  });
  target.replaceChildren(...groups);
  renderExternalBuffGain();
}

async function renderExternalBuffGain() {
  // Compare current DPS with and without external buffs — real simulation gain.
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
  try {
    const post = async (buffs) => {
      const res = await fetch("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, externalBuffs: buffs }) });
      const body = await res.json();
      if (!res.ok) throw new Error("simulate failed");
      const sim = body.simulation || body;
      return finite(sim.targetDamage?.dps) ?? finite(sim.moddedStats?.sustainedDps) ?? 0;
    };
    const [withBuffs, without] = await Promise.all([post(state.externalBuffs.map((b) => ({ id: b.id, value: b.value }))), post([])]);
    if (without > 0) {
      const percent = (withBuffs / without - 1) * 100;
      gainEl.hidden = false;
      gainEl.innerHTML = "";
      gainEl.append(
        create("span", "", "外部加成总收益"),
        create("b", `external-buff-gain-value${percent < 0 ? " is-negative" : ""}`, `${percent >= 0 ? "+" : ""}${percent.toFixed(1)}%`),
        create("small", "", `${formatMetric(withBuffs)} → ${formatMetric(without)} DPS（关闭后）`),
      );
    }
  } catch (_error) {
    gainEl.hidden = true;
  }
}

function externalBuffsPayload() {
  return state.externalBuffs.map((item) => ({ id: item.id, value: Number(item.value ?? 0) }));
}

function rivenPayload() {
  const rivenSlot = state.manualSlots.find((mod) => mod && mod.__riven && Array.isArray(mod.stats) && mod.stats.length);
  if (!rivenSlot) return null;
  return {
    stats: rivenSlot.stats.map((stat) => ({ code: stat.code, value: Number(stat.value || 0), negative: Boolean(stat.negative) })),
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
    copy.append(create("p", "arcane-slot-description", arcaneDescription(record)));
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
      const target = kind === "warframe" ? state.frameArcanes[slotIndex] : state.weaponArcane;
      target.rank = clamp(next, 0, maxRank);
      syncArcaneSelections(); renderArcaneSelections(); persistActiveBuildConfig(); scheduleLiveManualSimulation();
    };
    down.addEventListener("click", (event) => { event.stopPropagation(); update(rank - 1); });
    up.addEventListener("click", (event) => { event.stopPropagation(); update(rank + 1); });
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      if (kind === "warframe") state.frameArcanes[slotIndex] = null;
      else state.weaponArcane = null;
      syncArcaneSelections(); renderArcaneSelections(); persistActiveBuildConfig(); scheduleLiveManualSimulation();
    });
    controls.append(down, create("span", "rank-stepper-value", `R${rank}`), up, remove);
    slot.append(controls);
    // 触发型赋能提供「强制触发 / 限定层数」开关：默认关闭时由后端按武器面板
    // 推导触发期望；打开后按手动状态（满层全程 / 固定层数全程）参与解算。
    const trigger = record.trigger || {};
    const hasTrigger = trigger.conditionTag || trigger.chance != null || trigger.maxStacks != null;
    if (hasTrigger) {
      const maxStacks = Math.max(1, Number(trigger.maxStacks ?? 1) || 1);
      const entry = () => (kind === "warframe" ? state.frameArcanes[slotIndex] : state.weaponArcane);
      const commit = () => { syncArcaneSelections(); renderArcaneSelections(); persistActiveBuildConfig(); scheduleLiveManualSimulation(); };
      const toggles = create("div", "arcane-slot-toggles");
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
          toggles.append(sdown, create("span", "rank-stepper-value", `${current} 层`), sup);
        }
      }
      slot.append(toggles);
    }
  }
  return slot;
}

function renderArcaneSelections() {
  const target = ui["build-arcane-list"];
  if (!target) return;
  const specs = [
    ["weapon", 0, state.weaponArcane],
    ["warframe", 0, state.frameArcanes[0]],
    ["warframe", 1, state.frameArcanes[1]],
  ];
  // diff 复用：未变化的赋能槽不重绘（图标/框图不重载）
  const existing = Array.from(target.children);
  specs.forEach(([kind, slotIndex, item], position) => {
    const signature = [kind, slotIndex, item?.path || "", item ? Number(item.rank ?? item.maxRank ?? 0) : "", item?.forceProc ? 1 : 0, item?.fixedStacks ?? "", state.buildInputMode].join("|");
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
  const current = state.arcanePickerKind === "warframe" ? state.frameArcanes[state.arcanePickerSlot] : state.weaponArcane;
  if (state.arcaneSelections.some((item) => item.path === target && item !== current)) return toast("该赋能已经添加");
  const record = arcaneRecords().find((item) => item.path === target) || {};
  const isFrame = record.slotKind === "warframe";
  const selection = {
    ...record,
    path: target,
    rank: Number(record.maxRank ?? 0),
    slotKind: record.slotKind || "weapon",
  };
  if (isFrame) state.frameArcanes[state.arcanePickerSlot] = selection;
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
  // The frozen Warframe sidecar is newer and more specific than the shared
  // weapon-art index.  Merge art/frame metadata underneath the selected row so
  // stale generic fields can never overwrite rank, slot type, text or sets.
  const merged = { ...asset };
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
      label: applySetMultiplierToOfficialLine(seg, setMultiplier)
        .replace(/<\/?DT_[A-Z_]+_COLOR>/g, "")
        .replace(/<[^>]+>/g, ""),
      icon: ELEMENT_ICONS[iconKey] || null,
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
  return String(value || "")
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
  return count && values.length ? `计算采用满层 ${count} 层：${values.join("；")}` : "";
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
      ? `套装 ${mod.setMaxPieces} 件效果依赖运行时条件，本引擎不支持模拟（当前 ${Math.min(pieces, maxPieces)} 件）`
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
  const conditionLine = condition && !conditionAlreadyListed(meta) ? String(condition).replace(/<\/?DT_[A-Z_]+_COLOR>/g, "") : "";
  const officialText = String(official || "");
  const uniqueLines = lines.filter((line) => !officialText.includes(String(line)));
  const unsupportedNote = Array.isArray(mod?.unsupportedNotes) && mod.unsupportedNotes.length ? "该词条不参与引擎解算" : "";
  // Unsupported diagnostics stay in the hover title/diagnostics channel, not
  // in the rendered card: "mod-effect-line is-unsupported", "该词条不参与引擎解算"。
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
    // 紫卡自身极性由槽位极化声明：槽位已被 forma 极化（formaSlots 有记录）
    // 即视为紫卡与该槽匹配，消耗减半；未极化保持中性全值。
    const declared = Number.isInteger(slotIndex) ? state.formaSlots?.[slotIndex] : null;
    if (declared && slotPolarity && slotPolarity !== "AP_UNIVERSAL") {
      return { drain: Math.ceil(base / 2), relation: "match" };
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
    let formaNeeded = 0;
    let working = perSlot.map((s) => ({ ...s }));
    let guard = 0;
    while (computeCapacityFromSlots(working).over && guard < 16) {
      const target = working.findIndex((s) => Number.isInteger(s.index) && s.drain > 0 && s.relation === "mismatch");
      const neutralTarget = target === -1 ? working.findIndex((s) => Number.isInteger(s.index) && s.drain > 0 && s.relation === "neutral") : -1;
      const polarize = target !== -1 ? target : neutralTarget;
      if (polarize === -1) break;
      const mod = state.manualSlots[polarize];
      // 紫卡槽也可极化（声明紫卡极性与槽一致），drain 18 → 9。
      if (!mod) break;
      working[polarize].drain = Math.max(0, Math.ceil(modBaseDrain(mod) / 2));
      working[polarize].relation = "match";
      formaNeeded += 1;
      guard += 1;
    }
    needed.hidden = !formaNeeded;
    needed.textContent = formaNeeded ? `还需极化 ×${formaNeeded}` : "";
  }
}

function computeCapacityFromSlots(perSlot) {
  const limit = weaponCapacityLimit();
  let used = 0;
  perSlot.forEach((s) => { used += s.drain || 0; });
  return { used, limit, over: used > limit };
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
  chip.title = `槽位 ${index + 1} 极性 · ${POLARITY_NAMES[pol] || pol}${info.forma ? "（已极化）" : ""}${info.relation === "mismatch" ? " · MOD 不匹配（消耗 ×1.25）" : info.relation === "match" ? " · 匹配（消耗减半）" : ""}${isRivenSlot ? " · 紫卡槽：极化即声明紫卡极性，匹配后消耗减半" : ""} · 点击切换极化`;
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
  if (!mod || mod.__riven) {
    // 空槽与紫卡槽：自由循环极化极性。紫卡自身极性以槽位极化声明——
    // 已极化的紫卡槽视为与紫卡匹配（消耗减半），与游戏内 forma 语义一致。
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
  state.formaCount = Object.keys(state.formaSlots).length;
  if (ui["forma-count"]) ui["forma-count"].textContent = String(state.formaCount);
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
  state.formaCount = Object.keys(state.formaSlots).length;
  if (ui["forma-count"]) ui["forma-count"].textContent = String(state.formaCount);
  persistActiveBuildConfig();
  renderManualSlots();
  scheduleLiveManualSimulation();
}

function autoPolarize() {
  // For every occupied slot whose mod polarity mismatches, polarize to match
  // (Overframe-style): mismatch ×1.25 → match /2. Reverse polarity stays
  // allowed as long as total capacity is not exceeded.
  const slots = weaponSlotPolarities();
  state.manualSlots.forEach((mod, index) => {
    if (!mod) return;
    const modPol = mod.__riven ? "AP_UNIVERSAL" : (state.modAssets?.mods?.[mod.path]?.polarity || mod.polarity);
    if (modPol && !polarityMatches(modPol, slots[index])) state.formaSlots[index] = modPol;
  });
  state.formaCount = Object.keys(state.formaSlots).length;
  if (ui["forma-count"]) ui["forma-count"].textContent = String(state.formaCount);
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
  const ghost = createModDragGhost(slot);
  if (ghost) event.dataTransfer.setDragImage(ghost, ghost.offsetWidth / 2, Math.min(45, ghost.offsetHeight / 2));
}
function finishModDrag() {
  modDragSource = null;
  document.querySelectorAll(".is-dragging, .is-drop-target").forEach((node) => node.classList.remove("is-dragging", "is-drop-target"));
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
  if (mod.__riven) return `riven|${mod.nameZh || ""}|${JSON.stringify(mod.stats || [])}|${common}`;
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
        const { fits, polarized } = ensureCapacityFit(index);
        if (!fits) {
          mod.rank = before;
          ensureCapacityFit(-1);
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
  const signature = JSON.stringify([payload.weapon, payload.mods, targetSlot, candidates.slice().sort()]);
  if (signature === modGainsSignature && state.modGains && Object.keys(state.modGains).length) {
    paintModGains();
    return;
  }
  try {
    const response = await fetch("/api/mod-gains", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, candidates, targetSlot }),
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
  const equipped = state.manualSlots.filter(Boolean).map((mod) => mod.__riven ? "__riven__" : mod.path);
  if (!equipped.length) { state.equippedGains = null; paintEquippedGains(); return; }
  try {
    const response = await fetch("/api/mod-gains", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, candidates: equipped, mode: "equipped" }),
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
  document.querySelectorAll("#manual-slots .game-mod-card").forEach((card) => {
    const slot = card.closest(".manual-slot");
    const index = Number(slot?.dataset.slot);
    const mod = state.manualSlots[index];
    if (!mod) return;
    const key = mod.__riven ? "__riven__" : mod.path;
    const info = gains[key];
    let badge = card.querySelector(".mod-gain-badge");
    if (!badge) {
      badge = create("div", "mod-gain-badge");
      card.append(badge);
    }
    if (!info || info.gainPercent === null || info.gainPercent === undefined) {
      badge.hidden = true;
      return;
    }
    // equipped mode returns (without - with); contribution is the negation
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
      badge.hidden = true;
      return;
    }
    const percent = Number(gainInfo.gainPercent);
    badge.hidden = false;
    badge.textContent = `${percent >= 0 ? "+" : ""}${percent.toFixed(1)}%`;
    badge.classList.toggle("is-negative", percent < 0);
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

// Dynamic polarization (manual workbench): polarization count is an OUTPUT of
// the build, not a constraint on it. When the loadout exceeds capacity, forma
// occupied slots one by one — the just-changed slot first, then the largest
// savings — until the build fits. Returns { fits, polarized }.
function ensureCapacityFit(preferIndex = -1) {
  let polarized = 0;
  let guard = 0;
  while (computeCapacity().over && guard < 16) {
    guard += 1;
    const slots = weaponSlotPolarities();
    const candidates = state.manualSlots
      .map((mod, index) => {
        if (!mod || mod.__riven) return null;
        const modPol = state.modAssets?.mods?.[mod.path]?.polarity || mod.polarity;
        if (!modPol || polarityMatches(modPol, slots[index])) return null;
        const saving = modEffectiveDrain(mod, slots[index]).drain - Math.max(0, Math.ceil(modBaseDrain(mod) / 2));
        return saving > 0 ? { index, modPol, saving } : null;
      })
      .filter(Boolean);
    if (!candidates.length) break;
    candidates.sort((a, b) => (a.index === preferIndex ? -1 : b.index === preferIndex ? 1 : b.saving - a.saving));
    state.formaSlots[candidates[0].index] = candidates[0].modPol;
    polarized += 1;
  }
  if (polarized) {
    state.formaCount = Object.keys(state.formaSlots).length;
    if (ui["forma-count"]) ui["forma-count"].textContent = String(state.formaCount);
  }
  return { fits: !computeCapacity().over, polarized };
}

function applyModToPickerSlot(mod) {
  if (state.modPickerKind !== "normal") return applySpecialMod(mod);
  const slot = state.modPickerSlot;
  if (state.manualLocks[slot]) return toast("当前槽位已锁定");
  const candidate = { ...mod, rank: ui["manual-level-toggle"]?.checked === false ? 0 : (mod.rank ?? mod.maxRank ?? 0) };
  const previous = state.manualSlots[slot] || null;
  state.manualSlots[slot] = candidate;
  const { fits, polarized } = ensureCapacityFit(slot);
  if (!fits) {
    state.manualSlots[slot] = previous;
    ensureCapacityFit(-1);
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
  syncAutoFormaFromSlots();
  renderManualSlots();
}

function modPolarity(mod) {
  return modPolarityOf(mod);
}

// The optimizer assumes matching Forma but does not return a slot map. Pair
// cards with native matching slots first, then polarize only the remaining slots.
function syncAutoFormaFromSlots() {
  const specialForma = Object.fromEntries(
    Object.entries(state.formaSlots).filter(([index]) => Number(index) >= 8 && Number(index) < 10),
  );
  const base = Array.isArray(state.buildWeapon?.polarities) ? state.buildWeapon.polarities.slice(0, 8) : [];
  const cards = state.manualSlots.filter(Boolean);
  const assigned = Array.from({ length: 8 }, () => null);
  const remaining = cards.slice();
  for (let index = 0; index < assigned.length; index += 1) {
    const polarity = base[index];
    if (!polarity || polarity === "AP_UNIVERSAL") continue;
    const match = remaining.findIndex((mod) => polarityMatches(modPolarity(mod), polarity));
    if (match >= 0) assigned[index] = remaining.splice(match, 1)[0];
  }
  for (let index = 0; index < assigned.length && remaining.length; index += 1) {
    if (!assigned[index]) assigned[index] = remaining.shift();
  }
  state.manualSlots = assigned;
  state.formaSlots = { ...specialForma };
  assigned.forEach((mod, index) => {
    const polarity = modPolarity(mod);
    if (polarity && polarity !== "AP_UNIVERSAL" && !polarityMatches(polarity, base[index])) {
      state.formaSlots[index] = polarity;
    }
  });
  state.formaCount = Object.keys(state.formaSlots).length;
  if (ui["forma-count"]) ui["forma-count"].textContent = String(state.formaCount);
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
  if (Array.isArray(read("frameArcanes"))) {
    const frames = read("frameArcanes").slice(0, 2).map((item) => hydrateRankedSelection(item, arcaneRecords(), "warframe"));
    state.frameArcanes = [frames[0] || null, frames[1] || null];
  } else if (Array.isArray(read("arcanes"))) {
    const selected = normalizeArcaneSelections(read("arcanes"));
    state.weaponArcane = hydrateRankedSelection(selected.find((item) => item.slotKind !== "warframe"), arcaneRecords(), "weapon");
    const frames = selected.filter((item) => item.slotKind === "warframe").slice(0, 2).map((item) => hydrateRankedSelection(item, arcaneRecords(), "warframe"));
    state.frameArcanes = [frames[0] || null, frames[1] || null];
  }
  const forma = read("forma");
  if (forma && typeof forma === "object") {
    const regular = Number(forma.regular || 0);
    const umbra = Number(forma.umbra || 0);
    const stance = Number(forma.stance || 0);
    state.formaCount = regular + umbra + stance;
    if (ui["forma-count"]) ui["forma-count"].textContent = String(state.formaCount);
    if (ui["forma-needed"]) {
      ui["forma-needed"].hidden = !state.formaCount;
      const summaries = [
        ["普通", regular, null],
        ["Umbra", umbra, "/assets/game/formas/UmbraForma.png"],
        ["架势", stance, "/assets/game/formas/StanceForma.png"],
      ];
      ui["forma-needed"].replaceChildren(...summaries.map(([label, count, asset]) => {
        const chip = create("span", "forma-kind-chip");
        if (asset) chip.append(imageNode(asset, "forma-kind-icon", `${label} Forma`, "eager"));
        chip.append(document.createTextNode(`${label} ×${count}`));
        return chip;
      }));
    }
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
  const target = ui["timeline-content"];
  if (!target) return;
  const points = Array.isArray(timeline?.points) ? timeline.points : (Array.isArray(timeline) ? timeline : []);
  const kill = killTimeline && Array.isArray(killTimeline.points) ? killTimeline : null;
  if (points.length < 2 && !kill) {
    target.replaceChildren(create("p", "empty-copy", "后端未返回时间线；当前只显示静态结果"));
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
  const stats = source?.moddedStats || source?.stats || {};
  const metrics = source?.metrics || source?.build || source?.killMetrics || {};
  const target = source?.targetDamage || {};
  const stat = (camel, snake = camel) => stats[camel] ?? stats[snake];
  const rows = [["面板伤害", stat("totalDamage", "total_damage")], ["平均命中", stat("averageHit", "average_hit")], ["单次伤害", target.perShot ?? metrics.shotDamage], ["持续 DPS", source?.totalSustainedDps ?? target.dps ?? stat("sustainedDps", "sustained_dps") ?? metrics.sustainedDps ?? metrics.attackDps], ["触发几率", stat("statusChance", "status_chance") == null ? null : `${(Number(stat("statusChance", "status_chance")) * 100).toFixed(1)}%`]].filter(([, value]) => value !== undefined && value !== null);
  ui["manual-result-grid"].replaceChildren(...rows.map(([label, value]) => { const item = create("div", "manual-result-item"); item.append(create("span", "", label), create("strong", "", typeof value === "number" ? formatMetric(value) : String(value))); return item; }));
  renderProbabilityVisual(source.probability || source.probabilityDistribution || {});
  renderStatusBreakdown(source);
  drawTimelineVisual(source.timeline || [], source.killTimeline || null);
  updateEnemyStatsPanel(result);
  ui["manual-results"].hidden = false;
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
  ui["build-metric"].textContent = METRIC_LABELS[state.result.metric] || state.result.metric || "战斗伤害";
  // 无限极化口径的极化次数（只展示结果）：架势/Umbra 极化在提示里细分。
  const forma = build?.forma;
  const formaEl = ui["build-forma"];
  if (formaEl) {
    if (forma && Number.isFinite(Number(forma.total))) {
      const total = Number(forma.total);
      const parts = [];
      if (forma.regular) parts.push(`常规 ×${forma.regular}`);
      if (forma.umbra) parts.push(`Umbra ×${forma.umbra}`);
      if (forma.stance) parts.push(`架势槽 ×${forma.stance}`);
      formaEl.textContent = `极化 ×${total}`;
      formaEl.title = total ? `按武器原生极性，该配装需要极化：${parts.join("、")}` : "该配装不需要极化";
      formaEl.hidden = false;
    } else {
      formaEl.hidden = true;
    }
  }
  renderMetrics(build);
  renderFireModes(build, ui["fire-mode-strip"], { interactive: true });
  renderMods(build);
  renderAnalysisStance();
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

function warframeDescription(record) {
  const lines = String(record?.descriptionZh || record?.description || record?.effect || "")
    .replace(/\\n/g, "\n")
    .replace(/<LINE_SEPARATOR>/gi, "\n")
    .replace(/<\/?DT_[A-Z_]+_COLOR>/g, "")
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

function warframeSourceLabel(record) {
  if (!record) return "";
  if (record.kind === "native") return "来源：Helminth 原生技能";
  const origin = String(record.originFrame || record.sourceFrame || "");
  const frame = warframeRows("warframes").find((row) => warframeId(row) === origin || row.path === origin);
  return frame ? `来源：${warframeName(frame)}` : (origin ? `来源：${origin.split("/").filter(Boolean).pop()}` : "来源：战甲技能");
}

function warframePassiveText(record) {
  return String(record?.passive || record?.passiveDescription || "")
    .replace(/<\/?DT_[A-Z_]+(?:_COLOR)?>/g, "")
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

function emptyWarframeSnapshot(frame = state.warframeBuild.frame) {
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
  return {
    schema: 1,
    buildLabel: state.warframeCatalog?.buildLabel || "OFFLINE",
    aura: warframeSelection(build.aura),
    exilus: warframeSelection(build.exilus),
    normalMods: build.normalMods.map(warframeSelection),
    normalLocks: build.normalLocks.map(Boolean),
    arcanes: build.arcanes.map(warframeSelection),
    shards: build.shards.map((row) => row ? { path: warframeId(row), tau: Boolean(row.tau) } : null),
    slotPolarities: {
      aura: build.slotPolarities.aura || null,
      exilus: build.slotPolarities.exilus || null,
      normal: build.slotPolarities.normal.slice(0, 8),
    },
    helminthSlot: build.helminthSlot,
    helminthAbility: build.helminthAbility ? warframeId(build.helminthAbility) : null,
    invigoration: build.invigoration.map(warframeId),
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
  build.configs[build.activeConfig] = captureWarframeConfig();
  build.store[frameId] = build.configs;
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
  renderWarframeWorkbench();
  scheduleWarframeCalculation();
}

function selectWarframeFrame(frame) {
  if (!frame) return;
  persistWarframeConfig();
  const build = state.warframeBuild;
  build.frame = frame;
  build.activeConfig = "A";
  const saved = build.store[warframeId(frame)];
  build.configs = { A: saved?.A || null, B: saved?.B || null, C: saved?.C || null };
  applyWarframeConfig(build.configs.A);
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
  build.store[warframeId(build.frame)] = build.configs;
  try { localStorage.setItem(WARFRAME_CONFIG_STORAGE_KEY, JSON.stringify(build.store)); } catch (_error) { /* private mode */ }
  if (ui["warframe-config-status"]) ui["warframe-config-status"].textContent = `已复制到配置 ${target}`;
}

function exportWarframeConfig() {
  persistWarframeConfig();
  const build = state.warframeBuild;
  const payload = {
    schema: 1,
    kind: "warframe-build",
    buildLabel: state.warframeCatalog?.buildLabel || "OFFLINE",
    frameId: warframeId(build.frame),
    configId: build.activeConfig,
    config: build.configs[build.activeConfig] || captureWarframeConfig(),
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `wf-warframe-${String(build.frame?.nameEn || "build").replace(/[^a-z0-9_-]+/gi, "-")}-${build.activeConfig}.json`;
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
      if (!config || Number(parsed.schema ?? config.schema ?? 1) !== 1) throw new Error("战甲配置 schema 不兼容");
      const build = state.warframeBuild;
      const frame = parsed.frameId ? warframeResolve(warframeRows("warframes"), parsed.frameId) : build.frame;
      if (!frame) throw new Error("导入文件中的战甲不在当前冻结目录");
      const active = build.activeConfig;
      if (warframeId(frame) !== warframeId(build.frame)) {
        persistWarframeConfig();
        build.frame = frame;
        const saved = build.store[warframeId(frame)];
        build.configs = { A: saved?.A || null, B: saved?.B || null, C: saved?.C || null };
        build.activeConfig = active;
      }
      build.configs[active] = config;
      applyWarframeConfig(config);
      persistWarframeConfig();
      if (ui["warframe-config-status"]) ui["warframe-config-status"].textContent = `已导入配置 ${active}`;
      toast(`已导入 ${warframeName(frame)} 配置 ${active}`);
    } catch (error) {
      toast(error.message || "战甲配置导入失败");
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
  ui["warframe-loading"].querySelector("p").textContent = "正在读取冻结战甲目录";
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
  const frame = state.warframeBuild.frame;
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
  const native = kind === "normal" ? frameSlotPolarities(build.frame).normal[index] : frameSlotPolarities(build.frame)[kind];
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

function modPolarityOf(mod) {
  return mod?.__riven ? null : (mod?.polarity || state.modAssets?.mods?.[mod?.path]?.polarity || null);
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
  copy.append(create("small", "arcane-slot-label", `战甲赋能 ${index + 1}`), create("strong", "", item ? warframeName(item) : "空槽位"), create("p", "arcane-slot-description", item ? warframeLocalizedDescription(item) : "未装备"));
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
  const slot = create("article", `warframe-shard-slot${item ? " is-filled" : ""}${item?.tau ? " is-tau" : ""}`);
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
  copy.append(create("small", "", `源力石 ${index + 1}`), create("strong", "", item ? warframeName(item) : "空槽位"), create("p", "", item ? warframeDescription(item) : "未安装"));
  slot.append(visual, copy);
  if (item) {
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
    kind, index, warframeId(item), Number(item?.rank ?? item?.maxRank ?? 0), item?.rarity || "", item?.tau ? 1 : 0,
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

function renderWarframeProfile() {
  const build = state.warframeBuild;
  const frame = build.frame;
  if (!frame) return;
  const frameId = warframeId(frame);
  ui["warframe-frame-select"].value = frameId;
  ui["warframe-frame-select-name"].textContent = warframeName(frame);
  ui["warframe-frame-select-description"].textContent = warframeLocalizedDescription(frame, "冻结官方战甲档案");
  const frameVisual = ui["warframe-frame-select-visual"];
  if (frameVisual) {
    frameVisual.replaceChildren();
    const portrait = frame.portraitAsset || frame.iconAsset;
    if (portrait) frameVisual.append(imageNode(portrait, "warframe-selector-icon", warframeName(frame), "lazy"));
    else frameVisual.append(create("i", "", "W"));
  }
  ui["warframe-profile-name"].textContent = warframeName(frame);
  ui["warframe-result-name"].textContent = warframeName(frame);
  ui["warframe-profile-description"].textContent = warframeLocalizedDescription(frame, "冻结官方战甲档案");
  ui["warframe-passive"].textContent = warframePassiveText(frame) || "--";
  const portrait = frame.portraitAsset || frame.iconAsset;
  ui["warframe-portrait"].hidden = !portrait;
  if (portrait) { ui["warframe-portrait"].src = portrait; ui["warframe-portrait"].alt = warframeName(frame); }
  ui["warframe-frame-caption"].textContent = `${state.warframeCatalog?.buildLabel || "OFFLINE"} · 固定满级 30`;
  ui["warframe-apply-conditionals"].checked = build.applyConditionals;
  ui["warframe-helminth-slot"].value = build.helminthSlot === null ? "" : String(build.helminthSlot);
  const replacedAbility = build.helminthSlot === null ? null : frame.abilities?.[Number(build.helminthSlot)];
  ui["warframe-helminth-slot-name"].textContent = replacedAbility ? warframeName(replacedAbility) : "不替换";
  ui["warframe-helminth-slot-description"].textContent = replacedAbility ? warframeLocalizedDescription(replacedAbility, `第 ${Number(build.helminthSlot) + 1} 个主动技能`) : "保留战甲原本的四个主动技能";
  const slotVisual = ui["warframe-helminth-slot-visual"];
  if (slotVisual) {
    slotVisual.replaceChildren();
    const icon = replacedAbility?.iconAsset || replacedAbility?.icon;
    if (icon) slotVisual.append(imageNode(icon, "warframe-selector-icon", warframeName(replacedAbility), "lazy"));
    else slotVisual.append(create("i", "", "—"));
  }
  ui["warframe-helminth-ability"].value = build.helminthAbility ? warframeId(build.helminthAbility) : "";
  ui["warframe-helminth-ability-open"].disabled = build.helminthSlot === null;
  ui["warframe-helminth-ability-name"].textContent = build.helminthAbility ? warframeName(build.helminthAbility) : "选择技能";
  ui["warframe-helminth-ability-source"].textContent = build.helminthAbility ? warframeSourceLabel(build.helminthAbility) : "先选择替换技能槽";
  const helminthVisual = ui["warframe-helminth-ability-visual"];
  if (helminthVisual) {
    helminthVisual.replaceChildren();
    const icon = build.helminthAbility?.iconAsset;
    if (icon) helminthVisual.append(imageNode(icon, "warframe-selector-icon", warframeName(build.helminthAbility), "lazy"));
    else helminthVisual.append(create("i", "", "H"));
  }
  ui["warframe-helminth-description"].textContent = build.helminthAbility ? warframeLocalizedDescription(build.helminthAbility, "该技能只替换一个主动技能槽。") : "未替换技能。";
  ui["warframe-invigoration-name"].textContent = build.invigoration.length ? build.invigoration.map(warframeName).join(" + ") : "未选择";
  ui["warframe-invigoration-description"].textContent = build.invigoration.length ? build.invigoration.map((row) => warframeLocalizedDescription(row, "冻结静态增幅")).join("；") : "一项攻势 + 一项辅助";
  ui["warframe-config-tabs"].querySelectorAll("[data-warframe-config]").forEach((button) => {
    const active = button.dataset.warframeConfig === build.activeConfig;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-selected", String(active));
  });
}

function renderWarframeWorkbench() {
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
    ...(build.frame?.abilities || []).slice(0, 4).map((ability, slot) => ({ ...ability, id: `helminth-slot-${slot}`, slot })),
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
    const sub = kind === "helminth" ? warframeSourceLabel(row) : kind === "helminthSlot" ? (row.slot === null ? "保留原技能" : `原技能 ${Number(row.slot) + 1}`) : (kind === "frame" ? "固定满级 30 · 冻结官方档案" : (row.tau ? "Tau 级" : (row.rarity || row.category || "静态效果")));
    copy.append(create("strong", "", warframeName(row)), create("small", "", sub), create("p", "", warframeDescription(row) || "冻结游戏数据"));
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
  } else ui["warframe-picker-sub"].textContent = `${rows.length} 条可选记录`;
}

function warframePickerRowsForCategory(kind, category) {
  if (!category || category === "all") return warframePickerRowsBase();
  return warframePickerRowsBase().filter((row) => warframeCategoryMatches(row, category));
}

function openWarframePicker(kind, slot = 0) {
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
    frameId: warframeId(build.frame),
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

function warframeEffectLabel(effect) {
  const stat = String(effect?.stat || effect?.label || effect?.source || "");
  const labels = {
    AVATAR_HEALTH_MAX: "生命值", AVATAR_SHIELD_MAX: "护盾", AVATAR_ARMOUR: "护甲", AVATAR_ARMOR: "护甲", AVATAR_POWER_MAX: "最大能量",
    AVATAR_ABILITY_STRENGTH: "技能强度", AVATAR_ABILITY_DURATION: "技能持续", AVATAR_ABILITY_RANGE: "技能范围", AVATAR_ABILITY_EFFICIENCY: "技能效率",
    AVATAR_POWER_RATE: "能量恢复", AVATAR_ENERGY_REGEN: "能量恢复", AVATAR_HEALTH_REGEN: "生命恢复", AVATAR_CASTING_SPEED: "施法速度", AVATAR_PARKOUR_BOOST: "跑酷速度",
    health: "生命值", shield: "护盾", armor: "护甲", energy: "最大能量", sprint: "冲刺速度", abilityStrength: "技能强度", abilityDuration: "技能持续", abilityRange: "技能范围", abilityEfficiency: "技能效率", energyRegen: "能量恢复", healthRegen: "生命恢复", castingSpeed: "施法速度", parkour: "跑酷速度",
  };
  return labels[stat] || labels[stat.toUpperCase()] || String(effect?.label || stat).replace(/^AVATAR_/, "").replaceAll("_", " ") || "效果";
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
  const stats = [
    ["health", "生命值"], ["shield", "护盾"], ["armor", "护甲"], ["energy", "能量"], ["sprint", "冲刺速度"],
    ["abilityStrength", "技能强度"], ["abilityDuration", "技能持续"], ["abilityRange", "技能范围"], ["abilityEfficiency", "技能效率"], ["damageReduction", "护甲减伤"], ["ehp", "生命等效 EHP"],
  ];
  ui["warframe-panel-grid"].replaceChildren(...stats.map(([key, label]) => {
    const cell = create("div", "warframe-panel-stat");
    const finalValue = warframePanelValue(key, final[key]);
    const baseValue = ["abilityStrength", "abilityDuration", "abilityRange", "abilityEfficiency"].includes(key) ? "100%" : warframePanelValue(key, base[key]);
    cell.append(create("span", "", label), create("strong", "", finalValue), create("small", "", `基础 ${baseValue}`));
    if (finalValue !== baseValue) cell.classList.add("is-changed");
    return cell;
  }));
  const effects = Array.isArray(result.activeEffects) ? result.activeEffects : [];
  ui["warframe-active-effects"].replaceChildren(...(effects.length ? effects.map((effect) => {
    const row = create("span", "warframe-active-effect");
    row.append(create("strong", "", warframeEffectLabel(effect)), document.createTextNode(effect.condition ? ` · ${effect.condition}` : ""));
    return row;
  }) : [create("p", "empty-copy", "当前没有直接改变面板的已启用效果")])) ;
  const globalScale = `强度 ${warframePanelValue("abilityStrength", final.abilityStrength)} · 持续 ${warframePanelValue("abilityDuration", final.abilityDuration)} · 范围 ${warframePanelValue("abilityRange", final.abilityRange)} · 效率 ${warframePanelValue("abilityEfficiency", final.abilityEfficiency)}`;
  const sourceAbilities = Array.isArray(state.warframeBuild.frame?.abilities) ? state.warframeBuild.frame.abilities : [];
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
    card.append(head, create("p", "warframe-ability-description", warframeAbilityDescription(ability) || "官方描述随冻结数据展示。"));
    const scalarList = create("div", "warframe-ability-scalars");
    const cost = ability.energyCost || {};
    const scalars = Array.isArray(ability.scalars) ? ability.scalars : [];
    const hasEnergyFields = scalars.some((scalar) => scalar.isEnergy || /energy cost|energy drain/i.test(String(scalar.label || "")));
    const hasExtraCostFields = ["perTarget", "perShot", "chargedShot", "perAllyPerSecond", "perEnemyPerSecond", "perAbilityPerSecond", "airborneActivation"].some((key) => Number.isFinite(Number(cost[key]))) || String(cost.resource || "energy") !== "energy";
    if (!hasEnergyFields || hasExtraCostFields) {
      const costDisplay = warframeAbilityCost(cost);
      const costRow = create("div", `warframe-ability-energy is-${String(cost.resource || "energy").replace(/[^a-z]/gi, "")}`);
      costRow.append(create("span", "", costDisplay.label), create("strong", "", costDisplay.text), create("small", "", costDisplay.note || (costDisplay.base ? `基础 ${costDisplay.base}` : "冻结官方资源规则")));
      scalarList.append(costRow);
    }
    let currentGroup = "";
    if (scalars.length) scalars.forEach((scalar) => {
      if (hasExtraCostFields && scalar.isEnergy && /energy cost/i.test(String(scalar.label || "")) && Number(scalar.value) === 0) return;
      const group = String(scalar.group || "").trim();
      if (group && group !== currentGroup) {
        scalarList.append(create("p", "warframe-ability-scalar-group", group));
        currentGroup = group;
      }
      const row = create("div", [scalar.isStatic || scalar.scale === "none" ? "is-static" : "", scalar.isEnergy ? "is-energy" : "", scalar.scale === "range" ? "is-range" : ""].filter(Boolean).join(" "));
      row.append(create("span", "", warframeScalarLabel(scalar)), create("strong", "", warframeScalarValueText(scalar)), create("small", "", `${warframeScalarScaleLabel(scalar.scale)} · 基础 ${warframeScalarBaseText(scalar)}`));
      scalarList.append(row);
    });
    else {
      const evidence = Array.isArray(ability.sourceEvidence) ? ability.sourceEvidence : [];
      const sources = [...new Set(evidence.map((entry) => entry?.kind === "wiki" ? "Wiki" : entry?.kind === "packages" ? "游戏包" : "冻结资料").filter(Boolean))];
      scalarList.append(create("p", "", `官方描述已保留${sources.length ? ` · 来源 ${sources.join(" / ")}` : ""}`));
      const unresolved = Array.isArray(ability.unresolvedFields) ? ability.unresolvedFields.filter(Boolean) : [];
      if (unresolved.length) scalarList.append(create("small", "warframe-ability-diagnostic", unresolved.join("；")));
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
    const frame = state.warframeBuild.frame;
    Object.assign(state.warframeBuild, emptyWarframeSnapshot(frame), { frame, activeConfig: state.warframeBuild.activeConfig, configs: state.warframeBuild.configs, store: state.warframeBuild.store, result: null });
    renderWarframeWorkbench();
    persistWarframeConfig();
    scheduleWarframeCalculation();
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

function refreshBuildMetrics() {
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
  for (const tier of tiers) {
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
      const detail = create("small", "", option.description);
      copy.append(title, detail);
      if (option.unsupported?.length) copy.append(create("em", "", option.unsupported.join("；")));
      label.append(input, copy);
      options.append(label);
    }
    field.append(legend, options);
    return field;
  }));
}

function selectBuildWeapon(weapon, writeInput = true) {
  if (state.buildWeapon && state.buildWeapon.path !== weapon?.path) persistActiveBuildConfig();
  state.buildWeapon = weapon;
  state.buildResult = null;
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
  state.formaCount = 0;
  if (ui["forma-count"]) ui["forma-count"].textContent = "0";
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
  const enh = sim.enemyEnhancements || result?.enemyEnhancements || {};
  const tags = [];
  if (enh.eximus) tags.push("卓越者");
  if (enh.empowered) tags.push(`强化·${enh.playerCount || 1}人`);
  if (enh.archimedea) tags.push("科研超宏");
  if (ui["build-steel-path"]?.checked) tags.push("钢铁之路");
  const ctx = ui["build-enemy-stats-context"];
  if (ctx) ctx.textContent = [`Lv ${ui["build-enemy-level"]?.value || 160}`, ...tags].join(" · ");
  panel.hidden = false;
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
  if (damageModel === "custom" && !customDamageSupported()) throw new Error("当前后端未支持自定义防御快照");
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
      ["装填", value("reloadTime", "reload_time"), (value) => `${value.toFixed(2)}s`],
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
    ...normalizeLabels(result.unsupported).map((item) => `未完整支持：${item}`),
    ...normalizeLabels(result.skipped).map((item) => `计算说明：${item}`),
    ...normalizeLabels(result.limitations).map((item) => `限制：${item}`),
  ];
  const unique = [...new Set(lines)];
  ui["weapon-build-diagnostic-count"].textContent = String(unique.length);
  ui["weapon-build-diagnostic-list"].replaceChildren(...(unique.length ? unique.map((line) => create("p", "", line)) : [create("p", "", "本次计算没有额外诊断项")]));
}

function renderWeaponBuild(result) {
  const weapon = state.buildWeapon;
  const build = resultBuildView(result);
  ui["weapon-build-type"].textContent = `${TYPE_LABELS[weapon.weaponType] || weapon.weaponType} BUILD`;
  ui["weapon-build-name"].textContent = weaponName(weapon);
  ui["weapon-build-fire-mode"].textContent = ui["build-fire-mode-select"].selectedOptions[0]?.textContent || `模式 ${Number(result.fireMode) + 1}`;
  const archetype = result.buildArchetype || build.buildArchetype || result.selection?.buildArchetype || "";
  if (ui["weapon-build-archetype"]) {
    ui["weapon-build-archetype"].hidden = !archetype;
    ui["weapon-build-archetype"].textContent = archetype ? `流派 ${archetype}` : "";
  }
  const innate = result.innateElement;
  const innateText = innate ? `自带${DAMAGE_TYPE_LABELS[innate.damageType] || innate.damageType} ${(Number(innate.percent || innate.value * 100)).toFixed(0)}%` : "无自带元素";
  ui["weapon-build-element-note"].textContent = `${result.elementTarget ? `元素目标：${result.elementTarget.label}（配装包含）` : "未限定元素"} · ${innateText}`;
  ui["weapon-build-slot-summary"].textContent = `${result.slotCount ?? Number(ui["build-slot-count"]?.value || 8)} SLOTS`;
  ui["weapon-build-build-label"].textContent = result.buildLabel || "OFFLINE";
  updateLiveHud(result);
  renderWeaponStats(result.moddedStats);
  renderMetrics(build, ui["weapon-build-damage-metrics"], weapon);
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
    option.append(
      create("strong", "", enemy.displayName || enemy.nameZh || enemy.nameEn || enemy.nameInternal),
      create("span", "", `${factionGroup(enemy.faction)} · 基础等级 ${enemy.baseLevel}${headText ? ` · ${headText}` : ""}`),
      defenseChipRow(enemy),
    );
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

async function submitWeaponBuild(event, live = false) {
  event?.preventDefault();
  let payload;
  try {
    payload = buildPayloadFromForm();
  } catch (error) {
    showBuildMessage(issueLabel(error.message));
    toast(issueLabel(error.message));
    return;
  }
  showBuildMessage("");
  const requestId = ++state.liveRequestId;
  if (!state.buildResult || !live) setWeaponBuildState("loading");
  if (live) markLiveHudSolving();
  try {
    const response = await fetch(state.buildInputMode === "manual" ? "/api/simulate" : "/api/build", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const body = await response.json();
    if (!response.ok) throw new Error(body?.error?.message || `配装失败（${response.status}）`);
    if (requestId !== state.liveRequestId) return;
    state.buildResult = body;
    renderWeaponBuild(body);
    setWeaponBuildState("content");
  } catch (error) {
    if (requestId === state.liveRequestId) {
      const message = issueLabel(error.message) || "配装失败";
      ui["weapon-build-error-message"].textContent = message;
      if (live) {
        // Keep the last good numbers on screen but surface the failure clearly.
        ui["live-hud-pulse"]?.classList.remove("is-solving");
        toast(`实时解算失败：${message}`);
      } else {
        setWeaponBuildState("error");
      }
    }
  }
}

function diagnosticLines() {
  const lines = [];
  for (const item of normalizeLabels(state.result.unsupported)) lines.push(`未完整支持：${item}`);
  for (const item of normalizeLabels(state.result.skipped)) lines.push(`未计入：${item}`);
  if (state.result.incarnonPolicy) lines.push(`灵化策略：${typeof state.result.incarnonPolicy === "string" ? state.result.incarnonPolicy : JSON.stringify(state.result.incarnonPolicy)}`);
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

function toast(message) {
  const node = create("div", "toast", message);
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
  ui["sample-button"].addEventListener("click", sample);
  ui["reset-button"].addEventListener("click", reset);
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
    state.formaCount = 0;
    if (ui["forma-count"]) ui["forma-count"].textContent = "0";
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
      fillManualFromResult(body);
      // Auto-polarize to the solved build (Overframe behaviour): green slots.
      autoPolarize();
      persistActiveBuildConfig();
      scheduleLiveManualSimulation();
      toast("已回填最优配装并自动极化");
    } catch (error) {
      toast(issueLabel(error.message) || "求解失败");
    } finally {
      button.disabled = false;
      button.innerHTML = originalLabel;
      if (state.buildInputMode !== previousMode) setBuildModeUI(previousMode);
    }
  });
  ui["forma-increase"]?.addEventListener("click", () => {
    // +1 极化: auto-polarize the next mismatched occupied slot
    const slots = weaponSlotPolarities();
    const target = state.manualSlots.findIndex((mod, index) => {
      if (!mod) return false;
      const modPol = mod.__riven ? null : (state.modAssets?.mods?.[mod.path]?.polarity || mod.polarity);
      return modPol && !polarityMatches(modPol, slots[index]);
    });
    if (target === -1) return toast("没有需要极化的槽位");
    const mod = state.manualSlots[target];
    setSlotPolarity(target, state.modAssets?.mods?.[mod.path]?.polarity || mod.polarity);
    toast(`槽位 ${target + 1} 已极化`);
  });
  ui["forma-decrease"]?.addEventListener("click", () => {
    const keys = Object.keys(state.formaSlots).map(Number).sort((a, b) => b - a);
    if (!keys.length) return toast("没有可撤销的极化");
    const last = keys[0];
    delete state.formaSlots[last];
    state.formaCount = keys.length - 1;
    if (ui["forma-count"]) ui["forma-count"].textContent = String(state.formaCount);
    persistActiveBuildConfig();
    renderManualSlots();
    scheduleLiveManualSimulation();
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
  ui["build-headshot-chance"].addEventListener("input", () => { refreshScenarioLabels(); scheduleLiveManualSimulation(); });
  ui["build-damage-model"]?.addEventListener("change", () => {
    updateCustomDamageControls();
    if (ui["build-damage-model"].value === "custom" && !customDamageSupported()) showBuildMessage("当前后端未支持自定义防御快照");
    else showBuildMessage("");
  });
  ui["build-enemy-search"]?.addEventListener("input", fillBuildEnemies);
  ui["build-enemy-empowered"]?.addEventListener("change", syncEmpoweredPlayerCount);
  ui["arcane-picker-search"]?.addEventListener("input", renderArcanePicker);
  ui["arcane-picker-close"]?.addEventListener("click", closeArcanePicker);
  bindWarframeEvents();
  ui["weapon-build-form"]?.addEventListener("input", () => { updateCustomDamageControls(); persistActiveBuildConfig(); scheduleLiveManualSimulation(); });
  ui["weapon-build-form"]?.addEventListener("change", () => { persistActiveBuildConfig(); scheduleLiveManualSimulation(); });
  ui["weapon-build-form"].addEventListener("submit", submitWeaponBuild);
  if (matchMedia("(pointer: fine)").matches) {
    ui["riven-stage"].addEventListener("pointermove", (event) => {
      const bounds = ui["riven-stage"].getBoundingClientRect();
      const x = (event.clientX - bounds.left) / bounds.width - 0.5;
      const y = (event.clientY - bounds.top) / bounds.height - 0.5;
      ui["riven-card"].style.transform = `rotateX(${(-y * 5).toFixed(2)}deg) rotateY(${(x * 7).toFixed(2)}deg) translateY(-2px)`;
    });
    ui["riven-stage"].addEventListener("pointerleave", () => { ui["riven-card"].style.transform = ""; });
  }
}

async function bootstrap() {
  try {
    state.buildStore = readBuildStore();
    const [catalogResponse, assetsResponse] = await Promise.all([fetch("/api/catalog?v=20260831h"), fetch("/assets/mods/index.json?v=20260831h")]);
    if (!catalogResponse.ok) throw new Error("本地目录加载失败");
    state.catalog = await catalogResponse.json();
    state.modAssets = assetsResponse.ok ? await assetsResponse.json() : null;
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
    ui["footer-schema"].textContent = `SCHEMA ${state.catalog.schemaVersion}`;
    ui["health-label"].textContent = "本地引擎已连接";
    ui["health-dot"].classList.add("is-live");
    bindEvents();
    setBuildModeUI(state.buildInputMode);
    renderExternalBuffs();
    reset();
    const buildWeapon = state.catalog.weapons.find((entry) => entry.buildAvailable && entry.nameEn === "Boltor Prime")
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
