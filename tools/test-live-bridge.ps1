param(
    [string]$BridgeDirectory = "",
    [string]$Python = "python"
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $root 'mcp_server\src'
if ([string]::IsNullOrWhiteSpace($BridgeDirectory)) {
    $BridgeDirectory = ((& $Python -c 'from tpf2_mcp.config import bridge_dir; print(bridge_dir())') | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($BridgeDirectory)) { throw 'Unable to locate the installed TPF2 MCP bridge.' }
}
Remove-Item Env:TPF2_MCP_MOCK -ErrorAction SilentlyContinue
$env:TPF2_MCP_BRIDGE_DIR = $BridgeDirectory

function Show-FailureDiagnostics {
    Write-Host "Bridge directory: $BridgeDirectory"
    $heartbeat = Join-Path $BridgeDirectory 'heartbeat.json'
    if (Test-Path -LiteralPath $heartbeat) {
        Write-Host 'Heartbeat state:'
        Get-Content -Raw -LiteralPath $heartbeat
    } else {
        Write-Host 'Heartbeat state: heartbeat.json not found'
    }
}

function Invoke-BridgeCli([string]$Command) {
    $output = & $Python -m tpf2_mcp.cli $Command 2>&1
    if ($LASTEXITCODE -ne 0) { throw ($output | Out-String) }
    return (($output | Out-String) | ConvertFrom-Json)
}

try {
    Write-Host '[1/3] bridge status ... ' -NoNewline
    $status = Invoke-BridgeCli 'status'
    if (-not $status.result.connected) { throw 'bridge is not connected (heartbeat absent, stale, or bridge_ready=false)' }
    Write-Host 'PASS'

    Write-Host '[2/3] ping/pong ...... ' -NoNewline
    $ping = Invoke-BridgeCli 'ping'
    if ($ping.result.message -ne 'pong') { throw 'unexpected ping response' }
    Write-Host 'PASS'

    Write-Host '[3/3] get_game_state . ' -NoNewline
    $state = Invoke-BridgeCli 'game-state'
    if (-not $state.result.game) { throw 'response has no game object' }
    Write-Host 'PASS'
    Write-Host 'LIVE TPF2 TEST PASS'
} catch {
    Write-Host 'FAIL'
    Write-Host "LIVE TPF2 TEST FAIL: $($_.Exception.Message)"
    Show-FailureDiagnostics
    exit 1
}
