# AI Speaker Windows Offline Installer

This package targets Windows 10/11 x64.

## Runtime Shape

- Installer: Inno Setup `setup.exe`
- Service wrapper: WinSW
- Service name: `ai-speaker`
- Service display name: `AI Speaker`
- Port: `5018`
- UI: `http://127.0.0.1:5018/`
- Program files: `%ProgramFiles%\AI Speaker`
- Runtime data: `%ProgramData%\AI Speaker\data`
- NLU static data: `%ProgramFiles%\AI Speaker\data`
- Logs: `%ProgramData%\AI Speaker\logs`

Runtime data is preserved across upgrades and uninstall.

## Build Prerequisites

Prepare these on a Windows x64 build machine:

- Node.js and npm for the Vue build.
- Inno Setup with `ISCC.exe` on `PATH`.
- A prepared Windows x64 Python runtime directory containing `python.exe`.
- Runtime Python dependencies installed into that Python runtime.
- A WinSW x64 executable.
- Complete `models/` directory.
- Complete repository-level `data/` directory, including `label_config.json`.

The final installer does not include Node.js.
Business runtime data is stored separately from NLU static data. Upgrades preserve
`%ProgramData%\AI Speaker\data` and replace `%ProgramFiles%\AI Speaker\data`.

## Build

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -File deploy\windows\build_windows_bundle.ps1 `
  -PythonRuntimeDir C:\runtime\ai-speaker-python `
  -WinSWExe C:\tools\WinSW-x64.exe
```

If `web\dist` already exists:

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -File deploy\windows\build_windows_bundle.ps1 `
  -PythonRuntimeDir C:\runtime\ai-speaker-python `
  -WinSWExe C:\tools\WinSW-x64.exe `
  -SkipWebBuild
```

Output:

- Bundle: `deploy\out\windows-x64`
- Installer: `deploy\out\windows-x64\installer\AI-Speaker-Setup-x64.exe`

## Verify Bundle

Before handing off the installer, run the Windows bundle verifier from the repo
root:

```powershell
python scripts\verify_windows_bundle.py --bundle-dir deploy\out\windows-x64 --skip-http-probe
```

After installing and starting the service, run the runtime probe:

```powershell
python scripts\verify_windows_bundle.py --bundle-dir deploy\out\windows-x64 --base-url http://127.0.0.1:5018
```

The verifier checks the bundle shape, service wrapper configuration, frontend
assets, model files, checksums, and prevents pre-bundling local runtime state
such as remote settings, sync metadata, or assistant command logs.

## Install

Run the generated installer as Administrator.

After installation:

```powershell
Get-Service "ai-speaker"
Start-Process http://127.0.0.1:5018/
```

Configure the remote device address in the web UI after first launch.

## Upgrade

Run the newer installer over the existing installation.

The installer updates program files and preserves `%ProgramData%\AI Speaker\data`.

## Uninstall

Uninstall from Windows Apps/Programs.

The uninstaller stops and unregisters the Windows Service and removes program files.
It intentionally keeps `%ProgramData%\AI Speaker` for operational recovery.
