from agri.language import detect_style, extract


EXAMPLES = {
    "ta": "என் மிளகாய் செடியில் இலை சுருண்டு போகுது. என்ன பிரச்சனை?",
    "en": "My chilli plant leaves are curling. What is the reason?",
    "ta-Latn": "En milagai chediyoda leaves curl aaguthu. Enna disease?",
}


def test_the_three_requirement_examples_are_understood():
    for style, text in EXAMPLES.items():
        assert detect_style(text) == style, text
        e = extract(text)
        assert e.crops == ["chilli"], (text, e)
        assert "leaf_curl" in e.symptoms, (text, e)


def test_short_reply_keeps_conversation_language():
    assert detect_style("ok", previous="ta") == "ta"
    assert detect_style("Pazhaya ilaigal", previous="en") == "ta-Latn"


def test_tanglish_spelling_variants_and_chilli_vs_pepper():
    assert extract("milaghai chedi manjal aaguthu").crops == ["chilli"]
    assert extract("milagu kodi vaadi poguthu").crops == ["pepper"]
    assert extract("மிளகு கொடி").crops == ["pepper"]
    assert extract("keezh ilai manjal").leaf_age == "older"
    e = extract("pudhu ilai manjala irukku")
    assert e.leaf_age == "newer" and "yellowing" in e.symptoms


def test_product_intent_in_all_languages():
    for text in ["Which Vishakan product is suitable for chilli?", "மிளகாய்க்கு எந்த மருந்து?", "milagai ku enna marunthu podanum"]:
        assert "product" in extract(text).intents, text
