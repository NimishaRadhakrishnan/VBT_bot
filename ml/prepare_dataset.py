"""Map a public dataset's class folders onto ONE crop's taxonomy keys and make a
train/val/test split that never puts near-duplicate images in different splits.

Example (Paddy Doctor, Kaggle "paddy-disease-classification" train_images/):
  python ml/prepare_dataset.py --crop paddy --src ~/data/paddy/train_images --dst ~/data/heads/paddy --map paddy_doctor

Your own field photos: put them in --src/<taxonomy_key>/ and use --map none.
Hold out real field photos from other districts as the test set with --test-src.
"""
from __future__ import annotations

import argparse
import hashlib
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agri.taxonomy import problems  # noqa: E402

MAPS = {
    "paddy_doctor": {
        "bacterial_leaf_blight": "bacterial_leaf_blight", "bacterial_leaf_streak": "bacterial_leaf_streak",
        "bacterial_panicle_blight": "bacterial_panicle_blight", "blast": "blast", "brown_spot": "brown_spot",
        "dead_heart": "stem_borer", "black_stem_borer": "stem_borer", "white_stem_borer": "stem_borer",
        "yellow_stem_borer": "stem_borer", "downy_mildew": "downy_mildew", "hispa": "hispa", "tungro": "tungro",
        "leaf_roller": "leaf_folder", "normal": "healthy",
    },
    "chilli_mendeley": {  # e.g. data.mendeley.com/datasets/tm3v4zmh7c
        "bacterial": "bacterial_leaf_spot", "bacterial_spot": "bacterial_leaf_spot", "cercospora": "cercospora_leaf_spot",
        "cercospora_leaf_spot": "cercospora_leaf_spot", "curl_virus": "leaf_curl_virus", "healthy_leaf": "healthy",
        "healthy": "healthy", "powdery_mildew": "powdery_mildew",
        # "nutrient_deficiency" in public sets is not specific enough for our N / Mg / Fe-Zn keys -> left out on purpose
    },
    "none": {},
}


def phash(p: Path) -> str:
    from PIL import Image

    img = Image.open(p).convert("L").resize((9, 8))
    px = list(img.getdata())
    bits = "".join("1" if px[r * 9 + c] > px[r * 9 + c + 1] else "0" for r in range(8) for c in range(8))
    return hex(int(bits, 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop", required=True)
    ap.add_argument("--src", required=True)
    ap.add_argument("--dst", required=True)
    ap.add_argument("--map", default="none", choices=list(MAPS))
    ap.add_argument("--test-src", help="separate field test folder (preferred over a random test split)")
    ap.add_argument("--val", type=float, default=0.15)
    ap.add_argument("--test", type=float, default=0.15)
    a = ap.parse_args()

    allowed = set(problems(a.crop)) | {"healthy", "other_or_unclear"}
    mapping = MAPS[a.map]
    random.seed(13)
    groups: dict[tuple[str, str], list[Path]] = {}
    for d in sorted(Path(a.src).iterdir()):
        if not d.is_dir():
            continue
        key = mapping.get(d.name.lower(), d.name.lower()) if mapping else d.name.lower()
        if key not in allowed:
            print(f"skip folder '{d.name}': not a {a.crop} class in taxonomy.yaml")
            continue
        for f in d.iterdir():
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
                try:
                    groups.setdefault((key, phash(f)), []).append(f)
                except Exception:
                    print("unreadable", f)
    by_class: dict[str, list[list[Path]]] = {}
    for (key, _), files in groups.items():
        by_class.setdefault(key, []).append(files)
    dst = Path(a.dst)
    for key, gl in by_class.items():
        random.shuffle(gl)
        n = len(gl)
        nt = 0 if a.test_src else int(n * a.test)
        nv = int(n * a.val)
        for i, g in enumerate(gl):
            split = "test" if i < nt else "val" if i < nt + nv else "train"
            for f in g:  # near-duplicates stay together
                out = dst / split / key / f"{hashlib.md5(str(f).encode()).hexdigest()[:12]}{f.suffix.lower()}"
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out)
        print(f"{key}: {sum(len(g) for g in gl)} images in {n} duplicate-groups")
    if a.test_src:
        for d in Path(a.test_src).iterdir():
            if d.is_dir() and d.name in allowed:
                for f in d.iterdir():
                    out = dst / "test" / d.name / f.name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, out)


if __name__ == "__main__":
    main()
