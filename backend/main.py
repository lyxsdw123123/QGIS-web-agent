"""QGIS Web Agent MVP — FastAPI 后端。

启动：在项目根目录运行
    uvicorn backend.main:app --reload --port 8000
然后打开 http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import iterate_in_threadpool

from . import engine as engine_mod
from .agent import Agent, QWEN_MODEL
from .store import LayerStore

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
DATA_DIR = BASE_DIR / "data"


def _load_env():
    """读取项目根目录 .env（若存在），已存在的环境变量不覆盖。"""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env()

store = LayerStore()
engine = engine_mod.create_engine()
agent = Agent(store, engine, DATA_DIR)

app = FastAPI(title="QGIS Web Agent MVP")


class ChatRequest(BaseModel):
    text: str = ""


# ---------- 配置 ----------
@app.get("/api/config")
def config():
    return {
        "engine": engine.name,
        "model": QWEN_MODEL,
        "has_api_key": bool(os.environ.get("DASHSCOPE_API_KEY")),
    }


# ---------- 图层 ----------
@app.get("/api/layers")
def list_layers():
    return {"layers": store.list()}


@app.get("/api/layers/{lid}/data.geojson")
def layer_data(lid: str):
    layer = store.get(lid)
    if layer is None or layer.get("layer_type") != "vector":
        raise HTTPException(404, "矢量图层不存在")
    return JSONResponse(layer["geojson"])


@app.get("/api/layers/{lid}/file")
def layer_file(lid: str):
    """栅格图层的图片（浏览器不能显示 GeoTIFF，统一转成 PNG）。"""
    layer = store.get(lid)
    if layer is None or layer.get("layer_type") != "raster":
        raise HTTPException(404, "栅格图层不存在")
    return FileResponse(layer["png_path"], media_type="image/png")


@app.get("/api/layers/{lid}/download")
def layer_download(lid: str):
    layer = store.get(lid)
    if layer is None:
        raise HTTPException(404, "图层不存在")
    name = layer["name"]
    if layer.get("layer_type") == "raster":
        return FileResponse(layer["png_path"], media_type="image/png",
                            filename=f"{name}.png")
    # header 只能用 latin-1，中文文件名走 RFC 5987 的 filename*=UTF-8''...
    safe = f"{lid}.geojson"
    utf8_name = quote(f"{name}.geojson")
    headers = {"Content-Disposition": f"attachment; filename=\"{safe}\"; filename*=UTF-8''{utf8_name}"}
    return JSONResponse(layer["geojson"], headers=headers)


@app.delete("/api/layers/{lid}")
def layer_delete(lid: str):
    if store.delete(lid) is None:
        raise HTTPException(404, "图层不存在")
    return {"ok": True}


@app.post("/api/layers")
async def upload_layer(file: UploadFile):
    raw = await file.read()
    try:
        geojson = json.loads(raw)
    except Exception:
        raise HTTPException(400, "不是合法 GeoJSON（MVP 仅支持单个 GeoJSON 文件）")
    name = Path(file.filename or "上传图层").stem
    lid = store.add(name=name, geojson=geojson)
    return store.meta(lid)


@app.post("/api/demo/load")
def load_demo():
    path = DATA_DIR / "sample_roads.geojson"
    if not path.exists():
        raise HTTPException(500, "示例数据缺失，请先运行 scripts/make_sample.py")
    geojson = json.loads(path.read_text(encoding="utf-8"))
    lid = store.add(name="示例道路（武汉）", geojson=geojson)
    return store.meta(lid)


# ---------- 对话（SSE 流式） ----------
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
async def chat(body: ChatRequest):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "消息为空")

    async def gen():
        async for event, data in iterate_in_threadpool(agent.chat_stream(text)):
            yield _sse(event, data)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------- 前端静态（放在最后，避免遮蔽 /api 路由） ----------
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
