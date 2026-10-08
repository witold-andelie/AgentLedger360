# Run lint + tests under CPython 3.11 AND 3.13 (uv downloads missing interpreters).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\check_compat.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
foreach ($v in @("3.11", "3.13")) {
    $venv = ".venv" + $v.Replace(".", "")
    Write-Host "=== Python $v ($venv) ===" -ForegroundColor Cyan
    if (-not (Test-Path $venv)) { uv venv $venv --python $v -q }
    $py = Join-Path $venv "Scripts\python.exe"
    uv pip install -q --python $py -e ".[dev,ml,agent]"
    & $py -m compileall -q src tests
    if ($LASTEXITCODE -ne 0) { throw "compileall failed on $v" }
    & $py -m pytest
    if ($LASTEXITCODE -ne 0) { throw "tests failed on $v" }
}
uv tool run ruff check src tests
if ($LASTEXITCODE -ne 0) { throw "ruff failed" }
Write-Host "OK: 3.11 and 3.13 both green" -ForegroundColor Green
