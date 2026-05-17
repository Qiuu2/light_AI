param(
  [Parameter(Mandatory = $true)]
  [string]$InstallRoot
)

$ErrorActionPreference = "Stop"

$serviceExe = Join-Path $InstallRoot "service\ai-speaker-service.exe"

if (Test-Path $serviceExe) {
  Push-Location (Split-Path -Parent $serviceExe)
  try {
    $existing = Get-Service -Name "ai-speaker" -ErrorAction SilentlyContinue
    if ($existing) {
      & $serviceExe stop | Out-Null
      & $serviceExe uninstall | Out-Null
    }
  } finally {
    Pop-Location
  }
}

try {
  $rule = Get-NetFirewallRule -DisplayName "AI Speaker 5018" -ErrorAction SilentlyContinue
  if ($rule) {
    Remove-NetFirewallRule -DisplayName "AI Speaker 5018" | Out-Null
  }
} catch {
  Write-Warning "Could not remove firewall rule for port 5018: $($_.Exception.Message)"
}
