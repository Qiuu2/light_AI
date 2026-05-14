"""
Offline entity mining: mines new device/content names from JSON training data.
Updated for v3.1 slot names.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

from preprocessor import DEFAULT_JSON, DATA_DIR


@dataclass
class ExtractionConfig:
    json_path: Path = DEFAULT_JSON
    entity_map_path: Path = DATA_DIR / "entity_map.json"


def _load_samples(cfg: ExtractionConfig) -> List[Dict]:
    content = cfg.json_path.read_text(encoding="utf-8")
    payload = json.loads(content)
    samples = payload.get("data", payload) if isinstance(payload, dict) else payload
    return [s for s in samples if isinstance(s, dict)]


def _derive_from_slots(samples: List[Dict]) -> Dict[str, Set[str]]:
    """Extract entity values organized by slot type from training data."""
    entities: Dict[str, Set[str]] = {
        "media_names": set(),
        "task_names": set(),
        "zone_names": set(),
        "terminal_names": set(),
        "schedule_names": set(),
    }

    for sample in samples:
        slots = sample.get("slots", {})
        if not isinstance(slots, dict):
            continue

        for key, val in slots.items():
            val_str = str(val).strip()
            if not val_str:
                continue

            if key in ("media_name", "new_media_name"):
                entities["media_names"].add(val_str)
            elif key == "task_name":
                entities["task_names"].add(val_str)
            elif key == "zone_name":
                entities["zone_names"].add(val_str)
            elif key in ("terminal_name",):
                entities["terminal_names"].add(val_str)
            elif key in ("schedule_name", "new_schedule_name"):
                entities["schedule_names"].add(val_str)

    return entities


def refresh_entity_map(cfg: ExtractionConfig = ExtractionConfig()) -> Dict[str, object]:
    """Extract and save entity maps from training data."""
    samples = _load_samples(cfg)
    entities = _derive_from_slots(samples)

    entity_map = {}
    if cfg.entity_map_path.exists():
        try:
            entity_map = json.loads(cfg.entity_map_path.read_text(encoding="utf-8"))
        except Exception:
            entity_map = {}

    # Update maps
    for map_key, slot_key in [
        ("MEDIA_MAP", "media_names"),
        ("TASK_MAP", "task_names"),
        ("ZONE_MAP", "zone_names"),
        ("TERMINAL_MAP", "terminal_names"),
        ("SCHEDULE_MAP", "schedule_names"),
    ]:
        current = entity_map.get(map_key, {})
        for name in entities[slot_key]:
            current.setdefault(name, name)
        entity_map[map_key] = current

    cfg.entity_map_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.entity_map_path.write_text(
        json.dumps(entity_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Entity map refreshed:")
    for key, val in entity_map.items():
        print(f"  {key}: {len(val)} entries")

    return entity_map


if __name__ == "__main__":
    refresh_entity_map()
