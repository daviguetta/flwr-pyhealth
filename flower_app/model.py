"""Model construction and the FedProx proximal term.

The architecture is PyHealth's ``Transformer`` over the mortality task schema.
The only local addition is an opt-in proximal penalty. FedProx's server side
signals the coefficient through the ``"proximal-mu"`` key of the train
``ConfigRecord``, but it deliberately cannot apply the penalty itself: in FedProx
the regularisation lives in the *client* objective, pulling the local weights
back towards the global ones while the node keeps training on skewed data.

Reference
---------
Li, Sahu, Zaheer, Sanjabi, Talwalkar, Smith. "Federated Optimization in
Heterogeneous Networks." MLSys 2020. https://arxiv.org/abs/1812.06127
"""

from __future__ import annotations

from typing import Dict, Mapping

import torch
from pyhealth.models import Transformer


class ProximalMixin:
    """Adds the FedProx penalty on top of a PyHealth model's loss.

    The term is ``(mu / 2) * ||w - w_global||^2``. It is applied by wrapping
    ``forward``, which is where PyHealth computes the loss: ``Trainer.train``
    reads ``output["loss"]`` straight out of the model's return dict. Hooking
    here keeps the local training loop stock PyHealth, so metrics, early
    stopping and best-checkpoint reloading all keep working.

    With ``mu <= 0`` the override short-circuits and FedAvg runs unaffected.
    """

    _proximal_mu: float = 0.0
    _proximal_reference: Mapping[str, torch.Tensor] = {}

    def enable_proximal(self, reference: Mapping[str, torch.Tensor], mu: float) -> None:
        """Anchor the penalty to ``reference``, the received global weights."""
        self._proximal_reference = {
            name: tensor.detach().clone() for name, tensor in reference.items()
        }
        self._proximal_mu = float(mu)

    def proximal_penalty(self, device: torch.device, dtype: torch.dtype) -> torch.Tensor:
        """Squared L2 distance from the anchored global weights."""
        penalty = torch.zeros((), device=device, dtype=dtype)
        for name, parameter in self.named_parameters():
            reference = self._proximal_reference.get(name)
            if reference is None:
                continue
            penalty = penalty + (parameter - reference.to(device)).pow(2).sum()
        return penalty

    def forward(self, **kwargs: torch.Tensor) -> Dict[str, torch.Tensor]:
        output = super().forward(**kwargs)
        mu = self._proximal_mu
        loss = output.get("loss")
        if mu > 0.0 and loss is not None:
            penalty = self.proximal_penalty(loss.device, loss.dtype)
            output["loss"] = loss + (mu / 2.0) * penalty
            output["proximal_penalty"] = penalty.detach()
        return output


class ProximalTransformer(ProximalMixin, Transformer):
    """``Transformer`` that can carry a FedProx proximal term.

    Adds no parameters, so its ``state_dict`` keys are identical to a plain
    ``Transformer`` and it stays interchangeable with the centralised baseline.
    """


def build_model(samples) -> ProximalTransformer:
    """Build the shared architecture from the task schema.

    Returns a fresh, identically-initialised model on every node. Because every
    node derives the schema from the same dataset, vocabularies and embedding
    shapes agree by construction: the global ``state_dict`` loads with
    ``strict=True`` and no shape patching is required.
    """
    return ProximalTransformer(dataset=samples)
