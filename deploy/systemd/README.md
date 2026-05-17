# AI Speaker `systemd` Deployment

This directory contains the production `systemd` unit for running the FastAPI
backend as a managed Linux service.

## Files

- `ai-speaker.service`: `systemd` unit for `backend.api_public:app` on port `5018`
- `ai-speaker.env.example`: suggested runtime overrides for `/etc/ai-speaker/ai-speaker.env`

## Assumptions

- Project path on the Linux server: `/home/it0/AI_speaker`
- Conda environment path: `/home/it0/miniconda3/envs/ai-speaker-py39`
- Service user: `it0`
- API entrypoint: `backend.api_public:app`
- Optional environment file: `/etc/ai-speaker/ai-speaker.env`

If the deployment path is different, update only `WorkingDirectory` first.

## Runtime Notes

- Keep the deployment as a single `uvicorn` process. Do not add extra workers
  or multiple replicas while pending actions and runtime cache still live only
  in process memory.
- The service unit now reads an optional `EnvironmentFile`, raises the file
  descriptor limit, and adds systemd start-rate limits for safer long-running
  operation.
- Do not set `MemoryMax` yet. Capture a real soak-test memory baseline first,
  then enforce a limit from measured production usage.

## Install

Copy the unit file to the server and install it as root:

```bash
sudo cp deploy/systemd/ai-speaker.service /etc/systemd/system/ai-speaker.service
sudo systemctl daemon-reload
sudo systemctl enable ai-speaker
sudo systemctl start ai-speaker
sudo systemctl status ai-speaker
```

If a legacy `nohup` process is still using port `5018`, stop it before starting
the service:

```bash
ps -ef | grep uvicorn
kill <old_pid>
```

## Operations

```bash
sudo systemctl restart ai-speaker
sudo systemctl stop ai-speaker
sudo systemctl status ai-speaker
sudo journalctl -u ai-speaker -n 200
sudo journalctl -u ai-speaker -f
```

## Verification

```bash
sudo systemctl status ai-speaker
curl http://127.0.0.1:5018/license/status
curl http://127.0.0.1:5018/healthz
curl http://127.0.0.1:5018/readyz
curl http://127.0.0.1:5018/ops/status
sudo systemctl restart ai-speaker
```

After a full server reboot, confirm that the service returns in the `active
(running)` state.

If `/readyz` returns `503`, treat the instance as not ready for cutover. If it
returns `200` with `"degraded": true`, the API is up but the remote sync path
needs investigation.

## Environment File

Store deployment overrides in `/etc/ai-speaker/ai-speaker.env`, for example:

```bash
REMOTE_BASE_URL=
REMOTE_USERNAME=admin
REMOTE_PASSWORD=123456
REMOTE_TIMEOUT=15
REMOTE_AUTO_SYNC_SECONDS=180
DEBUG_REMOTE=0
CORS_ALLOW_ORIGINS=
```

Leave `REMOTE_BASE_URL` blank when the deployment address is determined per site.
The login bootstrap flow can suggest candidate addresses and persist the selected
value into runtime settings.

`CORS_ALLOW_ORIGINS` is optional. Leave it empty for same-origin deployment, or
set a comma-separated allowlist such as
`http://127.0.0.1:5018,http://DEVICE_IP:5018` when a separate browser origin
must call the API.

Run the repository test suite before handoff, then use the commands above to
verify the deployed service on the target machine.

## Access Model

The default deployment serves the application directly from `uvicorn` on port
`5018`. A reverse proxy such as `nginx` is optional and is not required by the
`systemd` unit in this directory.

If an existing production server still exposes the app through `nginx` on a
different external port such as `170`, use
[`MIGRATE_170_TO_5018.md`](./MIGRATE_170_TO_5018.md) as the cutover checklist
for switching clients to direct access on `http://SERVER_IP:5018/`.
