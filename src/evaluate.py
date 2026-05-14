"""
Evaluate the trained joint model on a JSON test set and export predictions.
Updated for v3.1 intent/slot names.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List

from engine import load_engine


@dataclass
class EvalConfig:
    test_path: Path = Path("src/data_clean_balanced.json")
    output_jsonl: Path = Path("data/eval_predictions.jsonl")
    val_ratio: float = 0.1  # evaluate on last N% of data


def evaluate(cfg: EvalConfig = EvalConfig()) -> float:
    engine = load_engine()

    # Load test data from JSON
    content = cfg.test_path.read_text(encoding="utf-8")
    payload = json.loads(content)
    samples = payload.get("data", payload) if isinstance(payload, dict) else payload

    # Use last val_ratio as test set
    split_idx = int(len(samples) * (1 - cfg.val_ratio))
    test_samples = samples[split_idx:]

    json_lines: List[str] = []
    correct_intent = 0
    total = 0

    for sample in test_samples:
        text = str(sample.get("text", "")).strip()
        true_intent = sample.get("intent", "")
        true_slots = sample.get("slots", {})
        if not text:
            continue

        result = engine.infer(text)
        pred_intent = result["intent"]
        pred_slots = result.get("slots", {})
        intent_conf = result.get("intent_confidence", 0.0)

        is_intent_correct = pred_intent == true_intent
        correct_intent += int(is_intent_correct)
        total += 1

        # Check slot accuracy (exact match on known slot keys)
        slot_correct = 0
        slot_total = 0
        for slot_key, slot_val in true_slots.items():
            slot_total += 1
            if pred_slots.get(slot_key) == slot_val:
                slot_correct += 1

        json_lines.append(
            json.dumps(
                {
                    "text": text,
                    "true_intent": true_intent,
                    "pred_intent": pred_intent,
                    "intent_correct": is_intent_correct,
                    "intent_confidence": intent_conf,
                    "true_slots": true_slots,
                    "pred_slots": {k: v for k, v in pred_slots.items()
                                   if not k.endswith("_matched") and not k.endswith("_score") and not k.endswith("_id")},
                    "slot_correct": slot_correct,
                    "slot_total": slot_total,
                },
                ensure_ascii=False,
            )
        )

    intent_accuracy = correct_intent / max(total, 1)
    cfg.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    cfg.output_jsonl.write_text("\n".join(json_lines), encoding="utf-8")
    print(json.dumps({
        "total": total,
        "intent_correct": correct_intent,
        "intent_accuracy": round(intent_accuracy, 4),
    }, ensure_ascii=False, indent=2))
    return intent_accuracy


if __name__ == "__main__":
    evaluate()
