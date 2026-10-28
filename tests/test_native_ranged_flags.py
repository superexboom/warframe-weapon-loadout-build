"""Audit regressions: inherited declarations, list replacement and reachability."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"tools/audit_native_ranged_flags.py"
spec=importlib.util.spec_from_file_location("native_ranged_flags_audit",SCRIPT)
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class FakePackages:
    def __init__(self,objects,parents):
        self.objects=objects
        self.parents=parents
    def own(self,path):
        return deepcopy(self.objects.get(path,{}))
    def exists(self,path):
        return path in self.objects or path in self.parents
    def parent(self,path):
        return self.parents.get(path,"")


def test_damage_flag_inheritance_keeps_declaring_source_and_explicit_false():
    packages=FakePackages({"/base":{"IgnoreHeadShotBonus":1,"AttackData":{"Amount":10}},
                           "/child":{"IgnoreHeadShotBonus":0,"AttackData":{"ProcChance":.25}}},
                          {"/child":"/base"})
    assert audit.declaration(packages,"/child",("IgnoreHeadShotBonus",))=="/child"
    assert audit.declaration(packages,"/child",("AttackData","Amount"))=="/base"
    fields=audit.relevant_fields(packages,"/child",{"IgnoreHeadShotBonus":0})
    assert fields==[{"field":"IgnoreHeadShotBonus","value":0,"declaration":"/child"}]


def test_list_replacement_does_not_borrow_parent_mode_declarations():
    packages=FakePackages({"/base":{"Behaviors":[{"ApplyOnHit":1}]},
                           "/child":{"Behaviors":[{"ApplyOnKill":1}]}},{"/child":"/base"})
    assert audit.declaration(packages,"/child",("Behaviors",0,"ApplyOnKill"))=="/child"
    assert audit.declaration(packages,"/child",("Behaviors",0,"ApplyOnHit")) is None


def test_projectile_classification_includes_native_classes_without_ee_parent():
    packages=FakePackages({}, {"/Lotus/Weapons/Wave":"/Lotus/Types/Weapon/WaveProjectile",
        "/Lotus/Weapons/Blade":"/Lotus/Types/Weapon/RandomProcGlaive",
        "/Lotus/Fx/ProjectileTrail":"/EE/Types/Effects/ParticleSys"})
    assert audit.node_kind(packages,"/Lotus/Weapons/Wave")=="projectile"
    assert audit.node_kind(packages,"/Lotus/Weapons/Blade")=="projectile"
    assert audit.node_kind(packages,"/Lotus/Fx/ProjectileTrail") is None


def test_reference_resolution_uses_owner_then_parent_folder_and_preserves_support():
    packages=FakePackages({"/a/variant/W":{},"/a/Base":{},"/a/P":{},"/a/Effect":{}},
        {"/a/variant/W":"/a/Base","/a/P":"/Lotus/Types/Weapon/BoltoProjectile",
         "/a/Effect":"/EE/Types/Effects/Spawner"})
    assert audit.locate(packages,"/a/variant/W","P")=="/a/P"
    refs=audit.references(packages,"/a/variant/W",{"projectileType":"P","EmbedEffect":"/a/Effect"})
    assert refs==[{"field":"projectileType","target":"/a/P"},{"field":"EmbedEffect","target":"/a/Effect"}]


def test_missing_flags_and_native_hit_types_are_not_converted_to_assumed_rules():
    packages=FakePackages({"/p":{"AttackData":{"HitType":"DHT_PROJECTILE"}}},{})
    fields=audit.relevant_fields(packages,"/p",packages.own("/p"),match_all=True)
    assert fields==[{"field":"AttackData.HitType","value":"DHT_PROJECTILE","declaration":"/p"}]
    assert not any(row["field"] in {"NoProc","NoProcs","CanCrit","ApplyOnKill"} for row in fields)


def test_reference_cycles_do_not_break_native_ancestry():
    packages=FakePackages({}, {"/a":"/b","/b":"/a"})
    assert audit.ancestry(packages,"/a")==["/a","/b"]


def test_send_events_false_is_retained_by_relevant_field_filter():
    packages=FakePackages({"/p":{"SendEvents":0}},{})
    fields=audit.relevant_fields(packages,"/p",packages.own("/p"))
    assert fields==[{"field":"SendEvents","value":0,"declaration":"/p"}]
