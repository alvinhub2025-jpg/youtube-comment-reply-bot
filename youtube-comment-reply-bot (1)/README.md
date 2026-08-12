# YouTube Comment Reply Bot — Railway

A clean Railway-first app for replying to YouTube comments that the channel owner has **never replied to**.

## Safety behaviour

- Scans top-level YouTube comments.
- If the channel owner has already replied anywhere in that comment thread, it skips it.
- If another viewer replied but the channel owner did not, it can still be eligible.
- Re-checks before posting to reduce duplicate replies.
- Defaults to preview mode. Replies are posted only when **LIVE MODE** is ticked.
- Can process oldest-to-newest or newest-to-oldest.

## Google Cloud setup

Enable **YouTube Data API v3**.

Create an OAuth 2.0 Client ID of type **Web application**.

After Railway gives you a public domain, for example:

    https://your-service.up.railway.app

set the Google **Authorised redirect URI** to:

    https://your-service.up.railway.app/oauth2callback

The `/oauth2callback` part is required.

## Railway Variables

Add:

    GOOGLE_CLIENT_ID
    GOOGLE_CLIENT_SECRET
    BASE_URL
    OPENAI_API_KEY
    FLASK_SECRET_KEY

Optional:

    OPENAI_MODEL=gpt-4.1-mini

`BASE_URL` is the Railway public URL without a trailing slash.

Do not put secrets in GitHub.

## Railway deployment

This repository deliberately uses a Dockerfile. Railway should detect it automatically, and `railway.toml` explicitly selects the Dockerfile builder.

No custom Start Command is required.
No Root Directory is required.
Do not hard-code port 8501. The app listens on Railway's `$PORT`.

## Quota warning

YouTube Data API quota is separate from OpenAI API usage. Reply creation consumes YouTube API quota, so start with a small batch and confirm your actual Google Cloud quota before attempting thousands of replies.

## First test

1. Deploy to Railway.
2. Generate a Railway public domain.
3. Set `BASE_URL`.
4. Add the exact `BASE_URL/oauth2callback` URI to Google OAuth.
5. Open the app.
6. Connect YouTube.
7. Scan a small number of videos/comments.
8. Run with LIVE MODE **off**.
9. Review generated replies.
10. Only then use LIVE MODE with a small batch.
