$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Assert-ProjectChildPath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    $projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
    $targetPath = [System.IO.Path]::GetFullPath($Path)

    if (-not $targetPath.StartsWith($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside project: $targetPath"
    }
}

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Command,

        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]] $Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $Command $Arguments"
    }
}

$runningApp = Get-Process -Name "InterviewAssistant" -ErrorAction SilentlyContinue
if ($runningApp) {
    throw "InterviewAssistant.exe is running. Close the app in Windows, then run this build script again."
}

$buildDir = Join-Path $PSScriptRoot "build"
$distDirRoot = Join-Path $PSScriptRoot "dist"

foreach ($pathToClean in @($buildDir, $distDirRoot)) {
    if (Test-Path $pathToClean) {
        Assert-ProjectChildPath $pathToClean
        Write-Host "Removing old folder: $pathToClean"
        Remove-Item -LiteralPath $pathToClean -Recurse -Force
    }
}

Write-Host "Installing dependencies..."
Invoke-Step python -m pip install --upgrade pip
Invoke-Step python -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")

Write-Host "Building Windows executable..."
Invoke-Step python -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "InterviewAssistant.spec")

$distDir = Join-Path $PSScriptRoot "dist\InterviewAssistant"
$questionsSource = Join-Path $PSScriptRoot "questions"
$questionsTarget = Join-Path $distDir "questions"
$recordingsTarget = Join-Path $distDir "recordings"

if (Test-Path $questionsTarget) {
    Remove-Item $questionsTarget -Recurse -Force
}

Copy-Item $questionsSource $questionsTarget -Recurse
New-Item -ItemType Directory -Force -Path $recordingsTarget | Out-Null

Write-Host ""
Write-Host "Done."
Write-Host "Run: dist\InterviewAssistant\InterviewAssistant.exe"
