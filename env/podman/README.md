# `env/podman/` — containerised Flower deployment runtime

The topology itself lives at the repository root, because that is where Flower's
tooling expects it:

* `podman-compose.yml` — SuperLink + two SuperNodes + three SuperExec processes;
* `Containerfile.superexec` — the image that runs the ServerApp and the ClientApps.

What lives here is the environment's *material*: the TLS material needed to stop
using `--insecure`.

## Certificates

`certs.yml` generates a self-signed CA and a SuperLink certificate whose SAN
includes the service name `superlink`, because SuperNodes connect to
`superlink:9092`:

```bash
podman compose -f env/podman/certs.yml run --rm gen-certs
```

Output lands in `env/podman/superlink-certificates/`, which is git-ignored.

> **Never commit `ca.key` or `server.key`.** They are federation secrets: with
> them an attacker can impersonate the aggregation server and receive model
> updates.

Self-signed certificates are for development only. A real deployment must use the
institution's ICP/AC-issued material.

## Current status

The compose file runs with `--insecure`, so certificates are optional today. They
are provided because moving off `--insecure` is a prerequisite for any deployment
that leaves a single trusted host — see `docs/DEPLOYMENT.md`.
