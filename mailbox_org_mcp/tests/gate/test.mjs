// Browser-Simulation gegen Gate (:8099) mit Mock-IdP und Mock-Hub.
const G = "http://127.0.0.1:8099";
let fails = 0;
const ok = (cond, msg) => { console.log(`${cond ? "PASS" : "FAIL"}  ${msg}`); if (!cond) fails++; };

function jar() {
  const store = new Map();
  return {
    header: () => [...store].map(([k, v]) => `${k}=${v}`).join("; "),
    take: (res) => { for (const c of res.headers.getSetCookie()) { const [kv, ...attrs] = c.split(";"); const i = kv.indexOf("="); const k = kv.slice(0, i).trim(); const v = kv.slice(i + 1); if (attrs.some((a) => /max-age=0/i.test(a))) store.delete(k); else store.set(k, v); } },
    has: (k) => store.has(k),
  };
}
async function get(j, url, opts = {}) {
  const r = await fetch(url, { redirect: "manual", ...opts, headers: { cookie: j.header(), ...(opts.headers || {}) } });
  j.take(r);
  return r;
}
const mode = (m) => fetch("http://127.0.0.1:9000/mode", { method: "POST", body: JSON.stringify(m) });

async function fullLogin(j, uid) {
  let r = await get(j, `${G}/interaction/${uid}/`);
  if (r.status !== 302) return { step: "gate-start", r };
  r = await get(j, r.headers.get("location")); // IdP authorize → redirect zu callback
  if (r.status !== 302) return { step: "idp", r };
  r = await get(j, r.headers.get("location")); // Gate-Callback
  return { step: "callback", r };
}

// 1) Durchreichen ohne Sitzung: /token und SSE /hub
{
  const r = await fetch(`${G}/token`, { method: "POST", body: "grant_type=x", headers: { "content-type": "application/x-www-form-urlencoded" } });
  ok(r.status === 200 && (await r.json()).echoed === "grant_type=x", "/token wird unverändert durchgereicht");
  ok((r.headers.get("x-seen-xff") || "").includes("127.0.0.1"), "X-Forwarded-For wird gesetzt");
  const t0 = Date.now();
  const s = await fetch(`${G}/hub`);
  const reader = s.body.getReader();
  const first = await reader.read();
  const tFirst = Date.now() - t0;
  let rest = ""; for (;;) { const { done, value } = await reader.read(); if (done) break; rest += Buffer.from(value).toString(); }
  ok(tFirst < 250 && Buffer.from(first.value).toString().includes("one") && rest.includes("three"), `SSE ungepuffert (erstes Event nach ${tFirst} ms)`);
}

// 2) Login-POST ohne Sitzung wird abgewiesen, auch mit richtigem Passwort
{
  const r = await fetch(`${G}/interaction/abc/login`, { method: "POST", body: "password=hub-pw&request=abc", headers: { "content-type": "application/x-www-form-urlencoded" }, redirect: "manual" });
  ok(r.status === 403, "Login-POST ohne Passkey-Sitzung → 403");
  const c = await fetch(`${G}/interaction/abc/consent`, { method: "POST", body: "x=1", redirect: "manual" });
  ok(c.status === 403, "Consent-POST ohne Passkey-Sitzung → 403");
  const g = await fetch(`${G}/interaction/abc/`, { redirect: "manual" });
  ok(g.status === 302 && g.headers.get("location").startsWith("http://127.0.0.1:9000/authorize?"), "GET Interaktion ohne Sitzung → Umleitung zum IdP");
}

// 3) Voller Ablauf
{
  await mode({ email: "david@example.org", badSig: false, wrongAud: false, wrongNonce: false });
  const j = jar();
  const { step, r } = await fullLogin(j, "uid1");
  ok(step === "callback" && r.status === 302 && r.headers.get("location") === "/interaction/uid1/", `Callback → zurück zur Interaktion (${step} ${r.status} ${r.headers.get("location")})`);
  ok(j.has("mbx_gate") && !j.has("mbx_gate_flow"), "Sitzungs-Cookie gesetzt, Flow-Cookie gelöscht");
  const p = await get(j, `${G}/interaction/uid1/`);
  const html = await p.text();
  ok(p.status === 200 && !html.includes('type="password"') && html.includes("david@example.org") && html.includes("Freigeben"), "Freigabeseite ohne Passwortfeld, mit Passkey-Hinweis");
  ok((p.headers.get("content-security-policy") || "").includes("https://ai.example"), "CSP des Hubs bleibt erhalten");
  ok(j.has("_interaction"), "Interaktions-Cookie des Hubs kommt durch");
  const s = await get(j, `${G}/interaction/uid1/login`, { method: "POST", body: "request=uid1&password=falsch", headers: { "content-type": "application/x-www-form-urlencoded" } });
  ok(s.status === 303 && s.headers.get("location") === "/authorize/uid1", `Login-POST: Hub-Passwort eingesetzt, mitgeschicktes überschrieben (HTTP ${s.status})`);
  ok(s.headers.getSetCookie().length === 2, "Beide Set-Cookie-Header des Hubs kommen durch");
}

// 4) Ablehnungen
for (const [name, m] of [
  ["fremde E-Mail", { email: "evil@example.org" }],
  ["kaputte Signatur", { email: "david@example.org", badSig: true }],
  ["falsche aud", { badSig: false, wrongAud: true }],
  ["falsche nonce", { wrongAud: false, wrongNonce: true }],
]) {
  await mode(m);
  const j = jar();
  const { step, r } = await fullLogin(j, "uid2");
  ok(step === "callback" && r.status === 403 && !j.has("mbx_gate"), `${name} → 403, keine Sitzung`);
}
await mode({ email: "david@example.org", badSig: false, wrongAud: false, wrongNonce: false });

// 5) Manipulierte Cookies / state
{
  const j = jar();
  let r = await get(j, `${G}/interaction/uid3/`);
  r = await get(j, r.headers.get("location"));
  const cb = new URL(r.headers.get("location"));
  cb.searchParams.set("state", "falsch");
  r = await get(j, cb.toString());
  ok(r.status === 400 && !j.has("mbx_gate"), "falscher state → 400");
  const forged = await fetch(`${G}/interaction/uid3/`, { headers: { cookie: "mbx_gate=eyJzdWIiOiJ4IiwiZXhwIjo5OTk5OTk5OTk5OTk5fQ.AAAA" }, redirect: "manual" });
  ok(forged.status === 302, "gefälschtes Sitzungs-Cookie wird ignoriert");
  const traversal = await fetch(`${G}/interaction/../hub`, { redirect: "manual" });
  ok(traversal.status !== 500, `Pfad mit .. führt nicht zu Fehler (HTTP ${traversal.status})`);
}

// 6) Umgehungsversuche über Pfad-Varianten (roh, ohne URL-Normalisierung von fetch)
{
  const http = await import("node:http");
  const raw = (path) => new Promise((resolve) => {
    const r = http.request({ host: "127.0.0.1", port: 8099, method: "POST", path, headers: { "content-type": "application/x-www-form-urlencoded" } }, (res) => { res.resume(); resolve(res.statusCode); });
    r.end("password=hub-pw&request=abc");
  });
  for (const p of ["/INTERACTION/abc/login", "/%69nteraction/abc/login", "//interaction/abc/login", "/interaction/abc/login/", "/Interaction/abc/Login", "/interaction/abc/%6Cogin", "/interaction/%2e%2e/login"]) {
    const s = await raw(p);
    ok(s === 403 || s === 404 || s === 400, `${p} → ${s} (nicht zum Hub durchgereicht)`);
  }
}

console.log(fails ? `\n${fails} FEHLER` : "\nalle Tests bestanden");
process.exit(fails ? 1 : 0);
