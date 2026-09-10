const CORE_REQUIRED = ["SAPISID"];
const SESSION_ALTERNATIVES = ["__Secure-1PSID", "__Secure-3PSID", "SID"];
const LEGACY_COOKIES = ["SID", "HSID", "SSID", "APISID", "SAPISID"];
const WATCH_COOKIES = ["SAPISID", "SID", "__Secure-1PSID", "__Secure-3PSID"];

const EXPORT_ORDER = [
  "SID",
  "HSID",
  "SSID",
  "APISID",
  "SAPISID",
  "LSID",
  "OSID",
  "SIDCC",
  "AEC",
  "NID",
  "COMPASS",
  "__Secure-1PAPISID",
  "__Secure-1PSID",
  "__Secure-1PSIDTS",
  "__Secure-1PSIDCC",
  "__Secure-1PSIDRTS",
  "__Secure-3PAPISID",
  "__Secure-3PSID",
  "__Secure-3PSIDTS",
  "__Secure-3PSIDCC",
  "__Secure-3PSIDRTS",
  "__Secure-OSID",
  "__Host-1PLSID",
  "__Host-3PLSID"
];

const LOOKUP_URLS = [
  "https://gemini.google.com/app",
  "https://accounts.google.com/",
  "https://www.google.com/",
  "https://google.com/"
];

const LOGIN_URL = "https://accounts.google.com/ServiceLogin?hl=en&continue=https%3A%2F%2Fgemini.google.com%2Fapp";

function normalizeDomain(domain = "") {
  return domain.replace(/^\./, "").toLowerCase();
}

function isGoogleCookie(cookie) {
  const domain = normalizeDomain(cookie.domain);
  return domain === "google.com" || domain.endsWith(".google.com");
}

function cookieKey(cookie) {
  const partition = cookie.partitionKey ? JSON.stringify(cookie.partitionKey) : "";
  return [cookie.storeId || "", cookie.name, cookie.domain, cookie.path, partition].join("|");
}

function scoreCookie(cookie) {
  const domain = (cookie.domain || "").toLowerCase();
  let score = 0;
  if (domain === ".google.com") score += 120;
  else if (domain === "google.com") score += 110;
  else if (domain === ".gemini.google.com") score += 100;
  else if (domain === "gemini.google.com") score += 95;
  else if (domain === ".accounts.google.com") score += 80;
  else if (domain === "accounts.google.com") score += 75;
  else if (domain.endsWith(".google.com")) score += 40;
  if (cookie.path === "/") score += 10;
  if (cookie.secure) score += 3;
  if (cookie.httpOnly) score += 2;
  if (!cookie.partitionKey) score += 2;
  if (!cookie.session) score += 1;
  return score;
}

async function readGoogleCookies() {
  const stores = await chrome.cookies.getAllCookieStores();
  const deduped = new Map();
  for (const store of stores) {
    const queries = [
      chrome.cookies.getAll({ storeId: store.id }),
      ...LOOKUP_URLS.map((url) => chrome.cookies.getAll({ storeId: store.id, url }))
    ];
    const results = await Promise.allSettled(queries);
    for (const result of results) {
      if (result.status !== "fulfilled") continue;
      for (const cookie of result.value) {
        if (!isGoogleCookie(cookie) || !cookie.value) continue;
        deduped.set(cookieKey(cookie), cookie);
      }
    }
  }
  return [...deduped.values()];
}

function selectBestCookies(cookies) {
  const selected = new Map();
  for (const name of EXPORT_ORDER) {
    const candidates = cookies
      .filter((cookie) => cookie.name === name && cookie.value)
      .sort((a, b) => scoreCookie(b) - scoreCookie(a));
    if (candidates.length > 0) selected.set(name, candidates[0]);
  }
  return selected;
}

function validateSelection(selected) {
  const missingCore = CORE_REQUIRED.filter((name) => !selected.has(name));
  const sessionCookie = SESSION_ALTERNATIVES.find((name) => selected.has(name));
  return {
    missingCore,
    sessionCookie,
    valid: missingCore.length === 0 && Boolean(sessionCookie)
  };
}

function listPresent(selected, names) {
  return names.filter((name) => selected.has(name));
}

function summarizeAvailable(cookies) {
  return [...new Set(cookies
    .map((cookie) => cookie.name)
    .filter((name) => /SID|APISID|LSID|OSID|COMPASS/.test(name)))]
    .sort();
}

function getActiveGeminiAccount(tabs) {
  for (const tab of tabs) {
    try {
      const url = new URL(tab.url || "");
      if (url.hostname !== "gemini.google.com") continue;
      const match = url.pathname.match(/^\/u\/(\d+)(?:\/|$)/);
      return match ? match[1] : null;
    } catch {
      // Ignore malformed URLs.
    }
  }
  return null;
}

function chooseGeminiTab(tabs) {
  return tabs.find((tab) => tab.active) || tabs[0] || null;
}

async function readGeminiPageMetadata(tabs) {
  const tab = chooseGeminiTab(tabs);
  if (!tab?.id) {
    return { xsrfToken: null, geminiBl: null, source: null, error: null };
  }
  try {
    const result = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      world: "MAIN",
      func: () => {
        const wiz = globalThis.WIZ_global_data || {};
        const html = document.documentElement?.innerHTML || "";
        const decode = (value) => {
          if (!value) return null;
          try {
            return JSON.parse(`"${value.replace(/"/g, '\\"')}"`);
          } catch {
            return value
              .replace(/\\u003d/gi, "=")
              .replace(/\\u0026/gi, "&")
              .replace(/\\u003c/gi, "<")
              .replace(/\\u003e/gi, ">");
          }
        };
        const regexValue = (name) => {
          const patterns = [
            new RegExp(`"${name}"\\s*:\\s*"([^"\\n]+)"`),
            new RegExp(`\\\\"${name}\\\\"\\s*:\\s*\\\\"([^"\\n]+)\\\\"`)
          ];
          for (const pattern of patterns) {
            const match = html.match(pattern);
            if (match?.[1]) return decode(match[1]);
          }
          return null;
        };
        const xsrfToken = wiz.SNlM0e || regexValue("SNlM0e");
        const geminiBl = wiz.cfb2h || regexValue("cfb2h");
        return {
          xsrfToken: xsrfToken || null,
          geminiBl: geminiBl || null,
          source: wiz.SNlM0e || wiz.cfb2h ? "WIZ_global_data" : (xsrfToken || geminiBl ? "page-html" : null),
          url: location.href
        };
      }
    });
    return result?.[0]?.result || { xsrfToken: null, geminiBl: null, source: null };
  } catch (error) {
    return { xsrfToken: null, geminiBl: null, source: null, error: error?.message || String(error) };
  }
}

async function buildInspection() {
  const [cookies, tabs] = await Promise.all([
    readGoogleCookies(),
    chrome.tabs.query({ url: "https://gemini.google.com/*" })
  ]);
  const selected = selectBestCookies(cookies);
  const validation = validateSelection(selected);
  return {
    cookies,
    selected,
    validation,
    legacyPresent: listPresent(selected, LEGACY_COOKIES),
    legacyMissing: LEGACY_COOKIES.filter((name) => !selected.has(name)),
    available: summarizeAvailable(cookies),
    authUser: getActiveGeminiAccount(tabs),
    pageMetadata: await readGeminiPageMetadata(tabs)
  };
}

function inspectionMessage(info) {
  const { cookies, selected, validation, legacyPresent, legacyMissing, available, authUser, pageMetadata } = info;
  const lines = [
    `Found ${cookies.length} cookie(s) across Google domains.`,
    "",
    `SAPISID: ${selected.has("SAPISID") ? "present" : "missing"}`,
    `Session cookie: ${validation.sessionCookie || "missing"}`,
    `XSRF / SNlM0e: ${pageMetadata.xsrfToken ? "present" : "missing"}`,
    `gemini_bl / cfb2h: ${pageMetadata.geminiBl ? "present" : "missing"}`,
    `auth_user: ${authUser ?? "default account"}`,
    "",
    `Legacy present: ${legacyPresent.join(", ") || "none"}`,
    `Available for export: ${available.join(", ") || "none"}`
  ];
  if (pageMetadata.error) lines.push("", `Page note: ${pageMetadata.error}`);
  if (validation.valid) lines.push("", "Session cookies are ready. They will auto-fill the playground.");
  else lines.push("", "Session is incomplete: SAPISID and one of __Secure-1PSID, __Secure-3PSID, or SID are required.");
  return lines.join("\n");
}

function buildCookieString(info) {
  return EXPORT_ORDER
    .filter((name) => info.selected.has(name))
    .map((name) => `${name}=${info.selected.get(name).value}`)
    .join("; ");
}

function cookiePayload(info) {
  return {
    cookie: buildCookieString(info),
    sapisid: info.selected.get("SAPISID")?.value || "",
    auth_user: info.authUser,
    xsrf_token: info.pageMetadata.xsrfToken,
    gemini_bl: info.pageMetadata.geminiBl
  };
}

function isPlaygroundTab(tab) {
  const url = tab.url || "";
  const title = tab.title || "";
  if (title.toLowerCase().includes("gemini-web2api")) return true;
  if (/https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?(\/|\/playground|\/index\.html)?\/?(\?.*)?$/.test(url)) return true;
  if (url.includes("onrender.com") && !url.includes("gemini.google.com")) return true;
  if (url.includes("/playground")) return true;
  return false;
}

function deliverCookieToTab(tabId, payload) {
  return chrome.scripting.executeScript({
    target: { tabId },
    func: (data) => {
      try {
        if (data && data.cookie) window.localStorage.setItem("g2a.cookie", data.cookie);
      } catch (e) {}
      const field = document.getElementById("geminiCookie");
      if (field && data && data.cookie) field.value = data.cookie;
      window.postMessage({ source: "gemini-cookie-sync", type: "cookies", ...data }, window.location.origin);
    },
    args: [payload]
  });
}

async function sendCookieToPlayground(payload) {
  const tabs = await chrome.tabs.query({});
  const targets = tabs.filter(isPlaygroundTab);
  if (!targets.length) {
    throw new Error("Open the gemini-web2api playground tab first.");
  }
  let sent = 0;
  for (const tab of targets) {
    if (!tab.id) continue;
    await deliverCookieToTab(tab.id, payload);
    sent += 1;
  }
  return sent;
}

async function captureReadyPayload() {
  const info = await buildInspection();
  if (!info.validation.valid) return null;
  return cookiePayload(info);
}
