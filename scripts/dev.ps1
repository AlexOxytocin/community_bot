[CmdletBinding()]
param(
    [switch]$SkipSync
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $projectRoot
try {
    if (-not $SkipSync) {
        uv sync --locked --all-groups
        if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }
    }

    docker compose up -d --wait postgres
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL startup failed" }

    uv run alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Alembic migration failed" }

    Write-Host "Community Mini App: http://localhost:8000"
    uv run community-web
    if ($LASTEXITCODE -ne 0) { throw "community-web failed" }
}
finally {
    Pop-Location
}
