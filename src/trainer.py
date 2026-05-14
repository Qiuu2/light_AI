"""
RBT3 joint training (intent classification + slot tagging with CRF) plus ONNX export.
"""
from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from tqdm import tqdm
import torch
from datasets import DatasetDict, load_from_disk
from torch import nn
from torch.utils.data import DataLoader
from transformers import (
    AutoModel,
    AutoTokenizer,
    get_linear_schedule_with_warmup,
)

try:
    from .preprocessor import LABEL_CONFIG_JSON, PreprocessConfig, prepare_hf_datasets, DATA_DIR, resolve_model_dir
except ImportError:  # pragma: no cover - fallback for script usage
    from preprocessor import LABEL_CONFIG_JSON, PreprocessConfig, prepare_hf_datasets, DATA_DIR, resolve_model_dir


def _load_crf_class():
    for module_name in ("torchcrf", "TorchCRF"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        crf = getattr(module, "CRF", None)
        if crf is not None:
            return crf
    return None


CRF = _load_crf_class()  # type: ignore

BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"

@dataclass
class TrainConfig:
    model_name: str = "models"  # repo-local RBT3 assets
    cache_dir: Path = PreprocessConfig().cache_dir
    output_dir: Path = MODELS_DIR / "joint_rbt3"
    max_length: int = 128
    batch_size: int = 4
    num_epochs: int = 5
    lr: float = 5e-5
    weight_decay: float = 0.01
    warmup_ratio: float = 0.06
    grad_accum_steps: int = 1
    device: str = "cpu"
    fp16: bool = False


class JointRBT3Model(nn.Module):
    def __init__(
        self,
        model_name: str,
        num_intents: int,
        num_slot_labels: int,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.encoder = AutoModel.from_pretrained(model_name)
        hidden = self.encoder.config.hidden_size
        self.dropout = nn.Dropout(dropout)
        self.intent_classifier = nn.Linear(hidden, num_intents)
        self.slot_classifier = nn.Linear(hidden, num_slot_labels)
        self.crf = CRF(num_slot_labels, batch_first=True) if CRF else None
        self.slot_pad_id = 0

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor,
        token_type_ids: torch.Tensor | None = None,
        intent_labels: torch.Tensor | None = None,
        slot_labels: torch.Tensor | None = None,
    ) -> Dict[str, object]:
        enc_out = self.encoder(
            input_ids=input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids,
            return_dict=True,
        )
        seq_output = self.dropout(enc_out.last_hidden_state)
        pooled = self.dropout(enc_out.pooler_output if enc_out.pooler_output is not None else seq_output[:, 0])

        intent_logits = self.intent_classifier(pooled)
        slot_logits = self.slot_classifier(seq_output)

        slot_mask = attention_mask.bool()
        slot_loss = None
        decoded = None
        if self.crf:
            if slot_labels is not None:
                slot_labels_crf = slot_labels.clone()
                slot_labels_crf[slot_labels_crf < 0] = self.slot_pad_id
                slot_loss = -self.crf(slot_logits, slot_labels_crf, mask=slot_mask, reduction="mean")
            decoded = self.crf.decode(slot_logits, mask=slot_mask)

        intent_loss = None
        if intent_labels is not None:
            intent_loss = nn.functional.cross_entropy(intent_logits, intent_labels)

        loss = None
        if intent_loss is not None and slot_loss is not None:
            loss = intent_loss + slot_loss
        elif intent_loss is not None:
            loss = intent_loss
        elif slot_loss is not None:
            loss = slot_loss

        return {
            "loss": loss,
            "intent_loss": intent_loss,
            "slot_loss": slot_loss,
            "intent_logits": intent_logits,
            "slot_logits": slot_logits,
            "slot_tags": decoded,
        }

def _load_label_config() -> Dict[str, object]:
    return json.loads(LABEL_CONFIG_JSON.read_text(encoding="utf-8"))

def _tokenize_and_align(
    tokenizer: AutoTokenizer,
    examples: Dict[str, List[object]],
    max_length: int,
) -> Dict[str, List[object]]:
    encoding = tokenizer(
        examples["tokens"],
        is_split_into_words=True,
        padding="max_length",
        truncation=True,
        max_length=max_length,
    )
    aligned_labels: List[List[int]] = []
    for i in range(len(examples["tokens"])):
        word_ids = encoding.word_ids(batch_index=i)  # type: ignore[arg-type]
        labels = examples["slot_label_ids"][i]  # type: ignore[index]
        label_ids: List[int] = []
        for word_id in word_ids:
            if word_id is None:
                label_ids.append(-100)
            else:
                label_ids.append(labels[word_id])
        aligned_labels.append(label_ids)
    encoding["slot_labels"] = aligned_labels
    encoding["intent_labels"] = examples["intent_id"]
    return encoding


def _build_dataloaders(
    dataset: DatasetDict,
    tokenizer: AutoTokenizer,
    cfg: TrainConfig,
) -> Tuple[DataLoader, DataLoader]:
    tokenized = dataset.map(
        lambda ex: _tokenize_and_align(tokenizer, ex, cfg.max_length),
        batched=True,
        remove_columns=list(dataset["train"].column_names),
    )
    tokenized.set_format(type="torch")
    train_loader = DataLoader(tokenized["train"], batch_size=cfg.batch_size, shuffle=True)
    val_loader = DataLoader(tokenized["test"], batch_size=cfg.batch_size, shuffle=False)
    return train_loader, val_loader


def _eval_intent_accuracy(model: JointRBT3Model, dataloader: DataLoader, cfg: TrainConfig) -> float:
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for batch in dataloader:
            input_ids = batch["input_ids"].to(cfg.device)
            attention_mask = batch["attention_mask"].to(cfg.device)
            token_type_ids = batch.get("token_type_ids")
            if token_type_ids is not None:
                token_type_ids = token_type_ids.to(cfg.device)
            intent_labels = batch["intent_labels"].to(cfg.device)
            outputs = model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                token_type_ids=token_type_ids,
            )
            preds = outputs["intent_logits"].argmax(dim=-1)
            correct += (preds == intent_labels).sum().item()
            total += intent_labels.numel()
    return correct / max(total, 1)

def _save_checkpoint(model: JointRBT3Model, label_cfg: Dict[str, object], cfg: TrainConfig, epoch: int) -> Path:
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = cfg.output_dir / f"joint_model_epoch_{epoch}.pt"
    torch.save({"model_state_dict": model.state_dict(), "label_config": label_cfg, "epoch": epoch}, ckpt_path)
    return ckpt_path


def train_joint(cfg: TrainConfig = TrainConfig()) -> None:
    if not cfg.cache_dir.exists():
        prepare_hf_datasets(PreprocessConfig(cache_dir=cfg.cache_dir, max_length=cfg.max_length))
    label_cfg = _load_label_config()
    slot_labels: List[str] = label_cfg["slot_labels"]
    num_slot_labels = len(slot_labels)
    num_intents = len(label_cfg["intent2id"])
    cfg.model_name = resolve_model_dir(label_cfg.get("model_name", cfg.model_name))

    tokenizer = AutoTokenizer.from_pretrained(cfg.model_name, use_fast=True)
    dataset = load_from_disk(cfg.cache_dir)
    train_loader, val_loader = _build_dataloaders(dataset, tokenizer, cfg)

    model = JointRBT3Model(cfg.model_name, num_intents=num_intents, num_slot_labels=num_slot_labels)
    model.to(cfg.device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    total_steps = max(1, len(train_loader) * cfg.num_epochs // cfg.grad_accum_steps)
    warmup_steps = int(total_steps * cfg.warmup_ratio)
    scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=warmup_steps, num_training_steps=total_steps)
    scaler = torch.cuda.amp.GradScaler(enabled=cfg.fp16 and cfg.device.startswith("cuda"))

    for epoch in range(cfg.num_epochs):
        model.train()
        running_loss = 0.0
        optimizer.zero_grad()
        pbar = tqdm(enumerate(train_loader), total=len(train_loader), desc=f"Epoch {epoch+1}")
        for step, batch in pbar:
            input_ids = batch["input_ids"].to(cfg.device)
            attention_mask = batch["attention_mask"].to(cfg.device)
            token_type_ids = batch.get("token_type_ids")
            if token_type_ids is not None:
                token_type_ids = token_type_ids.to(cfg.device)
            intent_labels = batch["intent_labels"].to(cfg.device)
            slot_labels = batch["slot_labels"].to(cfg.device)

            with torch.cuda.amp.autocast(enabled=cfg.fp16 and cfg.device.startswith("cuda")):
                outputs = model(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    token_type_ids=token_type_ids,
                    intent_labels=intent_labels,
                    slot_labels=slot_labels,
                )
                loss = outputs["loss"] / cfg.grad_accum_steps

            scaler.scale(loss).backward()

            if (step + 1) % cfg.grad_accum_steps == 0:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                scheduler.step()
                optimizer.zero_grad()

            running_loss += loss.item()
            if step % 10 == 0:
                pbar.set_postfix({"loss": f"{loss.item():.4f}"})
        intent_acc = _eval_intent_accuracy(model, val_loader, cfg)
        avg_loss = running_loss / max(len(train_loader), 1)
        print(f"Epoch {epoch+1}/{cfg.num_epochs} - loss: {avg_loss:.4f} - intent_acc: {intent_acc:.4f}")
        _save_checkpoint(model, label_cfg, cfg, epoch + 1)

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    torch.save({"model_state_dict": model.state_dict(), "label_config": label_cfg}, cfg.output_dir / "joint_model.pt")
    tokenizer.save_pretrained(cfg.output_dir)


def export_onnx(model_dir: Path | None = None, quantized: bool = True, max_length: int = 128) -> Path:
    """
    Export the trained joint model to ONNX and optionally quantize to INT8.
    """
    model_dir = model_dir or TrainConfig().output_dir
    label_cfg = _load_label_config()
    slot_labels: List[str] = label_cfg["slot_labels"]
    num_slot_labels = len(slot_labels)
    num_intents = len(label_cfg["intent2id"])

    onnx_path = model_dir / "joint_model.onnx"
    quant_path = model_dir / "joint_model.int8.onnx"

    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    state = torch.load(model_dir / "joint_model.pt", map_location="cpu")
    model = JointRBT3Model(resolve_model_dir(label_cfg.get("model_name")), num_intents=num_intents, num_slot_labels=num_slot_labels)
    model.load_state_dict(state["model_state_dict"])
    model.eval()

    class _OnnxWrapper(nn.Module):
        def __init__(self, base: JointRBT3Model) -> None:
            super().__init__()
            self.base = base

        def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor, token_type_ids: torch.Tensor | None = None):
            outputs = self.base(
                input_ids=input_ids,
                attention_mask=attention_mask,
                token_type_ids=token_type_ids,
            )
            return outputs["intent_logits"], outputs["slot_logits"]

    onnx_model = _OnnxWrapper(model)

    dummy = tokenizer(
        ["test"],
        is_split_into_words=False,
        padding="max_length",
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    torch.onnx.export(
        onnx_model,
        args=(
            dummy["input_ids"],
            dummy["attention_mask"],
            dummy.get("token_type_ids"),
        ),
        f=onnx_path,
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["intent_logits", "slot_logits"],
        opset_version=17,
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "token_type_ids": {0: "batch", 1: "seq"},
            "intent_logits": {0: "batch"},
            "slot_logits": {0: "batch", 1: "seq"},
        },
    )

    if quantized:
        try:
            from onnxruntime.quantization import QuantType, quantize_dynamic

            quantize_dynamic(
                model_input=onnx_path,
                model_output=quant_path,
                weight_type=QuantType.QInt8,
            )
            return quant_path
        except Exception as exc:  # pragma: no cover - optional dependency
            print(f"Quantization skipped: {exc}")
    return onnx_path


if __name__ == "__main__":
    train_joint()
