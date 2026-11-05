// Passkey-Gate vor mcp-hub.
//
// mcp-hub kennt als Login nur ein Passwort. Dieses Gate steht davor und
// verlangt für alles unter /interaction/ (Login- und Freigabeseiten des Hubs)
// eine Anmeldung bei einem OIDC-Anbieter (Pocket ID → Passkey). Erst dann
// zeigt es die Freigabeseite des Hubs – ohne Passwortfeld – und setzt beim
// Absenden das Hub-Passwort serverseitig ein. Von außen ist das Hub-Passwort
// damit nicht mehr verwendbar: Ein Login-POST ohne gültige Gate-Sitzung wird
// abgewiesen, ein mitgeschicktes Passwort immer überschrieben.
//
// Alles andere (/hub, /<name>/mcp, /token, /register, /.well-known, …) wird
// unverändert und ungepuffert durchgereicht – das sind Server-zu-Server-
// Aufrufe der MCP-Clients, die durch OAuth-Tokens des Hubs geschützt sind.
//
// Bewusst ohne npm-Abhängigkeiten: nur node:http, node:crypto und fetch.

import http from "node:http";
import crypto from "node:crypto";
import { readFileSync } from "node:fs";

const env = process.env;
const log = (m) => console.error(`[passkey-gate] ${m}`);

function required(name) {
  const v = (env[name] || "").trim();
  if (!v) {
    log(`FEHLER: ${name} fehlt`);
    process.exit(1);
  }
  return v;
}

const CFG = {
  port: Number(env.GATE_PORT || 8099),
  hubPort: Number(env.HUB_PORT || 8100),
  externalUrl: required("EXTERNAL_URL").replace(/\/+$/, ""),
  issuer: required("OIDC_ISSUER").replace(/\/+$/, ""),
  clientId: required("OIDC_CLIENT_ID"),
  clientSecret: required("OIDC_CLIENT_SECRET"),
  allowed: new Set(
    required("GATE_ALLOWED_USERS")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean),
  ),
  hubPassword: required("HUB_PASSWORD"),
  secret: readFileSync(required("GATE_SECRET_FILE")),
  sessionTtlMs: 10 * 60_000,
  flowTtlMs: 10 * 60_000,
  // Nur für lokale Tests über http; im Add-on immer https.
  insecureCookies: env.GATE_INSECURE_COOKIES === "1",
};

if (CFG.secret.length < 32) {
  log("FEHLER: Gate-Schlüssel zu kurz");
  process.exit(1);
}

const REDIRECT_URI = `${CFG.externalUrl}/passkey/callback`;
const SESSION_COOKIE = CFG.insecureCookies ? "mbx_gate" : "__Host-mbx_gate";
const FLOW_COOKIE = CFG.insecureCookies ? "mbx_gate_flow" : "__Host-mbx_gate_flow";

// ---------------------------------------------------------------------------
// Hilfen

const b64u = (buf) => Buffer.from(buf).toString("base64url");
const rand = (n = 32) => b64u(crypto.randomBytes(n));
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

function safeEqual(a, b) {
  const x = Buffer.from(String(a));
  const y = Buffer.from(String(b));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}

function sign(obj) {
  const body = b64u(JSON.stringify(obj));
  const mac = b64u(crypto.createHmac("sha256", CFG.secret).update(body).digest());
  return `${body}.${mac}`;
}

function unsign(value) {
  if (typeof value !== "string") return null;
  const i = value.lastIndexOf(".");
  if (i < 1) return null;
  const body = value.slice(0, i);
  const mac = b64u(crypto.createHmac("sha256", CFG.secret).update(body).digest());
  if (!safeEqual(mac, value.slice(i + 1))) return null;
  try {
    const obj = JSON.parse(Buffer.from(body, "base64url").toString("utf8"));
    if (typeof obj.exp !== "number" || obj.exp < Date.now()) return null;
    return obj;
  } catch {
    return null;
  }
}

function parseCookies(header) {
  const out = {};
  for (const part of String(header || "").split(";")) {
    const i = part.indexOf("=");
    if (i < 0) continue;
    const k = part.slice(0, i).trim();
    if (k && !(k in out)) out[k] = part.slice(i + 1).trim();
  }
  return out;
}

function cookie(name, value, maxAgeMs) {
  const parts = [`${name}=${value}`, "Path=/", "HttpOnly", "SameSite=Lax", `Max-Age=${Math.floor(maxAgeMs / 1000)}`];
  if (!CFG.insecureCookies) parts.push("Secure");
  return parts.join("; ");
}

function clientIp(req) {
  return req.socket.remoteAddress || "unknown";
}

const PAGE_HEADERS = {
  "Content-Type": "text/html; charset=utf-8",
  "Cache-Control": "no-store",
  "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
  "X-Frame-Options": "DENY",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
};

function page(res, status, text, extraHeaders = {}) {
  res.writeHead(status, { ...PAGE_HEADERS, ...extraHeaders });
  res.end(
    `<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex"><title>mcp-hub</title>` +
      `<style>body{font-family:system-ui,sans-serif;background:#111826;color:#e5e7eb;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}div{background:#1f2937;padding:2rem;border-radius:12px;width:min(22rem,90vw)}</style>` +
      `</head><body><div><p>${esc(text)}</p></div></body></html>`,
  );
}

// ---------------------------------------------------------------------------
// OIDC: Discovery, JWKS, ID-Token-Prüfung (ohne Bibliothek, nur asymmetrische Algorithmen)

let discovery = null;
let discoveryAt = 0;
let jwks = null;
let jwksAt = 0;

async function getDiscovery() {
  if (discovery && Date.now() - discoveryAt < 3600_000) return discovery;
  const r = await fetch(`${CFG.issuer}/.well-known/openid-configuration`, { redirect: "error" });
  if (!r.ok) throw new Error(`Discovery HTTP ${r.status}`);
  const d = await r.json();
  if (String(d.issuer).replace(/\/+$/, "") !== CFG.issuer) throw new Error(`Issuer passt nicht: ${d.issuer}`);
  for (const k of ["authorization_endpoint", "token_endpoint", "jwks_uri"]) {
    if (typeof d[k] !== "string" || !d[k].startsWith("https://")) {
      if (!(CFG.insecureCookies && typeof d[k] === "string"))
        throw new Error(
          `${k} ist keine https-URL (${String(d[k]).slice(0, 100)}). Bei Pocket ID: INTERNAL_APP_URL nicht auf http setzen oder leer lassen.`,
        );
    }
  }
  discovery = d;
  discoveryAt = Date.now();
  return d;
}

async function getJwks(force = false) {
  if (!force && jwks && Date.now() - jwksAt < 3600_000) return jwks;
  if (force && jwks && Date.now() - jwksAt < 60_000) return jwks; // höchstens einmal pro Minute neu laden
  const d = await getDiscovery();
  const r = await fetch(d.jwks_uri, { redirect: "error" });
  if (!r.ok) throw new Error(`JWKS HTTP ${r.status}`);
  const j = await r.json();
  if (!Array.isArray(j.keys)) throw new Error("JWKS ohne keys");
  jwks = j.keys;
  jwksAt = Date.now();
  return jwks;
}

// alg → [Hash, erwarteter kty, Zusatzoptionen]
const ALGS = {
  RS256: ["sha256", "RSA", {}],
  RS384: ["sha384", "RSA", {}],
  RS512: ["sha512", "RSA", {}],
  PS256: ["sha256", "RSA", { padding: crypto.constants.RSA_PKCS1_PSS_PADDING, saltLength: 32 }],
  PS384: ["sha384", "RSA", { padding: crypto.constants.RSA_PKCS1_PSS_PADDING, saltLength: 48 }],
  PS512: ["sha512", "RSA", { padding: crypto.constants.RSA_PKCS1_PSS_PADDING, saltLength: 64 }],
  ES256: ["sha256", "EC", { dsaEncoding: "ieee-p1363" }, "P-256"],
  ES384: ["sha384", "EC", { dsaEncoding: "ieee-p1363" }, "P-384"],
  ES512: ["sha512", "EC", { dsaEncoding: "ieee-p1363" }, "P-521"],
  EdDSA: [null, "OKP", {}],
};

async function verifyIdToken(token, expectedNonce) {
  const parts = String(token).split(".");
  if (parts.length !== 3) throw new Error("ID-Token hat kein JWS-Format");
  const header = JSON.parse(Buffer.from(parts[0], "base64url").toString("utf8"));
  const payload = JSON.parse(Buffer.from(parts[1], "base64url").toString("utf8"));
  const spec = ALGS[header.alg];
  if (!spec) throw new Error(`Algorithmus nicht erlaubt: ${header.alg}`);
  const [hash, kty, opts, crv] = spec;

  const pick = (keys) =>
    keys.filter(
      (k) =>
        k.kty === kty &&
        (!crv || k.crv === crv) &&
        (k.use === undefined || k.use === "sig") &&
        (header.kid === undefined || k.kid === header.kid),
    );
  let candidates = pick(await getJwks());
  if (candidates.length === 0) candidates = pick(await getJwks(true));
  if (candidates.length === 0) throw new Error("Kein passender Schlüssel im JWKS");

  const data = Buffer.from(`${parts[0]}.${parts[1]}`);
  const sig = Buffer.from(parts[2], "base64url");
  const ok = candidates.some((jwk) => {
    try {
      const key = crypto.createPublicKey({ key: jwk, format: "jwk" });
      return crypto.verify(hash, data, { key, ...opts }, sig);
    } catch {
      return false;
    }
  });
  if (!ok) throw new Error("Signatur ungültig");

  const now = Math.floor(Date.now() / 1000);
  const d = await getDiscovery();
  if (payload.iss !== d.issuer) throw new Error("iss passt nicht");
  const aud = Array.isArray(payload.aud) ? payload.aud : [payload.aud];
  if (!aud.includes(CFG.clientId)) throw new Error("aud passt nicht");
  if (aud.length > 1 && payload.azp !== CFG.clientId) throw new Error("azp passt nicht");
  if (typeof payload.exp !== "number" || payload.exp < now - 60) throw new Error("ID-Token abgelaufen");
  if (typeof payload.iat === "number" && payload.iat > now + 300) throw new Error("iat liegt in der Zukunft");
  if (!expectedNonce || !safeEqual(payload.nonce ?? "", expectedNonce)) throw new Error("nonce passt nicht");
  if (typeof payload.sub !== "string" || !payload.sub) throw new Error("sub fehlt");
  return payload;
}

function isAllowed(claims) {
  const ids = [claims.sub];
  if (typeof claims.email === "string" && claims.email_verified !== false) ids.push(claims.email);
  if (typeof claims.preferred_username === "string") ids.push(claims.preferred_username);
  return ids.some((id) => CFG.allowed.has(String(id).toLowerCase()));
}

// ---------------------------------------------------------------------------
// Durchreichen an den Hub

function forwardHeaders(req, bodyLength) {
  const h = { ...req.headers };
  const ip = clientIp(req);
  h["x-forwarded-for"] = h["x-forwarded-for"] ? `${h["x-forwarded-for"]}, ${ip}` : ip;
  if (bodyLength !== undefined) {
    h["content-length"] = String(bodyLength);
    delete h["transfer-encoding"];
  }
  return h;
}

/** Ungepuffertes Durchreichen (SSE-tauglich). */
function proxy(req, res) {
  const up = http.request(
    { host: "127.0.0.1", port: CFG.hubPort, method: req.method, path: req.url, headers: forwardHeaders(req) },
    (upRes) => {
      res.writeHead(upRes.statusCode, upRes.rawHeaders);
      upRes.pipe(res);
      res.on("close", () => upRes.destroy());
    },
  );
  up.on("error", () => {
    if (!res.headersSent) page(res, 502, "Hub nicht erreichbar.");
    else res.destroy();
  });
  req.pipe(up);
}

/** Gepufferter Aufruf, für die wenigen Antworten, die das Gate verändert. */
function upstream(req, body) {
  return new Promise((resolve, reject) => {
    const up = http.request(
      {
        host: "127.0.0.1",
        port: CFG.hubPort,
        method: req.method,
        path: req.url,
        headers: forwardHeaders(req, body === undefined ? undefined : body.length),
      },
      (upRes) => {
        const chunks = [];
        let size = 0;
        upRes.on("data", (c) => {
          size += c.length;
          if (size > 1_000_000) {
            upRes.destroy();
            reject(new Error("Antwort zu groß"));
          } else chunks.push(c);
        });
        upRes.on("end", () => resolve({ status: upRes.statusCode, rawHeaders: upRes.rawHeaders, body: Buffer.concat(chunks) }));
        upRes.on("error", reject);
      },
    );
    up.on("error", reject);
    up.end(body);
  });
}

function readBody(req, limit = 16_384) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (c) => {
      size += c.length;
      if (size > limit) {
        reject(new Error("Body zu groß"));
        req.destroy();
      } else chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function withoutHeaders(rawHeaders, names) {
  const drop = new Set(names);
  const out = [];
  for (let i = 0; i < rawHeaders.length; i += 2) {
    if (!drop.has(rawHeaders[i].toLowerCase())) out.push(rawHeaders[i], rawHeaders[i + 1]);
  }
  return out;
}

function headerOf(rawHeaders, name) {
  for (let i = 0; i < rawHeaders.length; i += 2) if (rawHeaders[i].toLowerCase() === name) return rawHeaders[i + 1];
  return undefined;
}

// ---------------------------------------------------------------------------
// Routen

const INTERACTION = /^\/interaction\/([A-Za-z0-9_-]+)(?:\/([a-z]*))?$/;
const RETURN_TO = /^\/interaction\/[A-Za-z0-9_-]+\/?$/;

async function startLogin(req, res, returnTo) {
  const d = await getDiscovery();
  const state = rand();
  const nonce = rand();
  const verifier = rand(48);
  const challenge = b64u(crypto.createHash("sha256").update(verifier).digest());
  const flow = sign({ state, nonce, verifier, returnTo, exp: Date.now() + CFG.flowTtlMs });
  const url = new URL(d.authorization_endpoint);
  url.search = new URLSearchParams({
    response_type: "code",
    client_id: CFG.clientId,
    redirect_uri: REDIRECT_URI,
    scope: "openid email profile",
    state,
    nonce,
    code_challenge: challenge,
    code_challenge_method: "S256",
  }).toString();
  res.writeHead(302, { Location: url.toString(), "Set-Cookie": cookie(FLOW_COOKIE, flow, CFG.flowTtlMs), "Cache-Control": "no-store" });
  res.end();
}

async function callback(req, res, url) {
  const flow = unsign(parseCookies(req.headers.cookie)[FLOW_COOKIE]);
  const clearFlow = cookie(FLOW_COOKIE, "", 0);
  if (!flow) return page(res, 400, "Anmeldung abgelaufen. Fenster schließen und erneut verbinden.", { "Set-Cookie": clearFlow });
  if (!safeEqual(url.searchParams.get("state") ?? "", flow.state)) {
    log(`state passt nicht (${clientIp(req)})`);
    return page(res, 400, "Ungültige Anmeldung. Fenster schließen und erneut verbinden.", { "Set-Cookie": clearFlow });
  }
  if (url.searchParams.get("error")) {
    log(`Anbieter meldet Fehler: ${String(url.searchParams.get("error")).slice(0, 80)}`);
    return page(res, 403, "Anmeldung abgebrochen.", { "Set-Cookie": clearFlow });
  }
  const code = url.searchParams.get("code");
  if (!code) return page(res, 400, "Kein Code erhalten.", { "Set-Cookie": clearFlow });

  const d = await getDiscovery();
  // RFC 9207: Wenn der Anbieter iss mitschickt, muss er der erwartete sein (Mix-up-Schutz).
  const issParam = url.searchParams.get("iss");
  if (issParam !== null && issParam !== d.issuer) {
    log(`iss im Callback passt nicht: ${issParam.slice(0, 100)}`);
    return page(res, 400, "Ungültige Anmeldung.", { "Set-Cookie": clearFlow });
  }
  const form = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: REDIRECT_URI,
    code_verifier: flow.verifier,
  });
  const headers = { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" };
  const methods = d.token_endpoint_auth_methods_supported;
  if (!Array.isArray(methods) || methods.includes("client_secret_basic")) {
    const enc = (s) => encodeURIComponent(s);
    headers.Authorization = `Basic ${Buffer.from(`${enc(CFG.clientId)}:${enc(CFG.clientSecret)}`).toString("base64")}`;
  } else {
    form.set("client_id", CFG.clientId);
    form.set("client_secret", CFG.clientSecret);
  }
  const r = await fetch(d.token_endpoint, { method: "POST", headers, body: form, redirect: "error" });
  if (!r.ok) {
    log(`Token-Abruf fehlgeschlagen: HTTP ${r.status}`);
    return page(res, 502, "Anmeldung fehlgeschlagen (Token-Abruf).", { "Set-Cookie": clearFlow });
  }
  const tokens = await r.json();
  let claims;
  try {
    claims = await verifyIdToken(tokens.id_token, flow.nonce);
  } catch (e) {
    log(`ID-Token abgelehnt: ${e.message}`);
    return page(res, 403, "Anmeldung abgelehnt.", { "Set-Cookie": clearFlow });
  }
  const who = claims.email || claims.preferred_username || claims.sub;
  if (!isAllowed(claims)) {
    log(`Benutzer nicht freigegeben: ${String(who).slice(0, 120)} (${clientIp(req)})`);
    return page(res, 403, "Dieser Benutzer ist für den Hub nicht freigegeben.", { "Set-Cookie": clearFlow });
  }
  log(`Passkey-Anmeldung ok: ${String(who).slice(0, 120)}`);
  const session = sign({ sub: claims.sub, who: String(who).slice(0, 200), exp: Date.now() + CFG.sessionTtlMs });
  const target = RETURN_TO.test(flow.returnTo) ? flow.returnTo : "/";
  res.writeHead(302, {
    Location: target,
    "Set-Cookie": [clearFlow, cookie(SESSION_COOKIE, session, CFG.sessionTtlMs)],
    "Cache-Control": "no-store",
  });
  res.end();
}

/** Freigabeseite: Seite des Hubs holen, Passwortfeld durch Passkey-Hinweis ersetzen. */
async function showInteraction(req, res, session) {
  const up = await upstream(req);
  const type = headerOf(up.rawHeaders, "content-type") || "";
  const encoded = headerOf(up.rawHeaders, "content-encoding");
  let body = up.body;
  if (type.startsWith("text/html") && !encoded) {
    const html = body
      .toString("utf8")
      .replace(
        /<input type="password"[^>]*>/,
        `<p class="label">Angemeldet per Passkey</p>\n  <code class="target">${esc(session.who)}</code>`,
      )
      .replace(">Sign in</button>", ">Freigeben</button>");
    body = Buffer.from(html, "utf8");
  }
  res.writeHead(up.status, [...withoutHeaders(up.rawHeaders, ["content-length", "transfer-encoding", "connection"]), "Content-Length", String(body.length)]);
  res.end(body);
}

/** Login-POST: Hub-Passwort serverseitig einsetzen (überschreibt jedes mitgeschickte). */
async function submitLogin(req, res, session) {
  const raw = await readBody(req);
  const form = new URLSearchParams(raw.toString("utf8"));
  form.set("password", CFG.hubPassword);
  const body = Buffer.from(form.toString(), "utf8");
  req.headers["content-type"] = "application/x-www-form-urlencoded";
  const up = await upstream(req, body);
  log(`Freigabe abgeschickt für ${String(session.who).slice(0, 120)} → Hub HTTP ${up.status}`);
  res.writeHead(up.status, [...withoutHeaders(up.rawHeaders, ["content-length", "transfer-encoding", "connection"]), "Content-Length", String(up.body.length)]);
  res.end(up.body);
}

async function handle(req, res) {
  const url = new URL(req.url, "http://gate.invalid");
  const path = url.pathname;

  if (path === "/passkey/callback") {
    if (req.method !== "GET") return page(res, 405, "Methode nicht erlaubt.");
    return callback(req, res, url);
  }

  // Express routet ohne Beachtung der Groß-/Kleinschreibung und dekodiert
  // Prozentkodierung; damit /INTERACTION/… oder /%69nteraction/… nicht am Gate
  // vorbei zum Hub-Login gelangen, wird für die Entscheidung normalisiert.
  let norm;
  try {
    norm = decodeURIComponent(path).toLowerCase().replace(/\/{2,}/g, "/");
  } catch {
    return page(res, 400, "Ungültiger Pfad.");
  }
  if (!norm.startsWith("/interaction")) return proxy(req, res);
  const m = path.match(INTERACTION);
  if (!m) return page(res, 404, "Nicht gefunden.");

  const session = unsign(parseCookies(req.headers.cookie)[SESSION_COOKIE]);
  const sub = m[2]; // undefined | "" | "login" | "consent" | …

  if (!session) {
    if (req.method === "GET" && (sub === undefined || sub === "")) return startLogin(req, res, path);
    log(`${req.method} ${path} ohne Passkey-Sitzung abgewiesen (${clientIp(req)})`);
    return page(res, 403, "Passkey-Anmeldung erforderlich. Fenster schließen und erneut verbinden.");
  }

  if (req.method === "GET" && (sub === undefined || sub === "")) return showInteraction(req, res, session);
  if (req.method === "POST" && sub === "login") return submitLogin(req, res, session);
  if (req.method === "POST" && sub === "consent") return proxy(req, res);
  return page(res, 404, "Nicht gefunden.");
}

const server = http.createServer((req, res) => {
  handle(req, res).catch((e) => {
    log(`Fehler: ${e.message}`);
    if (!res.headersSent) page(res, 502, "Interner Fehler im Passkey-Gate.");
    else res.destroy();
  });
});
server.requestTimeout = 0; // MCP-Streams können lange offen sein
server.headersTimeout = 15_000;
server.keepAliveTimeout = 65_000;

server.listen(CFG.port, () => {
  log(`lauscht auf :${CFG.port} → Hub 127.0.0.1:${CFG.hubPort} | Anbieter ${CFG.issuer} | ${CFG.allowed.size} freigegebene(r) Benutzer`);
  getDiscovery().catch((e) => log(`WARNUNG: Discovery fehlgeschlagen: ${e.message}`));
});
