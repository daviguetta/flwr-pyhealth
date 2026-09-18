# `env/incus/` — institution-level unit topology

This directory is a **template, not a working deployment**. It records the
intended shape of a real rollout so that the container work in `env/podman/` is
built against the right target, and so the security questions about exposed
services can be answered before anything is deployed.

## Model

One Incus unit == one institution, or the federation hub. Each unit:
 
* is network-isolated from the others except for the declared federation port;
* runs Podman inside, which in turn runs the Flower components;
* pulls images from the internal registry rather than from the public internet.

```text
  Incus host(s)
  ├── unit: federation-server        (hub)
  │     └── podman: superlink, superexec(serverapp), registry mirror
  ├── unit: hospital-a               (client)
  │     └── podman: supernode, superexec(clientapp)
  └── unit: hospital-b               (client)
        └── podman: supernode, superexec(clientapp)

  Only these flows are permitted:
    hospital-*:9094/9095  ->  federation-server:9092   (SuperNode -> SuperLink)
    federation-server:9091 <-  hospital-*              (AppIO, return path)
```

## Files

| File | Purpose |
| --- | --- |
| `unit.template.yaml` | Skeleton Incus profile: resource limits, isolated NIC, no host mounts. |
| `PORTS.md` | The service/port inventory and which of them may ever leave the unit. |

## Why this is a template

Provisioning Incus units requires decisions this repository cannot make on the
institution's behalf: network ranges, storage pools, the CA to trust, and which
registry mirror is reachable. `unit.template.yaml` therefore marks each such
value with `# TODO(operator):` instead of inventing a default that would look
authoritative and be wrong.

## Data boundary

An Incus client unit is the boundary of the local data. Records are read by the
container inside the unit and never mounted out. `unit.template.yaml`
deliberately declares **no** host path mounts outside the unit, so a
misconfiguration cannot silently expose the hospital filesystem.
