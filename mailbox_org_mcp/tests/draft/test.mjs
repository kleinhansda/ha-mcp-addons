// save_draft nach dem Patch: Verkettung über in_reply_to/references, unabhängig vom Ordner.
import { pathToFileURL } from 'node:url';

const { registerWriteTools } = await import(pathToFileURL(process.argv[2]).href);
const { ToolInputError } = await import(pathToFileURL(process.argv[2].replace(/tools\/write\.js$/, 'errors.js')).href);

const handler = {};
const server = { registerTool: (name, def, fn) => { handler[name] = { def, fn }; } };
const angehaengt = [];
const client = {
    user: 'ich@example.org',
    withMailbox: async (folder, readOnly, fn) => fn({
        mailbox: { permanentFlags: new Set(['\\Draft', '\\Seen']) },
        append: async (f, raw, flags) => { angehaengt.push({ f, raw: raw.toString('utf8'), flags }); },
    }),
    threadHeaders: async (mailbox, uid) => {
        if ((mailbox ?? 'INBOX') !== 'INBOX' || uid !== 17900) {
            throw new ToolInputError(`imap-mcp: no message with UID ${uid} in this mailbox.`);
        }
        return { messageId: '<uid17900@example.org>', references: ['<uid17900@example.org>'] };
    },
};
registerWriteTools(server, client, { imap: { draftsMailbox: 'Drafts' } }, undefined, undefined);

let fehler = 0;
const check = (ok, name) => { console.log(`${ok ? 'ok  ' : 'FEHL'} ${name}`); if (!ok) fehler += 1; };
const basis = { to: ['vermieter@example.org'], subject: 'AW: Wohnung', body: 'Guten Tag,\nanbei.' };
const rufen = async (args) => {
    angehaengt.length = 0;
    const parsed = handler.save_draft.def.inputSchema.safeParse({ ...basis, ...args });
    if (!parsed.success) return { schemaFehler: parsed.error.issues.map((i) => i.path.join('.')).join(',') };
    const r = await handler.save_draft.fn(parsed.data);
    return { r, text: (r.content ?? []).map((c) => c.text).join(''), raw: angehaengt[0]?.raw ?? '' };
};

let e = await rufen({ in_reply_to: '<abc@mail.example.org>', references: ['<root@x.org>', '<mid@x.org>'] });
check(/^In-Reply-To: <abc@mail\.example\.org>$/m.test(e.raw), 'in_reply_to setzt In-Reply-To');
check(/^References: <root@x\.org> <mid@x\.org> <abc@mail\.example\.org>$/m.test(e.raw), 'References: Kette plus beantwortete Mail');

e = await rufen({ in_reply_to: '<abc@mail.example.org>' });
check(/^References: <abc@mail\.example\.org>$/m.test(e.raw), 'ohne references: References = in_reply_to');

e = await rufen({ in_reply_to: '<abc@mail.example.org>', reply_to_uid: 999, mailbox: 'Gesendet' });
check(/^In-Reply-To: <abc@mail\.example\.org>$/m.test(e.raw), 'in_reply_to hat Vorrang vor einer falschen UID');

e = await rufen({ reply_to_uid: 17900 });
check(/^In-Reply-To: <uid17900@example\.org>$/m.test(e.raw), 'reply_to_uid wie bisher');

e = await rufen({ reply_to_uid: 17900, mailbox: 'Gesendet' });
check(e.r?.isError === true && e.raw === '' && /no message with UID/.test(e.text) && /in_reply_to/.test(e.text),
    'falscher Ordner: Fehler mit Hinweis auf in_reply_to, kein Entwurf');

e = await rufen({ in_reply_to: 'abc@mail.example.org' });
check(e.r?.isError === true && e.raw === '' && /angle brackets/.test(e.text), 'Message-ID ohne Klammern abgelehnt');

e = await rufen({ in_reply_to: '<abc@x.org>\r\nBcc: boese@x.org' });
check(e.r?.isError === true && e.raw === '', 'Zeilenumbruch in in_reply_to abgelehnt');

e = await rufen({ in_reply_to: '<abc@x.org>', references: ['<ok@x.org>', '<a b@x.org>'] });
check(e.r?.isError === true && e.raw === '', 'ungültige Referenz abgelehnt');

e = await rufen({ references: ['<root@x.org>'] });
check(e.r?.isError === true && e.raw === '' && /needs in_reply_to/.test(e.text), 'references ohne in_reply_to abgelehnt');

e = await rufen({});
check(e.raw !== '' && !/^In-Reply-To:/m.test(e.raw), 'ohne Bezug: Entwurf ohne In-Reply-To');

console.log(fehler ? `${fehler} Fehler` : 'alle Prüfungen bestanden');
process.exit(fehler ? 1 : 0);
