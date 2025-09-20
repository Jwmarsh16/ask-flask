# server/app.py
#Flask serves ../client/dist and exposes /api routes

from config import app  # existing Flask app instance
import os
from openai import OpenAI
from flask import request, jsonify, render_template  # ← render_template for SPA fallback
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200  # for Render health checks

# --------------------------- API ROUTES -----------------------------------
@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.get_json(silent=True)
    if not data or "message" not in data:
        return jsonify({"error": "Missing JSON body or 'message' field"}), 400  # validation

    user_message = data.get('message', '')
    model = data.get('model', 'gpt-3.5-turbo')  # default model

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_message}
            ]
        )
        return jsonify({'reply': response.choices[0].message.content})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
# -------------------------------------------------------------------------

# ---------------------- SPA FALLBACK FOR ROUTING -------------------------
# Any non-API 404 returns the built index.html so client-side routes work.
@app.errorhandler(404)
def not_found(_e):
    return render_template("index.html")
# -------------------------------------------------------------------------

if __name__ == '__main__':
    # Local dev convenience; Render will use gunicorn
    app.run(debug=True)
