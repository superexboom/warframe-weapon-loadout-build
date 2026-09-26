# Third-party notices

## License scope

Project-authored source code that does not carry a separate notice, including the bundled `vendor/wfarsenal` calculation engine and this project's modifications to it, is distributed under `AGPL-3.0-only` as stated in `LICENSE`.

The AGPL source-code license does not relicense Warframe names, artwork, icons, extracted game data, or other third-party material. Those items remain subject to their owners' rights and the notices below.

## WFHelper assets

`frontend/assets/riven/riven-template.webp`, polarity icons, and element icons were copied from WFHelper at commit `b310f18aaa9351cae14b74a4409fbfced6d6b90e`.

MIT License

Copyright (c) 2026 WFHelper

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Warframe artwork and names

Warframe and related artwork, names, and icons are property of Digital Extremes. This is an unofficial community tool and is not endorsed by Digital Extremes.

The MOD illustrations and `OmegaMod.png` Riven art were selected from the local WarframeRabbit official 2D export. Bronze, Silver, Gold, Legendary, Riven/Omega, and rank layers were selected from the official Warframe Companion 5.3.5.0 package. They remain Digital Extremes artwork.

## warframe-items fallback

`frontend/assets/mods/art/WarframeItems/NightwaveLasGooPistolAugmentMod.jpg` was copied from `WFCD/warframe-items` at commit `6c90d27600ad98a47a4d4e99bb7550bddfea2217`.

MIT License

Copyright (c) 2017 Kaptard

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Design references

The interaction model was studied against the MIT-licensed open-source RivenMirror project (`pa001024/riven-mirror`, commit `8dd93e4`) and the open-source Sub2API interface. No RivenMirror application code or branding is included.

## wfsim mechanics derivation

Damage-mechanics rules in `vendor/wfarsenal/damage.py` were derived from the
AGPL-3.0-or-later project **wfsim** (`magenie33/wfsim`, commit `main` at
2026-09) — specifically its `docs/MECHANICS.md`, `docs/MEASUREMENTS.md`,
`docs/OPTIMIZER.md`, `docs/RECORD.md` and `docs/UI.md`. The following
behaviours in this project's engine are transcriptions of rules documented
there (each carries a source comment in the code):

- **Windowed stack ramp** (`windowed_status_damage`): per-step live stack
  levels instead of steady-state assumptions, pool-transition-aware
  amplifiers (overguard→magnetic, health→viral read at tick time), and the
  InstantRespawn kill/respawn semantics including ramp-clock reset.
  Source: wfsim `docs/MECHANICS.md` §6 snapshot-vs-live boundary;
  `docs/UI.md` §TargetMode::InstantRespawn.
- **DoT +1 accumulator** (M58): each DoT tick group carries a +1 flat
  accumulator; Heat/Electricity/Gas consolidate into one shared group while
  Slash and Toxin tick independently per stack. Source: wfsim
  `docs/MEASUREMENTS.md` M58.
- **Single-target Gas cloud**: Gas is a 10-slot cloud on the target; against
  a lone target only the cloud's own tick counts, not one full expected-proc
  payload per pellet. Source: wfsim `docs/MECHANICS.md` §6 DoT table.
- **Kill score as a rate** (KPM): whole kills plus the fractional progress
  of the current body's pools, reported per minute. Source: wfsim
  `docs/UI.md` §"The kill score is reported as a RATE".
- **Per-hit damage-type quantization** (`quantize_damage_vector`): each type
  value snaps to units of `ModdedBase/32` before crit/faction/armour
  multipliers; the denominator is ModdedBase (IPS-only scaled base), with
  elemental additions in the numerator only. Source: wfsim
  `docs/MEASUREMENTS.md` M57 (`M57-quantization-divides-by-moddedbase.md`),
  `M80`.
- **Base crit-damage quantization** (`quantize_base_crit_damage`): the base
  crit multiplier quantizes to steps of `32/4095`; flat CD bonuses add
  before quantization, relative (%) mods multiply after. Source: wfsim
  `docs/MECHANICS.md` §5 Quantization.
- **Per-proc DoT seeds by crit tier** (`crit_tier_seed_distribution`): each
  proc stores the damage snapshot of the hit that caused it — that hit's
  crit tier included — rather than the panel's crit-averaged damage; the
  tier decomposition (floor(cc) guaranteed + fractional tier+1) reproduces
  the closed-form average exactly while preserving the distribution for
  per-tick amplifiers. Source: wfsim `docs/MECHANICS.md` §6 "Every DoT has
  a PARENT"; §5 crit tiers.
- **Per-trigger ammo cost in sustained rate** (`ModdedStats.ammo_cost`,
  `sustained_attack_rate`): modes with `ammoCost > 1` (Twin Grakatas) spend
  the magazine at `triggers = magazine / ammo_cost`, changing reload
  cadence. Source: wfsim `docs/MECHANICS.md` §2 "Continuous ammo cost"
  (ammo_cost multiplies the MAGAZINE spend); wiki Twin Grakatas (120 mag /
  2 per trigger = 60 triggers).

Both projects are AGPL-3.0, so this derivation keeps the combined work under
the same license. The "WFSim" name and logo are not used here; see wfsim's
`TRADEMARK.md` for its branding terms.


### Pinned combat-reference refresh (2026-09-26)

`data/mechanics/combat-reference.json` records WFSim source commit
`b98b3d456393131857e1c0e247b19aac6ecc08f4`. Its 65 weakpoint-charged
Incarnon profiles, six syndicate families and enemy-affinity reference data
were imported from that project's YAML data. Internal syndicate identities
were independently matched against local game-package UpgradeObject fields,
with hashes in packageEvidence. No WFSim executable or website assets are
redistributed by this change.

`vendor/wfarsenal/combat_replay.py` and `manual_combat.py` implement an
expected-count event model informed by those records, the debuff YAML files,
and MECHANICS/MEASUREMENTS. They do not claim numerical equivalence to the
reference's random simulation or a general-purpose Lua runtime. The original
AGPL licensing and attribution above continue to apply.

The follow-up event audit also imports one audited direct-hit charged Torid
profile (66 charging profiles total) and seven base-attack records. Each audited
attack records its source YAML path and SHA-256; runtime application is gated by
weapon identity, mode, and matching base damage. Dual Toxocyst frenzy is derived
from the local 2026.09.22.16.46 game-package upgrade and direct-headshot condition,
with original source paths and hash retained. The importer can reproduce the
current records into an isolated output directory. Further direct-hit profiles
are excluded until their runtime economics have been audited.
