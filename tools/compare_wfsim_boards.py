"""Capture public board leaders and cross-score Portable builds on a pinned WFSim runtime.

prepare: fetch/map rows; run: isolated local solves and current-engine replays.
No board submission, cache baking or external writes are performed.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time
import traceback
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
COMPARISON_VERSION = 3


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    temporary.replace(path)


def archive_previous(path):
    if path.exists():
        path.replace(path.with_name(path.stem + '.previous-' + str(time.time_ns()) + '.json'))


def record_of(weapon, row):
    record = {k: deepcopy(row[k]) for k in ('mods', 'arcanes', 'evolutions', 'valence', 'exilus', 'grip', 'loader', 'wielder') if k in row}
    record['weapon'] = weapon
    riven = row.get('riven')
    if riven:
        record.update(riven_pos=list(riven['bonuses']), riven_neg=riven.get('malus') or '', riven_rolls=list(riven['rolls']))
    return record


def fetch_board(runtime, weapon):
    if not re.fullmatch(r'[a-z0-9_]+', weapon):
        raise ValueError('invalid weapon id')
    path = runtime / 'boards' / (weapon + '.json')
    if not path.exists():
        request = Request('https://cdn.wfsim.app/board/' + weapon + '.json', headers={'User-Agent': 'WF-Riven-comparison/1.0'})
        with urlopen(request, timeout=40) as response:
            raw = response.read()
        data = json.loads(raw)
        if not isinstance(data, list):
            raise ValueError('board response is not an array')
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    return read(path), hashlib.sha256(path.read_bytes()).hexdigest()


class Mapper:
    def __init__(self, runtime):
        import app
        from tools.compare_archgun_board_builds import registry
        from tools.wfsim_native_reference import NativeReference, WasmReference
        from tools.fetch_wfsim_runtime import extract_data_pack
        self.app, self.runtime = app, runtime
        app._disable_analysis_statics_persistence()
        self.release = read(runtime / 'site/release.json')
        library = runtime / 'native' / (self.release['engine'] + '-sfe2-v3.dll')
        self.reference_manifest = dict(engine=self.release['engine'])
        if library.exists():
            manifest = read(library.with_name(library.name + '.build.json'))
            self.reference = NativeReference(library, self.release['engine'], manifest['sha256'])
            self.reference_manifest.update(library=library.name, library_sha256=self.reference.sha256)
        else:
            self.reference = WasmReference(runtime)
        if not (runtime / 'data/weapons').is_dir():
            extract_data_pack(runtime, self.release)
        self.tables = {kind: registry(runtime / 'data' / kind) for kind in ('weapons', 'mods', 'arcanes', 'evolutions', 'enemies')}
        meta_path = runtime / 'meta-ready.json'
        if not meta_path.exists():
            write(meta_path, self.reference.call('/api/meta', {}))
        self.meta = read(meta_path)
        self.stances = {row['path']: row for row in app.STANCE_ROWS}
        self.reverse_mods, self.reverse_arcanes = {}, {}
        mod_records = {r['path']: r for r in app.EXPORTS['mods']}
        mod_records.update(app.UTILITY_MODS_BY_PATH)
        mod_records.update(self.stances)
        self.mod_records = list(mod_records.values())
        for kind, local, reverse in [('mods', self.mod_records, self.reverse_mods),
                                     ('arcanes', app.EXPORTS['arcanes'], self.reverse_arcanes)]:
            for ref_id, row in self.tables[kind].items():
                try:
                    record = self.exact(row, local)
                    reverse.setdefault(record['path'], []).append(ref_id)
                except ValueError:
                    continue

    @staticmethod
    def exact(row, records):
        from tools.compare_archgun_board_builds import exact_record
        return exact_record(row, records)

    def mod(self, identity):
        base, marker, rank = identity.partition('@')
        definition = self.tables['mods'][base]
        try:
            local = self.exact(definition, self.mod_records)
        except ValueError:
            local = self.stances.get(definition.get('internal_name'))
            if local is None:
                raise
        rank = int(rank) if marker else int(local.get('maxRank', definition.get('max_rank', 3)))
        return base, local, rank

    def mode(self, identity, row, weapon):
        mode = row['mode']
        if weapon.get('slot') == 'melee':
            combinations = {'base': 'CC_GROUND', 'neutral': 'CC_GROUND', 'forward': 'CC_GROUND_BRANCH_A',
                            'block': 'CC_GROUND_BRANCH_C', 'block_forward': 'CC_GROUND_BRANCH_B'}
            if mode not in combinations:
                raise ValueError('melee mode requires a separate cadence contract: ' + mode)
            return 0, False, dict(meleeRoute='combo', meleeCombo=combinations[mode])
        modes = weapon.get('fireModes') or []
        if mode in ('cycle', 'incarnon'):
            indexes = [i for i, spec in enumerate(modes) if spec.get('isIncarnonForm')]
            if len(indexes) != 1:
                raise ValueError('no unique Incarnon fire mode')
            return indexes[0], mode == 'cycle', {}
        overrides = {'fulmin': {'base': 1, 'semi_auto': 0, 'alternate': 0},
                     'fulmin_prime': {'base': 1, 'semi_auto': 0, 'alternate': 0}}
        if identity in overrides and mode in overrides[identity]:
            return overrides[identity][mode], False, {}
        if mode == 'base':
            return 0, False, {}
        raise ValueError('unmapped weapon mode: ' + mode)

    def prepare(self, weapon_id, row, profile, window_seconds=None):
        from tools.compare_archgun_board_builds import public_evolutions, resolved_riven_payload, ELEMENTS
        app = self.app
        order = self.reference.call('/api/board/order', dict(record=record_of(weapon_id, row), ruler=row['benchmark'], mode=row['mode']))
        request = order['request']
        official_duration = request['duration']
        if window_seconds is not None:
            if not math.isfinite(window_seconds) or not .1 <= window_seconds <= 600:
                raise ValueError('window must be between 0.1 and 600 seconds')
            request['duration'] = window_seconds
        if request.get('metric') != 'kpm' or request.get('extra_stats') or request.get('wielder'):
            raise ValueError('non-KPM or external-stat/wielder scenario outside comparison contract')
        weapon = self.exact(self.tables['weapons'][weapon_id], app.EXPORTS['weapons'])
        fire_mode, cycle, state = self.mode(weapon_id, row, weapon)
        state['selfShieldBreakForced'] = False
        enemy = self.exact(self.tables['enemies'][request['enemy']], app.EXPORTS['enemies'])
        choices, proof = public_evolutions(weapon, weapon_id, request.get('evolutions'), self.tables['evolutions'])
        mods, polarities, special, stance, exilus, riven_slot = [], [None] * 8, {}, None, None, None
        exilus_id = (row.get('exilus') or '').split('@')[0]
        for index, identity in enumerate(request['mods']):
            if identity.startswith('riven:'):
                riven_slot = index
                if index >= 8: raise ValueError('Riven lies outside normal slots')
                polarities[index] = 'AP_ATTACK'
                continue
            base, local, rank = self.mod(identity)
            if local['path'] in self.stances:
                stance = local['path']; special['stance'] = 'AP_ANY'; continue
            if base == exilus_id:
                exilus = dict(path=local['path'], rank=rank); special['exilus'] = 'AP_ANY'; continue
            if index >= 8 or local['path'] not in app.MANUAL_MODS_BY_PATH:
                raise ValueError('normal MOD not in Portable catalog: ' + identity)
            mods.append(dict(path=local['path'], rank=rank, slot=index)); polarities[index] = local.get('polarity')
        arcanes = []
        for identity in request.get('arcane') or []:
            if not identity: continue
            record = self.exact(self.tables['arcanes'][identity], app.EXPORTS['arcanes'])
            if record['path'] not in app.MANUAL_ARCANES_BY_PATH:
                raise ValueError('Arcane not in Portable catalog: ' + identity)
            arcanes.append(dict(path=record['path'], rank=record.get('maxRank', 5)))
        player, target = request.get('player_at', [0, 0]), request.get('target_at', [0, .5])
        distance = math.sqrt(sum((float(a)-float(b))**2 for a,b in zip(player,target)))
        if stance:
            state['meleeStance'] = stance
        payload = dict(weapon=weapon['path'], fireMode=fire_mode, mods=mods, arcanes=arcanes,
            mode='auto', profile=profile, metric='attackDps' if weapon.get('slot') == 'melee' else 'killsPerMinute', enemy=enemy['path'],
            level=request['level'], steelPath=bool(request.get('steel_path')), windowSeconds=request['duration'],
            headshotChance=float(request.get('headshot_pct', 0))/100., aiming=bool(request.get('aiming')),
            triggerPolicy='emergent', distance=distance, incarnonCycle=cycle, incarnonChoices=choices,
            slotPolarities=polarities, specialSlotPolarities=special, optimizeWithArcanes=True,
            scenario=dict(aiming=bool(request.get('aiming')), triggerPolicy='emergent', distance=distance,
                          incarnonCycle=cycle, combatState=state), combatState=state)
        if stance: payload['stancePath'] = stance
        if exilus: payload['exilus'] = exilus
        if request.get('valence_element'):
            payload.update(innateElement=ELEMENTS[request['valence_element']], innateElementValue=request.get('valence_bonus', .6))
        if riven_slot is not None:
            spec = request['rivens'][0]['spec']
            resolved = self.reference.call('/api/riven', dict(weapon=weapon_id, **spec))
            family = app.optimizer._riven_type(None, weapon)
            payload['riven'] = resolved_riven_payload(spec, resolved, riven_slot, family)
        # WFSim's infinite_ammo suppresses reserve depletion, while Portable's
        # combatState.infiniteAmmo suppresses reloads. The latter stays off.
        app._manual_resolve_sim_context(payload)
        key = json.dumps([weapon_id, row['benchmark'], row['mode'], row.get('riven'), row['mods']], sort_keys=True)
        case_id = weapon_id + '-' + hashlib.sha256(key.encode()).hexdigest()[:12]
        forbidden = [path for path in app.MANUAL_MODS_BY_PATH if path not in self.reverse_mods]
        result = dict(id=case_id, comparison_version=COMPARISON_VERSION, weapon=weapon_id, benchmark=row['benchmark'], mode=row['mode'],
            official_duration=official_duration, duration=request['duration'],
            has_riven=bool(row.get('riven')), board=row, request=request, payload=payload,
            evolution_mapping=proof, forbidden_unmapped_mods=forbidden)
        result['prepared_hash'] = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
        return result


def reverse_id(path, table):
    ids = table.get(path) or []
    if len(ids) != 1:
        raise ValueError('ambiguous or missing reverse identity: ' + path + ' ' + repr(ids))
    return ids[0]


def worker(runtime, case_path, output, runs):
    os.environ.update(WF_RIVEN_ROOT=str(ROOT), WF_ANALYZER_SERIAL='1', WF_ENGINE_WORKERS='1', WF_SEARCH_NO_DEADLINE='1',
                      WF_ANALYSIS_STATICS_CACHE_PATH=str(output.parent/'unused-statics.json'))
    import app
    from wfarsenal import search_session
    from tools.wfsim_native_reference import reference_from_manifest
    app._disable_analysis_statics_persistence()
    manifest = read(runtime/'comparison-mapping.json'); case=read(case_path)
    engine=reference_from_manifest(runtime, manifest)
    result=dict(case=case, comparison_version=COMPARISON_VERSION, runs=runs,
                inputs=app._analysis_inputs_fingerprint(), startedAt=datetime.now(timezone.utc).isoformat())
    try:
        start,cpu=time.perf_counter(),time.process_time()
        original=app.simulate_manual_payload(case['payload'])
        result['board_local']=original
        payload=deepcopy(case['payload']);payload.pop('mods',None)
        payload['forbiddenMods']=case['forbidden_unmapped_mods']
        token=search_session.CANCEL.set(lambda:time.perf_counter()-start>300)
        try: build=app.build_weapon_payload(payload)
        finally: search_session.CANCEL.reset(token)
        result.update(build=build,local_seconds=time.perf_counter()-start,local_cpu=time.process_time()-cpu)
        ours=deepcopy(case['payload'])
        ours['mods']=[dict(path=m['path'],rank=m['rank'],slot=m['slot']) for m in build['build']['mods']]
        ours['riven']=build['build'].get('riven')
        exilus = build['build'].get('exilus')
        ours['exilus']=({k:exilus[k] for k in ('path','rank')} if exilus else None)
        ours['slotPolarities']=[None]*8
        for row in ours['mods']: ours['slotPolarities'][row['slot']]=app.MANUAL_MODS_BY_PATH[row['path']].get('polarity')
        if ours.get('riven'): ours['slotPolarities'][ours['riven']['slot']]='AP_ATTACK'
        ours['specialSlotPolarities']={k:'AP_ANY' for k in ours.get('specialSlotPolarities',{})}
        if ours.get('exilus'):ours['specialSlotPolarities']['exilus']='AP_ANY'
        ours['incarnonChoices']=build['incarnonChoices']
        result['ours_payload']=ours;result['ours_local']=app.simulate_manual_payload(ours)
        reference=deepcopy(case['request']);reference.update(runs=runs,threads=1)
        ref_ours=deepcopy(reference)
        selected=[]
        for row in build['build']['mods']:
            identity=reverse_id(row['path'],manifest['reverse_mods'])
            maximum=manifest['mod_max_ranks'].get(identity)
            if maximum is not None and row['rank']!=maximum:identity+='@'+str(row['rank'])
            selected.append((row['slot'],identity))
        if ours.get('riven'):selected.append((ours['riven']['slot'],'riven:board'))
        ref_ours['mods']=[identity for _,identity in sorted(selected)]
        if ours.get('stancePath'):ref_ours['mods'].append(reverse_id(ours['stancePath'],manifest['reverse_mods']))
        if ours.get('exilus'):
            ex=ours['exilus'];identity=reverse_id(ex['path'],manifest['reverse_mods'])
            maximum=manifest['mod_max_ranks'].get(identity)
            if maximum is not None and ex['rank']!=maximum:identity+='@'+str(ex['rank'])
            ref_ours['mods'].append(identity)
        result['reference_request']=reference;result['ours_reference_request']=ref_ours
        start=time.perf_counter()
        result['board_reference']=engine.call('/api/simulate',reference)
        result['ours_reference']=engine.call('/api/simulate',ref_ours)
        result['reference_seconds']=time.perf_counter()-start
        result['status']='complete'
    except BaseException as error:
        result.update(status='error',error=f'{type(error).__name__}: {error}',traceback=traceback.format_exc())
    write(output,result)
    print(case['id'],result['status'],flush=True)


def summarize(output):
    """Cross-scores separate an observable search miss from a ranking disagreement."""
    manifest = read(output / 'manifest.json')
    rows, failures, pending = [], [], []
    for identity in manifest['cases']:
        path = output / 'results' / (identity + '.json')
        if not path.exists():
            pending.append(identity)
            continue
        result = read(path)
        if result.get('status') != 'complete':
            failures.append(dict(id=identity, error=result.get('error', result.get('status'))))
            continue
        case = result['case']
        try:
            if case.get('prepared_hash') != read(output / 'cases' / (identity + '.json'))['prepared_hash']:
                raise ValueError('case mapping revised; rerun required')
            own = result['ours_local']['benchmarkTimeline']['killsPerMinute']
            board = result['board_local']['benchmarkTimeline']['killsPerMinute']
            objective = result['build']['build']['objectiveScore']
            if not math.isclose(own, objective, rel_tol=1e-8, abs_tol=1e-8):
                raise ValueError(f'search/manual score mismatch: {objective} vs {own}')
            factor = 60 / result['board_reference']['duration']
            ref_board = result['board_reference']['score'] * factor
            ref_own = result['ours_reference']['score'] * factor
            combined_se = math.hypot(result['board_reference']['score_se'], result['ours_reference']['score_se']) * factor
            local_miss = board > own + max(1e-8, abs(board) * .001)
            ref_loss = ref_board - ref_own > max(3 * combined_se, abs(ref_board) * .001)
            diagnosis = ('search-miss' if local_miss else 'model-ranking-gap') if ref_loss else 'within-reference-band-or-better'
            unsupported = sorted(set(str(v) for side in ['board_local', 'ours_local']
                                     for v in result[side].get('unsupported', [])))
            rows.append(dict(id=identity, weapon=case['weapon'], mode=case['mode'], riven=case['has_riven'],
                local_board=board, local_ours=own, local_ratio=own / board if board else None,
                reference_board=ref_board, reference_ours=ref_own, reference_ratio=ref_own / ref_board if ref_board else None,
                combined_se=combined_se, diagnosis=diagnosis, local_search_miss=local_miss,
                seconds=result['local_seconds'], cpu=result['local_cpu'], unsupported=unsupported,
                historical_score=case['board']['score'], measured_by=case['board'].get('measured_by'),
                board_mods=case['request']['mods'], our_mods=result['ours_reference_request']['mods']))
        except (KeyError, TypeError, ValueError) as error:
            failures.append(dict(id=identity, error=str(error)))
    groups = {}
    for label, group in [('all', rows), ('no_riven', [r for r in rows if not r['riven']]),
                         ('riven', [r for r in rows if r['riven']])]:
        ratios = [r['reference_ratio'] for r in group if r['reference_ratio'] is not None]
        groups[label] = dict(count=len(group), median_ratio=statistics.median(ratios) if ratios else None,
            minimum_ratio=min(ratios) if ratios else None, maximum_ratio=max(ratios) if ratios else None,
            at_least_95pct=sum(r >= .95 for r in ratios), at_least_98pct=sum(r >= .98 for r in ratios),
            local_search_misses=sum(r['local_search_miss'] for r in group),
            ranking_gaps=sum(r['diagnosis'] == 'model-ranking-gap' for r in group),
            median_seconds=statistics.median([r['seconds'] for r in group]) if group else None)
    summary = dict(release=manifest['release'], inputs=manifest['inputs'], profile=manifest['profile'],
                   window_seconds=manifest.get('windowSeconds'),
                   groups=groups, rows=rows, failures=failures, pending=pending,
                   skipped=[{k:v for k,v in r.items() if k != 'row'} for r in manifest['skipped']])
    cross_rows = []
    for row in rows:
        path = output / 'cross-180' / (row['id'] + '.json')
        source = output / 'results' / path.name
        if not path.exists():
            continue
        crossed = read(path)
        if (crossed.get('status') != 'complete'
                or crossed.get('source_sha256') != hashlib.sha256(source.read_bytes()).hexdigest()):
            continue
        board, own = crossed['board_reference'], crossed['ours_reference']
        ratio = own['score'] / board['score'] if board['score'] else None
        local_miss = crossed['board_local'] > crossed['ours_local'] + max(1e-8, crossed['board_local'] * .001)
        ref_loss = board['score'] - own['score'] > max(3 * math.hypot(board['score_se'], own['score_se']), board['score'] * .001)
        if not ref_loss:
            diagnosis = 'within-reference-band-or-better'
        elif not local_miss:
            diagnosis = 'model-ranking-gap'
        elif not row['local_search_miss']:
            diagnosis = 'window-objective-difference'
        else:
            diagnosis = 'search-miss'
        cross_rows.append(dict(id=row['id'], weapon=row['weapon'], mode=row['mode'], riven=row['riven'],
            ratio=ratio, board_kpm=board['score'] / 3, our_kpm=own['score'] / 3,
            local_board=crossed['board_local'], local_ours=crossed['ours_local'], diagnosis=diagnosis))
    cross_groups = {}
    for label, group in [('all', cross_rows), ('no_riven', [r for r in cross_rows if not r['riven']]),
                         ('riven', [r for r in cross_rows if r['riven']])]:
        ratios = [r['ratio'] for r in group if r['ratio'] is not None]
        cross_groups[label] = dict(count=len(group), median_ratio=statistics.median(ratios) if ratios else None,
            at_least_95pct=sum(r >= .95 for r in ratios), at_least_98pct=sum(r >= .98 for r in ratios),
            diagnostics={name:sum(r['diagnosis']==name for r in group) for name in
                         ['within-reference-band-or-better','search-miss','model-ranking-gap','window-objective-difference']})
    summary['official_window_replay'] = dict(groups=cross_groups, rows=cross_rows)
    write(output / 'summary.json', summary)
    lines = ['# WFSim current-board cross-scoring', '',
        'Fixed board Arcane/evolution/Riven values; Portable searches ordinary MODs and Exilus. '
        'Both models replay the exact resulting builds for the same requested duration. Reference scores are freshly '
        'measured with the pinned current engine; published scores remain separate.', '',
        f"Engine `{manifest['release']['engine']}`; data `{manifest['release']['data']}`; Portable `{manifest['inputs']}`; profile `{manifest['profile']}`.", '',
        f"Window: {manifest.get('windowSeconds') or 'official board duration'} seconds. A duration override replays leaders selected on the official board; it does not reproduce their published ranking objective.", '',
        f'{len(rows)} completed, {len(failures)} failed validation/execution, {len(pending)} pending, {len(manifest["skipped"])} mapping exclusions.', '',
        '| Weapon | Mode | Riven | WFSim board KPM | WFSim our KPM | Ratio | Local board / ours | Solve seconds | Diagnostic |',
        '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |']
    for row in rows:
        ratio = f"{row['reference_ratio']:.1%}" if row['reference_ratio'] is not None else 'undefined'
        lines.append(f"| {row['weapon']} | {row['mode']} | {row['riven']} | {row['reference_board']:.4f} | {row['reference_ours']:.4f} | {ratio} | {row['local_board']:.4f} / {row['local_ours']:.4f} | {row['seconds']:.2f} | {row['diagnosis']} |")
    if cross_rows:
        lines += ['', '## Existing search results replayed for 180 seconds', '',
                  'These builds are not searched again. This measures their transfer to the official board window.', '',
                  '| Weapon | Mode | Riven | Board KPM | Our KPM | Ratio | Diagnostic |',
                  '| --- | --- | --- | ---: | ---: | ---: | --- |']
        for row in cross_rows:
            ratio = f"{row['ratio']:.1%}" if row['ratio'] is not None else 'undefined'
            lines.append(f"| {row['weapon']} | {row['mode']} | {row['riven']} | {row['board_kpm']:.4f} | {row['our_kpm']:.4f} | {ratio} | {row['diagnosis']} |")
    lines += ['', 'A diagnostic band uses three times the root sum of squared reported standard errors. '
              'It is not a formal significance test; shared seeds can correlate the estimates. '
              'A search miss means Portable itself prefers the supplied board candidate. '
              'A model ranking gap means it prefers its own candidate while WFSim prefers the board. '
              'Neither model or public board proves the global game optimum.', '', '## Exclusions and failures', '']
    lines += [f'- `{r.get("id", r.get("weapon"))}`: {r["error"]}' for r in [*summary['skipped'], *failures]]
    (output / 'comparison.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(dict(groups=groups, official_window=cross_groups, failures=failures, pending=len(pending)), ensure_ascii=True))


def cross_window_worker(runtime, result_path, output, seconds, runs):
    """Measure the default-window solution on the board's longer objective."""
    os.environ.update(WF_RIVEN_ROOT=str(ROOT), WF_ANALYZER_SERIAL='1', WF_ENGINE_WORKERS='1',
                      WF_ANALYSIS_STATICS_CACHE_PATH=str(output.parent / 'unused-statics.json'))
    import app
    from tools.wfsim_native_reference import reference_from_manifest
    app._disable_analysis_statics_persistence()
    source = read(result_path)
    result = dict(id=source['case']['id'], seconds=seconds, runs=runs,
                  source_sha256=hashlib.sha256(result_path.read_bytes()).hexdigest(),
                  inputs=app._analysis_inputs_fingerprint())
    try:
        if source['status'] != 'complete' or result['inputs'] != source['inputs']:
            raise ValueError('source result is incomplete or uses different Portable inputs')
        current_case = read(result_path.parent.parent / 'cases' / (source['case']['id'] + '.json'))
        if source['case']['prepared_hash'] != current_case['prepared_hash']:
            raise ValueError('case mapping revised; rerun the search first')
        engine = reference_from_manifest(runtime, read(runtime / 'comparison-mapping.json'))
        for side, payload_key, request_key in [('board', None, 'reference_request'), ('ours', 'ours_payload', 'ours_reference_request')]:
            payload = deepcopy(source[payload_key] if payload_key else source['case']['payload'])
            payload['windowSeconds'] = seconds
            local = app.simulate_manual_payload(payload)
            result[side + '_local'] = local['benchmarkTimeline']['killsPerMinute']
            request = dict(source[request_key], duration=seconds, runs=runs, threads=1)
            response = engine.call('/api/simulate', request)
            result[side + '_reference'] = {k:response[k] for k in ['score', 'score_se', 'duration', 'runs', 'kills', 'shots', 'reloads', 'work']}
        result['status'] = 'complete'
    except BaseException as error:
        result.update(status='error', error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
    write(output, result)


def cross_window(runtime, output, seconds, runs, workers):
    manifest = read(output / 'manifest.json')
    queue = []
    for identity in manifest['cases']:
        source = output / 'results' / (identity + '.json')
        if not source.exists() or read(source).get('status') != 'complete':
            continue
        target = output / ('cross-' + format(seconds, 'g')) / source.name
        if target.exists():
            old = read(target)
            if (old.get('status') == 'complete' and old.get('runs') == runs
                    and old.get('source_sha256') == hashlib.sha256(source.read_bytes()).hexdigest()):
                continue
        queue.append((source, target))
    def run_one(pair):
        source, target = pair
        archive_previous(target)
        command = [sys.executable, str(Path(__file__).resolve()), 'cross-worker', '--runtime', str(runtime),
                   '--output', str(target), '--case', str(source), '--window-seconds', str(seconds), '--runs', str(runs)]
        try:
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600)
            if not target.exists():
                write(target, dict(status='error', error=completed.stderr[-2000:]))
        except subprocess.TimeoutExpired:
            write(target, dict(status='timeout', error='cross-window worker timed out'))
        print(source.stem, read(target)['status'], flush=True)
        return read(target)['status']
    with ThreadPoolExecutor(max_workers=workers) as pool:
        statuses = list(pool.map(run_one, queue))
    if any(status != 'complete' for status in statuses):
        raise SystemExit(1)


def verify_current(output):
    """Keep old measurement provenance while checking final-source replay parity."""
    os.environ.update(WF_RIVEN_ROOT=str(ROOT), WF_ANALYZER_SERIAL='1', WF_ENGINE_WORKERS='1',
                      WF_ANALYSIS_STATICS_CACHE_PATH=str(output / 'verify-unused-cache.json'))
    import app
    app._disable_analysis_statics_persistence()
    manifest = read(output / 'manifest.json')
    report = dict(measured_inputs=manifest['inputs'], current_inputs=app._analysis_inputs_fingerprint(),
                  contract='Replayed stored builds; did not repeat the searches. Explicit stance binding is unchanged.',
                  cases=[], failures=[])
    for identity in manifest['cases']:
        path = output / 'results' / (identity + '.json')
        if not path.exists():
            continue
        source = read(path)
        if source.get('status') != 'complete':
            continue
        if source['case']['prepared_hash'] != read(output / 'cases' / path.name)['prepared_hash']:
            continue
        try:
            for side, key in [('board', None), ('ours', 'ours_payload')]:
                payload = source[key] if key else source['case']['payload']
                stance = payload.get('stancePath')
                if stance:
                    assert payload['scenario']['combatState']['meleeStance'] == stance
                    assert source['build']['evaluationScenario']['combatState']['meleeStance'] == stance
                now = app.simulate_manual_payload(payload)
                old_score = source[side + '_local']['benchmarkTimeline']['killsPerMinute']
                assert now['benchmarkTimeline']['killsPerMinute'] == old_score, (identity, side, old_score, now['benchmarkTimeline']['killsPerMinute'])
                crossed = output / 'cross-180' / path.name
                if crossed.exists():
                    old = read(crossed)
                    if old.get('status') == 'complete' and old.get('source_sha256') == hashlib.sha256(path.read_bytes()).hexdigest():
                        now_long = app.simulate_manual_payload(dict(payload, windowSeconds=180))
                        assert now_long['benchmarkTimeline']['killsPerMinute'] == old[side + '_local'], (identity, side, '180-second replay differs')
            report['cases'].append(identity)
        except Exception as error:
            report['failures'].append(dict(id=identity, error=repr(error)))
    write(output / 'final-source-verification.json', report)
    print(json.dumps(dict(cases=len(report['cases']), failures=report['failures'], current_inputs=report['current_inputs'])))
    if report['failures']:
        raise SystemExit(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=['prepare','run','worker','summarize','cross-window','cross-worker','verify-current'])
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--weapons',nargs='+')
    parser.add_argument('--benchmarks',nargs='+',default=['standard_single_target'])
    parser.add_argument('--modes',nargs='+',default=['base','cycle'])
    parser.add_argument('--profile',default='standard')
    parser.add_argument('--window-seconds',type=float,help='Replay and search both builds at this duration instead of the official board duration')
    parser.add_argument('--runs',type=int,default=1000)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--case',type=Path)
    args=parser.parse_args();runtime=args.runtime.resolve();output=args.output.resolve()
    if args.runs <= 0 or args.workers <= 0:
        parser.error('--runs and --workers must be positive')
    if args.stage=='worker':
        worker(runtime,args.case,output,args.runs);return
    if args.stage=='summarize':
        summarize(output);return
    if args.stage=='verify-current':
        verify_current(output);return
    if args.stage=='cross-worker':
        cross_window_worker(runtime,args.case,output,args.window_seconds or 180,args.runs);return
    if args.stage=='cross-window':
        cross_window(runtime,output,args.window_seconds or 180,args.runs,args.workers);return
    output.mkdir(parents=True,exist_ok=True)
    if args.stage=='prepare':
        if not args.weapons:parser.error('--weapons required')
        os.environ['WF_RIVEN_ROOT']=str(ROOT)
        mapper=Mapper(runtime);prepared=[];skipped=[];sources=[]
        for weapon in args.weapons:
            try:
                rows,digest=fetch_board(runtime,weapon)
            except Exception as error:
                skipped.append(dict(weapon=weapon,error=str(error),stage='download'));continue
            sources.append(dict(weapon=weapon,sha256=digest,url='https://cdn.wfsim.app/board/'+weapon+'.json'))
            for benchmark in args.benchmarks:
                for mode in args.modes:
                    for riven in [False,True]:
                        found=[r for r in rows if r.get('benchmark')==benchmark and r.get('mode')==mode and bool(r.get('riven'))==riven]
                        if not found:continue
                        row=max(found,key=lambda r:r['score'])
                        try:
                            case=mapper.prepare(weapon,row,args.profile,args.window_seconds);write(output/'cases'/(case['id']+'.json'),case);prepared.append(case['id'])
                        except Exception as error:
                            skipped.append(dict(weapon=weapon,benchmark=benchmark,mode=mode,riven=riven,error=str(error),row=row))
        mod_ranks={identity:int(row.get('max_rank',row.get('ranks',0))) for identity,row in mapper.tables['mods'].items()}
        # Local max ranks are authoritative for exported local builds; the
        # reference registry provides the rank spelling used on its request.
        for path,ids in mapper.reverse_mods.items():
            local=mapper.app.MANUAL_MODS_BY_PATH.get(path) or mapper.app.UTILITY_MODS_BY_PATH.get(path)
            if local:
                for identity in ids:mod_ranks[identity]=int(local.get('maxRank',local.get('rank',0)))
        write(runtime/'comparison-mapping.json',dict(**mapper.reference_manifest,
            reverse_mods=mapper.reverse_mods,reverse_arcanes=mapper.reverse_arcanes,mod_max_ranks=mod_ranks))
        write(output/'manifest.json',dict(capturedAt=datetime.now(timezone.utc).isoformat(),release=mapper.release,
            inputs=mapper.app._analysis_inputs_fingerprint(),profile=args.profile,cases=prepared,sources=sources,skipped=skipped,
            weapons=args.weapons,benchmarks=args.benchmarks,modes=args.modes,windowSeconds=args.window_seconds))
        print(json.dumps(dict(prepared=len(prepared),skipped=[{k:v for k,v in s.items() if k!='row'} for s in skipped]),ensure_ascii=True),flush=True);return
    manifest=read(output/'manifest.json');queue=[]
    for identity in manifest['cases']:
        if args.weapons and read(output/'cases'/(identity+'.json'))['weapon'] not in args.weapons:
            continue
        target=output/'results'/(identity+'.json')
        if target.exists():
            previous=read(target);prepared=read(output/'cases'/(identity+'.json'))
            if (previous.get('status')=='complete' and previous.get('inputs')==manifest['inputs']
                    and previous.get('comparison_version')==COMPARISON_VERSION and previous.get('runs')==args.runs
                    and previous.get('case',{}).get('prepared_hash')==prepared['prepared_hash']):continue
        queue.append((identity,target))
    def run_one(item):
        identity,target=item;log=output/'logs'/(identity+'.log');log.parent.mkdir(parents=True,exist_ok=True)
        archive_previous(target)
        command=[sys.executable,str(Path(__file__).resolve()),'worker','--runtime',str(runtime),'--case',str(output/'cases'/(identity+'.json')),'--output',str(target),'--runs',str(args.runs)]
        try:
            with log.open('w',encoding='utf-8') as stream:
                completed=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,timeout=600)
            if not target.exists():write(target,dict(status='error',error=f'worker exited {completed.returncode}; see {log}'))
        except subprocess.TimeoutExpired:
            write(target,dict(status='timeout',error='600-second comparison worker limit'))
        result=read(target)
        if result.get('inputs') not in (None,manifest['inputs']):
            result.update(status='error',error='Portable input fingerprint changed');write(target,result)
        print(identity,result['status'],flush=True)
        return result['status']
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        statuses = list(pool.map(run_one,queue))
    if any(status != 'complete' for status in statuses):
        raise SystemExit(1)


if __name__=='__main__':
    main()
