// Entrypoint: reads Home Assistant add-on options, writes mcp-hub's mcp.json,
// drops root and starts mcp-hub. Secrets are passed via the hub's environment
// and expanded by mcp-hub (${VAR}); they are never written into mcp.json.
// With internal_access, each enabled server is additionally offered without
// login through mcp_bridge.py (common/ of this repo) on 9081–9085, internal
// Docker network only.
import { chownSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";

const OPTIONS = process.env.OPTIONS_PATH || "/data/options.json";
const DATA = process.env.DATA_DIR || "/data";
const HUB_DATA = `${DATA}/hub`;
const GATE_DATA = `${DATA}/gate`;
const BRIDGE = process.env.BRIDGE_PATH || "/app/mcp_bridge.py";
// Interne Ports je Dienst (öffentlicher Port 8099 bleibt der Hub/das Gate).
const BRIDGE_PORTS = { mail: 9081, smtp: 9082, calendar: 9083, contacts: 9084, drive: 9085 };
const CONFIG_DIR = `${DATA}/hub-config`;
const CONFIG = `${CONFIG_DIR}/mcp.json`;
const NODE_UID = 1000;
const NODE_GID = 1000;
const DRY_RUN = process.argv.includes("--dry-run");

const log = (m) => console.error(`[mailbox-org-mcp] ${m}`);
const fail = (m) => {
  log(`FEHLER: ${m}`);
  process.exit(1);
};

const raw = JSON.parse(readFileSync(OPTIONS, "utf8"));
// URL, Hub-Passwort und Passkey stehen im optionalen Abschnitt "public".
const o = { ...raw, ...(raw.public || {}) };
const str = (v) => (typeof v === "string" ? v.trim() : "");

const email = str(o.email);
const appPassword = str(o.app_password);
// mailbox.org vergibt Passwörter je Anwendungstyp: Kalender/Adressbuch brauchen
// ein eigenes "CalDAV/CardDAV"-Anwendungspasswort. Ohne Angabe gilt app_password.
const davPassword = str(o.dav_password) || appPassword;
const hubPassword = str(o.hub_password);
const externalUrl = str(o.external_url).replace(/\/+$/, "");

// Öffentlicher Zugang (mcp-hub, optional mit Passkey-Gate) nur mit external_url.
const publicAccess = externalUrl !== "";

if (!email || !appPassword) fail("'email' und 'app_password' sind Pflicht.");
if (!publicAccess && o.internal_access !== true)
  fail("Kein Zugang aktiviert: 'internal_access' einschalten oder unter „Öffentlicher Zugang“ eine externe URL eintragen.");
if (publicAccess) {
  if (!/^https:\/\/[^/]+$/.test(externalUrl))
    fail("'external_url' muss eine https-URL ohne Pfad sein, z. B. https://mcp.example.net");
  if (!hubPassword) fail("'hub_password' ist mit externer URL Pflicht (Login für den Hub).");
}

const essential = o.essential_tools !== false;
const servers = {};

// --- Arbeitsordner (optional) ----------------------------------------------
// Gemeinsamer Ordner mit ArtCraft, Foto MCP und Open Terminal. Die Mail-App nutzt darin
// nur mbox/: Anhänge landen in mbox/inbox/, Anhänge zum Senden kommen aus mbox/outbox/,
// Drive kopiert in beide Richtungen. Die Server laufen als uid 1000 und brauchen dort
// Schreibrechte.
const workDir = str(o.work_dir).replace(/\/+$/, "");
if (workDir && !/^\/share(\/[^\s]+)?$/.test(workDir)) fail("'work_dir' muss /share oder ein Ordner darunter sein, z. B. /share/artcraft/work");
const mboxDir = workDir && `${workDir}/mbox`;

// --- Mail lesen (IMAP) ---------------------------------------------------
if (o.mail_enabled) {
  const env = {
    IMAP_HOST: "imap.mailbox.org",
    IMAP_PORT: "993",
    IMAP_TLS: "implicit",
    IMAP_USER: "${MBX_EMAIL}",
    IMAP_PASSWORD: "${MBX_PASSWORD}",
    // imap-mcp: nur das Literal "false" schaltet Schreib-Tools frei
    IMAP_READ_ONLY: o.mail_write ? "false" : "true",
  };
  if (workDir) env.IMAP_DOWNLOAD_DIR = `${mboxDir}/inbox`;
  // "essential" enthält kein save_draft; mit Schreibrecht kommt es dazu (Entwurf bleibt im
  // Postfach, nichts wird versendet), mit Arbeitsordner get_attachments.
  if (essential)
    env.IMAP_ALLOW_TOOLS = ["essential", workDir && "get_attachments", o.mail_write && "save_draft"]
      .filter(Boolean)
      .join(",");
  if (str(o.imap_trusted_authserv_id)) env.IMAP_TRUSTED_AUTHSERV_ID = str(o.imap_trusted_authserv_id);
  servers.mail = { command: "imap-mcp", args: [], env };
}

// --- Mail senden (SMTP) --------------------------------------------------
if (o.smtp_enabled) {
  const name = str(o.smtp_from_name);
  const env = {
    SMTP_HOST: "smtp.mailbox.org",
    SMTP_PORT: "587",
    SMTP_TLS: "starttls",
    SMTP_USER: "${MBX_EMAIL}",
    SMTP_PASSWORD: "${MBX_PASSWORD}",
    SMTP_FROM: name ? `${name} <${email}>` : email,
    SMTP_ALLOW_SEND: o.smtp_allow_send ? "true" : "false",
  };
  if (o.smtp_allow_send) {
    const rcpt = str(o.smtp_allowed_recipients);
    if (!rcpt) fail("'smtp_allow_send' braucht 'smtp_allowed_recipients' (Adressen/@domains, '*' = alle).");
    env.SMTP_ALLOWED_RECIPIENTS = rcpt;
  }
  if (workDir) env.SMTP_ATTACHMENT_DIR = `${mboxDir}/outbox`;
  if (essential) env.SMTP_ALLOW_TOOLS = "essential";
  servers.smtp = { command: "smtp-mcp", args: [], env };
}

// --- Kalender (CalDAV) ---------------------------------------------------
if (o.calendar_enabled) {
  const env = {
    CALDAV_URL: "https://dav.mailbox.org/",
    CALDAV_USERNAME: "${MBX_EMAIL}",
    CALDAV_PASSWORD: "${MBX_DAV_PASSWORD}",
    CALDAV_TIMEZONE: str(o.timezone) || "Europe/Berlin",
    CALDAV_USER_EMAIL: email,
    CALDAV_READ_ONLY: o.calendar_write ? "false" : "true",
  };
  if (essential) env.CALDAV_ALLOW_TOOLS = "essential";
  servers.calendar = { command: "caldav-mcp", args: [], env };
}

// --- Adressbuch (CardDAV) ------------------------------------------------
if (o.contacts_enabled) {
  const env = {
    CARDDAV_URL: "https://dav.mailbox.org/",
    CARDDAV_USERNAME: "${MBX_EMAIL}",
    CARDDAV_PASSWORD: "${MBX_DAV_PASSWORD}",
    CARDDAV_READ_ONLY: o.contacts_write ? "false" : "true",
  };
  if (essential) env.CARDDAV_ALLOW_TOOLS = "essential";
  servers.contacts = { command: "carddav-mcp", args: [], env };
}

// --- Drive (WebDAV) ------------------------------------------------------
// Eigener kleiner Server (webdav/webdav-mcp.mjs): nur lesen, solange
// drive_write aus ist; Löschen/Verschieben gibt es nicht.
const webdavPassword = str(o.webdav_password);
if (o.drive_enabled) {
  if (!webdavPassword) fail("'drive_enabled' braucht 'webdav_password' (mailbox.org-Anwendungspasswort vom Typ „WebDAV-Client“).");
  const env = {
    WEBDAV_URL: "https://dav.mailbox.org/servlet/webdav.infostore",
    WEBDAV_USERNAME: "${MBX_EMAIL}",
    WEBDAV_PASSWORD: "${MBX_WEBDAV_PASSWORD}",
    WEBDAV_ROOT: str(o.drive_root) || "/",
    WEBDAV_READ_ONLY: o.drive_write ? "false" : "true",
  };
  if (workDir) env.WORK_DIR = mboxDir;
  servers.drive = { command: "node", args: ["/app/webdav/webdav-mcp.mjs"], env };
}

if (Object.keys(servers).length === 0) fail("Kein Dienst aktiviert.");

// --- Passkey-Gate (optional) ---------------------------------------------
const passkey = publicAccess && o.passkey_enabled === true;
const oidcIssuer = str(o.oidc_issuer).replace(/\/+$/, "");
const oidcClientId = str(o.oidc_client_id);
const oidcClientSecret = str(o.oidc_client_secret);
const allowedUsers = str(o.passkey_allowed_users);
if (passkey) {
  if (!/^https:\/\/[^/?#]+(\/[^?#]*)?$/.test(oidcIssuer)) fail("'oidc_issuer' muss eine https-URL sein, z. B. https://id.example.net");
  if (!oidcClientId || !oidcClientSecret) fail("'oidc_client_id' und 'oidc_client_secret' sind bei 'passkey_enabled' Pflicht.");
  if (!allowedUsers) fail("'passkey_allowed_users' ist bei 'passkey_enabled' Pflicht (E-Mail-Adressen oder Benutzernamen, kommagetrennt).");
}

const config = JSON.stringify({ mcpServers: servers }, null, 2) + "\n";

// --- Interner Zugriff ohne Login (optional) ------------------------------
// Je Dienst eine mcp_bridge.py (stdio → Streamable HTTP unter /mcp) im
// internen Netz von Home Assistant, z. B. für Open WebUI auf demselben Gerät.
// Die Ports stehen nicht in config.yaml und werden nie auf den Host gelegt.
// Die Brücke bekommt die Umgebung des Dienstes mit bereits eingesetzten
// Secrets, weil hier kein mcp-hub die ${VAR}-Platzhalter auflöst.
const internal = o.internal_access === true;
// Token für den internen Zugriff: nur die Brücke liest es und gibt es nicht an die Dienste weiter.
const bridgeToken = str(o.internal_token);
const secrets = {
  MBX_EMAIL: email,
  MBX_PASSWORD: appPassword,
  MBX_DAV_PASSWORD: davPassword,
  MBX_WEBDAV_PASSWORD: webdavPassword,
};
const expand = (v) => String(v).replace(/\$\{(\w+)\}/g, (_, k) => secrets[k] ?? "");
const bridges = internal
  ? Object.entries(servers).map(([name, s]) => ({
      name,
      port: BRIDGE_PORTS[name],
      cmd: [s.command, ...s.args],
      env: Object.fromEntries(Object.entries(s.env).map(([k, v]) => [k, expand(v)])),
    }))
  : [];
const host = (() => {
  try { return readFileSync("/etc/hostname", "utf8").trim(); } catch { return "<add-on-hostname>"; }
})();
for (const b of bridges)
  log(bridgeToken
    ? `${b.name}: intern unter http://${host}:${b.port}/mcp (Bearer-Token nötig)`
    : `${b.name}: intern ohne Login unter http://${host}:${b.port}/mcp (Achtung: ohne Token, internal_token setzen)`);

if (DRY_RUN) {
  process.stdout.write(config);
  process.exit(0);
}


for (const dir of [HUB_DATA, CONFIG_DIR, GATE_DATA]) {
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true, mode: 0o700 });
  chownSync(dir, NODE_UID, NODE_GID);
}
writeFileSync(CONFIG, config, { mode: 0o644 });

if (workDir) {
  for (const d of ["inbox", "outbox"]) mkdirSync(`${mboxDir}/${d}`, { recursive: true });
  // Schreibrechte für uid 1000 nur auf mbox/, auch als Vorgabe für später angelegte Dateien.
  const acl = spawnSync("setfacl", ["-R", "-m", `u:${NODE_UID}:rwX`, "-m", `d:u:${NODE_UID}:rwX`, mboxDir], { stdio: "ignore" });
  if (acl.status === 0) log(`Arbeitsordner: ${mboxDir} (inbox/, outbox/, Rechte per ACL)`);
  else {
    for (const d of ["", "/inbox", "/outbox"]) chownSync(`${mboxDir}${d}`, NODE_UID, NODE_GID);
    log(`Arbeitsordner: ${mboxDir} (ohne ACL, gehört uid ${NODE_UID})`);
  }
}
log(`Dienste: ${Object.keys(servers).join(", ")} | Werkzeugauswahl: ${essential ? "essential" : "alle"}`);

// Ohne Gate lauscht der Hub direkt auf 8099. Mit Gate lauscht das Gate auf
// 8099 und der Hub intern auf 8100; das Gate ist dann der einzige direkte
// Proxy des Hubs und wird über "loopback" als vertrauenswürdig eingetragen.
const hubPort = passkey ? "8100" : "8099";
const trusted = [passkey ? "loopback" : "", str(o.trusted_proxies)].filter(Boolean).join(",");

const base = { PATH: process.env.PATH, HOME: "/home/node", NODE_ENV: "production" };
const hubEnv = {
  ...base,
  PORT: hubPort,
  CONFIG_PATH: CONFIG,
  DATA_PATH: HUB_DATA,
  EXTERNAL_URL: externalUrl,
  PASSWORD: hubPassword,
  MBX_EMAIL: email,
  MBX_PASSWORD: appPassword,
  MBX_DAV_PASSWORD: davPassword,
  MBX_WEBDAV_PASSWORD: webdavPassword,
};
if (trusted) hubEnv.TRUSTED_PROXIES = trusted;

const children = [];
const asNode = (args, env, name) => {
  const c = spawn("setpriv", [`--reuid=${NODE_UID}`, `--regid=${NODE_GID}`, "--init-groups", "--", ...args], {
    env,
    stdio: "inherit",
    cwd: "/app",
  });
  c.on("exit", (code, signal) => {
    log(`${name} beendet (code=${code}, signal=${signal}) – Add-on wird beendet.`);
    stopping = true;
    for (const other of [...children, ...bridgeProcs]) if (other !== c && other.exitCode === null) other.kill("SIGTERM");
    process.exit(code ?? (signal ? 1 : 0));
  });
  children.push(c);
};

// Root ablegen: Hub, Gate und alle Kindprozesse laufen als node (uid 1000)
if (publicAccess) {
  asNode(["node", "/app/dist/index.js"], hubEnv, "mcp-hub");
  log(`Öffentlich über ${externalUrl} (${passkey ? "Passkey" : "Hub-Passwort"})`);
} else {
  log("Kein öffentlicher Zugang (keine externe URL), nur intern");
}

if (passkey) {
  const secretFile = `${GATE_DATA}/secret`;
  if (!existsSync(secretFile)) writeFileSync(secretFile, randomBytes(48), { mode: 0o600 });
  chownSync(secretFile, NODE_UID, NODE_GID);
  asNode(
    ["node", "/app/gate.mjs"],
    {
      ...base,
      GATE_PORT: "8099",
      HUB_PORT: hubPort,
      EXTERNAL_URL: externalUrl,
      OIDC_ISSUER: oidcIssuer,
      OIDC_CLIENT_ID: oidcClientId,
      OIDC_CLIENT_SECRET: oidcClientSecret,
      GATE_ALLOWED_USERS: allowedUsers,
      HUB_PASSWORD: hubPassword,
      GATE_SECRET_FILE: secretFile,
    },
    "passkey-gate",
  );
  log(`Passkey-Gate aktiv (${oidcIssuer}); Callback-URL für den Anbieter: ${externalUrl}/passkey/callback`);
}

// Brücken: Beendet sich eine (z. B. weil ihr Server abstürzt), startet nur sie
// neu – nach 5 s, bei wiederholtem Sofort-Absturz mit wachsender Pause bis
// 60 s. Hub und Gate laufen weiter (anders als bei asNode oben).
let stopping = false;
const bridgeProcs = new Set();
const superviseBridge = (b, pause = 5) => {
  const started = Date.now();
  const c = spawn(
    "setpriv",
    [`--reuid=${NODE_UID}`, `--regid=${NODE_GID}`, "--init-groups", "--", "python3", BRIDGE, String(b.port), "--", ...b.cmd],
    { env: { ...base, ...b.env, ...(bridgeToken ? { BRIDGE_TOKEN: bridgeToken } : {}) }, stdio: "inherit", cwd: "/app" },
  );
  bridgeProcs.add(c);
  c.on("exit", (code, signal) => {
    bridgeProcs.delete(c);
    if (stopping) return;
    const next = Date.now() - started > 60_000 ? 5 : Math.min(pause * 2, 60);
    log(`${b.name}:intern beendet (code=${code}, signal=${signal}), Neustart in ${next} s`);
    setTimeout(() => superviseBridge(b, next), next * 1000);
  });
};
for (const b of bridges) superviseBridge(b);

for (const sig of ["SIGTERM", "SIGINT"])
  process.on(sig, () => {
    stopping = true;
    for (const c of [...children, ...bridgeProcs]) c.kill(sig);
  });
