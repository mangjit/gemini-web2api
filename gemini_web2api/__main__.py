"""Entry point: python -m gemini_web2api"""
import argparse
import os

from .config import CONFIG, load_config, find_config
from .models import MODELS
from .gemini import HAS_HTTPX, fetch_latest_bl, load_cookie
from .server import GeminiHandler, ThreadedServer
from . import __version__


def main():
    parser = argparse.ArgumentParser(description="Gemini Web to OpenAI API")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "login"],
                        help="serve the API (default) or login with Google to capture cookies")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--cookie-file", type=str, default=None)
    parser.add_argument("--proxy", type=str, default=None, help="HTTP proxy, e.g. http://127.0.0.1:7890")
    parser.add_argument("--output", type=str, default="cookie.txt",
                        help="Where `login` writes the cookie string (do not commit)")
    parser.add_argument("--from-json", dest="from_json", type=str, default=None,
                        help="Import gemini-auth.json instead of opening a browser")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds to wait for Google sign-in")
    parser.add_argument("--version", action="version", version=f"gemini-web2api {__version__}")
    args = parser.parse_args()

    if args.command == "login":
        from .login import run_login
        raise SystemExit(run_login(output=args.output, from_json=args.from_json, timeout=args.timeout))

    config_path = args.config or os.environ.get("GEMINI_WEB2API_CONFIG") or find_config()
    if config_path:
        load_config(config_path)

    env_port = os.environ.get("PORT")
    if env_port:
        try:
            CONFIG["port"] = int(env_port)
        except ValueError:
            pass

    if args.port:
        CONFIG["port"] = args.port
    if args.cookie_file:
        CONFIG["cookie_file"] = args.cookie_file
    if args.proxy:
        CONFIG["proxy"] = args.proxy

    new_bl = fetch_latest_bl()
    if new_bl:
        CONFIG["gemini_bl"] = new_bl

    port = CONFIG["port"]
    server = ThreadedServer((CONFIG["host"], port), GeminiHandler)
    print(f"gemini-web2api v{__version__}")
    print(f"  Listening:  http://0.0.0.0:{port}")
    print(f"  Playground: http://localhost:{port}/")
    print(f"  Base URL:   http://localhost:{port}/v1")
    print(f"  Models:    {', '.join(MODELS.keys())}")
    cookie_str, _ = load_cookie()
    print(f"  Cookie:    {'yes' if cookie_str else 'none (anonymous)'}")
    print(f"  Proxy:     {CONFIG.get('proxy') or 'system env'}")
    print(f"  Streaming: {'httpx (true streaming)' if HAS_HTTPX else 'urllib (buffered)'}")
    print(f"  Temporary: {'yes' if CONFIG.get('temporary_chats', False) else 'no'}")
    print(f"  BL:        {CONFIG['gemini_bl']}")
    print()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.shutdown()


if __name__ == "__main__":
    main()
