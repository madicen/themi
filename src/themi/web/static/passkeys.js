// SP7b: passkeys. Buttons say what they do with data-passkey="add" or "sign-in"; the
// server sends the options and checks what the browser's passkey sends back.
(() => {
  const toBytes = (s) => {
    const b64 = s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4);
    return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  };
  const toText = (buf) =>
    btoa(String.fromCharCode(...new Uint8Array(buf)))
      .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

  const say = (button, words) => {
    const out = document.getElementById(button.dataset.say || "passkey-said");
    if (out) out.textContent = words;
  };

  async function post(url, body, csrf) {
    const headers = { "Content-Type": "application/json" };
    if (csrf) headers["X-CSRF-Token"] = csrf;
    const response = await fetch(url, {
      method: "POST", headers, credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const answer = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(answer.error || "That didn't work. Try again.");
    return answer;
  }

  async function add(button) {
    const csrf = button.dataset.csrf;
    const options = await post("/passkeys/options", undefined, csrf);
    options.challenge = toBytes(options.challenge);
    options.user.id = toBytes(options.user.id);
    (options.excludeCredentials || []).forEach((c) => { c.id = toBytes(c.id); });
    const made = await navigator.credentials.create({ publicKey: options });
    const credential = {
      id: made.id, rawId: toText(made.rawId), type: made.type,
      response: {
        clientDataJSON: toText(made.response.clientDataJSON),
        attestationObject: toText(made.response.attestationObject),
        transports: made.response.getTransports ? made.response.getTransports() : [],
      },
      clientExtensionResults: made.getClientExtensionResults(),
    };
    const name = (document.getElementById("passkey-name") || {}).value || "";
    const answer = await post("/passkeys/register", { credential, name }, csrf);
    window.location = answer.next;
  }

  async function signIn() {
    const options = await post("/passkeys/sign-in/options");
    options.challenge = toBytes(options.challenge);
    (options.allowCredentials || []).forEach((c) => { c.id = toBytes(c.id); });
    const got = await navigator.credentials.get({ publicKey: options });
    const credential = {
      id: got.id, rawId: toText(got.rawId), type: got.type,
      response: {
        clientDataJSON: toText(got.response.clientDataJSON),
        authenticatorData: toText(got.response.authenticatorData),
        signature: toText(got.response.signature),
        userHandle: got.response.userHandle ? toText(got.response.userHandle) : null,
      },
      clientExtensionResults: got.getClientExtensionResults(),
    };
    const answer = await post("/passkeys/sign-in", { credential });
    window.location = answer.next;
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-passkey]");
    if (!button) return;
    event.preventDefault();
    if (!window.PublicKeyCredential) {
      say(button, "This browser can't use passkeys.");
      return;
    }
    const run = button.dataset.passkey === "add" ? add : signIn;
    run(button).catch((error) => say(button, error.message));
  });
})();
