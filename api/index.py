import os
import re
import yt_dlp
import requests
from flask import Flask, request, jsonify, send_from_directory
from urllib.parse import quote, unquote
from mega import Mega
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Vercel allows writing ONLY to /tmp
TEMP_DIR = "/tmp"

mega = Mega()
m = mega.login()

def get_ip(req):
    # On Vercel, we need the public URL of the deployment
    return req.host_url.rstrip('/')

@app.route('/start', methods=['GET'])
def start_process():
    yt_url = request.args.get('url')
    webhook_url = "https://trigger.macrodroid.com/bf96afee-13f7-47ef-bc9d-e370ad48108a/autodownload"
    
    if not yt_url:
        return jsonify({"error": "Missing url"}), 400

    try:
        # 1. yt-dlp configuration for Serverless
        # We use a very fast setting to avoid Vercel timeouts
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{TEMP_DIR}/%(title)s.%(ext)s',
            'noplaylist': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128', # Lower quality = faster processing
            }],
            # Critical: Point to a static ffmpeg if needed, 
            # though many vercel runtimes include it in PATH
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(yt_url, download=True)
            base_path = ydl.prepare_filename(info)
            abs_path = os.path.splitext(base_path)[0] + ".mp3"
            filename = os.path.basename(abs_path)

        # 2. Upload to Mega
        mega_file = m.upload(abs_path)
        
        # 3. Generate Links
        base_url = get_ip(request)
        server_download_url = f"{base_url}/fetch/{quote(filename)}"
        server_verify_url = f"{base_url}/verify"

        # 4. Trigger MacroDroid
        webhook_params = (
            f"?download_url={quote(server_download_url, safe='')}"
            f"&path={quote(filename)}"
            f"&verify_url={quote(server_verify_url, safe='')}"
        )
        
        requests.get(webhook_url + webhook_params)

        return jsonify({
            "status": "success",
            "file": filename,
            "mega_link": m.get_upload_link(mega_file)
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
