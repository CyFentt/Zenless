$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$distRoot = Join-Path $projectRoot "dist"

Push-Location -LiteralPath $projectRoot
try {
    Push-Location -LiteralPath (Join-Path $projectRoot "frontend")
    try {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci falhou com código $LASTEXITCODE." }
        $env:VITE_ZENLESS_MOCK = "false"
        npm run typecheck
        if ($LASTEXITCODE -ne 0) { throw "TypeScript falhou com código $LASTEXITCODE." }
        npm run test
        if ($LASTEXITCODE -ne 0) { throw "Vitest falhou com código $LASTEXITCODE." }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "Vite falhou com código $LASTEXITCODE." }
    }
    finally {
        Remove-Item Env:VITE_ZENLESS_MOCK -ErrorAction SilentlyContinue
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
