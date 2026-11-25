// smtp-mcp nach dem Patch: from je Aufruf, nur Adressen aus MBX_FROM_ADDRESSES.
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const dist = process.argv[2];
const imp = (f) => import(pathToFileURL(join(dist, f)).href);
const { registerSendTools } = await imp('tools/send.js');
const { loadConfig } = await imp('config.js');
const { RateLimiter } = await imp('ratelimit.js');
const { SentRegistry } = await imp('sent.js');

const ohne = process.argv[3] === 'ohne';
const config = loadConfig({
    SMTP_HOST: 'smtp.example.org', SMTP_USER: 'mail@ddsk.cloud', SMTP_PASSWORD: 'x',
    SMTP_FROM: 'David Kleinhans <mail@ddsk.cloud>', SMTP_ALLOWED_RECIPIENTS: '*', SMTP_ALLOW_SEND: 'true',
});
const gesendet = [];
let dialog;
const ctx = {
    config,
    client: { send: async ({ envelope, raw }) => { gesendet.push({ envelope, raw: raw.toString('utf8') }); return { accepted: envelope.to, rejected: [] }; } },
    limiter: new RateLimiter(100),
    sent: new SentRegistry(),
    approval: { requestApproval: async (server, mcp, conf, req) => { dialog = req; return { decision: 'approved' }; } },
    version: 'test',
};
const handler = {};
registerSendTools({ registerTool: (name, def, fn) => { handler[name] = { def, fn }; } }, ctx, undefined);

let fehler = 0;
const check = (ok, name) => { console.log(`${ok ? 'ok  ' : 'FEHL'} ${name}`); if (!ok) fehler += 1; };
let n = 0;
async function senden(werkzeug, args) {
    gesendet.length = 0;
    dialog = undefined;
    n += 1;   // anderer Text je Aufruf, sonst greift der Schutz gegen doppeltes Senden
    const parsed = handler[werkzeug].def.inputSchema.safeParse({ to: ['vermieter@example.org'], body: `Text ${n}`, ...args });
    if (!parsed.success) return { schemaFehler: parsed.error.issues.map((i) => i.path.join('.')).join(',') };
    const r = await handler[werkzeug].fn(parsed.data, {});
    const g = gesendet[0];
    const von = (dialog?.details ?? []).find((d) => d.label === 'From')?.value;
    return { r, text: (r.content ?? []).map((c) => c.text).join(''), g, von };
}

if (ohne) {
    let e = await senden('send_mail', { subject: 'Hallo', from: 'Mail@ddsk.cloud' });
    check(e.g?.envelope.from === 'mail@ddsk.cloud' && /^From: David Kleinhans <mail@ddsk\.cloud>$/m.test(e.g.raw),
        'ohne Liste: from = Adresse aus SMTP_FROM erlaubt, Name bleibt');
    e = await senden('send_mail', { subject: 'Hallo', from: 'dkleinhans@mailbox.org' });
    check(e.r?.isError === true && e.g === undefined, 'ohne Liste: andere Adresse abgelehnt');
    console.log(fehler ? `${fehler} Fehler` : 'alle Prüfungen bestanden');
    process.exit(fehler ? 1 : 0);
}
let e = await senden('send_mail', { subject: 'Hallo' });
check(e.g?.envelope.from === 'mail@ddsk.cloud' && /^From: David Kleinhans <mail@ddsk\.cloud>$/m.test(e.g.raw), 'ohne from: SMTP_FROM wie bisher');
e = await senden('send_mail', { subject: 'Hallo', from: 'DKleinhans@mailbox.org' });
check(e.g?.envelope.from === 'dkleinhans@mailbox.org' && /^From: David Kleinhans <dkleinhans@mailbox\.org>$/m.test(e.g.raw),
    'send_mail mit from: Kopfzeile und Umschlag');
check(e.von === '"David Kleinhans" <dkleinhans@mailbox.org>', 'Bestätigungsdialog nennt denselben Absender');
check(/@mailbox\.org>$/m.test((e.g?.raw.match(/^Message-ID: .*$/m) ?? [''])[0]), 'Message-ID mit Domain des Absenders');
e = await senden('reply_mail', { original_subject: 'Wohnung', in_reply_to: '<hux@outlook.com>', from: 'dkleinhans@mailbox.org' });
check(e.g?.envelope.from === 'dkleinhans@mailbox.org' && /^In-Reply-To: <hux@outlook\.com>$/m.test(e.g.raw), 'reply_mail mit from');
e = await senden('forward_mail', { original_subject: 'Wohnung', quote: 'alt', from: 'mail@ddsk.cloud' });
check(e.g?.envelope.from === 'mail@ddsk.cloud', 'forward_mail mit from');
e = await senden('send_mail', { subject: 'Hallo', from: 'chef@firma.de' });
check(e.r?.isError === true && e.g === undefined && e.von === undefined && /not one of the configured/.test(e.text),
    'from nicht erlaubt: nichts gesendet, kein Dialog');
e = await senden('send_mail', { subject: 'Hallo', from: 'dkleinhans@mailbox.org\r\nBcc: x@y.z' });
check(e.r?.isError === true && e.g === undefined, 'from mit Umbruch: nichts gesendet');
e = await senden('send_mail', { subject: 'Hallo' });
check(e.g?.envelope.from === 'mail@ddsk.cloud', 'danach wieder SMTP_FROM (keine Änderung an der gemeinsamen Konfiguration)');

console.log(fehler ? `${fehler} Fehler` : 'alle Prüfungen bestanden');
process.exit(fehler ? 1 : 0);
