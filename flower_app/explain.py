"""Node-local explainability for the federated model.

Explainability is a project requirement: a deterioration alarm that cannot be
justified to a clinician will not be adopted. This module is a thin, explicit
adapter over PyHealth's interpretability suite so that the federation layer does
not grow its own, unvalidated attribution code.

The suite is PyHealth's own: ``IntegratedGradients``, ``DeepLift``, ``GIM``,
``CheferRelevance``, ``Lime``, ``Shap`` and ``BasicGradientSaliencyMaps`` from
``pyhealth.interpret.methods``, scored with ``Comprehensiveness`` and
``Sufficiency`` through ``pyhealth.metrics.evaluate_attribution``.

Governance rule
---------------
Attributions are computed **on the node that holds the records**. Attribution
maps point back at individual codes and visits, so they are patient-derived
data: they stay inside the container. Only aggregate scores may be reported
through a ``MetricRecord``.

Cost
----
Attribution is orders of magnitude more expensive than a forward pass, so it is
never part of the federated loop. Call it from an explicit evaluation script.
"""

from __future__ import annotations

import importlib
from typing import Dict, List, Optional, Sequence

from pyhealth.interpret.api import Interpretable
from pyhealth.metrics import evaluate_attribution

#: Interpreter name -> (module, class) inside PyHealth.
METHODS: Dict[str, tuple] = {
    "integrated_gradients": (
        "pyhealth.interpret.methods.integrated_gradients",
        "IntegratedGradients",
    ),
    "deeplift": ("pyhealth.interpret.methods.deeplift", "DeepLift"),
    "gim": ("pyhealth.interpret.methods.gim", "GIM"),
    "ig_gim": ("pyhealth.interpret.methods.ig_gim", "IntegratedGradientGIM"),
    "chefer": ("pyhealth.interpret.methods.chefer", "CheferRelevance"),
    "lime": ("pyhealth.interpret.methods.lime", "Lime"),
    "shap": ("pyhealth.interpret.methods.shap", "Shap"),
    "basic_gradient": (
        "pyhealth.interpret.methods.basic_gradient",
        "BasicGradientSaliencyMaps",
    ),
}

ATTRIBUTION_METRICS = ("comprehensiveness", "sufficiency")


def available_methods() -> List[str]:
    """Interpreter names this module knows how to build."""
    return sorted(METHODS)


def supports_interpretability(model) -> bool:
    """Whether the model implements PyHealth's ``Interpretable`` contract.

    Gradient- and embedding-level methods need the model to expose its embedding
    stage separately. Models that do not satisfy the contract raise inside
    PyHealth, so this is checked up front to fail with a clear message.
    """
    return isinstance(model, Interpretable)


def build_interpreter(name: str, model, **kwargs):
    """Instantiate a PyHealth interpreter for ``name``.

    Extra keyword arguments are forwarded to the interpreter, for example
    ``steps=50`` for ``integrated_gradients``.
    """
    if name not in METHODS:
        raise ValueError(
            f"unknown interpreter {name!r}; available: {available_methods()}"
        )
    if not supports_interpretability(model):
        raise TypeError(
            f"{type(model).__name__} does not implement pyhealth's Interpretable "
            "interface, so attribution methods cannot run on it"
        )
    module_name, class_name = METHODS[name]
    interpreter_class = getattr(importlib.import_module(module_name), class_name)
    return interpreter_class(model, **kwargs)


def evaluate_explanations(
    model,
    dataloader,
    method: str = "integrated_gradients",
    metrics: Sequence[str] = ATTRIBUTION_METRICS,
    percentages: Sequence[float] = (1, 5, 10, 20, 50),
    ablation_strategy: str = "zero",
    positive_threshold: float = 0.5,
    interpreter_kwargs: Optional[dict] = None,
) -> Dict[str, float]:
    """Score an attribution method on a node-local dataloader.

    Returns aggregate scores only. The per-sample attribution maps are not
    returned, because they are patient-derived and must not be shipped off-node.
    """
    interpreter = build_interpreter(method, model, **(interpreter_kwargs or {}))
    return evaluate_attribution(
        model=model,
        dataloader=dataloader,
        method=interpreter,
        metrics=list(metrics),
        percentages=list(percentages),
        ablation_strategy=ablation_strategy,
        positive_threshold=positive_threshold,
    )
