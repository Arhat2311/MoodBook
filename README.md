# MoodBook

BookMood is an AI-powered book recommendation web app built with Flask that suggests books based on your current mood.

## Features
- Mood-based book recommendations
- Gemini API integration
- Responsive UI
- About page with creator details

## Deployment
This project is ready to deploy on Render.

### Steps:
1. Push this folder to a GitHub repository.
2. On Render:
   - Create a new Web Service.
   - Connect your GitHub repo.
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
   - Add environment variable: `GEMINI_API_KEY` with your API key.

Enjoy! 📚
