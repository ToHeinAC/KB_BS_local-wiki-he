---
name: restart-app
description: Restart the LocalWiki Streamlit app (port 8520) to pick up code changes without dropping the Cloudflare quick-tunnel URL. Use when asked to restart/reload/update the running app while a tunnel is live.
version: 1.0.0
---

# Restart app (tunnel-preserving)

Restart the live Streamlit app on **port 8520** so it re-imports changed code,
**without** losing the public `*.trycloudflare.com` URL.

## When to use

- "Restart / reload / update the running app" while it's exposed via `tunnel.sh`.
- Changes to imported submodules or constants that Streamlit `runOnSave` does not
  reliably hot-reload.
- The app process died and needs to come back on the same tunnel.

Do **not** use it to *stop* the app — `Ctrl-C` on `tunnel.sh` intentionally tears
down both the app's tunnel and the tunnel process.

## Why a plain restart breaks the URL

The public URL is a Cloudflare **quick tunnel**. `tunnel.sh` ends in a watchdog
loop that kills the tunnel once port 8520 stops listening (so the URL changes on
the next start). A naive `pkill` + relaunch trips that watchdog. This skill
disarms the watchdog first, restarts the app the same way `tunnel.sh` does, then
arms an equivalent detached watchdog pointed at the **same** tunnel PID. The
cloudflared process is never touched. Full startup logic lives in `tunnel.sh`.

## How to run

Run the script from the repo (it locates the repo root itself):

```bash
bash .claude/skills/restart-app/scripts/restart_app.sh
```

Then relay its result:

- On success it prints the app PID and the preserved **Public URL** (from
  `/tmp/wiki-app-url.txt`).
- If no tunnel is running it restarts the app only and tells the user to run
  `./tunnel.sh` to create a URL.
- On failure it tails `/tmp/wiki-app.log`; surface that to the user.

## Notes

- Idempotent: safe to run whether or not the app is currently up.
- Logs: app `/tmp/wiki-app.log`, tunnel `/tmp/wiki-tunnel.log`.
- Watchdog disarming is scoped to **this** repo / port 8520 — other projects'
  tunnels (e.g. ports 8511, 8530) are left alone.
- Assumes the fixed project port **8520** and a single app instance.
