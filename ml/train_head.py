"""Train ONE crop-specific disease head, calibrate it, export ONNX for the bot.

  pip install -r requirements-ml.txt
  python ml/train_head.py --crop paddy --data ~/data/heads/paddy --epochs 25

Expects <data>/{train,val,test}/<taxonomy_key>/*.jpg (made by prepare_dataset.py).
Writes models/heads/<crop>/{model.onnx, labels.json, report.json}. The bot picks it up on restart.
Run on a GPU (Colab/Kaggle); CPU works but is slow.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import timm
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, WeightedRandomSampler
from torchvision import datasets, transforms

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agri.taxonomy import problems  # noqa: E402

MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]


def loaders(data: Path, size: int, bs: int):
    train_tf = transforms.Compose([
        transforms.RandomResizedCrop(size, scale=(0.5, 1.0)), transforms.RandomHorizontalFlip(), transforms.RandomVerticalFlip(),
        transforms.RandomRotation(20), transforms.ColorJitter(0.25, 0.25, 0.1, 0.02),  # mild: colour carries the diagnosis
        transforms.RandomApply([transforms.GaussianBlur(5)], p=0.2), transforms.ToTensor(), transforms.Normalize(MEAN, STD)])
    eval_tf = transforms.Compose([transforms.Resize(int(size * 1.14)), transforms.CenterCrop(size), transforms.ToTensor(),
                                  transforms.Normalize(MEAN, STD)])
    tr = datasets.ImageFolder(data / "train", train_tf)
    va = datasets.ImageFolder(data / "val", eval_tf)
    te = datasets.ImageFolder(data / "test", eval_tf) if (data / "test").exists() else None
    for d in (va, te):
        if d is not None and d.classes != tr.classes:
            raise SystemExit(f"class folders differ between splits: {d.classes} vs {tr.classes}")
    counts = np.bincount(tr.targets, minlength=len(tr.classes))
    w = (1.0 / np.maximum(counts, 1))[tr.targets]
    sampler = WeightedRandomSampler(torch.tensor(w, dtype=torch.double), len(tr), replacement=True)
    mk = lambda d, **k: DataLoader(d, batch_size=bs, num_workers=4, **k)  # noqa: E731
    return tr.classes, mk(tr, sampler=sampler), mk(va), (mk(te) if te else None)


@torch.no_grad()
def logits_of(model, dl, dev):
    model.eval()
    L, Y = [], []
    for x, y in dl:
        L.append(model(x.to(dev)).float().cpu())
        Y.append(y)
    return torch.cat(L), torch.cat(Y)


def fit_temperature(logits, y) -> float:
    t = torch.ones(1, requires_grad=True)
    opt = torch.optim.LBFGS([t], lr=0.05, max_iter=200)
    nll = nn.CrossEntropyLoss()

    def step():
        opt.zero_grad()
        loss = nll(logits / t.clamp(min=0.05), y)
        loss.backward()
        return loss

    opt.step(step)
    return float(t.clamp(min=0.05))


def metrics(logits, y, T, classes):
    p = torch.softmax(logits / T, 1).numpy()
    pred, yy = p.argmax(1), y.numpy()
    per = {}
    for i, c in enumerate(classes):
        tp = int(((pred == i) & (yy == i)).sum()); fp = int(((pred == i) & (yy != i)).sum()); fn = int(((pred != i) & (yy == i)).sum())
        prec, rec = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        per[c] = {"precision": round(prec, 3), "recall": round(rec, 3), "f1": round(2 * prec * rec / max(prec + rec, 1e-9), 3),
                  "n": int((yy == i).sum())}
    conf = p.max(1)
    bins, ece = np.linspace(0, 1, 11), 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            ece += m.mean() * abs((pred[m] == yy[m]).mean() - conf[m].mean())
    return {"accuracy": round(float((pred == yy).mean()), 3), "macro_f1": round(float(np.mean([v["f1"] for v in per.values()])), 3),
            "ece": round(float(ece), 4), "per_class": per}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--arch", default="tf_efficientnetv2_s.in21k_ft_in1k")
    ap.add_argument("--size", type=int, default=384)
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--bs", type=int, default=32)
    ap.add_argument("--lr", type=float, default=3e-4)
    a = ap.parse_args()

    data = Path(a.data)
    classes, tr, va, te = loaders(data, a.size, a.bs)
    allowed = set(problems(a.crop)) | {"healthy", "other_or_unclear"}
    bad = [c for c in classes if c not in allowed]
    if bad:
        raise SystemExit(f"folders not in {a.crop} taxonomy: {bad}")
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = timm.create_model(a.arch, pretrained=True, num_classes=len(classes)).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=0.05)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.epochs * len(tr), pct_start=0.1)
    loss_fn = nn.CrossEntropyLoss(label_smoothing=0.1)
    scaler = torch.amp.GradScaler(enabled=dev == "cuda")
    best, out = -1.0, ROOT / "models" / "heads" / a.crop
    out.mkdir(parents=True, exist_ok=True)
    for ep in range(a.epochs):
        model.train()
        for x, y in tr:
            opt.zero_grad()
            with torch.autocast(dev, enabled=dev == "cuda"):
                loss = loss_fn(model(x.to(dev)), y.to(dev))
            scaler.scale(loss).backward(); scaler.step(opt); scaler.update(); sched.step()
        lv, yv = logits_of(model, va, dev)
        m = metrics(lv, yv, 1.0, classes)
        print(f"epoch {ep + 1}: val acc {m['accuracy']} macro-F1 {m['macro_f1']}")
        if m["macro_f1"] > best:
            best = m["macro_f1"]
            torch.save(model.state_dict(), out / "best.pt")

    model.load_state_dict(torch.load(out / "best.pt", map_location=dev))
    lv, yv = logits_of(model, va, dev)
    T = fit_temperature(lv, yv)
    report = {"val": metrics(lv, yv, T, classes), "temperature": T}
    if te is not None:
        lt, yt = logits_of(model, te, dev)
        report["test"] = metrics(lt, yt, T, classes)
    model.eval().cpu()
    torch.onnx.export(model, torch.randn(1, 3, a.size, a.size), out / "model.onnx", input_names=["input"],
                      output_names=["logits"], dynamic_axes={"input": {0: "n"}}, opset_version=17)
    version = f"{a.crop}-{a.arch.split('.')[0]}-{date.today().isoformat()}"
    (out / "labels.json").write_text(json.dumps({"labels": classes, "temperature": T, "input_size": a.size, "mean": MEAN,
                                                 "std": STD, "version": version}, indent=2))
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "val"}, indent=2)[:2000])
    print(f"saved {out}. Promote only if the FIELD test macro-F1 and ECE meet the targets in the blueprint.")


if __name__ == "__main__":
    main()
