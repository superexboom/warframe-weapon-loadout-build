# Offline asset manifest

Runtime code references these local files only; nothing here needs a CDN or a
network request. Apart from the manifests (`ASSETS.md`, `mods/index.json`,
`enemies/index.json`, `data-assets.json`), every image in this directory is
Digital Extremes artwork: it is not covered by the project's AGPL license and no
rights in it are granted. See `THIRD_PARTY_NOTICES.md`.

| Path | Files | Use | Source |
| --- | ---: | --- | --- |
| `mods/art/**` | 2482 | MOD card illustrations (incl. sentinel mods and precepts) and Riven card faces | Official 2D asset export (one `warframe-items` fallback); Riven-only faces (`RivenUpgrades/*`, Status Chance cards) extracted from the game cache |
| `mods/frame/**` | 66 | Rarity frames, Riven art, rank pips | Warframe Companion 5.3.5.0 app package + official 2D asset export |
| `stances/art/**` | 174 | Stance card illustrations | Official 2D asset export |
| `arcanes/*`, `arcanes/frames/*` | 177 | Arcane icons and rarity frames | `warframe-items` image set + official 2D asset export |
| `weapons/*` | 796 | Weapon icons | Official 2D asset export (`Lotus/Interface/Icons/StoreIcons`) |
| `enemies/art/**` | 874 | Enemy icons | Game interface textures (`Lotus/Interface/Icons/Npcs`) |
| `sentinels/*` | 17 | Robotic sentinel portraits | Official 2D asset export (`Lotus/Interface/Icons/StoreIcons/Companions/Sentinels`) |
| `warframes/portraits/*` | 119 | Warframe portraits | `warframe-items` image set |
| `warframes/abilities/*` | 284 | Ability icons | `warframe-items` image set |
| `warframes/mods/*` | 338 | Warframe MOD illustrations | `warframe-items` image set |
| `warframes/shards/*` | 12 | Archon Shard icons | `warframe-items` image set |
| `game/slots/*`, `game/formas/*` | 9 | Aura / Exilus / Stance / Arcane slot marks, Stance and Umbra Forma | Official 2D asset export and Companion menu icons |
| `game/dark-lotus-theme.png` | 1 | Page watermark | WarframeRabbit icon set |
| `riven/riven-icon.png`, `.ico` | 2 | Riven tab / executable icon | WarframeRabbit `IconRivenMod.png` (the `.ico` is resized locally) |
| `riven/riven-template.webp` | 1 | Riven card shell | WFHelper `assets/RivenTemplate.webp` |
| `riven/omega-transition.png` | 1 | Riven face transition mask | Game cache `/Lotus/Interface/Graphics/OmegaModTransition.png`, resized to 256 px |
| `polarities/*`, `elements/*` | 25 | Polarity and damage-type glyphs | WFHelper and Companion icon sets |

Source snapshots:

- WFHelper: commit `b310f18aaa9351cae14b74a4409fbfced6d6b90e` (<https://github.com/WFHelper/WFHelper>, MIT repository license).
- WFCD `warframe-items`: commit `6c90d27600ad98a47a4d4e99bb7550bddfea2217` (<https://github.com/WFCD/warframe-items>, MIT repository license).
- Official 2D asset export of game build `2026.08.13.13.24`, and the Warframe Companion 5.3.5.0 app package (`assets/Resources/common/mods`).
- Textures extracted on 2026-10-20 from the local game cache with Warframe-Exporter-CLI 2.14 (`--extract-textures --texture-format PNG`); cards also in the 2D export were checked pixel-identical, alpha included.

The MIT licenses of WFHelper and `warframe-items` cover those repositories' own
work; they do not replace Digital Extremes' rights in Warframe artwork.

`mods/index.json` records each MOD's art path and `artSource`;
`enemies/index.json` records each enemy icon's source path and SHA-256.
