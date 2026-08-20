# Suppress TensorFlow warnings and disable oneDNN for compatibility
import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

import uuid
import sqlite3
import json
import re
import hashlib
import sys
from html.parser import HTMLParser
from datetime import datetime
from pathlib import Path
from threading import Lock
from urllib.parse import quote, quote_plus
from urllib.request import Request, urlopen

from flask import Flask, jsonify, render_template, request, send_from_directory
from dotenv import load_dotenv
from groq import Groq

from rag import (
    build_index,
    health,
    search_guidelines,
    build_context,
    TOP_K,
)

# =========================================================
# LOAD ENVIRONMENT
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

LOCAL_SCORE_THRESHOLD = float(os.getenv("LOCAL_SCORE_THRESHOLD", "0.42"))
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "true").lower() == "true"
ANSWER_MODE = os.getenv("ANSWER_MODE", "direct").lower()
USER_DAILY_MESSAGE_LIMIT = int(os.getenv("USER_DAILY_MESSAGE_LIMIT", "30"))
WEB_FALLBACK_SCORE_THRESHOLD = float(os.getenv("WEB_FALLBACK_SCORE_THRESHOLD", "0.45"))

# Debug startup info
print(f"[APP] Starting Clinical RAG application...", file=sys.stderr)
print(f"[APP] Base directory: {BASE_DIR}", file=sys.stderr)
print(f"[APP] Python version: {sys.version}", file=sys.stderr)

# =========================================================
# FLASK
# =========================================================

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

# =========================================================
# DATABASE
# =========================================================

DB_PATH = BASE_DIR / "users.db"


def init_db():
    """Initialize SQLite tables for multi-user chat app."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE,
        password_hash TEXT,
        name TEXT,
        created_at TEXT,
        last_login TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS user_sessions (
        token TEXT PRIMARY KEY,
        user_id TEXT,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS user_profiles (
        id TEXT PRIMARY KEY,
        name TEXT,
        age INTEGER,
        gender TEXT,
        blood_group TEXT,
        medical_history TEXT,
        medications TEXT,
        photo_path TEXT,
        created_at TEXT,
        updated_at TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS user_chats (
        user_id TEXT,
        chat_id TEXT,
        title TEXT,
        messages_json TEXT,
        created_at TEXT,
        updated_at TEXT,
        PRIMARY KEY (user_id, chat_id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS user_daily_usage (
        user_id TEXT,
        usage_date TEXT,
        message_count INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, usage_date)
    )""")

    conn.commit()
    conn.close()


init_db()


def consume_user_message_quota(user_id):
    usage_date = datetime.utcnow().date().isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT message_count FROM user_daily_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, usage_date),
        ).fetchone()
        current_count = row[0] if row else 0
        if current_count >= USER_DAILY_MESSAGE_LIMIT:
            conn.rollback()
            return False, current_count

        new_count = current_count + 1
        conn.execute(
            "INSERT INTO user_daily_usage (user_id, usage_date, message_count) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, usage_date) DO UPDATE SET message_count = excluded.message_count",
            (user_id, usage_date, new_count),
        )
        conn.commit()
        return True, new_count
    finally:
        conn.close()

# =========================================================
# GROQ
# =========================================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b"
)

GROQ_API_KEYS = []
for key_number in range(1, 100):
    variable_name = "GROQ_API_KEY" if key_number == 1 else f"GROQ_API_KEY_{key_number}"
    api_key = os.getenv(variable_name, "").strip()
    if api_key:
        GROQ_API_KEYS.append(api_key)

groq_clients = [Groq(api_key=api_key) for api_key in GROQ_API_KEYS]
groq_client = groq_clients[0] if groq_clients else None
groq_key_index = 0
groq_key_lock = Lock()


class GroqQuotaExhaustedError(RuntimeError):
    """Raised when every configured Groq key is rate-limited."""

# =========================================================
# IN-MEMORY CHAT STORAGE
# =========================================================

lock = Lock()
chats = {}


# =========================================================
# AUTH HELPERS
# =========================================================


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_session_user():
    token = request.cookies.get("session_token")
    if not token:
        return None

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """SELECT u.id, u.email, u.name FROM users u
        JOIN user_sessions s ON s.user_id = u.id
        WHERE s.token = ?""",
        (token,),
    )
    row = c.fetchone()
    conn.close()

    if not row:
        return None

    return {"id": row[0], "email": row[1], "name": row[2], "guest": str(row[0]).startswith("guest-")}


def set_session_cookie(response, token):
    response.set_cookie(
        "session_token",
        token,
        httponly=True,
        samesite="Lax",
        max_age=60 * 60 * 24 * 30,
    )
    return response


def clear_session_cookie(response):
    response.set_cookie(
        "session_token",
        "",
        expires=0,
        httponly=True,
        samesite="Lax",
    )
    return response


def create_session_for_user(user_id: str):
    token = uuid.uuid4().hex
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO user_sessions (token, user_id, created_at) VALUES (?, ?, ?)",
        (token, user_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return token


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = """
You are Guideline AI, a warm, intelligent medical information assistant.

Respond in the same language as the user. Understand spelling mistakes, Egyptian Arabic, Arabizi, short messages, and follow-up questions from context.

Answer like a strong conversational assistant:
- Start with the direct answer, then add only the most useful explanation.
- Use clear headings or bullets when they improve readability.
- Keep every answer concise: exactly 2-4 short bullets or sentences unless the user asks for detail. Do not add headings or long lists.
- Never repeat the question or pad the answer with generic filler.
- Ask one focused follow-up question only when missing information changes the advice.
- For urgent warning signs, say clearly what the user should do now.
- Do not diagnose with certainty or prescribe antibiotics, inhalers, or prescription medicines without clinical assessment.
- When the question is not an emergency, give practical first-line self-care and reasonable over-the-counter options when appropriate, including important contraindications or label guidance. Do not answer only with “see a doctor.”
- Always explain when and why a clinician is needed, but put that advice after the useful steps unless the symptoms are urgent.
- For medicine questions, distinguish clearly between supportive care, over-the-counter medicine, and prescription treatment.
- Cetirizine and loratadine are antihistamines, not antibiotics. Never label them as antibiotics.
- For nasal congestion, recommend saline spray or rinsing unless a clinician has confirmed a specific medicine; do not invent or guess spray names.
- Never invent sources, statistics, test results, or treatment claims.
- End with a complete sentence. Do not stop mid-sentence.

Be natural and empathetic without pretending to be a human or claiming to be ChatGPT.
This is educational information and not a substitute for a qualified clinician.
Only answer questions about breathing, lungs, chest symptoms, cough, asthma, respiratory allergies, congestion, sore throat, or related respiratory infections.
"""

# =========================================================
# PATIENT PROFILE
# =========================================================

def profile_context(profile):

    if not profile:
        return "No patient profile information was provided."

    fields = [
        ("name", "Name"),
        ("age", "Age"),
        ("gender", "Gender"),
        ("blood_group", "Blood group"),
        ("medical_history", "Medical history"),
        ("allergies", "Allergies"),
        ("medications", "Current medications"),
        ("additional_details", "Additional details"),
    ]

    lines = []

    for key, label in fields:

        value = profile.get(key)

        if value not in (
            None,
            "",
            [],
            {}
        ):
            lines.append(
                f"- {label}: {value}"
            )

    if not lines:
        return "No patient profile information was provided."

    return (
        "PATIENT PROFILE\n"
        "The following information has already been provided "
        "by the patient. Do not ask for it again.\n\n"
        + "\n".join(lines)
    )


# =========================================================
# CHAT FUNCTIONS
# =========================================================

def get_chat(chat_id):

    with lock:

        if chat_id not in chats:

            chats[chat_id] = {
                "id": chat_id,
                "title": "New conversation",
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "messages": [],
            }

        return chats[chat_id]


def add_message(
    chat_id,
    role,
    text
):

    chat = get_chat(chat_id)

    with lock:

        chat["messages"].append(
            {
                "role": role,
                "text": text,
                "time": datetime.now().strftime("%H:%M"),
            }
        )

        chat["updated_at"] = (
            datetime.utcnow().isoformat()
        )

        if (
            role == "user"
            and chat["title"] == "New conversation"
        ):

            chat["title"] = (
                text[:42]
                + ("…" if len(text) > 42 else "")
            )


# =========================================================
# GROQ ANSWER
# =========================================================

def normalize_question(text):
    if not text:
        return ""

    text = str(text).strip()
    text = " ".join(text.split())
    text = text.replace("ـ", "")
    text = text.replace("…", "")
    text = text.replace("\u200c", "")
    text = text.replace("\u200d", "")

    # Remove repeated letters common in fast typing
    text = re.sub(r"(.)\1{2,}", r"\1\1", text)

    return text


def is_respiratory_question(text):
    respiratory_terms = (
        "تنفس", "نفس", "ضيق", "نهجان", "نهج", "كحه", "كحة", "سعال", "بلغم",
        "صفير", "صدر", "رئة", "رئه", "ربو", "اختناق", "حساسية صدر", "رشح",
        "زكام", "عطس", "احتقان", "حلق", "التهاب رئوي", "انفلونزا", "إنفلونزا",
        "cough", "breath", "breathing", "asthma", "lung", "chest", "wheez",
        "sputum", "phlegm", "pneumonia", "flu", "respiratory", "shortness",
    )
    normalized = normalize_question(text).lower()
    return any(term in normalized for term in respiratory_terms)


def retrieval_query(question):
    expansions = {
        "ربو": "asthma",
        "كحة": "cough",
        "كحه": "cough",
        "سعال": "cough",
        "بلغم": "sputum phlegm",
        "صفير": "wheezing",
        "ضيق التنفس": "shortness of breath breathlessness",
        "ضيق نفس": "shortness of breath breathlessness",
        "الانسداد الرئوي المزمن": "chronic obstructive pulmonary disease COPD",
        "احتقان الأنف": "nasal congestion",
        "احتقان": "nasal congestion",
        "حساسية": "allergy allergic",
        "التهاب الحلق": "sore throat",
        "التهاب رئوي": "pneumonia",
    }
    normalized = normalize_question(question)
    terms = [english for arabic, english in expansions.items() if arabic in normalized]
    return f"{normalized} {' '.join(terms)}" if terms else normalized


def sanitize_medical_terms(answer):
    replacements = {
        "مضاد حيوية غير مبرمج (سيتيريزين أو لوراتادين)": "مضاد حساسية بدون وصفة (مثل سيتيريزين أو لوراتادين)",
        "مضاد حيوي غير مبرمج (سيتيريزين أو لوراتادين)": "مضاد حساسية بدون وصفة (مثل سيتيريزين أو لوراتادين)",
        "مضاد حيوية (سيتيريزين أو لوراتادين)": "مضاد حساسية (مثل سيتيريزين أو لوراتادين)",
        "مضاد حيوي (سيتيريزين أو لوراتادين)": "مضاد حساسية (مثل سيتيريزين أو لوراتادين)",
        "مضاد احتقان موضعي (مثل فلوفينازين)": "محلول ملحي للأنف",
        "بخاخ أو قطرة ملح ملحي للأنف أو مضاد احتقان موضعي (مثل فلوفينازين)": "بخاخ أو قطرات محلول ملحي للأنف",
    }
    for incorrect, correct in replacements.items():
        answer = answer.replace(incorrect, correct)
    return answer


def is_groq_quota_error(error):
    status_code = getattr(error, "status_code", None)
    error_text = str(error).lower()
    return status_code == 429 or "rate_limit" in error_text or "rate limit" in error_text


def groq_completion(system_prompt, user_prompt, temperature, max_tokens):
    if not groq_clients:
        raise RuntimeError("No Groq API key is configured.")

    global groq_key_index
    with groq_key_lock:
        start_index = groq_key_index

    last_error = None
    for offset in range(len(groq_clients)):
        client_index = (start_index + offset) % len(groq_clients)
        try:
            response = groq_clients[client_index].chat.completions.create(
                model=GROQ_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            with groq_key_lock:
                groq_key_index = client_index
            return response
        except Exception as error:
            last_error = error
            if not is_groq_quota_error(error):
                raise

    raise GroqQuotaExhaustedError(
        f"All {len(groq_clients)} configured Groq API keys reached their rate limit: {last_error}"
    )


def call_groq_with_prompt(system_prompt, user_prompt):
    last_error = None
    for attempt in range(2):
        try:
            response = groq_completion(
                system_prompt,
                user_prompt,
                temperature=0.3,
                max_tokens=700,
            )
            answer = response.choices[0].message.content
            if answer:
                answer = answer.strip()
                if answer.endswith((".", "!", "?", "؟", "。", "!")):
                    return sanitize_medical_terms(answer)
                repair = groq_completion(
                    "Rewrite the answer as exactly two complete, safe sentences. Answer in the user's language. Do not stop mid-sentence.",
                    f"Repair this incomplete answer:\n{answer}",
                    temperature=0.1,
                    max_tokens=500,
                )
                repaired = repair.choices[0].message.content
                if repaired and repaired.strip().endswith((".", "!", "?", "؟", "。")):
                    return sanitize_medical_terms(repaired.strip())
                return sanitize_medical_terms(answer + ".")
            last_error = "The model returned an empty response."
            user_prompt += "\nReturn a complete answer now, even if brief. Do not return an empty response."
        except Exception as error:
            if isinstance(error, GroqQuotaExhaustedError):
                raise
            last_error = error
            if attempt == 0:
                continue
    raise RuntimeError(f"AI provider error: {last_error}")


class SearchResultParser(HTMLParser):
    """Extract DuckDuckGo result titles, links, and snippets."""

    def __init__(self):
        super().__init__()
        self.results = []
        self.current = None
        self.capture = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class", "").split()
        if tag == "a" and "result__a" in classes:
            self.current = {"title": "", "url": attributes.get("href", "")}
            self.capture = "title"
        elif self.current and tag in {"a", "div"} and "result__snippet" in classes:
            self.capture = "snippet"

    def handle_data(self, data):
        if self.current and self.capture:
            self.current[self.capture] += data.strip() + " "

    def handle_endtag(self, tag):
        if self.current and tag == "a" and self.capture == "title":
            self.capture = None
        elif self.current and self.capture == "snippet" and tag == "div":
            self.current["title"] = self.current["title"].strip()
            self.current["snippet"] = self.current.get("snippet", "").strip()
            if self.current["title"] and self.current["url"]:
                self.results.append(self.current)
            self.current = None
            self.capture = None


def search_web(question, limit=5):
    if not WEB_SEARCH_ENABLED:
        return []

    url = "https://html.duckduckgo.com/html/?q=" + quote_plus(f"medical health {question}")
    try:
        request = Request(url, headers={"User-Agent": "ClinicalGuidelineAssistant/1.0"})
        with urlopen(request, timeout=8) as response:
            html = response.read().decode("utf-8", errors="ignore")
        parser = SearchResultParser()
        parser.feed(html)
        if parser.results:
            return parser.results[:limit]

        # Wikipedia's public search API is a dependable fallback when search HTML is blocked.
        api_url = (
            "https://en.wikipedia.org/w/api.php?action=query&list=search"
            "&format=json&utf8=1&srlimit=5&srsearch=" + quote_plus(question)
        )
        api_request = Request(api_url, headers={"User-Agent": "ClinicalGuidelineAssistant/1.0"})
        with urlopen(api_request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
        return [
            {
                "title": item["title"],
                "url": "https://en.wikipedia.org/wiki/" + quote_plus(item["title"].replace(" ", "_")),
                "snippet": re.sub(r"<[^>]+>", "", item.get("snippet", "")),
            }
            for item in data.get("query", {}).get("search", [])[:limit]
        ]
    except Exception as error:
        print(f"[WEB] Search unavailable: {error}", file=sys.stderr)
        return []


def build_web_context(results):
    if not results:
        return "No web results were found."
    return "\n\n".join(
        f"[WEB SOURCE {index}]\nTitle: {item['title']}\nURL: {item['url']}\nSummary: {item.get('snippet', '')}"
        for index, item in enumerate(results, start=1)
    )


def pdf_source_name(item):
    source = item.get("source", "Medical guideline")
    text = " ".join(str(item.get("text", "")).split())
    title = text.split(". ")[0].strip(" -:") if text else "Medical guideline"
    if len(title) < 12 or len(title) > 90:
        title = "Medical guideline"
    return f"{title} ({source}), page {item.get('page', '?')}"


def build_source_list(local_results=None, web_results=None):
    sources = []
    seen = set()
    for item in local_results or []:
        label = pdf_source_name(item)
        if label not in seen:
            seen.add(label)
            filename = Path(str(item.get("source", ""))).name
            page = item.get("page", "")
            url = f"/guidelines/{quote(filename)}#page={page}" if filename.lower().endswith(".pdf") else ""
            sources.append(f"- PDF: {label} - {url}" if url else f"- PDF: {label}")
    for item in web_results or []:
        title = item.get("title", "Web medical source")
        url = item.get("url", "")
        label = f"- Web: {title} - {url}" if url else f"- Web: {title}"
        if label not in seen:
            seen.add(label)
            sources.append(label)
    return "\n".join(sources[:5])


def generate_local_fallback_answer(question, local_results):
    if not local_results:
        if re.search(r"[\u0600-\u06ff]", question):
            return "لا يحتوي دليل الـ PDF المحلي على معلومات كافية للإجابة عن هذا السؤال. إذا كانت الأعراض شديدة أو تتفاقم، اطلب تقييمًا طبيًا عاجلًا."
        return "The local PDF guidelines do not contain enough information to answer this question. If symptoms are severe or worsening, seek urgent medical evaluation."

    query_terms = set(re.findall(r"[a-z]{4,}|[\u0600-\u06ff]{3,}", retrieval_query(question).lower()))
    metadata_terms = (
        "active ingredient", "active moiety", "inactive ingredients", "unii:",
        "marketing information", "marketing application", "labeler", "establishment",
        "packaging item", "ndc:", "revised:", "business operations",
    )
    candidate_sentences = []
    for item in local_results[:3]:
        text = " ".join(str(item.get("text", "")).split())
        for sentence in re.split(r"(?<=[.!?؟])\s+|\n+", text):
            sentence = sentence.strip(" -:;")
            lowered = sentence.lower()
            if len(sentence) < 35 or any(term in lowered for term in metadata_terms):
                continue
            overlap = sum(1 for term in query_terms if term in lowered)
            if overlap:
                candidate_sentences.append((overlap, sentence))

    candidate_sentences.sort(key=lambda item: item[0], reverse=True)
    excerpt = " ".join(sentence for _, sentence in candidate_sentences[:3]).strip()
    if not excerpt:
        if re.search(r"[\u0600-\u06ff]", question):
            return "لم أجد في مقتطفات دليل الـ PDF المحلي معلومات طبية مرتبطة بهذا السؤال. إذا كانت الأعراض شديدة أو تتفاقم، اطلب تقييمًا طبيًا عاجلًا."
        return "I could not find a relevant medical passage for this question in the local PDF guidelines. If symptoms are severe or worsening, seek urgent medical evaluation."

    words = excerpt.split()
    if len(words) > 120:
        excerpt = " ".join(words[:120]).rstrip(" ,;:") + "."

    if re.search(r"[\u0600-\u06ff]", question):
        return f"وفقًا للمقتطفات المتاحة من دليل الـ PDF المحلي:\n- {excerpt}"
    return f"According to the available local PDF guideline passages:\n- {excerpt}"


def build_web_search_link(question):
    return "https://duckduckgo.com/?q=" + quote_plus(f"medical health {question}")


def wants_sources(question):
    source_terms = (
        "مصدر", "مصادر", "مرجع", "مراجع", "دليل", "المراجع",
        "source", "sources", "reference", "references", "guideline",
        "citation", "citations",
    )
    normalized = normalize_question(question).lower()
    return any(term in normalized for term in source_terms)


def generate_fallback_answer(question, profile, history, web_results=None):
    recent_history = []
    for message in history[-2:]:
        recent_history.append(f"{message['role'].upper()}: {message['text']}")

    history_text = "\n".join(recent_history) if recent_history else "None"
    user_prompt = f"""{profile_context(profile)}

HISTORY: {history_text}

Q: {question}

Web search results:
{build_web_context(web_results or [])}

Answer helpfully using the web summaries when available, otherwise general medical knowledge. If the issue may be urgent or dangerous, advise immediate medical evaluation. Never invent citations or claim a source says something that is not in its summary."""

    fallback_system = """
You are a careful medical assistant.
Answer in the same language as the user.
Use web summaries when provided; otherwise use general medical knowledge.
Give a clear, useful answer in 3-6 short bullets or paragraphs.
If the case might be urgent or dangerous, recommend immediate medical attention.
Be transparent that local guideline data was not found and the answer is based on general medical guidance.
Do not mention sources that are not provided in the prompt.
"""

    return call_groq_with_prompt(fallback_system, user_prompt)


def generate_direct_answer(question, profile, history, local_results=None, web_results=None):
    recent_history = [
        f"{message['role'].upper()}: {message['text']}"
        for message in history[-8:]
    ]
    history_text = "\n".join(recent_history) if recent_history else "None"
    user_prompt = f"""{profile_context(profile)}

CONVERSATION:
{history_text}

USER QUESTION:
{question}

RETRIEVED PDF PASSAGES (PRIMARY EVIDENCE):
{build_context(local_results) if local_results else "No relevant PDF passage was retrieved."}

WEB MEDICAL SUMMARIES (SECONDARY EVIDENCE):
{build_web_context(web_results or []) if web_results else "No web summaries were retrieved."}

Use the PDF passages first and inspect them carefully. Use the web summaries only to fill gaps when the PDFs do not contain enough detail. Clearly distinguish information supported by the PDF from information supported by web summaries. If neither source answers the question, give a concise, safe answer from general medical knowledge and say that the exact detail was not found. Never invent or cite sources that are not provided."""
    language = "Arabic" if re.search(r"[\u0600-\u06ff]", question) else "English"
    language_system = f"{SYSTEM_PROMPT}\n\nLANGUAGE REQUIREMENT: Answer entirely in {language}. Do not switch languages unless a medical term has no clear translation."
    return call_groq_with_prompt(language_system, user_prompt)


def generate_answer(
    question,
    profile,
    history
):
    if groq_client is None:
        return "GROQ_API_KEY is not configured. Please add it to your .env file."

    question = normalize_question(question)

    if not is_respiratory_question(question):
        return (
            "هذا الشات مخصص لمشاكل التنفس والصدر فقط، مثل الكحة وضيق النفس والربو. "
            "اكتب سؤالك عن عرض تنفسي لأساعدك."
        )

    try:
        results = search_guidelines(retrieval_query(question), TOP_K)
    except Exception as error:
        print(f"[RAG] Local search unavailable: {error}", file=sys.stderr)
        results = []
    relevant_results = [
        item for item in results
        if item.get("score", 0) >= LOCAL_SCORE_THRESHOLD
    ]

    show_sources = wants_sources(question)

    if ANSWER_MODE == "direct":
        best_local_score = max((item.get("score", 0) for item in relevant_results), default=0)
        web_results = []
        if WEB_SEARCH_ENABLED and (not relevant_results or best_local_score < WEB_FALLBACK_SCORE_THRESHOLD):
            web_results = search_web(question)
        try:
            answer = generate_direct_answer(question, profile, history, relevant_results, web_results)
        except GroqQuotaExhaustedError:
            answer = generate_local_fallback_answer(question, relevant_results)
        denial_terms = ("do not contain", "no information", "don't contain", "لا تحتوي", "لا تتضمن", "لا يوجد معلومات")
        if relevant_results and any(term in answer.lower() for term in denial_terms):
            answer = generate_local_fallback_answer(question, relevant_results)
        sources = build_source_list(relevant_results, web_results)
        if sources:
            answer += "\n\nSources\n" + sources
        return answer

    if not relevant_results:
        web_results = search_web(question) if show_sources else []
        answer = generate_fallback_answer(question, profile, history, web_results)
        note = "\n\nNote: No exact match was found in the local guideline database."
        if web_results and show_sources:
            note += " Web summaries were used and should be verified with a qualified clinician."
        return answer + note

    recent_history = [
        f"{message['role'].upper()}: {message['text']}"
        for message in history[-4:]
    ]
    history_text = "\n".join(recent_history) if recent_history else "None"
    context = build_context(relevant_results)
    user_prompt = f"""{profile_context(profile)}

HISTORY:
{history_text}

QUESTION: {question}

LOCAL MEDICAL GUIDELINES:
{context}"""

    try:
        answer = call_groq_with_prompt(SYSTEM_PROMPT, user_prompt)
    except GroqQuotaExhaustedError:
        answer = generate_local_fallback_answer(question, relevant_results)
    sources = build_source_list(relevant_results)
    if sources:
        answer += "\n\nSources\n" + sources
    return answer


# =========================================================
# AUTH ROUTES
# =========================================================

@app.post("/auth/signup")
def auth_signup():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", "")).strip()
    name = str(data.get("name", "")).strip()

    if not email or not password or not name:
        return jsonify({"success": False, "error": "Email, password and name are required."}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE email = ?", (email,))
    if c.fetchone():
        conn.close()
        return jsonify({"success": False, "error": "This email is already registered."}), 409

    user_id = "user-" + uuid.uuid4().hex
    now = datetime.utcnow().isoformat()
    c.execute(
        "INSERT INTO users (id, email, password_hash, name, created_at, last_login) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, email, hash_password(password), name, now, now),
    )
    c.execute(
        "INSERT INTO user_profiles (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (user_id, name, now, now),
    )
    conn.commit()
    conn.close()

    token = create_session_for_user(user_id)
    response = jsonify({"success": True, "user": {"id": user_id, "email": email, "name": name}})
    return set_session_cookie(response, token)


@app.post("/auth/login")
def auth_login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", "")).strip()

    if not email or not password:
        return jsonify({"success": False, "error": "Email and password are required."}), 400

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, password_hash FROM users WHERE email = ?", (email,))
    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"success": False, "error": "No account found for this email. Please create an account first."}), 401

    user_id, name, password_hash = row
    if password_hash != hash_password(password):
        return jsonify({"success": False, "error": "Incorrect email or password."}), 401

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    token = create_session_for_user(user_id)
    response = jsonify({"success": True, "user": {"id": user_id, "email": email, "name": name}})
    return set_session_cookie(response, token)


@app.post("/auth/logout")
def auth_logout():
    token = request.cookies.get("session_token")
    if token:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT user_id FROM user_sessions WHERE token = ?", (token,))
        session_row = c.fetchone()
        c.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
        if session_row and str(session_row[0]).startswith("guest-"):
            c.execute("DELETE FROM user_profiles WHERE id = ?", (session_row[0],))
            c.execute("DELETE FROM users WHERE id = ?", (session_row[0],))
        conn.commit()
        conn.close()
    response = jsonify({"success": True})
    return clear_session_cookie(response)


@app.post("/auth/guest")
def auth_guest():
    user_id = "guest-" + uuid.uuid4().hex
    now = datetime.utcnow().isoformat()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO users (id, email, password_hash, name, created_at, last_login) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, None, "", "Guest", now, now),
    )
    conn.commit()
    conn.close()
    token = create_session_for_user(user_id)
    response = jsonify({"success": True, "user": {"id": user_id, "email": "", "name": "Guest", "guest": True}})
    return set_session_cookie(response, token)


@app.get("/auth/me")
def auth_me():
    user = get_session_user()
    if not user:
        return jsonify({"logged_in": False})
    return jsonify({"logged_in": True, "user": user})


@app.get("/usage")
def usage():
    user = get_session_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    usage_date = datetime.utcnow().date().isoformat()
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT message_count FROM user_daily_usage WHERE user_id = ? AND usage_date = ?",
        (user["id"], usage_date),
    ).fetchone()
    conn.close()
    return jsonify({
        "success": True,
        "used": row[0] if row else 0,
        "limit": USER_DAILY_MESSAGE_LIMIT,
    })


# =========================================================
# FRONTEND
# =========================================================

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/guidelines/<path:filename>")
def guideline_file(filename):
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.lower().endswith(".pdf"):
        return jsonify({"error": "Guideline file not found."}), 404
    return send_from_directory(BASE_DIR / "data", safe_name)


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
def health_route():

    return jsonify(
        health()
    )


# =========================================================
# BUILD QDRANT INDEX
# =========================================================

@app.post("/index")
def index_route():

    data = (
        request
        .get_json(
            silent=True
        )
        or {}
    )

    force = bool(
        data.get(
            "force",
            False
        )
    )

    try:

        points = build_index(
            force=force
        )

        return jsonify(
            {
                "success": True,
                "points": points,
            }
        )

    except Exception as e:

        return jsonify(
            {
                "success": False,
                "error": str(e),
            }
        ), 500


# =========================================================
# NEW CHAT
# =========================================================

@app.post("/new_chat")
def new_chat():
    user = get_session_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    chat_id = "chat-" + uuid.uuid4().hex
    chat = {
        "id": chat_id,
        "title": "New conversation",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "messages": [],
    }

    with lock:
        chats[chat_id] = chat

    if user["id"].startswith("guest-"):
        return jsonify({"success": True, "chat_id": chat_id})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO user_chats (user_id, chat_id, title, messages_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user["id"], chat_id, chat["title"], json.dumps(chat["messages"]), chat["created_at"], chat["updated_at"]),
    )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "chat_id": chat_id})


@app.get("/chats")
def chats_route():
    user = get_session_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    if user["id"].startswith("guest-"):
        return jsonify({"success": True, "chats": []})

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT chat_id, title, created_at, updated_at FROM user_chats WHERE user_id = ? AND messages_json != '[]' ORDER BY updated_at DESC",
        (user["id"],),
    ).fetchall()
    conn.close()
    return jsonify({
        "success": True,
        "chats": [
            {"id": row[0], "title": row[1], "created_at": row[2], "updated_at": row[3]}
            for row in rows
        ],
    })


# =========================================================
# GET CHAT HISTORY
# =========================================================

@app.get("/history/<chat_id>")
def history(chat_id):
    user = get_session_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    chat = get_chat(chat_id)
    if user["id"].startswith("guest-"):
        return jsonify({"chat_id": chat_id, "title": chat["title"], "messages": chat["messages"]})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT title, messages_json FROM user_chats WHERE user_id = ? AND chat_id = ?",
        (user["id"], chat_id),
    )
    row = c.fetchone()
    conn.close()

    if row:
        chat["title"] = row[0]
        chat["messages"] = json.loads(row[1] or "[]")

    return jsonify({"chat_id": chat_id, "title": chat["title"], "messages": chat["messages"]})


# =========================================================
# CHAT
# =========================================================

@app.post("/chat")
def chat():
    user = get_session_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()
    chat_id = str(data.get("chat_id", "")).strip()
    profile = data.get("profile") or {}

    if not message:
        return jsonify({"error": "Message is empty."}), 400

    quota_allowed, message_count = consume_user_message_quota(user["id"])
    if not quota_allowed:
        if re.search(r"[\u0600-\u06ff]", message):
            limit_message = f"تم الوصول إلى حدك اليومي: {USER_DAILY_MESSAGE_LIMIT} رسالة. حاول مرة أخرى غدًا."
        else:
            limit_message = f"You reached your daily limit of {USER_DAILY_MESSAGE_LIMIT} messages. Please try again tomorrow."
        return jsonify({
            "success": True,
            "daily_limit_exhausted": True,
            "used_messages": message_count,
            "daily_limit": USER_DAILY_MESSAGE_LIMIT,
            "response": limit_message,
        })

    if not chat_id:
        chat_id = "chat-" + uuid.uuid4().hex

    chat = get_chat(chat_id)
    add_message(chat_id, "user", message)

    try:
        answer = generate_answer(message, profile, chat["messages"])
        add_message(chat_id, "bot", answer)

        if not user["id"].startswith("guest-"):
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute(
                "INSERT INTO user_chats (user_id, chat_id, title, messages_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, chat_id) DO UPDATE SET title = excluded.title, messages_json = excluded.messages_json, updated_at = excluded.updated_at",
                (user["id"], chat_id, chat["title"], json.dumps(chat["messages"]), chat["created_at"], chat["updated_at"]),
            )
            conn.commit(); conn.close()

        return jsonify({"success": True, "chat_id": chat_id, "response": answer})
    except Exception as e:
        print(f"[CHAT] Request failed: {e}", file=sys.stderr)
        if isinstance(e, GroqQuotaExhaustedError):
            if re.search(r"[\u0600-\u06ff]", message):
                error_message = "تم الوصول إلى الحد اليومي لمفاتيح الذكاء الاصطناعي المتاحة حاليًا. جرّب مرة أخرى لاحقًا."
            else:
                error_message = "The daily limit for the available AI keys has been reached. Please try again later."
            add_message(chat_id, "bot", error_message)
            return jsonify({"success": True, "quota_exhausted": True, "chat_id": chat_id, "response": error_message})
        error_message = "I couldn't complete the request right now. Please try again in a moment."
        add_message(chat_id, "bot", error_message)
        return jsonify({"success": False, "chat_id": chat_id, "response": error_message}), 500


# =========================================================
# DELETE CHAT
# =========================================================

@app.post("/delete_chat/<chat_id>")
def delete_chat(chat_id):
    user = get_session_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    with lock:
        if chat_id in chats:
            del chats[chat_id]

    if user["id"].startswith("guest-"):
        return jsonify({"success": True, "message": "Guest chat deleted"})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM user_chats WHERE user_id = ? AND chat_id = ?", (user["id"], chat_id))
    conn.commit(); conn.close()

    return jsonify({"success": True, "message": "Chat deleted"})


# =========================================================
# PROFILE SAVE/LOAD
# =========================================================

@app.post("/profile/save")
def profile_save():
    user = get_session_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    profile = data.get("profile") or {}
    if user["id"].startswith("guest-"):
        return jsonify({"success": True, "message": "Guest profile is temporary"})
    now = datetime.utcnow().isoformat()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """INSERT INTO user_profiles (id, name, age, gender, blood_group, medical_history, medications, photo_path, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            age = excluded.age,
            gender = excluded.gender,
            blood_group = excluded.blood_group,
            medical_history = excluded.medical_history,
            medications = excluded.medications,
            photo_path = excluded.photo_path,
            updated_at = excluded.updated_at""",
        (
            user["id"],
            profile.get("name"),
            profile.get("age"),
            profile.get("gender"),
            profile.get("blood_group"),
            profile.get("medical_history"),
            profile.get("medications"),
            profile.get("photo"),
            now,
            now,
        ),
    )
    c.execute("UPDATE users SET name = ? WHERE id = ?", (profile.get("name") or user["name"], user["id"]))
    conn.commit(); conn.close()
    return jsonify({"success": True, "message": "Profile saved"})


@app.get("/profile/load")
@app.get("/profile/load/<user_id>")
def profile_load(user_id=None):
    user = get_session_user()
    if not user:
        return jsonify({"success": False, "profile": {}})

    target_user = user_id or user["id"]
    if target_user != user["id"]:
        return jsonify({"success": False, "profile": {}})

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT name, age, gender, blood_group, medical_history, medications, photo_path FROM user_profiles WHERE id = ?",
        (target_user,),
    )
    row = c.fetchone()
    conn.close()

    if row:
        profile = {
            "name": row[0],
            "age": row[1],
            "gender": row[2],
            "blood_group": row[3],
            "medical_history": row[4],
            "medications": row[5],
            "photo": row[6],
        }
        return jsonify({"success": True, "profile": profile})

    return jsonify({"success": True, "profile": {}})


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")  # Listen on all interfaces for cloud deployment
    port = int(os.getenv("PORT", os.getenv("FLASK_PORT", "5000")))  # Railway uses PORT env var
    debug = os.getenv("FLASK_ENV") == "development"  # Only debug in development
    app.run(host=host, port=port, debug=debug)