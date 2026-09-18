"""The FedProx proximal term.

Tested against a tiny local model rather than a real ``Transformer``: the
arithmetic of the penalty is what matters, and checking it this way keeps the
test instant and independent of PyHealth.
"""

from __future__ import annotations

import pytest
import torch

from flower_app.model import ProximalMixin


class _Base(torch.nn.Module):
    """Stand-in for a PyHealth model: returns a dict containing ``loss``."""

    def __init__(self):
        super().__init__()
        self.w = torch.nn.Parameter(torch.zeros(3))

    def forward(self, **kwargs):
        return {"loss": self.w.pow(2).sum()}


class _Model(ProximalMixin, _Base):
    """Mixin composed ahead of the base so the override is exercised."""


def test_mu_zero_leaves_the_loss_untouched():
    model = _Model()
    output = model()
    assert float(output["loss"]) == 0.0
    assert "proximal_penalty" not in output


def test_mu_positive_adds_the_penalty_against_the_reference():
    model = _Model()
    model.enable_proximal({"w": torch.ones(3)}, mu=1.0)

    output = model()

    # w = 0, reference = 1, so penalty = ||0 - 1||^2 = 3 and the term is
    # (mu / 2) * penalty = 1.5 on top of a base loss of 0.
    assert float(output["proximal_penalty"]) == 3.0
    assert float(output["loss"]) == 1.5


def test_penalty_shrinks_as_the_model_approaches_the_reference():
    """The penalty itself must fall; the total loss also carries the task term."""
    model = _Model()
    model.enable_proximal({"w": torch.ones(3)}, mu=1.0)

    far = float(model()["proximal_penalty"])
    with torch.no_grad():
        model.w.fill_(0.9)
    near = float(model()["proximal_penalty"])

    assert near < far
    # ||w - ref||^2 = 3 * (0.1)^2 = 0.03. The mu/2 factor multiplies the loss
    # term, not this raw squared distance.
    assert near == pytest.approx(0.03)


def test_parameters_absent_from_the_reference_are_ignored():
    """A partially matching state_dict must not crash the round."""
    model = _Model()
    model.enable_proximal({"unrelated": torch.ones(2)}, mu=1.0)

    output = model()

    assert float(output["proximal_penalty"]) == 0.0
    assert float(output["loss"]) == 0.0


def test_penalty_only_counts_parameters_it_can_match():
    model = _Model()
    model.enable_proximal({"w": torch.ones(3), "unrelated": torch.ones(5)}, mu=1.0)
    assert float(model()["proximal_penalty"]) == 3.0
