import http.client
import base64
import json
import threading
import unittest
from unittest import mock
from urllib.parse import parse_qs

import os

from gemini_web2api.config import CONFIG, DEFAULT_CONFIG
from gemini_web2api.gemini import (
    _build_payload,
    clear_request_cookie,
    empty_upstream_message,
    load_cookie,
    normalize_cookie,
    set_request_cookie,
)
from gemini_web2api.multimodal import upload_image
from gemini_web2api.server import GeminiHandler, ThreadedServer
from gemini_web2api.tools import google_contents_to_prompt, messages_to_prompt


def _decode_payload(payload):
    outer = json.loads(parse_qs(payload)["f.req"][0])
    return json.loads(outer[1])


def _decode_sse(body):
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event_type = next(
            (line[len("event: "):] for line in lines if line.startswith("event: ")),
            None,
        )
        data = next(
            (line[len("data: "):] for line in lines if line.startswith("data: ")),
            None,
        )
        if event_type and data:
            events.append((event_type, json.loads(data)))
    return events


class PayloadPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.original_config = dict(CONFIG)

    def tearDown(self):
        CONFIG.clear()
        CONFIG.update(self.original_config)

    def test_temporary_chats_default_to_disabled(self):
        self.assertIs(DEFAULT_CONFIG["temporary_chats"], False)

    def test_empty_upstream_message_mentions_render(self):
        self.assertIn("Render", empty_upstream_message(""))
        self.assertIn("CAPTCHA", empty_upstream_message("Please complete recaptcha"))

    def test_load_cookie_from_env(self):
        CONFIG["cookie_file"] = None
        CONFIG["cookie"] = None
        with mock.patch.dict(os.environ, {"GEMINI_COOKIE": "SID=abc; SAPISID=xyz"}, clear=False):
            cookie_str, sapisid = load_cookie()
        self.assertEqual(cookie_str, "SID=abc; SAPISID=xyz")
        self.assertEqual(sapisid, "xyz")

    def test_normalize_markdown_secure_cookie(self):
        repaired = normalize_cookie("SID=abc; **Secure-1PSID=psid; SAPISID=xyz")
        self.assertIn("__Secure-1PSID=psid", repaired)
        self.assertNotIn("**Secure-", repaired)

    def test_upload_image_requires_cookie(self):
        CONFIG["cookie_file"] = None
        CONFIG["cookie"] = None
        clear_request_cookie()
        with mock.patch.dict(os.environ, {"GEMINI_COOKIE": "", "GEMINI_SAPISID": ""}, clear=False):
            with self.assertRaises(RuntimeError) as ctx:
                upload_image(b"\x89PNG\r\n\x1a\n", "x.png", "image/png")
        self.assertIn("cookie", str(ctx.exception).lower())

    def test_request_cookie_overrides_env(self):
        CONFIG["cookie_file"] = None
        CONFIG["cookie"] = None
        try:
            set_request_cookie("SID=req; SAPISID=fromreq")
            with mock.patch.dict(os.environ, {"GEMINI_COOKIE": "SID=abc; SAPISID=xyz"}, clear=False):
                cookie_str, sapisid = load_cookie()
            self.assertEqual(sapisid, "fromreq")
            self.assertIn("SID=req", cookie_str)
        finally:
            clear_request_cookie()

    def test_persistent_chat_payload(self):
        CONFIG["temporary_chats"] = False

        inner = _decode_payload(_build_payload("hello", 1, 4))

        self.assertEqual(inner[41], [2])
        self.assertIsNone(inner[45])

    def test_temporary_chat_payload(self):
        CONFIG["temporary_chats"] = True

        inner = _decode_payload(_build_payload("hello", 1, 4))

        self.assertEqual(inner[41], [1])
        self.assertEqual(inner[45], 1)

    def test_payload_includes_uploaded_image_refs(self):
        inner = _decode_payload(_build_payload("describe", 1, 4, ["/uploaded/image-ref"]))

        self.assertEqual(inner[0][0], "describe")
        self.assertEqual(
            inner[0][3],
            [[["/uploaded/image-ref", 1, None, "image/png"], "image.png", None, None, None, None, None, None, [0]]],
        )

    def test_payload_includes_image_ref_dict(self):
        inner = _decode_payload(_build_payload("describe", 1, 4, [{
            "ref": "/contrib_service/ttl_1d/abc",
            "name": "photo.jpg",
            "mime": "image/jpeg",
            "kind": 1,
        }]))
        self.assertEqual(
            inner[0][3][0][:2],
            [["/contrib_service/ttl_1d/abc", 1, None, "image/jpeg"], "photo.jpg"],
        )

    def test_empty_upstream_image_message(self):
        msg = empty_upstream_message("", has_files=True)
        self.assertIn("image", msg.lower())
        self.assertIn("cookie", msg.lower())

    def test_payload_includes_cached_page_xsrf(self):
        from gemini_web2api import multimodal

        original = dict(multimodal._page_tokens_cache)
        CONFIG["xsrf_token"] = None
        try:
            multimodal._page_tokens_cache["tokens"] = {"at": "page-xsrf"}
            qs = parse_qs(_build_payload("hello", 1, 4))
            self.assertEqual(qs.get("at", [None])[0], "page-xsrf")
        finally:
            multimodal._page_tokens_cache.clear()
            multimodal._page_tokens_cache.update(original)


class MessageParsingTests(unittest.TestCase):
    def test_messages_to_prompt_extracts_openai_image_url_data_url(self):
        image_data = base64.b64encode(b"fake png").decode()

        prompt, images = messages_to_prompt([{
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}},
            ],
        }])

        self.assertEqual(prompt, "Describe [Image attached]")
        self.assertEqual(images, [(b"fake png", "image/png")])

    def test_messages_to_prompt_extracts_responses_input_image_url(self):
        prompt, images = messages_to_prompt([{
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Describe"},
                {"type": "input_image", "image_url": "https://example.com/image.png"},
            ],
        }])

        self.assertEqual(prompt, "Describe [Image attached]")
        self.assertEqual(images, [("https://example.com/image.png", "image/png")])

    def test_messages_to_prompt_ignores_malformed_image_data_url(self):
        prompt, images = messages_to_prompt([{
            "role": "user",
            "content": [
                {"type": "text", "text": "Describe"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,%%%"}},
            ],
        }])

        self.assertEqual(prompt, "Describe")
        self.assertEqual(images, [])

    def test_google_contents_to_prompt_extracts_inline_image_data(self):
        image_data = base64.b64encode(b"fake png").decode()

        prompt, images = google_contents_to_prompt({
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": "Describe"},
                    {"inlineData": {"mimeType": "image/png", "data": image_data}},
                ],
            }],
        })

        self.assertEqual(prompt, "Describe\n[Image attached]")
        self.assertEqual(images, [(b"fake png", "image/png")])

    def test_google_contents_to_prompt_ignores_malformed_inline_image_data(self):
        prompt, images = google_contents_to_prompt({
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": "Describe"},
                    {"inlineData": {"mimeType": "image/png", "data": "%%%"}},
                ],
            }],
        })

        self.assertEqual(prompt, "Describe")
        self.assertEqual(images, [])


class StreamingEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadedServer(("127.0.0.1", 0), GeminiHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self.original_config = dict(CONFIG)
        CONFIG["api_keys"] = []
        CONFIG["log_requests"] = False

    def tearDown(self):
        CONFIG.clear()
        CONFIG.update(self.original_config)

    def get(self, path, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        hdrs = dict(response.getheaders())
        connection.close()
        return response.status, hdrs, body

    def test_root_serves_playground(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        self.assertIn(b"gemini-web2api", body)
        self.assertIn(b"/v1/chat/completions", body)
        self.assertIn(b'id="modelSelect"', body)
        self.assertIn(b'id="attachBtn"', body)
        self.assertIn(b'id="input"', body)
        self.assertIn(b'id="geminiCookie"', body)
        self.assertIn(b'id="googleSignIn"', body)
        self.assertIn(b"gemini-cookie-sync", body)
        self.assertIn(b"Sign in with Google", body)
        self.assertIn(b"request-cookies", body)
        self.assertIn(b"Signed in", body)
        self.assertIn(b"AddSession", body)
        self.assertIn(b"accounts.google.com", body)
        self.assertIn(b"width=1100", body)
        self.assertNotIn(b"www.google.com/", body)
        self.assertNotIn(b"gemini.google.com/app", body)
        self.assertIn(b"application/pdf", body)
        self.assertNotIn(b"Get Cookie Sync", body)
        self.assertNotIn(b'id="cookieImport"', body)
        self.assertNotIn(b'id="downloadExt"', body)
        self.assertIn(b'id="chatList"', body)
        self.assertIn(b'id="exportChats"', body)
        self.assertIn(b"sk-gemini", body)
        self.assertNotIn(b'id="<pre', body)
        self.assertNotIn(b"ro/textarea", body)
        self.assertNotIn(b"type=\"password\" id=\"gmail", body)

    def test_extension_zip(self):
        import io
        import zipfile

        status, headers, body = self.get("/extension.zip")
        self.assertEqual(status, 200)
        self.assertIn("zip", headers["Content-Type"])
        names = zipfile.ZipFile(io.BytesIO(body)).namelist()
        self.assertTrue(any(name.endswith("manifest.json") for name in names))
        self.assertTrue(any(name.endswith("popup.js") for name in names))
        self.assertTrue(any(name.endswith("background.js") for name in names))
        self.assertTrue(any(name.endswith("content.js") for name in names))
        self.assertTrue(any("gemini-cookie-sync-extension/" in name for name in names))

    def test_playground_does_not_require_api_key(self):
        CONFIG["api_keys"] = ["secret"]
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])

    def test_health_returns_json(self):
        CONFIG["api_keys"] = ["secret"]
        status, headers, body = self.get("/health")
        self.assertEqual(status, 200)
        self.assertIn("application/json", headers["Content-Type"])
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["auth_required"])
        self.assertIn("models", data)
        self.assertIn("default_model", data)
        self.assertIn("google_client_id", data)

    def test_auth_google_without_client_id_does_not_open_gemini(self):
        status, headers, body = self.get("/auth/google")
        self.assertEqual(status, 400)
        self.assertNotIn("gemini.google.com", (headers.get("Location") or ""))
        self.assertIn("not configured", body.decode())

    def test_auth_connect_opens_add_session_not_search(self):
        from urllib.parse import unquote

        status, headers, _ = self.get("/auth/connect")
        self.assertEqual(status, 302)
        location = unquote(headers.get("Location") or "")
        self.assertIn("accounts.google.com", location)
        self.assertIn("AddSession", location)
        self.assertNotIn("www.google.com", location)
        self.assertNotIn("/auth/connected", location)
        self.assertNotIn("gemini.google.com", location)

    def test_auth_connected_closes_the_login_window(self):
        status, _, body = self.get("/auth/connected")
        self.assertEqual(status, 200)
        self.assertIn(b"window.close", body)
        self.assertIn(b"postMessage", body)
        self.assertNotIn(b"gemini.google.com/app", body)
        self.assertNotIn(b'type="password"', body)

    def test_auth_session_anonymous(self):
        status, _, body = self.get("/auth/session")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertFalse(data["connected"])

    @mock.patch("gemini_web2api.google_auth._http_json", side_effect=RuntimeError("bad token"))
    def test_auth_google_token_rejects_garbage(self, _http_json):
        status, _, body = self.post_json("/auth/google/token", {"credential": "not-a-jwt"})
        self.assertEqual(status, 401)
        self.assertIn("error", json.loads(body))

    def test_health_auth_required_false_when_no_keys(self):
        CONFIG["api_keys"] = []
        _, _, body = self.get("/health")
        self.assertFalse(json.loads(body)["auth_required"])

    def test_google_api_key_gets_explicit_401(self):
        CONFIG["api_keys"] = ["sk-gemini"]
        status, _, body = self.get(
            "/v1/models",
            headers={"Authorization": "Bearer AQ.not-a-google-secret"},
        )
        self.assertEqual(status, 401)
        message = json.loads(body)["error"]["message"]
        self.assertIn("not Google's Gemini API", message)
        self.assertIn("sk-gemini", message)

    def test_local_password_is_accepted(self):
        CONFIG["api_keys"] = ["sk-gemini"]
        status, _, body = self.get(
            "/v1/models",
            headers={"Authorization": "Bearer sk-gemini"},
        )
        self.assertEqual(status, 200)
        self.assertIn("gemini-3.6-flash", body.decode())

    def post_json(self, path, payload, extra_headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        connection.request(
            "POST",
            path,
            body=json.dumps(payload),
            headers=headers,
        )
        response = connection.getresponse()
        body = response.read().decode()
        headers = dict(response.getheaders())
        connection.close()
        return response.status, headers, body

    def post_chunked_json(self, path, payload):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(
            "POST",
            path,
            body=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            encode_chunked=True,
        )
        response = connection.getresponse()
        body = response.read().decode()
        headers = dict(response.getheaders())
        connection.close()
        return response.status, headers, body

    def test_x_gemini_cookie_header_is_used(self):
        CONFIG["cookie_file"] = None
        CONFIG["cookie"] = None

        def fake_generate(*_args, **_kwargs):
            cookie_str, sapisid = load_cookie()
            self.assertEqual(sapisid, "fromheader")
            self.assertIn("SID=abc", cookie_str)
            return "ok"

        with mock.patch("gemini_web2api.server.generate", side_effect=fake_generate):
            status, _, body = self.post_json(
                "/v1/chat/completions",
                {
                    "model": "gemini-3.6-flash",
                    "messages": [{"role": "user", "content": "hello"}],
                },
                extra_headers={"X-Gemini-Cookie": "SID=abc; SAPISID=fromheader"},
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["choices"][0]["message"]["content"], "ok")
        with mock.patch.dict(os.environ, {"GEMINI_COOKIE": "", "GEMINI_SAPISID": ""}, clear=False):
            cookie_str, sapisid = load_cookie()
        self.assertFalse(cookie_str)
        self.assertIsNone(sapisid)

    @mock.patch("gemini_web2api.server.generate_stream", side_effect=RuntimeError("blocked by Google"))
    def test_chat_stream_forwards_upstream_error(self, _generate_stream):
        status, headers, body = self.post_json(
            "/v1/chat/completions",
            {
                "model": "gemini-3.6-flash",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/event-stream")
        self.assertIn("blocked by Google", body)
        self.assertIn('"error"', body)

    @mock.patch("gemini_web2api.server.generate_stream")
    def test_chat_stream_starts_with_assistant_role(self, generate_stream):
        generate_stream.return_value = iter(["hel", "lo"])

        status, headers, body = self.post_json(
            "/v1/chat/completions",
            {
                "model": "gemini-3.6-flash",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/event-stream")
        chunks = [
            json.loads(line[len("data: "):])
            for line in body.splitlines()
            if line.startswith("data: {")
        ]
        self.assertEqual(chunks[0]["choices"][0]["delta"], {"role": "assistant"})
        self.assertEqual(chunks[1]["choices"][0]["delta"], {"content": "hel"})
        self.assertEqual(chunks[2]["choices"][0]["delta"], {"content": "lo"})
        self.assertTrue(body.endswith("data: [DONE]\n\n"))

    @mock.patch("gemini_web2api.server.generate", return_value="chunked ok")
    def test_chat_accepts_chunked_body(self, _generate):
        status, _, body = self.post_chunked_json(
            "/v1/chat/completions",
            {
                "model": "gemini-3.6-flash",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["choices"][0]["message"]["content"], "chunked ok")

    @mock.patch("gemini_web2api.server.upload_image", return_value="/uploaded/image-ref")
    @mock.patch("gemini_web2api.server.generate", return_value="looks good")
    def test_chat_accepts_openai_image_url_data_url(self, generate, upload_image):
        image_data = base64.b64encode(b"fake png").decode()

        status, _, body = self.post_json(
            "/v1/chat/completions",
            {
                "model": "gemini-3.6-flash",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_data}"
                            },
                        },
                    ],
                }],
            },
        )

        self.assertEqual(status, 200)
        upload_image.assert_called_once_with(b"fake png", "image.png", "image/png")
        self.assertEqual(generate.call_args.args[3], [{
            "ref": "/uploaded/image-ref",
            "name": "image.png",
            "mime": "image/png",
            "kind": 1,
        }])
        self.assertIn("[Image attached]", generate.call_args.args[0])
        self.assertEqual(json.loads(body)["choices"][0]["message"]["content"], "looks good")

    @mock.patch("gemini_web2api.server.fetch_image_bytes", return_value=b"\xff\xd8\xffremote jpeg")
    @mock.patch("gemini_web2api.server.upload_image", return_value="/uploaded/remote-ref")
    @mock.patch("gemini_web2api.server.generate", return_value="remote ok")
    def test_responses_accepts_input_image_url(self, generate, upload_image, fetch_image_bytes):
        status, _, _ = self.post_json(
            "/v1/responses",
            {
                "model": "gemini-3.6-flash",
                "input": [{
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "What is shown?"},
                        {
                            "type": "input_image",
                            "image_url": "https://example.com/image.jpg",
                        },
                    ],
                }],
            },
        )

        self.assertEqual(status, 200)
        fetch_image_bytes.assert_called_once_with("https://example.com/image.jpg")
        upload_image.assert_called_once_with(b"\xff\xd8\xffremote jpeg", "image.jpg", "image/jpeg")
        self.assertEqual(generate.call_args.args[3], [{
            "ref": "/uploaded/remote-ref",
            "name": "image.jpg",
            "mime": "image/jpeg",
            "kind": 1,
        }])
        self.assertIn("[Image attached]", generate.call_args.args[0])

    @mock.patch("gemini_web2api.server.upload_image", return_value="/uploaded/image-ref")
    @mock.patch("gemini_web2api.server.generate", return_value="top-level image ok")
    def test_responses_accepts_top_level_input_image(self, generate, upload_image):
        image_data = base64.b64encode(b"fake png").decode()

        status, _, _ = self.post_json(
            "/v1/responses",
            {
                "model": "gemini-3.6-flash",
                "input": [
                    {"type": "input_text", "text": "What is shown?"},
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{image_data}",
                    },
                ],
            },
        )

        self.assertEqual(status, 200)
        upload_image.assert_called_once_with(b"fake png", "image.png", "image/png")
        self.assertEqual(generate.call_args.args[3], [{
            "ref": "/uploaded/image-ref",
            "name": "image.png",
            "mime": "image/png",
            "kind": 1,
        }])
        self.assertIn("What is shown?", generate.call_args.args[0])
        self.assertIn("[Image attached]", generate.call_args.args[0])

    @mock.patch("gemini_web2api.server.upload_image", side_effect=RuntimeError("upload denied"))
    def test_google_image_upload_failure_returns_502(self, _upload_image):
        image_data = base64.b64encode(b"fake png").decode()

        status, _, body = self.post_json(
            "/v1beta/models/gemini-3.6-flash:generateContent",
            {
                "contents": [{
                    "role": "user",
                    "parts": [{
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": image_data,
                        },
                    }],
                }],
            },
        )

        self.assertEqual(status, 502)
        self.assertIn("file upload failed: upload denied", json.loads(body)["error"]["message"])

    @mock.patch("gemini_web2api.server.generate_stream", return_value=iter(["streamed"]))
    def test_google_stream_generate_content_uses_sse(self, _generate_stream):
        status, headers, body = self.post_json(
            "/v1beta/models/gemini-3.6-flash:streamGenerateContent",
            {
                "contents": [{
                    "role": "user",
                    "parts": [{"text": "Stream this"}],
                }],
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/event-stream")
        self.assertIn('"text": "streamed"', body)

    @mock.patch("gemini_web2api.server.generate", return_value="hello")
    def test_responses_text_stream_has_complete_event_sequence(self, _generate):
        status, headers, body = self.post_json(
            "/v1/responses",
            {
                "model": "gemini-3.6-flash",
                "input": "hello",
                "stream": True,
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/event-stream")
        events = _decode_sse(body)
        self.assertEqual(
            [event_type for event_type, _ in events],
            [
                "response.created",
                "response.in_progress",
                "response.output_item.added",
                "response.content_part.added",
                "response.output_text.delta",
                "response.output_text.done",
                "response.content_part.done",
                "response.output_item.done",
                "response.completed",
            ],
        )
        self.assertEqual(
            [event["sequence_number"] for _, event in events],
            list(range(1, len(events) + 1)),
        )
        self.assertEqual(events[4][1]["delta"], "hello")
        self.assertEqual(events[-1][1]["response"]["status"], "completed")
        self.assertEqual(events[-1][1]["response"]["output"][0]["content"][0]["text"], "hello")

    @mock.patch("gemini_web2api.server.parse_tool_calls")
    @mock.patch("gemini_web2api.server.generate", return_value="tool output")
    def test_responses_function_call_stream_has_complete_event_sequence(
        self, _generate, parse_tool_calls
    ):
        parse_tool_calls.return_value = (
            "",
            [
                {
                    "id": "call_test",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city":"Shanghai"}'},
                }
            ],
        )

        status, _, body = self.post_json(
            "/v1/responses",
            {
                "model": "gemini-3.6-flash",
                "input": "weather",
                "tools": [
                    {
                        "type": "function",
                        "name": "get_weather",
                        "description": "Get weather",
                        "parameters": {"type": "object"},
                    }
                ],
                "stream": True,
            },
        )

        self.assertEqual(status, 200)
        events = _decode_sse(body)
        self.assertEqual(
            [event_type for event_type, _ in events],
            [
                "response.created",
                "response.in_progress",
                "response.output_item.added",
                "response.function_call_arguments.delta",
                "response.function_call_arguments.done",
                "response.output_item.done",
                "response.completed",
            ],
        )
        self.assertEqual(
            [event["sequence_number"] for _, event in events],
            list(range(1, len(events) + 1)),
        )
        self.assertEqual(events[2][1]["output_index"], 0)
        self.assertEqual(events[3][1]["delta"], '{"city":"Shanghai"}')
        self.assertEqual(events[4][1]["arguments"], '{"city":"Shanghai"}')
        self.assertEqual(events[-1][1]["response"]["output"][0]["name"], "get_weather")


class GoogleLoginCookieTests(unittest.TestCase):
    def test_cookies_to_header_prefers_google_domain(self):
        from gemini_web2api.login import cookies_to_header, header_is_ready

        header = cookies_to_header([
            {"name": "SAPISID", "value": "sap", "domain": ".accounts.google.com"},
            {"name": "SAPISID", "value": "better", "domain": ".google.com"},
            {"name": "SID", "value": "sid", "domain": ".google.com"},
            {"name": "HSID", "value": "hsid", "domain": ".google.com"},
            {"name": "ignored", "value": "nope", "domain": ".google.com"},
        ])
        self.assertEqual(header, "SID=sid; HSID=hsid; SAPISID=better")
        self.assertTrue(header_is_ready(header))
        self.assertFalse(header_is_ready("SAPISID=only"))

    def test_auth_json_import_writes_cookie_file(self):
        import tempfile

        from gemini_web2api.login import cookie_from_auth_json, run_login

        payload = {
            "cookie": "SID=sidtest; HSID=hsidtest; SAPISID=saptest; __Secure-1PSID=psidtest",
            "sapisid": "saptest",
        }
        self.assertIn("SID=sidtest", cookie_from_auth_json(payload))
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "gemini-auth.json")
            dest = os.path.join(tmp, "cookie.txt")
            with open(src, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            self.assertEqual(run_login(output=dest, from_json=src), 0)
            with open(dest, encoding="utf-8") as handle:
                written = handle.read().strip()
            self.assertIn("SAPISID=saptest", written)
            self.assertIn("__Secure-1PSID=psidtest", written)

    def test_login_rejects_password_only_json(self):
        from gemini_web2api.login import cookie_from_auth_json

        with self.assertRaises(ValueError):
            cookie_from_auth_json({"password": "not-a-cookie"})

    def test_attachment_kind_for_pdf_video_code(self):
        from gemini_web2api.multimodal import attachment_kind, filename_for_mime

        self.assertEqual(attachment_kind("image/png"), 1)
        self.assertEqual(attachment_kind("video/mp4"), 2)
        self.assertEqual(attachment_kind("audio/mpeg"), 3)
        self.assertEqual(attachment_kind("application/pdf"), 0)
        self.assertEqual(attachment_kind("text/x-python"), 0)
        self.assertEqual(filename_for_mime("application/pdf"), "document.pdf")

    def test_messages_to_prompt_extracts_pdf(self):
        data = base64.b64encode(b"%PDF-fake").decode()
        prompt, files = messages_to_prompt([{
            "role": "user",
            "content": [
                {"type": "text", "text": "Summarize"},
                {"type": "input_file", "filename": "doc.pdf", "mime_type": "application/pdf",
                 "file_data": f"data:application/pdf;base64,{data}"},
            ],
        }])
        self.assertIn("[PDF attached]", prompt)
        self.assertEqual(files[0][1], "application/pdf")

    def test_payload_pdf_kind_zero(self):
        inner = _decode_payload(_build_payload("read", 1, 4, [{
            "ref": "/contrib_service/ttl_1d/pdf",
            "name": "doc.pdf",
            "mime": "application/pdf",
            "kind": 0,
        }]))
        self.assertEqual(inner[0][3][0][0], ["/contrib_service/ttl_1d/pdf", 0, None, "application/pdf"])


if __name__ == "__main__":
    unittest.main()
