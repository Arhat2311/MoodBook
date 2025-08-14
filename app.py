# app.py
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from functools import wraps
from datetime import datetime
import os
import requests
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import json

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super_secret_key_123")  # change in production

# Gemini settings
API_KEY = os.environ.get("GEMINI_API_KEY",)  # set in Render / environment for deployment
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# Database file
DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")

# Banned list (example)
BANNED_TITLES = [
    "The House in the Cerulean Sea",
    "The Midnight Library",
    "Pride and Prejudice"
]


# --------------------- Database helpers ---------------------
def get_conn():
    # Use check_same_thread=False if you share connection across threads (we create per-request)
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS shelves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            mood TEXT,
            books_text TEXT,
            created_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    conn.commit()
    conn.close()


def find_user_by_username(username):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, username, password_hash FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    return row  # None or tuple


def create_user(username, password_plain):
    password_hash = generate_password_hash(password_plain)
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
        conn.commit()
        user_id = c.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return None
    conn.close()
    return user_id


def save_shelf_entry(username, mood, books_text):
    user = find_user_by_username(username)
    if not user:
        return False
    user_id = user[0]
    created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO shelves (user_id, mood, books_text, created_at) VALUES (?, ?, ?, ?)",
        (user_id, mood, books_text, created_at),
    )
    conn.commit()
    conn.close()
    return True


def get_shelves_for_user(username, limit=50):
    user = find_user_by_username(username)
    if not user:
        return []
    user_id = user[0]
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "SELECT mood, books_text, created_at FROM shelves WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    )
    rows = c.fetchall()
    conn.close()
    return [{"mood": r[0], "books_text": r[1], "date": r[2]} for r in rows]


# Init DB at module import
init_db()


# --------------------- Auth helper / decorator ---------------------
def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


# --------------------- Routes ---------------------
@app.route("/")
@login_required
def home():
    return render_template("index.html", username=session["username"])


@app.route("/about")
@login_required
def about():
    return render_template("about.html", username=session["username"])


@app.route("/shelves")
@login_required
def shelves():
    # server-side rendering: pass shelves to template
    shelves_data = get_shelves_for_user(session["username"])
    return render_template("shelves.html", username=session["username"], shelves=shelves_data)


@app.route("/challenges")
def challenges():
    return render_template("challenges.html")


@app.route("/badges")
@login_required
def badges():
    return render_template("badges.html", username=session["username"])


# --------------------- Auth routes ---------------------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            return render_template("signup.html", error="Please provide username and password")

        # try create
        created_id = create_user(username, password)
        if not created_id:
            return render_template("signup.html", error="Username already exists")

        # auto-login
        session["username"] = username
        return redirect(url_for("home"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return render_template("login.html", error="Please enter username and password")

        user = find_user_by_username(username)
        if not user:
            return render_template("login.html", error="Invalid username or password")

        user_id, user_name, password_hash = user
        if not check_password_hash(password_hash, password):
            return render_template("login.html", error="Invalid username or password")

        session["username"] = username
        return redirect(url_for("home"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# --------------------- Gemini & Suggest Book ---------------------
def call_gemini(prompt_text, timeout=30):
    if not API_KEY:
        raise RuntimeError("Gemini API key is not configured in GEMINI_API_KEY environment variable")

    headers = {"Content-Type": "application/json"}
    body = {"contents": [{"parts": [{"text": prompt_text}]}]}
    resp = requests.post(f"{GEMINI_URL}?key={API_KEY}", headers=headers, json=body, timeout=timeout)

    # Provide helpful error on non-200
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API returned {resp.status_code}: {resp.text}")

    return resp.json()


@app.route("/suggest_book", methods=["POST"])
@login_required
def suggest_book():
    data = request.get_json(silent=True) or {}
    mood = (data.get("mood") or "").strip()
    if not mood:
        return jsonify({"error": "Mood not provided"}), 400

    prompt = f"""
You are a creative and diverse mood-based book recommender.

    The user's mood is: {mood.upper()}.

    Instructions:
    1. The mood MUST strongly influence the choice of books — the genre, tone, and themes must clearly match the mood.
    2. Avoid any books from this banned list: {', '.join(BANNED_TITLES)}. The book should be clearly available in India
    3. Give 3 unique and random book recommendations that have not appeared in your previous answer, and are not much known or heard about, definitely not bestsellers.
    4. Each recommendation should include:
       - Title
       - Author
       - Genre
       - 1–2 sentence description explaining why it matches the mood.
    5. Be creative — avoid generic bestsellers unless they perfectly fit the mood.
    6. Make sure the recommendations are varied in setting, style, or author.
    7. Suggest a book for me with the following details: 

"""

    try:
        gemini_json = call_gemini(prompt)
    except Exception as e:
        return jsonify({"error": f"Gemini call failed: {str(e)}"}), 500

    # Try to extract the textual content from expected structure
    try:
        books_text = gemini_json["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        # fallback: return entire response as text for debugging
        return jsonify({"error": "Unexpected Gemini response structure", "raw": gemini_json}), 500

    # Save raw books_text to DB
    try:
        saved = save_shelf_entry(session["username"], mood, books_text)
        saved_flag = bool(saved)
    except Exception as e:
        # don't fail entire request on DB problem; return the recommendation but mark saved false
        saved_flag = False

    return jsonify({"books_text": books_text, "saved": saved_flag})


# --------------------- API endpoints ---------------------
@app.route("/api/shelves")
@login_required
def api_shelves():
    shelves = get_shelves_for_user(session["username"])
    return jsonify({"shelves": shelves})


# --------------------- run ---------------------
if __name__ == "__main__":
    # for local dev you can set GEMINI_API_KEY in env or leave blank (Gemini calls will fail)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)


