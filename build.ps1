param(
    [switch]$FrontendIntegration,
    [switch]$SkipInstaller
)

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

    if ($FrontendIntegration) {
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
    }

    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "frontend\dist\index.html"))) {
        throw "Compiled frontend is missing. Merge the frontend branch or run build.ps1 -FrontendIntegration."
    }

    python -m PyInstaller --clean --noconfirm Zenless.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }

    if (-not $SkipInstaller) {
        $makeNsis = Get-Command makensis.exe -ErrorAction SilentlyContinue
        $makeNsisPath = if ($null -ne $makeNsis) { $makeNsis.Source } else { "" }
        if (-not $makeNsisPath) {
            $defaultNsis = Join-Path ${env:ProgramFiles(x86)} "NSIS\makensis.exe"
            if (Test-Path -LiteralPath $defaultNsis) {
                $makeNsisPath = $defaultNsis
            }
        }
        if (-not $makeNsisPath) {
            $defaultNsis = Join-Path $env:ProgramFiles "NSIS\makensis.exe"
            if (Test-Path -LiteralPath $defaultNsis) {
                $makeNsisPath = $defaultNsis
            }
        }
        if (-not $makeNsisPath) {
            throw "NSIS 3.12 is required to create ZenlessSetup.exe."
        }
        $makeNsisVersion = (& $makeNsisPath /VERSION | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $makeNsisVersion -notmatch '^v?3\.12(?:$|[.-])') {
            throw "NSIS 3.12 is required; found '$makeNsisVersion'."
        }
        Push-Location -LiteralPath (Join-Path $projectRoot "installer")
        try {
            & $makeNsisPath /WX "Zenless.nsi"
            if ($LASTEXITCODE -ne 0) { throw "NSIS failed with exit code $LASTEXITCODE." }
        }
        finally {
            Pop-Location
        }
    }

    Write-Host "Build complete:"
    Write-Host (Join-Path $distRoot "Zenless.exe")
    if (-not $SkipInstaller) {
        Write-Host (Join-Path $distRoot "ZenlessSetup.exe")
    }
}
finally {
    Pop-Location
}
