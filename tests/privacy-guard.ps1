$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$runner = Join-Path (Split-Path -Parent $PSScriptRoot) 'automation\nightly-windows.ps1'
$text = Get-Content -LiteralPath $runner -Raw -Encoding UTF8
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count -ne 0) { throw 'Runner has PowerShell syntax errors.' }
$guard = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Assert-PrivateBackup'
}, $true)
if ($null -eq $guard) { throw 'Privacy guard is missing.' }
. ([scriptblock]::Create($guard.Extent.Text))

function Invoke-Git { param([string[]]$Arguments) return $script:mockRemote }
function gh {
    $script:ghCalls++
    $global:LASTEXITCODE = $script:mockExit
    return $script:mockPrivate
}

$cases = @(
    @{ Name = 'HTTPS private'; Remote = 'https://github.com/example/private-wiki.git'; Private = 'true'; Exit = 0; Pass = $true },
    @{ Name = 'SSH private'; Remote = 'git@github.com:example/private-wiki.git'; Private = 'true'; Exit = 0; Pass = $true },
    @{ Name = 'Public target rejected'; Remote = 'https://github.com/example/public-wiki'; Private = 'false'; Exit = 0; Pass = $false },
    @{ Name = 'API failure rejected'; Remote = 'https://github.com/example/private-wiki'; Private = ''; Exit = 1; Pass = $false },
    @{ Name = 'Empty visibility rejected'; Remote = 'https://github.com/example/private-wiki'; Private = ''; Exit = 0; Pass = $false },
    @{ Name = 'Credentials in URL rejected'; Remote = 'https://example-user@example.invalid/private-wiki'; Private = 'true'; Exit = 0; Pass = $false },
    @{ Name = 'Other host rejected'; Remote = 'https://example.invalid/example/private-wiki'; Private = 'true'; Exit = 0; Pass = $false },
    @{ Name = 'Local target rejected'; Remote = 'C:\fixtures\backup.git'; Private = 'true'; Exit = 0; Pass = $false }
)
foreach ($case in $cases) {
    $script:mockRemote = $case.Remote
    $script:mockPrivate = $case.Private
    $script:mockExit = $case.Exit
    $script:ghCalls = 0
    $passed = $true
    try { Assert-PrivateBackup } catch { $passed = $false }
    if ($passed -ne $case.Pass) { throw "Unexpected guard result: $($case.Name)" }
    Write-Output "PASS: $($case.Name)"
}
$runGuard = $text.IndexOf('    Assert-PrivateBackup')
$readSource = $text.IndexOf('    $currentManifest = Get-CurrentManifest')
if ($runGuard -lt 0 -or $runGuard -ge $readSource) { throw 'Guard must run before source scanning.' }
Write-Output 'PASS: privacy check precedes source scanning'
Write-Output 'All tests passed; no real source data or external service was used.'
