# AI Speaker Offline Acceptance Checklist

Use this checklist on the target machine after the offline bundle has been
copied over and installed.

## Install and Service Checks

```bash
bash kylininstall-ai-speaker.sh
ls -l /etc/ai-speaker/ai-speaker.env
cat /etc/ai-speaker/ai-speaker.env
systemctl cat ai-speaker --no-pager | grep EnvironmentFile
sudo systemctl status ai-speaker
sudo journalctl -u ai-speaker -n 200
```

Expected result:

- service reaches `active (running)`
- `/etc/ai-speaker/ai-speaker.env` exists after install
- the env file includes `REMOTE_BASE_URL=` by default plus the expected credential keys
- the installed service still references `EnvironmentFile=-/etc/ai-speaker/ai-speaker.env`
- no immediate startup crash caused by missing models, wheelhouse packages, or
  runtime data

## Bundle Structure Checks

Run the bundle verifier before you rely on any runtime result:

```bash
python docs/verify_rc_candidate.py --bundle-dir . --skip-http-probe
```

Expected result:

- output includes `bundle structure verified`
- the command confirms `manifest.json`, `checksums.txt`, `wheelhouse/`,
  `models/`, `systemd/`, and delivery docs are present
- no runtime-state files such as `license_state.json` or
  `assistant_command_logs.json` are pre-bundled

## Runtime Endpoint Checks

```bash
python docs/verify_rc_candidate.py --bundle-dir . --base-url http://127.0.0.1:5018
curl http://127.0.0.1:5018/license/status
```

Expected result:

- output includes `runtime endpoints verified`
- `/healthz` returns `200`
- `/ops/status` returns `200`
- `/readyz` returns `200` for a cutover-ready machine
- `/license/status` no longer fails because `/etc/ai-speaker/ai-speaker.env` is missing
- login page can show candidate remote addresses when `REMOTE_BASE_URL` is blank
- after choosing or entering the correct remote address and completing login, `/license/status` returns a non-empty `machine_code`

If `/readyz` returns `503`, stop the acceptance and investigate remote sync,
runtime permissions, or data initialization before handoff.

## Manual Functional Checks

Verify the following user-visible flows:

- frontend page opens from `http://DEVICE_IP:5018/`
- core assistant interface can reach backend APIs
- schedule data loads correctly
- terminal and media data load correctly
- a representative core playback or schedule operation completes

## Recovery Checks

Run these service operations at least once:

```bash
sudo systemctl restart ai-speaker
sudo systemctl stop ai-speaker
sudo systemctl start ai-speaker
```

Confirm:

- the service returns after restart
- recent logs remain readable through `journalctl`
- runtime JSON files still load after restart
- `.history` backup files exist and can be used for manual recovery if needed

## Handoff Decision

The machine is ready for formal acceptance only when all of the following are
true:

- install completed without manual source edits
- service is stable after restart
- health, readiness, and ops endpoints respond as expected
- frontend and core flows are reachable
- no unresolved degraded or not-ready signal remains on `/readyz`
