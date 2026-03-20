#!/usr/bin/env pwsh
param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Resolve repo root and dist directory
$RepoRoot = Split-Path -Parent $PSScriptRoot
$DistDir = Join-Path $RepoRoot "dist"

# Internal PyPI endpoint
$InternalRepoUrl = $env:PYPI_REPO_URL
if (-not $InternalRepoUrl) {
    $InternalRepoUrl = "http://maven.abc.com.cn/repository/pypi/"
}

# Clean previous builds
if (Test-Path $DistDir) {
    Remove-Item $DistDir -Recurse -Force
}

# Read version from pyproject.toml
$PyprojectPath = Join-Path $RepoRoot "pyproject.toml"
$Version = python -c "import tomllib, pathlib; d = tomllib.loads(pathlib.Path(r'$PyprojectPath').read_text()); print(d['project']['version'])"
$Version = $Version.Trim()
Write-Host "[Version] $Version"

# Build Studio frontend (dist/ force-included in wheel via pyproject.toml)
$FrontendDir = Join-Path $RepoRoot "src/ark_agentic/studio/frontend"
if (Test-Path (Join-Path $FrontendDir "package.json")) {
    Write-Host "[Building] Studio frontend..."
    Set-Location $FrontendDir
    npm ci --ignore-scripts
    npm run build
    Set-Location $RepoRoot
    Write-Host "[Done] Studio frontend built"
}

# Build ark-agentic wheel
Write-Host "[Building] ark-agentic..."
Set-Location $RepoRoot
uv build --out-dir $DistDir

Write-Host ""
Write-Host "[Build artifacts]"
Get-ChildItem $DistDir

if ($DryRun) {
    Write-Host "[Dry run] skipping upload"
    exit 0
}

# Upload to internal PyPI
Write-Host "[Uploading] to $InternalRepoUrl ..."
twine upload `
  --repository-url $InternalRepoUrl `
  "$DistDir/ark_agentic-$Version*"

Write-Host "[Done] Published ark-agentic==$Version"

