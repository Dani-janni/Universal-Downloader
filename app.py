import os
import shutil
import tempfile
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_file # type: ignore
import yt_dlp # type: ignore

app = Flask(__name__)
BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

# ---------- PORTABLE FFMPEG ----------
FFMPEG_DIR = BASE_DIR / "ffmpeg" / "bin"

# add ffmpeg folder to PATH (runtime only)
os.environ["PATH"] = str(FFMPEG_DIR) + os.pathsep + os.environ["PATH"]
# --------------------------------------


def get_formats(url):
    ydl_opts = {"quiet": True, "skip_download": True, "no_warnings": True}

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    title = info.get("title")
    formats = info.get("formats", []) or []

    simplified = []
    for f in formats:
        filesize = f.get("filesize") or f.get("filesize_approx")
        size_mb = round(filesize / (1024 * 1024), 1) if filesize else None
        height = f.get("height")

        simplified.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "height": height,
            "tbr": f.get("tbr"),
            "size_mb": size_mb,
            "is_dash": bool(f.get("acodec") == "none" or f.get("vcodec") == "none")
        })

    return {"title": title, "formats": simplified}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/formats", methods=["POST"])
def api_formats():
    data = request.json
    url = data.get("url")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        info = get_formats(url)
        formats = info["formats"]

        def pick(h):
            x = [f for f in formats if f["height"] and f["height"] <= h and not f["is_dash"]]
            if x:
                return max(x, key=lambda i: (i["tbr"] or 0))
            return None

        opt360 = pick(360)
        opt720 = pick(720)
        opt1080 = pick(1080)

        return jsonify({
            "success": True,
            "title": info["title"],
            "options": {
                "bestaudio": {"id": "bestaudio", "label": "Audio (MP3)"},
                "360p": {"id": opt360["format_id"], "label": "360p"} if opt360 else None,
                "720p": {"id": opt720["format_id"], "label": "720p"} if opt720 else None,
                "1080p": {"id": opt1080["format_id"], "label": "1080p"} if opt1080 else None,
                "best": {"id": "best", "label": "Best available"},
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.json
    url = data.get("url")
    choice = data.get("choice")

    if not url or not choice:
        return jsonify({"error": "Missing URL or format choice"}), 400

    tmpdir = Path(tempfile.mkdtemp(prefix="ydl_"))
    outtmpl = str(tmpdir / "%(title)s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ffmpeg_location": str(FFMPEG_DIR)   # MOST IMPORTANT
    }

    if choice == "bestaudio":
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        })

    elif choice in ("360p", "720p", "1080p"):
        height = {"360p": 360, "720p": 720, "1080p": 1080}[choice]
        ydl_opts["format"] = f"bestvideo[height<={height}]+bestaudio/best"

    elif choice == "best":
        ydl_opts["format"] = "bestvideo+bestaudio/best"

    else:
        ydl_opts["format"] = choice

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        files = list(tmpdir.iterdir())
        media_files = [f for f in files if f.suffix not in (".part", ".json")]

        file_path = media_files[0]

        return send_file(str(file_path), as_attachment=True, download_name=file_path.name)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
