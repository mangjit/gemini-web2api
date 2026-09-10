# Gemini Cookie Sync

After you sign in to Gemini with Gmail, this extension **automatically** reads the HttpOnly cookies (`SID`, `SAPISID`, `__Secure-1PSID`) and fills the playground. It never asks for your Google password.

Install once, then Sign in with Google in the playground. Keep the playground tab open.

## Install

1. Download `/extension.zip` from the playground (**Get Cookie Sync**) and unzip it.
2. Open `chrome://extensions`
3. Enable **Developer mode**
4. **Load unpacked** → select `gemini-cookie-sync-extension`

## Use

1. Keep the gemini-web2api playground tab open.
2. Click **Sign in with Google** (playground or this popup).
3. Sign in with Gmail on Google’s page.
4. Return to the playground — the cookie field fills by itself.

That cookie is what Gemini Web needs for **images, PDFs, video, and coding/Pro routing**. Text chat can work without it; file chat cannot.

Manual **Send now** / **Copy** / **Export gemini-auth.json** are backups.

Do not share or commit the cookie string.
