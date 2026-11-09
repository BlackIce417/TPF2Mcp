param(
    [string]$NativeRoot = 'C:\Users\Anakin\source\repos\tpf2_native',
    [string]$OutputRoot = '',
    [string]$ModFolderName = 'tpf2_mcp_1',
    [switch]$InstallToMods,
    [string]$ModsRoot = 'D:\Steam\steamapps\common\Transport Fever 2\mods'
)

$ErrorActionPreference = 'Stop'
$repository = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$modSource = Join-Path $repository 'tpf2_mod'
$NativeRoot = [System.IO.Path]::GetFullPath($NativeRoot)
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $repository ('.tmp-native-mod\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
$destination = Join-Path $OutputRoot $ModFolderName
$solution = Join-Path $NativeRoot 'tpf2_native.slnx'

if ($ModFolderName -notmatch '^.+_[0-9]+$') {
    throw "TPF2 Mod folder must end in _<number>: $ModFolderName"
}

if (Test-Path -LiteralPath $destination) { throw "Native Mod destination already exists: $destination" }
foreach ($required in @(
    $solution,
    (Join-Path $modSource 'mod.lua'),
    (Join-Path $modSource 'strings.lua'),
    (Join-Path $modSource 'image_00.tga'),
    (Join-Path $modSource 'workshop_preview.jpg'),
    (Join-Path $modSource 'res')
)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required input not found: $required" }
}

$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) { throw "vswhere not found: $vswhere" }
$msbuild = & $vswhere -latest -prerelease -products * -requires Microsoft.Component.MSBuild -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($msbuild)) { throw 'MSBuild not found.' }

& $msbuild $solution /t:Build /m /p:Configuration=Release /p:Platform=x64
if ($LASTEXITCODE -ne 0) { throw "Native solution build failed with exit code $LASTEXITCODE" }

$loaderDll = Join-Path $NativeRoot 'x64\Release\tpf2_loader.dll'
$controllerDll = Join-Path $NativeRoot 'x64\Release\tpf2_controller.dll'
foreach ($dll in @($loaderDll, $controllerDll)) {
    if (-not (Test-Path -LiteralPath $dll -PathType Leaf)) { throw "Native DLL not found after build: $dll" }
}

New-Item -ItemType Directory -Path $destination | Out-Null
foreach ($name in @('mod.lua', 'strings.lua', 'image_00.tga', 'workshop_preview.jpg')) {
    Copy-Item -LiteralPath (Join-Path $modSource $name) -Destination $destination
}
Copy-Item -LiteralPath (Join-Path $modSource 'res') -Destination $destination -Recurse
$nativeDestination = New-Item -ItemType Directory -Path (Join-Path $destination 'native')
Copy-Item -LiteralPath $loaderDll -Destination (Join-Path $nativeDestination 'tpf2_loader.dll')
Copy-Item -LiteralPath $controllerDll -Destination (Join-Path $nativeDestination 'tpf2_control.dll')

$forbidden = Get-ChildItem -LiteralPath $destination -Recurse -File | Where-Object {
    $_.Extension -in @('.py', '.pyc', '.pyd') -or $_.FullName -match '[\\/](mcp_server|ui|tools)[\\/]'
}
if ($forbidden) { throw 'Native-only package unexpectedly contains Python/UI/tooling files.' }

$files = Get-ChildItem -LiteralPath $destination -Recurse -File | Sort-Object FullName
$manifest = foreach ($file in $files) {
    [pscustomobject]@{
        path = $file.FullName.Substring($destination.Length + 1).Replace('\', '/')
        bytes = $file.Length
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}
$report = [pscustomobject]@{
    schema_version = 1
    package_kind = 'TPF2_NATIVE_ONLY_MOD'
    mod_folder = $ModFolderName
    created_at = (Get-Date).ToUniversalTime().ToString('o')
    native_solution = $solution
    python_included = $false
    files = $manifest
}
$reportPath = Join-Path $OutputRoot 'native-mod-manifest.json'
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $reportPath -Encoding utf8
$archive = Join-Path $OutputRoot ($ModFolderName + '-native.zip')
Compress-Archive -LiteralPath $destination -DestinationPath $archive

$installed = $null
$backup = $null
if ($InstallToMods) {
    if (Get-Process -Name 'TransportFever2' -ErrorAction SilentlyContinue) {
        throw 'Transport Fever 2 is running. Refusing to replace an installed Mod.'
    }
    $ModsRoot = [System.IO.Path]::GetFullPath($ModsRoot)
    if (-not (Test-Path -LiteralPath $ModsRoot -PathType Container)) {
        throw "Mods root not found: $ModsRoot"
    }
    $installed = [System.IO.Path]::GetFullPath((Join-Path $ModsRoot $ModFolderName))
    if (-not $installed.StartsWith($ModsRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to install outside the Mods root: $installed"
    }
    if (Test-Path -LiteralPath $installed) {
        $backupRoot = Join-Path $OutputRoot 'installed-backup'
        New-Item -ItemType Directory -Path $backupRoot | Out-Null
        $backup = Join-Path $backupRoot $ModFolderName
        if (Test-Path -LiteralPath $backup) { throw "Backup destination already exists: $backup" }
        Move-Item -LiteralPath $installed -Destination $backup
    }
    try {
        Copy-Item -LiteralPath $destination -Destination $installed -Recurse
    }
    catch {
        if ($backup -and (Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $installed)) {
            Move-Item -LiteralPath $backup -Destination $installed
        }
        throw
    }
    foreach ($requiredInstalled in @(
        (Join-Path $installed 'mod.lua'),
        (Join-Path $installed 'res'),
        (Join-Path $installed 'native\tpf2_loader.dll'),
        (Join-Path $installed 'native\tpf2_control.dll')
    )) {
        if (-not (Test-Path -LiteralPath $requiredInstalled)) { throw "Installed Mod is incomplete: $requiredInstalled" }
    }
    $installedPython = Get-ChildItem -LiteralPath $installed -Recurse -File | Where-Object { $_.Extension -in @('.py', '.pyc', '.pyd') }
    if ($installedPython) { throw 'Installed native-only Mod contains Python files.' }
}

Write-Host "Native-only Mod folder: $destination"
Write-Host "Archive: $archive"
Write-Host "Manifest: $reportPath"
if ($installed) { Write-Host "Installed Mod: $installed" }
if ($backup) { Write-Host "Previous Mod backup: $backup" }
