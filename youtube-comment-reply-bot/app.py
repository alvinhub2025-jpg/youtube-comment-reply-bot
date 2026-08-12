import os
import time
import secrets
from datetime import datetime
from flask import Flask, redirect, request, session, url_for, render_template_string, flash
import requests

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

SCOPES = "https://www.googleapis.com/auth/youtube.force-ssl"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
YT = "https://www.googleapis.com/youtube/v3"

HOME = r"""
<!doctype html>
<html>
<head>
  <title>YouTube Comment Reply Bot</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body{font-family:Arial,sans-serif;max-width:980px;margin:35px auto;padding:0 18px;background:#f6f7f9;color:#16181d}
    .card{background:white;border:1px solid #ddd;border-radius:14px;padding:22px;margin:16px 0}
    button,.btn{background:#111827;color:white;border:0;border-radius:9px;padding:11px 16px;text-decoration:none;cursor:pointer}
    .danger{background:#b91c1c}.secondary{background:#475569}
    input,textarea,select{width:100%;box-sizing:border-box;padding:10px;margin:6px 0 14px;border:1px solid #cbd5e1;border-radius:8px}
    table{width:100%;border-collapse:collapse;font-size:14px}td,th{padding:9px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
    .ok{color:#166534}.warn{color:#9a3412}.small{font-size:13px;color:#64748b}
  </style>
</head>
<body>
<h1>YouTube Comment Reply Bot</h1>
<p class="small">Replies only to top-level comments where your channel has never replied in that thread.</p>
{% with messages = get_flashed_messages() %}{% if messages %}<div class="card">{% for m in messages %}<p>{{m}}</p>{% endfor %}</div>{% endif %}{% endwith %}
<div class="card">
{% if not connected %}
  <h2>1. Connect YouTube</h2>
  <p>Sign in with the Google account that owns/manages the YouTube channel.</p>
  <a class="btn" href="/login">Connect YouTube</a>
{% else %}
  <h2>Connected: {{channel_title}}</h2>
  <p class="ok">YouTube OAuth connected.</p>
  <a class="btn secondary" href="/logout">Disconnect</a>
{% endif %}
</div>

{% if connected %}
<div class="card">
<h2>2. Scan comments</h2>
<form method="post" action="/scan">
<label>Maximum videos to scan</label>
<input type="number" name="max_videos" min="1" max="5000" value="100">
<label>Maximum eligible comments to collect</label>
<input type="number" name="max_comments" min="1" max="5000" value="500">
<label>Order</label>
<select name="order"><option value="oldest">Oldest to newest</option><option value="newest">Newest to oldest</option></select>
<button type="submit">Scan — do not reply yet</button>
</form>
<p class="small">Scanning does not post replies. Threads where your channel already replied are skipped.</p>
</div>
{% endif %}

{% if candidates %}
<div class="card">
<h2>3. Preview eligible comments ({{candidates|length}})</h2>
<table><tr><th>Date</th><th>Author</th><th>Comment</th><th>Video</th></tr>
{% for c in candidates[:100] %}
<tr><td>{{c.published}}</td><td>{{c.author}}</td><td>{{c.text}}</td><td>{{c.video_id}}</td></tr>
{% endfor %}</table>
{% if candidates|length > 100 %}<p class="small">Showing first 100.</p>{% endif %}
</div>

<div class="card">
<h2>4. Generate/post replies</h2>
<form method="post" action="/reply">
<label>Maximum replies this run</label>
<input type="number" name="limit" min="1" max="1000" value="25">
<label>Reply style / instructions</label>
<textarea name="style" rows="4">Friendly, natural, brief and relevant. Do not argue. Do not mention being AI. Avoid repetitive wording.</textarea>
<label><input style="width:auto" type="checkbox" name="live"> LIVE MODE — actually post replies to YouTube</label>
<p class="warn"><strong>Leave LIVE MODE unticked first.</strong> The first run will only generate a preview.</p>
<button type="submit">Run reply batch</button>
</form>
</div>
{% endif %}

{% if results %}
<div class="card">
<h2>Latest results</h2>
<table><tr><th>Status</th><th>Comment</th><th>Reply</th></tr>
{% for r in results %}<tr><td>{{r.status}}</td><td>{{r.comment}}</td><td>{{r.reply}}</td></tr>{% endfor %}
</table></div>
{% endif %}
</body></html>
"""

def redirect_uri():
    if not BASE_URL:
        return ""
    return BASE_URL + "/oauth2callback"

def token():
    return session.get("token")

def yt_get(path, params=None):
    t = token()
    if not t:
        raise RuntimeError("Not connected to YouTube")
    headers = {"Authorization": f"Bearer {t['access_token']}"}
    r = requests.get(YT + path, params=params or {}, headers=headers, timeout=30)
    if r.status_code == 401 and t.get("refresh_token"):
        refresh_token()
        headers["Authorization"] = f"Bearer {session['token']['access_token']}"
        r = requests.get(YT + path, params=params or {}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def yt_post(path, params=None, payload=None):
    t = token()
    headers = {"Authorization": f"Bearer {t['access_token']}", "Content-Type": "application/json"}
    r = requests.post(YT + path, params=params or {}, json=payload, headers=headers, timeout=30)
    if r.status_code == 401 and t.get("refresh_token"):
        refresh_token()
        headers["Authorization"] = f"Bearer {session['token']['access_token']}"
        r = requests.post(YT + path, params=params or {}, json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

def refresh_token():
    t = session["token"]
    r = requests.post(TOKEN_URL, data={
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": t["refresh_token"],
        "grant_type": "refresh_token",
    }, timeout=30)
    r.raise_for_status()
    new = r.json()
    new["refresh_token"] = t["refresh_token"]
    session["token"] = new

def my_channel():
    data = yt_get("/channels", {"part":"snippet,contentDetails", "mine":"true"})
    item = data["items"][0]
    return item["id"], item["snippet"]["title"], item["contentDetails"]["relatedPlaylists"]["uploads"]

def all_playlist_videos(playlist_id, max_videos):
    out, page = [], None
    while len(out) < max_videos:
        p = {"part":"snippet,contentDetails","playlistId":playlist_id,"maxResults":50}
        if page: p["pageToken"] = page
        data = yt_get("/playlistItems", p)
        for i in data.get("items", []):
            out.append({
                "video_id": i["contentDetails"]["videoId"],
                "published": i["contentDetails"].get("videoPublishedAt", i["snippet"].get("publishedAt",""))
            })
            if len(out) >= max_videos: break
        page = data.get("nextPageToken")
        if not page: break
    return out

def top_comments(video_id):
    out, page = [], None
    while True:
        p = {"part":"snippet","videoId":video_id,"maxResults":100,"order":"time","textFormat":"plainText"}
        if page: p["pageToken"] = page
        r = requests.get(YT + "/commentThreads", params=p,
                         headers={"Authorization":f"Bearer {token()['access_token']}"}, timeout=30)
        if r.status_code == 403:
            return out
        r.raise_for_status()
        data = r.json()
        for th in data.get("items", []):
            s = th["snippet"]
            c = s["topLevelComment"]
            cs = c["snippet"]
            out.append({
                "comment_id": c["id"],
                "video_id": video_id,
                "text": cs.get("textDisplay",""),
                "author": cs.get("authorDisplayName",""),
                "author_channel_id": (cs.get("authorChannelId") or {}).get("value"),
                "published": cs.get("publishedAt",""),
                "total_replies": s.get("totalReplyCount",0)
            })
        page = data.get("nextPageToken")
        if not page: break
    return out

def owner_has_replied(parent_id, owner_channel_id):
    page = None
    while True:
        p = {"part":"snippet","parentId":parent_id,"maxResults":100,"textFormat":"plainText"}
        if page: p["pageToken"] = page
        data = yt_get("/comments", p)
        for c in data.get("items", []):
            aid = (c["snippet"].get("authorChannelId") or {}).get("value")
            if aid == owner_channel_id:
                return True
        page = data.get("nextPageToken")
        if not page: return False

def openai_reply(comment, style):
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing")
    prompt = f"""Write one YouTube creator reply to this viewer comment.

Creator instructions:
{style}

Viewer comment:
{comment}

Return only the reply text. Keep it concise and human-sounding."""
    r = requests.post("https://api.openai.com/v1/responses",
        headers={"Authorization":f"Bearer {OPENAI_API_KEY}","Content-Type":"application/json"},
        json={"model":OPENAI_MODEL,"input":prompt,"max_output_tokens":120}, timeout=45)
    r.raise_for_status()
    data = r.json()
    # Responses API output_text convenience is not guaranteed in raw JSON, so parse output.
    texts = []
    for item in data.get("output", []):
        for part in item.get("content", []):
            if part.get("type") == "output_text":
                texts.append(part.get("text",""))
    return " ".join(texts).strip()

@app.route("/")
def home():
    connected = bool(token())
    title = ""
    if connected:
        try:
            _, title, _ = my_channel()
        except Exception:
            connected = False
            session.pop("token", None)
    return render_template_string(HOME, connected=connected, channel_title=title,
                                  candidates=session.get("candidates",[]),
                                  results=session.get("results",[]))

@app.route("/health")
def health():
    return {"status":"ok"}, 200

@app.route("/login")
def login():
    if not all([GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, BASE_URL]):
        return "Missing GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET or BASE_URL in Railway Variables.", 500
    state = secrets.token_urlsafe(24)
    session["oauth_state"] = state
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri(),
        "response_type":"code",
        "scope":SCOPES,
        "access_type":"offline",
        "prompt":"consent",
        "include_granted_scopes":"true",
        "state":state,
    }
    return redirect(requests.Request("GET", AUTH_URL, params=params).prepare().url)

@app.route("/oauth2callback")
def oauth2callback():
    if request.args.get("state") != session.get("oauth_state"):
        return "OAuth state mismatch.", 400
    if request.args.get("error"):
        return f"Google OAuth error: {request.args.get('error')}", 400
    r = requests.post(TOKEN_URL, data={
        "code":request.args["code"],
        "client_id":GOOGLE_CLIENT_ID,
        "client_secret":GOOGLE_CLIENT_SECRET,
        "redirect_uri":redirect_uri(),
        "grant_type":"authorization_code",
    }, timeout=30)
    if not r.ok:
        return f"Token exchange failed: {r.text}", 400
    session["token"] = r.json()
    return redirect(url_for("home"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/scan", methods=["POST"])
def scan():
    owner_id, _, uploads = my_channel()
    max_videos = min(int(request.form.get("max_videos",100)), 5000)
    max_comments = min(int(request.form.get("max_comments",500)), 5000)
    order = request.form.get("order","oldest")
    videos = all_playlist_videos(uploads, max_videos)
    comments = []
    for v in videos:
        comments.extend(top_comments(v["video_id"]))
    comments.sort(key=lambda x:x["published"], reverse=(order=="newest"))

    eligible = []
    for c in comments:
        if c["author_channel_id"] == owner_id:
            continue
        # If there are no replies at all, the creator definitely has not replied.
        if c["total_replies"] == 0:
            eligible.append(c)
        else:
            if not owner_has_replied(c["comment_id"], owner_id):
                eligible.append(c)
        if len(eligible) >= max_comments:
            break
    session["candidates"] = eligible
    session["results"] = []
    flash(f"Scan complete: {len(eligible)} eligible comments collected. Nothing was posted.")
    return redirect(url_for("home"))

@app.route("/reply", methods=["POST"])
def reply():
    owner_id, _, _ = my_channel()
    limit = min(int(request.form.get("limit",25)), 1000)
    style = request.form.get("style","Friendly, natural and brief.")
    live = request.form.get("live") == "on"
    candidates = session.get("candidates", [])[:limit]
    results = []

    for c in candidates:
        try:
            # Critical second check immediately before posting, preventing duplicate replies
            # if the creator replied after the original scan.
            if c["total_replies"] > 0 and owner_has_replied(c["comment_id"], owner_id):
                results.append({"status":"SKIPPED — already replied","comment":c["text"],"reply":""})
                continue
            reply_text = openai_reply(c["text"], style)
            if live:
                # Re-check again, because generating text takes time.
                if owner_has_replied(c["comment_id"], owner_id):
                    results.append({"status":"SKIPPED — already replied","comment":c["text"],"reply":""})
                    continue
                yt_post("/comments", {"part":"snippet"}, {
                    "snippet":{"parentId":c["comment_id"],"textOriginal":reply_text}
                })
                status = "POSTED"
            else:
                status = "PREVIEW ONLY"
            results.append({"status":status,"comment":c["text"],"reply":reply_text})
            time.sleep(0.15)
        except Exception as e:
            results.append({"status":f"ERROR: {str(e)[:180]}","comment":c["text"],"reply":""})
    session["results"] = results
    return redirect(url_for("home"))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
