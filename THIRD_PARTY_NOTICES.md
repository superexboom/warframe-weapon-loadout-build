# Third-party notices

This repository combines project code with material owned by others. Each item
below keeps its owner and terms; the project's code license does not relicense
any of it.

| What | Where | Owner / terms |
| --- | --- | --- |
| Project code | everything not listed below | `AGPL-3.0-only` (see `LICENSE`) |
| Code and rules derived from WFSim | engine modules listed in [WFSim](#wfsim) | WFSim by magenie33, `AGPL-3.0-or-later`; distributed here under AGPL-3.0 |
| Data imported from WFSim | `data/mechanics/combat-reference.json`, `sniper-mechanics.json`, `battery-profiles.json`, parts of `data/weapon_mechanics_overrides.json` | game facts, credited to WFSim |
| WFSim benchmark outputs | `tests/fixtures/*_board_20260926.json` | WFSim, `CC BY-NC-SA 4.0` |
| WARFRAME Wiki module copy | `data/sources/wiki/stance_data_2026-08-23.lua` | WARFRAME Wiki contributors, `CC BY-NC-SA 3.0` |
| Game data, text and artwork | `data/export/`, data sidecars, `frontend/assets/`, `tools/archon_frame_source/` | © Digital Extremes Ltd. — no license granted |
| WFHelper assets | Riven card shell, polarity and element icons | WFHelper, MIT (artwork remains Digital Extremes') |
| warframe-items data and images | generation inputs; Warframe portraits, Warframe-mod, Arcane, ability and shard icons; one MOD illustration | WFCD, MIT (artwork remains Digital Extremes') |
| Overframe ability statistics | `data/overframe_abilitystats.json` | game facts, credited to Overframe |

## License scope

Project-authored source code that does not carry a separate notice, including
the bundled `vendor/wfarsenal` calculation engine, the `native/wfcore` Rust core
and this project's modifications to derived code, is distributed under
`AGPL-3.0-only` as stated in `LICENSE`.

The AGPL does not cover Warframe names, artwork, icons, card text, extracted game
data, or the Creative Commons material listed above. Files under a Creative
Commons license keep that license, including its NonCommercial and ShareAlike
terms, when redistributed with this project.

## WFSim

**WFSim** — <https://github.com/magenie33/wfsim>, by **magenie33** (maintainer and
copyright holder) and the WFSim contributors. Code license: `AGPL-3.0-or-later`.
Data terms: WFSim's `LICENSE-DATA.md`. Name: WFSim's `TRADEMARK.md`.

This project is **based in part on WFSim**. It is a separate project with its own
name: it is not WFSim, is not maintained by the WFSim project, and is not
endorsed by it. The WFSim name is used here only to state where material comes
from, and the WFSim logo is not used.

### Derived code and rules

The following parts of this project's engine are ports of WFSim code, or
transcriptions of mechanics documented in WFSim's `docs/MECHANICS.md`,
`docs/OPTIMIZER.md`, `docs/BUFFS.md` and `docs/UI.md`. Source comments in the
code name the WFSim file, section or commit each rule comes from (pinned commits
include `b98b3d4`, `69e6a139`, `7399c9e`, `5809c383` and `c993d6ffc`).

- `vendor/wfarsenal/damage.py` — windowed status-stack ramp and InstantRespawn
  semantics; DoT tick groups with the +1 accumulator; the single-target Gas
  cloud; per-hit damage-type quantization; base crit-damage quantization;
  per-proc DoT seeds by crit tier; per-trigger ammo cost; emergent trigger
  stacking (`StackPolicy::Emergent`); the kill score as a rate; weak-point,
  shotgun status-chance and faction-bracket conventions.
- `vendor/wfarsenal/combat_replay.py`, `manual_combat.py` — the event-replay
  model (pause and reload handling after `fight/after.rs`, pellet status
  payloads after `fight/pellet.rs`, syndicate and debuff behaviour from WFSim
  data), shield-gate leak, pile detonation and magazine-less weapons.
- `vendor/wfarsenal/beam_ramp.py` — held-beam ramp and idle decay, ported from
  WFSim `beam.rs`.
- `vendor/wfarsenal/optimizer.py` — the search-scope model and the full 1-swap
  neighbourhood hill-climb (`optimizer/search.rs`), and profile budgeting.
- `vendor/wfarsenal/sniper.py`, `event_profiles.py`, `status_arcanes.py`,
  `arcane_runtime.py`, `deferred_spread.py` — sniper combo, battery and spin-up
  semantics, the Encumber pool, Arcane stacking and spread sampling.
- `native/wfcore/src/` — the Rust ports of the rules above.
- `app.py`, `frontend/app.js` — Archgun-on-ground Arcane slots and the KPM
  replay view follow WFSim's conventions.
- `tools/` — importers that read WFSim's data files (`import_combat_reference.py`,
  `import_sniper_mechanics.py`, `import_battery_profiles.py` and related
  `import_*` / `refresh_*` scripts) and comparison tools that run WFSim's
  published runtime locally (`fetch_wfsim_runtime.py`, `run_reference_wasm.mjs`,
  `wfsim_sweep.py`, `compare_*`). No WFSim executable, WebAssembly module or
  website asset is redistributed.

WFSim's code is `AGPL-3.0-or-later`; the derived parts are distributed here
under AGPL-3.0, keeping this attribution.

### Data, measurements and benchmark outputs

- **Game data.** `data/mechanics/combat-reference.json` records WFSim source
  commit `b98b3d456393131857e1c0e247b19aac6ecc08f4`: its weak-point charged
  Incarnon profiles, syndicate families, enemy-affinity reference and audited
  base-attack records were imported from WFSim's YAML data, each with its source
  path and SHA-256. Internal identities were matched independently against local
  game-package fields. `sniper-mechanics.json`, `battery-profiles.json` and
  entries of `data/weapon_mechanics_overrides.json` were cross-checked against
  WFSim's weapon data. These are facts about the game, credited to WFSim.
- **Measurements.** Code comments cite WFSim's in-game measurement entries
  (`M27`, `M57`, `M58`, `M61`, `M80`, `M89`, `M100`, `M102`, `M108`, `M114`, …).
  This project implements the observed rules; it does not reproduce the
  write-ups. WFSim publishes its measurement corpus under `CC BY-NC-SA 4.0`,
  credited to WFSim and to the contributor each entry names.
- **Benchmark outputs.** `tests/fixtures/archgun_board_20260926.json`,
  `nonmelee_board_20260926.json` and `status_arcane_board_20260926.json` contain
  sample board rows from wfsim.app and reference figures from running WFSim's
  engine, used as regression fixtures. They are WFSim output, licensed
  `CC BY-NC-SA 4.0` with attribution to WFSim, and are not covered by this
  project's AGPL license.

## WARFRAME Wiki

Weapon statistics in `data/wiki_weapon_overrides.json` were read from the
[WARFRAME Wiki](https://wiki.warframe.com/) (`Module:Weapons/data/*` through the
MediaWiki API) and stored as facts in this project's own schema.

`data/sources/wiki/stance_data_2026-08-23.lua` is a copy of the wiki page
[`Module:Stances/data`](https://wiki.warframe.com/w/Module:Stances/data) as of
2026-08-23, by the WARFRAME Wiki contributors. The wiki declares its content
under [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/); that
license applies to this file, which is kept unmodified. `data/stances.json` is
generated from it together with game data.

`data/mechanics/warframe-forms.json` also cross-checks Sevagoth Shadow ability
rank vectors against the official ability articles (Embrace, Consume, Death's
Harvest, Reunite and Exalted Shadow). The four corresponding ability icons are
served from the same official Wiki and bundled locally; they remain Digital
Extremes artwork rather than project-licensed assets.

## Digital Extremes

*Warframe* is a trademark of Digital Extremes Ltd. This is an unofficial
community tool, not affiliated with or endorsed by Digital Extremes. No Warframe
or Digital Extremes logo is used as this project's branding.

The following are the copyright of Digital Extremes Ltd. They are not licensed by
this project, are not covered by the AGPL, and no grant is made here:

- **Game data and text** — `data/export/` and the data sidecars under `data/`,
  generated from the game client's packages, `Languages.bin` localization,
  Digital Extremes' Public Export, and analysis of the game client; MOD, Arcane,
  ability and evolution card text and localized names.
- **Artwork** — everything under `frontend/assets/` except the
  project-written manifests (`ASSETS.md`, `index.json`, `data-assets.json`):
  MOD illustrations and card frames (from the official 2D
  asset export and the Warframe Companion 5.3.5.0 app package), weapon icons,
  enemy icons (game interface textures), Warframe portraits, ability, Arcane and
  Archon Shard icons, stance art, polarity and element glyphs, Riven art and the
  Riven app icon (`riven/riven-icon.png` / `.ico`).
- **Source textures** — `tools/archon_frame_source/` (in-game card renders
  published on the WARFRAME Wiki and client textures used to rebuild Archon MOD
  frames).

They are included so that the item a user is configuring can be recognized and
its in-game wording compared with the calculation. Anyone redistributing this
repository should reach their own conclusion about this material. Anything
Digital Extremes asks to have removed will be removed; open an issue on this
repository.

## WFHelper assets

`frontend/assets/riven/riven-template.webp`, polarity icons, and element icons were copied from WFHelper at commit `b310f18aaa9351cae14b74a4409fbfced6d6b90e`. The MIT license below covers WFHelper's own work; the artwork itself remains Digital Extremes'.

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

## warframe-items

`WFCD/warframe-items` (<https://github.com/WFCD/warframe-items>, commit `6c90d27600ad98a47a4d4e99bb7550bddfea2217`) supplied generation inputs (`Mods.json` and `i18n.json`) and its image set for Warframe portraits, Warframe-mod, Arcane, ability and Archon Shard icons, and `frontend/assets/mods/art/WarframeItems/NightwaveLasGooPistolAugmentMod.jpg`. The MIT license below covers that repository's own work; the images are Digital Extremes artwork.

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

## Overframe

`data/overframe_abilitystats.json` holds Warframe ability statistics (labels,
values and scaling modifiers per ability) read from
[Overframe](https://overframe.gg/); the game generator uses it to label and fill
ability panels. The ordinary Shadow's rank-30 panel and independent loadout
entry were cross-checked against its public Overframe page. Overframe is
credited as the source; this project is not affiliated with Overframe.

## Design references

The interaction model was studied against the MIT-licensed open-source RivenMirror project (`pa001024/riven-mirror`, commit `8dd93e4`) and the open-source Sub2API interface. No RivenMirror application code or branding is included.
