# Warframe & Weapon Loadout Build

[中文](README.md) | [English](README.en.md)

A local Warframe Riven analyzer, weapon loadout builder, and Warframe loadout builder. At runtime it reads only the frozen data bundled with the repository. It does not contact a CDN, Warframe Market, the Wiki, Overframe, or any other online service.

> This is an unofficial community project. It is not affiliated with or endorsed by Digital Extremes.

## Features

- **Riven analysis**: scores a Riven from its weapon, disposition, stat count, and roll values; reports per-stat contribution, dynamic T0-T3 gains, recommended negatives, and fatal negatives.
- **Weapon loadouts**: supports guns, melee, Kitguns, Zaws, exalted weapons, stances, Exilus slots, Arcanes, Incarnon branches, Forma, and A/B/C configurations.
- **Automatic search**: reuses evaluated candidates within the same combat context. With automatic Incarnon and Arcane selection both enabled, it also checks joint changes and adopts only builds with a higher combat score. Results remain the best builds found within the search budget.
- **Final evaluation**: Riven analysis compares the main search, elemental seeds and baseline replacement builds on the same three target-hardness nodes. The native core batches independent health variants, sharing initialization while keeping combat state separate.
- **Completed-build refinement**: Automatic builds revisit alternatives in each MOD family, including Galvanized cards discarded by their weak starting state. Standard and deep profiles also check single-card replacements, additions and removals across the complete candidate pool. Only stronger results that preserve the original constraints are adopted.
- **Companions**: companion weapons follow the AI's real behavior (torso shots only, no aiming, no Arcanes, switchable Galvanized stacks); robotic sentinel bodies take 10 sentinel mods with a stats panel, and weapon-relevant ones such as Fired Up count toward damage.
- **Build constraints**: auto builds take required / per-weapon forbidden / global blocked mods and a one-click faction (bane) mod block; right-click an equipped mod to drop it and rebuild.
- **Exalted weapons**: all 35 exalted weapons (including Whipclaw, Shattered Lash, Landslide and Blade Storm) are in the weapon builder, linked to a saved Warframe build for Ability Strength / Efficiency / energy; damage follows the ability figures and Strength, cast-type weapons use per-cast hits with the ability combo; the result shows energy sustain without regeneration and keeps a warning when the ability could not start or chain. Calculations always assume unlimited energy.
- **Riven disposition (2026-10-23)**: every Riven weapon uses 1.2; the old value is shown in brackets.
- **Riven vault**: save Rivens across weapons, browse them by weapon, load one into analysis or a build in one click, and export / import the list.
- **Warframe loadouts**: supports Aura, Exilus and normal mods, Arcanes, Archon Shards, Helminth abilities, Invigorations, conditional effects, capacity, and ability-panel calculations.
- **Target simulation**: includes a local enemy catalog, custom defenses, level scaling, Steel Path, Eximus and Overguard options, armor strip, headshots, and multiple damage metrics.
- **Local assets**: card art, frames, polarities, Warframe portraits, ability icons, and datasets ship with the project. Configurations can be imported or exported, including the compact Warframe Rabbit format.
- **Explicit degradation**: unsupported runtime scripts, projectile components, and conditional mechanics remain visible as `unsupported` / `skipped` diagnostics instead of being guessed.

Tennokai cards currently retain equipment and capacity metadata. Opportunity triggers and subsequent automatic heavy attacks are not modeled, and affected results explicitly disclose that limitation.

Current frozen game-data build: `2026.08.13.13.24`.

## Run From Source

Python 3.11 or newer is required. The server itself uses only the Python standard library and the bundled `vendor/wfarsenal` package.

```powershell
python app.py
```

The default address is <http://127.0.0.1:8765/> and the browser opens automatically. To select an available port:

```powershell
python app.py --port 0
```

On Windows, `run-dev.cmd` provides the same startup path.

An optional Rust core makes searches much faster: with a Rust toolchain installed, run `python tools/build_native.py`; the resulting `vendor/wfarsenal/wfcore.pyd` is loaded automatically. Without it the engine uses its Python implementation, which gives the same results.

## Windows Portable Build

Download `Warframe-Weapon-Loadout-Build-win-x64.exe` from the repository Releases and double-click it. Python and adjacent data or dependency folders are not required. The interface opens in the system browser. Press `Ctrl+C` in the server console to exit.

Bundled resources are extracted to a temporary directory at startup and removed on normal exit. Persistent calculation caches use `%LOCALAPPDATA%\Warframe-Weapon-Loadout-Build\cache`. Loadouts and the theme remain in browser local storage; use import/export to move loadouts between computers. Copying the EXE does not copy browser data.

The server console prints local links to the bundled documentation, license and notices at `/docs/README.md`, `/docs/LICENSE` and `/docs/THIRD_PARTY_NOTICES.md`.

Packaging requires PyInstaller:

```powershell
python -m pip install pyinstaller
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-portable.ps1
```

The executable is written to `.local/artifacts/release/Warframe-Weapon-Loadout-Build-win-x64.exe` with an `.exe.sha256` checksum. Only the EXE is required to run; the checksum is provided to verify the download. `.local/` contains machine-local builds, caches, audits, and archived development material and is never committed.

## Development Checks

Run `python -m pytest -q` for regression tests and `python tools/check_runtime.py` to check the frozen dataset and actual import paths. The loadout, manual simulation and contribution APIs accept an explicit `windowSeconds` (0.1–600 seconds); the default stays 30 seconds. Compared scores must use the same battle window.

The optional WFSim comparison tools require Node.js and PyYAML. They fetch public reference assets and replay builds locally, without submitting board entries or baking caches:

```powershell
python tools/fetch_wfsim_runtime.py --output .local/wfsim-reference
python tools/compare_wfsim_boards.py prepare --runtime .local/wfsim-reference --output .local/wfsim-comparison --weapons laetum nikana_prime --profile fast --window-seconds 30
python tools/compare_wfsim_boards.py run --runtime .local/wfsim-reference --output .local/wfsim-comparison --runs 1000 --workers 2
python tools/compare_wfsim_boards.py summarize --runtime .local/wfsim-reference --output .local/wfsim-comparison
```

Omit `--window-seconds` to use the official board duration. `cross-window --window-seconds 180` replays existing search results at 180 seconds without searching again. Reports retain mapping exclusions, timeouts and disagreements between model rankings. They measure MOD search with fixed Arcanes, evolution choices and exact Riven values; they do not prove a global optimum. Official WASM is the default backend. An optional simfleet native library is checked against its matching build manifest and engine identity before use.

## Repository Layout

```text
app.py                 Local HTTP server and API
frontend/              Chinese web UI and bundled assets
vendor/wfarsenal/      Loadout, damage, and Warframe calculation engine
native/wfcore/         Optional Rust calculation core
data/                  Frozen datasets, source lock, and runtime sidecars
tools/                 Data generation, import, baking, and audit tools
tests/                 Regression tests and fixtures
build-portable.ps1     Windows portable-package builder
THIRD_PARTY_NOTICES.md Third-party provenance and licenses
```

## License

Unless separately noted, project source code is licensed under the [GNU Affero General Public License v3.0](LICENSE), SPDX identifier `AGPL-3.0-only`.

Parts of the calculation engine are ported from or based on [WFSim](https://github.com/magenie33/wfsim) by magenie33 and the WFSim contributors (`AGPL-3.0-or-later`); those parts are distributed here under AGPL-3.0, and source comments name where each comes from. This project is not WFSim and is not endorsed by it; the WFSim name is used only to state that origin. Data, measured rules and benchmark outputs (test fixtures, `CC BY-NC-SA 4.0`) imported from WFSim are credited under its terms.

Some weapon data was read from the [WARFRAME Wiki](https://wiki.warframe.com/); the bundled copy of `Module:Stances/data` is under the wiki's declared `CC BY-NC-SA 3.0`.

*Warframe* is a trademark of Digital Extremes Ltd. Game data, card text, and the artwork, icons, and other images under `frontend/assets/` are the copyright of Digital Extremes. They are not covered by the project's code license, and no rights in them are granted here; anything the rights holder asks to have removed will be removed.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for every source, author, and term.
