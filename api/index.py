import sys

# --- VERCEL COMPATIBILITY PATCH START ---
# This must be at the very top to fix the 'Sequence' ImportError in Python 3.12
import collections
import collections.abc
if not hasattr(collections, 'Sequence'):
    collections.Sequence = collections.abc.Sequence
# --- VERCEL COMPATIBILITY PATCH END ---

import os
import re
import yt_dlp
import requests
from flask import Flask, request, jsonify, send_from_directory
from urllib.parse import quote, unquote
from mega import Mega

app = Flask(__name__)

# Vercel only allows writing to /tmp
TEMP_DIR = "/tmp"

# Initialize Mega (Anonymous for stability)
mega = Mega()
m = mega.login()

state = {
    "last_file": None,
    "mega_handle": None
}

def download_and_upload(youtube_url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{TEMP_DIR}/%(title)s.%(ext)s',
        'noplaylist': True,
        # IMPORTANT: We remove the MP3 postprocessor because Vercel 
        # usually doesn't have FFmpeg. We will upload the raw audio.
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        print(f"[*] Downloading from YouTube...")
        info = ydl.extract_info(youtube_url, download=True)
        abs_path = ydl.prepare_filename(info)
        filename = os.path.basename(abs_path)
        
        print(f"[*] Uploading {filename} to Mega...")
        try:
            mega_file = m.upload(abs_path)
            return filename, mega_file
        except Exception as e:
            print(f"[-] Mega Upload failed: {e}")
            return filename, None

@app.route('/start', methods=['GET'])
def start_process():
    yt_url = request.args.get('url')
    if not yt_url:
        return jsonify({"error": "Missing url"}), 400

    try:
        filename, mega_handle = download_and_upload(yt_url)
        state["last_file"] = filename
        state["mega_handle"] = mega_handle
        
        # On Vercel, use the request host to build URLs
        base_url = request.host_url.rstrip('/')
        server_download_url = f"{base_url}/fetch/{quote(filename)}"
        server_verify_url = f"{base_url}/verify"
        
        # MacroDroid Webhook
        webhook_url = "https://trigger.macrodroid.com/bf96afee-13f7-47ef-bc9d-e370ad48108a/autodownload"
        webhook_params = (
            f"?download_url={quote(server_download_url, safe='')}"
            f"&path={quote(filename)}"
            f"&verify_url={quote(server_verify_url, safe='')}"
        )
        
        requests.get(webhook_url + webhook_params)
        
        return jsonify({
            "status": "success",
            "file": filename,
            "verify_at": server_verify_url
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/fetch/<filename>', methods=['GET'])
def serve_file(filename):
    clean_name = unquote(filename)
    print(f"\n[1/2] PHONE DOWNLOAD IN PROGRESS: {clean_name}")
    return send_from_directory(TEMP_DIR, clean_name)

@app.route('/verify', methods=['POST', 'GET'])
def verify():
    raw_data = request.get_data(as_text=True) if request.method == 'POST' else request.query_string.decode()
    decoded_data = unquote(raw_data)
    
    target = state["last_file"]
    if not target:
        return "No active file to verify", 400

    found_files = re.findall(r'\[(.*?)\]:', decoded_data)

    print("\n" + "="*50)
    print("🏁 VERIFICATION REPORT")
    if target in found_files:
        print(f"✅ SUCCESS: {target} confirmed.")
        
        if state["mega_handle"]:
            try:
                m.delete(state["mega_handle"]['f'][0]['h'])
                print("[*] Deleted from Mega.")
            except: pass
            
        local_path = os.path.join(TEMP_DIR, target)
        if os.path.exists(local_path):
            os.remove(local_path)
            print(f"[*] Deleted local copy.")
            
        state["last_file"] = None
        print("="*50 + "\n")
        return "Verified", 200
    else:
        print(f"❌ FAILED: {target} not found in report.")
        return "Failed", 400


# Required for Vercel
def handler(event, context):
    return app(event, context)

if __name__ == "__main__":
    app.run(debug=True)
