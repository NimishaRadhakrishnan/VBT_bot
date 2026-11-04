"""Reply templates in Tamil (ta), English (en) and Tanglish (ta-Latn).
Agronomy-critical wording lives here so the agronomist can review it in one place."""

T: dict[str, dict[str, str]] = {
    "welcome": {
        "en": "Vanakkam! I am the Vishakan Biotech crop assistant.\n\nYou can:\n• send a photo of the affected plant\n• tell me the problem by text or voice\n• ask about Vishakan products\n\nI answer in Tamil or English, whichever you use.",
        "ta": "வணக்கம்! நான் விசாகன் பயோடெக் பயிர் உதவியாளர்.\n\nநீங்கள்:\n• பாதிக்கப்பட்ட செடியின் புகைப்படம் அனுப்பலாம்\n• பிரச்சனையை எழுத்து அல்லது குரல் மூலம் சொல்லலாம்\n• விசாகன் பொருட்கள் பற்றி கேட்கலாம்\n\nநீங்கள் பயன்படுத்தும் மொழியில் (தமிழ் / ஆங்கிலம்) பதில் சொல்வேன்.",
        "ta-Latn": "Vanakkam! Naan Vishakan Biotech payir udhaviyaalar.\n\nNeenga:\n• baadhikkappatta chediyoda photo anuppalaam\n• prachanaiya text illa voice-la sollalaam\n• Vishakan products pathi kekkalaam\n\nNeenga pesura mozhiyila badhil solluven.",
    },
    "consent": {
        "en": "To improve diagnosis, photos you send may be reviewed by Vishakan agronomists. Is that okay?",
        "ta": "கண்டறிதலை மேம்படுத்த, நீங்கள் அனுப்பும் புகைப்படங்களை விசாகன் வேளாண் நிபுணர்கள் பார்வையிடலாம். சம்மதமா?",
        "ta-Latn": "Diagnosis-a improve panna, neenga anuppura photos-a Vishakan agronomists paarkalaam. Ok-va?",
    },
    "ask_crop": {
        "en": "Which crop is this? Please choose:",
        "ta": "இது எந்த பயிர்? தேர்வு செய்யுங்கள்:",
        "ta-Latn": "Idhu endha payir? Choose pannunga:",
    },
    "ask_leaf_age": {
        "en": "Are the older (lower) leaves turning yellow, or the newer (top) leaves?",
        "ta": "பழைய (கீழ்) இலைகள் மஞ்சளாகிறதா, அல்லது புதிய (மேல்) இலைகளா?",
        "ta-Latn": "Pazhaya (keezh) ilaigal manjal aaguthaa, illa pudhu (mel) ilaigalaa?",
    },
    "ask_photo": {
        "en": "Can you send a clear photo of the affected plant? Take it in daylight, about one hand-span from the leaf.",
        "ta": "பாதிக்கப்பட்ட செடியின் தெளிவான புகைப்படம் அனுப்ப முடியுமா? பகல் வெளிச்சத்தில், இலையிலிருந்து ஒரு சாண் தூரத்தில் எடுக்கவும்.",
        "ta-Latn": "Baadhikkappatta chediyoda clear photo anuppa mudiyumaa? Pagal velichathula, ilai-la irundhu oru saan dhoorathula edunga.",
    },
    "clearer_blurry": {
        "en": "The photo is blurry. Please hold the phone steady and send it again, close to the affected leaf.",
        "ta": "புகைப்படம் தெளிவாக இல்லை. கைபேசியை அசையாமல் பிடித்து, பாதித்த இலையின் அருகில் மீண்டும் எடுத்து அனுப்பவும்.",
        "ta-Latn": "Photo clear-a illa. Phone-a asaiyaama pidichu, baadhicha ilai pakkathula marubadiyum eduthu anuppunga.",
    },
    "clearer_too_dark": {
        "en": "The photo is too dark. Please take it again in daylight.",
        "ta": "புகைப்படம் மிகவும் இருட்டாக உள்ளது. பகல் வெளிச்சத்தில் மீண்டும் எடுக்கவும்.",
        "ta-Latn": "Photo romba irutta irukku. Pagal velichathula marubadiyum edunga.",
    },
    "clearer_too_bright": {
        "en": "The photo is too bright. Please avoid direct sun on the camera and try again.",
        "ta": "புகைப்படம் மிகவும் வெளிச்சமாக உள்ளது. கேமராவில் நேரடி வெயில் படாமல் மீண்டும் எடுக்கவும்.",
        "ta-Latn": "Photo romba velicham-a irukku. Camera-la nera veyil padaama marubadiyum edunga.",
    },
    "clearer_too_small": {
        "en": "The photo is too small. Please send the original photo, closer to the leaf.",
        "ta": "புகைப்படம் மிகச் சிறியதாக உள்ளது. இலையின் அருகில் எடுத்த அசல் புகைப்படத்தை அனுப்பவும்.",
        "ta-Latn": "Photo romba chinnadhaa irukku. Ilai pakkathula eduthu original photo anuppunga.",
    },
    "not_plant": {
        "en": "I could not find a plant in this photo. Please send a photo of the affected leaves or plant.",
        "ta": "இந்த புகைப்படத்தில் செடி தெரியவில்லை. பாதிக்கப்பட்ட இலை அல்லது செடியின் புகைப்படம் அனுப்பவும்.",
        "ta-Latn": "Indha photo-la chedi theriyala. Baadhikkappatta ilai illa chediyoda photo anuppunga.",
    },
    "multiple_plants": {
        "en": "I can see more than one kind of plant. Which plant is your question about?",
        "ta": "புகைப்படத்தில் ஒன்றுக்கு மேற்பட்ட செடிகள் தெரிகின்றன. எந்த செடி பற்றி கேட்கிறீர்கள்?",
        "ta-Latn": "Photo-la onnukku mela chedigal theriyudhu. Endha chedi pathi kekkureenga?",
    },
    "confirm_crop": {
        "en": "The photo looks like {crop}{conf}. Is that correct?",
        "ta": "புகைப்படம் {crop} போல் தெரிகிறது{conf}. சரியா?",
        "ta-Latn": "Photo {crop} maadhiri theriyudhu{conf}. Sariyaa?",
    },
    "crop_line_vision": {"en": "Crop: {crop} (identified from the photo, about {pct})",
                         "ta": "பயிர்: {crop} (புகைப்படத்திலிருந்து கண்டறிந்தது, சுமார் {pct})",
                         "ta-Latn": "Payir: {crop} (photo-la irundhu kandupidichadhu, sumaar {pct})"},
    "crop_line_farmer": {"en": "Crop: {crop} (as you told me)", "ta": "பயிர்: {crop} (நீங்கள் சொன்னபடி)",
                         "ta-Latn": "Payir: {crop} (neenga sonnapadi)"},
    "healthy": {
        "en": "The plant in the photo looks healthy. If you see a problem, describe it or send a closer photo of that part.",
        "ta": "புகைப்படத்தில் உள்ள செடி ஆரோக்கியமாகத் தெரிகிறது. பிரச்சனை இருந்தால் அதை விவரிக்கவும் அல்லது அந்தப் பகுதியின் அருகில் எடுத்த புகைப்படம் அனுப்பவும்.",
        "ta-Latn": "Photo-la irukka chedi nalla aarogyama theriyudhu. Prachanai irundha adha sollunga illa andha idathoda close photo anuppunga.",
    },
    "head_likely": {"en": "Likely problem:", "ta": "பெரும்பாலும் இந்த பிரச்சனை:", "ta-Latn": "Perumbaalum indha prachanai:"},
    "head_possible": {"en": "Possible problems:", "ta": "இருக்கக்கூடிய பிரச்சனைகள்:", "ta-Latn": "Irukka koodiya prachanaigal:"},
    "symptom_possible": {
        "en": "Possible causes, based on the symptoms (not a confirmed diagnosis):",
        "ta": "அறிகுறிகளின் அடிப்படையில் இருக்கக்கூடிய காரணங்கள் (உறுதியான கண்டறிதல் அல்ல):",
        "ta-Latn": "Arigurigal adippadaiyil irukka koodiya kaaranangal (urudhiyaana diagnosis illa):",
    },
    "unclear": {
        "en": "I cannot tell the cause reliably from this. Please describe what you see (spots, curling, yellowing, insects, wilting) or talk to our agronomist.",
        "ta": "இதிலிருந்து காரணத்தை உறுதியாகச் சொல்ல முடியவில்லை. நீங்கள் பார்ப்பதை (புள்ளிகள், சுருட்டல், மஞ்சள், பூச்சி, வாடல்) விவரிக்கவும் அல்லது எங்கள் வேளாண் நிபுணரிடம் பேசவும்.",
        "ta-Latn": "Idhula irundhu kaaranatha urudhiyaa solla mudiyala. Neenga paakkuradha (pulli, surul, manjal, poochi, vaadal) sollunga illa engal agronomist kitta pesunga.",
    },
    "no_head_note": {
        "en": "No percentage is shown because the disease model for {crop} is still being trained.",
        "ta": "{crop} பயிருக்கான நோய் கண்டறியும் மாதிரி இன்னும் பயிற்சியில் உள்ளதால் சதவீதம் காட்டப்படவில்லை.",
        "ta-Latn": "{crop}-kkaana noi model innum training-la irukkaradhaala percentage kaattala.",
    },
    "products_header": {"en": "Verified Vishakan products for this:", "ta": "இதற்கான சரிபார்க்கப்பட்ட விசாகன் பொருட்கள்:",
                        "ta-Latn": "Idhukkaana verify panna Vishakan products:"},
    "general_products_header": {"en": "Verified Vishakan products for general {crop} crop health:",
                                "ta": "{crop} பயிரின் பொது ஆரோக்கியத்திற்கான சரிபார்க்கப்பட்ட விசாகன் பொருட்கள்:",
                                "ta-Latn": "{crop} payir podhu aarogyathukkaana verify panna Vishakan products:"},
    "dosage": {"en": "Dosage", "ta": "அளவு", "ta-Latn": "Alavu"},
    "method": {"en": "Method", "ta": "முறை", "ta-Latn": "Murai"},
    "frequency": {"en": "When / how often", "ta": "எப்போது / எத்தனை முறை", "ta-Latn": "Eppo / ethana murai"},
    "precautions": {"en": "Precautions", "ta": "முன்னெச்சரிக்கை", "ta-Latn": "Munnecharikkai"},
    "source": {"en": "Source", "ta": "ஆதாரம்", "ta-Latn": "Aadhaaram"},
    "no_product": {
        "en": "Vishakan documents do not list a verified product for {problem} on {crop}. Please talk to our agronomist before applying anything.",
        "ta": "{crop} பயிரில் {problem} பிரச்சனைக்கு சரிபார்க்கப்பட்ட விசாகன் பொருள் ஆவணங்களில் இல்லை. எதையும் பயன்படுத்தும் முன் எங்கள் வேளாண் நிபுணரிடம் பேசவும்.",
        "ta-Latn": "{crop} payir-la {problem}-kku verify panna Vishakan product documents-la illa. Edhaiyum use panradhukku munnaadi engal agronomist kitta pesunga.",
    },
    "no_product_crop": {
        "en": "There is no verified Vishakan product for {crop} in our documents yet. Please talk to our agronomist.",
        "ta": "எங்கள் ஆவணங்களில் {crop} பயிருக்கு இன்னும் சரிபார்க்கப்பட்ட விசாகன் பொருள் இல்லை. எங்கள் வேளாண் நிபுணரிடம் பேசவும்.",
        "ta-Latn": "Engal documents-la {crop} payirukku innum verify panna Vishakan product illa. Engal agronomist kitta pesunga.",
    },
    "dealer": {"en": "Ask your nearest Vishakan dealer for these products.", "ta": "இந்த பொருட்களை உங்கள் அருகிலுள்ள விசாகன் விற்பனையாளரிடம் கேளுங்கள்.",
               "ta-Latn": "Indha products-a ungal pakkathula irukka Vishakan dealer kitta kelunga."},
    "kb_header": {"en": "From Vishakan Biotech documents:", "ta": "விசாகன் பயோடெக் ஆவணங்களிலிருந்து:",
                  "ta-Latn": "Vishakan Biotech documents-la irundhu:"},
    "kb_none": {
        "en": "I could not find this in Vishakan Biotech's documents. Please talk to our agronomist.",
        "ta": "இந்த தகவல் விசாகன் பயோடெக் ஆவணங்களில் கிடைக்கவில்லை. எங்கள் வேளாண் நிபுணரிடம் பேசவும்.",
        "ta-Latn": "Indha thagaval Vishakan Biotech documents-la kidaikkala. Engal agronomist kitta pesunga.",
    },
    "escalated": {
        "en": "I have sent your case (#{code}) to a Vishakan agronomist. They will reply here.",
        "ta": "உங்கள் விவரங்களை (#{code}) விசாகன் வேளாண் நிபுணருக்கு அனுப்பியுள்ளேன். அவர் இங்கே பதில் அளிப்பார்.",
        "ta-Latn": "Ungal case-a (#{code}) Vishakan agronomist-kku anuppitten. Avanga inge badhil solluvaanga.",
    },
    "agronomist_reply": {"en": "Reply from Vishakan agronomist:", "ta": "விசாகன் வேளாண் நிபுணரின் பதில்:", "ta-Latn": "Vishakan agronomist badhil:"},
    "voice_failed": {
        "en": "Sorry, I could not understand the voice message. Please try again or type your question.",
        "ta": "மன்னிக்கவும், குரல் செய்தியைப் புரிந்துகொள்ள முடியவில்லை. மீண்டும் முயற்சிக்கவும் அல்லது கேள்வியை எழுதி அனுப்பவும்.",
        "ta-Latn": "Mannikkavum, voice message puriyala. Marubadiyum try pannunga illa type panni anuppunga.",
    },
    "heard": {"en": "I heard: “{t}”", "ta": "நான் கேட்டது: “{t}”", "ta-Latn": "Naan kettadhu: “{t}”"},
    "new_case": {"en": "Okay, starting a new question. Tell me the problem or send a photo.",
                 "ta": "சரி, புதிய கேள்வியைத் தொடங்குகிறேன். பிரச்சனையைச் சொல்லுங்கள் அல்லது புகைப்படம் அனுப்புங்கள்.",
                 "ta-Latn": "Sari, pudhu kelvi start pannuren. Prachanaiya sollunga illa photo anuppunga."},
    "rate_limited": {"en": "You are sending messages very fast. Please wait a few minutes.",
                     "ta": "நீங்கள் மிக வேகமாக செய்திகளை அனுப்புகிறீர்கள். சில நிமிடங்கள் காத்திருக்கவும்.",
                     "ta-Latn": "Neenga romba vegama messages anuppureenga. Konjam nimisham wait pannunga."},
    "error": {"en": "Sorry, something went wrong. Please send it again.", "ta": "மன்னிக்கவும், ஏதோ தவறு நடந்தது. மீண்டும் அனுப்பவும்.",
              "ta-Latn": "Mannikkavum, edho thappu aayiduchu. Marubadiyum anuppunga."},
    "thanks": {"en": "Thank you!", "ta": "நன்றி!", "ta-Latn": "Nandri!"},
    # button labels
    "btn_older": {"en": "Older leaves", "ta": "பழைய இலைகள்", "ta-Latn": "Pazhaya ilaigal"},
    "btn_newer": {"en": "Newer leaves", "ta": "புதிய இலைகள்", "ta-Latn": "Pudhu ilaigal"},
    "btn_photo": {"en": "📷 Send a photo", "ta": "📷 புகைப்படம் அனுப்ப", "ta-Latn": "📷 Photo anuppa"},
    "btn_agronomist": {"en": "👩‍🌾 Talk to agronomist", "ta": "👩‍🌾 வேளாண் நிபுணரிடம் பேச", "ta-Latn": "👩‍🌾 Agronomist kitta pesa"},
    "btn_yes": {"en": "Yes", "ta": "ஆம்", "ta-Latn": "Aamaa"},
    "btn_no": {"en": "No, another crop", "ta": "இல்லை, வேறு பயிர்", "ta-Latn": "Illa, vera payir"},
    "btn_products": {"en": "🧴 Vishakan products", "ta": "🧴 விசாகன் பொருட்கள்", "ta-Latn": "🧴 Vishakan products"},
    "btn_other_crop": {"en": "Other crop", "ta": "வேறு பயிர்", "ta-Latn": "Vera payir"},
}

SYMPTOM_WORDS = {
    "yellowing": {"en": "yellowing", "ta": "மஞ்சள் நிறம்", "ta-Latn": "manjal niram"},
    "leaf_curl": {"en": "leaf curling", "ta": "இலை சுருட்டல்", "ta-Latn": "ilai surul"},
    "leaf_spots": {"en": "spots on leaves", "ta": "இலைப் புள்ளிகள்", "ta-Latn": "ilai pulligal"},
    "white_powder": {"en": "white powder", "ta": "வெள்ளை பூச்சு", "ta-Latn": "vellai poochu"},
    "wilting": {"en": "wilting", "ta": "வாடல்", "ta-Latn": "vaadal"},
    "fruit_rot": {"en": "rotting", "ta": "அழுகல்", "ta-Latn": "azhugal"},
    "base_rot": {"en": "rot at the base", "ta": "அடிப்பகுதி அழுகல்", "ta-Latn": "adi azhugal"},
    "holes_chewed": {"en": "holes / chewing", "ta": "ஓட்டைகள்", "ta-Latn": "ottaigal"},
    "insects_visible": {"en": "insects seen", "ta": "பூச்சிகள் தெரிகின்றன", "ta-Latn": "poochigal theriyudhu"},
    "stunting": {"en": "poor growth", "ta": "வளர்ச்சி குறைவு", "ta-Latn": "valarchi kuraivu"},
    "mosaic": {"en": "mosaic pattern", "ta": "தேமல்", "ta-Latn": "themal"},
    "drying": {"en": "drying / burning", "ta": "கருகல்", "ta-Latn": "karugal"},
    "leaf_streaks": {"en": "streaks on leaves", "ta": "இலைக் கோடுகள்", "ta-Latn": "ilai kodugal"},
    "webbing": {"en": "webbing", "ta": "வலை", "ta-Latn": "valai"},
    "leaf_age:older": {"en": "older leaves affected", "ta": "பழைய இலைகள் பாதிப்பு", "ta-Latn": "pazhaya ilaigal baadhippu"},
    "leaf_age:newer": {"en": "newer leaves affected", "ta": "புதிய இலைகள் பாதிப்பு", "ta-Latn": "pudhu ilaigal baadhippu"},
}


def t(key: str, style: str, **kw) -> str:
    s = T[key].get(style) or T[key]["en"]
    return s.format(**kw) if kw else s


def sym(key: str, style: str) -> str:
    return SYMPTOM_WORDS.get(key, {}).get(style, key.replace("_", " "))
