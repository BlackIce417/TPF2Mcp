param(
    [string]$NativeRoot = '',
    [ValidateSet('Debug', 'Release')][string]$Configuration = 'Release',
    [ValidateSet('x64')][string]$Platform = 'x64'
)
$ErrorActionPreference = 'Stop'
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
if ([string]::IsNullOrWhiteSpace($NativeRoot)) { $NativeRoot = Join-Path $repository 'native\tpf2_native' }
$solution = Join-Path ([IO.Path]::GetFullPath($NativeRoot)) 'tpf2_native.slnx'
if (-not (Test-Path -LiteralPath $solution -PathType Leaf)) { throw "Native solution not found: $solution" }
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$msbuild = & $vswhere -latest -prerelease -products * -requires Microsoft.Component.MSBuild -find 'MSBuild\**\Bin\MSBuild.exe' | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($msbuild)) { throw 'MSBuild not found.' }
$output = Join-Path $repository ".tmp-build\native\bin\$Platform\$Configuration"
& $msbuild $solution /m "/p:Configuration=$Configuration" "/p:Platform=$Platform" "/p:OutDir=$output\" /v:minimal /nologo | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Native build failed: $LASTEXITCODE" }
$loader = Join-Path $output 'tpf2_loader.dll'
$controller = Join-Path $output 'tpf2_controller.dll'
foreach ($file in @($loader, $controller)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Native output missing: $file" }
}
[pscustomobject]@{ Solution = $solution; OutputRoot = $output; LoaderDll = $loader; ControllerDll = $controller }
