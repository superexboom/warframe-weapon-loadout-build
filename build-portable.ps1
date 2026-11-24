[CmdletBinding()]
param(
    [string]$Snapshot,
    [string]$OutputDirectory,
    [switch]$RequireBakedCache,
    [switch]$NoCache
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$artifactsRoot = Join-Path $projectRoot ".local\artifacts"
$releaseRoot = Join-Path $artifactsRoot "release"
if ($OutputDirectory) { $releaseRoot = [IO.Path]::GetFullPath($OutputDirectory) }
$distRoot = Join-Path $artifactsRoot "dist\onefile"
$buildRoot = Join-Path $artifactsRoot "build\onefile"
$appName = "Warframe-Weapon-Loadout-Build"
$packageRoot = Join-Path $buildRoot ("inputs-" + [guid]::NewGuid().ToString('N'))

Set-Location -LiteralPath $projectRoot
$bundleArguments = @('tools/data_pipeline.py', 'bundle', $packageRoot)
if ($Snapshot) { $bundleArguments += @('--snapshot', $Snapshot) }
python @bundleArguments
if ($LASTEXITCODE -ne 0) { throw "Frozen runtime validation failed." }
# Native engine core (Rust, native/wfcore). Without a Rust toolchain the build
# can reuse an existing core or package the Python reference.
if (Get-Command cargo -ErrorAction SilentlyContinue) {
    python tools/build_native.py
    if ($LASTEXITCODE -ne 0) { throw "Native core build failed." }
} else {
    Write-Warning "cargo not found: staging the installed native core if available."
}
$cacheArguments = @('tools/stage_portable_cache.py', $packageRoot)
if ($RequireBakedCache) { $cacheArguments += '--require-cache' }
if ($NoCache) { $cacheArguments += '--no-cache' }
python @cacheArguments
if ($LASTEXITCODE -ne 0) { throw "Runtime source identity or baked cache staging failed." }

$nativeArguments = @()
$nativeCore = Join-Path $packageRoot "wfarsenal\wfcore.pyd"
if (Test-Path -LiteralPath $nativeCore) {
    $nativeArguments = @('--add-binary', "$nativeCore;wfarsenal", '--hidden-import', 'wfarsenal.wfcore')
}
$moduleSourceArguments = foreach ($source in Get-ChildItem -LiteralPath (Join-Path $packageRoot 'wfarsenal') -Filter '*.py' -File) {
    '--add-data'
    "$($source.FullName);wfarsenal"
}
python -m PyInstaller @nativeArguments @moduleSourceArguments `
    --noconfirm `
    --clean `
    --noupx `
    --onefile `
    --name $appName `
    --workpath (Join-Path $buildRoot "work") `
    --specpath (Join-Path $buildRoot "spec") `
    --distpath $distRoot `
    --paths $packageRoot `
    --add-data "$(Join-Path $packageRoot 'frontend');frontend" `
    --add-data "$(Join-Path $packageRoot 'data');data" `
    --add-data "$(Join-Path $packageRoot 'app.py');." `
    --add-data "$(Join-Path $projectRoot 'README.md');." `
    --add-data "$(Join-Path $projectRoot 'README.en.md');." `
    --add-data "$(Join-Path $projectRoot 'LICENSE');." `
    --add-data "$(Join-Path $projectRoot 'THIRD_PARTY_NOTICES.md');." `
    --icon (Join-Path $projectRoot "frontend\assets\riven\riven-icon.ico") `
    (Join-Path $packageRoot 'app.py')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
$executable = Join-Path $releaseRoot "$appName-win-x64.exe"
Copy-Item -LiteralPath (Join-Path $distRoot "$appName.exe") -Destination $executable -Force
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $executable).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$executable.sha256" -Encoding ascii -Value "$hash  $([IO.Path]::GetFileName($executable))"

Write-Host "Single-file executable: $executable"
Write-Host "SHA-256: $hash"
