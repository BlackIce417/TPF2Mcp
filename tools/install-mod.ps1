param(
    [string]$GameUserModDirectory = "",
    [string]$ModFolderName = "tpf2mcp_1",
    [switch]$EnableRenameLineTest,
    [switch]$EnablePhase13VehicleTest,
    [switch]$EnablePhase16LineTest,
    [switch]$EnablePhase17RouteTest,
    [switch]$EnablePhase19LineStopsTest,
    [switch]$EnablePhase20VehicleLifecycleTest,
    [switch]$EnablePhase20SchedulingTest,
    [switch]$EnableDispatchTest
)

$ErrorActionPreference = 'Stop'

function Find-Tpf2GameDirectory {
    if (-not [string]::IsNullOrWhiteSpace($env:TPF2_GAME_DIR)) {
        $configured = [System.IO.Path]::GetFullPath($env:TPF2_GAME_DIR)
        if (Test-Path -LiteralPath $configured -PathType Container) { return $configured }
    }

    $steamRoots = [System.Collections.Generic.List[string]]::new()
    $steam = Get-ItemProperty -Path 'HKCU:\Software\Valve\Steam' -ErrorAction SilentlyContinue
    if ($steam.SteamPath) { $steamRoots.Add([System.IO.Path]::GetFullPath($steam.SteamPath)) }
    foreach ($root in @("${env:ProgramFiles(x86)}\Steam", "$env:ProgramFiles\Steam")) {
        if (-not [string]::IsNullOrWhiteSpace($root) -and (Test-Path -LiteralPath $root -PathType Container)) {
            $steamRoots.Add([System.IO.Path]::GetFullPath($root))
        }
    }

    $libraryRoots = [System.Collections.Generic.List[string]]::new()
    foreach ($root in $steamRoots) {
        $libraryRoots.Add($root)
        $vdf = Join-Path $root 'steamapps\libraryfolders.vdf'
        if (Test-Path -LiteralPath $vdf -PathType Leaf) {
            $text = Get-Content -Raw -LiteralPath $vdf
            foreach ($match in [regex]::Matches($text, '"path"\s+"([^"]+)"')) {
                $libraryRoots.Add($match.Groups[1].Value.Replace('\\', '\'))
            }
        }
    }

    foreach ($root in $libraryRoots | Select-Object -Unique) {
        $candidate = Join-Path $root 'steamapps\common\Transport Fever 2'
        if (Test-Path -LiteralPath $candidate -PathType Container) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw 'Transport Fever 2 installation not found. Set TPF2_GAME_DIR or pass -GameUserModDirectory.'
}

if ([string]::IsNullOrWhiteSpace($GameUserModDirectory)) {
    $GameUserModDirectory = Join-Path (Find-Tpf2GameDirectory) 'mods'
}
$source = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\tpf2_mod"))
$companionSource = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\mcp_server"))
$destination = [System.IO.Path]::GetFullPath((Join-Path $GameUserModDirectory $ModFolderName))
$BridgeDirectory = [System.IO.Path]::GetFullPath((Join-Path $destination 'bridge'))
if (-not (Test-Path -LiteralPath $source)) { throw "Mod source not found: $source" }
if (-not (Test-Path -LiteralPath $companionSource)) { throw "MCP companion source not found: $companionSource" }
New-Item -ItemType Directory -Force -Path $GameUserModDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $BridgeDirectory | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BridgeDirectory 'responses') | Out-Null
New-Item -ItemType Directory -Force -Path $destination | Out-Null
Copy-Item -Path (Join-Path $source '*') -Destination $destination -Recurse -Force
$companionDestination = Join-Path $destination 'mcp_server'
New-Item -ItemType Directory -Force -Path $companionDestination | Out-Null
foreach ($fileName in @('pyproject.toml', 'requirements.txt', 'start_server.py', 'start_ui.py')) {
    Copy-Item -LiteralPath (Join-Path $companionSource $fileName) -Destination (Join-Path $companionDestination $fileName) -Force
}
$companionPackageSource = Join-Path $companionSource 'src'
foreach ($file in Get-ChildItem -LiteralPath $companionPackageSource -Recurse -File -Filter '*.py') {
    $relativePath = [System.IO.Path]::GetRelativePath($companionPackageSource, $file.FullName)
    $target = Join-Path (Join-Path $companionDestination 'src') $relativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target -Force
}
$uiSource = Join-Path $PSScriptRoot '..\ui\rail-map'
$uiDestination = Join-Path $destination 'ui\rail-map'
New-Item -ItemType Directory -Force -Path $uiDestination | Out-Null
foreach ($fileName in @('app.js', 'bridge-crossings.js', 'index.html', 'network-app.js', 'network-page.js', 'network.css', 'README.md', 'template-runtime.js', 'timetable-page.js', 'timetable.css', 'timetable.html', 'timetable.js')) {
    Copy-Item -LiteralPath (Join-Path $uiSource $fileName) -Destination $uiDestination -Force
}
foreach ($directoryName in @('templates', 'vendor')) {
    Copy-Item -LiteralPath (Join-Path $uiSource $directoryName) -Destination $uiDestination -Recurse -Force
}
$toolDestination = Join-Path $destination 'tools'
New-Item -ItemType Directory -Force -Path $toolDestination | Out-Null
foreach ($fileName in @('serve-rail-map.py', 'export-rail-network-map.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $fileName) -Destination $toolDestination -Force
}
$allowWrite = ($EnableRenameLineTest.IsPresent -or $EnablePhase13VehicleTest.IsPresent -or $EnablePhase16LineTest.IsPresent -or $EnablePhase17RouteTest.IsPresent -or $EnablePhase19LineStopsTest.IsPresent -or $EnablePhase20VehicleLifecycleTest.IsPresent -or $EnablePhase20SchedulingTest.IsPresent -or $EnableDispatchTest.IsPresent).ToString().ToLower()
$allowedOperations = if ($EnableDispatchTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true, CREATE_LINE_FROM_SOURCE_ROUTE = true, CREATE_LINE = true, SET_LINE_STOPS = true, SELL_VEHICLE = true, SET_LINE_STOP_POLICY = true, HOLD_VEHICLE_AT_TERMINAL = true, RELEASE_VEHICLE_FROM_HOLD = true, APPLY_LINE_TIMETABLE = true, CLEAR_LINE_TIMETABLE = true }' } elseif ($EnablePhase20SchedulingTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true, CREATE_LINE_FROM_SOURCE_ROUTE = true, CREATE_LINE = true, SET_LINE_STOPS = true, SELL_VEHICLE = true, SET_LINE_STOP_POLICY = true }' } elseif ($EnablePhase20VehicleLifecycleTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true, CREATE_LINE_FROM_SOURCE_ROUTE = true, CREATE_LINE = true, SET_LINE_STOPS = true, SELL_VEHICLE = true }' } elseif ($EnablePhase19LineStopsTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true, CREATE_LINE_FROM_SOURCE_ROUTE = true, CREATE_LINE = true, SET_LINE_STOPS = true }' } elseif ($EnablePhase17RouteTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true, CREATE_LINE_FROM_SOURCE_ROUTE = true, CREATE_LINE = true }' } elseif ($EnablePhase16LineTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true, CREATE_LINE_FROM_SOURCE_ROUTE = true }' } elseif ($EnablePhase13VehicleTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true }' } elseif ($EnableRenameLineTest.IsPresent) { '{ RENAME_LINE = true }' } else { '{}' }
$generatedLocalConfig = @"
local M = {}

M.allow_write_operations = $allowWrite
M.allowed_operations = $allowedOperations

return M
"@
$configPath = Join-Path $destination "res\scripts\tpf2_mcp\local_config.lua"
[System.IO.File]::WriteAllText($configPath, $generatedLocalConfig, [System.Text.UTF8Encoding]::new($false))
Write-Output "Mod directory: $destination"
Write-Output "Bridge directory: $BridgeDirectory"
Write-Output "MCP server directory: $companionDestination"
Write-Output "Generated local Lua config: $configPath"
