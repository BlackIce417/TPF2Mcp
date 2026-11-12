param(
    [Parameter(Mandatory)][string]$PackageDirectory,
    [Parameter(Mandatory)][string]$ModDirectory,
    [switch]$AllowUnloadedGame
)
$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$package = (Resolve-Path -LiteralPath $PackageDirectory).Path
$target = [IO.Path]::GetFullPath($ModDirectory).TrimEnd('\', '/')
if ((Split-Path -Leaf $target) -notmatch '^.+_\d+$') { throw 'Mod folder must end in _<number>.' }
if ($target -eq $package -or $target.StartsWith($package + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Install target must be separate from the package.'
}
foreach ($required in @('mod.lua', 'res/scripts/tpf2_mcp/runtime/main.lua', 'native/tpf2_loader.dll',
    'native/tpf2_control.dll', 'mcp_server/start_http_server.py', 'skills/tpf2-dispatch/SKILL.md',
    'start-mcp.ps1', 'docs/usage/deployment.md')) {
    if (-not (Test-Path -LiteralPath (Join-Path $package $required) -PathType Leaf)) { throw "Incomplete package: $required" }
}
$games = @(Get-Process TransportFever2 -ErrorAction SilentlyContinue)
if ($games.Count -gt 0) {
    if (-not $AllowUnloadedGame) { throw 'Exit the whole game before replacing Loader.' }
    foreach ($game in $games) {
        # Only a fresh process that has not loaded either native module may be
        # updated in the menu. Loaded Loader code is never unloaded here.
        $modules = @($game.Modules)
        if (-not $modules.Count) { throw 'Cannot verify game module list.' }
        if ($modules | Where-Object ModuleName -in @('tpf2_loader.dll', 'tpf2_control.dll', 'tpf2_controller.dll')) {
            throw 'Native modules are loaded; exit the whole game before replacement.'
        }
    }
}
foreach ($process in Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'") {
    if ($process.CommandLine -and $process.CommandLine.IndexOf($target, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "Stop this Mod's Python service before installation (PID $($process.ProcessId))."
    }
}
$existed = Test-Path -LiteralPath $target -PathType Container
if ($existed) {
    if (-not (Test-Path -LiteralPath (Join-Path $target 'mod.lua') -PathType Leaf)) { throw 'Existing target is not a Mod.' }
    foreach ($dll in @('native/tpf2_loader.dll', 'native/tpf2_control.dll')) {
        $path = Join-Path $target $dll
        if (Test-Path -LiteralPath $path) {
            $probe = [IO.File]::Open($path, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            $probe.Dispose()
        }
    }
}
$backupRoot = [IO.Path]::GetFullPath((Join-Path $repository ('.tmp-install-backups/' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N'))))
if (-not $backupRoot.StartsWith($repository + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Backup escaped project root.' }
$backup = Join-Path $backupRoot (Split-Path -Leaf $target)
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
if ($existed) { Move-Item -LiteralPath $target -Destination $backup }
try {
    Copy-Item -LiteralPath $package -Destination $target -Recurse
    if ($existed) {
        foreach ($name in @('bridge', 'var', 'logs')) {
            $old = Join-Path $backup $name
            if (Test-Path -LiteralPath $old -PathType Container) { Copy-Item -LiteralPath $old -Destination $target -Recurse }
        }
        $localConfig = 'res/scripts/tpf2_mcp/local_config.lua'
        if (Test-Path -LiteralPath (Join-Path $backup $localConfig)) {
            Copy-Item -LiteralPath (Join-Path $backup $localConfig) -Destination (Join-Path $target $localConfig)
        }
        $legacyState = Join-Path $backup 'tpf2_mcp_state'
        if (Test-Path -LiteralPath $legacyState -PathType Container) {
            $state = Join-Path $target 'var/mcp'
            New-Item -ItemType Directory -Force -Path $state | Out-Null
            foreach ($item in Get-ChildItem -LiteralPath $legacyState -Force) {
                $existingItem = Join-Path $state $item.Name
                if (-not (Test-Path -LiteralPath $existingItem)) { Copy-Item -LiteralPath $item.FullName -Destination $state -Recurse }
            }
        }
        $oldEvents = Join-Path $target 'bridge/station-events.sqlite3'
        if (Test-Path -LiteralPath $oldEvents) {
            $newEvents = Join-Path $target 'var/mcp/station-events.sqlite3'
            if (-not (Test-Path -LiteralPath $newEvents)) {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $newEvents) | Out-Null
                Move-Item -LiteralPath $oldEvents -Destination $newEvents
            }
        }
    }
    foreach ($file in Get-ChildItem -LiteralPath $package -Recurse -File) {
        $relative = $file.FullName.Substring($package.Length).TrimStart('\', '/')
        if ((Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne
            (Get-FileHash -LiteralPath (Join-Path $target $relative) -Algorithm SHA256).Hash) {
            throw "Installed file mismatch: $relative"
        }
    }
} catch {
    if (Test-Path -LiteralPath $target) { Move-Item -LiteralPath $target -Destination (Join-Path $backupRoot 'failed-install') }
    if ($existed -and (Test-Path -LiteralPath $backup)) { Move-Item -LiteralPath $backup -Destination $target }
    throw
}
[pscustomobject]@{ Installed = $target; Backup = $(if ($existed) { $backup } else { $null }); RuntimeDataPreserved = $existed }
