/* Only migrate server-verified, previously admitted unreleased identities.
 * The original entry stays in the config/export; API validation remains strict.
 */
function migrateLegacyBuildConfig(config, replacements) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) return { config, changes: [] };
  const changes = [];
  const label = (rule) => rule.nameZh && !rule.nameZh.includes('\uFFFD') ? rule.nameZh : (rule.nameEn || rule.path);
  const next = { ...config };
  const lookup = (path) => typeof path === 'string' && Object.hasOwn(replacements || {}, path) ? replacements[path] : null;
  const ranked = (item, field, slot) => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return item;
    const rule = lookup(item.path);
    if (!rule || rule.reason !== 'unreleased-tier-clone' || typeof rule.path !== 'string' || !Number.isInteger(rule.maxRank) || rule.maxRank < 0) return item;
    // Leave malformed ranks for the ordinary validator instead of guessing.
    const requested = item.rank == null ? rule.maxRank : item.rank;
    if (!Number.isInteger(requested) || requested < 0) return item;
    const replacement = { ...item, path: rule.path, rank: Math.min(requested, rule.maxRank) };
    changes.push({ field, slot, from: { ...item }, to: { ...replacement }, label: label(rule) });
    return replacement;
  };
  if (Array.isArray(config.mods)) next.mods = config.mods.map((item, index) => ranked(item, 'mods', Number.isInteger(item?.slot) ? item.slot : index));
  if (config.exilus) next.exilus = ranked(config.exilus, 'exilus', null);
  for (const field of ['requiredMods', 'forbiddenMods']) {
    if (!Array.isArray(config[field])) continue;
    next[field] = [...new Set(config[field].map((path) => {
      const rule = lookup(path);
      if (!rule || rule.reason !== 'unreleased-tier-clone' || typeof rule.path !== 'string') return path;
      changes.push({ field, from: path, to: rule.path, label: label(rule) });
      return rule.path;
    }))];
  }
  if (!changes.length) return { config, changes };
  next.legacyModMigrations = [...(Array.isArray(config.legacyModMigrations) ? config.legacyModMigrations : []), ...changes];
  return { config: next, changes };
}

function legacyModMigrationMessage(history) {
  if (!Array.isArray(history) || !history.length) return '';
  const entries = history.filter((change) => change && typeof change === 'object' && ['mods', 'exilus', 'requiredMods', 'forbiddenMods'].includes(change.field));
  if (!entries.length) return '';
  const details = entries.map((change) => {
    const location = change.field === 'mods' ? `第 ${Number(change.slot) + 1} 槽` : ({ exilus: '特殊槽', requiredMods: '必选限制', forbiddenMods: '禁用限制' }[change.field] || 'MOD');
    const rank = change.to && typeof change.to === 'object' ? `，等级 ${change.from?.rank ?? '默认'} → ${change.to.rank}` : '';
    return `${location}：${change.label || 'MOD'}${rank}`;
  });
  return `旧配置中的未发布 MOD 变体已替换为正式版本（${details.join('；')}）。超出正式上限的等级已调整，数值将重新计算；原始路径与等级保留在导出 JSON 的 legacyModMigrations 中。`;
}
