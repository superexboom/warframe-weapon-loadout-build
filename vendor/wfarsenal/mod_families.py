"""Authoritative Warframe Mod exclusivity family helpers.

Loads ``data/mechanics/mod-families.json`` (derived from ``Packages.bin`` type
inheritance matching ``Warframe.x64.exe`` ``0x14171CE28`` & ``0x14118FC40``)
and provides fast cached lookups across Warframe, weapon, sentinel, and
companion build validators and optimizers.
"""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping


def _runtime_root() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    if (base / "data/mechanics/mod-families.json").is_file():
        return base
    env_root = os.environ.get("WF_RIVEN_ROOT")
    if env_root:
        cand = Path(env_root).resolve()
        if (cand / "data/mechanics/mod-families.json").is_file():
            return cand
    return base


def _clean_path(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().replace("\\", "/")
    if "#" in text:
        text = text.split("#", 1)[0].strip()
    if len(text) > 1:
        text = text.rstrip("/")
    return text


@lru_cache(maxsize=1)
def _loaded_tables() -> tuple[
    dict[str, str],
    dict[str, str],
    dict[str, frozenset[str]],
    dict[str, list[str]],
    frozenset[str],
]:
    path = _runtime_root() / "data/mechanics/mod-families.json"
    if not path.is_file():
        return {}, {}, {}, {}, frozenset()
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw_families = raw.get("families") if isinstance(raw, Mapping) else None
    orig_by_lower: dict[str, str] = {}
    lower_by_lower: dict[str, str] = {}
    if isinstance(raw_families, Mapping):
        for mod_p, fam_p in raw_families.items():
            mp = _clean_path(mod_p)
            fp = _clean_path(fam_p)
            if mp and fp:
                mp_low = mp.lower()
                orig_by_lower[mp_low] = fp
                lower_by_lower[mp_low] = fp.lower()

    raw_extra = raw.get("equipmentAdditionalBases") if isinstance(raw, Mapping) else None
    extra_lower: dict[str, frozenset[str]] = {}
    extra_orig: dict[str, list[str]] = {}
    if isinstance(raw_extra, Mapping):
        for eq_p, bases in raw_extra.items():
            ep = _clean_path(eq_p)
            if not ep or not isinstance(bases, (list, tuple)):
                continue
            cleaned_bases = [_clean_path(b) for b in bases if _clean_path(b)]
            extra_orig[ep] = cleaned_bases
            extra_lower[ep.lower()] = frozenset(b.lower() for b in cleaned_bases)

    raw_unreleased = raw.get("unreleasedWarframeMods") if isinstance(raw, Mapping) else None
    unreleased_set: frozenset[str] = (
        frozenset(
            _clean_path(p).lower()
            for p in raw_unreleased
            if _clean_path(p)
        )
        if isinstance(raw_unreleased, (list, tuple))
        else frozenset()
    )
    return orig_by_lower, lower_by_lower, extra_lower, extra_orig, unreleased_set


def authoritative_mod_family(
    mod_path: str | None,
    fallback_family: str | None = None,
) -> str | None:
    """Return original-cased authoritative ``modFamily`` path for catalog rows."""
    orig_by_lower, _, _, _, _ = _loaded_tables()
    mp = _clean_path(mod_path)
    if mp:
        found = orig_by_lower.get(mp.lower())
        if found:
            return found
    fb = _clean_path(fallback_family)
    if fb:
        return fb
    return mp or None


def canonical_mod_family(
    mod_path: str | Mapping[str, Any] | None,
    fallback_family: str | None = None,
    equip_path: str | None = None,
) -> str:
    """Return lowercased canonical family key (never suffixed with ``#compatibility``).

    When ``equip_path`` matches ``equipmentAdditionalBases`` (such as Dante's
    ``/Lotus/Powersuits/Pagemaster/ExaltedBook`` Noctua or Jade's ``Choir``) and
    the mod's base family is listed in that equipment's additional bases, the
    climb stops before that base — returning the mod's own normalized path so
    distinct Tome Invocations/Canticles (or Jade Auras) can coexist.
    """
    if isinstance(mod_path, Mapping):
        row = mod_path
        raw_path = row.get("path")
        if fallback_family is None:
            fallback_family = (
                row.get("modFamily")
                or row.get("family")
                or row.get("nameTag")
                or row.get("nameEn")
                or row.get("nameInternal")
            )
    else:
        raw_path = mod_path

    _, lower_by_lower, extra_lower, _, _ = _loaded_tables()
    mp_low = _clean_path(raw_path).lower()
    fb_low = _clean_path(fallback_family).lower()

    fam_low = lower_by_lower.get(mp_low) if mp_low else None
    if not fam_low:
        fam_low = fb_low or mp_low
    if not fam_low:
        return ""

    if equip_path and mp_low:
        ep_low = _clean_path(equip_path).lower()
        extra_bases = extra_lower.get(ep_low)
        if extra_bases and fam_low in extra_bases:
            return mp_low
    return fam_low


def is_unreleased_warframe_mod(mod_path: str | None) -> bool:
    """Return True if ``mod_path`` is a flawed/unreleased Warframe placeholder mod."""
    mp_low = _clean_path(mod_path).lower()
    if not mp_low:
        return False
    _, _, _, _, unreleased_set = _loaded_tables()
    return mp_low in unreleased_set


def equipment_additional_bases() -> dict[str, list[str]]:
    """Return a copy of ``equipmentAdditionalBases`` for catalog/UI metadata."""
    _, _, _, extra_orig, _ = _loaded_tables()
    return {k: list(v) for k, v in extra_orig.items()}
