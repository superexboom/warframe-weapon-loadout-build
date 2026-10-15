/* Only migrate server-verified, previously admitted unreleased identities.
 * Silent for the user; API validation of direct requests remains strict.
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
  if (!changes.length && !Object.hasOwn(config, 'legacyModMigrations')) return { config, changes };
  // Older saves carried an audit trail of these swaps; it means nothing to the user.
  delete next.legacyModMigrations;
  return { config: next, changes };
}
