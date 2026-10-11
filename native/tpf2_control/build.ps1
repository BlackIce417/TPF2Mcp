[CmdletBinding()]
param(
    [string]$Gcc
)

$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$output = Join-Path $source 'build'
New-Item -ItemType Directory -Force -Path $output | Out-Null
if (-not $Gcc) {
    $command = Get-Command gcc -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { $Gcc = $command.Source }
}
if (-not $Gcc -or -not (Test-Path -LiteralPath $Gcc -PathType Leaf)) {
    throw 'MinGW-w64 gcc was not found. Add gcc to PATH or pass -Gcc <absolute-path>.'
}
$Gcc = (Resolve-Path -LiteralPath $Gcc).Path
& $Gcc -O2 -fomit-frame-pointer -shared -s -o (Join-Path $output 'tpf2_control.dll') (Join-Path $source 'tpf2_control.c') (Join-Path $source 'speed_hook.S') -static-libgcc
if ($LASTEXITCODE -ne 0) { throw 'DLL build failed.' }
& $Gcc -O2 -municode -s -o (Join-Path $output 'tpf2_control_injector.exe') (Join-Path $source 'injector.c') -static-libgcc
if ($LASTEXITCODE -ne 0) { throw 'Injector build failed.' }
