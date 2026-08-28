$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$distRoot = Join-Path $projectRoot "dist"
$previousMockMode = [Environment]::GetEnvironmentVariable("VITE_ZENLESS_MOCK", "Process")

Push-Location -LiteralPath $projectRoot
try {
    python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff falhou com código $LASTEXITCODE." }

    python -m pyright
    if ($LASTEXITCODE -ne 0) { throw "Pyright falhou com código $LASTEXITCODE." }

    python -m pytest -o addopts= -q
    if ($LASTEXITCODE -ne 0) { throw "Pytest falhou com código $LASTEXITCODE." }

    Push-Location -LiteralPath (Join-Path $projectRoot "frontend")
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci falhou com código $LASTEXITCODE." }
        $env:VITE_ZENLESS_MOCK = "false"
        npm run lint
        if ($LASTEXITCODE -ne 0) { throw "ESLint falhou com código $LASTEXITCODE." }
        npm run typecheck
        if ($LASTEXITCODE -ne 0) { throw "TypeScript falhou com código $LASTEXITCODE." }
        npm run test
        if ($LASTEXITCODE -ne 0) { throw "Vitest falhou com código $LASTEXITCODE." }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Vite falhou com código $LASTEXITCODE." }
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
        throw "PyInstaller falhou com código $LASTEXITCODE."
    }

    Write-Host "Build concluído:"
    Write-Host (Join-Path $distRoot "Zenless.exe")
}
finally {
    Pop-Location
}
