"""M8 pool-break inputs shared by Python and native replay."""

import math

from .damage import _float32 as f32


# WFSim magnetic-proxy-inputs.json binds these missing Weakness declarations
# to the exact avatar, controller and selected proxy. Some exports shorten
# the resolved controller to /Basename.
_PROXY_WEAKNESS_BINDINGS = {
    '/Lotus/Types/Enemies/Duviri/Avatars/DuviriMeleeAvatar': (
        '/Lotus/Types/Enemies/Duviri/Avatars/DuviriMeleeTestDamageController',
        '/Lotus/Types/Enemies/Grineer/GrineerAvatars/HitProxies/GrineerHead', 1., 2.),
    '/Lotus/Types/Enemies/Corpus/Spaceman/AIWeek/RifleSpacemanAvatar': (
        '/Lotus/Types/Enemies/Corpus/Spaceman/AIWeek/RifleSpacemanDamageController',
        '/Lotus/Types/Enemies/Corpus/Spaceman/Head', 1., 2.),
    '/Lotus/Types/Enemies/WF1999Infested/InfestedWarframeCapture/InfestedCaptureMutalistAvatar': (
        '/Lotus/Types/Enemies/WF1999Infested/InfestedWarframeCapture/CaptureInfestedTargetScaledDamageController',
        '/Lotus/Types/Enemies/Corpus/Spaceman/Head', 1., 2.),
}


def weapon_weakness(path):
    from .magnetic_weapon_sources import WEAKNESS_BY_WEAPON
    prefix = '/Lotus/'
    if isinstance(path, str) and path.startswith(prefix):
        binding = WEAKNESS_BY_WEAPON.get(path[len(prefix):])
        if binding is not None:
            return binding[0]
    return None


def target_proxy(target):
    """Select the first greatest positive native Weakness in export order."""
    selected = None
    greatest = 0.0
    binding = _PROXY_WEAKNESS_BINDINGS.get(target.get('path'))
    if binding and target.get('damageController') not in (binding[0], '/' + binding[0].rsplit('/', 1)[1]):
        binding = None
    for proxy in target.get('hitProxies') or ():
        if not isinstance(proxy, dict):
            continue
        weakness = proxy.get('weakness')
        if weakness is None and binding and (proxy.get('type'), proxy.get('damageAtten')) == (binding[1], binding[3]):
            weakness = binding[2]
        if not isinstance(weakness, (int, float)) or not math.isfinite(weakness):
            continue
        weakness = f32(weakness)
        if weakness > greatest:
            greatest = weakness
            attenuation = proxy.get('damageAtten')
            selected = (weakness, f32(attenuation)) if (
                isinstance(attenuation, (int, float)) and math.isfinite(attenuation) and attenuation >= 0.
            ) else None
    return selected


def retained_source(maximum, stacks, weakness, proxy, status_factor):
    source = math.trunc(f32(f32(f32(maximum) * f32(.005)) * f32(stacks)))
    if weakness is not None and proxy is not None:
        divisor = f32(1. + f32(max(0., f32(weakness)) * proxy[0]))
        source = math.floor(f32(f32(source / divisor) + .5))
    scaled = f32(f32(source) * status_factor)
    return f32(scaled * proxy[1]) if weakness is not None and proxy is not None else scaled


def electricity_immune(target):
    return any(value in ('DT_ELECTRICITY', 'Electricity', 5)
               for value in (target.get('statusImmunities') or ()))
