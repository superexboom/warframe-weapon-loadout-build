"""Source-bound admission for audited contact and delayed radial damage-event producers."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import sys

CLIENT = 'eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d'
PACKAGES = '00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06'


@lru_cache(maxsize=1)
def producers():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
    try:
        data = json.loads((root/'data/mechanics/damage-event-producers.json').read_text(encoding='utf8'))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    sources = data.get('sources') or {}
    rows = data.get('delayedRadialProducers')
    if (data.get('schemaVersion') != 2 or not isinstance(sources, dict)
            or sources.get('clientSha256') != CLIENT or sources.get('packagesBinSha256') != PACKAGES
            or not isinstance(rows, dict)):
        return {}
    return rows


def producer(component):
    return next((row for row in producers().get(component.get('nativeSource'), ())
                 if row.get('nativeField') == component.get('nativeField')
                 and row.get('nativeRoute') == component.get('nativeRoute')), None)


def admitted(component):
    """Identity, raw field and native contact/delay must all match the audit."""
    row = producer(component)
    if (not isinstance(row, dict) or component.get('nativeField') != row.get('nativeField')
            or not row.get('genericHit') or not row.get('genericCriticalHit')):
        return False
    delay = component.get('native_event_delay_seconds', component.get('impact_delay_seconds'))
    bounds = row.get('nativeDelayRange') or []
    return (isinstance(delay, (int, float)) and not isinstance(delay, bool)
            and len(bounds) == 2 and 0 <= bounds[0] <= delay <= bounds[1]
            and not component.get('headOnly') and not component.get('__embedded')
            and not component.get('bodyOnly'))


def components(profile):
    """Source records for modeled secondary packets, preserving their own fields."""
    return [part for part in [profile.get('radial'), *(profile.get('radials') or ()),
            profile.get('lingering'), profile.get('embedded'),
            *(c.get(k) for c in profile.get('clusters') or () for k in ('direct','radial')),
            *(part for kind in ('normal-parent','extra-ms-parent')
                for part in (profile.get('phantasmaChildren',{}).get(kind,{}) or {}).get('packets',()))]
            if isinstance(part,dict)]


def profile_admitted(profile):
    return any(admitted(part) for part in components(profile))
