param(
    [string]$Python = 'python',
    [string]$ListenAddress = '127.0.0.1',
    [ValidateRange(1, 65535)][int]$Port = 8766
)
$ErrorActionPreference = 'Stop'
$modRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$launcher = Join-Path $modRoot 'mcp_server/start_http_server.py'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "MCP launcher missing: $launcher" }
$pythonExe = (Get-Command $Python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$previous = @{}
$settings = @{
    TPF2_MCP_MOD_DIR = $modRoot
    TPF2_MCP_BRIDGE_DIR = (Join-Path $modRoot 'bridge')
    TPF2_MCP_STATE_DIR = (Join-Path $modRoot 'var/mcp')
    PYTHONPYCACHEPREFIX = (Join-Path $modRoot 'var/python-cache')
    TEMP = (Join-Path $modRoot 'var/tmp')
    TMP = (Join-Path $modRoot 'var/tmp')
}
foreach ($directory in @('logs/mcp', 'logs/dispatch', 'var/mcp', 'var/tmp')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $modRoot $directory) | Out-Null
}
foreach ($name in $settings.Keys) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $settings[$name], 'Process')
}
Push-Location -LiteralPath $modRoot
try {
    Write-Host "MCP: http://${ListenAddress}:$Port/mcp"
    Write-Host "Logs: $(Join-Path $modRoot 'logs/mcp')"
    & $pythonExe -B $launcher --host $ListenAddress --port $Port
    $serverExit = $LASTEXITCODE
} finally {
    Pop-Location
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}
exit $serverExit
