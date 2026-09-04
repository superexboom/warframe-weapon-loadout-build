# Warframe & Weapon Loadout Build

[中文](README.md) | [English](README.en.md)

A local Warframe Riven analyzer, weapon loadout builder, and Warframe loadout builder. At runtime it reads only the frozen data bundled with the repository. It does not contact a CDN, Warframe Market, the Wiki, Overframe, or any other online service.

> This is an unofficial community project. It is not affiliated with or endorsed by Digital Extremes.

## Features

- **Riven analysis**: scores a Riven from its weapon, disposition, stat count, and roll values; reports per-stat contribution, dynamic T0-T3 gains, recommended negatives, and fatal negatives.
- **Weapon loadouts**: supports guns, melee, Kitguns, Zaws, exalted weapons, stances, Exilus slots, Arcanes, Incarnon branches, Forma, and A/B/C configurations.
- **Warframe loadouts**: supports Aura, Exilus and normal mods, Arcanes, Archon Shards, Helminth abilities, Invigorations, conditional effects, capacity, and ability-panel calculations.
- **Target simulation**: includes a local enemy catalog, custom defenses, level scaling, Steel Path, Eximus and Overguard options, armor strip, headshots, and multiple damage metrics.
- **Local assets**: card art, frames, polarities, Warframe portraits, ability icons, and datasets ship with the project. Configurations can be imported or exported, including the compact Warframe Rabbit format.
- **Explicit degradation**: unsupported runtime scripts, projectile components, and conditional mechanics remain visible as `unsupported` / `skipped` diagnostics instead of being guessed.

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

## Windows Portable Build

Packaging requires PyInstaller:

```powershell
python -m pip install pyinstaller
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build-portable.ps1
```

The package is written to `.local/artifacts/release/Warframe-Weapon-Loadout-Build-win-x64.zip` together with a SHA-256 checksum. `.local/` contains machine-local builds, caches, audits, and archived development material and is never committed.

## Data Refresh

Weapon, mod, Arcane, enemy, Warframe, and ability data must be refreshed as one version-locked set. Do not mix outputs from different game builds. See [DATA_PIPELINE.md](DATA_PIPELINE.md) for the source lock, generation order, and strict audit process.

Audit the current frozen data without replacing it:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\update-data.ps1
```

## Repository Layout

```text
app.py                 Local HTTP server and API
frontend/              Chinese web UI and bundled assets
vendor/wfarsenal/      Loadout, damage, and Warframe calculation engine
data/                  Frozen datasets, source lock, and runtime sidecars
tools/                 Data generation and audit tools
build-portable.ps1     Windows portable-package builder
DATA_PIPELINE.md       Data provenance and refresh workflow
THIRD_PARTY_NOTICES.md Third-party provenance and licenses
```

## License

Unless separately noted, project source code is licensed under the [GNU Affero General Public License v3.0](LICENSE), SPDX identifier `AGPL-3.0-only`.

Warframe names, artwork, icons, and other Digital Extremes material are not relicensed by the project's source-code license. Third-party components and assets remain subject to their respective terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
