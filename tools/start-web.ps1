param(
    [int]$ApiPort = 8765,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repository '.venv\python.exe'
$apiLauncher = Join-Path $repository 'mcp_server\start_api.py'
$frontend = Join-Path $repository 'ui\rail-map'
$package = Join-Path $frontend 'package.json'
$vite = Join-Path $frontend 'node_modules\.bin\vite.cmd'

foreach ($required in @($python, $apiLauncher, $package)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required project file is missing: $required"
    }
}
if (-not (Test-Path -LiteralPath $vite -PathType Leaf)) {
    throw "Frontend dependencies are missing. Run: npm --prefix `"$frontend`" install"
}

foreach ($port in @($ApiPort, $FrontendPort)) {
    $listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        throw "Port $port is already in use by PID $($listener.OwningProcess). Stop that process or choose another port."
    }
}

$api = Start-Process -FilePath $python `
    -ArgumentList @($apiLauncher, '--port', [string]$ApiPort) `
    -WorkingDirectory $repository `
    -WindowStyle Hidden `
    -PassThru

try {
    $env:TPF2_API_TARGET = "http://127.0.0.1:$ApiPort"
    Write-Host "FastAPI JSON API: http://127.0.0.1:$ApiPort/api/docs"
    Write-Host "Vite frontend:      http://127.0.0.1:$FrontendPort/?view=network"
    Write-Host 'Press Ctrl+C to stop both development processes.'
    & $vite --host 127.0.0.1 --port $FrontendPort
} finally {
    if ($api -and -not $api.HasExited) {
        Stop-Process -Id $api.Id -ErrorAction SilentlyContinue
        $api.WaitForExit(5000) | Out-Null
    }
}
