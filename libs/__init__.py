"""Shared, importable contracts that describe what the federation agrees on.

``flower_app`` implements behaviour; this package records the *agreement* that
behaviour implements. Keeping the two apart matters for a multi-institution
federation: the contract is the artefact institutions negotiate and version,
while the implementation is free to change behind it.

Nothing here reads data, and nothing here imports Flower or PyHealth, so the
contract can be validated in isolation and emitted as experiment metadata.
"""
