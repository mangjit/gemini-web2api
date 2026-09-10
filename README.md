# gemini-web2api

<p align="center">
  <img src="logo.png" width="200" alt="gemini-web2api logo">
</p>

[中文文档](README_CN.md)

Convert Google Gemini's web interface into an OpenAI-compatible API. Zero cost, cross-platform, single file.

## Features

- **Optional API Keys**: no auth when `api_keys` is empty, OpenAI-style Bearer auth when configured
- **OpenAI Compatible**: Drop-in replacement for `/v1/chat/completions` and `/v1/models`
- **Tool Calling**: Full function calling support (OpenAI format)
- **Multiple Models**: Flash (3.6), Extended Thinking (20k+ char output), Pro, Auto, Lite
- **Thinking Depth**: Adjustable via `@think=N` suffix (0=deepest, 4=shallowest)
- **Web Search**: Built-in internet access (Gemini's native search)
- **Cross-Platform**: Pure Python, single optional dependency (`httpx` for streaming)
- **Streaming**: SSE streaming support via `httpx`
- **Codex CLI**: Responses API (`/v1/responses`) for OpenAI Codex integration
- **Gemini CLI**: Google native API (`/v1beta/models`) for Gemini CLI compatibility
- **Web Playground**: Built-in chat UI at `/` for browser use after deploy

## Quick Start

```bash
pip install httpx
python gemini_web2api.py
```

Server starts at `http://localhost:8081/v1`.

Open `http://localhost:8081/` in a browser for the built-in chat playground. JSON health lives at `/health`.

## Client Configuration

### Cherry Studio / ChatBox / any OpenAI client

| Field | Value |
|-------|-------|
| Base URL | `http://localhost:8081/v1` |
| API Key | any `api_keys` value from `config.json`; anything if not configured |
| Model | `gemini-3.5-flash-thinking` |

### curl

#### bash / macOS / Linux

```bash
curl http://localhost:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-your-key" \
  -d '{"model":"gemini-3.5-flash","messages":[{"role":"user","content":"Hello!"}]}'
```

#### PowerShell (Windows)

```powershell
curl.exe --% http://127.0.0.1:8081/v1/chat/completions -H "Content-Type: application/json" -H "Authorization: Bearer sk-your-key" -d "{\"model\":\"gemini-3.5-flash\",\"messages\":[{\"role\":\"user\",\"content\":\"Hello!\"}]}"
```

> Note: On Windows PowerShell, use `curl.exe` and `--%` so PowerShell does not reinterpret JSON quoting or curl options.

### OpenAI Python SDK

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8081/v1", api_key="sk-your-key")
resp = client.chat.completions.create(
    model="gemini-3.5-flash-thinking",
    messages=[{"role": "user", "content": "Explain quantum computing"}]
)
print(resp.choices[0].message.content)
```

### Gemini CLI

```bash
export GEMINI_API_KEY=none
export GOOGLE_GEMINI_BASE_URL=http://localhost:8081
gemini
```

Supports Google native API endpoints:
- `GET /v1beta/models` — list models
- `POST /v1beta/models/{model}:generateContent` — non-streaming
- `POST /v1beta/models/{model}:streamGenerateContent` — streaming (SSE)

## Available Models

| Model | Description | Output |
|-------|-------------|--------|
| `gemini-3.6-flash` | All-around model (latest) | ~12k chars |
| `gemini-3.5-flash` | Alias for gemini-3.6-flash | ~12k chars |
| `gemini-3.5-flash-thinking` | Extended thinking, longest output | **~20k chars** |
| `gemini-3.5-flash-thinking-lite` | Adaptive thinking depth | ~15k chars |
| `gemini-3.1-pro` | Advanced math & code (needs cookie) | ~12k chars |
| `gemini-auto` | Auto model selection | varies |
| `gemini-flash-lite` | Fastest answers, lightweight | ~10k chars |

### Thinking Depth

Append `@think=N` to any model name:

```
gemini-3.5-flash-thinking@think=0   # deepest (default)
gemini-3.5-flash-thinking@think=2   # medium
gemini-3.5-flash-thinking@think=4   # shallowest
```

## Sign in with Google (Gemini cookies)

Anonymous access works for some text chats, but Render datacenter IPs and **file chat** need a signed-in `gemini.google.com` session. `gemini-3.1-pro` also needs a **Gemini Advanced** cookie or it silently routes to Flash.

This project never asks for your Gmail password.

### Playground (including Render)

Click **Sign in with Google**. Google’s sign-in page opens so you can enter email and password. Close that window when you are done; this app shows **Signed in**.

Cookies stay in that browser and are sent as `X-Gemini-Cookie`. Also set `GEMINI_COOKIE` in the Render dashboard so API clients work without the playground. Do not commit the cookie.

### Local browser login

On your own computer (needs a display):

```bash
pip install playwright
playwright install chromium
python -m gemini_web2api login
```

Sign in with Gmail in the window that opens. Writes `cookie.txt` (gitignored). Then:

```bash
python -m gemini_web2api --cookie-file cookie.txt
```

Import an extension export without opening a browser:

```bash
python -m gemini_web2api login --from-json gemini-auth.json --output cookie.txt
```

### Manual fallback

DevTools → Application → Cookies → `https://gemini.google.com`, then paste `SID`, `HSID`, `SSID`, `APISID`, `SAPISID`, `__Secure-1PSID` as one `Name=value; …` line.

### Authenticated account path and XSRF token

If the signed-in Gemini page URL contains an account index, such as:

```
https://gemini.google.com/u/1/app/...
```

set `auth_user` to that index. Authenticated web requests may also require the page XSRF token. In the rendered Gemini page source, this token is exposed as `SNlM0e`; pass it as `xsrf_token` in `config.json`. The server sends it as the `at` form field.

Example:

```json
{
  "cookie_file": "/app/cookie.txt",
  "auth_user": "1",
  "xsrf_token": "AOOh0P...",
  "gemini_bl": "boq_assistant-bard-web-server_YYYYMMDD.xx_p0"
}
```

If authenticated requests return HTTP 400 with an `xsrf` error, refresh Gemini Web, update `xsrf_token`, and make sure `auth_user` matches the `/u/<index>/` part of the browser URL.

Pro routing requires **Gemini Advanced** (paid subscription). A free Google account cookie will authenticate but silently fall back to Flash.

## Configuration

Create `config.json` in the same directory:

```json
{
  "port": 8081,
  "host": "0.0.0.0",
  "retry_attempts": 3,
  "retry_delay_sec": 2,
  "request_timeout_sec": 180,
  "gemini_bl": "boq_assistant-bard-web-server_20260716.08_p0",
  "auth_user": null,
  "xsrf_token": null,
  "api_keys": ["sk-your-key"],
  "cookie_file": null,
  "proxy": null,
  "log_requests": true,
  "temporary_chats": false
}
```

Set `temporary_chats` to `true` to use Gemini Web temporary chats instead of
persisting conversations to the account history.

When `api_keys` is `[]`, authentication is disabled. When one or more keys are set, `/v1/*` endpoints require `Authorization: Bearer <key>` or `x-api-key: <key>`.

## Web Playground

Visiting the server root (`/`) opens a chat UI that talks to `/v1/chat/completions` on the same host. Use it after a Render/Docker deploy instead of reading the old JSON status blob.

If `api_keys` is set in `config.json`, paste a key in the sidebar. The Docker example config uses `sk-gemini`.

The playground keeps previous threads in the **Chats** list (this browser’s local storage). **New chat** starts a blank thread without deleting the old one. Use **Export** to download `gemini-web2api-chats.json` and put that file in Google Drive or any folder; **Import** restores it.

Point OpenAI-compatible clients at:

| Field | Value |
|-------|-------|
| Base URL | `https://your-host/v1` |
| API Key | a value from `api_keys`, or anything if unset |
| Model | `gemini-3.6-flash` |

## Deploy on Render

1. New Web Service from this repo (Docker, or Python with `pip install -r requirements.txt`).
2. Start command for native Python: `python -m gemini_web2api`.
3. The process listens on `0.0.0.0` and reads Render's `PORT` env var automatically.
4. After deploy, open the service URL — you should see the playground, not raw JSON.
5. Health check path: `/health`.

### Keep-alive cron URL

Render’s free web service sleeps after idle time. Ping **GET** this URL every 5–10 minutes:

```
https://YOUR-SERVICE.onrender.com/health
```

Example (this deploy):

```
https://gemini-web2api-be17.onrender.com/health
```

Paste that into [cron-job.org](https://cron-job.org), UptimeRobot, or EasyCron:

| Field | Value |
|-------|-------|
| URL | `https://gemini-web2api-be17.onrender.com/health` |
| Method | GET |
| Interval | every 10 minutes |
| Auth | none (`/health` is public) |

This repo also has `.github/workflows/keep-alive.yml` (every 10 minutes). Optional GitHub secret `HEALTH_URL` overrides the default. Enable Actions on the repo, or run the workflow manually once to test.
6. In the Render dashboard → **Environment**, add `GEMINI_COOKIE` (the blueprint leaves it blank on purpose). Value is a `gemini.google.com` cookie string, for example:

```
SID=...; HSID=...; SSID=...; APISID=...; SAPISID=...; __Secure-1PSID=...
```

Note the two underscores in `__Secure-1PSID`. This is **not** an AI Studio API key. Save, then redeploy. Never commit the cookie to git.

`render.yaml` declares `GEMINI_COOKIE` with `sync: false` so Render asks you to fill it in the dashboard.

**Empty replies on Render are expected without cookies.** Google often blocks datacenter IPs for anonymous Gemini Web access. This is the same issue as Docker bridge networking.

To make chat work on Render:

- Click **Sign in with Google** in the playground (cookies collect automatically), or
- Set `GEMINI_COOKIE` in the Render Environment tab (preferred for API clients), or
- Run `python -m gemini_web2api login` on your computer and use `--cookie-file cookie.txt`, or
- Put that string in `config.json` as `"cookie"` / `"cookie_file"`, optionally with a residential `proxy`.

Do **not** use an AI Studio API key. That is a different product.

## Docker

```bash
cp config.example.json config.json
docker build -t gemini-web2api .
docker run -d --name gemini-web2api -p 8081:8081 -v ./config.json:/app/config.json gemini-web2api
```

Or use Docker Compose:

```bash
cp config.example.json config.json
docker compose up -d
```

To mount a cookie file:

```bash
docker run -d --name gemini-web2api -p 8081:8081 -v ./config.json:/app/config.json -v ./cookie.txt:/app/cookie.txt gemini-web2api
```

Set `"cookie_file": "/app/cookie.txt"` in `config.json`.

> **Note**: If you get empty responses (`content: null`) with Docker's default bridge network, switch to host networking: `docker run --network host ...` or add `network_mode: host` in your compose file. This is caused by Gemini's upstream rejecting requests from certain Docker NAT IP ranges.

## Proxy

If you cannot access `gemini.google.com` directly (connection timeout), configure a proxy:

**Method 1: CLI argument**
```bash
python gemini_web2api.py --proxy http://127.0.0.1:7890
```

**Method 2: config.json**
```json
{"proxy": "http://127.0.0.1:7890"}
```

**Method 3: Environment variable** (auto-detected)
```bash
export HTTPS_PROXY=http://127.0.0.1:7890
python gemini_web2api.py
```

Works with Clash, V2Ray, Shadowsocks, or any HTTP proxy.

## Tool Calling

```python
resp = client.chat.completions.create(
    model="gemini-3.5-flash",
    messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
    tools=[{
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get weather for a city",
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}
        }
    }]
)
```

## Image Input

OpenAI-style multimodal messages are supported for Chat Completions and the
Responses API. Use either HTTP(S) image URLs or base64 data URLs:

```python
resp = client.chat.completions.create(
    model="gemini-3.6-flash",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "Describe this image"},
            {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}}
        ]
    }]
)
```

## Limitations

- **Files need a cookie**: Images, PDFs, and video uploads are rejected anonymously. Sign in with Google (Cookie Sync auto-collects cookies) or set `GEMINI_COOKIE`. Text/coding can work without it; files cannot.
- **Not real Pro/Ultra**: Without a paid subscription cookie, `gemini-3.1-pro` routes to the same Flash model. The "Pro" label is a UI preference, not a backend model switch.
- **Single-turn only**: Each request is an independent conversation. Multi-turn context is simulated by including previous messages in the prompt.
- **Rate limits**: Google may throttle high-frequency requests. The server retries automatically but sustained heavy use may be blocked.

## Requirements

- Python 3.8+
- `httpx` (`pip install httpx`) — used for streaming requests
- Network access to `gemini.google.com` (proxy/VPN may be needed in some regions)

## How It Works

This tool reverse-engineers Google Gemini's web StreamGenerate protocol. It sends requests to the same endpoint that the Gemini web app uses, converting between OpenAI's API format and Gemini's internal protobuf-like format.

The model selection is controlled by field `[79]` in the request payload, mapped from Gemini's frontend JavaScript source (`MODE_CATEGORY` enum).

## Acknowledgments

- Inspired by the open-source API proxy ecosystem

## License

MIT

---

## 致谢

本项目的开发 agent 能力由 [GenericAgent](https://github.com/lsdefine/GenericAgent) 提供。

### 🚩 友情链接

[![GenericAgent](https://img.shields.io/badge/Agent_Framework-GenericAgent-orange?style=for-the-badge&logo=github)](https://github.com/lsdefine/GenericAgent)
[![LinuxDo](https://img.shields.io/badge/社区-LinuxDo-blue?style=for-the-badge)](https://linux.do/)
