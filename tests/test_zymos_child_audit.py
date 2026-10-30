"""Zymos source contracts and ordered guided-contact calculation."""
from copy import deepcopy
import pytest
from tools.import_zymos_child_audit import child_audit, merge, SCRIPT, WEAPON, PROJECTILE, CARRIER, CHILD
from wfarsenal.damage import ModEffect, Scenario
from wfarsenal.zymos import (ContactPolicy, SourceContext, UpgradeValue,
                             carrier_snapshot, child_packets, fire_count_distribution)


class Packages:
    def __init__(self):
        self.rows = {
            PROJECTILE: {"ValidEmbedPart": "HEAD",
                "EmbedDeathAttackHitScript": {"Script": SCRIPT, "Function": "OnRadialDamage", "_projectileType": "EmbedDeathKillClusterProj"},
                "OnProjectileDeathScript": {"Script": SCRIPT, "Function": "OnDeath", "_projectileType": "EmbedDeathKillClusterProj"}},
            CARRIER: {"ClusterProjectiles": "EmbedDeathKillGuidedProj", "ClusterSetsChildrenDamageInfo": 1},
            CHILD: {"SendEvents": 0, "DamageUpgradeTypes": [], "CriticalChance": .05, "CriticalMultiplier": 2.3,
                    "ExplosiveAttack": {"Amount": 333, "Type": "DT_POISON", "ProcChance": .3}}}
    def resolve(self, path):
        return self.rows[path]


def test_shared_record_and_source_declaration_contract_stays_independent():
    evidence = child_audit(Packages())
    assert [branch["requestedChildCount"] for branch in evidence["callbackBranches"]] == [5, 5]
    assert evidence["branchCombination"] == "shared-record-consumed-once-do-not-sum"
    assert evidence["childDeclarations"]["SendEvents"] == 0
    reference = {"auditedAttacks": {WEAPON: {"projectile": PROJECTILE, "directTotal": 23.,
        "radials": [{"damage": {"toxin": 61.}}, {"damage": {"toxin": 953.}, "headOnly": True}]}}}
    original = deepcopy(reference)
    merged = merge(reference, evidence)
    assert reference == original
    assert merged["auditedAttacks"][WEAPON]["radials"] == original["auditedAttacks"][WEAPON]["radials"]
    assert merged == merge(merged, evidence)
    packages = Packages()
    del packages.rows[CHILD]["SendEvents"]
    with pytest.raises(ValueError, match="declaration contract"):
        child_audit(packages)


def test_retained_crit_and_integer_callback_counts_build_paired_packets(monkeypatch):
    import app
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("path") == WEAPON)
    effects = [ModEffect("WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", 1.2),
               ModEffect("WEAPON_CRIT_DAMAGE", "STACKING_MULTIPLY", 1.2),
               ModEffect("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", 1.),
               ModEffect("WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE", "STACKING_MULTIPLY", .4),
               ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", .5, damage_type="DT_POISON")]
    context = SourceContext.ordinary_static()
    snapshot = carrier_snapshot(weapon, effects, context=context,
                                callback_counts=fire_count_distribution(1.25))
    assert snapshot.contact_amounts == ((46, .75), (92, .25))
    policy = ContactPolicy.from_state({"zymosChildOverlap": "ideal-contact", "zymosChildArrivalSeconds": .4, "zymosChildContacts": 5})
    parts = child_packets(snapshot, weapon, effects, context=context, policy=policy)
    assert [(p.weight, p.contacts, p.arrival_seconds) for p in parts] == [(.75, 5, .4), (.25, 5, .4)]
    assert [p.contact.total_damage for p in parts] == pytest.approx([69., 138.])
    assert parts[0].explosion.total_damage == pytest.approx(499.5)
    assert parts[0].contact.crit_chance == pytest.approx(.17)
    assert parts[0].explosion.crit_multiplier == pytest.approx(7.82)
    assert parts[0].contact.radial_only and not parts[0].contact.radial_victim_crit
    assert parts[0].explosion.radial_only and parts[0].explosion.radial_victim_crit
    assert parts[0].contact.delayed_radial_hit_event and parts[0].explosion.delayed_radial_hit_event
    assert parts[0].contact._co_spec.gunco_fraction == 1.
    assert parts[0].explosion._co_spec.gunco_fraction is None

    # Exercise the real carrier -> next update -> paired-child replay too.
    # A helper-only check missed a resolver/closure name collision here.
    from wfarsenal.manual_combat import prepare
    from wfarsenal.combat_replay import replay
    from wfarsenal import native_replay
    state={'zymosChildOverlap':'ideal-contact','zymosChildArrivalSeconds':.4}
    combat=prepare(dict(weapon=weapon,fire_mode=0,effects=[
        ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.)],
        scenario=Scenario(combat_state=state)),[],[])
    resolve=combat['resolve']
    def single(*args):
        direct,radial=resolve(*args);direct.fire_rate=.001;return direct,radial
    combat['resolve']=single;direct,_=single('selected',{},0.)
    victim=dict(health=1e12,armour=0.,shield=0.,baseLevel=1)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    native_before=native_replay.STATS['native']
    kwargs=dict(attacks_per_second=.001,headshot_chance=1.,collect_timeline=False,combat=combat)
    before=replay(direct,victim,window_seconds=1.5,**kwargs)
    after=replay(direct,victim,window_seconds=1.6,**kwargs)
    assert after['shots']==1 and after['zymosChildren']
    assert after['directWindow']-before['directWindow']==pytest.approx(5*(23.+333.))
    assert native_replay.STATS['native']>native_before
    curve=[]
    replay(direct,{**victim,'health':before['directWindow']+10.},window_seconds=1.6,life_curve=curve,**kwargs)
    child_hits=[event[1] for event in curve if event[0]>1.5]
    assert child_hits==pytest.approx([23.])  # Dead original host cannot transfer its blast to the next enemy.

    shiver=ModEffect('RUNTIME_COLD_STACK_DAMAGE','ADD',.3)
    shivering=prepare(dict(weapon=weapon,fire_mode=0,effects=[shiver,
        ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.)],
        scenario=Scenario(combat_state=state)),[],[])
    resolve_shiver=shivering['resolve']
    def cold_shot(*args):
        direct,radial=resolve_shiver(*args);direct.fire_rate=.001
        direct.native_forced_procs={'DT_FREEZE':1.}
        return direct,radial
    shivering['resolve']=cold_shot;direct,_=cold_shot('selected',{},0.)
    before=replay(direct,victim,window_seconds=1.5,**{**kwargs,'combat':shivering})
    after=replay(direct,victim,window_seconds=1.6,**{**kwargs,'combat':shivering})
    # SCRIPT5 contact takes the independently proven 261 victim-stack query;
    # its 333 explosion cannot borrow that contact consumer.
    assert after['directWindow']-before['directWindow']==pytest.approx(5*(23.*1.3+333.))


def test_ordered_contexts_operations_and_explicit_admission(monkeypatch):
    import app
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("path") == WEAPON)
    effects = [ModEffect("WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", 1.),
               ModEffect("WEAPON_CRIT_CHANCE", "MULTIPLY", 1.2)]
    snapshot = carrier_snapshot(weapon, effects, context=SourceContext((.1,), 0., 1., "carrier-F"),
                                callback_counts=fire_count_distribution(7., cached_count=1))
    policy = ContactPolicy(.4, 5)
    packet = child_packets(snapshot, weapon, effects,
        context=SourceContext((.2,), .3, 1., "later-F-and-final-G"), policy=policy)[0]
    assert packet.contact.crit_chance == pytest.approx(1.08)
    value = UpgradeValue(.05).query([ModEffect("WEAPON_CRIT_CHANCE", "ADD", .2),
        ModEffect("WEAPON_CRIT_CHANCE", "MULTIPLY", 2.),
        ModEffect("WEAPON_CRIT_CHANCE", "SET_BASE", .1),
        ModEffect("WEAPON_CRIT_CHANCE", "ADD_BASE", .1)])
    assert value.get() == pytest.approx(.8)
    assert value.query([ModEffect("WEAPON_CRIT_CHANCE", "SET", .3)]).get() == pytest.approx(.3)
    assert ContactPolicy.from_state({}) is None
    with pytest.raises(ValueError, match="ArrivalSeconds"):
        ContactPolicy.from_state({"zymosChildOverlap": "ideal-contact"})
    with pytest.raises(ValueError, match="enervate-query-snapshot-required"):
        child_packets(snapshot, weapon, effects, context=SourceContext.ordinary_static(enervate_active=True), policy=policy)
    enervate = ModEffect("WEAPON_CRIT_CHANCE", "ADD", .2,
                        source_path="/Lotus/Upgrades/CosmeticEnhancers/Offensive/SecondaryCritOnHit")
    mapped = SourceContext.ordinary_static(enervate_active=True, enervate_snapshotted=True)
    carrier = carrier_snapshot(weapon, [enervate], context=mapped,
                               callback_counts=fire_count_distribution(1.))
    assert child_packets(carrier, weapon, [enervate], context=mapped, policy=policy)[0].contact.crit_chance == pytest.approx(.45)
    negative = carrier_snapshot(weapon, [ModEffect("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", -2.)],
        context=mapped, callback_counts=fire_count_distribution(1.))
    pair = child_packets(negative, weapon, [], context=mapped, policy=policy)[0]
    assert pair.contact.total_damage == 0. and pair.explosion.total_damage == 333.

    from wfarsenal.manual_combat import prepare
    from wfarsenal.combat_replay import replay
    from wfarsenal import native_replay
    from tools.audit_optimizer_events import evaluate_payload
    arcane=next(a for a in app.EXPORTS['arcanes'] if a['path']==enervate.source_path)
    state={'zymosChildOverlap':'ideal-contact','zymosChildArrivalSeconds':.4}
    combat=prepare(dict(weapon=weapon,fire_mode=0,effects=[],scenario=Scenario(
        trigger_policy='emergent',combat_state=state)),[],[(arcane,5,{})])
    direct,_=combat['resolve']('selected',{},0.)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    result=replay(direct,dict(health=1e12,shield=0.,armour=0.,baseLevel=1),combat=combat,
        attacks_per_second=direct.fire_rate,headshot_chance=1.,window_seconds=5.,collect_timeline=False)
    assert result['zymosChildren'] and result['enervate']['acceptedHits']>0
    assert 'zymos-two-source-enervate-snapshots-use-marginal-probabilities' in result['unsupported']
    # The same selected policy crosses the production manual/optimizer boundary.
    checked=evaluate_payload(dict(weapon=WEAPON,fireMode=0,mods=[],arcanes=[],
        enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=1.,
        triggerPolicy='emergent',combatState=state,metric='killsPerMinute'))
    assert checked['manual']==pytest.approx(checked['optimizer'],rel=1e-9)
