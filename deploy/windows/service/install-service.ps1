param(
  [Parameter(Mandatory = $true)]
  [string]$InstallRoot,
  [switch]$SkipFirewall
)

$ErrorActionPreference = "Stop"

$programData = Join-Path $env:ProgramData "AI Speaker"
$dataDir = Join-Path $programData "data"
$logsDir = Join-Path $programData "logs"
$serviceExe = Join-Path $InstallRoot "service\ai-speaker-service.exe"

New-Item -ItemType Directory -Force -Path $programData, $dataDir, $logsDir | Out-Null

if (!(Test-Path $serviceExe)) {
  throw "Missing service executable: $serviceExe"
}

Push-Location (Split-Path -Parent $serviceExe)
try {
  $existing = Get-Service -Name "ai-speaker" -ErrorAction SilentlyContinue
  if ($existing) {
    & $serviceExe stop | Out-Null
    & $serviceExe uninstall | Out-Null
  }

  & $serviceExe install | Out-Null
  & $serviceExe start | Out-Null
} finally {
  Pop-Location
}

Start-Sleep -Seconds 3
$installed = Get-Service -Name "ai-speaker" -ErrorAction SilentlyContinue
if (!$installed) {
  throw "AI Speaker service was not installed. Check WinSW logs under $logsDir."
}
if ($installed.Status -ne "Running") {
  throw "AI Speaker service is $($installed.Status), expected Running. Check logs under $logsDir."
}

if (!$SkipFirewall) {
  try {
    $rule = Get-NetFirewallRule -DisplayName "AI Speaker 5018" -ErrorAction SilentlyContinue
    if (!$rule) {
      New-NetFirewallRule `
        -DisplayName "AI Speaker 5018" `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort 5018 | Out-Null
    }
  } catch {
    Write-Warning "Could not create firewall rule for port 5018: $($_.Exception.Message)"
  }
}
