param(
    [string]$StagingArea = "",
    [string]$ModFolderName = "tpf2mcp_1",
    [string]$NativeRoot = ""
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
$repository = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$modSource = Join-Path $repository 'tpf2_mod'
$companionSource = Join-Path $repository 'mcp_server'
if ([string]::IsNullOrWhiteSpace($NativeRoot)) { $NativeRoot = Join-Path $repository 'native\tpf2_native' }
$nativeSource = [System.IO.Path]::GetFullPath($NativeRoot)
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
    (Join-Path $companionSource 'start_http_server.py'),
    (Join-Path $companionSource 'start_ui.py'),
    (Join-Path $companionSource 'start_api.py'),
    (Join-Path $companionSource 'src'),
    (Join-Path $nativeSource 'tpf2_native.slnx')
)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required release input not found: $required" }
}

$nativeBuild = & (Join-Path $PSScriptRoot 'build-native.ps1') -NativeRoot $nativeSource
$loaderDll = $nativeBuild.LoaderDll
$nativeDll = $nativeBuild.ControllerDll

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
Copy-Item -LiteralPath (Join-Path $repository 'skills') -Destination $destination -Recurse
foreach ($fileName in @('README.md', 'start-mcp.ps1')) {
    Copy-Item -LiteralPath (Join-Path $repository $fileName) -Destination $destination
}
# Only maintained text documentation; exclude local reports, images and source
# migration inventories from the installed Mod.
foreach ($file in Get-ChildItem -LiteralPath (Join-Path $repository 'docs') -Recurse -File -Filter '*.md') {
    if ($file.Name -in @('NATIVE_ENGINE_RESEARCH.md', 'SIGNAL_OBSERVATIONS.md')) { continue }
    $relativeDoc = $file.FullName.Substring((Join-Path $repository 'docs').Length).TrimStart('\', '/')
    if ($relativeDoc.StartsWith('images')) { continue }
    $docTarget = Join-Path (Join-Path $destination 'docs') $relativeDoc
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $docTarget) | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $docTarget
}

$companionDestination = Join-Path $destination 'mcp_server'
New-Item -ItemType Directory -Force -Path $companionDestination | Out-Null
foreach ($fileName in @('pyproject.toml', 'requirements.txt', 'start_server.py', 'start_http_server.py', 'start_ui.py', 'start_api.py')) {
    Copy-Item -LiteralPath (Join-Path $companionSource $fileName) -Destination $companionDestination
}
$packageSource = Join-Path $companionSource 'src'
foreach ($file in Get-ChildItem -LiteralPath $packageSource -Recurse -File -Filter '*.py') {
    $sourcePrefix = [System.IO.Path]::GetFullPath($packageSource).TrimEnd('\') + '\'
    $fullSourceFile = [System.IO.Path]::GetFullPath($file.FullName)
    if (-not $fullSourceFile.StartsWith($sourcePrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Companion source escaped package root: $fullSourceFile"
    }
    $relativePath = $fullSourceFile.Substring($sourcePrefix.Length)
    $target = Join-Path (Join-Path $companionDestination 'src') $relativePath
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target
}

$uiSource = Join-Path $repository 'ui\rail-map'
$uiDestination = Join-Path $destination 'ui\rail-map'
New-Item -ItemType Directory -Force -Path $uiDestination | Out-Null
foreach ($fileName in @('README.md', 'package.json', 'package-lock.json', 'vite.config.mjs')) {
    Copy-Item -LiteralPath (Join-Path $uiSource $fileName) -Destination $uiDestination
}
foreach ($directoryName in @('public', 'src')) {
    Copy-Item -LiteralPath (Join-Path $uiSource $directoryName) -Destination $uiDestination -Recurse
}
$toolDestination = Join-Path $destination 'tools'
New-Item -ItemType Directory -Force -Path $toolDestination | Out-Null
foreach ($fileName in @('web/serve-rail-map.py', 'web/start-web.ps1', 'visualization/export-rail-network-map.py', 'visualization/export-dispatch-regions.py', 'diagnostics/run-regional-dispatch.py', 'diagnostics/collect-regional-inputs.py', 'diagnostics/hot-reload-telemetry.py')) {
    $targetTool = Join-Path $toolDestination $fileName
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetTool) | Out-Null
    Copy-Item -LiteralPath (Join-Path $repository "tools\$fileName") -Destination $targetTool
}
foreach ($fileName in @('diagnostics/control-system.py', 'diagnostics/control-system-acceptance.py', 'diagnostics/configure-capacity-routing.py', 'diagnostics/configure-speed-zone.py', 'diagnostics/configure-station-assignment.py')) {
    $targetTool = Join-Path $toolDestination $fileName
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetTool) | Out-Null
    Copy-Item -LiteralPath (Join-Path $repository "tools\$fileName") -Destination $targetTool
}

$nativeDestination = Join-Path $destination 'native'
New-Item -ItemType Directory -Force -Path $nativeDestination | Out-Null
Copy-Item -LiteralPath $nativeDll -Destination (Join-Path $nativeDestination 'tpf2_control.dll')
Copy-Item -LiteralPath $loaderDll -Destination (Join-Path $nativeDestination 'tpf2_loader.dll')

$forbidden = Get-ChildItem -LiteralPath $destination -Recurse -Force | Where-Object {
    $_.Name -in @('bridge', 'var', 'logs', 'tpf2_mcp_state', 'local_config.lua', '__pycache__') -or
    $_.Name -like '*.egg-info' -or
    (!$_.PSIsContainer -and $_.Extension -in @('.pyc', '.sqlite', '.sqlite3', '.log', '.tmp'))
}
if ($forbidden) {
    throw "Forbidden runtime/build data entered the package: $($forbidden.FullName -join ', ')"
}
$config = Get-Content -LiteralPath (Join-Path $destination 'res\scripts\tpf2_mcp\config\settings.lua') -Raw
if ($config -notmatch 'M\.allow_write_operations\s*=\s*false') {
    throw 'Published package must default to read-only mode.'
}

$files = Get-ChildItem -LiteralPath $destination -Recurse -File
$archive = Join-Path $StagingArea ($ModFolderName + '-release.zip')
if (Test-Path -LiteralPath $archive) { throw "Release archive already exists: $archive" }
Compress-Archive -LiteralPath $destination -DestinationPath $archive -CompressionLevel Optimal
[pscustomobject]@{
    Name = 'tpf2mcp'
    Author = 'BlackIce'
    Destination = $destination
    FileCount = $files.Count
    SizeBytes = ($files | Measure-Object Length -Sum).Sum
    DefaultMode = 'READ_ONLY'
    Archive = $archive
} | Format-List
