"""Test harness: real PostgreSQL + pgvector; stand-ins only for downloadable models and paid APIs."""
import os
import tempfile
from pathlib import Path

import numpy as np
import pytest

TMP = Path(tempfile.mkdtemp(prefix="agri-test-"))
os.environ.update({
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "postgresql://agri@localhost:5433/agri_test"),
    "EMBEDDING_PROVIDER": "hash", "CROP_BACKEND": "bioclip", "LLM_PROVIDER": "none", "STT_PROVIDER": "none",
    "API_KEY": "test-key", "MEDIA_DIR": str(TMP / "media"), "HEADS_DIR": str(TMP / "heads"),
    "RATE_LIMIT_PER_10MIN": "1000",
})

from agri import db, knowledge, llm, vision, language  # noqa: E402
from agri.taxonomy import crops, taxonomy  # noqa: E402


class FakeZeroShot:
    """Stands in for BioCLIP 2. `scenario` sets what the 'model' sees in the next photo."""

    def __init__(self):
        self.scenario = {"plant": True, "crop": "chilli", "p": 0.92, "tiles": None}
        self._tile_calls = 0

    def scores(self, img, prompts):
        t = taxonomy()
        n = len(prompts)
        if prompts[0] == t["plant_prompts"][0]:
            npos = len(t["plant_prompts"])
            p = np.full(n, 0.02 / max(n - npos, 1))
            if self.scenario["plant"]:
                p[:npos] = 0.95 / npos
                p[npos:] = 0.05 / (n - npos)
            else:
                p[:npos] = 0.1 / npos
                p[npos:] = 0.9 / (n - npos)
            return np.log(p)
        crop, prob = self.scenario["crop"], self.scenario["p"]
        if img.size[0] < 500 and self.scenario.get("tiles"):  # quarter tiles of a 640 px image
            crop = self.scenario["tiles"][self._tile_calls % 4]
            self._tile_calls += 1
            prob = 0.9
        keys, _ = vision.crop_prompts()
        target = keys.index(crop)
        p = np.full(n, (1 - prob) / (n - 1))
        p[target] = prob
        return np.log(p)


@pytest.fixture(scope="session", autouse=True)
def database():
    db.init_db()
    yield
    db.close_pool()


@pytest.fixture(autouse=True)
def clean(database):
    db.execute("TRUNCATE feedback, escalations, diagnoses, messages, cases, users, product_targets, products, chunks, documents CASCADE")
    import shutil

    shutil.rmtree(os.environ["HEADS_DIR"], ignore_errors=True)
    vision.get_head.cache_clear()
    llm.set_llm(None)
    language.set_stt(None)
    yield


@pytest.fixture
def zs():
    z = FakeZeroShot()
    vision.set_zero_shot(z)
    yield z
    vision.set_zero_shot(None)


def make_image(name: str, kind: str = "leaf", size=(640, 480)) -> str:
    from PIL import Image, ImageFilter

    rng = np.random.default_rng(0)
    if kind == "leaf":
        base = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        base[..., 1] = 140
        noise = rng.integers(0, 90, (size[1], size[0], 3), dtype=np.uint8)
        arr = base + noise
    elif kind == "dark":
        arr = rng.integers(0, 25, (size[1], size[0], 3), dtype=np.uint8)
    else:  # blurry
        arr = rng.integers(60, 200, (size[1], size[0], 3), dtype=np.uint8)
    img = Image.fromarray(arr)
    if kind == "blurry":
        img = img.filter(ImageFilter.GaussianBlur(12))
    p = TMP / name
    img.save(p, quality=92)
    return str(p)


def make_head(crop: str, labels: list[str], bias: list[float]) -> None:
    """Tiny real ONNX classifier (global-average-pool + linear) standing in for a trained head."""
    import json

    import onnx
    from onnx import TensorProto, helper

    n = len(labels)
    W = helper.make_tensor("W", TensorProto.FLOAT, [3, n], [0.0] * (3 * n))
    B = helper.make_tensor("B", TensorProto.FLOAT, [n], bias)
    nodes = [helper.make_node("GlobalAveragePool", ["input"], ["gap"]),
             helper.make_node("Flatten", ["gap"], ["flat"]),
             helper.make_node("MatMul", ["flat", "W"], ["mm"]),
             helper.make_node("Add", ["mm", "B"], ["logits"])]
    g = helper.make_graph(nodes, "head", [helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 64, 64])],
                          [helper.make_tensor_value_info("logits", TensorProto.FLOAT, [1, n])], initializer=[W, B])
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 17)])
    m.ir_version = 8
    d = Path(os.environ["HEADS_DIR"]) / crop
    d.mkdir(parents=True, exist_ok=True)
    onnx.save(m, d / "model.onnx")
    (d / "labels.json").write_text(json.dumps({"labels": labels, "temperature": 1.0, "input_size": 64, "version": f"{crop}-test"}))
    vision.get_head.cache_clear()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from agri.api import app

    c = TestClient(app)
    c.headers["X-API-Key"] = "test-key"
    return c


class Chat:
    """Drives the public API the way the Telegram adapter does."""

    def __init__(self, client, user="farmer-1"):
        self.c, self.user = client, user

    def send(self, text=None, button=None, image=None, voice=None):
        data = {"user_ref": self.user, "channel": "telegram"}
        if text:
            data["text"] = text
        if button:
            data["button"] = button
        files = []
        if image:
            files.append(("images", ("p.jpg", open(image, "rb"), "image/jpeg")))
        if voice:
            files.append(("voice", ("v.ogg", open(voice, "rb"), "audio/ogg")))
        r = self.c.post("/v1/chat/messages", data=data, files=files or None)
        assert r.status_code == 200, r.text
        return r.json()


@pytest.fixture
def chat(client):
    return Chat(client)


def tomato_names() -> list[str]:
    out = []
    for p in crops()["tomato"]["problems"].values():
        out += [p["en"], p["ta"], p["tl"]]
    return [n for n in out if n not in {v for c in ("chilli",) for q in crops()[c]["problems"].values() for v in (q["en"], q["ta"], q["tl"])}]
