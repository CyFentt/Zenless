$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$distRoot = Join-Path $projectRoot "dist"
$previousMockMode = [Environment]::GetEnvironmentVariable("VITE_ZENLESS_MOCK", "Process")

Push-Location -LiteralPath $projectRoot
try {
    python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff failed with exit code $LASTEXITCODE." }

    python -m pyright
    if ($LASTEXITCODE -ne 0) { throw "Pyright failed with exit code $LASTEXITCODE." }

    python -m pytest -o addopts= -q
    if ($LASTEXITCODE -ne 0) { throw "Pytest failed with exit code $LASTEXITCODE." }

    Push-Location -LiteralPath (Join-Path $projectRoot "frontend")
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE." }
        $env:VITE_ZENLESS_MOCK = "false"
        npm run lint
        if ($LASTEXITCODE -ne 0) { throw "ESLint failed with exit code $LASTEXITCODE." }
        npm run typecheck
        if ($LASTEXITCODE -ne 0) { throw "TypeScript failed with exit code $LASTEXITCODE." }
        npm run test
        if ($LASTEXITCODE -ne 0) { throw "Vitest failed with exit code $LASTEXITCODE." }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Vite failed with exit code $LASTEXITCODE." }
    }
    finally {
        if ($null -eq $previousMockMode) {
            Remove-Item Env:VITE_ZENLESS_MOCK -ErrorAction SilentlyContinue
        }
        else {
            $env:VITE_ZENLESS_MOCK = $previousMockMode
        }
        Pop-Location
    }

    python -m PyInstaller --clean --noconfirm Zenless.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    Write-Host "Build complete:"
    Write-Host (Join-Path $distRoot "Zenless.exe")
}
finally {
    Pop-Location
}
