importScripts("cookies.js");

let pushTimer = null;
let lastCookie = "";

async function autoPushCookies() {
  try {
    const payload = await captureReadyPayload();
    if (!payload || !payload.cookie || payload.cookie === lastCookie) return;
    const sent = await sendCookieToPlayground(payload);
    if (sent) lastCookie = payload.cookie;
  } catch (error) {
    // Playground tab may not be open yet.
  }
}

function scheduleAutoPush() {
  if (pushTimer) clearTimeout(pushTimer);
  pushTimer = setTimeout(autoPushCookies, 1200);
}

chrome.runtime.onInstalled.addListener(scheduleAutoPush);
chrome.runtime.onStartup.addListener(scheduleAutoPush);

chrome.cookies.onChanged.addListener((change) => {
  const name = change?.cookie?.name;
  if (!name || !WATCH_COOKIES.includes(name)) return;
  if (!isGoogleCookie(change.cookie)) return;
  scheduleAutoPush();
});

chrome.tabs.onUpdated.addListener((_id, info, tab) => {
  if (info.status !== "complete") return;
  const url = tab.url || "";
  if (url.includes("gemini.google.com") || isPlaygroundTab(tab)) scheduleAutoPush();
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== "get-cookies") return;
  captureReadyPayload()
    .then((payload) => sendResponse(payload || { ready: false }))
    .catch((error) => sendResponse({ ready: false, error: error?.message || String(error) }));
  return true;
});
