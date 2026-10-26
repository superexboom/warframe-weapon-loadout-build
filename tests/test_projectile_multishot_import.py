from copy import deepcopy
from tools.repair_projectile_multishot import repair_profiles


class Packages:
    def __init__(self,root,rows):self.root,self.rows=root,rows
    def resolve(self,path):return self.rows.get(path)
    def _path_to_file(self,path):return self.root/(path.lstrip('/')+'.json')


def test_repairs_projectile_and_children_but_keeps_hitscan_exception(tmp_path):
    payload=dict(auditedAttacks={'/weapon':dict(projectile='/parent',radials=[
        dict(damage={'blast':100.},takes_multishot=False,nativeSource='/parent',nativeField='ExplosiveAttack'),
        dict(damage={'blast':50.},takes_multishot=False,nativeSource='/weapon',nativeField='RadialDamage')],
        clusters=[dict(nativeChild='/child',direct=dict(damage={'impact':10.},takes_multishot=False),
                       radial=dict(damage={'blast':20.},takes_multishot=False))])})
    package=Packages(tmp_path,{'/parent':dict(ExplosiveAttack=dict(Amount=100.)),
                              '/child':dict(AttackData=dict(Amount=10.),ExplosiveAttack=dict(Amount=20.))})
    result=repair_profiles(payload,[],package)
    assert len(result['changed'])==3
    assert payload['auditedAttacks']['/weapon']['radials'][1]['takes_multishot'] is False
    assert len(result['skipped'])==1
    assert repair_profiles(payload,[],package)['changed']==[]


def test_missing_or_mismatched_native_records_never_change_data(tmp_path):
    payload=dict(auditedAttacks={'/weapon':dict(projectile='/parent',radial=dict(damage={'blast':100.},takes_multishot=False))})
    before=deepcopy(payload)
    package=Packages(tmp_path,{'/parent':dict(ExplosiveAttack=dict(Amount=99.))})
    result=repair_profiles(payload,[],package)
    assert not result['changed'] and payload==before


def test_identical_native_lifecycle_alternatives_share_projectile_count(tmp_path):
    payload=dict(auditedAttacks={'/weapon':dict(projectile='/parent',radial=dict(damage={'blast':175.},takes_multishot=False))})
    package=Packages(tmp_path,{'/parent':dict(ExplosiveAttack=dict(Amount=175.),EmbedDeathAttack=dict(Amount=175.))})
    result=repair_profiles(payload,[],package)
    assert len(result['changed'])==1
    assert result['changed'][0]['matchedFields']==['ExplosiveAttack','EmbedDeathAttack']
