import os
import json
import base64
from flask import Flask, request, jsonify
import moviepy.editor as mp
from moviepy.editor import VideoFileClip, concatenate_videoclips, clips_array
import speech_recognition as sr
import urllib.request
from firebase_admin import credentials, initialize_app, storage, firestore
from google.cloud.exceptions import NotFound
import tempfile

app = Flask(__name__)

# Load Firebase credentials and storage bucket from environment variables
firebase_credentials = os.getenv("FIREBASE_CREDENTIALS")
firebase_storage_bucket = os.getenv("FIREBASE_STORAGE_BUCKET")

if firebase_credentials:
    # Decode the base64 encoded credentials
    cred = credentials.Certificate(json.loads(
        base64.b64decode(firebase_credentials)))
    initialize_app(cred, {"storageBucket": firebase_storage_bucket})
    db = firestore.client()


def upload_video_to_firebase(video_path, destination_path):
    try:
        bucket = storage.bucket()
        blob = bucket.blob(destination_path)
        blob.upload_from_filename(video_path)
        blob.make_public()
        download_url = blob.public_url
        return download_url
    except NotFound as e:
        print(f"Error: Bucket or path not found - {e}")
        return None
    except Exception as e:
        print(f"Error uploading video - {e}")
        return None


def download_http_video(url, destination):
    try:
        with urllib.request.urlopen(url) as response, open(destination, "wb") as out_file:
            chunk_size = 8192
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
        print(f"Download successful. Content saved to {destination}")
    except Exception as e:
        print(f"Error: {e}")


def merge_letter_videos(word, assets_folder):
    letter_clips = []
    for letter in word:
        letter_lower = letter.lower()
        letter_video_path = os.path.join(assets_folder, f"{letter_lower}.mp4")
        if os.path.isfile(letter_video_path):
            letter_clip = VideoFileClip(letter_video_path)
            letter_clips.append(letter_clip)
        else:
            print(f"No video found for letter: {letter_lower}")
    if not letter_clips:
        print("No valid videos found for the word.")
        return None
    final_clip = concatenate_videoclips(letter_clips)
    return final_clip


def merge_word_videos(words, assets_folder):
    video_clips = []
    for word in words:
        word_lower = word.lower()
        word_video_path = os.path.join(assets_folder, f"{word_lower}.mp4")
        if os.path.isfile(word_video_path):
            video_clip = VideoFileClip(word_video_path)
            video_clips.append(video_clip)
        else:
            print(f"No video found for word: {word_lower}")
            print(f"Splitting '{word}' into letters...")
            letter_video = merge_letter_videos(word, assets_folder)
            if letter_video is not None:
                video_clips.append(letter_video)
    if not video_clips:
        print("No valid videos found.")
        return None
    final_clip = concatenate_videoclips(video_clips)
    return final_clip


def extract_audio_as_text(video_path):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio_file:
            temp_audio_path = temp_audio_file.name
        video = mp.VideoFileClip(video_path)
        audio = video.audio
        audio.write_audiofile(temp_audio_path)
        r = sr.Recognizer()
        with sr.AudioFile(temp_audio_path) as source:
            audio_data = r.record(source)
            audio_text = r.recognize_google(audio_data)
        os.remove(temp_audio_path)
        return audio_text
    except Exception as e:
        print(f"Error processing video: {e}")
        if "temp_audio_path" in locals() and os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
        return None


@app.route("/video_sign", methods=["POST"])
def generate_combined_video():
    data = request.get_json()
    video_url = data.get("url")
    if not video_url:
        return jsonify({"error": "Invalid request. Missing required parameter: url"}), 400

    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_video_file:
        temp_video_path = temp_video_file.name

    download_http_video(video_url, temp_video_path)
    extracted_text = extract_audio_as_text(temp_video_path)
    if extracted_text is None:
        return jsonify({"error": "Failed to extract audio text."}), 500

    assets_folder = "D:/final/final_app/python/assets1"
    words = extracted_text.split()
    if not words:
        return jsonify({"error": "Please enter a valid sentence."}), 400

    video = merge_word_videos(words, assets_folder)
    if video is None:
        return jsonify({"error": "No valid videos found."}), 400

    continuous_video_path = "output_continuous_video.mp4"
    video.write_videofile(continuous_video_path, codec="libx264")

    uploaded_video = VideoFileClip(temp_video_path)
    uploaded_video = uploaded_video.resize(height=video.h)
    final_video = clips_array([[uploaded_video, video]])

    final_video_path = "final_combined_video.mp4"
    final_video.write_videofile(final_video_path, codec="libx264")
    os.remove(continuous_video_path)

    firebase_destination_path = f"videos/final_combined_video_{os.path.basename(temp_video_path)}"
    final_video_url = upload_video_to_firebase(
        final_video_path, firebase_destination_path)
    if final_video_url is None:
        return jsonify({"error": "Failed to upload the final video to Firebase Storage."}), 500

    db.collection("videos").add({"final_video_url": final_video_url})
    response = {"process_completed": True, "final_video_url": final_video_url}
    return jsonify(response), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 3000)))
