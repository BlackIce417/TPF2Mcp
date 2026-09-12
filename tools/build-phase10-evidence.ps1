param([Parameter(Mandatory = $true)][string]$SessionPath, [Parameter(Mandatory = $true)][string]$OutputDirectory)

$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$responseDirectory = Join-Path $OutputDirectory 'responses'
New-Item -ItemType Directory -Force -Path $responseDirectory | Out-Null
$requests = @{}; $responses = @{}
foreach ($line in Get-Content -LiteralPath $SessionPath) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $item = $line | ConvertFrom-Json
    if ($item.direction -eq 'request') { $requests[[string]$item.message.id] = $item.message }
    if ($item.direction -eq 'response') { $responses[[string]$item.message.id] = $item.message }
}
function Tool([string]$name) {
    $id = $null
    foreach ($key in $requests.Keys) { if ($requests[$key].method -eq 'tools/call' -and $requests[$key].params.name -eq $name) { $id = $key } }
    if ($null -eq $id) { throw "Missing tool: $name" }
    return $responses[$id].result.structuredContent
}
function Resource([string]$uri) {
    $id = $null
    foreach ($key in $requests.Keys) { if ($requests[$key].method -eq 'resources/read' -and $requests[$key].params.uri -eq $uri) { $id = $key } }
    if ($null -eq $id) { throw "Missing resource: $uri" }
    return ($responses[$id].result.contents[0].text | ConvertFrom-Json)
}
function WriteJson([string]$name, $value) {
    $json = $value | ConvertTo-Json -Depth 100
    [System.IO.File]::WriteAllText((Join-Path $OutputDirectory $name), $json, $utf8)
    [System.IO.File]::WriteAllText((Join-Path $responseDirectory $name), $json, $utf8)
}
$baseline = Tool 'get_world_snapshot'
WriteJson 'network-baseline.json' $baseline
WriteJson 'capabilities.json' (Resource 'tpf2://capabilities')
WriteJson 'network-problems.json' (Tool 'detect_network_problems')
WriteJson 'station-route.json' (Tool 'find_alternative_routes')
$articulation = Tool 'find_articulation_stations'
WriteJson 'articulation-stations.json' $articulation
WriteJson 'bridge-connections.json' (Tool 'find_bridge_connections')
WriteJson 'network-resilience.json' (Tool 'analyze_network_resilience')
WriteJson 'scenario-connect-components.json' (Tool 'simulate_station_connection')
WriteJson 'scenario-line-failure.json' (Tool 'simulate_line_failure')
if (@($articulation.results).Count -gt 0) { WriteJson 'scenario-station-failure.json' (Tool 'simulate_station_failure') } else { WriteJson 'scenario-station-failure.json' @{ status = 'NONE_FOUND'; reason = 'No articulation station in this snapshot.' } }
WriteJson 'scenario-comparison.json' (Tool 'compare_network_scenarios')
WriteJson 'planning-options.json' (Tool 'get_planning_options')
WriteJson 'network-plan.json' (Tool 'analyze_and_plan_network')
Copy-Item -LiteralPath $SessionPath -Destination (Join-Path $OutputDirectory 'phase10-live-mcp-session.jsonl') -Force
$manifest = @{ phase = 10; snapshot_sequence = $baseline.sequence; read_only = $true; scenario_execution = 'IN_MEMORY_ONLY'; features = @{ problems = $true; impact_analysis = $true; topology_routes = $true; tarjan_resilience = $true; scenarios = $true; scenario_comparison = $true; planning_options = $true } }
WriteJson 'manifest.json' $manifest
Write-Output "Evidence directory: $OutputDirectory"
