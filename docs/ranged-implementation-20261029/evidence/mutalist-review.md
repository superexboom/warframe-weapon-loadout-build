# Mutalist final self-review and engine freeze

Root-requested review completed with two-file focused change only: vendor/wfarsenal/manual_combat.py and tests/test_mutalist_source_owned_fields.py. No Rust/new field/data changes. Existing normal source-owned native library remains valid; this fix preserves CoSpec into the existing native stats reader rather than altering ABI.

## Confirmed and fixed

The conversion `replace(embed[0],multishot=1.)` discarded the original5toxin EmbedAttack's private `_co_spec`. With a real CO bucket, manual_combat.live_variant returnedNone, falling back to full apply instead of the intended fractional CO optimization. New code shallow-copies the full stats object then sets multishot1, preserving CoSpec and private context. New regression directly asserts spec presence, non-None live_variant and equal per-type Embed/swarm damage versus exact full resolver at0.5live types; it also asserts Embed CO changes while independent3toxin does not.

Tests' `run` helper previously assigned native_replay.ENABLED permanently. It now saves/restores through try/finally, with explicit regression proving restoration. Each actual-production native toggle uses pytest monkeypatch teardown.

## Element alias finding

WEAPON_FIRE_DAMAGE/WEAPON_ELECTRICITY_DAMAGE/WEAPON_POISON_DAMAGE/WEAPON_FREEZE_DAMAGE are UI labels / legacy test inputs, NOT accepted aliases in this checkout's damage or Rust MOD core. Python SUPPORTED_WEAPON_UPGRADE_TYPES omits them; _bucket preserves original keys, and only canonical WEAPON_PERCENT_BASE_DAMAGE_ADDED is consumed. Rust mods.rs bucket list likewise has no alias and applies the canonical ordinal route. Direct _apply_mods_spec_py confirms aliases are returned in unsupported and add no damage. There is therefore no existing shared alias normalizer to reuse in source allowlist. Passing those names only into swarm would silently grant element damage there while the arrow ignores it, so this review does not fabricate such compatibility.

The audited ordinary element route remains canonical WEAPON_PERCENT_BASE_DAMAGE_ADDED with damage_type; new tests check Heat->Gas,Electricity->Corrosive,Poison->Poison,Cold->Viral on independent3toxin. Four explicit alias tests verify source trigger stays3toxin and direct engine marks unsupported. Broad API alias support, if desired later, must normalize shared effects consistently before both direct and fields; it is a separate feature, not an unchecked allowlist expansion.

## Production pathways

New test reads actual production combat-reference periodicTriggers and app.EXPORTS with no contract/profile monkeypatch. Uses actual selected Mutalist Cernos weapon plus legal multishot, canonicalElectricity and CO effects. It compares Python search_combat.window to native health batch across4health scales including duplicate context, confirms actual batch counter increases4 and no state carry; compares actual manual prepare/replay to scalar search on the same10000health/100armour4scontext, with active owner fields. Cached scores are isolated by replacing _REPLAYS and clearing bound stats caches; only engine/data reads, no production persistence.

Mutalist focused source-owned tests now32cases (old21+11). No further engine edits intended; ready for root fullsuite freeze. Mandonel finite7s field intentionally deferred per parent pending DHT_DOT proc acceptance.
