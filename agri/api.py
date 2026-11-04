"""Channel-independent REST API. Telegram is just one client of /v1/chat/messages."""
from __future__ import annotations

import logging
import shutil
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import db, knowledge, orchestrator, products, vision
from .config import get_settings
from .contracts import InboundMessage, Media, Reply

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = FastAPI(title="Vishakan Agri Assistant API", version="0.1.0")


def auth(x_api_key: str = Header(default="")) -> None:
    if x_api_key != get_settings().api_key:
        raise HTTPException(401, "invalid API key")


def _save_upload(f: UploadFile, kind: str) -> Media:
    d = Path(get_settings().media_dir)
    d.mkdir(parents=True, exist_ok=True)
    ext = Path(f.filename or "").suffix.lower() or (".jpg" if kind == "image" else ".ogg")
    p = d / f"{uuid.uuid4().hex}{ext}"
    with p.open("wb") as out:
        shutil.copyfileobj(f.file, out)
    return Media(kind=kind, path=str(p), mime=f.content_type or "")


@app.get("/v1/health")
def health():
    db.fetchone("SELECT 1 AS ok")
    return {"status": "ok"}


@app.post("/v1/chat/messages", response_model=Reply, dependencies=[Depends(auth)])
def chat(user_ref: str = Form(...), channel: str = Form("api"), text: str | None = Form(None),
         button: str | None = Form(None), idempotency_key: str | None = Form(None), user_name: str | None = Form(None),
         images: list[UploadFile] = File(default=[]), voice: UploadFile | None = File(default=None)):
    media = [_save_upload(f, "image") for f in images if f and f.filename]
    if voice is not None and voice.filename:
        media.append(_save_upload(voice, "voice"))
    msg = InboundMessage(channel=channel, user_ref=user_ref, text=text, media=media, button=button,
                         idempotency_key=idempotency_key, user_name=user_name)
    return orchestrator.handle(msg)


@app.get("/v1/media/{name}", dependencies=[Depends(auth)])
def media(name: str):
    p = (Path(get_settings().media_dir) / Path(name).name).resolve()
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


@app.post("/v1/vision/diagnose", dependencies=[Depends(auth)])
def diagnose(image: UploadFile = File(...), crop_hint: str | None = Form(None)):
    m = _save_upload(image, "image")
    r = vision.analyse(m.path, crop_hint)
    out = r.as_dict()
    out["crop_top"] = [{"crop": c, "confidence": vision.pct(p)} for c, p in r.crop_top]
    out["disease_top"] = [{"label": c, "confidence": vision.pct(p)} for c, p in r.disease_top]
    return out


class KQuery(BaseModel):
    question: str
    crop: str | None = None


@app.post("/v1/knowledge/query", dependencies=[Depends(auth)])
def kquery(q: KQuery):
    hits = knowledge.retrieve(q.question, q.crop)
    return {"grounded": bool(hits), "passages": [h.__dict__ for h in hits]}


class RecQuery(BaseModel):
    crop: str
    problems: list[str]


@app.post("/v1/recommendations", dependencies=[Depends(auth)])
def recommend(q: RecQuery):
    ms = products.recommend(q.crop, q.problems)
    return {"status": "matched" if any(m.exact for m in ms) else "no_verified_product", "products": [m.__dict__ for m in ms]}


@app.get("/v1/products", dependencies=[Depends(auth)])
def list_products(crop: str):
    return [m.__dict__ for m in products.products_for_crop(crop)]


class AgroReply(BaseModel):
    text: str
    verified_crop: str | None = None
    verified_label: str | None = None


@app.post("/v1/escalations/{code}/reply", dependencies=[Depends(auth)])
def escalation_reply(code: str, body: AgroReply):
    out = orchestrator.agronomist_reply(code, body.text, body.verified_crop, body.verified_label)
    if not out:
        raise HTTPException(404, "unknown case code")
    return out


@app.post("/v1/admin/products", dependencies=[Depends(auth)])
def admin_products(file: UploadFile = File(...)):
    m = _save_upload(file, "image")
    return products.load_products_csv(m.path)


@app.post("/v1/admin/documents", dependencies=[Depends(auth)])
def admin_documents(file: UploadFile | None = File(default=None), url: str | None = Form(None),
                    source_type: str = Form("brochure")):
    if file is not None and file.filename:
        m = _save_upload(file, "image")
        dest = Path(m.path).with_name(file.filename)
        Path(m.path).rename(dest)
        return {"result": knowledge.ingest_pdf(str(dest), source_type)}
    if url:
        return knowledge.crawl(url)
    raise HTTPException(400, "send a PDF file or a url")
