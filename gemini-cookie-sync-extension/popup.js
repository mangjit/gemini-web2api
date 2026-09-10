const statusEl = document.getElementById("status");
const exportButton = document.getElementById("export");
const inspectButton = document.getElementById("inspect");
const openButton = document.getElementById("open");
const sendButton = document.getElementById("send");
const copyButton = document.getElementById("copy");

function setStatus(message, kind = "") {
  statusEl.textContent = message;
  statusEl.className = kind;
}

async function downloadJson(filename, payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2) + "\n"], {
    type: "application/json;charset=utf-8"
  });
  const url = URL.createObjectURL(blob);
  await chrome.downloads.download({
    url,
    filename,
    saveAs: true,
    conflictAction: "uniquify"
  });
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

openButton.addEventListener("click", async () => {
  await chrome.tabs.create({ url: LOGIN_URL });
});

copyButton.addEventListener("click", async () => {
  copyButton.disabled = true;
  setStatus("Reading cookies…");
  try {
    const info = await buildInspection();
    if (!info.validation.valid) throw new Error(inspectionMessage(info));
    await navigator.clipboard.writeText(buildCookieString(info));
    setStatus("Cookie string copied. It should also auto-fill the playground.", "ok");
  } catch (error) {
    setStatus(error?.message || String(error), "warn");
  } finally {
    copyButton.disabled = false;
  }
});

sendButton.addEventListener("click", async () => {
  sendButton.disabled = true;
  setStatus("Sending cookies to playground…");
  try {
    const payload = await captureReadyPayload();
    if (!payload) throw new Error("Sign in to Gemini with Gmail first.");
    const sent = await sendCookieToPlayground(payload);
    setStatus(`Sent cookies to ${sent} playground tab(s). They also auto-send after sign-in.`, "ok");
  } catch (error) {
    setStatus(error?.message || String(error), "warn");
  } finally {
    sendButton.disabled = false;
  }
});

inspectButton.addEventListener("click", async () => {
  inspectButton.disabled = true;
  setStatus("Inspecting session…");
  try {
    const info = await buildInspection();
    setStatus(inspectionMessage(info), info.validation.valid ? "ok" : "warn");
  } catch (error) {
    setStatus(error?.message || String(error), "warn");
  } finally {
    inspectButton.disabled = false;
  }
});

exportButton.addEventListener("click", async () => {
  exportButton.disabled = true;
  setStatus("Reading cookies…");
  try {
    const info = await buildInspection();
    if (!info.validation.valid) throw new Error(inspectionMessage(info));
    await downloadJson("gemini-auth.json", cookiePayload(info));
    setStatus("Created gemini-auth.json. Do not share it or commit it to Git.", "ok");
  } catch (error) {
    setStatus(error?.message || String(error), "warn");
  } finally {
    exportButton.disabled = false;
  }
});
