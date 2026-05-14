import os
import re
import socket
import yt_dlp
import requests
from flask import Flask, request, jsonify, send_from_directory
from urllib.parse import quote, unquote
from mega import Mega

# --- CONFIGURATION ---
PORT = 8000
MACRODROID_URL = "https://trigger.macrodroid.com/bf96afee-13f7-47ef-bc9d-e370ad48108a/autodownload"
TEMP_DIR = "downloads"

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

app = Flask(__name__)
mega = Mega()
m = mega.login()

state = {
    "last_file": None,
    "mega_handle": None
}

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception: IP = '127.0.0.1'
    finally: s.close()
    return IP

LOCAL_IP = get_ip()

def download_and_upload(youtube_url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{TEMP_DIR}/%(title)s.%(ext)s',
        'noplaylist': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        print(f"[*] Downloading from YouTube...")
        info = ydl.extract_info(youtube_url, download=True)
        base_path = ydl.prepare_filename(info)
        abs_path = os.path.splitext(base_path)[0] + ".mp3"
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
        return "Error: Missing 'url' parameter", 400

    try:
        filename, mega_file = download_and_upload(yt_url)
        state["last_file"] = filename
        state["mega_handle"] = mega_file
        
        # 1. URL for the phone to download the file
        server_download_url = f"http://{LOCAL_IP}:{PORT}/fetch/{quote(filename)}"
        
        # 2. URL for the phone to send the verification report
        server_verify_url = f"http://{LOCAL_IP}:{PORT}/verify"
        
        # 3. Construct MacroDroid Webhook with all 3 parameters
        webhook_params = (
            f"?download_url={quote(server_download_url, safe='')}"
            f"&path={quote(filename)}"
            f"&verify_url={quote(server_verify_url, safe='')}"
        )
        
        print(f"[*] Triggering MacroDroid...")
        print(f"[*] Verify URL sent: {server_verify_url}")
        requests.get(MACRODROID_URL + webhook_params)
        
        return jsonify({
            "status": "success",
            "file": filename,
            "verify_at": server_verify_url
        })
    except Exception as e:
        return str(e), 500

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

