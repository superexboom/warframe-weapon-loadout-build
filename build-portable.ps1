[CmdletBinding()]
param(
    [string]$Snapshot,
    [string]$OutputDirectory
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
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name $appName `
    --workpath (Join-Path $buildRoot "work") `
    --specpath (Join-Path $buildRoot "spec") `
    --distpath $distRoot `
    --paths (Join-Path $projectRoot "vendor") `
    --add-data "$(Join-Path $packageRoot 'frontend');frontend" `
    --add-data "$(Join-Path $packageRoot 'data');data" `
    --add-data "$(Join-Path $projectRoot 'vendor\wfarsenal\optimizer.py');wfarsenal" `
    --add-data "$(Join-Path $projectRoot 'README.md');." `
    --add-data "$(Join-Path $projectRoot 'README.en.md');." `
    --add-data "$(Join-Path $projectRoot 'LICENSE');." `
    --add-data "$(Join-Path $projectRoot 'THIRD_PARTY_NOTICES.md');." `
    --icon (Join-Path $projectRoot "frontend\assets\riven\riven-icon.ico") `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
$executable = Join-Path $releaseRoot "$appName-win-x64.exe"
Copy-Item -LiteralPath (Join-Path $distRoot "$appName.exe") -Destination $executable -Force
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $executable).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$executable.sha256" -Encoding ascii -Value "$hash  $([IO.Path]::GetFileName($executable))"

Write-Host "Single-file executable: $executable"
Write-Host "SHA-256: $hash"
