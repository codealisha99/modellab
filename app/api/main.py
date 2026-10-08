"""ModelLab FastAPI — training pipeline + memory + resumable token streams."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from ..training.pipeline import ingest_dataset, train_lora, evaluate_comparison, list_models, validate_dataset, clean_records, clear as clear_training, DATASETS
from ..memory.memos import add_memory, retrieve, compress_working, stats, clear as clear_mem, WORKING, EPISODIC, SEMANTIC
from ..observability.otel import init_tracing, span, current_trace_id
from ..streaming.routes import build_router
from ..streaming.store import StreamSettings, StreamStore
from .guard import GuardMiddleware

init_tracing("modellab")
streams = StreamStore(StreamSettings.from_env())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await streams.start()  # background reaper for expired streams
    try:
        yield
    finally:
        await streams.close()


app = FastAPI(
    title="ModelLab",
    version="1.1.0",
    description="Training (LoRA/QLoRA) + Memory (working/episodic/semantic) + resumable SSE streams. Stream tokens are simulated.",
    lifespan=lifespan,
)
app.add_middleware(GuardMiddleware)


@app.exception_handler(RequestValidationError)
async def request_error(request, exc):
    # Pydantic's default 422 echoes submitted input; return metadata only.
    return JSONResponse(
        {"detail": [{"path": ".".join(map(str, e["loc"])), "message": e["msg"], "type": e["type"]} for e in exc.errors()]}, 422
    )

@app.get("/health")
def health(): return {"status":"ok","service":"modellab"}

# ----- datasets -----
class DatasetIngest(BaseModel):
    name: str
    records: List[Dict[str, Any]]

@app.post("/v1/datasets/validate")
def post_validate(body: DatasetIngest):
    return validate_dataset(clean_records(body.records))


@app.post("/v1/datasets")
def post_dataset(body: DatasetIngest):
    try:
        did = ingest_dataset(body.name, body.records)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"dataset_id": did, "count": len(body.records)}

@app.get("/v1/datasets/{dataset_id}")
def get_dataset(dataset_id: str):
    if dataset_id not in DATASETS:
        raise HTTPException(404, "dataset not found")
    d = DATASETS[dataset_id]
    return {"dataset_id": dataset_id, "name": d["name"], "count": d["count"], "train": len(d["train"]), "val": len(d["val"])}

# ----- training -----
class TrainRequest(BaseModel):
    dataset_id: str
    base_model: str = "phi-3-mini"
    lora_r: int = 8
    lora_alpha: int = 16
    use_qlora: bool = False

@app.post("/v1/training/run")
def post_train(body: TrainRequest):
    try:
        with span("modellab.train", dataset_id=body.dataset_id, base_model=body.base_model):
            mid = train_lora(body.dataset_id, body.base_model, body.lora_r, body.lora_alpha, body.use_qlora)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"model_id": mid, "trace_id": current_trace_id()}

@app.get("/v1/models")
def get_models():
    return {"models": list_models()}

@app.get("/v1/models/{model_id}")
def get_model(model_id: str):
    from ..training.pipeline import MODELS
    if model_id not in MODELS:
        raise HTTPException(404, "model not found")
    return MODELS[model_id]

@app.post("/v1/models/{model_id}/evaluate")
def post_evaluate(model_id: str):
    try:
        return evaluate_comparison(model_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

@app.post("/v1/inference")
def inference(body: Dict[str, Any]):
    model_id = body.get("model_id")
    prompt = body.get("prompt","")
    from ..training.pipeline import MODELS
    if model_id and model_id not in MODELS:
        raise HTTPException(404, "model not found")
    from ..training.pipeline import infer

    return {"model_id": model_id or "base", "prompt": prompt, "completion": infer(model_id, prompt) if model_id else prompt, "tokens": len(prompt)//4}

# ----- memory -----
class MemoryAdd(BaseModel):
    text: str
    kind: str = "episodic"
    importance: float = 0.5
    metadata: Optional[Dict[str, Any]] = None

@app.post("/v1/memory")
def post_memory(body: MemoryAdd, x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")):
    if body.kind not in ("working","episodic","semantic"):
        raise HTTPException(400, "kind must be working|episodic|semantic")
    return add_memory(body.text, body.kind, body.importance, body.metadata, tenant_id=x_tenant_id or "default")

@app.get("/v1/memory/search")
def search_memory(q: str, kind: Optional[str] = None, top_k: int = 5, x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")):
    return {"results": retrieve(q, kind, top_k, tenant_id=x_tenant_id or "default")}

@app.get("/v1/memory/eval")
def mem_eval():
    from ..memory.memos import eval_relevance

    return eval_relevance(20)


@app.get("/v1/memory/stats")
def mem_stats(x_tenant_id: Optional[str] = Header(default=None, alias="X-Tenant-Id")):
    return stats(x_tenant_id)

@app.post("/v1/memory/compress")
def mem_compress():
    return {"summary": compress_working()}

# ----- streaming -----
def _known_model(model_id: str) -> bool:
    from ..training.pipeline import MODELS
    return model_id in MODELS


app.include_router(build_router(streams, _known_model))

STATIC = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def playground():
    return FileResponse(STATIC / "index.html")
