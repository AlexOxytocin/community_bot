[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$TestPath,
    [switch]$Full
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

function Invoke-Checked {
    param([scriptblock]$Command, [string]$Name)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Name failed" }
}

Push-Location $projectRoot
try {
    if ($Full) {
        Invoke-Checked { uv run ruff format --check . } "ruff format"
        Invoke-Checked { uv run ruff check . } "ruff check"
        Invoke-Checked { uv run ty check src tests ops } "ty"
        Invoke-Checked { uv run pytest } "pytest"
    }
    elseif ($TestPath.Count -gt 0) {
        Invoke-Checked { uv run pytest @TestPath } "targeted pytest"
    }
    else {
        Invoke-Checked { uv run pytest tests/unit tests/smoke } "quick pytest"
    }
}
finally {
    Pop-Location
}
