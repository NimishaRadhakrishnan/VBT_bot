"""Admin commands.

  python -m agri.cli init-db
  python -m agri.cli crawl https://vishakanbiotech.com/ --max-pages 300
  python -m agri.cli ingest-pdf brochures/*.pdf --type brochure
  python -m agri.cli load-products data/products/verified_products.csv
  python -m agri.cli ask "Which Vishakan product is suitable for chilli?" --user test1
  python -m agri.cli eval-crop path/to/field_test   (folders named by crop key)
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
from pathlib import Path


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="agri")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    c = sub.add_parser("crawl"); c.add_argument("url"); c.add_argument("--max-pages", type=int, default=200)
    p = sub.add_parser("ingest-pdf"); p.add_argument("paths", nargs="+"); p.add_argument("--type", default="brochure")
    h = sub.add_parser("ingest-html"); h.add_argument("path"); h.add_argument("--url", required=True)
    lp = sub.add_parser("load-products"); lp.add_argument("csv")
    a = sub.add_parser("ask"); a.add_argument("text", nargs="?"); a.add_argument("--image"); a.add_argument("--voice")
    a.add_argument("--button"); a.add_argument("--user", default="cli-user")
    e = sub.add_parser("eval-crop"); e.add_argument("folder")
    args = ap.parse_args()

    from . import db, knowledge, products

    if args.cmd == "init-db":
        db.init_db()
        print("database ready")
    elif args.cmd == "crawl":
        print(json.dumps(knowledge.crawl(args.url, args.max_pages), indent=2))
    elif args.cmd == "ingest-pdf":
        for pattern in args.paths:
            for f in glob.glob(pattern):
                print(f, knowledge.ingest_pdf(f, args.type))
    elif args.cmd == "ingest-html":
        print(knowledge.ingest_html(args.url, Path(args.path).read_text(encoding="utf-8")))
    elif args.cmd == "load-products":
        out = products.load_products_csv(args.csv)
        print(f"loaded {out['loaded']} rows")
        for err in out["errors"]:
            print("  REJECTED", err)
    elif args.cmd == "ask":
        from .contracts import InboundMessage, Media
        from .orchestrator import handle

        media = ([Media(kind="image", path=args.image)] if args.image else []) + \
                ([Media(kind="voice", path=args.voice)] if args.voice else [])
        r = handle(InboundMessage(channel="cli", user_ref=args.user, text=args.text, media=media, button=args.button))
        print(r.text)
        for b in r.buttons:
            print(f"  [{b.label}] -> {b.payload}")
    elif args.cmd == "eval-crop":
        from .vision import analyse

        total = correct = wrong_confident = abstained = 0
        for crop_dir in sorted(Path(args.folder).iterdir()):
            for img in crop_dir.glob("*.*"):
                r = analyse(str(img))
                total += 1
                if r.action != "ok":
                    abstained += 1
                elif r.crop == crop_dir.name:
                    correct += 1
                else:
                    wrong_confident += 1
                    print(f"WRONG {img}: predicted {r.crop}")
        answered = total - abstained
        print(f"images={total} answered={answered} accuracy_on_answered={correct / max(answered, 1):.3f} "
              f"wrong_confident_rate={wrong_confident / max(total, 1):.3f} abstained={abstained}")


if __name__ == "__main__":
    main()
