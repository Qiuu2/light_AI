# AI Speaker Migration: `170` to Direct `5018`

This runbook is for servers where external traffic currently flows through:

```text
client -> nginx:170 -> 127.0.0.1:5018 -> ai-speaker
```

The goal is to stop depending on `nginx` for the public entrypoint and let
clients access the service directly on:

```text
http://SERVER_IP:5018/
```

## Preconditions

- `ai-speaker` is already managed by `systemd`
- the backend listens on `0.0.0.0:5018`
- clients are allowed to change their access URL from `:170` to `:5018`
- no other process is using `5018`

## Step 1: Confirm the Service on `5018`

```bash
sudo systemctl status ai-speaker --no-pager -l
sudo ss -ltnp | grep 5018
curl http://127.0.0.1:5018/license/status
```

Expected result:

- `ai-speaker` is `active (running)`
- Python or uvicorn is listening on `0.0.0.0:5018`
- the local health check returns JSON instead of timing out

## Step 2: Open `5018` for Direct Access

Use the firewall tooling that exists on the server. Common examples:

### firewalld

```bash
sudo firewall-cmd --permanent --add-port=5018/tcp
sudo firewall-cmd --reload
sudo firewall-cmd --list-ports | grep 5018
```

### ufw

```bash
sudo ufw allow 5018/tcp
sudo ufw status | grep 5018
```

If the server is behind a cloud security group, router ACL, or upstream
firewall, open TCP `5018` there as well.

## Step 3: Verify Remote Reachability

From another machine on the same network:

```bash
curl http://SERVER_IP:5018/license/status
```

Also open the page in a browser:

```text
http://SERVER_IP:5018/
```

Expected result:

- the login page or main page loads
- browser requests succeed without going through `:170`

## Step 4: Switch External References

Replace `http://SERVER_IP:170/` with `http://SERVER_IP:5018/` in all places
that users or systems rely on:

- browser bookmarks
- desktop shortcuts
- QR codes
- operation manuals
- links in other systems
- test scripts or monitoring checks

Keep the existing `nginx` `170 -> 5018` proxy in place during this phase so
users still have a rollback path.

## Step 5: Gray Verification

Before removing the old entrypoint, verify the business flow from `:5018`:

- login works
- schedule list loads
- save and upload works
- sync from remote backend works
- terminal and zone information render correctly

Useful commands:

```bash
sudo journalctl -u ai-speaker -n 100 --no-pager
sudo ss -ltnp | grep 5018
```

## Step 6: Disable the `170` Proxy After Cutover

Only after all clients have moved to `:5018`, update the `nginx` site config to
remove or disable the server block that listens on `170`.

Recommended sequence:

```bash
sudo nginx -T | grep -nE 'listen 170|proxy_pass|5018'
sudo nginx -t
sudo systemctl reload nginx
```

If you manage `nginx` with site files under `/etc/nginx/conf.d/` or
`/etc/nginx/sites-enabled/`, disable the `170` listener there before the
reload.

## Rollback

If direct access on `5018` fails during the cutover:

- keep `ai-speaker` running on `5018`
- leave the `nginx` `170 -> 5018` proxy enabled
- continue serving users through `:170`
- fix firewall or external access rules before trying the cutover again

## Notes

- The offline bundle in this repository does not install `nginx`
- The default `systemd` unit already uses `--port 5018`
- Do not change the application to listen on `170`; keep low ports behind a
  reverse proxy if they are still needed
