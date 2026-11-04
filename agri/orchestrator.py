"""Conversation orchestrator. One entry point: handle(InboundMessage) -> Reply.

Nodes: ingest -> load_case -> understand -> (diagnose | product | knowledge | escalate)
       -> compose -> validate -> persist. Channel-agnostic: no Telegram code here."""
from __future__ import annotations

import json
import logging
import secrets
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from . import db, knowledge, products, vision
from .config import get_settings
from .contracts import Button, InboundMessage, Reply, Source
from .language import detect_style, extract, get_stt
from .llm import get_llm, has_llm, parse_json
from .messages import sym, t
from .taxonomy import crop_name, crops, problem_name, problems
from .triage import triage

log = logging.getLogger(__name__)
_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)  # one message at a time per user


# ------------------------------------------------------------------ persistence
def _user(msg: InboundMessage) -> dict:
    return db.fetchone(
        "INSERT INTO users (channel, channel_user_id, name) VALUES (%s,%s,%s) "
        "ON CONFLICT (channel, channel_user_id) DO UPDATE SET name=COALESCE(EXCLUDED.name, users.name) RETURNING *",
        (msg.channel, msg.user_ref, msg.user_name))


def _open_case(user_id) -> dict:
    s = get_settings()
    c = db.fetchone("SELECT * FROM cases WHERE user_id=%s AND closed_at IS NULL ORDER BY opened_at DESC LIMIT 1", (user_id,))
    if c and c["updated_at"] < datetime.now(timezone.utc) - timedelta(days=s.case_idle_days):
        _close(c["id"])
        c = None
    if not c:
        c = db.fetchone("INSERT INTO cases (user_id, state) VALUES (%s, '{}') RETURNING *", (user_id,))
    c["state"] = c["state"] or {}
    return c


def _close(case_id) -> None:
    db.execute("UPDATE cases SET closed_at=now(), status='closed' WHERE id=%s", (case_id,))


def _save(case: dict) -> None:
    st = case["state"]
    db.execute("UPDATE cases SET state=%s, crop=%s, status=%s, updated_at=now() WHERE id=%s",
               (json.dumps(st, ensure_ascii=False), st.get("crop"), st.get("status", "gathering"), case["id"]))


def _log(case, user, direction, text=None, style=None, media=None, key=None, reply=None, transcript=None):
    db.execute(
        "INSERT INTO messages (case_id, user_id, direction, text, transcript, style, media, idempotency_key, reply) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (idempotency_key) DO NOTHING",
        (case["id"] if case else None, user["id"], direction, text, transcript, style, media or [], key,
         json.dumps(reply, ensure_ascii=False) if reply else None))


# ------------------------------------------------------------------ understanding
UNDERSTAND_SYSTEM = (
    "You extract structured facts from a farmer's message (Tamil, English or Tanglish) for an agricultural assistant. "
    "Do not answer the question. Return JSON only."
)


def understand(text: str, state: dict) -> dict:
    """Glossary rules first (always), LLM adds what rules miss (when configured)."""
    e = extract(text)
    out = {"crops": e.crops, "symptoms": e.symptoms, "leaf_age": e.leaf_age, "intents": e.intents, "question_en": None}
    if has_llm() and text and len(text) > 3:
        prompt = (
            f"Message: {text}\nKnown case context: crop={state.get('crop')}, symptoms={state.get('symptoms', [])}\n"
            "Return JSON with: crop (one of " + json.dumps(list(crops())) + " or null), "
            "symptoms (list from " + json.dumps(list(_symptom_keys())) + "), leaf_age (older|newer|null), "
            "intent (diagnose|product|knowledge|agronomist|greeting|other), question_en (the question in plain English)."
        )
        j = parse_json(get_llm().generate(UNDERSTAND_SYSTEM, prompt, json_mode=True)) or {}
        if j.get("crop") in crops() and not out["crops"]:
            out["crops"] = [j["crop"]]
        out["symptoms"] = sorted(set(out["symptoms"]) | {s for s in j.get("symptoms") or [] if s in _symptom_keys()})
        if not out["leaf_age"] and j.get("leaf_age") in ("older", "newer"):
            out["leaf_age"] = j["leaf_age"]
        intent = {"product": "product", "agronomist": "agronomist", "greeting": "greeting"}.get(j.get("intent"))
        if intent and intent not in out["intents"]:
            out["intents"].append(intent)
        if j.get("intent") == "knowledge":
            out["intents"].append("knowledge")
        out["question_en"] = j.get("question_en")
    return out


def _symptom_keys():
    from .taxonomy import symptom_keys

    return symptom_keys()


# ------------------------------------------------------------------ main entry
def handle(msg: InboundMessage) -> Reply:
    with _locks[f"{msg.channel}:{msg.user_ref}"]:
        try:
            return _handle(msg)
        except Exception:
            log.exception("orchestrator failure")
            return Reply(text=t("error", "en"), style="en", action="error")


def _handle(msg: InboundMessage) -> Reply:
    s = get_settings()
    if msg.idempotency_key:
        prev = db.fetchone("SELECT reply FROM messages WHERE idempotency_key=%s AND direction='out'", (f"out:{msg.idempotency_key}",))
        if prev and prev["reply"]:
            return Reply(**prev["reply"])
    user = _user(msg)
    recent = db.fetchone("SELECT count(*) AS n FROM messages WHERE user_id=%s AND direction='in' AND created_at > now() - interval '10 minutes'",
                         (user["id"],))
    style = user["preferred_style"] or "en"
    if recent["n"] >= s.rate_limit_per_10min:
        return Reply(text=t("rate_limited", style), style=style, action="error")

    case = _open_case(user["id"])
    st = case["state"]
    text = (msg.text or "").strip()
    transcript = None
    images = [m.path for m in msg.media if m.kind == "image"]
    voices = [m.path for m in msg.media if m.kind == "voice"]

    # ---- ingest: voice -> text
    if voices:
        transcript, _ = get_stt().transcribe(voices[0])
        if not transcript:
            r = Reply(text=t("voice_failed", style), style=style, action="ask", case_id=str(case["id"]))
            return _finish(msg, user, case, r, text, style, transcript)
        text = f"{text} {transcript}".strip()

    if text and not text.startswith("/"):
        style = detect_style(text, user["preferred_style"])
        db.execute("UPDATE users SET preferred_style=%s WHERE id=%s", (style, user["id"]))
    st["style"] = style

    reply = _route(msg, user, case, st, text, images, style)
    if transcript:
        reply.text = t("heard", style, t=transcript) + "\n\n" + reply.text
    return _finish(msg, user, case, reply, text, style, transcript)


def _finish(msg, user, case, reply: Reply, text, style, transcript) -> Reply:
    reply.case_id = reply.case_id or (str(case["id"]) if case else None)
    if case and not case.get("_closed"):
        _save(case)
    _log(case, user, "in", text=text, style=style, media=[m.path for m in msg.media], key=msg.idempotency_key, transcript=transcript)
    _log(case, user, "out", text=reply.text, style=reply.style, key=f"out:{msg.idempotency_key}" if msg.idempotency_key else None,
         reply=reply.model_dump())
    return reply


# ------------------------------------------------------------------ routing
def _agronomist_btn(style):
    return Button(label=t("btn_agronomist", style), payload="esc")


def _crop_buttons(style, only: list[str] | None = None, with_pct: dict | None = None) -> list[Button]:
    keys = only or list(crops())
    out = []
    for k in keys:
        lbl = crop_name(k, style) + (f" ({with_pct[k]})" if with_pct and k in with_pct else "")
        out.append(Button(label=lbl, payload=f"crop:{k}"))
    if only:
        out.append(Button(label=t("btn_other_crop", style), payload="crop:list"))
    return out


def _route(msg, user, case, st, text, images, style) -> Reply:
    # ---- commands and buttons
    cmd = (msg.button or (text if text.startswith("/") else "")).strip()
    if cmd in ("/start", "start"):
        return Reply(text=t("welcome", style) + "\n\n" + t("consent", style), style=style,
                     buttons=[Button(label=t("btn_yes", style), payload="consent:yes"), Button(label="No", payload="consent:no")])
    if cmd.startswith("consent:"):
        db.execute("UPDATE users SET consent_images=%s WHERE id=%s", (cmd.endswith("yes"), user["id"]))
        return Reply(text=t("thanks", style) + "\n\n" + t("ask_photo", style), style=style)
    if cmd in ("/new", "new"):
        _close(case["id"])
        case["_closed"] = True
        return Reply(text=t("new_case", style), style=style)
    if cmd.startswith("/language") or cmd.startswith("lang:"):
        new = cmd.split(":", 1)[1] if ":" in cmd else ("ta" if style != "ta" else "en")
        db.execute("UPDATE users SET preferred_style=%s WHERE id=%s", (new, user["id"]))
        st["style"] = new
        return Reply(text=t("welcome", new), style=new)
    if cmd in ("/agronomist", "esc"):
        return _escalate(user, case, st, style, reason="farmer asked")
    if cmd == "products":
        return _products(st, style)
    if cmd == "photo_hint":
        return Reply(text=t("ask_photo", style), style=style, action="ask")
    if cmd == "crop:list":
        return Reply(text=t("ask_crop", style), style=style, buttons=_crop_buttons(style), action="ask")
    if cmd.startswith("crop:"):
        crop = cmd.split(":", 1)[1]
        if crop in crops():
            _set_crop(case, st, crop, "farmer")
            pending = st.pop("pending_image", None)
            if pending:
                return _diagnose_photo(user, case, st, pending, style, farmer_confirmed=True)
            return _symptom_flow(user, case, st, style)
    if cmd.startswith("age:"):
        st["leaf_age"] = cmd.split(":", 1)[1]
        return _symptom_flow(user, case, st, style)

    # ---- understand free text
    u = understand(text, st) if text else {"crops": [], "symptoms": [], "leaf_age": None, "intents": [], "question_en": None}
    if u["crops"]:
        new_crop = u["crops"][0]
        if st.get("crop") and new_crop != st["crop"] and st.get("diagnosis"):
            _close(case["id"])  # different crop after a finished diagnosis = new problem
            case.clear()
            case.update(_open_case(user["id"]))
            st = case["state"]
            st["style"] = style
        _set_crop(case, st, new_crop, "farmer")
    if u["symptoms"]:
        st["symptoms"] = sorted(set(st.get("symptoms", [])) | set(u["symptoms"]))
    if u["leaf_age"]:
        st["leaf_age"] = u["leaf_age"]

    if "agronomist" in u["intents"]:
        return _escalate(user, case, st, style, reason="farmer asked")
    if images:
        return _diagnose_photo(user, case, st, images[0], style)
    if "product" in u["intents"]:
        return _products(st, style, question=text, question_en=u["question_en"])
    if u["symptoms"] or (u["leaf_age"] and st.get("symptoms")):
        return _symptom_flow(user, case, st, style)
    if "photo_refusal" in u["intents"] and st.get("symptoms"):
        st["photo_declined"] = True
        return _symptom_flow(user, case, st, style)
    if "greeting" in u["intents"] and len(text.split()) <= 3:
        return Reply(text=t("welcome", style), style=style)
    if u["crops"] and not text.strip("?").count(" ") > 2:
        return Reply(text=t("ask_photo", style), style=style, action="ask")
    return _knowledge(st, style, text, u["question_en"])


def _set_crop(case, st, crop, source):
    if st.get("crop") != crop:
        st.pop("diagnosis", None)
    st["crop"], st["crop_source"] = crop, source


# ------------------------------------------------------------------ diagnosis
def _diagnose_photo(user, case, st, image_path, style, farmer_confirmed=False) -> Reply:
    res = vision.analyse(image_path, crop_hint=st.get("crop"), hint_confirmed=farmer_confirmed)
    db.execute("INSERT INTO diagnoses (case_id, image_path, result) VALUES (%s,%s,%s)",
               (case["id"], image_path, json.dumps(res.as_dict(), ensure_ascii=False, default=str)))
    dbg = {"vision": res.as_dict()}
    if res.action == "ask_clearer":
        return Reply(text=t(f"clearer_{res.reason}", style), style=style, action="ask", debug=dbg)
    if res.action == "not_plant":
        return Reply(text=t("not_plant", style), style=style, action="ask", debug=dbg)
    if res.action == "error":
        return Reply(text=t("error", style), style=style, action="error", debug=dbg)
    if res.action in ("ask_crop", "multiple_plants"):
        st["pending_image"] = image_path
        only = [c for c, _ in res.crop_top if c in crops()] or None
        pcts = {c: vision.pct(p) for c, p in res.crop_top} if res.crop_top else None
        key = "multiple_plants" if res.action == "multiple_plants" else "ask_crop"
        return Reply(text=t(key, style), style=style, buttons=_crop_buttons(style, only, pcts), action="ask", debug=dbg)
    if res.action == "confirm_crop":
        st["pending_image"] = image_path
        conf = f" ({res.crop_display})" if res.crop_display else ""
        return Reply(text=t("confirm_crop", style, crop=crop_name(res.crop, style), conf=conf), style=style, action="ask",
                     buttons=[Button(label=t("btn_yes", style), payload=f"crop:{res.crop}"),
                              Button(label=t("btn_no", style), payload="crop:list")], debug=dbg)

    _set_crop(case, st, res.crop, res.crop_source)
    st["crop_display"] = res.crop_display
    st["has_photo"] = True
    st.setdefault("images", []).append(image_path)
    st["symptoms"] = sorted(set(st.get("symptoms", [])) | set(res.symptoms_seen))
    st["head"] = res.disease_top
    st["head_version"] = res.head_version
    r = _symptom_flow(user, case, st, style, just_photo=True)
    r.debug.update(dbg)
    return r


def _symptom_flow(user, case, st, style, just_photo=False) -> Reply:
    crop = st.get("crop")
    if not crop:
        return Reply(text=t("ask_crop", style), style=style, buttons=_crop_buttons(style), action="ask")
    tri = triage(crop, st.get("symptoms", []), st.get("leaf_age"), bool(st.get("has_photo") or st.get("photo_declined")),
                 st.get("head") or None, st.get("questions_asked", 0))
    if tri.next_question and not just_photo:
        st["questions_asked"] = st.get("questions_asked", 0) + 1
        if tri.next_question == "leaf_age":
            return Reply(text=t("ask_leaf_age", style), style=style, action="ask",
                         buttons=[Button(label=t("btn_older", style), payload="age:older"),
                                  Button(label=t("btn_newer", style), payload="age:newer")])
        return Reply(text=t("ask_photo", style), style=style, action="ask")
    return _compose_diagnosis(user, case, st, style, tri)


def _crop_line(st, style) -> str:
    c = crop_name(st["crop"], style)
    if st.get("crop_source") == "vision" and st.get("crop_display"):
        return "🌱 " + t("crop_line_vision", style, crop=c, pct=st["crop_display"])
    return "🌱 " + t("crop_line_farmer", style, crop=c)


def _compose_diagnosis(user, case, st, style, tri) -> Reply:
    crop = st["crop"]
    lines = [_crop_line(st, style), ""]
    buttons = [Button(label=t("btn_photo", style), payload="photo_hint"), _agronomist_btn(style)]
    st["status"] = "diagnosed"
    if tri.healthy:
        lines.append(t("healthy", style))
        st["diagnosis"] = {"healthy": True}
        return Reply(text="\n".join(lines), style=style, buttons=buttons)
    if not tri.candidates:
        lines.append(t("unclear", style))
        st["diagnosis"] = {"candidates": []}
        return Reply(text="\n".join(lines), style=style, buttons=buttons, action="answer")

    from_head = tri.candidates[0].calibrated_p is not None
    if from_head:
        lines.append(t("head_likely" if tri.certainty == "likely" else "head_possible", style))
        for c in tri.candidates:
            pc = f" — {vision.pct(c.calibrated_p)}" if c.calibrated_p is not None else ""
            lines.append(f"• {problem_name(crop, c.problem, style)}{pc}")
    else:
        lines.append(t("symptom_possible", style))
        for c in tri.candidates:
            ev = ", ".join(sym(e, style) for e in c.evidence)
            lines.append(f"• {problem_name(crop, c.problem, style)}" + (f" ({ev})" if ev else ""))
        lines.append("")
        lines.append("ℹ️ " + t("no_head_note", style, crop=crop_name(crop, style)))

    top = tri.candidates[0]
    note = problems(crop)[top.problem].get("note_ta" if style == "ta" else "note_en")
    if note:
        lines += ["", "⚠️ " + note]

    keys = [c.problem for c in tri.candidates]
    st["diagnosis"] = {"candidates": [c.__dict__ for c in tri.candidates], "certainty": tri.certainty,
                       "head_version": st.get("head_version")}
    sources: list[Source] = []
    lines.append("")
    lines += _product_block(crop, keys, style, sources, top_name=problem_name(crop, top.problem, style))
    return Reply(text="\n".join(lines).strip(), style=style, buttons=buttons, sources=sources)


def _product_block(crop, problem_keys, style, sources, top_name=None) -> list[str]:
    matches = products.recommend(crop, problem_keys)
    exact = [m for m in matches if m.exact]
    general = [m for m in matches if not m.exact]
    out = []
    if exact:
        out.append("🧴 " + t("products_header", style))
        out += _format_products(exact, crop, style, sources)
    else:
        out.append(t("no_product", style, problem=top_name or "", crop=crop_name(crop, style)))
        if general:
            out += ["", "🧴 " + t("general_products_header", style, crop=crop_name(crop, style))]
            out += _format_products(general, crop, style, sources)
    if matches:
        out += ["", t("dealer", style)]
    return out


def _format_products(ms, crop, style, sources) -> list[str]:
    out = []
    for m in ms:
        out.append(f"\n▪️ {m.name}" + (f" ({m.category})" if m.category else ""))
        if m.problem != "general_crop_health":
            out.append(f"   → {problem_name(crop, m.problem, style)}")
        out.append(f"   {t('dosage', style)}: {m.dosage}")
        out.append(f"   {t('method', style)}: {m.method}")
        if m.frequency:
            out.append(f"   {t('frequency', style)}: {m.frequency}")
        if m.precautions:
            out.append(f"   {t('precautions', style)}: {m.precautions}")
        out.append(f"   {t('source', style)}: {m.source_doc}, {m.source_ref}")
        sources.append(Source(title=m.source_doc, ref=m.source_ref))
    return out


# ------------------------------------------------------------------ products
def _products(st, style, question: str = "", question_en: str | None = None) -> Reply:
    crop = st.get("crop")
    if not crop:
        return Reply(text=t("ask_crop", style), style=style, buttons=_crop_buttons(style), action="ask")
    sources: list[Source] = []
    diag = st.get("diagnosis") or {}
    keys = [c["problem"] for c in diag.get("candidates", [])]
    lines = [_crop_line(st, style), ""]
    if keys:
        lines += _product_block(crop, keys, style, sources, top_name=problem_name(crop, keys[0], style))
    else:
        raw = products.products_for_crop(crop) + [m for m in products.recommend(crop, []) if not m.exact]
        seen_p = set()
        ms = []
        for m in raw:
            k = (m.name, m.problem, m.method)
            if k not in seen_p:
                seen_p.add(k)
                ms.append(m)
        if ms:
            lines.append("🧴 " + t("products_header", style))
            lines += _format_products(ms, crop, style, sources) + ["", t("dealer", style)]
        else:
            if question and len(question.strip().split()) > 1:
                kb_reply = _knowledge(st, style, question, question_en)
                if kb_reply.action != "ask" and "could not find" not in kb_reply.text.lower():
                    return kb_reply
            lines.append(t("no_product_crop", style, crop=crop_name(crop, style)))
    return Reply(text="\n".join(lines).strip(), style=style, sources=sources, buttons=[_agronomist_btn(style)])


# ------------------------------------------------------------------ knowledge (RAG)
ANSWER_SYSTEM = (
    "You are Vishakan Biotech's agricultural assistant. Answer ONLY from the numbered context passages. "
    "Do not add product names, numbers, doses or claims that are not in the passages. "
    "If the passages do not answer the question, reply exactly NOT_FOUND. "
    "Cite passages like [1]. Write simply for a farmer."
)
STYLE_INSTR = {"ta": "Write the answer in Tamil script.", "en": "Write the answer in simple English.",
               "ta-Latn": "Write the answer in Tanglish (Tamil words in English letters)."}


def _knowledge(st, style, text, question_en=None) -> Reply:
    crop = st.get("crop")
    q = " ".join(x for x in [text, question_en, crop_name(crop, "en") if crop else None] if x)
    hits = knowledge.retrieve(q, crop=crop)
    if not hits:
        return Reply(text=t("kb_none", style), style=style, buttons=[_agronomist_btn(style)])
    sources = [Source(title=h.title, ref=h.ref) for h in hits[:3]]
    if has_llm():
        ctx = "\n\n".join(f"[{i}] {h.content}" for i, h in enumerate(hits, 1))
        ans = get_llm().generate(ANSWER_SYSTEM, f"Context:\n{ctx}\n\nQuestion: {text}\n{STYLE_INSTR[style]}")
        if ans and "NOT_FOUND" not in ans:
            bad_nums = knowledge.unsupported_numbers(ans, [h.content for h in hits])
            if not bad_nums:
                return Reply(text=ans.strip() + "\n\n" + _source_lines(sources, style), style=style, sources=sources,
                             buttons=[_agronomist_btn(style)])
            log.warning("answer rejected, unsupported numbers: %s", bad_nums)
        elif ans and "NOT_FOUND" in ans:
            return Reply(text=t("kb_none", style), style=style, buttons=[_agronomist_btn(style)])
    # No LLM or answer failed validation: show the retrieved passages themselves.
    body = "\n\n".join(f"“{h.content[:450].strip()}{'…' if len(h.content) > 450 else ''}”" for h in hits[:2])
    return Reply(text=t("kb_header", style) + "\n\n" + body + "\n\n" + _source_lines(sources[:2], style), style=style,
                 sources=sources[:2], buttons=[_agronomist_btn(style)])


def _source_lines(sources, style) -> str:
    return "\n".join(f"📄 {t('source', style)}: {s.title} — {s.ref}" for s in sources)


# ------------------------------------------------------------------ escalation
def _escalate(user, case, st, style, reason) -> Reply:
    code = secrets.token_hex(3).upper()
    db.execute("INSERT INTO escalations (short_code, case_id, user_id, reason) VALUES (%s,%s,%s,%s)",
               (code, case["id"], user["id"], reason))
    st["status"] = "escalated"
    diag = st.get("diagnosis") or {}
    cands = ", ".join(problem_name(st["crop"], c["problem"], "en") for c in diag.get("candidates", [])) if st.get("crop") else ""
    summary = (f"Case #{code}\nFarmer: {user.get('name') or user['channel_user_id']} ({user['channel']})\n"
               f"Language: {style}\nCrop: {st.get('crop') or 'unknown'} (source: {st.get('crop_source') or '-'})\n"
               f"Symptoms: {', '.join(st.get('symptoms', [])) or '-'}; leaf age: {st.get('leaf_age') or '-'}\n"
               f"Bot's possible causes: {cands or '-'}\nReason: {reason}\n\nReply to THIS message to answer the farmer.")
    return Reply(text=t("escalated", style, code=code), style=style, action="escalate", escalate=True,
                 escalation_summary=summary, escalation_images=st.get("images", [])[-3:])


def agronomist_reply(code: str, text: str, verified_crop: str | None = None, verified_label: str | None = None) -> dict | None:
    e = db.fetchone("SELECT e.*, u.channel, u.channel_user_id, u.preferred_style FROM escalations e "
                    "JOIN users u ON u.id = e.user_id WHERE e.short_code=%s", (code.upper(),))
    if not e:
        return None
    db.execute("UPDATE escalations SET status='answered', agronomist_reply=%s, verified_crop=%s, verified_label=%s, "
               "resolved_at=now() WHERE id=%s", (text, verified_crop, verified_label, e["id"]))
    db.execute("INSERT INTO feedback (case_id, source, verdict, corrected_crop, corrected_label, notes) "
               "VALUES (%s,'agronomist','answered',%s,%s,%s)", (e["case_id"], verified_crop, verified_label, text))
    style = e["preferred_style"] or "en"
    return {"channel": e["channel"], "user_ref": e["channel_user_id"],
            "text": f"👩‍🌾 {t('agronomist_reply', style)}\n\n{text}"}
