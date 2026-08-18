# Suppress TensorFlow warnings and disable oneDNN for compatibility
import os
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

import uuid
import sqlite3
import json
import re
import hashlib
from datetime import datetime
from pathlib import Path
from threading import Lock

from flask import Flask, jsonify, render_template, request
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
load_dotenv(BASE_DIR / ".env")

# Debug startup info
import sys
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

    conn.commit()
    conn.close()


init_db()

# =========================================================
# GROQ
# =========================================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "mixtral-8x7b-32768"  # Changed from llama-3.3-70b-versatile
)

if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)
else:
    groq_client = None

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

    return {"id": row[0], "email": row[1], "name": row[2]}


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
You are a concise medical assistant.

Respond in the same language as the user.

Hard rules:
1. Use only the retrieved medical guidelines when available.
2. If no guideline matches, say so briefly and answer with general medical guidance only.
3. Keep the response extremely short: max 3 short lines, or 2 bullets maximum.
4. Do not repeat the same idea, do not ramble, and do not add long explanations.
5. If the case may be urgent or dangerous, advise immediate medical evaluation.
6. Never invent guideline sources, pages, or exact treatment claims.
7. If the user writes Arabic, answer in Arabic.
8. Do not mention the web unless it is explicitly available.

Style: direct, professional, minimal.
Disclaimer: Not a substitute for professional medical advice.
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


def call_groq_with_prompt(system_prompt, user_prompt):
    response = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        temperature=0.2,
        max_tokens=220,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content or "No answer was returned."


def generate_fallback_answer(question, profile, history):
    recent_history = []
    for message in history[-2:]:
        recent_history.append(f"{message['role'].upper()}: {message['text']}")

    history_text = "\n".join(recent_history) if recent_history else "None"
    user_prompt = f"""{profile_context(profile)}

HISTORY: {history_text}

Q: {question}

No guideline data was found for this query. Use general medical knowledge carefully and answer briefly. If the issue may be urgent or dangerous, advise immediate medical evaluation. Do not invent specific guideline citations if none are available. Do not claim to have searched the web if you are only using general knowledge."""

    fallback_system = """
You are a careful medical assistant.
Answer in the same language as the user.
Use only general medical knowledge when no local guideline data is available.
Keep it brief: 1-3 short lines or 2 bullets max.
If the case might be urgent or dangerous, recommend immediate medical attention.
Be transparent that local guideline data was not found and the answer is based on general medical guidance.
Do not claim to have access to the live web unless explicitly available.
"""

    return call_groq_with_prompt(fallback_system, user_prompt)


def generate_answer(
    question,
    profile,
    history
):

    if groq_client is None:

        return (
            "GROQ_API_KEY is not configured. "
            "Please add it to your .env file."
        )

    question = normalize_question(question)

    # -----------------------------------------------------
    # RETRIEVE
    # -----------------------------------------------------

    results = search_guidelines(
        question,
        TOP_K
    )

    context = build_context(
        results
    )

    if not results or not context or "No relevant information" in context:
        answer = generate_fallback_answer(question, profile, history)
        return answer + "\n\nNote: No exact match was found in the local guideline database, so a general medical answer is provided."

    # Limit to last 2 messages to reduce tokens
    recent_history = []
    for message in history[-2:]:
        recent_history.append(
            f"{message['role'].upper()}: "
            f"{message['text']}"
        )

    history_text = (
        "\n".join(recent_history)
        if recent_history
        else "None"
    )

    # MINIMAL PROMPT - Cut tokens aggressively
    user_prompt = f"""{profile_context(profile)}

HISTORY: {history_text}

Q: {question}

Guidelines:
{context}"""

    # -----------------------------------------------------
    # GROQ
    # -----------------------------------------------------

    answer = call_groq_with_prompt(SYSTEM_PROMPT, user_prompt)

    # -----------------------------------------------------
    # SOURCES
    # -----------------------------------------------------

    sources = []

    seen = set()

    for item in results:

        source = item.get("source")
        page = item.get("page")

        key = (
            source,
            page,
        )

        if (
            key not in seen
            and source
        ):

            seen.add(key)

            sources.append(
                f"- {source}, page {page}"
            )

    if sources:

        answer += (
            "\n\nSources\n"
            + "\n".join(
                sources[:5]
            )
        )

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
        c.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    response = jsonify({"success": True})
    return clear_session_cookie(response)


@app.get("/auth/me")
def auth_me():
    user = get_session_user()
    if not user:
        return jsonify({"logged_in": False})
    return jsonify({"logged_in": True, "user": user})


# =========================================================
# FRONTEND
# =========================================================

@app.get("/")
def index():
    return render_template("index.html")


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

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO user_chats (user_id, chat_id, title, messages_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user["id"], chat_id, chat["title"], json.dumps(chat["messages"]), chat["created_at"], chat["updated_at"]),
    )
    conn.commit()
    conn.close()

    return jsonify({"success": True, "chat_id": chat_id})


# =========================================================
# GET CHAT HISTORY
# =========================================================

@app.get("/history/<chat_id>")
def history(chat_id):
    user = get_session_user()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    chat = get_chat(chat_id)
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

    if not chat_id:
        chat_id = "chat-" + uuid.uuid4().hex

    chat = get_chat(chat_id)
    add_message(chat_id, "user", message)

    try:
        answer = generate_answer(message, profile, chat["messages"])
        add_message(chat_id, "bot", answer)

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
        error_message = "I couldn't complete the request.\n\nTechnical details: " + str(e)
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