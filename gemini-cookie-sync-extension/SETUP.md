# Gemini Cookie Sync Setup

Sign in to Gemini with Gmail, then send cookies to the playground. This extension never asks for your Google password.

Google OAuth tokens are **not** Gemini Web cookies. `SID`, `SAPISID`, and `__Secure-1PSID` are HttpOnly and can only be read with `chrome.cookies`.

## Install

1. Download `gemini-cookie-sync-extension.zip` from the playground (**Get Cookie Sync** or `/extension.zip`) and unzip it, **or** use the `gemini-cookie-sync-extension` folder in this repo.
2. Open `chrome://extensions`
3. Enable **Developer mode**
4. Click **Load unpacked**
5. Select the unzipped `gemini-cookie-sync-extension` folder

## Send cookies to the playground

1. Keep the gemini-web2api playground tab open
2. Click **1. Sign in with Google** in the extension (or the playground button)
3. Sign in with Gmail on Google’s page
4. Open Gemini and refresh if needed
5. Click **2. Send cookies to playground**

The playground Gemini cookie field fills in automatically. Cookies stay in that browser (`localStorage`) and are sent as `X-Gemini-Cookie`. They are not uploaded to git.

You can also **Copy cookie string** or **Export gemini-auth.json**.

## Apply `gemini-auth.json` locally

```bash
python -m gemini_web2api login --from-json gemini-auth.json --output cookie.txt
```

Then run the server with `--cookie-file cookie.txt`, or set `GEMINI_COOKIE` in the Render dashboard. Do not commit `cookie.txt` or `gemini-auth.json`.

## Keep it secret

The cookie string is a live Google session. Do not share it, print it, or commit it to Git.
