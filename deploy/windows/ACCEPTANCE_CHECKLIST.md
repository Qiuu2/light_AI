# AI Speaker Windows Acceptance Checklist

## Install

- Run `AI-Speaker-Setup-x64.exe` as Administrator.
- Confirm the installer completes without errors.
- Confirm `%ProgramFiles%\AI Speaker` exists.
- Confirm `%ProgramFiles%\AI Speaker\data\label_config.json` exists.
- Confirm `%ProgramData%\AI Speaker\data` exists.
- Confirm `%ProgramData%\AI Speaker\logs` exists.

## Bundle Verification

Before installation:

```powershell
python scripts\verify_windows_bundle.py --bundle-dir deploy\out\windows-x64 --skip-http-probe
```

Expected:

- Bundle structure is complete.
- Service wrapper files are present.
- Frontend and model files are present.
- Runtime data does not include old remote settings, sync metadata, or assistant logs.

## Service

```powershell
Get-Service "ai-speaker"
Get-CimInstance Win32_Service -Filter "Name='ai-speaker'"
```

Expected:

- Service exists.
- Startup type is automatic.
- Service status is running.

## Runtime

```powershell
Invoke-WebRequest http://127.0.0.1:5018/healthz
Invoke-WebRequest http://127.0.0.1:5018/ops/status
Invoke-WebRequest http://127.0.0.1:5018/readyz
Invoke-WebRequest http://127.0.0.1:5018/
python scripts\verify_windows_bundle.py --bundle-dir deploy\out\windows-x64 --base-url http://127.0.0.1:5018
```

Expected:

- `/healthz` returns HTTP 200.
- `/ops/status` returns HTTP 200.
- `/readyz` returns HTTP 200 when ready, or HTTP 503 when the service is alive but not cutover-ready.
- `/` returns the frontend HTML.

## Manual UI

- Open `http://127.0.0.1:5018/`.
- Complete remote device address configuration in the login/bootstrap flow.
- Confirm media, terminal, and schedule pages load.
- Run one representative read-only operation before any real device action.

## Restart

```powershell
Restart-Service "ai-speaker"
Start-Sleep -Seconds 5
Invoke-WebRequest http://127.0.0.1:5018/healthz
```

Expected:

- Service returns to running.
- Health endpoint responds.
- Logs are written under `%ProgramData%\AI Speaker\logs`.

## Upgrade

- Install a newer setup over an existing install.
- Confirm `%ProgramData%\AI Speaker\data\remote_settings.json` and schedule data are preserved.
- Confirm service restarts and UI opens.

## Uninstall

- Uninstall from Windows Apps/Programs.
- Confirm service is removed.
- Confirm `%ProgramFiles%\AI Speaker` is removed.
- Confirm `%ProgramData%\AI Speaker` is retained.
