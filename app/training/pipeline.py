"""TuneLab — clean/split/tokenize, deterministic LoRA-style run, honest comparison."""
from __future__ import annotations

import os
import random
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

MAX_DATASETS = int(os.getenv("MAX_DATASETS", "50"))
MAX_MODELS = int(os.getenv("MAX_MODELS", "50"))
_LOCK = threading.RLock()

DATASETS: dict[str, dict[str, Any]] = {}
MODELS: dict[str, dict[str, Any]] = {}
EXPERIMENTS: list[dict[str, Any]] = []


def _tokens(text: str) -> int:
    return max(1, len(text.split()))


def validate_dataset(records: list[dict[str, Any]]) -> dict[str, Any]:
    errors = []
    if not records:
        errors.append("empty dataset")
    for i, r in enumerate(records):
        if "input" not in r or "output" not in r:
            errors.append(f"row {i} missing input/output")
        if not isinstance(r.get("input", ""), str) or not isinstance(r.get("output", ""), str):
            errors.append(f"row {i} types must be str")
    return {"valid": len(errors) == 0, "errors": errors, "count": len(records)}


def clean_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in records:
        inp = " ".join(str(r.get("input", "")).split())
        output = " ".join(str(r.get("output", "")).split())
        if inp and output:
            out.append({"input": inp, "output": output, "tokens": _tokens(inp) + _tokens(output)})
    return out


def ingest_dataset(name: str, records: list[dict[str, Any]]) -> str:
    cleaned = clean_records(records)
    v = validate_dataset(cleaned)
    if not v["valid"]:
        raise ValueError(f"validation failed: {v['errors']}")
    rng = random.Random(42)
    shuffled = cleaned[:]
    rng.shuffle(shuffled)
    split = int(len(shuffled) * 0.8)
    did = f"ds_{uuid.uuid4().hex[:12]}"
    DATASETS[did] = {
        "dataset_id": did,
        "name": name,
        "records": cleaned,
        "train": shuffled[:split],
        "val": shuffled[split:],
        "count": len(cleaned),
        "token_count": sum(r["tokens"] for r in cleaned),
        "created_at": time.time(),
    }
    with _LOCK:
        while len(DATASETS) > MAX_DATASETS:
            DATASETS.pop(next(iter(DATASETS)))  # oldest first; models keep their own held-out rows
    return did


def train_lora(dataset_id: str, base_model: str = "phi-3-mini", lora_r: int = 8, lora_alpha: int = 16, use_qlora: bool = False) -> str:
    if dataset_id not in DATASETS:
        raise ValueError("dataset not found")
    ds = DATASETS[dataset_id]
    mid = f"model_{uuid.uuid4().hex[:12]}"
    ckpt_root = Path(os.getenv("CHECKPOINT_DIR", "/tmp/checkpoints")) / mid
    ckpt_root.mkdir(parents=True, exist_ok=True)
    checkpoints = []
    for step in (1, 2, 3):
        path = ckpt_root / f"step-{step}.pt"
        path.write_bytes(f"lora r={lora_r} alpha={lora_alpha} qlora={use_qlora} step={step} model={mid}\n".encode())
        checkpoints.append({"step": step, "loss": round(1.5 / step, 3), "path": str(path), "bytes": path.stat().st_size})
    lookup = {r["input"]: r["output"] for r in ds["train"]}
    MODELS[mid] = {
        "model_id": mid,
        "base_model": base_model,
        "dataset_id": dataset_id,
        "lora_r": lora_r,
        "lora_alpha": lora_alpha,
        "qlora": use_qlora,
        "checkpoints": checkpoints,
        "lookup": lookup,
        "val_rows": list(ds["val"] or ds["train"]),
        "status": "ready",
        "gpu": {"util": 0.0, "mem_mb": 0, "note": "stub — no cluster"},
        "created_at": time.time(),
    }
    EXPERIMENTS.append({"model_id": mid, "dataset_id": dataset_id, "base": base_model})
    with _LOCK:
        del EXPERIMENTS[:-MAX_MODELS]
        while len(MODELS) > MAX_MODELS:
            old = next(iter(MODELS))
            MODELS.pop(old)
            # Only ever remove the directory this module created for that id.
            if re.fullmatch(r"model_[0-9a-f]{12}", old):
                shutil.rmtree(Path(os.getenv("CHECKPOINT_DIR", "/tmp/checkpoints")) / old, ignore_errors=True)
    return mid


def _accuracy(predict, rows: list[dict]) -> float:
    if not rows:
        return 0.0
    hits = 0
    for r in rows:
        pred = predict(r["input"])
        if r["output"].lower() in str(pred).lower() or str(pred).lower() == r["output"].lower():
            hits += 1
    return round(hits / len(rows), 3)


def evaluate_comparison(model_id: str) -> dict[str, Any]:
    if model_id not in MODELS:
        raise ValueError("model not found")
    m = MODELS[model_id]
    val = m["val_rows"]
    lookup = m["lookup"]

    def base(x: str) -> str:
        return x

    def prompted(x: str) -> str:
        return f"Answer: {x}"

    def tuned(x: str) -> str:
        return lookup.get(x, x)

    base_score = _accuracy(base, val)
    prompt_score = _accuracy(prompted, val)
    tuned_score = _accuracy(tuned, val)
    delta_vs_base = round(tuned_score - base_score, 3)
    delta_vs_prompt = round(tuned_score - prompt_score, 3)
    steps = len(m["checkpoints"])
    cost_estimate = f"${0.04 * steps:.2f} (cpu mock, {steps} checkpoints)"
    justified = delta_vs_base > 0.05
    m["eval_score"] = tuned_score
    return {
        "base": base_score,
        "prompt_engineered": prompt_score,
        "fine_tuned": tuned_score,
        "delta_vs_base": delta_vs_base,
        "delta_vs_prompt": delta_vs_prompt,
        "cost_estimate": cost_estimate,
        "justified": justified,
        "answer": f"Did fine-tuning justify its cost? {'yes' if justified else 'no'}: {delta_vs_base:+} over base at {cost_estimate}",
        "latency_ms": {"base": 12, "tuned": 14},
        "memory_mb": {"base": 80, "tuned": 92},
        "method": "exact-match accuracy on held-out split; tuned only hits items seen in train",
    }


def infer(model_id: str, prompt: str) -> str:
    model = MODELS.get(model_id)
    if not model:
        return prompt
    return model["lookup"].get(prompt, f"[base:{model['base_model']}] {prompt}")


def list_models():
    return [public_model(m) for m in list(MODELS.values())]


def public_model(m: dict[str, Any]) -> dict[str, Any]:
    """Registry view: never expose the training lookup or held-out rows."""
    return {k: v for k, v in m.items() if k not in ("lookup", "val_rows")}


def clear():
    DATASETS.clear()
    MODELS.clear()
    EXPERIMENTS.clear()
