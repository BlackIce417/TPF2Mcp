param([string]$Python = "python")

$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$root = Split-Path -Parent $PSScriptRoot
$directory = Join-Path $root ("diagnostics\\" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Force -Path $directory | Out-Null

$startInfo = [System.Diagnostics.ProcessStartInfo]::new()
$startInfo.FileName = $Python
$startInfo.Arguments = '-X utf8 -m tpf2_mcp.server'
$startInfo.WorkingDirectory = $root
$startInfo.UseShellExecute = $false
$startInfo.RedirectStandardInput = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
if ($null -ne $startInfo.PSObject.Properties['StandardInputEncoding']) { $startInfo.StandardInputEncoding = $utf8 }
if ($null -ne $startInfo.PSObject.Properties['StandardOutputEncoding']) { $startInfo.StandardOutputEncoding = $utf8 }
$process = [System.Diagnostics.Process]::new()
$process.StartInfo = $startInfo
if (-not $process.Start()) { throw 'Unable to start the MCP server' }

$session = [System.Collections.Generic.List[string]]::new()
function Invoke-Mcp([hashtable]$Message) {
    $requestJson = $Message | ConvertTo-Json -Compress -Depth 30
    $session.Add((@{ direction = 'request'; message = $Message } | ConvertTo-Json -Compress -Depth 30))
    $process.StandardInput.WriteLine($requestJson)
    $process.StandardInput.Flush()
    $responseJson = $process.StandardOutput.ReadLine()
    if ([string]::IsNullOrWhiteSpace($responseJson)) { throw 'MCP server closed stdout unexpectedly' }
    $response = $responseJson | ConvertFrom-Json
    $session.Add((@{ direction = 'response'; message = $response } | ConvertTo-Json -Compress -Depth 50))
    if ($null -ne $response.error) { throw "MCP error $($response.error.code): $($response.error.message)" }
    return $response
}

try {
    Invoke-Mcp @{ jsonrpc = '2.0'; id = 1; method = 'initialize'; params = @{} } | Out-Null
    Write-Host '[1/3] MCP initialize ........ PASS'
    Invoke-Mcp @{ jsonrpc = '2.0'; id = 2; method = 'tools/list'; params = @{} } | Out-Null
    Write-Host '[2/3] tools/list ............ PASS'
    $stateResponse = Invoke-Mcp @{ jsonrpc = '2.0'; id = 3; method = 'tools/call'; params = @{ name = 'get_game_state'; arguments = @{} } }
    if ($null -eq $stateResponse.result.structuredContent.index_age_ms) { throw 'index_age_ms missing' }
    if ($null -eq $stateResponse.result.structuredContent.source_snapshot_age_ms) { throw 'source_snapshot_age_ms missing' }
    Write-Host '[3/3] get_game_state ........ PASS'
    $beforeSequence = $stateResponse.result.structuredContent.snapshot_sequence
    $refreshResponse = Invoke-Mcp @{ jsonrpc = '2.0'; id = 4; method = 'tools/call'; params = @{ name = 'get_game_state'; arguments = @{ force_refresh = $true } } }
    $afterSequence = $refreshResponse.result.structuredContent.snapshot_sequence
    if ($afterSequence -le $beforeSequence) { throw "force_refresh did not advance snapshot sequence: $beforeSequence -> $afterSequence" }
    Write-Host ("force_refresh .............. PASS ({0} -> {1})" -f $beforeSequence, $afterSequence)
    $snapshotResponse = Invoke-Mcp @{ jsonrpc = '2.0'; id = 5; method = 'tools/call'; params = @{ name = 'get_world_snapshot'; arguments = @{} } }
    $state = $snapshotResponse.result.structuredContent
    if ($state.schema_version -lt 2) { throw "Expected snapshot schema v2 or newer, got $($state.schema_version)" }
    Write-Host ("get_world_snapshot ....... PASS (schema v{0})" -f $state.schema_version)
    $cargoTypes = Invoke-Mcp @{ jsonrpc = '2.0'; id = 6; method = 'tools/call'; params = @{ name = 'get_cargo_types'; arguments = @{} } }
    if (@($cargoTypes.result.structuredContent).Count -ne @($state.cargo_types).Count) { throw 'get_cargo_types count differs from snapshot' }
    if (@($cargoTypes.result.structuredContent).Count -eq 0) { throw 'get_cargo_types returned no cargo types' }
    $cargoResource = Invoke-Mcp @{ jsonrpc = '2.0'; id = 7; method = 'resources/read'; params = @{ uri = 'tpf2://cargo-types' } }
    if ([string]::IsNullOrWhiteSpace($cargoResource.result.contents[0].text)) { throw 'tpf2://cargo-types resource is empty' }
    Write-Host ("get_cargo_types / resource ... PASS ({0})" -f @($cargoTypes.result.structuredContent).Count)
    $specs = @(@{ plural = 'towns'; singular = 'town' }, @{ plural = 'industries'; singular = 'industry' }, @{ plural = 'stations'; singular = 'station' }, @{ plural = 'lines'; singular = 'line' }, @{ plural = 'vehicles'; singular = 'vehicle' })
    $requestId = 10
    foreach ($spec in $specs) {
        $plural = $spec.plural
        $items = @($state.$plural)
        $pluralResponse = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = "get_$plural"; arguments = @{} } }
        $requestId++
        if (@($pluralResponse.result.structuredContent).Count -ne $items.Count) { throw "get_$plural count differs from snapshot" }
        if ($items.Count -eq 0) { throw "get_$plural has no entity; run this against MCP_TEST_SAVE" }
        $entityId = $items[0].entity_id
        $one = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = "get_$($spec.singular)"; arguments = @{ entity_id = $entityId } } }
        $requestId++
        if ($one.result.structuredContent.entity_id -ne $entityId) { throw "get_$($spec.singular) returned a different entity" }
        Write-Host ("get_{0} / get_{1} ... PASS ({2})" -f $plural, $spec.singular, $items.Count)
    }
    $network = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'get_transport_network_summary'; arguments = @{} } }
    $requestId++
    if ($network.result.structuredContent.line_count -ne @($state.lines).Count) { throw 'Network summary line count differs from snapshot' }
    Write-Host 'get_transport_network_summary ... PASS'
    foreach ($line in @($state.lines | Select-Object -First 3)) {
        $summary = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'get_line_summary'; arguments = @{ line_id = $line.entity_id } } }
        $requestId++
        if ($summary.result.structuredContent.summary.stop_count -ne $line.stop_count) { throw "get_line_summary stop count differs for $($line.entity_id)" }
    }
    Write-Host 'get_line_summary (3 lines) ... PASS'
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_lines_without_vehicles'; arguments = @{} } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_unassigned_vehicles'; arguments = @{} } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_suspicious_lines'; arguments = @{} } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_stations_without_lines'; arguments = @{} } } | Out-Null
    $requestId++
    $vehicleOps = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'get_vehicle_operating_state'; arguments = @{ vehicle_id = $state.vehicles[0].entity_id } } }
    if ($null -eq $vehicleOps.result.structuredContent.availability) { throw 'Vehicle operating availability missing' }
    $requestId++
    $stationOps = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'get_station_operating_state'; arguments = @{ station_id = $state.stations[0].entity_id } } }
    if ($null -eq $stationOps.result.structuredContent.availability) { throw 'Station operating availability missing' }
    $requestId++
    $lineOps = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'get_line_operating_summary'; arguments = @{ line_id = $state.lines[0].entity_id } } }
    if ($null -eq $lineOps.result.structuredContent.availability) { throw 'Line operating availability missing' }
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_low_load_vehicles'; arguments = @{ occupancy_threshold = 0.2 } } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_high_waiting_stations'; arguments = @{ waiting_threshold = 100 } } } | Out-Null
    $requestId++
    $scorecard = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'get_line_scorecard'; arguments = @{ line_id = $state.lines[0].entity_id } } }
    if ($null -eq $scorecard.result.structuredContent.network.fleet_capacity_total) { throw 'Line scorecard fleet capacity missing' }
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'diagnose_line_structure'; arguments = @{ line_id = $state.lines[0].entity_id } } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'diagnose_transport_network'; arguments = @{} } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'compare_lines'; arguments = @{ line_ids = @($state.lines | Select-Object -First 2 | ForEach-Object { $_.entity_id }) } } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'rank_lines'; arguments = @{ metric = 'fleet_capacity_total' } } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'get_station_connectivity'; arguments = @{ station_id = $state.stations[0].entity_id } } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_station_route'; arguments = @{ source_station_id = $state.stations[0].entity_id; target_station_id = $state.stations[1].entity_id } } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'rank_transfer_stations'; arguments = @{} } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'get_fleet_summary'; arguments = @{} } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'rank_vehicles_by_capacity'; arguments = @{} } } | Out-Null
    $requestId++
    $capabilities = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'resources/read'; params = @{ uri = 'tpf2://capabilities' } }
    if ([string]::IsNullOrWhiteSpace($capabilities.result.contents[0].text)) { throw 'tpf2://capabilities resource is empty' }
    $requestId++
    $lineProfile = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'get_line_profile'; arguments = @{ line_id = $state.lines[0].entity_id } } }
    if ($lineProfile.result.structuredContent.snapshot_sequence -ne $state.sequence) { throw 'Line profile snapshot sequence differs from current snapshot' }
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'classify_lines'; arguments = @{} } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_line_outliers'; arguments = @{ metric = 'frequency_seconds'; method = 'iqr' } } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_similar_lines'; arguments = @{ line_id = $state.lines[0].entity_id } } } | Out-Null
    $requestId++
    $stationProfile = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'get_station_profile'; arguments = @{ station_id = $state.stations[0].entity_id } } }
    if ($stationProfile.result.structuredContent.snapshot_sequence -ne $state.sequence) { throw 'Station profile snapshot sequence differs from current snapshot' }
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'rank_station_hubs'; arguments = @{ metric = 'graph_degree' } } } | Out-Null
    $requestId++
    $reachability = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'analyze_network_reachability'; arguments = @{} } }
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_isolated_station_clusters'; arguments = @{} } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'get_network_recommendations'; arguments = @{} } } | Out-Null
    $requestId++
    $analysis = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'analyze_network'; arguments = @{} } }
    if ($analysis.result.structuredContent.snapshot_sequence -ne $state.sequence) { throw 'Network analysis snapshot sequence differs from current snapshot' }
    $requestId++
    $problems = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'detect_network_problems'; arguments = @{} } }
    $lineProblem = @($problems.result.structuredContent.problems | Where-Object { $_.target.entity_type -eq 'LINE' } | Select-Object -First 1)
    if ($lineProblem.Count -gt 0) { Invoke-Mcp @{ jsonrpc = '2.0'; id = ($requestId + 1); method = 'tools/call'; params = @{ name = 'analyze_problem_impact'; arguments = @{ problem_id = $lineProblem[0].problem_id } } } | Out-Null; $requestId++ }
    $requestId++
    $lineStops = @($state.lines[0].stops)
    if ($lineStops.Count -ge 2) { Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_alternative_routes'; arguments = @{ source_station_id = $lineStops[0].station_id; target_station_id = $lineStops[1].station_id; max_routes = 3 } } } | Out-Null; $requestId++ }
    $articulation = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_articulation_stations'; arguments = @{} } }
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'find_bridge_connections'; arguments = @{} } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'analyze_network_resilience'; arguments = @{} } } | Out-Null
    $requestId++
    $components = @($reachability.result.structuredContent.components)
    if ($components.Count -ge 2) {
        $connection = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'simulate_station_connection'; arguments = @{ station_a = $components[0].station_ids[0]; station_b = $components[1].station_ids[0] } } }
        if ($connection.result.structuredContent.delta.connected_component_count -ne -1) { throw 'Virtual cross-component connection did not reduce component count by one' }
        $requestId++
    }
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'simulate_line_failure'; arguments = @{ line_id = $state.lines[0].entity_id } } } | Out-Null
    $requestId++
    if (@($articulation.result.structuredContent.results).Count -gt 0) { Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'simulate_station_failure'; arguments = @{ station_id = $articulation.result.structuredContent.results[0].station_id } } } | Out-Null; $requestId++ }
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'simulate_network_scenario'; arguments = @{ mutations = @(@{ type = 'CHANGE_VIRTUAL_VEHICLE_COUNT'; line_id = $state.lines[0].entity_id; delta = 1 }) } } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'get_planning_options'; arguments = @{} } } | Out-Null
    $requestId++
    Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'compare_network_scenarios'; arguments = @{ scenarios = @(@{ name = 'baseline'; mutations = @() }, @{ name = 'extra_vehicle'; mutations = @(@{ type = 'CHANGE_VIRTUAL_VEHICLE_COUNT'; line_id = $state.lines[0].entity_id; delta = 1 }) }) } } } | Out-Null
    $requestId++
    $plan = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'tools/call'; params = @{ name = 'analyze_and_plan_network'; arguments = @{} } }
    if ($plan.result.structuredContent.snapshot_sequence -ne $state.sequence) { throw 'Decision support snapshot sequence differs from current snapshot' }
    $requestId++
    $networkResource = Invoke-Mcp @{ jsonrpc = '2.0'; id = $requestId; method = 'resources/read'; params = @{ uri = 'tpf2://network' } }
    if ([string]::IsNullOrWhiteSpace($networkResource.result.contents[0].text)) { throw 'tpf2://network resource is empty' }
    Write-Host 'deterministic network analysis ... PASS'
    Write-Host 'operating-state availability ... PASS'
    Write-Host 'Phase 8 scorecard/diagnostics .. PASS'
    Write-Host 'Phase 9 intelligence tools ...... PASS'
    Write-Host 'Phase 10 decision support ........ PASS'
    Write-Host 'tpf2://capabilities ............ PASS'
    Write-Host 'tpf2://network resource ... PASS'
    Write-Host 'LIVE MCP E2E PASS'
}
finally {
    [System.IO.File]::WriteAllLines((Join-Path $directory 'mcp-session.jsonl'), $session, [System.Text.UTF8Encoding]::new($false))
    if (-not $process.HasExited) { $process.StandardInput.Close(); $process.WaitForExit(3000) | Out-Null }
    $stderr = $process.StandardError.ReadToEnd()
    if (-not [string]::IsNullOrWhiteSpace($stderr)) { [System.IO.File]::WriteAllText((Join-Path $directory 'mcp-stderr.txt'), $stderr, [System.Text.UTF8Encoding]::new($false)) }
    Write-Host "Session: $(Join-Path $directory 'mcp-session.jsonl')"
}
