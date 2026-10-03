"""Budgeted Riven combinations, with every legal structure seeded first."""
from dataclasses import replace
import itertools
import time


def negative_rolls(lines):
    from . import optimizer as o
    for line in lines:
        low=line.value*.89/1.089
        values=[line.value]
        if line.code=='3':
            values=[low,(low+line.value)/2.,line.value]
            # The -100% boundary removes Ignite entirely; sample its live
            # side explicitly instead of testing only -91%, -101%, -111%.
            if low<99.9<line.value:
                values.extend([(low+99.9)/2.,99.9])
        for value in sorted(set(values)):
            yield replace(line,value=value,effect=o._effect_from_code(line.code,value,
                negative=True,source='riven:theoretical:'+line.code))


def result_rank(row):
    # Equivalent target kills can differ by ~1e-10 DPS from floating point
    # summation. That is not evidence for preferring a damaging curse.
    return (-float(f"{row['score']:.10g}"),-float(f"{row['tieBreakScore']:.10g}"),not row['neutralNegative'])


def recommend(weapon, baseline, positive_candidates, negative_candidates, *, scenario,
              metric, passives=None, capacity_limit=60, target_context=None,
              budget_seconds=10., top_limit=10, slot_count=8, min_fill=None,
              max_fill=None, required_damage_type=None, special_cards=(), special_capacity_cost=0):
    from . import optimizer as o
    start=time.monotonic()
    deadline=start+max(.5,float(budget_seconds))
    neutral=o._neutral_negative_codes(weapon)
    positives=[l for l in positive_candidates if l.effect and l.effect.supported]
    negatives=[l for l in negative_candidates if l.code in neutral or l.effect and l.effect.supported]
    if len(positives)<2:
        raise o.SimulationError('not enough supported positive Riven stats')
    required=tuple(c for c in baseline.cards if c.required)
    optional=tuple(c for c in baseline.cards if not c.required)
    lo=max(0,(min_fill or 1)-len(required)-1)
    hi=min(len(optional),min(slot_count,max_fill if max_fill is not None else slot_count)-len(required)-1)
    if lo>hi:
        raise o.SimulationError('Riven and required MODs cannot satisfy slot/fill limits')
    # Highest legal keep layer first. Never delete five equipped cards merely
    # to obtain a cheaper ranking signal on a different build.
    subsets=[]
    empty=o._card_from_lines([])
    for keep in range(hi,lo-1,-1):
        subsets=[tuple((*required,*(optional[i] for i in indexes)))
                 for indexes in itertools.combinations(range(len(optional)),keep)]
        subsets=[cs for cs in subsets if o._capacity((*cs,empty))+special_capacity_cost<=capacity_limit]
        if subsets:break
    if not subsets:
        raise o.SimulationError('no capacity-valid build can equip the Riven')
    memo={}; results={}; evaluations=0; memo_hits=0; covered=set(); fusion_evaluated=set()

    def remap(lines):
        n=sum(not l.negative for l in lines); cursed=any(l.negative for l in lines)
        out=[]
        for l in lines:
            factor=o.theoretical_structure_scale(n,cursed,negative=l.negative)/o.theoretical_structure_scale(3,False,negative=l.negative)
            value=l.value*factor
            out.append(replace(l,value=value,high=l.high*factor,
                effect=o._effect_from_code(l.code,value,negative=l.negative,source='riven:theoretical:'+l.code)))
        return out

    def evaluate(lines, stage, *, mandatory=False, first_only=False):
        nonlocal evaluations,memo_hits
        if len({l.code for l in lines})!=len(lines) or not o._combo_allows_fusion(lines):return None
        mapped=remap(lines); card=o._card_from_lines(mapped)
        key=tuple(sorted((l.code,l.negative,round(l.value,8)) for l in mapped))
        best=None
        for index,cards in enumerate(subsets):
            if time.monotonic()>=deadline and not (mandatory and index==0):break
            mk=(tuple(c.key for c in cards),key)
            if mk in memo:
                value=memo[mk];memo_hits+=1
            else:
                value=o._evaluate(weapon,cards,card,scenario=scenario,metric=metric,passives=passives,
                    slot_limit=slot_count,capacity_limit=capacity_limit,target_context=target_context,
                    special_cards=special_cards,special_capacity_cost=special_capacity_cost)
                evaluations+=1;memo[mk]=value
            if value and (not required_damage_type or value.stats.damage_types.get(required_damage_type,0)>0):
                tie=o._score(value.stats,'windowedDps',target_context=target_context) if metric=='killsPerMinute' and target_context else value.score
                if best is None or (value.score,tie)>(best[0].score,best[1]):best=(value,tie)
            if first_only:break
        if best:
            outcome,tie=best
            old=results.get(key)
            if old is None or (outcome.score,tie)>(old['score'],old['tieBreakScore']):
                build=o._build_payload(weapon,outcome,card,passives)
                wire=[dict(code=l.code,label=l.label,value=l.value,negative=l.negative,unit=l.unit) for l in mapped]
                build['damageTypes']=dict(outcome.stats.damage_types)
                build['riven']={'slot':outcome.riven_index,'polarity':card.polarity,
                    'stats':[{k:s[k] for k in ('code','value','negative')} for s in wire]}
                build['specialMods']=[dict(path=c.record['path'],rank=c.rank) for c in special_cards if c.record]
                results[key]=dict(build=build,stats=wire,score=outcome.score,tieBreakScore=tie,
                    gain=o._percent_gain(outcome.score,baseline.score),stage=stage,
                    structure=f"{sum(not l.negative for l in mapped)}+{sum(l.negative for l in mapped)}",
                    neutralNegative=any(l.negative and l.code in neutral for l in mapped))
            covered.add(results[key]['structure'])
            fusion_evaluated.update(l.code for l in mapped if l.code in o._FUSION_LINE_CODES)
            return outcome.score
        return None

    # All traits get a cheap signal; enumeration order must not discard fusion
    # traits at the end of the catalog when the event budget runs out.
    ranked=[]
    for line in positives:
        card=o._card_from_lines(remap([line]))
        value=o._evaluate(weapon,subsets[0],card,scenario=scenario,metric='sustainedDps',
            passives=passives,slot_limit=slot_count,capacity_limit=capacity_limit,
            special_cards=special_cards,special_capacity_cost=special_capacity_cost)
        ranked.append((value.score if value else 0.,line))
    ranked.sort(key=lambda x:(-x[0],x[1].code))
    ordered=[l for _,l in ranked]
    seed=[]
    for l in ordered:
        if o._combo_allows_fusion((*seed,l)):seed.append(l)
        if len(seed)==3:break
    neutral_order={'H':0,'X':0,'E':1,'Z':2,'M':3}
    neutral_lines=sorted([l for l in negatives if l.code in neutral],key=lambda l:(neutral_order.get(l.code,9),l.code))
    # No artificial reward: each curse increases the positive roll through
    # the real 1.25 structure coefficient and receives a full event score.
    for n in (2,3):
        if len(seed)<n:continue
        evaluate(seed[:n],'beam',mandatory=True,first_only=True)
        neg=next((l for l in neutral_lines if l.code not in {p.code for p in seed[:n]}),None)
        if neg:evaluate([*seed[:n],neg],'beam-negative',mandatory=True,first_only=True)
        duration=next((l for l in negatives if l.code=='3' and l.code not in {p.code for p in seed[:n]}),None)
        if duration:
            for curse in itertools.islice(negative_rolls([duration]),3):
                evaluate([*seed[:n],curse],'beam-negative',mandatory=True,first_only=True)

    def variants(combo):
        yield combo
        used={l.code for l in combo}
        available=[l for l in neutral_lines if l.code not in used]
        if available:yield (*combo,available[0])
        duration=next((l for l in negatives if l.code=='3' and l.code not in used),None)
        if duration:
            # A weaker curse can win on Heat strip timing while keeping ticks.
            # These are valid rolls between nominal*0.89 and nominal*1.089.
            for curse in negative_rolls([duration]):
                yield (*combo,curse)
        for l in negatives:
            if l.code not in used and l.code!='3' and (not available or l.code!=available[0].code):
                yield (*combo,l)

    # Evaluate every available fusion family with a legal seed before breadth
    # expansion; it cannot disappear merely because it was appended in data.
    for line in ordered:
        if line.code not in o._FUSION_LINE_CODES:continue
        companions=[p for p in ordered if p.code not in o._FUSION_LINE_CODES and p.code!=line.code]
        combo=(line,*companions[:1])
        for candidate in itertools.islice(variants(combo),2):
            if time.monotonic()>=deadline:break
            evaluate(candidate,'beam-negative' if any(l.negative for l in candidate) else 'beam',first_only=True)
    width=8 if budget_seconds<=10 else 12
    pools=[iter(itertools.combinations(ordered[:width],n)) for n in (2,3)]
    for pairs in itertools.zip_longest(*pools):
        if time.monotonic()>=deadline:break
        for combo in pairs:
            if combo is None or not o._combo_allows_fusion(combo):continue
            # Reserve breadth: test clean, neutral and three duration rolls
            # before spending remaining time on every other possible curse.
            for candidate in itertools.islice(variants(combo),5):
                if time.monotonic()>=deadline:break
                evaluate(candidate,'beam-negative' if any(l.negative for l in candidate) else 'beam')

    # Other negative effects can be beneficial too (magazine gates, IPS proc
    # weighting). Refine leading combinations only after structure breadth.
    code_to_line={l.code:l for l in positives}
    head=sorted(results.values(),key=lambda r:(-r['score'],-r['tieBreakScore']))[:4]
    for row in head:
        combo=tuple(code_to_line[s['code']] for s in row['stats'] if not s['negative'])
        for candidate in variants(combo):
            if time.monotonic()>=deadline:break
            evaluate(candidate,'refined')

    combos=[]; seen_affixes=set()
    for row in sorted(results.values(),key=result_rank):
        identity=tuple(sorted((s['code'],s['negative']) for s in row['stats']))
        if identity in seen_affixes:continue
        seen_affixes.add(identity);combos.append(row)
        if len(combos)>=top_limit:break
    return dict(combos=combos,budget=float(budget_seconds),elapsed=time.monotonic()-start,
        evaluations=evaluations,memoHits=memo_hits,refined=0,baselineScore=baseline.score,
        structuresEvaluated=sorted(covered),fusionCandidates=[l.code for l in positives if l.code in o._FUSION_LINE_CODES],
        fusionEvaluated=sorted(fusion_evaluated),
        neutralNegativeScope='Only the simulated attacks; finishers/sliding/zoom outside this scenario have no damage contribution.',
        stages={'coarse':'all traits, same equipped MOD context, panel ordering only',
                'beam':f'fair 2/3-positive structures, neutral negatives and legal duration rolls; width {width}',
                'refined':'keep 7..0 capacity fallback; no forced deletion for ranking'},
        scope=dict(slotCount=slot_count,minFill=max(1,min_fill or 1),maxFill=min(slot_count,max_fill or slot_count),requiredDamageType=required_damage_type),
        searchStatus='heuristic-budget-limited' if time.monotonic()>=deadline else 'heuristic-best-found')
