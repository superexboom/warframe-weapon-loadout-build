from __future__ import annotations

def base_profile(weapon, fire_mode=0):
    from .manual_combat import reference
    if weapon.get('isIncarnonForm') or int(weapon.get('__selectedFireMode__', fire_mode)) != 0:
        return {}
    profile = reference().get('auditedAttacks', {}).get(weapon.get('path'), {})
    mode = (weapon.get('fireModes') or [{}])[fire_mode]
    total = sum((mode.get('damage', {}).get('types') or {}).values())
    if abs(total - profile.get('directTotal', total)) > 0.02:
        return {}
    return profile
