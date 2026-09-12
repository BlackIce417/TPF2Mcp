param(
    [string]$GameUserModDirectory = "D:\Steam\steamapps\common\Transport Fever 2\mods",
    [string]$ModFolderName = "tpf2_mcp_1",
    [string]$BridgeDirectory = "$env:APPDATA\Transport Fever 2\tpf2_mcp_bridge",
    [switch]$EnableRenameLineTest,
    [switch]$EnablePhase13VehicleTest,
    [switch]$EnablePhase16LineTest,
    [switch]$EnablePhase17RouteTest,
    [switch]$EnablePhase19LineStopsTest,
    [switch]$EnablePhase20VehicleLifecycleTest,
    [switch]$EnablePhase20SchedulingTest,
    [switch]$EnableDispatchTest
)

if ([string]::IsNullOrWhiteSpace($env:APPDATA)) { throw "APPDATA is required to install the TPF2 MCP bridge." }
$source = Join-Path $PSScriptRoot "..\tpf2_mod"
$destination = Join-Path $GameUserModDirectory $ModFolderName
if (-not (Test-Path -LiteralPath $source)) { throw "Mod source not found: $source" }
New-Item -ItemType Directory -Force -Path $GameUserModDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $BridgeDirectory | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BridgeDirectory 'responses') | Out-Null
New-Item -ItemType Directory -Force -Path $destination | Out-Null
Copy-Item -Path (Join-Path $source '*') -Destination $destination -Recurse -Force
$luaBridgeDirectory = $BridgeDirectory.Replace('\', '/')
$luaBridgeDirectory = $luaBridgeDirectory.Replace('"', '\\"')
$allowWrite = ($EnableRenameLineTest.IsPresent -or $EnablePhase13VehicleTest.IsPresent -or $EnablePhase16LineTest.IsPresent -or $EnablePhase17RouteTest.IsPresent -or $EnablePhase19LineStopsTest.IsPresent -or $EnablePhase20VehicleLifecycleTest.IsPresent -or $EnablePhase20SchedulingTest.IsPresent -or $EnableDispatchTest.IsPresent).ToString().ToLower()
$allowedOperations = if ($EnableDispatchTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true, CREATE_LINE_FROM_SOURCE_ROUTE = true, CREATE_LINE = true, SET_LINE_STOPS = true, SELL_VEHICLE = true, SET_LINE_STOP_POLICY = true, HOLD_VEHICLE_AT_TERMINAL = true, RELEASE_VEHICLE_FROM_HOLD = true, APPLY_LINE_TIMETABLE = true, CLEAR_LINE_TIMETABLE = true }' } elseif ($EnablePhase20SchedulingTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true, CREATE_LINE_FROM_SOURCE_ROUTE = true, CREATE_LINE = true, SET_LINE_STOPS = true, SELL_VEHICLE = true, SET_LINE_STOP_POLICY = true }' } elseif ($EnablePhase20VehicleLifecycleTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true, CREATE_LINE_FROM_SOURCE_ROUTE = true, CREATE_LINE = true, SET_LINE_STOPS = true, SELL_VEHICLE = true }' } elseif ($EnablePhase19LineStopsTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true, CREATE_LINE_FROM_SOURCE_ROUTE = true, CREATE_LINE = true, SET_LINE_STOPS = true }' } elseif ($EnablePhase17RouteTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true, CREATE_LINE_FROM_SOURCE_ROUTE = true, CREATE_LINE = true }' } elseif ($EnablePhase16LineTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true, CREATE_LINE_FROM_SOURCE_ROUTE = true }' } elseif ($EnablePhase13VehicleTest.IsPresent) { '{ RENAME_LINE = true, BUY_VEHICLE = true, ASSIGN_VEHICLE_TO_LINE = true }' } elseif ($EnableRenameLineTest.IsPresent) { '{ RENAME_LINE = true }' } else { '{}' }
$generatedConfig = @"
local M = {}

M.bridge_dir = "$luaBridgeDirectory"
M.schema_version = 1
M.snapshot_schema_version = 5
M.snapshot_refresh_interval_seconds = 2
M.bridge_poll_interval_updates = 5
M.allow_write_operations = $allowWrite
M.allowed_operations = $allowedOperations

return M
"@
$configPath = Join-Path $destination "res\scripts\tpf2_mcp\config.lua"
[System.IO.File]::WriteAllText($configPath, $generatedConfig, [System.Text.UTF8Encoding]::new($false))
Write-Output "Mod directory: $destination"
Write-Output "Bridge directory: $BridgeDirectory"
Write-Output "Generated Lua config: $configPath"
