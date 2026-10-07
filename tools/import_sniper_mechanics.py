"""Import sniper Shot Combo and zoom-buff data, with provenance.

Primary source: the game packages of the pinned build (``SniperImpactBehavior``
combo fields and ``ZoomLevels[].Upgrades`` per weapon, inheritance resolved).
WFSim's weapon YAML (``sniper_combo:`` / ``scope:``) is read as an independent
cross-check; a weapon WFSim declares but whose packages carry no equivalent is
imported from the YAML and marked ``source: wfsim-yaml``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from wfarsenal.packages import PackageIndex, load  # noqa: E402

# Zoom upgrades that are pure buffs with an existing damage bucket. A zoom
# level carrying anything else is a stat trade (Komorex) and is not imported.
ZOOM_BUFF_TYPES = {'WEAPON_CRIT_DAMAGE', 'WEAPON_CRIT_CHANCE', 'WEAPON_HEADSHOT_MULTIPLIER'}
SCOPE_FIELDS = {  # WFSim ScopeSpec field -> (upgradeType, operation)
    'crit_multiplier': ('WEAPON_CRIT_DAMAGE', 'STACKING_MULTIPLY'),
    'crit_chance': ('WEAPON_CRIT_CHANCE', 'STACKING_MULTIPLY'),
    'crit_chance_post_mod': ('WEAPON_CRIT_CHANCE', 'ADD'),
    'headshot_damage': ('WEAPON_HEADSHOT_MULTIPLIER', 'STACKING_MULTIPLY'),
}


def _index(build: Path) -> PackageIndex:
    parents = build / 'parents.json'
    if parents.is_file():
        index = PackageIndex(build / 'packages')
        index.parents = json.loads(parents.read_text(encoding='utf-8-sig'))
        return index
    return load(build)


def _sha(index: PackageIndex, path: str) -> str | None:
    for suffix in ('.json', '.txt'):
        f = index.root / (path.lstrip('/') + suffix)
        if f.is_file():
            return hashlib.sha256(f.read_bytes()).hexdigest()
    return None


def _owner(index: PackageIndex, path: str, key: str, inner: str | None = None) -> str | None:
    """Most-derived package in the ancestry that declares ``key``."""
    for ancestor in index.ancestry(path):
        own = index.get(ancestor) or {}
        if inner is None and key in own:
            return ancestor
        if inner is not None and any(isinstance(b, dict) and inner in json.dumps(b) for b in own.get(key) or ()):
            return ancestor
    return None


def _combo(resolved: dict) -> dict | None:
    rows = []
    for i, behavior in enumerate(resolved.get('Behaviors') or ()):
        impact = behavior.get('impact:SniperImpactBehavior') if isinstance(behavior, dict) else None
        if isinstance(impact, dict) and 'BaseHitCount' in impact:
            rows.append((i, impact))
    live = [(i, b) for i, b in rows
            if int(b.get('ComboHitsAlwaysEnabled') or 0) == 0 and int(b.get('ComboDecayEnabled') or 0) == 1]
    if not live:
        return None
    _, b = live[0]
    if b.get('HitReqNextTierOperationType') != 'HTO_MULTIPLICATIVE':
        raise ValueError('unsupported combo tier operation: ' + str(b.get('HitReqNextTierOperationType')))
    return dict(
        min=int(b['BaseHitCount']),
        tierBonus=float(b['BaseHitMultipler']),
        tierFactor=float(b['HitReqNextTierOperator']),
        seconds=float(b['TimeBetweenHits']),
        timeOverDecay=bool(int(b.get('ComboTimeOverDecay') or 0)),
        missDecay=bool(int(b.get('ComboMissDecay') or 0)),
        behaviors=[i for i, _ in live],
        native={k: b.get(k) for k in ('ComboHitsAlwaysEnabled', 'BaseHitCount', 'BaseHitMultipler',
                                      'HitReqNextTierOperator', 'HitReqNextTierOperationType', 'TimeBetweenHits',
                                      'ComboDecayEnabled', 'ComboMissDecay', 'ComboTimeOverDecay', 'TimeUpgrade')},
    )


def _zoom(resolved: dict) -> dict | None:
    levels = resolved.get('ZoomLevels') or []
    native = [dict(magnification=z.get('aimFOVMultiplier'),
                   upgrades=[dict(upgradeType=u.get('UpgradeType'), operation=u.get('OperationType'),
                                  value=round(float(u.get('Value')), 6), damageType=u.get('DamageType'))
                             for u in z.get('Upgrades') or ()]) for z in levels]
    # A scope sits at its top level while aiming: the zoom buffs are free.
    for index in range(len(native) - 1, -1, -1):
        ups = native[index]['upgrades']
        if ups and all(u['upgradeType'] in ZOOM_BUFF_TYPES for u in ups):
            return dict(level=index, magnification=native[index]['magnification'], effects=ups, levels=native)
    if any(z['upgrades'] for z in native):
        return dict(level=None, effects=[], levels=native, excluded='zoom-stat-trade-unmodeled')
    return None


def _snake(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def _wfsim(wfsim: Path) -> dict[str, dict]:
    rows = {}
    for f in sorted((wfsim / 'weapons').rglob('*.yaml')):
        doc = yaml.safe_load(f.read_text(encoding='utf-8'))
        if not isinstance(doc, dict) or not (doc.get('sniper_combo') or doc.get('scope')):
            continue
        rows[doc.get('id') or f.stem] = dict(file=f.relative_to(wfsim).as_posix(),
                                             internal=doc.get('internal_name'),
                                             sniperCombo=doc.get('sniper_combo'), scope=doc.get('scope'),
                                             sha256=hashlib.sha256(f.read_bytes()).hexdigest())
    return rows


def _scope_effects(scope: dict) -> list[dict]:
    return [dict(upgradeType=t, operation=op, value=float(scope[k]), damageType='DT_ANY')
            for k, (t, op) in SCOPE_FIELDS.items() if scope.get(k)]


def _agrees(entry: dict, ref: dict) -> list[str]:
    out = []
    combo, want = entry.get('combo'), ref.get('sniperCombo')
    if bool(combo) != bool(want):
        out.append('combo presence')
    elif combo:
        if combo['min'] != want.get('min'):
            out.append('combo min')
        if abs(combo['seconds'] - float(want.get('seconds', 2.0))) > 1e-6:
            out.append('combo seconds')
    mine = sorted((e['upgradeType'], e['operation'], round(e['value'], 4)) for e in (entry.get('zoom') or {}).get('effects') or ())
    theirs = sorted((e['upgradeType'], e['operation'], round(e['value'], 4)) for e in _scope_effects(ref.get('scope') or {}))
    if mine != theirs:
        out.append('scope effects')
    return out


def build(build: Path, export: Path, wfsim: Path) -> dict:
    index = _index(build)
    weapons = json.loads((export / 'weapons.json').read_text(encoding='utf-8'))['data']
    reference = _wfsim(wfsim)
    by_internal = {r['internal']: (k, r) for k, r in reference.items() if r.get('internal')}
    entries, used = {}, set()
    for w in weapons:
        path = w.get('path')
        if not path or w.get('slot') not in ('primary', 'secondary'):
            continue
        sniper = any('SniperRifle' in a for a in w.get('ancestry') or ())
        try:
            resolved = index.resolve(path)
        except ValueError:
            continue
        combo = _combo(resolved) if sniper else None
        zoom = _zoom(resolved)
        if zoom and not sniper and zoom.get('effects'):
            zoom['aimGated'] = True
        key, ref = by_internal.get(path) or next(
            ((k, r) for k, r in reference.items() if k == _snake(w.get('nameEn') or '')), (None, None))
        if not combo and not (zoom and zoom.get('effects')) and not ref:
            continue
        entry = dict(name=w.get('nameEn'), sniper=sniper, source='game-packages',
                     packageBuild=build.name, combo=combo, zoom=zoom)
        sources = {p for p in (_owner(index, path, 'ZoomLevels') if zoom else None,
                               _owner(index, path, 'Behaviors', 'SniperImpactBehavior') if combo else None) if p}
        entry['packageSources'] = [dict(path=p, sha256=_sha(index, p)) for p in sorted(sources)]
        if ref:
            used.add(key)
            entry['wfsim'] = dict(id=key, **{k: v for k, v in ref.items() if k != 'internal'})
            entry['wfsim']['disagrees'] = _agrees(entry, ref)
            if not combo and not (zoom and zoom.get('effects')):
                # Packages carry no equivalent (e.g. a Lua-side aim bonus).
                entry['source'] = 'wfsim-yaml'
                entry['combo'] = (dict(min=int(ref['sniperCombo']['min']), tierBonus=.5, tierFactor=3.,
                                       seconds=float(ref['sniperCombo'].get('seconds', 2.)))
                                  if ref.get('sniperCombo') else None)
                entry['zoom'] = (dict(level=None, magnification=(ref.get('scope') or {}).get('magnification'),
                                      effects=_scope_effects(ref['scope']), aimGated=not sniper)
                                 if ref.get('scope') else None)
                entry['wfsim']['disagrees'] = []
        entries[path] = entry
    return dict(
        schemaVersion=1,
        packageBuild=build.name,
        exportBuild=json.loads((export / 'weapons.json').read_text(encoding='utf-8')).get('buildLabel'),
        semantics=dict(
            combo='multiplier(hits)=1 below min, else 1+tierBonus*(1+k) where k=max tier with hits>=min*tierFactor^k; '
                  'read before the hit is counted; one count per landing direct pellet; loses 1 per `seconds` without a landing hit; '
                  'multiplies direct and radial hit damage, not the status payload; paid only scoped in, never in an Incarnon form',
            zoom='top zoom level whose upgrades are all buffs; injected as engine effects with the native upgrade operation '
                 '(STACKING_MULTIPLY joins the mod bucket, ADD is flat after mods); snipers are evaluated scoped, other weapons '
                 'only when the scenario is aiming; Incarnon forms receive none',
            reference='WFSim engine/src/model/weapon.rs SniperCombo, fight/run.rs combo_at, fight/pellet.rs, '
                      'build/loadout/resolve.rs (scope)'),
        wfsimUnmatched=sorted(set(reference) - used),
        weapons=dict(sorted(entries.items())),
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build', type=Path, required=True, help='WF_Rever data/raw/<buildLabel> directory')
    ap.add_argument('--export', type=Path, default=ROOT / 'data/export/2026.08.13.13.24')
    ap.add_argument('--wfsim', type=Path, required=True, help='WFSim data/ directory')
    ap.add_argument('--out', type=Path, default=ROOT / 'data/mechanics/sniper-mechanics.json')
    a = ap.parse_args()
    doc = build(a.build, a.export, a.wfsim)
    a.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    bad = {p: e['wfsim']['disagrees'] for p, e in doc['weapons'].items() if (e.get('wfsim') or {}).get('disagrees')}
    print('weapons:', len(doc['weapons']), 'wfsim disagreements:', bad, 'wfsim unmatched:', doc['wfsimUnmatched'])


if __name__ == '__main__':
    main()
