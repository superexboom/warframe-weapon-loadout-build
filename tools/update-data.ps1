[CmdletBinding()]
param(
    [string]$Build,
    [switch]$Apply,
    [switch]$SkipAssets,
    [string]$EnemyExport,
    [string]$WikiSnapshot,
    [string]$FontRoot
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$documentsRoot = Split-Path -Parent $projectRoot
$lockPath = Join-Path $projectRoot 'data\source-lock.json'
$lock = Get-Content -LiteralPath $lockPath -Raw -Encoding utf8 | ConvertFrom-Json
if (-not $Build) { $Build = [string]$lock.activeBuild }

$wfArsenal = Join-Path $documentsRoot 'WF_Rever\wf-arsenal'
$sourceExport = Join-Path $wfArsenal "data\export\$Build"
$rawPackages = Join-Path $wfArsenal "data\raw\$Build\packages"
$languages = Join-Path $documentsRoot 'WF_Rever\research\wf-arsenal-external-sources\work\warframe-languages-bin-data'
$warframeItems = Join-Path $documentsRoot 'WF_Rever\research\wf-arsenal-external-sources\work\warframe-items\data'
$blackcat = Join-Path $documentsRoot '黑猫4.0-5.0'
$targetExport = Join-Path $projectRoot "data\export\$Build"
$stage = Join-Path $projectRoot ".local\temp\data-update-$Build"
$auditOutput = Join-Path $projectRoot ".local\audit\source-audit.json"

if (-not $EnemyExport) {
    $EnemyExport = Join-Path $documentsRoot 'WarframeRabbit4.0-deploy-20260724\WRData\git\warframe_public_export_plus\ExportEnemies.json'
}
if (-not $WikiSnapshot) {
    $wikiSource = $lock.sources | Where-Object id -eq 'wiki-abilities' | Select-Object -First 1
    $WikiSnapshot = [IO.Path]::GetFullPath((Join-Path $projectRoot ([string]$wikiSource.path).Replace('/', '\')))
}

function Invoke-Python([string[]]$Arguments) {
    & python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "python failed ($LASTEXITCODE): $($Arguments -join ' ')" }
}

Set-Location -LiteralPath $projectRoot
if (-not $Apply) {
    Invoke-Python @('tools\audit_data_pipeline.py', '--build', $Build, '--output', $auditOutput, '--strict')
    return
}

if (Test-Path -LiteralPath $targetExport) {
    throw "target build already exists; use a new build label instead of overwriting: $targetExport"
}

$copyNames = @(
    'weapons.json', 'warframes.json', 'mods.json', 'enemies.json', 'arcanes.json',
    'manifest.json', 'zaws.json'
)
foreach ($name in $copyNames) {
    $source = Join-Path $sourceExport $name
    if (-not (Test-Path -LiteralPath $source)) { throw "required generated source missing: $source" }
    $payload = Get-Content -LiteralPath $source -Raw -Encoding utf8 | ConvertFrom-Json
    $label = if ($payload.buildLabel) { [string]$payload.buildLabel } elseif ($payload.gameBuild) { [string]$payload.gameBuild } else { $null }
    if ($label -and $label -ne $Build) { throw "source build mismatch: $source = $label, expected $Build" }
}
foreach ($required in @($rawPackages, $languages, $warframeItems, $blackcat, $EnemyExport, $WikiSnapshot)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "required source missing: $required" }
}
if (-not $FontRoot) {
    throw 'Font export root is required for the ability Luau sidecar. Export /Lotus/Powersuits from B.Font/H.Font and pass -FontRoot.'
}
$FontRoot = [IO.Path]::GetFullPath($FontRoot)
if (-not (Test-Path -LiteralPath $FontRoot -PathType Container)) {
    throw "Font export root missing: $FontRoot"
}

New-Item -ItemType Directory -Path $targetExport -Force | Out-Null
New-Item -ItemType Directory -Path $stage -Force | Out-Null
foreach ($name in $copyNames) {
    Copy-Item -LiteralPath (Join-Path $sourceExport $name) -Destination (Join-Path $targetExport $name) -Force
}
if (Test-Path -LiteralPath (Join-Path $sourceExport 'incarnon_defaults.json')) {
    $incarnonPolicy = Get-Content -LiteralPath (Join-Path $sourceExport 'incarnon_defaults.json') -Raw -Encoding utf8 | ConvertFrom-Json
    if ($incarnonPolicy.gameBuild -and [string]$incarnonPolicy.gameBuild -ne $Build) {
        throw "Incarnon policy build mismatch: $($incarnonPolicy.gameBuild) != $Build"
    }
    Copy-Item -LiteralPath (Join-Path $sourceExport 'incarnon_defaults.json') -Destination (Join-Path $targetExport 'incarnon_defaults.json') -Force
}

Invoke-Python @(
    'tools\generate_kitguns.py', '--source-root', $wfArsenal, '--build-label', $Build,
    '--localization', (Join-Path $blackcat 'dist\WRData\data\v2_weapons.json'),
    '--wpep-weapons', (Join-Path $blackcat 'dist\WRData\data\v2_weapons.json'),
    '--output', (Join-Path $targetExport 'kitguns.json')
)
Invoke-Python @(
    'tools\generate_riven_templates.py', '--build', $Build, '--raw-packages', $rawPackages,
    '--localization', (Join-Path $languages 'zh.json'), '--weapons', (Join-Path $targetExport 'weapons.json'),
    '--output', (Join-Path $targetExport 'riven_templates.json')
)

Invoke-Python @(
    'sync_enemy_overrides.py', '--export-dir', $targetExport, '--raw', $EnemyExport,
    '--output', (Join-Path $targetExport 'enemy_overrides.json')
)
Invoke-Python @(
    'sync_incarnon_strings.py', '--build', $Build, '--export-dir', $targetExport,
    '--localization', (Join-Path $languages 'zh.json'), '--output', (Join-Path $targetExport 'incarnon_strings.json')
)
Invoke-Python @(
    'generate_game_data.py', '--build', $Build, '--export-dir', $targetExport,
    '--raw-packages', $rawPackages, '--output-dir', $stage,
    '--rabbit-mods', (Join-Path $blackcat 'dist\WRData\data\v2_mods.json'),
    '--rabbit-weapons', (Join-Path $blackcat 'dist\WRData\data\v2_weapons.json'),
    '--warframe-items', (Join-Path $warframeItems 'json\Mods.json'),
    '--item-i18n', (Join-Path $warframeItems 'json\i18n.json'),
    '--languages', $languages
)
Invoke-Python @(
    'generate_warframe_data.py', '--build', $Build, '--export-dir', $targetExport,
    '--raw', $rawPackages, '--items', $warframeItems,
    '--localization', (Join-Path $languages 'zh.json'), '--wiki', $WikiSnapshot,
    '--output', (Join-Path $stage 'warframe_build_data.json')
)
Invoke-Python @(
    'tools\extract_ability_luau_ir.py', '--catalog', (Join-Path $stage 'warframe_build_data.json'),
    '--packages-root', $rawPackages, '--font-root', $FontRoot,
    '--localization-en', (Join-Path $languages 'en.json'), '--localization-zh', (Join-Path $languages 'zh.json'),
    '--wiki', $WikiSnapshot,
    '--output', (Join-Path $stage 'ability_runtime_fields.json')
)
Invoke-Python @(
    'tools\diff_ability_runtime_fields.py', '--catalog', (Join-Path $stage 'warframe_build_data.json'),
    '--runtime', (Join-Path $stage 'ability_runtime_fields.json'),
    '--output', (Join-Path $stage 'ability_runtime_diff.json')
)
Invoke-Python @(
    'tools\promote_ability_runtime_fields.py', '--catalog', (Join-Path $stage 'warframe_build_data.json'),
    '--runtime', (Join-Path $stage 'ability_runtime_fields.json'),
    '--output', (Join-Path $stage 'warframe_build_data.promoted.json')
)
Move-Item -LiteralPath (Join-Path $stage 'warframe_build_data.promoted.json') -Destination (Join-Path $stage 'warframe_build_data.json') -Force

foreach ($name in @('stances.json', 'utility_mods.json', 'exalted_weapons.json', 'warframe_build_data.json', 'ability_runtime_fields.json', 'ability_runtime_diff.json')) {
    Copy-Item -LiteralPath (Join-Path $stage $name) -Destination (Join-Path $projectRoot "data\$name") -Force
}

if (-not $SkipAssets) {
    Invoke-Python @('tools\bake_archon_frames.py')
    Invoke-Python @(
        'sync_mod_assets.py', '--export-dir', $targetExport,
        '--stances', (Join-Path $projectRoot 'data\stances.json'),
        '--utility-mods', (Join-Path $projectRoot 'data\utility_mods.json'),
        '--arcanes', (Join-Path $targetExport 'arcanes.json')
    )
}

$lock.activeBuild = $Build
foreach ($source in $lock.sources) {
    $relative = ([string]$source.path).Replace('{build}', $Build).Replace('/', '\')
    $resolved = [IO.Path]::GetFullPath((Join-Path $projectRoot $relative))
    if (Test-Path -LiteralPath $resolved -PathType Leaf) {
        $source | Add-Member -NotePropertyName sha256 -NotePropertyValue ((Get-FileHash -Algorithm SHA256 -LiteralPath $resolved).Hash.ToLowerInvariant()) -Force
        if ($source.PSObject.Properties.Name -contains 'pinnedBuild') { $source.pinnedBuild = $Build }
    }
    $parser = [string]$source.parser
    if ($parser) {
        $parserPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $parser.Replace('/', '\')))
        if (-not (Test-Path -LiteralPath $parserPath -PathType Leaf)) {
            throw "source parser missing: $parserPath"
        }
        $source | Add-Member -NotePropertyName parserSha256 -NotePropertyValue ((Get-FileHash -Algorithm SHA256 -LiteralPath $parserPath).Hash.ToLowerInvariant()) -Force
    }
}
$lock | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $lockPath -Encoding utf8
Invoke-Python @('tools\audit_data_pipeline.py', '--build', $Build, '--output', $auditOutput, '--strict')
Write-Host "Prepared and activated frozen build: $Build"
