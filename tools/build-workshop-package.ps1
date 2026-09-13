param(
    [string]$StagingArea = "",
    [string]$ModFolderName = "tpf2mcp_1"
)

$ErrorActionPreference = 'Stop'

function Find-Tpf2StagingArea {
    $steamRoots = [System.Collections.Generic.List[string]]::new()
    if (-not [string]::IsNullOrWhiteSpace($env:TPF2_STEAM_ROOT)) {
        $steamRoots.Add([System.IO.Path]::GetFullPath($env:TPF2_STEAM_ROOT))
    }
    $steam = Get-ItemProperty -Path 'HKCU:\Software\Valve\Steam' -ErrorAction SilentlyContinue
    if ($steam.SteamPath) { $steamRoots.Add([System.IO.Path]::GetFullPath($steam.SteamPath)) }

    $candidates = foreach ($root in $steamRoots | Select-Object -Unique) {
        $userdata = Join-Path $root 'userdata'
        if (-not (Test-Path -LiteralPath $userdata -PathType Container)) { continue }
        foreach ($user in Get-ChildItem -LiteralPath $userdata -Directory) {
            $local = Join-Path $user.FullName '1066780\local'
            if (Test-Path -LiteralPath $local -PathType Container) {
                [pscustomobject]@{
                    Path = Join-Path $local 'staging_area'
                    LastWriteTime = (Get-Item -LiteralPath $local).LastWriteTime
                }
            }
        }
    }
    $selected = $candidates | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $selected) {
        throw 'TPF2 staging area not found. Pass -StagingArea explicitly.'
    }
    return [System.IO.Path]::GetFullPath($selected.Path)
}

if ([string]::IsNullOrWhiteSpace($StagingArea)) {
    $StagingArea = Find-Tpf2StagingArea
}
$StagingArea = [System.IO.Path]::GetFullPath($StagingArea)
$repository = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$modSource = Join-Path $repository 'tpf2_mod'
$companionSource = Join-Path $repository 'mcp_server'
$previewSource = Join-Path $modSource 'workshop_preview.jpg'
$modBrowserImageSource = Join-Path $modSource 'image_00.tga'
$destination = [System.IO.Path]::GetFullPath((Join-Path $StagingArea $ModFolderName))

if (-not $destination.StartsWith($StagingArea + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to build outside the staging area: $destination"
}
if (Test-Path -LiteralPath $destination) {
    throw "Workshop staging destination already exists: $destination"
}
foreach ($required in @(
    (Join-Path $modSource 'mod.lua'),
    (Join-Path $modSource 'strings.lua'),
    (Join-Path $modSource 'res'),
    $previewSource,
    $modBrowserImageSource,
    (Join-Path $companionSource 'requirements.txt'),
    (Join-Path $companionSource 'start_server.py'),
    (Join-Path $companionSource 'start_ui.py'),
    (Join-Path $companionSource 'src')
)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required release input not found: $required" }
}

Add-Type -AssemblyName System.Drawing
$preview = [System.Drawing.Image]::FromFile($previewSource)
try {
    if ($preview.Width -ne $preview.Height) { throw 'Workshop preview must be square.' }
} finally {
    $preview.Dispose()
}
if ((Get-Item -LiteralPath $previewSource).Length -ge 1MB) {
    throw 'Workshop preview must be smaller than 1 MB.'
}
$tgaHeader = [System.IO.File]::ReadAllBytes($modBrowserImageSource)
if ($tgaHeader.Length -lt 18 -or $tgaHeader[2] -ne 2 -or $tgaHeader[16] -ne 24) {
    throw 'image_00.tga must be an uncompressed 24-bit true-color TGA.'
}
$tgaWidth = $tgaHeader[12] + 256 * $tgaHeader[13]
$tgaHeight = $tgaHeader[14] + 256 * $tgaHeader[15]
if ($tgaWidth -ne 320 -or $tgaHeight -ne 180) {
    throw 'image_00.tga must be 320x180 pixels.'
}

New-Item -ItemType Directory -Force -Path $destination | Out-Null
Copy-Item -LiteralPath (Join-Path $modSource 'mod.lua') -Destination $destination
Copy-Item -LiteralPath (Join-Path $modSource 'strings.lua') -Destination $destination
Copy-Item -LiteralPath $previewSource -Destination $destination
Copy-Item -LiteralPath $modBrowserImageSource -Destination $destination
Copy-Item -LiteralPath (Join-Path $modSource 'res') -Destination $destination -Recurse

$companionDestination = Join-Path $destination 'mcp_server'
New-Item -ItemType Directory -Force -Path $companionDestination | Out-Null
foreach ($fileName in @('pyproject.toml', 'requirements.txt', 'start_server.py', 'start_ui.py')) {
    Copy-Item -LiteralPath (Join-Path $companionSource $fileName) -Destination $companionDestination
}
$packageSource = Join-Path $companionSource 'src'
foreach ($file in Get-ChildItem -LiteralPath $packageSource -Recurse -File -Filter '*.py') {
    $relativePath = [System.IO.Path]::GetRelativePath($packageSource, $file.FullName)
    $target = Join-Path (Join-Path $companionDestination 'src') $relativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target
}

$uiSource = Join-Path $repository 'ui\rail-map'
$uiDestination = Join-Path $destination 'ui\rail-map'
New-Item -ItemType Directory -Force -Path $uiDestination | Out-Null
foreach ($fileName in @('app.js', 'bridge-crossings.js', 'index.html', 'network-app.js', 'network-page.js', 'network.css', 'README.md', 'template-runtime.js', 'timetable-page.js', 'timetable.css', 'timetable.html', 'timetable.js')) {
    Copy-Item -LiteralPath (Join-Path $uiSource $fileName) -Destination $uiDestination
}
foreach ($directoryName in @('templates', 'vendor')) {
    Copy-Item -LiteralPath (Join-Path $uiSource $directoryName) -Destination $uiDestination -Recurse
}
$toolDestination = Join-Path $destination 'tools'
New-Item -ItemType Directory -Force -Path $toolDestination | Out-Null
foreach ($fileName in @('serve-rail-map.py', 'export-rail-network-map.py')) {
    Copy-Item -LiteralPath (Join-Path $repository "tools\$fileName") -Destination $toolDestination
}

$forbidden = Get-ChildItem -LiteralPath $destination -Recurse -Force | Where-Object {
    $_.Name -in @('bridge', 'tpf2_mcp_state', 'local_config.lua', '__pycache__') -or
    $_.Name -like '*.egg-info' -or
    (!$_.PSIsContainer -and $_.Extension -in @('.pyc', '.sqlite', '.sqlite3', '.log', '.tmp'))
}
if ($forbidden) {
    throw "Forbidden runtime/build data entered the package: $($forbidden.FullName -join ', ')"
}
$config = Get-Content -LiteralPath (Join-Path $destination 'res\scripts\tpf2_mcp\config.lua') -Raw
if ($config -notmatch 'M\.allow_write_operations\s*=\s*false') {
    throw 'Published package must default to read-only mode.'
}

$files = Get-ChildItem -LiteralPath $destination -Recurse -File
[pscustomobject]@{
    Name = 'tpf2mcp'
    Author = 'BlackIce'
    Destination = $destination
    FileCount = $files.Count
    SizeBytes = ($files | Measure-Object Length -Sum).Sum
    DefaultMode = 'READ_ONLY'
} | Format-List
