"""Restart recovery and failed-write behavior of the durable demo stores."""
from copy import deepcopy
from pathlib import Path

import pytest

from app import persistence
from app.memory import memos
from app.training import pipeline


@pytest.fixture
def database(monkeypatch, tmp_path):
    snapshots = {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    monkeypatch.setenv("CHECKPOINT_DIR", str(tmp_path / "first"))
    monkeypatch.setattr(persistence, "save", lambda key, value: snapshots.update({key: deepcopy(value)}))
    monkeypatch.setattr(persistence, "load", lambda key: deepcopy(snapshots.get(key)))
    pipeline.clear()
    memos.clear()
    yield snapshots
    pipeline.clear()
    memos.clear()


def test_restart_restores_training_memory_and_checkpoint_files(database, monkeypatch, tmp_path):
    did = pipeline.ingest_dataset("restart", [{"input": "hello", "output": "world"}] * 5)
    mid = pipeline.train_lora(did)
    pipeline.evaluate_comparison(mid)
    memory = memos.add_memory("persist across restart", tenant_id="alice")
    memos.add_memory("another tenant", tenant_id="bob")
    pipeline.clear()
    memos.clear()
    monkeypatch.setenv("CHECKPOINT_DIR", str(tmp_path / "second"))
    pipeline.restore()
    memos.restore()
    assert pipeline.infer(mid, "hello") == "world"
    assert pipeline.DATASETS[did]["count"] == 5
    assert "eval_score" in pipeline.MODELS[mid]
    assert all(Path(c["path"]).is_file() for c in pipeline.MODELS[mid]["checkpoints"])
    assert memos.retrieve("persist across restart", tenant_id="alice")[0]["memory"] == memory
    assert memos.stats("alice")["episodic"] == 1
    assert memos.stats("bob")["episodic"] == 1


def test_database_failure_rolls_back_ram(database, monkeypatch):
    memos.add_memory("original", tenant_id="alice")
    before = deepcopy(memos.EPISODIC)

    def fail(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(persistence, "save", fail)
    with pytest.raises(RuntimeError):
        memos.add_memory("uncommitted", tenant_id="alice")
    assert memos.EPISODIC == before
    with pytest.raises(RuntimeError):
        pipeline.ingest_dataset("uncommitted", [{"input": "a", "output": "b"}])
    assert pipeline.DATASETS == {}


def test_eval_never_persists_private_tenant(database):
    memos.add_memory("real memory", tenant_id="alice")
    before = deepcopy(database)
    assert memos.eval_relevance()["pass"]
    assert database == before
    assert all(m["tenant_id"] != memos.EVAL_TENANT for m in memos.SEMANTIC)
