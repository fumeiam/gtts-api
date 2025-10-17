from flask import Flask, request, jsonify, send_from_directory
from gtts import gTTS
import os
import uuid

app = Flask(__name__)
OUTPUT_DIR = "tts_audio"

os.makedirs(OUTPUT_DIR, exist_ok=True)

@app.route("/")
def home():
    return jsonify({"message": "Ahri TTS API is purring 💋"})

@app.route("/tts")
def tts():
    text = request.args.get("text")
    lang = request.args.get("lang", "en")
    if not text:
        return jsonify({"error": "Missing ?text= parameter"}), 400

    filename = f"{uuid.uuid4()}.mp3"
    filepath = os.path.join(OUTPUT_DIR, filename)

    tts = gTTS(text=text, lang=lang)
    tts.save(filepath)

    url = f"{request.host_url}audio/{filename}"
    return jsonify({"url": url})

@app.route("/audio/<path:filename>")
def serve_audio(filename):
    return send_from_directory(OUTPUT_DIR, filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
