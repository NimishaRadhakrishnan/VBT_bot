"""Vision cascade: quality gate -> plant gate -> crop ID -> crop-specific disease head.

Every stage can stop the pipeline with an action that asks the farmer for something,
instead of guessing. No stage can emit a label that belongs to another crop."""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import numpy as np
from PIL import Image, ImageOps

from .config import get_settings
from .llm import get_llm, has_llm, parse_json
from .taxonomy import crops, problems, symptom_keys, taxonomy

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- helpers
def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    z = np.asarray(logits, dtype=np.float64) / max(temperature, 1e-6)
    z = z - z.max()
    e = np.exp(z)
    p = e / e.sum()
    if not np.all(np.isfinite(p)) or abs(p.sum() - 1) > 1e-4:
        raise ValueError("non-finite probabilities")
    return p


def pct(p: float) -> str:
    """Display rounded to 5% so we never imply false precision; never NaN."""
    if not math.isfinite(p):
        raise ValueError("refusing to display a non-finite probability")
    return f"{int(round(p * 20) * 5)}%"


def load_image(path: str) -> Image.Image:
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    return img.convert("RGB")


# ---------------------------------------------------------------- stage 1: quality
@dataclass
class Quality:
    ok: bool
    reason: str | None
    blur: float
    brightness: float
    min_side: int


def check_quality(img: Image.Image) -> Quality:
    s = get_settings()
    w, h = img.size
    g = np.asarray(ImageOps.grayscale(img.copy()).resize((512, int(512 * h / w)) if w > 512 else (w, h)), dtype=np.float64)
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    blur = float(lap.var())
    bright = float(g.mean())
    reason = None
    if min(w, h) < s.min_side_px:
        reason = "too_small"
    elif bright < 40:
        reason = "too_dark"
    elif bright > 225:
        reason = "too_bright"
    elif blur < s.blur_threshold:
        reason = "blurry"
    return Quality(reason is None, reason, round(blur, 1), round(bright, 1), min(w, h))


# ---------------------------------------------------------------- stage 2-3: plant gate + crop ID
class ZeroShot(Protocol):
    def scores(self, img: Image.Image, prompts: list[str]) -> np.ndarray:  # logits, one per prompt
        ...


class BioCLIP:
    """BioCLIP 2 via open_clip (needs requirements-ml.txt). Loaded once, lazily."""

    def __init__(self, name: str):
        import open_clip
        import torch

        self.torch = torch
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(name)
        self.tokenizer = open_clip.get_tokenizer(name)
        self.model.eval()
        self._cache: dict[tuple, object] = {}

    def _text(self, prompts: list[str]):
        key = tuple(prompts)
        if key not in self._cache:
            with self.torch.no_grad():
                t = self.model.encode_text(self.tokenizer(prompts))
                self._cache[key] = t / t.norm(dim=-1, keepdim=True)
        return self._cache[key]

    def scores(self, img, prompts):
        with self.torch.no_grad():
            x = self.preprocess(img).unsqueeze(0)
            f = self.model.encode_image(x)
            f = f / f.norm(dim=-1, keepdim=True)
            logits = 100.0 * f @ self._text(prompts).T
        return logits[0].float().numpy()


_zs: ZeroShot | None = None
_zs_failed = False


def get_zero_shot() -> ZeroShot | None:
    global _zs, _zs_failed
    s = get_settings()
    if _zs is None and not _zs_failed and s.crop_backend == "bioclip":
        try:
            _zs = BioCLIP(s.bioclip_model)
        except Exception as e:  # weights not downloadable, torch missing ...
            log.warning("BioCLIP unavailable (%s); falling back to VLM crop guess", e)
            _zs_failed = True
    return _zs


def set_zero_shot(zs: ZeroShot | None) -> None:
    global _zs, _zs_failed
    _zs, _zs_failed = zs, False


def crop_prompts() -> tuple[list[str], list[str]]:
    keys, prompts = [], []
    for k, c in crops().items():
        for sci in c["scientific"]:
            keys.append(k)
            prompts.append(f"a photo of {sci}, {c['en'].lower()} plant")
    keys.append("other")
    prompts.append("a photo of a plant that is not a crop, a weed or garden plant")
    return keys, prompts


def classify_crop(zs: ZeroShot, img: Image.Image, temperature: float = 1.0) -> list[tuple[str, float]]:
    keys, prompts = crop_prompts()
    p = softmax(zs.scores(img, prompts), temperature)
    agg: dict[str, float] = {}
    for k, v in zip(keys, p):
        agg[k] = agg.get(k, 0.0) + float(v)
    return sorted(agg.items(), key=lambda kv: -kv[1])


def plant_probability(zs: ZeroShot, img: Image.Image) -> float:
    t = taxonomy()
    pos, neg = t["plant_prompts"], t["non_plant_prompts"]
    p = softmax(zs.scores(img, pos + neg))
    return float(p[: len(pos)].sum())


def tiles(img: Image.Image) -> list[Image.Image]:
    w, h = img.size
    return [img.crop((x, y, x + w // 2, y + h // 2)) for x in (0, w // 2) for y in (0, h // 2)]


# ---------------------------------------------------------------- stage 4: crop-specific heads
class Head:
    """ONNX classifier for ONE crop. labels.json must only contain that crop's problems."""

    def __init__(self, crop: str, folder: Path):
        import onnxruntime as ort

        meta = json.loads((folder / "labels.json").read_text())
        allowed = set(problems(crop)) | {"healthy", "other_or_unclear"}
        bad = [l for l in meta["labels"] if l not in allowed]
        if bad:
            raise ValueError(f"head for {crop} has labels outside its crop taxonomy: {bad}")
        self.crop, self.labels = crop, meta["labels"]
        self.temperature = float(meta.get("temperature", 1.0))
        self.size = int(meta.get("input_size", 384))
        self.mean = np.array(meta.get("mean", [0.485, 0.456, 0.406]), dtype=np.float32)
        self.std = np.array(meta.get("std", [0.229, 0.224, 0.225]), dtype=np.float32)
        self.version = meta.get("version", folder.name)
        self.sess = ort.InferenceSession(str(folder / "model.onnx"), providers=["CPUExecutionProvider"])

    def predict(self, img: Image.Image) -> list[tuple[str, float]]:
        x = np.asarray(img.resize((self.size, self.size)), dtype=np.float32) / 255.0
        x = ((x - self.mean) / self.std).transpose(2, 0, 1)[None].astype(np.float32)
        logits = self.sess.run(None, {self.sess.get_inputs()[0].name: x})[0][0]
        if not np.all(np.isfinite(logits)):
            raise ValueError("non-finite logits")
        p = softmax(logits, self.temperature)
        return sorted(zip(self.labels, map(float, p)), key=lambda kv: -kv[1])


@lru_cache
def get_head(crop: str) -> Head | None:
    folder = get_settings().heads_dir / crop
    if not (folder / "model.onnx").exists():
        return None
    try:
        return Head(crop, folder)
    except Exception as e:
        log.error("could not load head for %s: %s", crop, e)
        return None


# ---------------------------------------------------------------- VLM (evidence only)
VLM_SYSTEM = (
    "You are a plant-image inspector for an agricultural assistant. Describe only what is visible. "
    "Never diagnose a disease. Answer in JSON."
)


def vlm_inspect(image_path: str, crop_keys: list[str]) -> dict | None:
    if not has_llm():
        return None
    prompt = (
        "Look at the photo and return JSON with keys:\n"
        '"is_plant": true/false, "crop": one of ' + json.dumps(crop_keys + ["other", "unknown"]) + ",\n"
        '"several_crops": true/false, "symptoms": a list using ONLY these keys ' + json.dumps(symptom_keys()) + ",\n"
        '"description": one short English sentence of what is visible.'
    )
    out = parse_json(get_llm().generate(VLM_SYSTEM, prompt, images=[image_path], json_mode=True))
    if not out:
        return None
    out["symptoms"] = [s for s in out.get("symptoms", []) if s in symptom_keys()]
    if out.get("crop") not in crop_keys + ["other", "unknown"]:
        out["crop"] = "unknown"
    return out


# ---------------------------------------------------------------- the cascade
@dataclass
class VisionResult:
    action: str  # ok | ask_clearer | not_plant | ask_crop | multiple_plants | confirm_crop | error
    reason: str | None = None
    crop: str | None = None
    crop_source: str | None = None  # vision | farmer | vlm
    crop_top: list[tuple[str, float]] = field(default_factory=list)  # only from calibrated zero-shot
    crop_display: str | None = None
    disease_top: list[tuple[str, float]] = field(default_factory=list)  # only from a trained head
    head_version: str | None = None
    symptoms_seen: list[str] = field(default_factory=list)
    description: str | None = None
    quality: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def analyse(image_path: str, crop_hint: str | None = None, hint_confirmed: bool = False) -> VisionResult:
    s = get_settings()
    try:
        img = load_image(image_path)
    except Exception:
        return VisionResult("error", reason="unreadable")

    q = check_quality(img)
    if not q.ok:
        return VisionResult("ask_clearer", reason=q.reason, quality=q.__dict__)

    zs = get_zero_shot()
    crop_keys = list(crops().keys())
    vlm = vlm_inspect(image_path, crop_keys)
    res = VisionResult("ok", quality=q.__dict__)
    if vlm:
        res.symptoms_seen, res.description = vlm.get("symptoms", []), vlm.get("description")

    try:
        if zs is not None:
            if plant_probability(zs, img) < s.plant_threshold:
                return VisionResult("not_plant", quality=q.__dict__, description=res.description)
            top = classify_crop(zs, img)
            res.crop_top = top[:3]
            (c1, p1), (_, p2) = top[0], top[1]
            # several crops: confident, different answers on image quarters
            tile_tops = [classify_crop(zs, t)[0] for t in tiles(img)]
            strong = {c for c, p in tile_tops if p >= 0.6 and c != "other"}
            if len(strong) >= 2:
                res.action = "multiple_plants"
                res.crop_top = sorted(((c, p) for c, p in tile_tops if c in strong), key=lambda x: -x[1])
                res.crop_top = list({c: (c, p) for c, p in res.crop_top}.values())
                return res
            confident = p1 >= s.crop_min_conf and (p1 - p2) >= s.crop_min_margin and c1 != "other"
            if crop_hint and crop_hint in crop_keys:
                if confident and c1 != crop_hint and not hint_confirmed:
                    res.action, res.crop = "confirm_crop", c1  # farmer and model disagree: ask
                    res.crop_display = pct(p1)
                    return res
                if confident and c1 == crop_hint:  # photo agrees with what the farmer said
                    res.crop, res.crop_source, res.crop_display = crop_hint, "vision", pct(p1)
                else:
                    res.crop, res.crop_source = crop_hint, "farmer"
            elif confident:
                res.crop, res.crop_source, res.crop_display = c1, "vision", pct(p1)
            else:
                res.action = "ask_crop"
                return res
        else:
            if vlm and vlm.get("is_plant") is False:
                return VisionResult("not_plant", quality=q.__dict__, description=res.description)
            if vlm and vlm.get("several_crops"):
                res.action = "multiple_plants"
                return res
            if crop_hint and crop_hint in crop_keys:
                res.crop, res.crop_source = crop_hint, "farmer"
            elif vlm and vlm.get("crop") in crop_keys:
                res.action, res.crop, res.crop_source = "confirm_crop", vlm["crop"], "vlm"  # never trusted alone
                return res
            else:
                res.action = "ask_crop"
                return res

        head = get_head(res.crop)
        if head is not None:
            res.disease_top = head.predict(img)[:3]
            res.head_version = head.version
    except ValueError as e:  # non-finite numbers anywhere -> never shown
        log.error("vision numeric failure: %s", e)
        return VisionResult("error", reason="numeric")
    return res
