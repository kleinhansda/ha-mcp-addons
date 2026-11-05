// Mock-IdP (:9000) und Mock-Hub (:8100) für den Gate-Test.
import http from "node:http";
import crypto from "node:crypto";

const ALG = process.env.MOCK_ALG || "RS256";
const { publicKey, privateKey } =
  ALG === "ES256"
    ? crypto.generateKeyPairSync("ec", { namedCurve: "P-256" })
    : ALG === "EdDSA"
      ? crypto.generateKeyPairSync("ed25519")
      : crypto.generateKeyPairSync("rsa", { modulusLength: 2048 });
const jwk = { ...publicKey.export({ format: "jwk" }), kid: "k1", use: "sig", alg: ALG };
const b64u = (b) => Buffer.from(b).toString("base64url");
const ISS = "http://127.0.0.1:9000";
const codes = new Map();
export const mode = { email: "david@example.org", badSig: false, wrongAud: false, wrongNonce: false };

function signJwt(payload) {
  const h = b64u(JSON.stringify({ alg: ALG, kid: "k1", typ: "JWT" }));
  const p = b64u(JSON.stringify(payload));
  const data = Buffer.from(`${h}.${p}`);
  let sig =
    ALG === "ES256"
      ? crypto.sign("sha256", data, { key: privateKey, dsaEncoding: "ieee-p1363" })
      : ALG === "EdDSA"
        ? crypto.sign(null, data, privateKey)
        : crypto.sign("sha256", data, privateKey);
  if (mode.badSig) sig = Buffer.from(sig.map((x, i) => (i === 5 ? x ^ 1 : x)));
  return `${h}.${p}.${b64u(sig)}`;
}

const body = (req) => new Promise((r) => { const c = []; req.on("data", (d) => c.push(d)); req.on("end", () => r(Buffer.concat(c).toString())); });

http
  .createServer(async (req, res) => {
    const u = new URL(req.url, ISS);
    if (u.pathname === "/.well-known/openid-configuration") {
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ issuer: ISS, authorization_endpoint: `${ISS}/authorize`, token_endpoint: `${ISS}/token`, jwks_uri: `${ISS}/jwks`, token_endpoint_auth_methods_supported: ["client_secret_basic", "client_secret_post"] }));
    }
    if (u.pathname === "/jwks") { res.writeHead(200, { "Content-Type": "application/json" }); return res.end(JSON.stringify({ keys: [jwk] })); }
    if (u.pathname === "/authorize") {
      const q = u.searchParams;
      if (q.get("code_challenge_method") !== "S256" || q.get("client_id") !== "gate-client") { res.writeHead(400); return res.end("bad authorize"); }
      const code = crypto.randomBytes(8).toString("hex");
      codes.set(code, { nonce: q.get("nonce"), challenge: q.get("code_challenge"), redirect: q.get("redirect_uri") });
      res.writeHead(302, { Location: `${q.get("redirect_uri")}?code=${code}&state=${encodeURIComponent(q.get("state"))}&iss=${encodeURIComponent(ISS)}` });
      return res.end();
    }
    if (u.pathname === "/token" && req.method === "POST") {
      const f = new URLSearchParams(await body(req));
      const auth = Buffer.from((req.headers.authorization || "").replace("Basic ", ""), "base64").toString();
      const c = codes.get(f.get("code"));
      codes.delete(f.get("code"));
      const verOk = c && b64u(crypto.createHash("sha256").update(f.get("code_verifier") || "").digest()) === c.challenge;
      if (auth !== "gate-client:s3cret" || !verOk || f.get("redirect_uri") !== c.redirect) { res.writeHead(400, { "Content-Type": "application/json" }); return res.end(JSON.stringify({ error: "invalid_grant", auth, verOk })); }
      const now = Math.floor(Date.now() / 1000);
      const id_token = signJwt({ iss: ISS, sub: "uid-123", aud: mode.wrongAud ? "other" : "gate-client", exp: now + 300, iat: now, nonce: mode.wrongNonce ? "x" : c.nonce, email: mode.email, email_verified: true });
      res.writeHead(200, { "Content-Type": "application/json" });
      return res.end(JSON.stringify({ access_token: "at", token_type: "Bearer", id_token }));
    }
    if (u.pathname === "/mode" && req.method === "POST") { Object.assign(mode, JSON.parse(await body(req))); res.writeHead(204); return res.end(); }
    res.writeHead(404); res.end();
  })
  .listen(9000);

// --- Mock-Hub, bildet login-page.ts / interactions.ts nach -------------------
http
  .createServer(async (req, res) => {
    const u = new URL(req.url, "http://hub");
    res.setHeader("X-Seen-XFF", req.headers["x-forwarded-for"] || "");
    let m = u.pathname.match(/^\/interaction\/([^/]+)\/$/);
    if (m && req.method === "GET") {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": "default-src 'none'; form-action 'self' https://ai.example", "Set-Cookie": `_interaction=${m[1]}; Path=/interaction/${m[1]}/; HttpOnly` });
      return res.end(`<form method="post" action="login">\n  <h1>mcp-hub</h1>\n  <input type="password" name="password" placeholder="Password" autofocus required autocomplete="current-password">\n  <input type="hidden" name="request" value="${m[1]}">\n  <button type="submit">Sign in</button>\n</form>`);
    }
    m = u.pathname.match(/^\/interaction\/([^/]+)\/login$/);
    if (m && req.method === "POST") {
      const f = new URLSearchParams(await body(req));
      const cookieOk = (req.headers.cookie || "").includes(`_interaction=${m[1]}`);
      if (f.get("password") === "hub-pw" && f.get("request") === m[1] && cookieOk) {
        res.writeHead(303, { Location: `/authorize/${m[1]}`, "Set-Cookie": ["__Host-mcp_hub_session=abc; Path=/; HttpOnly", "_session=x; Path=/"] });
        return res.end();
      }
      res.writeHead(401, { "Content-Type": "text/plain" }); return res.end(`wrong password=${f.get("password")} cookieOk=${cookieOk}`);
    }
    if (u.pathname === "/hub") {
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.write("data: one\n\n");
      setTimeout(() => res.write("data: two\n\n"), 300);
      setTimeout(() => res.end("data: three\n\n"), 600);
      return;
    }
    if (u.pathname === "/token" && req.method === "POST") {
      const b = await body(req);
      res.writeHead(200, { "Content-Type": "application/json" }); return res.end(JSON.stringify({ echoed: b }));
    }
    res.writeHead(404); res.end("hub 404");
  })
  .listen(process.env.MOCK_HUB === "0" ? 0 : 8100);
console.log(`mocks up (${ALG})`);
