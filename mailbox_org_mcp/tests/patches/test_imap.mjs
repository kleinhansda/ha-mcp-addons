// imap-mcp nach dem Patch: save_draft mit Verlauf (in_reply_to/references) und Absender, reply_sender.
// Aufruf: node test_imap.mjs <dist> [ohne]  ("ohne" = ohne MBX_FROM_ADDRESSES, Anmeldename als Absender)
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const dist = process.argv[2];
const ohne = process.argv[3] === 'ohne';
const { registerWriteTools } = await import(pathToFileURL(join(dist, 'tools', 'write.js')).href);
const { ToolInputError } = await import(pathToFileURL(join(dist, 'errors.js')).href);
const { WRITE_TOOLS } = await import(pathToFileURL(join(dist, 'tools', 'catalogue.js')).href);

// Nachgebautes Postfach: Message-ID -> Ordner und Umschlag
const POST = {
    INBOX: [{ uid: 17900, id: '<hux@outlook.com>', envelope: { from: [{ address: 'ma.huxhagen@bossert.de' }], to: [{ address: 'DKleinhans@mailbox.org' }] } },
        { uid: 17901, id: '<news@x.org>', envelope: { from: [{ address: 'news@x.org' }], to: [{ address: 'liste@x.org' }] } }],
    Gesendet: [{ uid: 5, id: '<eigen@ddsk.cloud>', envelope: { from: [{ address: 'mail@ddsk.cloud' }], to: [{ address: 'freund@x.org' }] } },
        { uid: 6, id: '<alias@mailbox.org>', envelope: { from: [{ address: 'DKleinhans@mailbox.org' }], to: [{ address: 'hux@x.org' }] } }],
};
let suchFehler = false;
const angehaengt = [];
const client = {
    user: 'mail@ddsk.cloud',
    defaultMailbox: 'INBOX',
    listMailboxes: async () => ({ mailboxes: [{ path: 'INBOX' }, { path: 'Gesendet', specialUse: '\\Sent' }, { path: 'Drafts', specialUse: '\\Drafts' }] }),
    withMailbox: async (folder, readOnly, fn) => fn({
        folder: folder ?? 'INBOX',
        mailbox: { permanentFlags: new Set(['\\Draft', '\\Seen']) },
        append: async (f, raw, flags) => { angehaengt.push({ f, raw: raw.toString('utf8'), flags }); },
    }),
    search: async (c, query) => {
        if (suchFehler) throw new Error('SEARCH kaputt');
        if (query.all) return (POST[c.folder] ?? []).map((m) => m.uid);
        const id = query.header['message-id'];
        return (POST[c.folder] ?? []).filter((m) => m.id === id).map((m) => m.uid);
    },
    fetchSummaries: async (c, uids) => (POST[c.folder] ?? []).filter((m) => uids.includes(m.uid)).map((m) => ({ uid: m.uid, envelope: m.envelope })),
    threadHeaders: async (mailbox, uid) => {
        const m = (POST[mailbox ?? 'INBOX'] ?? []).find((x) => x.uid === uid);
        if (!m) throw new ToolInputError(`imap-mcp: no message with UID ${uid} in this mailbox.`);
        return { messageId: m.id, references: [m.id] };
    },
};
// Fehlerprotokoll mitschneiden
const protokoll = [];
const consoleError = console.error;
console.error = (...a) => { const t = a.join(' '); if (t.includes('FEHLER')) protokoll.push(t); else consoleError(...a); };
const handler = {};
registerWriteTools({ registerTool: (name, def, fn) => { handler[name] = { def, fn }; } }, client,
    { imap: { draftsMailbox: 'Drafts' } }, undefined, undefined);

let fehler = 0;
const check = (ok, name) => { console.log(`${ok ? 'ok  ' : 'FEHL'} ${name}`); if (!ok) fehler += 1; };
const basis = { to: ['vermieter@example.org'], subject: 'AW: Wohnung', body: 'Guten Tag,\nanbei.' };
async function rufen(werkzeug, args) {
    angehaengt.length = 0;
    const parsed = handler[werkzeug].def.inputSchema.safeParse(args);
    if (!parsed.success) return { schemaFehler: true, raw: '' };
    const r = await handler[werkzeug].fn(parsed.data);
    return { r, sc: r.structuredContent, text: (r.content ?? []).map((c) => c.text).join(''), raw: angehaengt[0]?.raw ?? '' };
}
const draft = (args) => rufen('save_draft', { ...basis, ...args });

check(WRITE_TOOLS.includes('reply_sender'), 'reply_sender im Katalog');

if (ohne) {
    let e = await draft({ in_reply_to: '<news@x.org>' });
    check(/^From: mail@ddsk\.cloud$/m.test(e.raw), 'ohne Absenderliste: Standard bleibt der Anmeldename');
    e = await draft({ from: 'chef@firma.de' });
    check(e.r?.isError === true && e.raw === '', 'ohne Absenderliste: fremder Absender abgelehnt');
    e = await draft({ in_reply_to: '<hux@outlook.com>' });
    check(/^From: dkleinhans@mailbox\.org$/m.test(e.raw),
        'ohne Absenderliste: Antwort von der Adresse, an die die Mail ging (aus „Gesendet“ gelernt)');
    e = await rufen('reply_sender', {});
    check(e.sc?.from === 'mail@ddsk.cloud' && e.sc?.allowed?.join() === 'mail@ddsk.cloud,dkleinhans@mailbox.org',
        'reply_sender ohne Liste: Standard Anmeldename, gelernte Adressen erlaubt');
    const { readFileSync } = await import('node:fs');
    check(readFileSync(process.env.MBX_SENDERS_FILE, 'utf8') === '["mail@ddsk.cloud","dkleinhans@mailbox.org"]',
        'gelernte Liste für smtp-mcp geschrieben');
} else {
    // Verlauf (aus 0.10.2)
    let e = await draft({ in_reply_to: '<abc@mail.example.org>', references: ['<root@x.org>', '<mid@x.org>'] });
    check(/^In-Reply-To: <abc@mail\.example\.org>$/m.test(e.raw), 'in_reply_to setzt In-Reply-To');
    check(/^References: <root@x\.org> <mid@x\.org> <abc@mail\.example\.org>$/m.test(e.raw), 'References: Kette plus beantwortete Mail');
    e = await draft({ in_reply_to: '<abc@mail.example.org>', reply_to_uid: 999, mailbox: 'Gesendet' });
    check(/^In-Reply-To: <abc@mail\.example\.org>$/m.test(e.raw), 'in_reply_to hat Vorrang vor einer falschen UID');
    e = await draft({ reply_to_uid: 17900 });
    check(/^In-Reply-To: <hux@outlook\.com>$/m.test(e.raw), 'reply_to_uid wie bisher');
    e = await draft({ reply_to_uid: 17900, mailbox: 'Gesendet' });
    check(e.r?.isError === true && e.raw === '' && /in_reply_to/.test(e.text), 'falscher Ordner: Fehler mit Hinweis auf in_reply_to');
    e = await draft({ in_reply_to: ' abc@mail.example.org ', references: ['root@x.org'] });
    check(/^In-Reply-To: <abc@mail\.example\.org>$/m.test(e.raw) && /^References: <root@x\.org> <abc@mail\.example\.org>$/m.test(e.raw),
        'Message-IDs ohne Klammern: Klammern ergänzt');
    protokoll.length = 0;
    e = await draft({ in_reply_to: 'abc' });
    check(e.r?.isError === true && e.raw === '', 'Message-ID ohne @ abgelehnt');
    check(protokoll.length === 1 && /^imap-mcp save_draft FEHLER: .*angle brackets/.test(protokoll[0]) && !protokoll[0].includes('anbei'),
        'Fehler im Protokoll, ohne Mailtext: ' + protokoll[0]);
    e = await draft({ in_reply_to: '<abc@x.org>\r\nBcc: boese@x.org' });
    check(e.r?.isError === true && e.raw === '', 'Zeilenumbruch in in_reply_to abgelehnt');
    e = await draft({ references: ['<root@x.org>'] });
    check(e.r?.isError === true && e.raw === '', 'references ohne in_reply_to abgelehnt');

    // Absender
    e = await draft({ in_reply_to: '<hux@outlook.com>' });
    check(/^From: "David Kleinhans" <dkleinhans@mailbox\.org>$/m.test(e.raw) && e.sc?.from === 'dkleinhans@mailbox.org',
        'Antwort: Adresse, an die die Mail ging (Groß-/Kleinschreibung egal)');
    e = await draft({ reply_to_uid: 17900 });
    check(/^From: "David Kleinhans" <dkleinhans@mailbox\.org>$/m.test(e.raw), 'auch über reply_to_uid');
    e = await draft({ in_reply_to: '<eigen@ddsk.cloud>' });
    check(/^From: "David Kleinhans" <mail@ddsk\.cloud>$/m.test(e.raw), 'Antwort auf eigene Mail (Gesendet): deren Absender');
    e = await draft({ in_reply_to: '<news@x.org>' });
    check(/^From: "David Kleinhans" <dkleinhans@mailbox\.org>$/m.test(e.raw), 'an keine eigene Adresse: Standard');
    e = await draft({ in_reply_to: '<gibtsnicht@x.org>' });
    check(/^From: "David Kleinhans" <dkleinhans@mailbox\.org>$/m.test(e.raw), 'Mail nicht gefunden: Standard');
    e = await draft({});
    check(/^From: "David Kleinhans" <dkleinhans@mailbox\.org>$/m.test(e.raw), 'neue Mail: Standard');
    e = await draft({ from: 'Mail@DDSK.cloud' });
    check(/^From: "David Kleinhans" <mail@ddsk\.cloud>$/m.test(e.raw), 'from ausdrücklich: erlaubte Adresse');
    e = await draft({ from: 'chef@firma.de' });
    check(e.r?.isError === true && e.raw === '' && /not one of the configured/.test(e.text), 'from nicht erlaubt: Fehler, kein Entwurf');
    e = await draft({ from: 'dkleinhans@mailbox.org>\r\nBcc: x@y.z' });
    check(e.r?.isError === true && e.raw === '', 'from mit Umbruch abgelehnt');
    suchFehler = true;
    e = await draft({ in_reply_to: '<hux@outlook.com>' });
    check(/^From: "David Kleinhans" <dkleinhans@mailbox\.org>$/m.test(e.raw) && /^In-Reply-To: <hux@outlook\.com>$/m.test(e.raw),
        'Suche scheitert: Entwurf trotzdem, mit Standard');
    suchFehler = false;

    // reply_sender
    e = await rufen('reply_sender', { in_reply_to: '<eigen@ddsk.cloud>' });
    check(e.sc?.from === 'mail@ddsk.cloud' && e.sc?.matched === true && e.sc?.found_in === 'Gesendet', 'reply_sender: passend, mit Ordner');
    e = await rufen('reply_sender', { in_reply_to: '<news@x.org>' });
    check(e.sc?.from === 'dkleinhans@mailbox.org' && e.sc?.matched === false, 'reply_sender: Standard, wenn nichts passt');
    e = await rufen('reply_sender', {});
    check(e.sc?.from === 'dkleinhans@mailbox.org' && e.sc?.allowed?.length === 2, 'reply_sender ohne Mail: Standard und Liste');
    e = await rufen('reply_sender', { in_reply_to: 'kaputt' });
    check(e.r?.isError === true && protokoll.some((z) => z.startsWith('imap-mcp reply_sender FEHLER')), 'reply_sender: ungültige Message-ID abgelehnt und protokolliert');
    e = await rufen('reply_sender', { in_reply_to: 'eigen@ddsk.cloud' });
    check(e.sc?.from === 'mail@ddsk.cloud' && e.sc?.matched === true, 'reply_sender: Message-ID ohne Klammern');
    protokoll.length = 0;
    await draft({ in_reply_to: '<hux@outlook.com>' });
    check(protokoll.length === 0, 'erfolgreicher Entwurf: nichts im Fehlerprotokoll');
}

console.log(fehler ? `${fehler} Fehler` : 'alle Prüfungen bestanden');
process.exit(fehler ? 1 : 0);
