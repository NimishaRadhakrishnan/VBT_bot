# Vishakan Biotech AI Agricultural Assistant — Telegram MVP

A Telegram bot backed by a channel-independent FastAPI "brain". Farmers send text, photos or voice
notes in Tamil, English or Tanglish; the bot identifies the crop first, diagnoses only with that crop's
own problem list, answers from Vishakan documents with sources, and recommends only
agronomist-verified Vishakan products.

```
Telegram ──▶ agri/telegram_bot.py (adapter only) ──HTTP──▶ agri/api.py  /v1/chat/messages
                                                               │
                                                   agri/orchestrator.py  (case memory, slot questions, escalation)
                         ┌───────────────┬─────────────────────┼──────────────────┬──────────────────┐
                 language.py        vision.py + triage.py   knowledge.py        products.py         llm.py
             style ID, glossary,   quality gate → plant    crawl, PDF, OCR,    verified product    Gemini / Claude /
             Sarvam STT/TTS        gate → crop ID →        versioning, hybrid  rows only; dosage   none (rules +
                                   crop-specific head      pgvector + BM25     shown verbatim      templates)
                                                               │
                                                PostgreSQL + pgvector (schema.sql)
```

## What works today (and how it was tested)

| Requirement | Where | Tested |
| --- | --- | --- |
| Crop identified before diagnosis; never tomato labels on chilli | `vision.analyse`, `triage.py`, `taxonomy.yaml` (problems are listed per crop) | ✔ chilli photo never shows tomato names; a head shipped with tomato labels for chilli is refused |
| Farmer and photo disagree → ask, don't guess | `vision.analyse` (`confirm_crop`) | ✔ |
| Blurry / dark / tiny / not-a-plant / several plants | `check_quality`, plant gate, 2×2 tile check | ✔ |
| Real, calibrated confidence; never NaN | `softmax` finite check, `pct()`, `Probability` validator, temperature from training | ✔ a NaN-producing model gives a polite error, no number |
| Low confidence → ask for crop / leaf age / another photo | `triage.next_question`, crop buttons | ✔ |
| Conversation memory (yellow leaves → older → photo → diagnosis) | `cases.state` | ✔ English, Tamil, Tanglish |
| Tamil, English, Tanglish text; language kept without selecting it | `language.detect_style`, `messages.py` | ✔ the three example sentences from the brief |
| Tamil voice notes | Sarvam Saaras v3 (`STT_PROVIDER=sarvam`) | ✔ with a stand-in STT; real API needs your key |
| RAG over website + brochures, with sources, OCR for scans, versioning | `knowledge.py` | ✔ HTML, text PDF, scanned PDF (OCR), re-ingest/supersede, crop filter |
| No invented numbers in answers | `unsupported_numbers` validator | ✔ an LLM answer with made-up dosage is rejected |
| Products only from verified, sourced rows; "no product" said honestly | `products.py`, `data/products/verified_products.csv` | ✔ unsourced or wrong-crop rows are rejected at load |
| Human agronomist escalation + reply relayed to farmer | `/agronomist` or button → agronomist Telegram group | ✔ adapter tested against a live API server with a fake Telegram |
| Backend reusable by website / field-force app | `/v1/*` REST API | ✔ |

**Not yet done (needs data, not code):** trained disease heads. Until `models/heads/<crop>/model.onnx`
exists, the bot shows *possible causes from symptoms* without percentages and says so. Train paddy first
(Paddy Doctor is Tamil Nadu field data), then chilli and banana — see "Train a disease head".

**Product catalogue starts empty on purpose.** The bot will say "no verified product" until an agronomist
fills `data/products/verified_products.csv`. It never takes products or dosage from the LLM.

## Run it on your laptop (about 20 minutes)

1. **Create the bot:** in Telegram open **@BotFather** → `/newbot` → copy the token.
2. **Get keys (optional but recommended):** Gemini API key (Google AI Studio) for understanding and answers;
   Sarvam API key (dashboard.sarvam.ai) for Tamil voice notes. Without them the bot still works with rules
   and templates, and asks voice users to type.
3. **Configure:**
   ```bash
   cp .env.example .env     # paste TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, SARVAM_API_KEY, a random API_KEY
   ```
4. **Start everything with Docker** (Postgres + pgvector, API, bot):
   ```bash
   docker compose up --build
   ```
   The first photo downloads BioCLIP 2 (~1.7 GB) and BGE-M3 (~2.3 GB) once into a cache volume.

   *Without Docker:* install PostgreSQL 16 + pgvector, then
   ```bash
   pip install -r requirements.txt -r requirements-ml.txt
   python -m agri.cli init-db
   uvicorn agri.api:app --port 8000          # terminal 1
   python -m agri.telegram_bot               # terminal 2 (polling: no public URL needed)
   ```
   On a low-RAM laptop set `CROP_BACKEND=vlm` and `EMBEDDING_PROVIDER=hash` to skip the big models while
   you demo (crop then always needs the farmer's confirmation, retrieval becomes keyword-only).
5. **Load company knowledge:**
   ```bash
   python -m agri.cli crawl https://vishakanbiotech.com/ --max-pages 300
   python -m agri.cli ingest-pdf "brochures/*.pdf" --type brochure
   python -m agri.cli load-products data/products/verified_products.csv   # prints every rejected row and why
   ```
6. **Agronomist group:** create a Telegram group, add the bot, send a message, read the group id
   (starts with `-100`) from `https://api.telegram.org/bot<TOKEN>/getUpdates`, put it in `AGRONOMIST_CHAT_ID`.
   Agronomists answer a case by **replying** to the case message; the bot forwards it to the farmer.

Try without Telegram: `python -m agri.cli ask "En milagai chediyoda leaves curl aaguthu" --user demo`
and `python -m agri.cli ask --image leaf.jpg --user demo`.

## Filling `verified_products.csv`

One row per product × crop × problem × method. Rows load only if `source_doc`, `source_ref`, `source_quote`,
`verified_by` and `verified_on` are filled and the crop/problem exist in `data/taxonomy.yaml`.
Use `problem = general_crop_health` for general-purpose products (bio-fertilisers, bio-stimulants).
`dosage` is shown to farmers exactly as written — copy it from the brochure.

## Train a disease head

```bash
pip install -r requirements-ml.txt
# Paddy Doctor: https://www.kaggle.com/c/paddy-disease-classification  (train_images/)
python ml/prepare_dataset.py --crop paddy --src ~/data/paddy/train_images --dst ~/data/heads/paddy --map paddy_doctor
python ml/train_head.py --crop paddy --data ~/data/heads/paddy --epochs 25      # GPU: Colab/Kaggle
```
This writes `models/heads/paddy/{model.onnx, labels.json, report.json}` with a fitted temperature.
Restart the API and paddy photos get calibrated percentages. Promote a head only after testing on
**Vishakan field photos** (`--test-src`), never on PlantVillage-style test sets.
Check crop ID on a labelled field folder: `python -m agri.cli eval-crop path/to/field_test`.

## Editing what the bot knows and says

- `data/taxonomy.yaml` — crops, each crop's own problems, Tamil/Tanglish names, symptom links. **Agronomist must review.**
- `data/glossary.yaml` — Tamil/Tanglish spellings → canonical terms. Add new farmer spellings here.
- `agri/messages.py` — every reply sentence in Tamil, English and Tanglish.
- Thresholds (`BLUR_THRESHOLD`, `CROP_MIN_CONF`, …) in `.env`; tune them on real photos.

## Tests

```bash
TEST_DATABASE_URL=postgresql://agri:agri@localhost:5432/agri_test pytest -q
```
26 tests run against real PostgreSQL + pgvector. Downloadable models and paid APIs are replaced by small
stand-ins (a scripted crop model, a tiny real ONNX head, fake LLM/STT), so tests run offline.

## Before showing farmers

1. Agronomist reviews `taxonomy.yaml`, `messages.py` (Tamil wording) and the product CSV.
2. Run `eval-crop` on ≥100 field photos per crop; tune `CROP_MIN_CONF` and `BLUR_THRESHOLD`.
3. Pilot with 20–50 farmers through field officers; review every case in the agronomist group.
