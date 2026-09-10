(function () {
  const origin = window.location.origin;

  function announce() {
    window.postMessage({ source: "gemini-cookie-sync", type: "hello" }, origin);
  }

  function requestCookies() {
    try {
      chrome.runtime.sendMessage({ type: "get-cookies" }, (payload) => {
        if (chrome.runtime.lastError) return;
        if (payload && payload.cookie) {
          window.postMessage({ source: "gemini-cookie-sync", type: "cookies", ...payload }, origin);
        }
      });
    } catch (e) {
      // Extension context may be gone after reload.
    }
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data || {};
    if (data.source !== "gemini-web2api") return;
    if (data.type === "request-cookies" || data.type === "ping") requestCookies();
  });

  announce();
  requestCookies();
  setTimeout(requestCookies, 1500);
})();
