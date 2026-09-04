[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$artifactsRoot = Join-Path $projectRoot ".local\artifacts"
$releaseRoot = Join-Path $artifactsRoot "release"
$distRoot = Join-Path $artifactsRoot "dist"
$buildRoot = Join-Path $artifactsRoot "build"
$appName = "Warframe-Weapon-Loadout-Build"

Set-Location -LiteralPath $projectRoot
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name $appName `
    --workpath (Join-Path $buildRoot "work") `
    --specpath (Join-Path $buildRoot "spec") `
    --distpath $distRoot `
    --paths (Join-Path $projectRoot "vendor") `
    --add-data "$(Join-Path $projectRoot 'frontend');frontend" `
    --add-data "$(Join-Path $projectRoot 'data');data" `
    --icon (Join-Path $projectRoot "frontend\assets\riven\riven-icon.ico") `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$bundle = Join-Path $distRoot $appName
foreach ($name in @("README.md", "README.en.md", "LICENSE", "THIRD_PARTY_NOTICES.md")) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $name) -Destination $bundle -Force
}

New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
$archive = Join-Path $releaseRoot "$appName-win-x64.zip"
if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
Compress-Archive -Path $bundle -DestinationPath $archive -CompressionLevel Optimal
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$archive.sha256" -Encoding ascii -Value "$hash  $([IO.Path]::GetFileName($archive))"

Write-Host "Portable package: $archive"
Write-Host "SHA-256: $hash"
