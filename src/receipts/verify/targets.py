"""Pure mapping from dataset test ids to collected pytest node ids."""

from __future__ import annotations

from collections.abc import Iterable


def map_target_ids(
    targets: list[str],
    collected: Iterable[str],
) -> dict[str, list[str]]:
    collected_ids = set(collected)
    mapping: dict[str, list[str]] = {}
    for target in targets:
        if target in collected_ids:
            mapping[target] = [target]
            continue
        matches = sorted(
            node_id
            for node_id in collected_ids
            if node_id.split(maxsplit=1)[0] == target
        )
        mapping[target] = matches or [target]
    return mapping


__all__ = ["map_target_ids"]
