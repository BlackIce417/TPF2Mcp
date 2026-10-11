param(
    [Parameter(Mandatory=$true)][int]$ProcessId,
    [Parameter(Mandatory=$true)][string]$DllPath,
    [string]$GameExecutable
)
$ErrorActionPreference = 'Stop'
$expectedSha256 = '782b904a8f7bbdac1f7a18528f1a5c778691e5aa3087c37c351bf6912585175c'
$process = Get-Process -Id $ProcessId -ErrorAction Stop
if (-not $GameExecutable) { $GameExecutable = $process.Path }
$resolvedGame = (Resolve-Path -LiteralPath $GameExecutable).Path
$resolvedDll = (Resolve-Path -LiteralPath $DllPath).Path
if ($process.Path -ne $resolvedGame) { throw "PID $ProcessId is not the verified game executable." }
$actual = (Get-FileHash -LiteralPath $resolvedGame -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expectedSha256) { throw "Game SHA256 mismatch; native hooks were not installed." }
$injector = Join-Path $PSScriptRoot 'build\tpf2_control_injector.exe'
if (-not (Test-Path -LiteralPath $injector)) { $injector = Join-Path $PSScriptRoot 'tpf2_control_injector.exe' }
if (-not (Test-Path -LiteralPath $injector)) { throw 'Build the native helper first.' }
& $injector $ProcessId $resolvedDll
if ($LASTEXITCODE -ne 0) { throw "Injector failed with exit code $LASTEXITCODE" }
