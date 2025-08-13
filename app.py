from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import requests
from functools import wraps
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = "super_secret_key_123"  # Change in production

# ---------------- In-memory "database" ---------------- #
users = {}  # Virtual JSON storage
BANNED_TITLES = [
    "The House in the Cerulean Sea",
    "The Midnight Library",
    "Pride and Prejudice"
]

API_KEY = os.environ.get("GEMINI_API_KEY")  # Set in Render secrets
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# ---------------- Helper Functions ---------------- #
def load_users():
    global users
    return users

def save_users(data):
    global users
    users = data

def ensure_user(users_data, username):
    if username not in users_data:
        users_data[username] = {"password": "", "shelves": []}
    elif "shelves" not in users_data[username]:
        users_data[username]["shelves"] = []
    return users_data

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login_route"))
        return f(*args, **kwargs)
    return decorated_function

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
    users_data = load_users()
    users_data = ensure_user(users_data, session["username"])
    shelves_data = users_data[session["username"]]["shelves"]
    return render_template("shelves.html", username=session["username"], shelves=shelves_data)

@app.route("/badges")
@login_required
def badges():
    return render_template("badges.html", username=session["username"])

# ---------------- Authentication Routes ---------------- #
@app.route("/login", methods=["GET", "POST"])
def login_route():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        users_data = load_users()
        user = users_data.get(username)
        stored = user.get("password", "") if isinstance(user, dict) else ""

        if username in users_data and stored == password:
            users_data = ensure_user(users_data, username)
            users_data[username]["password"] = password
            save_users(users_data)
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

        users_data = load_users()
        if username in users_data:
            return render_template("signup.html", error="Username already exists")

        users_data = ensure_user(users_data, username)
        users_data[username]["password"] = password
        save_users(users_data)
        session["username"] = username
        return redirect(url_for("home"))

    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_route"))

# ---------------- Book Suggestion Route ---------------- #
@app.route("/suggest_book", methods=["POST"])
@login_required
def suggest_book():
    data = request.get_json() or {}
    mood = data.get("mood", "").strip()
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

    headers = {"Content-Type": "application/json"}
    body = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        resp = requests.post(f"{GEMINI_URL}?key={API_KEY}", headers=headers, json=body, timeout=30)
        if resp.status_code != 200:
            return jsonify({"error": f"Gemini API error {resp.status_code}"}), 500

        data = resp.json()
        books_text = data["candidates"][0]["content"]["parts"][0]["text"]

        # Optional: save to shelves
        users_data = load_users()
        users_data = ensure_user(users_data, session["username"])
        entry = {
            "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "mood": mood,
            "books_text": books_text,
            "id": int(datetime.now().timestamp() * 1000)
        }
        users_data[session["username"]]["shelves"].insert(0, entry)
        users_data[session["username"]]["shelves"] = users_data[session["username"]]["shelves"][:50]
        save_users(users_data)

        return jsonify({"books_text": books_text, "saved": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------------- Run App ---------------- #
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
