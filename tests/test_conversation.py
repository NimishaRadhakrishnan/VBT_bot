import re

from agri import db
from tests.conftest import make_head, make_image, tomato_names

TAMIL = re.compile(r"[஀-௿]")


def _fake_ogg(name):
    from tests.conftest import TMP

    p = TMP / name
    p.write_bytes(b"OggS fake")
    return str(p)


def _no_nan(reply):
    assert "nan" not in reply["text"].lower().replace("nandri", "").replace("thanga", "")


def test_requirement_conversation_english(chat, zs):
    """Farmer: yellow leaves -> bot asks leaf age -> older -> bot asks photo -> photo -> diagnosis in context."""
    r = chat.send("My chilli plants have yellow leaves.")
    assert r["action"] == "ask" and "older" in r["text"].lower()
    assert {b["payload"] for b in r["buttons"]} == {"age:older", "age:newer"}

    r = chat.send("Older leaves")
    assert r["action"] == "ask" and "photo" in r["text"].lower()

    r = chat.send(image=make_image("chilli1.jpg"))
    text = r["text"]
    assert "Chilli" in text and re.search(r"about \d+%", text)          # crop from photo, calibrated display
    assert "Nitrogen deficiency" in text                      # older-leaf yellowing evidence was remembered
    assert "Iron / zinc" not in text                          # newer-leaf problems ruled out
    assert "not a confirmed diagnosis" in text               # no disease head yet -> no disease %
    assert "Tomato" not in text and not any(n in text for n in tomato_names())
    assert "do not list a verified product" in text         # empty catalogue -> honest
    _no_nan(r)
    case = db.fetchone("SELECT state FROM cases")
    assert case["state"]["crop"] == "chilli" and case["state"]["leaf_age"] == "older"


def test_same_conversation_in_tamil_and_tanglish(client, zs):
    from tests.conftest import Chat

    ta = Chat(client, "farmer-ta")
    r = ta.send("என் மிளகாய் செடியில் இலைகள் மஞ்சளாக இருக்கு")
    assert r["style"] == "ta" and TAMIL.search(r["text"]) and "age:older" in [b["payload"] for b in r["buttons"]]
    r = ta.send(button="age:older")
    assert r["style"] == "ta" and "புகைப்படம்" in r["text"]
    r = ta.send(image=make_image("chilli-ta.jpg"))
    assert "மிளகாய்" in r["text"] and "தழைச்சத்து குறைபாடு" in r["text"]
    assert "தக்காளி" not in r["text"]

    tl = Chat(client, "farmer-tl")
    r = tl.send("En milagai chediyoda leaves curl aaguthu. Enna disease?")
    assert r["style"] == "ta-Latn" and "photo" in r["text"].lower()
    r = tl.send(image=make_image("chilli-tl.jpg"))
    assert r["style"] == "ta-Latn" and "Milagai" in r["text"]
    assert "Ilai surul vairas noi" in r["text"]  # chilli leaf curl virus, Tanglish label
    assert "Vellai ee" not in r["text"]


def test_trained_head_shows_calibrated_confidence_and_only_chilli_labels(chat, zs):
    make_head("chilli", ["leaf_curl_virus", "thrips_mites", "healthy"], [3.0, 0.5, 0.2])
    r = chat.send("milagai ilai surul", image=make_image("chilli-head.jpg"))
    assert "Likely problem" in r["text"] or "Perumbaalum" in r["text"]
    assert "85%" in r["text"] or "90%" in r["text"]
    assert not any(n in r["text"] for n in tomato_names())
    assert "cannot be cured" in r["text"] or "kuna" in r["text"].lower() or "⚠️" in r["text"]
    _no_nan(r)


def test_head_with_another_crops_labels_is_refused(chat, zs):
    make_head("chilli", ["early_blight", "late_blight", "healthy"], [3.0, 0.0, 0.0])  # tomato labels!
    r = chat.send("chilli leaves have spots", image=make_image("chilli-bad-head.jpg"))
    assert "blight" not in r["text"].lower()
    assert "not a confirmed diagnosis" in r["text"]  # fell back to chilli-only symptom triage


def test_nan_from_model_is_never_displayed(chat, zs):
    make_head("chilli", ["leaf_curl_virus", "healthy"], [float("nan"), 0.0])
    r = chat.send(image=make_image("chilli-nan.jpg"))
    assert r["action"] == "error"
    _no_nan(r)


def test_farmer_says_chilli_but_photo_confidently_tomato_asks_to_confirm(chat, zs):
    zs.scenario.update(crop="tomato", p=0.9)
    r = chat.send("my chilli plant has spots", image=make_image("conflict.jpg"))
    assert r["action"] == "ask" and "Tomato" in r["text"] and "correct" in r["text"]
    assert [b["payload"] for b in r["buttons"]] == ["crop:tomato", "crop:list"]
    r = chat.send(button="crop:list")
    r = chat.send(button="crop:chilli")  # farmer insists: re-runs the stored photo as chilli
    assert "Chilli" in r["text"] and "as you told me" in r["text"]
    assert not any(n in r["text"] for n in tomato_names())


def test_unclear_crop_asks_with_top_choices_then_resumes(chat, zs):
    zs.scenario.update(crop="chilli", p=0.45)
    r = chat.send(image=make_image("unsure.jpg"))
    assert r["action"] == "ask" and "Which crop" in r["text"]
    assert r["buttons"][0]["payload"] == "crop:chilli" and "%" in r["buttons"][0]["label"]
    r = chat.send(button="crop:chilli")
    assert "Chilli" in r["text"]


def test_image_gates(chat, zs):
    assert "blurry" in chat.send(image=make_image("blur.jpg", "blurry"))["text"]
    assert "too dark" in chat.send(image=make_image("dark.jpg", "dark"))["text"]
    assert "too small" in chat.send(image=make_image("small.jpg", size=(200, 150)))["text"]
    zs.scenario.update(plant=False)
    assert "could not find a plant" in chat.send(image=make_image("selfie.jpg"))["text"]


def test_multiple_plants(chat, zs):
    zs.scenario.update(tiles=["banana", "banana", "coconut", "coconut"], crop="banana", p=0.7)
    r = chat.send(image=make_image("intercrop.jpg"))
    assert "more than one" in r["text"]
    assert {b["payload"] for b in r["buttons"]} >= {"crop:banana", "crop:coconut"}


def test_new_crop_after_diagnosis_starts_new_case(chat, zs):
    chat.send("chilli leaves curling")
    chat.send(image=make_image("c1.jpg"))
    chat.send("now my banana leaves are drying")
    rows = db.fetchall("SELECT crop, closed_at FROM cases ORDER BY opened_at")
    assert rows[0]["crop"] == "chilli" and rows[0]["closed_at"] is not None
    assert rows[1]["crop"] == "banana" and rows[1]["closed_at"] is None


def test_escalation_and_agronomist_reply(chat, client):
    r = chat.send("chilli leaves curling")
    r = chat.send(button="esc")
    assert r["escalate"] and "#" in r["text"]
    code = re.search(r"Case #([0-9A-F]{6})", r["escalation_summary"]).group(1)
    assert "chilli" in r["escalation_summary"]
    out = client.post(f"/v1/escalations/{code}/reply", json={"text": "Spray neem oil after checking for whitefly."}).json()
    assert out["user_ref"] == "farmer-1" and "agronomist" in out["text"].lower()
    assert db.fetchone("SELECT status FROM escalations")["status"] == "answered"


def test_idempotent_retries_and_auth(client):
    data = {"user_ref": "u9", "text": "hello", "idempotency_key": "tg:1:42"}
    a = client.post("/v1/chat/messages", data=data).json()
    b = client.post("/v1/chat/messages", data=data).json()
    assert a == b
    assert db.fetchone("SELECT count(*) AS n FROM messages WHERE direction='in'")["n"] == 1
    client.headers.pop("X-API-Key")
    assert client.post("/v1/chat/messages", data=data).status_code == 401


def test_voice_message_in_tamil(chat):
    from agri import language

    class FakeSTT(language.STT):
        def transcribe(self, path):
            return "என் மிளகாய் செடியில் இலை சுருண்டு போகுது", "ta-IN"

    language.set_stt(FakeSTT())
    r = chat.send(voice=_fake_ogg("fake-voice.ogg"))  # content irrelevant to the fake STT
    assert r["style"] == "ta" and "நான் கேட்டது" in r["text"] and "புகைப்படம்" in r["text"]


def test_voice_without_stt_asks_to_type(chat):
    r = chat.send(voice=_fake_ogg("v.ogg"))
    assert "voice message" in r["text"]
