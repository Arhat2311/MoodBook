from flask import Flask, render_template, request, jsonify
import requests
import os

app = Flask(__name__)

# Set your Gemini API key here or use an environment variable
API_KEY = os.environ.get("GEMINI_API_KEY")

# Banned books list to avoid repetition
BANNED_TITLES = [
    "The House in the Cerulean Sea",
    "The Midnight Library",
    "Pride and Prejudice"
]

@app.route("/")
def home():
    return render_template("index.html")
@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/suggest_book", methods=["POST"])
def suggest_book():
    data = request.get_json()
    mood = data.get("mood", "").strip()

    if not mood:
        return jsonify({"error": "Mood is required"}), 400

    # Stronger prompt to ensure mood is considered
    prompt = f"""
    You are a creative and diverse mood-based book recommender.

    The user's mood is: {mood.upper()}.

    Instructions:
    1. The mood MUST strongly influence the choice of books — the genre, tone, and themes must clearly match the mood.
    2. Avoid any books from this banned list: {', '.join(BANNED_TITLES)}.
    3. Give 3 unique book recommendations that have not appeared in your previous answer. Ensure that everytime the 3 books are random
    4. Each recommendation should include:
       - Title
       - Author
       - Genre
       - 1–2 sentence description explaining why it matches the mood.
    5. Be creative — avoid generic bestsellers unless they perfectly fit the mood.
    6. Make sure the recommendations are varied in setting, style, or author.
    """

    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {"Content-Type": "application/json"}
    body = {
        "contents": [
            {"parts": [{"text": prompt}]}
        ]
    }

    try:
        response = requests.post(f"{url}?key={API_KEY}", headers=headers, json=body)
        print("Status Code:", response.status_code)
        data = response.json()
        print("Response JSON:", data)

        if response.status_code == 200 and "candidates" in data:
            books_text = data["candidates"][0]["content"]["parts"][0]["text"]
            return jsonify({"books_text": books_text})
        else:
            return jsonify({"error": "Failed to get recommendations"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
