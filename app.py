from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import requests
import os
import json
import re
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "super_secret_key_123")

USERS_FILE = "users.json"
API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDTScs9GuMG4pTAiD4sVDRts2U87-1Wmec")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

BANNED_TITLES = {
    "the house in the cerulean sea",
    "the midnight library",
    "pride and prejudice",
}

# ---------------- Helper Functions ---------------- #
def load_users():
    """
    Load users.json, and support both old (username: password) and new structures.
    If old structure found, convert it to new structure and save back.
    """
    if not os.path.exists(USERS_FILE):
        return {}

    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    # Detect legacy format: username -> string password
    converted = False
    if isinstance(data, dict):
        for k, v in list(data.items()):
            if not isinstance(v, dict):
                # convert entry
                pwd = v if isinstance(v, str) else ""
                data[k] = {"password": pwd, "shelves": []}
                converted = True
            else:
                # ensure 'shelves' exists
                if "shelves" not in v:
                    data[k]["shelves"] = []
                    converted = True
    if converted:
        try:
            with open(USERS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    return data

def save_users(users):
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def ensure_user(users, username):
    if username not in users:
        users[username] = {"password": "", "shelves": []}
    elif "shelves" not in users[username]:
        users[username]["shelves"] = []
    return users

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# ---------------- Parsing helpers ---------------- #
def try_load_json(text):
    try:
        return json.loads(text)
    except Exception:
        return None

def extract_json_array(text):
    """
    Highly forgiving extraction:
    1. Try direct json.loads(text)
    2. Find the largest [...] block and attempt to json.loads it
    3. Find fenced ```json ... ``` blocks
    4. Try to parse structured plaintext:
       - Blocks like "Title: X\nAuthor: Y\nGenre: Z\nDescription: ..."
       - Numbered lists: "1. Title — Author [Genre]\n   Description..."
    Returns: list-of-dicts OR None
    """
    if not text or not isinstance(text, str):
        return None

    # 1) direct load
    parsed = try_load_json(text)
    if isinstance(parsed, list):
        return parsed

    # 2) fenced json blocks ```json ... ```
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence:
        candidate = fence.group(1).strip()
        parsed = try_load_json(candidate)
        if isinstance(parsed, list):
            return parsed

    # 3) biggest [...] block
    array_matches = re.findall(r"\[[\s\S]*?\]", text)
    if array_matches:
        # choose the longest candidate (most likely contains all objects)
        best = max(array_matches, key=len)
        parsed = try_load_json(best)
        if isinstance(parsed, list):
            return parsed

    # 4) try to extract multiple object-like patterns 'Title: ... Author: ...'
    blocks = re.split(r"\n\s*\n", text.strip())
    results = []
    for block in blocks:
        # find title/author pairs in the block
        title = None
        author = None
        genre = ""
        description = ""

        # Pattern: Title: <...>
        m_title = re.search(r"Title\s*[:\-]\s*(.+)", block, re.IGNORECASE)
        if m_title:
            title = m_title.group(1).strip()

        m_author = re.search(r"Author\s*[:\-]\s*(.+)", block, re.IGNORECASE)
        if m_author:
            author = m_author.group(1).strip()

        m_genre = re.search(r"Genre\s*[:\-]\s*(.+)", block, re.IGNORECASE)
        if m_genre:
            genre = m_genre.group(1).strip()

        m_desc = re.search(r"Description\s*[:\-]\s*([\s\S]+)", block, re.IGNORECASE)
        if m_desc:
            description = m_desc.group(1).strip()

        if title and author:
            results.append({
                "title": title,
                "author": author,
                "genre": genre,
                "description": description
            })
        else:
            # try numbered list style like "1. Title — Author [Genre]\n   Description..."
            lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
            for i, ln in enumerate(lines):
                m_num = re.match(r"^\d+\.\s*(.+)", ln)
                if m_num:
                    main = m_num.group(1)
                    # split by ' — ' or '-' or ' - ' or ' by '
                    parts = re.split(r"\s+—\s+|\s+-\s+|\s+by\s+", main, maxsplit=1)
                    t = parts[0].strip() if parts else ""
                    a = parts[1].strip() if len(parts) > 1 else ""
                    # optionally extract genre in brackets
                    g = ""
                    gm = re.search(r"\[(.*?)\]", main)
                    if gm:
                        g = gm.group(1).strip()
                    # description on next line(s)
                    desc = ""
                    if i + 1 < len(lines):
                        # if next line is indented or not numeric, treat as description
                        if not re.match(r"^\d+\.", lines[i + 1]):
                            desc = lines[i + 1]
                    if t and a:
                        results.append({"title": t, "author": a, "genre": g, "description": desc})

    if results:
        return results

    return None

def normalize_book_list(items):
    """
    Ensure we return a list of up to 3 book dicts with required keys.
    Filter banned titles and normalize fields.
    """
    out = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        author = (item.get("author") or "").strip()
        genre = (item.get("genre") or "").strip()
        description = (item.get("description") or item.get("desc") or "").strip()

        if not title or not author:
            continue
        if title.lower() in BANNED_TITLES:
            continue

        out.append({
            "title": title,
            "author": author,
            "genre": genre,
            "description": description
        })
        if len(out) == 3:
            break
    return out

# ---------------- Gemini call ---------------- #
def gemini_recommend(mood):
    prompt = f"""
You are an expert mood-based book recommender.

User mood: "{mood}".

Return EXACTLY a JSON array with THREE objects.
Each object MUST have keys: "title", "author", "genre", "description".
Do NOT include markdown, extra text, or code fences. Only valid JSON array.

Rules:
- Titles in this banned list must NOT appear: {sorted(list(BANNED_TITLES))}
- Prefer books available/known in India (not obscure out-of-print).
- Avoid bestsellers and overexposed picks; aim for lesser-known but strong fits to the mood.
- Description: 1–2 sentences on why this fits the mood.
"""
    headers = {"Content-Type": "application/json"}
    body = {"contents": [{"parts": [{"text": prompt}]}]}

    resp = requests.post(f"{GEMINI_URL}?key={API_KEY}", headers=headers, json=body, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini error: {resp.status_code} {resp.text}")

    data = resp.json()
    try:
        raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise RuntimeError("Unexpected Gemini response structure.")

    # First try strict parse, then forgiving extraction
    parsed = extract_json_array(raw_text)
    if parsed:
        books = normalize_book_list(parsed)
        if books:
            return books

    # If parsing failed, try to salvage using more relaxed parsing and also let caller know raw_text
    # Try to parse any JSON-like objects again with lower confidence
    # create fallback by scanning for common Title/Author lines
    fallback = extract_json_array(raw_text)  # second attempt (extract_json_array already forgiving)
    if fallback:
        books = normalize_book_list(fallback)
        if books:
            return books

    # Last resort: try to parse lines like "1. Title — Author"
    # (extract_json_array already handles numbered lists), so if still nothing, give helpful error
    raise RuntimeError("Could not parse JSON from Gemini. Raw output included for debugging.\n\n" + raw_text)

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
    users = load_users()
    users = ensure_user(users, session["username"])
    shelves_data = users[session["username"]]["shelves"]
    return render_template("shelves.html", username=session["username"], shelves=shelves_data)

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
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        users = load_users()
        # support both legacy and new structures
        user = users.get(username)
        if isinstance(user, dict):
            stored = user.get("password", "")
        else:
            stored = user if isinstance(user, str) else ""

        if username in users and stored == password:
            # ensure normalized user structure
            users = ensure_user(users, username)
            users[username]["password"] = password
            save_users(users)
            session["username"] = username
            return redirect(url_for("home"))
        else:
            return render_template("login.html", error="Invalid username or password")
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        users = load_users()
        if username in users:
            return render_template("signup.html", error="Username already exists")

        users = ensure_user(users, username)
        users[username]["password"] = password
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
    data = request.get_json(silent=True) or {}
    mood = (data.get("mood") or "").strip()
    if not mood:
        return jsonify({"error": "Mood not provided"}), 400

    try:
        books = gemini_recommend(mood)  # list of 3 dicts

        # Save immediately to shelves for this user
        users = load_users()
        users = ensure_user(users, session["username"])
        entry = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "mood": mood,
            "books": books,
            "id": int(datetime.now().timestamp() * 1000)
        }
        users[session["username"]]["shelves"].insert(0, entry)
        users[session["username"]]["shelves"] = users[session["username"]]["shelves"][:50]
        save_users(users)

        # Create plain text display
        lines = []
        for i, b in enumerate(books, 1):
            lines.append(f"{i}. {b['title']} — {b['author']} [{b.get('genre','')}]")
            if b.get("description"):
                lines.append(f"   {b['description']}")
        books_text = "\n".join(lines)

        return jsonify({
            "books_text": books_text,
            "saved": True,
            "shelf": entry
        })
    except Exception as e:
        # Return error and raw output in message so frontend can display for debugging
        return jsonify({"error": str(e)}), 500

# --- Optional: JSON API to fetch shelves (if you want SPA usage) --- #
@app.route("/api/shelves")
@login_required
def api_shelves():
    users = load_users()
    users = ensure_user(users, session["username"])
    return jsonify({"shelves": users[session["username"]]["shelves"]})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
