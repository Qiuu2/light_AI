"""
Character-level data preparation for the RBT3 joint (intent + slot) model.
Reads training data from JSON (data_clean_balanced.json) and converts to
Hugging Face Datasets with BIO tags.

Slot names are used directly from the training data without aliasing.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from datasets import Dataset, DatasetDict, load_from_disk
from transformers import AutoTokenizer

try:
    from .corpus_tools import DATA_CORPUS_PATH, SRC_CORPUS_PATH, build_audit_report, sync_corpus_copy
except ImportError:  # pragma: no cover - fallback for script usage
    from corpus_tools import DATA_CORPUS_PATH, SRC_CORPUS_PATH, build_audit_report, sync_corpus_copy

BASE_DIR = Path(__file__).resolve().parent.parent


def _path_from_env(name: str, default: Path) -> Path:
    value = str(os.getenv(name, "") or "").strip()
    if not value:
        return default
    return Path(value).expanduser()


DATA_DIR = _path_from_env("AI_SPEAKER_NLU_DATA_DIR", BASE_DIR / "data")
SRC_DIR = Path(__file__).resolve().parent
DEFAULT_JSON = SRC_CORPUS_PATH
CACHE_DIR = DATA_DIR / "hf_cache"
LABEL_CONFIG_JSON = DATA_DIR / "label_config.json"


def resolve_model_dir(model_name: str | Path) -> str:
    """Resolve a configured model path with a repo-local fallback for deployment."""
    candidate = Path(model_name)
    if candidate.exists():
        return str(candidate)
    if not candidate.is_absolute():
        repo_candidate = BASE_DIR / candidate
        if repo_candidate.exists():
            return str(repo_candidate)
    fallback = BASE_DIR / "models"
    return str(fallback)


@dataclass
class PreprocessConfig:
    json_path: Path = DEFAULT_JSON
    cache_dir: Path = CACHE_DIR
    sync_copy_path: Path = DATA_CORPUS_PATH
    val_ratio: float = 0.1
    model_name: str = "models"  # repo-local RBT3 assets
    max_length: int = 128


def _read_json(cfg: PreprocessConfig) -> List[Dict]:
    """Read training samples from JSON file."""
    content = cfg.json_path.read_text(encoding="utf-8")
    payload = json.loads(content)
    samples = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(samples, list):
        raise ValueError(f"Expected list of samples, got {type(samples)}")
    # Filter out empty texts
    samples = [s for s in samples if isinstance(s, dict) and s.get("text", "").strip()]
    return samples


def _find_all_spans(text: str, value: str) -> List[Tuple[int, int]]:
    """Find all non-overlapping occurrences of value in text."""
    spans: List[Tuple[int, int]] = []
    start = 0
    while True:
        idx = text.find(value, start)
        if idx == -1:
            break
        spans.append((idx, idx + len(value)))
        start = idx + len(value)
    return spans


def label_sentence(text: str, slots: Dict[str, str]) -> Tuple[List[str], List[str]]:
    """Generate BIO tags for a text given its slot annotations."""
    tokens = list(text)
    tags = ["O"] * len(tokens)

    # Sort slots by position in text (earliest first), and by length (longest first) for ties
    slot_items = []
    for slot_key, slot_val in slots.items():
        if not slot_val:
            continue
        spans = _find_all_spans(text, slot_val)
        for span_start, span_end in spans:
            slot_items.append((span_start, span_end, slot_key))

    # Sort by start position, then by longer span first
    slot_items.sort(key=lambda x: (x[0], -(x[1] - x[0])))

    # Track occupied positions to avoid overlap
    occupied = set()
    for span_start, span_end, slot_key in slot_items:
        # Check for overlap
        span_positions = set(range(span_start, min(span_end, len(tokens))))
        if span_positions & occupied:
            continue
        occupied |= span_positions

        if span_start < len(tokens):
            tags[span_start] = f"B-{slot_key}"
            for i in range(span_start + 1, min(span_end, len(tokens))):
                tags[i] = f"I-{slot_key}"

    return tokens, tags


def _collect_slot_types(samples: List[Dict]) -> List[str]:
    """Collect all unique slot type names from the training data."""
    slot_types: set = set()
    for sample in samples:
        slots = sample.get("slots", {})
        if isinstance(slots, dict):
            slot_types.update(slots.keys())
    return sorted(slot_types)


def _build_slot_label_list(slot_types: Sequence[str]) -> List[str]:
    """Build the full BIO label list from slot types."""
    labels = ["O"]
    for slot in slot_types:
        labels.append(f"B-{slot}")
        labels.append(f"I-{slot}")
    return labels


def _ensure_cache_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def prepare_hf_datasets(cfg: PreprocessConfig = PreprocessConfig()) -> DatasetDict:
    """Read JSON training data and produce HuggingFace DatasetDict + label_config.json."""
    samples = _read_json(cfg)
    audit_report = build_audit_report(samples)
    print(
        json.dumps(
            {
                "preprocess_audit": {
                    "required_missing": audit_report["required_missing"],
                    "multi_value_slots": audit_report["multi_value_slots"],
                    "slot_not_in_text": audit_report["slot_not_in_text"],
                    "duplicate_slot_conflicts": audit_report["duplicate_slot_conflicts"],
                    "hard_error_count": audit_report["hard_error_count"],
                }
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if audit_report["hard_error_count"] > 0:
        raise ValueError(
            "Training corpus contains hard errors. "
            "Run `python scripts/audit_training_corpus.py` and `python scripts/clean_training_corpus.py` first."
        )

    slot_types = _collect_slot_types(samples)
    slot_labels = _build_slot_label_list(slot_types)
    slot_label2id = {label: idx for idx, label in enumerate(slot_labels)}

    # Collect all intents and build mapping
    all_intents = sorted(set(s["intent"] for s in samples))
    intent2id = {label: idx for idx, label in enumerate(all_intents)}

    rows: List[Dict] = []
    skipped = 0
    for sample in samples:
        intent_val = sample["intent"]
        text = str(sample["text"]).strip()
        slots = sample.get("slots", {})
        if not isinstance(slots, dict):
            slots = {}

        tokens, tags = label_sentence(text, slots)

        # Validate tags against known labels
        valid = True
        slot_ids = []
        for tag in tags:
            if tag not in slot_label2id:
                valid = False
                break
            slot_ids.append(slot_label2id[tag])

        if not valid:
            skipped += 1
            continue

        rows.append(
            {
                "text": text,
                "tokens": tokens,
                "intent_id": intent2id[intent_val],
                "slot_label_ids": slot_ids,
            }
        )

    if skipped > 0:
        print(f"[Preprocessor] Skipped {skipped} samples with invalid slot labels.")

    print(f"[Preprocessor] Prepared {len(rows)} samples, {len(all_intents)} intents, {len(slot_types)} slot types.")
    print(f"[Preprocessor] Intents: {all_intents}")
    print(f"[Preprocessor] Slot types: {slot_types}")

    dataset = Dataset.from_list(rows)
    dataset = dataset.train_test_split(test_size=cfg.val_ratio, seed=42, shuffle=True)

    _ensure_cache_dir(cfg.cache_dir)
    dataset.save_to_disk(cfg.cache_dir)

    LABEL_CONFIG_JSON.parent.mkdir(parents=True, exist_ok=True)
    LABEL_CONFIG_JSON.write_text(
        json.dumps(
            {
                "slot_labels": slot_labels,
                "intent2id": intent2id,
                "id2intent": {v: k for k, v in intent2id.items()},
                "model_name": "models",
                "max_length": cfg.max_length,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if cfg.json_path.resolve() == SRC_CORPUS_PATH.resolve():
        sync_corpus_copy(cfg.json_path, cfg.sync_copy_path)
    return dataset


def quick_token_check(cfg: PreprocessConfig = PreprocessConfig()) -> Dict:
    """Small helper to validate tokenizer alignment without training."""
    if not cfg.cache_dir.exists():
        prepare_hf_datasets(cfg)
    tokenizer = AutoTokenizer.from_pretrained(resolve_model_dir(cfg.model_name), use_fast=True)
    dataset = load_from_disk(cfg.cache_dir)
    sample = dataset["train"][0]
    encoding = tokenizer(
        sample["tokens"],
        is_split_into_words=True,
        return_offsets_mapping=True,
        max_length=cfg.max_length,
        padding="max_length",
        truncation=True,
    )
    return {
        "text": sample["text"],
        "tokens": sample["tokens"],
        "offset_mapping": encoding["offset_mapping"],
        "word_ids": encoding.word_ids(),
    }


if __name__ == "__main__":
    cfg = PreprocessConfig()
    ds = prepare_hf_datasets(cfg)
    print(ds)
