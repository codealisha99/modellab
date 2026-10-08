"""ModelLab FastAPI — training pipeline + memory + resumable token streams."""
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Annotated, Any, Dict, List, Literal, Optional

from ..training.pipeline import ingest_dataset, train_lora, evaluate_comparison, list_models, public_model, infer, validate_dataset, clean_records, DATASETS, MODELS
from ..memory.memos import add_memory, retrieve, compress_working, stats, eval_relevance, EVAL_TENANT
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
def health():
    return {"status": "ok", "service": "modellab"}


Tenant = Annotated[Optional[str], Header(alias="X-Tenant-Id", max_length=64)]
TENANT_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def tenant_of(header: Optional[str]) -> str:
    """Tenant ids become dictionary keys and log fields: keep them boring."""
    if header is None or header == "":
        return "default"
    if not TENANT_RE.fullmatch(header) or header == EVAL_TENANT:
        raise HTTPException(400, "X-Tenant-Id must be 1-64 characters of letters, digits, '_', '.' or '-'.")
    return header


# ----- datasets -----
class DatasetIngest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=120)]
    records: Annotated[List[Dict[str, Any]], Field(max_length=5000)]


@app.post("/v1/datasets/validate")
def post_validate(body: DatasetIngest):
    cleaned = clean_records(body.records)
    return {**validate_dataset(cleaned), "dropped": len(body.records) - len(cleaned)}


@app.post("/v1/datasets")
def post_dataset(body: DatasetIngest):
    try:
        did = ingest_dataset(body.name, body.records)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"dataset_id": did, "count": len(body.records), "kept": DATASETS.get(did, {}).get("count")}


@app.get("/v1/datasets/{dataset_id}")
def get_dataset(dataset_id: str):
    if dataset_id not in DATASETS:
        raise HTTPException(404, "dataset not found")
    d = DATASETS[dataset_id]
    return {"dataset_id": dataset_id, "name": d["name"], "count": d["count"], "train": len(d["train"]), "val": len(d["val"])}


# ----- training -----
class TrainRequest(BaseModel):
    dataset_id: Annotated[str, Field(min_length=1, max_length=64)]
    base_model: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:/-]+$")] = "phi-3-mini"
    lora_r: Annotated[int, Field(strict=True, ge=1, le=256)] = 8
    lora_alpha: Annotated[int, Field(strict=True, ge=1, le=1024)] = 16
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
    if model_id not in MODELS:
        raise HTTPException(404, "model not found")
    return public_model(MODELS[model_id])


@app.post("/v1/models/{model_id}/evaluate")
def post_evaluate(model_id: str):
    try:
        return evaluate_comparison(model_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


class InferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: Annotated[Optional[str], Field(max_length=64)] = None
    prompt: Annotated[str, Field(max_length=4000)] = ""


@app.post("/v1/inference")
def inference(body: InferenceRequest):
    if body.model_id and body.model_id not in MODELS:
        raise HTTPException(404, "model not found")
    return {
        "model_id": body.model_id or "base",
        "prompt": body.prompt,
        "completion": infer(body.model_id, body.prompt) if body.model_id else body.prompt,
        "tokens": len(body.prompt) // 4,
    }


# ----- memory -----
class MemoryAdd(BaseModel):
    text: Annotated[str, Field(min_length=1, max_length=4000)]
    kind: Literal["working", "episodic", "semantic"] = "episodic"
    importance: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] = 0.5
    metadata: Optional[Dict[str, Any]] = None

    @field_validator("metadata")
    @classmethod
    def small_metadata(cls, v):
        if v is not None and len(json.dumps(v, default=str)) > 2000:
            raise ValueError("metadata must be at most 2000 characters as JSON")
        return v


@app.post("/v1/memory")
def post_memory(body: MemoryAdd, x_tenant_id: Tenant = None):
    return add_memory(body.text, body.kind, body.importance, body.metadata, tenant_id=tenant_of(x_tenant_id))


@app.get("/v1/memory/search")
def search_memory(
    q: Annotated[str, Query(min_length=1, max_length=500)],
    kind: Optional[Literal["working", "episodic", "semantic"]] = None,
    top_k: Annotated[int, Query(ge=1, le=50)] = 5,
    x_tenant_id: Tenant = None,
):
    return {"results": retrieve(q, kind, top_k, tenant_id=tenant_of(x_tenant_id))}


@app.get("/v1/memory/eval")
def mem_eval():
    # Runs in a private tenant; real memory is never touched.
    return eval_relevance(20)


@app.get("/v1/memory/stats")
def mem_stats(x_tenant_id: Tenant = None):
    return stats(tenant_of(x_tenant_id))


@app.post("/v1/memory/compress")
def mem_compress(x_tenant_id: Tenant = None):
    return {"summary": compress_working(tenant_of(x_tenant_id))}


# ----- streaming -----
def _known_model(model_id: str) -> bool:
    return model_id in MODELS


app.include_router(build_router(streams, _known_model))

STATIC = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def playground():
    return FileResponse(STATIC / "index.html")
