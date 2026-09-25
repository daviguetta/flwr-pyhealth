"""Print the component-model conformance report.

    python -m libs.federation_components

Exits non-zero if the model disagrees with itself or a realization fails to
conform. Needs no platform checkout, no containers and no network: the model is
data, and the realizations are declared next to it.
"""

from __future__ import annotations

import sys

from .conformance import check_conformance, check_model, render
from .model import COMPONENT_MODEL_VERSION, INTER_UNIT_INTERFACES, REALIZATIONS


def main() -> int:
    failed = 0

    print(f"component model {COMPONENT_MODEL_VERSION}")
    print(f"interfaces that may cross a unit boundary: {', '.join(INTER_UNIT_INTERFACES)}")
    print()

    model_findings = check_model()
    if model_findings:
        failed += 1
        print("\033[31m✗\033[0m model disagrees with itself")
        print(render(model_findings))
    else:
        print("\033[32m✓\033[0m model agrees with itself (provides/requires vs bindings)")

    for artifact in REALIZATIONS:
        findings = check_conformance(artifact)
        if findings:
            failed += 1
            print(f"\033[31m✗\033[0m {artifact.artifact}")
            print(render(findings))
        else:
            print(f"\033[32m✓\033[0m {artifact.artifact} conforms")
            print(f"      descriptors: {artifact.descriptors}")

    print()
    if failed:
        print(f"\033[1mResult:\033[0m {failed} failure(s)")
    else:
        print(f"\033[1mResult:\033[0m {len(REALIZATIONS)} realizations, all conforming")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
