param(
  [string]$OutputDir = "deploy/out/windows-x64",
  [string]$PythonRuntimeDir = "",
  [string]$WinSWExe = "",
  [switch]$SkipWebBuild,
  [switch]$SkipInstaller,
  [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"

function Resolve-RepoRoot {
  $scriptDir = Split-Path -Parent $PSCommandPath
  return (Resolve-Path (Join-Path $scriptDir "..\..")).Path
}

function Invoke-RobocopyChecked {
  param(
    [string]$Source,
    [string]$Destination,
    [string[]]$ExtraArgs = @()
  )
  if (!(Test-Path $Source)) {
    throw "Missing source path: $Source"
  }
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  $args = @(
    $Source,
    $Destination,
    "/MIR",
    "/NFL",
    "/NDL",
    "/NJH",
    "/NJS",
    "/NP",
    "/XD",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "/XF",
    "*.pyc",
    "*.pyo"
  ) + $ExtraArgs
  & robocopy @args | Out-Null
  if ($LASTEXITCODE -gt 7) {
    throw "robocopy failed copying $Source to $Destination with exit code $LASTEXITCODE"
  }
}

function New-ChecksumFile {
  param([string]$Root)
  $checksumPath = Join-Path $Root "checksums.txt"
  $rootUri = New-Object System.Uri (($Root.TrimEnd('\') + '\'))
  Get-ChildItem $Root -Recurse -File |
    Where-Object { $_.FullName -ne $checksumPath } |
    Sort-Object FullName |
    ForEach-Object {
      $fileUri = New-Object System.Uri $_.FullName
      $relative = [System.Uri]::UnescapeDataString($rootUri.MakeRelativeUri($fileUri).ToString()).Replace("/", "\")
      $hash = Get-FileHash -Algorithm SHA256 $_.FullName
      "{0}  {1}" -f $hash.Hash.ToLowerInvariant(), $relative
    } | Set-Content -Encoding UTF8 $checksumPath
}

function Resolve-SafeOutputDir {
  param(
    [string]$RepoRoot,
    [string]$RequestedOutputDir
  )
  $deployOutRoot = Join-Path $RepoRoot "deploy\out"
  New-Item -ItemType Directory -Force -Path $deployOutRoot | Out-Null
  $resolvedDeployOutRoot = (Resolve-Path $deployOutRoot).Path.TrimEnd('\')
  if ([System.IO.Path]::IsPathRooted($RequestedOutputDir)) {
    $resolvedOutput = [System.IO.Path]::GetFullPath($RequestedOutputDir).TrimEnd('\')
  } else {
    $resolvedOutput = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $RequestedOutputDir)).TrimEnd('\')
  }
  if ($resolvedOutput -eq $resolvedDeployOutRoot -or !$resolvedOutput.StartsWith($resolvedDeployOutRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to clean output outside deploy\out. Requested output: $resolvedOutput"
  }
  return $resolvedOutput
}

function Copy-RuntimeDataWhitelist {
  param(
    [string]$Source,
    [string]$Destination
  )
  $allowedFiles = @(
    "all_audio.json",
    "all_loc.json",
    "all_task.json",
    "broadcast_schedules.json",
    "calendar_holidays_cn.json",
    "task_overrides.json",
    "templates.json"
  )
  New-Item -ItemType Directory -Force -Path $Destination | Out-Null
  foreach ($fileName in $allowedFiles) {
    $sourcePath = Join-Path $Source $fileName
    if (Test-Path $sourcePath) {
      Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $Destination $fileName) -Force
    }
  }
}

$repo = Resolve-RepoRoot
Set-Location $repo

if (!$PythonRuntimeDir) {
  throw "Pass -PythonRuntimeDir with a prepared Windows x64 Python runtime that contains python.exe and installed runtime dependencies."
}
if (!(Test-Path (Join-Path $PythonRuntimeDir "python.exe"))) {
  throw "Python runtime must contain python.exe: $PythonRuntimeDir"
}
if (!$WinSWExe) {
  throw "Pass -WinSWExe with a WinSW x64 executable."
}
if (!(Test-Path $WinSWExe)) {
  throw "Missing WinSW executable: $WinSWExe"
}

if (!$SkipWebBuild) {
  Push-Location (Join-Path $repo "web")
  try {
    npm.cmd run build:prod
  } finally {
    Pop-Location
  }
}

$webDist = Join-Path $repo "web\dist"
if (!(Test-Path (Join-Path $webDist "index.html"))) {
  throw "Missing frontend build output. Expected web\dist\index.html. Run npm.cmd run build:prod or pass -SkipWebBuild only after building it."
}

$modelsDir = Join-Path $repo "models"
if (!(Test-Path $modelsDir)) {
  throw "Missing models directory: $modelsDir"
}

$nluDataDir = Join-Path $repo "data"
if (!(Test-Path (Join-Path $nluDataDir "label_config.json"))) {
  throw "Missing NLU data. Expected data\label_config.json."
}

$output = Resolve-SafeOutputDir -RepoRoot $repo -RequestedOutputDir $OutputDir
if (Test-Path $output) {
  Remove-Item -LiteralPath $output -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $output | Out-Null

Invoke-RobocopyChecked -Source (Join-Path $repo "backend") -Destination (Join-Path $output "app\backend")
Invoke-RobocopyChecked -Source (Join-Path $repo "src") -Destination (Join-Path $output "app\src")
Invoke-RobocopyChecked -Source $nluDataDir -Destination (Join-Path $output "data")
Invoke-RobocopyChecked -Source $webDist -Destination (Join-Path $output "web-dist")
Invoke-RobocopyChecked -Source $modelsDir -Destination (Join-Path $output "models")
Invoke-RobocopyChecked -Source $PythonRuntimeDir -Destination (Join-Path $output "python")

Copy-Item -LiteralPath (Join-Path $repo "requirements.txt") -Destination (Join-Path $output "app\requirements.txt") -Force
Copy-Item -LiteralPath (Join-Path $repo "README.md") -Destination (Join-Path $output "app\README.md") -Force

$runtimeData = Join-Path $output "runtime-data"
New-Item -ItemType Directory -Force -Path $runtimeData | Out-Null
if (Test-Path (Join-Path $repo "backend\data")) {
  Copy-RuntimeDataWhitelist -Source (Join-Path $repo "backend\data") -Destination $runtimeData
}

$serviceOut = Join-Path $output "service"
New-Item -ItemType Directory -Force -Path $serviceOut | Out-Null
Copy-Item -LiteralPath $WinSWExe -Destination (Join-Path $serviceOut "ai-speaker-service.exe") -Force
Copy-Item -LiteralPath (Join-Path $repo "deploy\windows\service\ai-speaker-service.xml") -Destination (Join-Path $serviceOut "ai-speaker-service.xml") -Force
Copy-Item -LiteralPath (Join-Path $repo "deploy\windows\service\install-service.ps1") -Destination (Join-Path $serviceOut "install-service.ps1") -Force
Copy-Item -LiteralPath (Join-Path $repo "deploy\windows\service\uninstall-service.ps1") -Destination (Join-Path $serviceOut "uninstall-service.ps1") -Force

Copy-Item -LiteralPath (Join-Path $repo "deploy\windows\installer.iss") -Destination (Join-Path $output "installer.iss") -Force
Copy-Item -LiteralPath (Join-Path $repo "deploy\windows\README.md") -Destination (Join-Path $output "README.md") -Force
Copy-Item -LiteralPath (Join-Path $repo "deploy\windows\ACCEPTANCE_CHECKLIST.md") -Destination (Join-Path $output "ACCEPTANCE_CHECKLIST.md") -Force

# 把 assets 目录（含 ai-speaker.ico）复制到 bundle，ISCC 在 bundle 里跑时能用相对路径找到。
# 用 $PSScriptRoot 而不是 $repo——前者 100% 是 deploy\windows，避免 scope 问题。
$assetsSrc = Join-Path $PSScriptRoot "assets"
if ($assetsSrc -and (Test-Path $assetsSrc)) {
    Invoke-RobocopyChecked -Source $assetsSrc -Destination (Join-Path $output "assets")
} else {
    Write-Warning "assets 目录不存在或路径为空：'$assetsSrc'"
}

$manifest = [ordered]@{
  name = "AI Speaker"
  version = $Version
  platform = "windows-x64"
  port = 5018
  generated_at = (Get-Date).ToString("s")
  python_runtime = "python"
  service = "ai-speaker"
  service_display_name = "AI Speaker"
  entrypoint = "backend.api_public:app"
  nlu_data = "data"
  web_dist = "web-dist"
}
$manifestJson = $manifest | ConvertTo-Json -Depth 4
# PowerShell 5.x 的 Set-Content -Encoding UTF8 会写 BOM，导致 Python json.loads 失败。
# 显式调 .NET API 写 UTF-8 (no BOM)，跟 PS 7+ 行为一致。
[System.IO.File]::WriteAllText((Join-Path $output "manifest.json"), $manifestJson, [System.Text.UTF8Encoding]::new($false))

Push-Location $output
try {
  New-ChecksumFile -Root $output
} finally {
  Pop-Location
}

if (!$SkipInstaller) {
  $iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
  if (!$iscc) {
    Write-Warning "ISCC.exe was not found. Bundle is ready at $output, but setup.exe was not built."
  } else {
    & $iscc.Source (Join-Path $output "installer.iss") "/DSourceDir=$output" "/DAppVersion=$Version"
  }
}

Write-Host "Windows bundle ready: $output"
