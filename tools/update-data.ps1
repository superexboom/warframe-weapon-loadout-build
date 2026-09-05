[CmdletBinding()]
param(
    [ValidateSet('check', 'prepare', 'activate', 'rollback')]
    [string]$Action = 'check',
    [string]$Config,
    [string]$Snapshot,
    [string]$Backup,
    [switch]$Sources
)

$ErrorActionPreference = 'Stop'
$arguments = @($Action)
switch ($Action) {
    'check' {
        if ($Sources) {
            if (-not $Config) { throw '-Sources requires -Config.' }
            $arguments += @('--sources', $Config)
        }
    }
    'prepare' {
        if (-not $Config) { throw 'prepare requires -Config.' }
        $arguments += @('--config', $Config)
    }
    'activate' {
        if (-not $Snapshot) { throw 'activate requires -Snapshot.' }
        $arguments += $Snapshot
    }
    'rollback' {
        if (-not $Backup) { throw 'rollback requires -Backup.' }
        $arguments += $Backup
    }
}

& python (Join-Path $PSScriptRoot 'data_pipeline.py') @arguments
if ($LASTEXITCODE -ne 0) { throw "Data pipeline failed with exit code $LASTEXITCODE." }
