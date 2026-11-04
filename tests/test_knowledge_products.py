import csv

from agri import db, knowledge, llm, products
from tests.conftest import TMP, make_image

HEADER = products.REQUIRED[:1] + ["aliases"] + [c for c in ["category", "composition", "crop", "problem", "growth_stage", "method",
          "dosage", "frequency", "precautions", "compatibility", "source_doc", "source_ref", "source_quote", "verified_by", "verified_on"]]

# Clearly fictional test product. Real Vishakan products are loaded only from agronomist-verified CSVs.
ROWS = [
    dict(product_name="TEST-BIOFUNGICIDE-A", aliases="", category="bio-fungicide", composition="test", crop="chilli",
         problem="powdery_mildew", growth_stage="vegetative", method="foliar spray", dosage="5 ml per litre of water",
         frequency="every 10 days", precautions="spray in the evening", compatibility="", source_doc="Test brochure",
         source_ref="p.2", source_quote="5 ml per litre", verified_by="Test Agronomist", verified_on="2026-10-30"),
    dict(product_name="TEST-UNSOURCED", aliases="", category="x", composition="", crop="chilli", problem="anthracnose",
         growth_stage="", method="spray", dosage="2 g/l", frequency="", precautions="", compatibility="", source_doc="",
         source_ref="", source_quote="", verified_by="", verified_on=""),
    dict(product_name="TEST-WRONG-CROP-LABEL", aliases="", category="x", composition="", crop="chilli", problem="early_blight",
         growth_stage="", method="spray", dosage="1 g/l", frequency="", precautions="", compatibility="", source_doc="d",
         source_ref="p1", source_quote="q", verified_by="a", verified_on="2026-10-30"),
]


def _load():
    p = TMP / "products.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(ROWS)
    return products.load_products_csv(str(p))


def test_only_verified_sourced_crop_correct_rows_load():
    out = _load()
    assert out["loaded"] == 1
    assert any("missing" in e for e in out["errors"])
    assert any("early_blight" in e and "not listed for chilli" in e for e in out["errors"])


def test_product_question_lists_verified_product_with_exact_dosage_and_source(chat):
    _load()
    r = chat.send("Which Vishakan product is suitable for chilli plants?")
    assert "TEST-BIOFUNGICIDE-A" in r["text"] and "5 ml per litre of water" in r["text"]
    assert "Test brochure, p.2" in r["text"] and "dealer" in r["text"]
    assert "TEST-UNSOURCED" not in r["text"] and "TEST-WRONG" not in r["text"]


def test_no_product_for_crop_is_said_honestly(chat):
    _load()
    r = chat.send("Which Vishakan product is good for banana?")
    assert "no verified Vishakan product for Banana" in r["text"]


def test_diagnosis_recommends_only_for_matching_problem(chat, zs):
    _load()
    r = chat.send("chilli leaves have white powder", image=make_image("pm.jpg"))
    assert "Powdery mildew" in r["text"] and "TEST-BIOFUNGICIDE-A" in r["text"]
    r = chat.send("/new")
    r = chat.send("chilli fruits rotting and spots", image=make_image("an.jpg"))
    assert "Anthracnose" in r["text"] and "TEST-BIOFUNGICIDE-A" not in r["text"]
    assert "do not list a verified product" in r["text"]


HTML = """<html><head><title>Bio Products | Test Company</title></head><body><article>
<h1>Bio fungicide for vegetables</h1>
<p>Our Trichoderma based bio fungicide protects chilli and brinjal nurseries from damping off and root rot.
Mix 10 grams per kg of seed before sowing. Store in a cool dry place away from sunlight.</p>
<p>For chilli powdery mildew, consult the technical brochure and your field officer.</p>
</article></body></html>"""

TOMATO_HTML = """<html><head><title>Tomato guide</title></head><body><article><p>Tomato early blight management:
remove infected lower leaves of tomato and keep tomato plants dry. This advice is only for tomato crops in the field.</p>
</article></body></html>"""


def _pdf(path, text):
    import pymupdf as fitz

    d = fitz.open()
    pg = d.new_page()
    pg.insert_text((72, 72), text, fontsize=11)
    d.save(path)


def test_ingestion_versioning_and_crop_filter():
    assert knowledge.ingest_html("https://example.test/bio", HTML) == "new"
    assert knowledge.ingest_html("https://example.test/bio", HTML) == "unchanged"
    assert knowledge.ingest_html("https://example.test/bio", HTML.replace("10 grams", "12 grams")) == "updated"
    assert db.fetchone("SELECT count(*) AS n FROM documents WHERE status='superseded'")["n"] == 1
    knowledge.ingest_html("https://example.test/tomato", TOMATO_HTML)
    pdf = str(TMP / "brochure.pdf")
    _pdf(pdf, "Seed treatment for chilli: Trichoderma bio fungicide reduces damping off in chilli nursery beds.")
    assert knowledge.ingest_pdf(pdf) == "new"

    hits = knowledge.retrieve("chilli damping off seed treatment", crop="chilli")
    assert hits and all("tomato" not in h.content.lower() for h in hits)
    assert any("12 grams" in h.content for h in hits) and not any("10 grams" in h.content for h in hits)
    assert any(h.ref.endswith("p.1") for h in hits)


def test_knowledge_answer_without_llm_quotes_sources(chat):
    knowledge.ingest_html("https://example.test/bio", HTML)
    r = chat.send("How do I protect chilli nursery from damping off?")
    assert "From Vishakan Biotech documents" in r["text"] and "10 grams per kg" in r["text"]
    assert r["sources"] and r["sources"][0]["ref"] == "https://example.test/bio"


class FakeLLM:
    def __init__(self, answer):
        self.answer = answer

    def generate(self, system, user, images=None, json_mode=False):
        return None if json_mode else self.answer


def test_grounded_llm_answer_and_number_validator(chat):
    knowledge.ingest_html("https://example.test/bio", HTML)
    llm.set_llm(FakeLLM("Treat the seed with the Trichoderma bio fungicide at 10 grams per kg before sowing [1]."))
    r = chat.send("chilli seed treatment for damping off?")
    assert r["text"].startswith("Treat the seed") and "Source" in r["text"]

    llm.set_llm(FakeLLM("Use 25 ml per litre every 3 days [1]."))  # invented numbers -> rejected
    r = chat.send("chilli seed treatment for damping off?")
    assert "25 ml" not in r["text"] and "From Vishakan Biotech documents" in r["text"]


def test_unanswerable_question_refuses(chat):
    knowledge.ingest_html("https://example.test/bio", HTML)
    r = chat.send("What is the export price of cardamom in Dubai?")
    assert "could not find this in Vishakan Biotech's documents" in r["text"]
