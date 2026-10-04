"""Held-beam direct-hit ramp and idle decay (WFSim 7399c9e, beam.rs)."""
# Exceptions are declared in the pinned weapon YAML. Keys identify the
# source already carried by the audited attack profile; no name guessing.
FLOORS = {
    'amprex':.30,'convectrix':.60,'convectrix_alt':.80,'cycron':.30,
    'embolist':.45,'flux_rifle':.25,'glaxion_vandal':.30,'ignis':.35,
    'ignis_wraith':.35,'kuva_nukor':.30,'nukor':.30,'tenet_cycron':.30,
    'spectra':.25,'spectra_vandal':.25,'phage':.70,
    'phantasma':.15,'phantasma_prime':.15,'quanta':.30,'quanta_vandal':.30,'tenet_quanta':.30,
}


def is_furis_beam(weapon,mode,index):
    return (weapon.get('path') in {'/Lotus/Weapons/Tenno/Pistol/AutoPistol','/Lotus/Weapons/MK1Series/MK1Furis'}
            and int(weapon.get('__selectedFireMode__',index))==1
            and mode.get('isIncarnonForm') is True
            and set((mode.get('damage') or {}).get('types') or {})=={'DT_FIRE'})


def floor_for(profile):
    name=str(profile.get('source') or '').rsplit('/',1)[-1].removesuffix('.yaml')
    return FLOORS.get(name,.20)


class BeamRamp:
    def __init__(self):
        self.progress=0.
        self.last=None

    def tick(self,time,interval,floor=.2):
        if self.last is not None:
            idle=time-self.last-interval
            if idle>.8:self.progress=max(0.,self.progress-(idle-.8)/2.)
        value=floor+(1.-floor)*self.progress
        self.progress=min(1.,self.progress+interval/.6)
        self.last=time
        return value
