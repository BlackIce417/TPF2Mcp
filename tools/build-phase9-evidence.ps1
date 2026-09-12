param(
    [Parameter(Mandatory = $true)][string]$SessionPath,
    [Parameter(Mandatory = $true)][string]$DynamicProbePath,
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$responsesDirectory = Join-Path $OutputDirectory 'responses'
New-Item -ItemType Directory -Force -Path $responsesDirectory | Out-Null

$requests = @{}
$responses = @{}
foreach ($line in Get-Content -LiteralPath $SessionPath) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $entry = $line | ConvertFrom-Json
    if ($entry.direction -eq 'request') { $requests[[string]$entry.message.id] = $entry.message }
    if ($entry.direction -eq 'response') { $responses[[string]$entry.message.id] = $entry.message }
}

function Get-ToolResult([string]$Name) {
    $match = $null
    foreach ($id in $requests.Keys) {
        $request = $requests[$id]
        if ($request.method -eq 'tools/call' -and $request.params.name -eq $Name) { $match = $id }
    }
    if ($null -eq $match) { throw "Missing tool response: $Name" }
    return $responses[$match].result.structuredContent
}

function Get-ResourceResult([string]$Uri) {
    $match = $null
    foreach ($id in $requests.Keys) {
        $request = $requests[$id]
        if ($request.method -eq 'resources/read' -and $request.params.uri -eq $Uri) { $match = $id }
    }
    if ($null -eq $match) { throw "Missing resource response: $Uri" }
    return ($responses[$match].result.contents[0].text | ConvertFrom-Json)
}

function Write-Json([string]$Name, $Value) {
    $json = $Value | ConvertTo-Json -Depth 100
    [System.IO.File]::WriteAllText((Join-Path $OutputDirectory $Name), $json, $utf8)
    [System.IO.File]::WriteAllText((Join-Path $responsesDirectory $Name), $json, $utf8)
}

$world = Get-ToolResult 'get_world_snapshot'
Write-Json 'game-state.json' $world
Write-Json 'capabilities.json' (Get-ResourceResult 'tpf2://capabilities')
Write-Json 'network.json' (Get-ResourceResult 'tpf2://network')
Write-Json 'line-profile.json' (Get-ToolResult 'get_line_profile')
Write-Json 'line-classification.json' (Get-ToolResult 'classify_lines')
Write-Json 'line-outliers.json' (Get-ToolResult 'find_line_outliers')
Write-Json 'line-similarity.json' (Get-ToolResult 'find_similar_lines')
Write-Json 'station-profile.json' (Get-ToolResult 'get_station_profile')
Write-Json 'station-hubs.json' (Get-ToolResult 'rank_station_hubs')
Write-Json 'network-reachability.json' (Get-ToolResult 'analyze_network_reachability')
Write-Json 'isolated-components.json' (Get-ToolResult 'find_isolated_station_clusters')
Write-Json 'network-recommendations.json' (Get-ToolResult 'get_network_recommendations')
Write-Json 'network-analysis.json' (Get-ToolResult 'analyze_network')

$probe = Get-Content -Raw -LiteralPath $DynamicProbePath | ConvertFrom-Json
Write-Json 'town-relation-probe.json' $probe.town_station_relation
Write-Json 'industry-probe.json' $probe.industry_semantics
Copy-Item -LiteralPath $SessionPath -Destination (Join-Path $OutputDirectory 'phase9-live-mcp-session.jsonl') -Force
$manifest = @{ phase = 9; schema_version = 6; snapshot_sequence = $world.sequence; features = @{ network_intelligence = $true; line_profiles = $true; station_hub_analysis = $true; network_reachability = $true; network_recommendations = $true; town_station_relation = $probe.town_station_relation.source_status; industry_semantics = $probe.industry_semantics.source_status } }
Write-Json 'manifest.json' $manifest
Write-Output "Evidence directory: $OutputDirectory"
