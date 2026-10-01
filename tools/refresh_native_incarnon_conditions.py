"""Recover strict native event gates without guessing from evolution names."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.refresh_spread_talons import preserve_lines

PROCS=dict(zip(['PT_KNOCKBACK','PT_FRAILTY','PT_BLEEDING','PT_IMMOLATION','PT_CHILLED','PT_ELECTROCUTION','PT_POISONED','PT_FLASHBANG','PT_RAD_TOX','PT_ASPHYXIATION','PT_MAGNETIZED','PT_INFECTED','PT_CAUSTIC_BURN'],
               ['DT_IMPACT','DT_PUNCTURE','DT_SLASH','DT_FIRE','DT_FREEZE','DT_ELECTRICITY','DT_POISON','DT_EXPLOSION','DT_RADIATION','DT_GAS','DT_MAGNETIC','DT_VIRAL','DT_CORROSIVE']))
TAGS={'PRE_RELOAD_FROM_EMPTY':'on-reload-empty','RELOAD_FROM_EMPTY':'on-reload-empty-complete','BURST_ALL_SHOTS_HIT':'on-burst-hit',
      'FIRE_WEAPON':'on-fire','PUNCTURED_SHOT_HIT':'on-punchthrough','RELOAD':'on-reload-complete'}
RESETS={'RELOAD':'on-reload','PRE_RELOAD':'on-reload','HolsterItem':'on-holster',
        'ACTIVATED_INCARNON_FORM':'on-transform','DEACTIVATED_INCARNON_FORM':'on-transform'}


def event(row):
    raw=row['native']
    if not raw or row.get('error'):
        return None
    script=raw.get('Script') or {}
    allowed_script=script.get('Script')=='/Lotus/Scripts/Challenges/MatchSpecificTag.lua' and script.get('Function')=='MatchTagEvent'
    if (script.get('Script')=='/Lotus/Types/Challenges/EvolvingWeaponUpgrades.lua'
            and script.get('Function')=='MatchAttackEvent' and script.get('_checkIsSliding')==0
            and script.get('_evoRank') in {3,5} and script.get('_evoSkillIndex') in {1,2}):
        allowed_script=True
    if (script.get('Script')=='/Lotus/Scripts/Mods/RestoreAmmoOnCondition.lua' and script.get('Function')=='MatchAttackEvent'
            and script.get('_ammoAmount')==1 and script.get('_restoreFromAmmoPool')==1
            and raw.get('VictimActiveProcTypes')==['PT_ELECTROCUTION']):
        allowed_script=True
    if script and not allowed_script:
        return None
    game=raw.get('GameTag')
    kind=TAGS.get(game)
    if raw.get('AttackDir')=='AD_DEFENDER':
        if game=='SHIELD_BREAK':
            kind='on-shield-broken'
        elif game=='SELF_OVERGUARD_BREAK':
            kind='on-overguard-broken'
        elif raw.get('ShieldDamage')=='T_YES':
            kind='on-shield-hit'
        else:
            return None
    elif raw.get('ProcTypes'):
        if len(raw['ProcTypes'])==1 and raw['ProcTypes'][0] in PROCS:
            kind='proc-'+PROCS[raw['ProcTypes'][0]]
        elif set(raw['ProcTypes'])==set(PROCS):
            kind='on-proc'
        else:
            return None
    elif not game:
        if raw.get('Injury')=='ANY':
            if raw.get('CriticalHit')=='T_NO' and raw.get('NoProcs')==1:
                kind='on-noncrit-no-proc'
            elif raw.get('CriticalHit')=='T_NO' or raw.get('NoProcs'):
                return None
            else:
                kind='on-crit' if raw.get('CriticalHit')=='T_YES' else ('on-headshot' if raw.get('Part')=='HEAD' else 'on-hit')
        elif any('/OnKill' in p or '/OnHeadshotKill' in p for p in row['ancestry']):
            kind='on-headshot-kill' if raw.get('Part')=='HEAD' else 'on-kill'
    if not kind:
        return None
    result=dict(kind=kind,requiredCount=int(raw.get('RequiredCount') or 1),
                resetOn=[RESETS[x] for x in raw.get('ResetOnTags') or [] if x in RESETS],
                path=row['path'],sha256=row.get('sha256'))
    if raw.get('AttackDir')=='AD_DEFENDER':
        result['actorOnly']=True
    if raw.get('RequiredTime'):
        result['requiredTime']=raw['RequiredTime']
    if raw.get('ResetOnWrongPart'):
        result['resetOn'].append('on-body-hit')
    victim=raw.get('VictimActiveProcTypes') or []
    if victim:
        if len(victim)!=1 or victim[0] not in PROCS:
            return None
        result['victimProcType']=PROCS[victim[0]]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory',type=Path,required=True)
    parser.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args()
    if args.evidence.exists():
        parser.error('choose a new evidence file')
    rows=json.loads(args.inventory.read_bytes())
    lookup={(r['weapon'],r['branch'],r['reference']):r for r in rows}
    before=args.export.read_bytes()
    payload=json.loads(before)
    changes,accepted=[],[]
    for weapon in payload['data']:
        old=deepcopy(weapon)
        for tier in (weapon.get('incarnon') or {}).get('tiers') or []:
            for branch in tier.get('branches') or []:
                for container in [branch,*(branch.get('sources') or [])]:
                    for condition in container.get('conditionalEffects') or []:
                        condition.pop('nativeEvent',None)
                        native=[lookup.get((weapon['path'],branch['id'],name)) for name in condition.get('conditions') or []]
                        events=[event(r) if r else None for r in native]
                        if not events or not all(events) or len({e['kind'] for e in events})!=1:
                            continue
                        condition['nativeEvent']=events[0]
                        if container is branch:
                            accepted.append(dict(weapon=weapon['path'],branch=branch['id'],source=condition.get('sourcePath'),event=events[0]))
        if old!=weapon:
            changes.append((old,weapon))
    text=before.decode('utf-8').replace('\r\n','\n')
    for old,new in changes:
        serialize=lambda value:json.dumps(value,ensure_ascii=False,sort_keys=True,indent=1).replace('\n','\n  ')
        previous=serialize(old)
        if text.count(previous)!=1:
            raise ValueError('ambiguous weapon record: '+old['path'])
        text=text.replace(previous,serialize(new),1)
    args.export.write_bytes(preserve_lines(before,text.encode('utf-8')))
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(accepted,indent=2)+'\n',encoding='utf-8')
    print('accepted native conditions:',len(accepted),'weapons:',len(changes))


if __name__=='__main__':
    main()
