# BitaxePID — Docker (Alpine, x86_64)

Builds and runs `bitaxepid.py` (https://github.com/ldemattos/BitaxePID) from
a minimal Alpine Linux base image, with every input adjustable through
environment variables.

## Usage

```bash
cp docker/.env.example docker/.env
# edit docker/.env — at minimum set BITAXE_IP
docker compose -f docker/docker-compose.yml up -d --build
docker compose -f docker/docker-compose.yml logs -f
```

## How it works

- **`Dockerfile`** — a two-stage build: stage 1 `git clone`s the BitaxePID
  repo (pinned via `BITAXEPID_REPO`/`BITAXEPID_REF`), stage 2 is a minimal
  `alpine:3.20` runtime with Python 3 + the app's `requirements.txt`
  installed into a venv.
- **`entrypoint.sh`** — reads environment variables and turns them into
  `bitaxepid.py` command-line flags (`--ip`, `--stratum-user`, ...), and
  writes a generated YAML file from any `BITAXEPID_CFG_<KEY>` variables
  (passed as `--config`) so every ASIC tuning parameter (`TARGET_TEMP`,
  `HASHRATE_SETPOINT`, `POWER_LIMIT`, PID gains, etc.) is overridable
  without editing the image.
- **`/data` volume** — the app's working directory at runtime, seeded with
  the ASIC model YAMLs, `pools.yaml` and `user.yaml`, and where its logs,
  CSV/JSON snapshots and generated config are written, so they persist
  across container restarts.

## Environment variables

See `.env.example` for the full, documented list. Only `BITAXE_IP` is
required; everything else falls back to BitaxePID's own defaults
(`<ASICModel>.yaml`, `pools.yaml`, `user.yaml`).

Set `SERVE_METRICS=true` to expose the Prometheus/Grafana metrics endpoint
on port 8093 (mapped via `METRICS_PORT`, default 8093).

Set `LOG_TO_CONSOLE=false` together with `tty: true` in the compose file to
get the rich terminal UI instead of plain log lines.

Set `DISABLE_FASTEST_POOLS=true` to skip the `get_fastest_pools()` latency
test at startup. This requires `PRIMARY_STRATUM` to already be set (since
without a latency test the tuner has no other way to pick a pool and will
exit immediately). If `BACKUP_STRATUM` is left unset, the primary pool is
reused as the backup so the tuner keeps running with a single working pool.
