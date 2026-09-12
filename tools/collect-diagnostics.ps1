param(
    [string]$BridgeDirectory = "$env:APPDATA\Transport Fever 2\tpf2_mcp_bridge",
    [string]$Tpf2StdoutPath = ""
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$defaultStdoutCandidates = @(
    (Join-Path $env:APPDATA 'Transport Fever 2\stdout.txt')
) + (Get-ChildItem -Path 'D:\Steam\userdata\*\1066780\local\crash_dump\stdout.txt' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -ExpandProperty FullName)
if ([string]::IsNullOrWhiteSpace($Tpf2StdoutPath)) {
    $Tpf2StdoutPath = $defaultStdoutCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
}
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$destination = Join-Path $root "diagnostics\$timestamp"
New-Item -ItemType Directory -Force -Path $destination | Out-Null

$sources = @(
    (Join-Path $BridgeDirectory 'heartbeat.json'),
    (Join-Path $BridgeDirectory 'command.json'),
    (Join-Path $BridgeDirectory 'state.json'),
    (Join-Path $BridgeDirectory 'company-probe.json'),
    (Join-Path $BridgeDirectory 'semantic-probe.json'),
    (Join-Path $BridgeDirectory 'operations-probe.json'),
    (Join-Path $BridgeDirectory 'ui-source-probe.json'),
    (Join-Path $BridgeDirectory 'context-probe.json'),
    $Tpf2StdoutPath
)
$copied = @()
foreach ($source in $sources) {
    if (-not [string]::IsNullOrWhiteSpace($source) -and (Test-Path -LiteralPath $source -PathType Leaf)) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $destination (Split-Path -Leaf $source))
        $copied += $source
    }
}
$responseDirectory = Join-Path $BridgeDirectory 'responses'
if (Test-Path -LiteralPath $responseDirectory -PathType Container) {
    $responseDestination = Join-Path $destination 'responses'
    Copy-Item -LiteralPath $responseDirectory -Destination $responseDestination -Recurse
    $copied += $responseDirectory
}
$snapshotPath = Join-Path $BridgeDirectory 'state.json'
if (Test-Path -LiteralPath $snapshotPath -PathType Leaf) {
    $snapshot = $null
    try { $snapshot = Get-Content -Raw -LiteralPath $snapshotPath | ConvertFrom-Json }
    catch { Write-Warning "PowerShell could not parse state.json; preserving the raw snapshot and using Python validation. $($_.Exception.GetType().Name)" }
    if ($null -ne $snapshot) {
        foreach ($collection in @('towns', 'industries', 'stations', 'lines', 'vehicles', 'cargo_types')) {
            $value = $snapshot.$collection
            if ($null -ne $value) {
                [System.IO.File]::WriteAllText((Join-Path $destination "$collection.json"), ($value | ConvertTo-Json -Depth 20), [System.Text.UTF8Encoding]::new($false))
            }
        }
        if ($null -ne $snapshot.company) {
            [System.IO.File]::WriteAllText((Join-Path $destination 'company.json'), ($snapshot.company | ConvertTo-Json -Depth 20), [System.Text.UTF8Encoding]::new($false))
        }
    }
    & python (Join-Path $root 'tools\validate-snapshot.py') (Join-Path $destination 'state.json') --verification (Join-Path $destination 'verification.json')
    if ($LASTEXITCODE -ne 0) { Write-Warning 'Snapshot validation reported failures; see verification.json.' }
}
$gitCommit = $null
try { $gitCommit = (git -C $root rev-parse HEAD 2>$null).Trim(); if ($LASTEXITCODE -ne 0) { $gitCommit = $null } } catch { }
$manifest = @{
    collected_at = (Get-Date).ToString('o')
    bridge_directory = $BridgeDirectory
    stdout_path = $Tpf2StdoutPath
    copied_sources = $copied
    git_commit = $gitCommit
    mod_version = "tpf2_mcp/1"
    schema_version = 1
} | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $destination 'manifest.json'), $manifest, [System.Text.UTF8Encoding]::new($false))
Write-Output "Diagnostics directory: $destination"
if ($copied.Count -eq 0) { Write-Warning 'No diagnostic source files were found; original files were not modified.' }
