from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import requests
import os
import json
from functools import wraps

app = Flask(__name__)
app.secret_key = "super_secret_key_123"  # Change in production

USERS_FILE = "users.json"
API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyDTScs9GuMG4pTAiD4sVDRts2U87-1Wmec")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
BANNED_TITLES = [
    "The House in the Cerulean Sea",
    "The Midnight Library",
    "Pride and Prejudice"
]

# ---------------- Helper Functions ---------------- #
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, indent=4)

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
    return render_template("shelves.html", username=session["username"])

@app.route("/challenges")
@login_required
def challenges():
    return render_template("challenges.html")

@app.route("/badges")
@login_required
def badges():
    return render_template("badges.html", username=session["username"])

# ---------- Authentication Routes ---------- #
@app.route("/login", methods=["GET", "POST"])
def login_route():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        users = load_users()
        user = users.get(username)
        stored = user.get("password", "") if isinstance(user, dict) else user if isinstance(user, str) else ""

        if username in users and stored == password:
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
    data = request.get_json()
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

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {"Content-Type": "application/json"}
    body = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        response = requests.post(f"{url}?key={API_KEY}", headers=headers, json=body)
        data = response.json()

        if response.status_code == 200 and "candidates" in data:
            books_text = data["candidates"][0]["content"]["parts"][0]["text"]
            return jsonify({"books_text": books_text})
        else:
            return jsonify({"error": "Failed to get recommendations"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)
