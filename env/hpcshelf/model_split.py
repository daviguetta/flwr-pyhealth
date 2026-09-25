"""The component model's own decomposition, expressed as HPC Shelf descriptors.

Why this module exists
----------------------
``docs/ARCHITECTURE.md`` section 2.1 describes the federation as four logical
units: ``link``, ``node``, ``exec-server`` and ``exec-client``. The deployment
that is frozen and proven bundles them into two physical units per role, because
two platform rules pull in opposite directions:

* **R6 / C017** — one nested composition admits a single inner replica per host
  replica, so two units that must share a host cannot live in the same
  composition;
* **R3 / C002** — a horizontal dependency resolves only inside one component, so
  two units that must talk cannot live in separate ones.

These descriptor sets put the model's decomposition on the platform and let the
validator answer for itself. ``env/hpcshelf/validate.py`` asserts the codes the
collision predicts, which turns "the platform will not allow it" from an argument
into a reproducible result.

Nothing here is published or deployed. It is an experiment.

Findings (2026-09-25, hpcshelf-model ``develop`` @ ``68f0ace``)
--------------------------------------------------------------
``mono`` — four logical units in ONE component, co-located per institution:
    both components validate; the *application* does not, with ``C017`` three
    times: ``link[0]`` occupies ``institution[0]``, so ``exec-server[0]`` cannot
    share it. Co-location inside one composition is refused, which is what R6
    says.

``split`` — two components, ``comunicacao`` {link, node} and ``exec``
{exec-server, exec-client}, co-located through SEPARATE compositions:
    ``comunicacao`` validates on its own, so the ``fleet`` binding survives a
    component boundary as long as both of its ends are inside it. ``exec`` does
    not: ``C002`` twice, because its dependencies target ``link`` and ``node``,
    which are units of a *sibling* component.

Read together: the collision is specifically about ``appio``. The minimal
platform change is to let a ``dependencies`` entry target a sibling component's
unit; nothing else in the model needs to move.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

#: Container ports from the reference model, so the descriptors and
#: ``libs/federation_components`` cannot drift apart.
APPIO_PORT_LINK = 9091
FLEET_PORT = 9092
CONTROL_PORT = 9093
APPIO_PORT_NODE = 9094

_GRPC = "grpc"


def _replicas(minimum: int, maximum: int, default: int) -> Dict[str, int]:
    return {"min": minimum, "max": maximum, "default": default}


def _explicit(pairs: List[Tuple[int, int]], host_unit: str) -> Dict[str, object]:
    return {
        "hostUnit": host_unit,
        "mapping": {
            "type": "explicit",
            "instances": [
                {"innerReplica": inner, "hostReplica": host} for inner, host in pairs
            ],
        },
    }


def _root(name: str, nested: Dict[str, object], institutions: int = 3) -> Dict[str, object]:
    return {
        "apiVersion": "hpcshelf.org/v1",
        "kind": "Component",
        "metadata": {"name": name, "version": "0.1"},
        "spec": {
            "units": {
                "institution": {
                    "image": "hpcshelf-unit-base",
                    "replicas": _replicas(1, 8, institutions),
                }
            },
            "nestedComponents": nested,
        },
    }


def _application(name: str, root_ref: str, institutions: int = 3) -> Dict[str, object]:
    return {
        "apiVersion": "hpcshelf.org/v1",
        "kind": "Application",
        "metadata": {"name": name},
        "spec": {
            "component": {"ref": root_ref},
            "units": {"institution": {"replicas": institutions}},
        },
    }


def _link_unit() -> Dict[str, object]:
    return {
        "image": "catalog.hpcshelf.org/pyhealth/flower-link:0.1.0",
        "replicas": _replicas(1, 1, 1),
        "services": {
            "appio": {"protocol": _GRPC, "containerPort": APPIO_PORT_LINK},
            "fleet": {"protocol": _GRPC, "containerPort": FLEET_PORT},
            "control": {"protocol": _GRPC, "containerPort": CONTROL_PORT},
        },
    }


def _node_unit() -> Dict[str, object]:
    return {
        "image": "catalog.hpcshelf.org/pyhealth/flower-node:0.1.0",
        "replicas": _replicas(1, 8, 2),
        "services": {"appio": {"protocol": _GRPC, "containerPort": APPIO_PORT_NODE}},
        "dependencies": {
            "link": {
                "target": {"unit": "link", "service": "fleet"},
                "environment": {"host": "SUPERLINK_HOST", "port": "SUPERLINK_PORT"},
            }
        },
    }


def _exec_unit(role: str) -> Dict[str, object]:
    return {
        "image": f"catalog.hpcshelf.org/pyhealth/flower-exec-{role}:0.1.0",
        "replicas": _replicas(1, 1, 1) if role == "server" else _replicas(1, 8, 2),
    }


def mono_variant() -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    """Four logical units inside ONE component, co-located per institution.

    Expected to fail with ``C017``: the composition can host only one inner
    replica per host replica, so ``link`` and ``exec-server`` cannot share
    ``institution[0]``.
    """
    component = {
        "apiVersion": "hpcshelf.org/v1",
        "kind": "Component",
        "metadata": {"name": "flower-mono", "version": "0.1"},
        "spec": {
            "units": {
                "link": _link_unit(),
                "node": _node_unit(),
                "exec-server": {
                    **_exec_unit("server"),
                    "dependencies": {
                        "link": {
                            "target": {"unit": "link", "service": "appio"},
                            "environment": {"host": "APPIO_HOST", "port": "APPIO_PORT"},
                        }
                    },
                },
                "exec-client": {
                    **_exec_unit("client"),
                    "dependencies": {
                        "node": {
                            "target": {"unit": "node", "service": "appio"},
                            "environment": {"host": "APPIO_HOST", "port": "APPIO_PORT"},
                        }
                    },
                },
            }
        },
    }

    root = _root(
        "mono-root",
        {
            "fl": {
                "component": {"ref": "flower-mono:0.1"},
                "units": {
                    "link": {"replicas": 1},
                    "node": {"replicas": 2},
                    "exec-server": {"replicas": 1},
                    "exec-client": {"replicas": 2},
                },
                "overlap": {
                    "link": _explicit([(0, 0)], "institution"),
                    "exec-server": _explicit([(0, 0)], "institution"),
                    "node": _explicit([(0, 1), (1, 2)], "institution"),
                    "exec-client": _explicit([(0, 1), (1, 2)], "institution"),
                },
            }
        },
    )
    return [component, root], _application("mono-app", "mono-root:0.1")


def split_variant() -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    """Two components, co-located through SEPARATE compositions.

    ``comunicacao`` is expected to validate on its own. ``exec`` is expected to
    fail with ``C002``, because its dependencies reach into a sibling component.
    """
    comunicacao = {
        "apiVersion": "hpcshelf.org/v1",
        "kind": "Component",
        "metadata": {"name": "comunicacao", "version": "0.1"},
        "spec": {"units": {"link": _link_unit(), "node": _node_unit()}},
    }

    exec_component = {
        "apiVersion": "hpcshelf.org/v1",
        "kind": "Component",
        "metadata": {"name": "exec", "version": "0.1"},
        "spec": {
            "units": {
                "exec-server": {
                    **_exec_unit("server"),
                    "dependencies": {
                        "link": {
                            "target": {"unit": "link", "service": "appio"},
                            "environment": {"host": "APPIO_HOST", "port": "APPIO_PORT"},
                        }
                    },
                },
                "exec-client": {
                    **_exec_unit("client"),
                    "dependencies": {
                        "node": {
                            "target": {"unit": "node", "service": "appio"},
                            "environment": {"host": "APPIO_HOST", "port": "APPIO_PORT"},
                        }
                    },
                },
            }
        },
    }

    root = _root(
        "split-root",
        {
            "com": {
                "component": {"ref": "comunicacao:0.1"},
                "units": {"link": {"replicas": 1}, "node": {"replicas": 2}},
                "overlap": {
                    "link": _explicit([(0, 0)], "institution"),
                    "node": _explicit([(0, 1), (1, 2)], "institution"),
                },
            },
            "ex": {
                "component": {"ref": "exec:0.1"},
                "units": {"exec-server": {"replicas": 1}, "exec-client": {"replicas": 2}},
                "overlap": {
                    "exec-server": _explicit([(0, 0)], "institution"),
                    "exec-client": _explicit([(0, 1), (1, 2)], "institution"),
                },
            },
        },
    )
    return [comunicacao, exec_component, root], _application("split-app", "split-root:0.1")
