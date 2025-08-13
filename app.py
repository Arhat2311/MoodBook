from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import requests
import os
import json
from functools import wraps
from datetime import datetime

app = Flask(__name__)

# ---------------- Basic Config ---------------- #
# In production, set this via environment variable
app.secret_key = os.environ.get("BOOKMOOD_SECRET_KEY", "super_secret_key_123")

USERS_FILE = "users.json"

# Prefer environment variable; fallback to the provided key for local dev
API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDTScs9GuMG4pTAiD4sVDRts2U87-1Wmec")

# Model endpoint (requests-style; same as your original code)
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# Titles you don't want to appear
BANNED_TITLES = [
    "The House in the Cerulean Sea",
    "The Midnight Library",
    "Pride and Prejudice"
]

# ---------------- Helper Functions ---------------- #
def load_users():
    """Load simple user store from JSON file."""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # If file is corrupted, start clean (or you can raise)
            return {}
    return {}

def save_users(users):
    """Persist user store to JSON file."""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def try_parse_books_json(text):
    """
    Try to parse a JSON array/object out of the model's text response.
    Returns: list[dict] | None
    """
    if not text:
        return None

    # First, a straight JSON parse
    try:
        data = json.loads(text)
        # Normalize to list
        if isinstance(data, dict) and "recommendations" in data and isinstance(data["recommendations"], list):
            return data["recommendations"]
        if isinstance(data, list):
            return data
    except Exception:
        pass

    # If the model wrapped JSON in ```json ... ```
    fence_start = text.find("```json")
    if fence_start != -1:
        fence_end = text.find("```", fence_start + 7)
        if fence_end != -1:
            fenced = text[fence_start + 7:fence_end].strip()
            try:
                data = json.loads(fenced)
                if isinstance(data, dict) and "recommendations" in data and isinstance(data["recommendations"], list):
                    return data["recommendations"]
                if isinstance(data, list):
                    return data
            except Exception:
                pass

    # Try to extract the largest bracketed JSON array
    lb = text.find("[")
    rb = text.rfind("]")
    if lb != -1 and rb != -1 and rb > lb:
        snippet = text[lb:rb+1]
        try:
            data = json.loads(snippet)
            if isinstance(data, list):
                return data
        except Exception:
            pass

    return None

# ---------------- Routes ---------------- #
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
    return render_template("shelves.html", username=session["username"])

@app.route("/challenges")
def challenges():
    return render_template("challenges.html")

@app.route("/badges")
@login_required
def badges():
    return render_template("badges.html", username=session["username"])

# ---------- Authentication Routes ---------- #
@app.route("/login", methods=["GET", "POST"])
def login():
    # Ensure users file exists to avoid surprises on first run
    if not os.path.exists(USERS_FILE):
        save_users({})

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        users = load_users()
        if username in users and users[username] == password:
            session["username"] = username
            return redirect(url_for("home"))
        else:
            # Render template with an error message (your login.html supports {{ error }})
            return render_template("login.html", error="Invalid username or password")
    # GET
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            return render_template("signup.html", error="Username and password are required")

        users = load_users()
        if username in users:
            return render_template("signup.html", error="Username already exists")

        users[username] = password
        save_users(users)
        session["username"] = username
        return redirect(url_for("home"))

    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------- Book Suggestion Route ---------- #
@app.route("/suggest_book", methods=["POST"])
@login_required
def suggest_book():
    """
    Accepts: JSON { "mood": "..." }
    Returns:
        {
          "books_text": "<raw model text>",
          "books": [  // if we managed to parse JSON
             {"title": "...", "author": "...", "genre": "...", "reason": "..."} , x3
          ]
        }
    """
    data = request.get_json(silent=True) or {}
    mood = (data.get("mood") or "").strip()

    if not mood:
        return jsonify({"error": "Mood not provided"}), 400

    # Prompt updated to request strict JSON, so shelves.html can parse it reliably.
    prompt = f"""
You are a creative and diverse mood-based book recommender.

User's mood: "{mood.upper()}"

Rules:
1) The mood MUST strongly influence the choice of books (tone, genre, themes must fit).
2) DO NOT recommend any of these banned titles (exact match or obvious variants):
   {", ".join(BANNED_TITLES)}.
3) Recommend exactly 3 lesser-known (not bestselling) books, varied in style, setting, or author.
4) The books must be reasonably available in India (but do not include purchase links here).
5) OUTPUT FORMAT: Return ONLY valid JSON (no prose, no markdown, no code fences).
   The JSON must be an object with a single key "recommendations" that is an array of 3 items.
   Each item MUST have the keys: "title", "author", "genre", "reason".
   Example:
   {{
     "recommendations": [
       {{
         "title": "…",
         "author": "…",
         "genre": "…",
         "reason": "1–2 sentences explaining why it matches the mood"
       }},
       ...
     ]
   }}

If you can't follow the rules, still output your best effort as JSON in that exact structure.
"""

    headers = {"Content-Type": "application/json"}
    body = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        resp = requests.post(f"{GEMINI_URL}?key={API_KEY}", headers=headers, json=body, timeout=45)
    except Exception as e:
        return jsonify({"error": f"Upstream model request failed: {e}"}), 502

    try:
        data = resp.json()
    except Exception:
        return jsonify({"error": "Model returned a non-JSON response"}), 502

    if resp.status_code != 200 or "candidates" not in data:
        return jsonify({"error": "Failed to get recommendations"}), 502

    # Raw text from the model (backwards compatible with your existing index.html)
    try:
        books_text = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        books_text = ""

    # Try to parse structured JSON so shelves can use it
    books_json = try_parse_books_json(books_text) or []

    # Hard cap to 3 items if model returned more
    if isinstance(books_json, list) and len(books_json) > 3:
        books_json = books_json[:3]

    return jsonify({
        "books_text": books_text,
        "books": books_json
    })

# ---------- Health (optional) ---------- #
@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "time": datetime.utcnow().isoformat() + "Z",
        "has_api_key": bool(API_KEY)
    })

if __name__ == "__main__":
    # For local testing
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
