// Build-Patch für @ni-c/imap-mcp (mailbox.org MCP). Passt ein Muster nicht genau einmal (neue
// imap-mcp-Version) oder ist die Datei schon gepatcht, bricht der Build ab.
//
// 1. Verlauf: save_draft findet die beantwortete Mail sonst nur über reply_to_uid, und UIDs gelten je
//    Ordner. Neu sind in_reply_to und references (Message-IDs aus get_message, wie bei reply_mail von
//    smtp-mcp); sie hängen den Entwurf an den Verlauf, egal in welchem Ordner die Mail liegt. Jede
//    Message-ID wird mit isMessageId geprüft, buildDraft prüft die Kopfzeilen zusätzlich auf Umbrüche.
//    Findet reply_to_uid nichts, nennt der Fehler beide Auswege.
// 2. Absender: MBX_FROM_ADDRESSES (kommagetrennt, erster Eintrag = Standard) und MBX_FROM_NAME. Ohne
//    Angabe nimmt save_draft die erlaubte Adresse, an die die beantwortete Mail ging (gesucht über die
//    Message-ID in Posteingang, Gesendet und Archiv), sonst den Standard. Das neue Werkzeug
//    reply_sender liefert dieselbe Wahl für das Senden (Werkzeug „Mail senden approval“ in Open WebUI).
//    Ohne MBX_FROM_ADDRESSES gelten der Anmeldename und die Absender der letzten 300 Mails in
//    „Gesendet“ (gelernt); die Liste geht nach MBX_SENDERS_FILE für smtp-mcp. Standard bleibt der
//    Anmeldename.
// 3. Robust: Message-IDs ohne spitze Klammern werden ergänzt; Fehler von save_draft und reply_sender
//    landen mit der Fehlermeldung (ohne Mailtext) im App-Protokoll.
//
// Aufruf: node imap_mcp.mjs <pfad zu @ni-c/imap-mcp/dist>
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const dist = process.argv[2];

function patchen(datei, ersetzungen, anhang = '') {
    let text = readFileSync(datei, 'utf8');
    if (text.includes('MBX_FROM_ADDRESSES') || text.includes("'reply_sender'")) {
        console.error(`imap_mcp: ${datei} ist schon gepatcht`);
        process.exit(1);
    }
    for (const [alt, neu] of ersetzungen) {
        const n = text.split(alt).length - 1;
        if (n !== 1) {
            console.error(`imap_mcp: ${datei}: Muster ${n}x statt 1x gefunden: ${alt.slice(0, 80)}`);
            process.exit(1);
        }
        text = text.replace(alt, () => neu);
    }
    writeFileSync(datei, text + anhang);
}

const schreibWerkzeuge = [
    [
        "import { buildDraft } from '../draft.js';",
        "import { buildDraft } from '../draft.js';\nimport { isMessageId } from '../message.js';\nimport { writeFileSync } from 'node:fs';",
    ],
    [
        "            mailbox: optionalMailboxParam.describe('Where to look for reply_to_uid. Defaults to the configured mailbox.'),\n",
        "            mailbox: optionalMailboxParam.describe('Where to look for reply_to_uid. Defaults to the configured mailbox.'),\n" +
        "            in_reply_to: z\n" +
        "                .string()\n" +
        "                .max(257)\n" +
        "                .optional()\n" +
        "                .describe('Message-ID of the message being answered, as returned by get_message (e.g. <abc@example.org>). ' +\n" +
        "                'Threads the draft no matter which folder that message is in; preferred over reply_to_uid.'),\n" +
        "            references: z\n" +
        "                .array(z.string().max(257))\n" +
        "                .max(50)\n" +
        "                .optional()\n" +
        "                .describe('References chain of the message being answered, as returned by get_message. Only with in_reply_to.'),\n",
    ],
    [
        "async ({ to, cc, bcc, subject, body, reply_to_uid, mailbox }) => run(async () => {\n" +
        "        const thread = reply_to_uid === undefined\n" +
        "            ? undefined\n" +
        "            : await client.threadHeaders(mailbox, reply_to_uid);\n",
        "async ({ to, cc, bcc, subject, body, reply_to_uid, mailbox, in_reply_to, references }) => run(async () => {\n" +
        "        if (in_reply_to === undefined && references !== undefined && references.length > 0) {\n" +
        "            throw new ToolInputError('imap-mcp: references needs in_reply_to (the Message-ID of the message being answered).');\n" +
        "        }\n" +
        "        for (const id of [in_reply_to, ...(references ?? [])]) {\n" +
        "            if (id !== undefined && !isMessageId(id)) {\n" +
        "                throw new ToolInputError('imap-mcp: in_reply_to and references take Message-IDs in angle brackets, e.g. <abc@example.org>, as returned by get_message.');\n" +
        "            }\n" +
        "        }\n" +
        "        const thread = in_reply_to !== undefined\n" +
        "            ? { messageId: in_reply_to, references: [...new Set([...(references ?? []), in_reply_to])].slice(-20) }\n" +
        "            : reply_to_uid === undefined\n" +
        "                ? undefined\n" +
        "                : await client.threadHeaders(mailbox, reply_to_uid).catch((e) => {\n" +
        "                    throw e instanceof ToolInputError\n" +
        "                        ? new ToolInputError(`${e.message} UIDs only count within one folder: pass that folder as mailbox, ` +\n" +
        "                            'or use in_reply_to with the Message-ID from get_message, which works for any folder.')\n" +
        "                        : e;\n" +
        "                });\n",
    ],

    // Absender: Parameter from und automatische Wahl
    [
        "                .describe('References chain of the message being answered, as returned by get_message. Only with in_reply_to.'),\n",
        "                .describe('References chain of the message being answered, as returned by get_message. Only with in_reply_to.'),\n" +
        "            from: z\n" +
        "                .string()\n" +
        "                .max(254)\n" +
        "                .optional()\n" +
        "                .describe('Sender address, one of the configured sender addresses. Leave out to pick automatically: ' +\n" +
        "                'the configured address the answered message was sent to, otherwise the default.'),\n",
    ],
    [
        "            action: z.literal('draft_saved'),\n",
        "            action: z.literal('draft_saved'),\n            from: z.string().describe('Sender address of the draft.'),\n",
    ],
    [
        "async ({ to, cc, bcc, subject, body, reply_to_uid, mailbox, in_reply_to, references }) => run(async () => {\n",
        "async ({ to, cc, bcc, subject, body, reply_to_uid, mailbox, in_reply_to, references, from }) => run(async () => {\n",
    ],
    [
        "        const draft = buildDraft({\n            from: client.user,\n",
        "        const sender = from !== undefined && from.trim() !== ''\n" +
        "            ? await checkedSender(client, from)\n" +
        "            : (await pickSender(client, { in_reply_to, reply_to_uid, mailbox })).from;\n" +
        "        const draft = buildDraft({\n            from: senderHeader(sender),\n",
    ],
    [
        "            action: 'draft_saved',\n",
        "            action: 'draft_saved',\n            from: sender,\n",
    ],
    [
        "    server.registerTool('save_draft', {\n",
        "    server.registerTool('reply_sender', {\n" +
        "        title: 'Pick the sender address for a reply',\n" +
        "        description: 'Returns the sender address a reply should use: the configured sender address the ' +\n" +
        "            'answered message was sent to (found by its Message-ID in the inbox, Sent and Archive), ' +\n" +
        "            'otherwise the default. Without in_reply_to it returns the default. Reads only.',\n" +
        "        inputSchema: z.object({\n" +
        "            in_reply_to: z\n" +
        "                .string()\n" +
        "                .max(257)\n" +
        "                .optional()\n" +
        "                .describe('Message-ID of the message being answered, as returned by get_message.'),\n" +
        "        }),\n" +
        "        annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },\n" +
        "    }, async ({ in_reply_to }) => run(async () => {\n" +
        "        in_reply_to = mitKlammern(in_reply_to);\n" +
        "        if (in_reply_to !== undefined && !isMessageId(in_reply_to)) {\n" +
        "            throw new ToolInputError('imap-mcp: in_reply_to takes a Message-ID in angle brackets, e.g. <abc@example.org>, as returned by get_message.');\n" +
        "        }\n" +
        "        const pick = await pickSender(client, { in_reply_to });\n" +
        "        return jsonResult({ ...pick, allowed: await allowedSenders(client) });\n" +
        "    }));\n" +
        "    server.registerTool('save_draft', {\n",
    ],
    // Robust: Message-IDs ohne spitze Klammern ergänzen; Fehler von save_draft/reply_sender protokollieren
    [
        "        if (in_reply_to === undefined && references !== undefined && references.length > 0) {\n",
        "        in_reply_to = mitKlammern(in_reply_to);\n" +
        "        references = references?.map(mitKlammern);\n" +
        "        if (in_reply_to === undefined && references !== undefined && references.length > 0) {\n",
    ],
    [
        "export function registerWriteTools(server, client, config, confirmations, approval) {\n",
        "export function registerWriteTools(server, client, config, confirmations, approval) {\n" +
        "    server = mitFehlerprotokoll(server);\n",
    ],
];

const absenderCode = `
// --- Patch mailbox.org MCP: Message-IDs und Fehlerprotokoll ---
// Modelle schreiben Message-IDs oft ohne spitze Klammern ab: abc@host wird zu <abc@host>.
function mitKlammern(id) {
    if (typeof id !== 'string') {
        return id;
    }
    const trimmed = id.trim();
    return /^[^\\s<>]+@[^\\s<>]+$/.test(trimmed) ? \`<\${trimmed}>\` : trimmed;
}
// Fehlgeschlagene Aufrufe von save_draft und reply_sender ins App-Protokoll (nur die Fehlermeldung,
// nie Mailtext), damit sich ein Entwurf ohne Verlauf nachvollziehen lässt.
function mitFehlerprotokoll(server) {
    const protokolliert = new Set(['save_draft', 'reply_sender']);
    return new Proxy(server, {
        get(target, prop) {
            if (prop !== 'registerTool') {
                const value = Reflect.get(target, prop, target);
                return typeof value === 'function' ? value.bind(target) : value;
            }
            return (name, definition, handler) => target.registerTool(name, definition, !protokolliert.has(name) ? handler : async (...args) => {
                const result = await handler(...args);
                if (result?.isError) {
                    const text = (result.content ?? []).map((part) => part?.text ?? '').join(' ').replace(/\\s+/g, ' ').slice(0, 400);
                    console.error(\`imap-mcp \${name} FEHLER: \${text}\`);
                }
                return result;
            });
        },
    });
}

// --- Patch mailbox.org MCP: Absender ---
const MBX_SENDERS = (process.env.MBX_FROM_ADDRESSES ?? '')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter((s) => /^[^\\s@<>",;]+@[^\\s@<>",;]+$/.test(s));
// Ohne MBX_FROM_ADDRESSES gelten der Anmeldename und die Absender der letzten Mails in „Gesendet“
// (gelernt, 10 Minuten zwischengespeichert). Die Liste geht nach MBX_SENDERS_FILE, damit smtp-mcp
// dieselben Adressen zulässt.
const LERN_ANZAHL = 300;
let gelernt = { zeit: 0, adressen: [] };
async function learnedSenders(client) {
    if (Date.now() - gelernt.zeit < 10 * 60 * 1000) {
        return gelernt.adressen;
    }
    let adressen = gelernt.adressen;
    try {
        const { mailboxes } = await client.listMailboxes();
        const sent = mailboxes.find((box) => box.specialUse === '\\\\Sent');
        adressen = sent === undefined ? [] : await client.withMailbox(sent.path, true, async (connection) => {
            const uids = (await client.search(connection, { all: true })).slice(-LERN_ANZAHL);
            const messages = uids.length === 0 ? [] : await client.fetchSummaries(connection, uids);
            return [...new Set(messages.flatMap((message) => (message.envelope?.from ?? [])
                .map((entry) => String(entry?.address ?? '').trim().toLowerCase())))]
                .filter((s) => /^[^\\s@<>",;]+@[^\\s@<>",;]+$/.test(s));
        });
    }
    catch {
        // Lernen darf nie einen Entwurf verhindern: dann bleibt es bei der bisherigen Liste.
    }
    gelernt = { zeit: Date.now(), adressen };
    return adressen;
}
async function allowedSenders(client) {
    if (MBX_SENDERS.length > 0) {
        return MBX_SENDERS;
    }
    const login = String(client.user ?? '').trim().toLowerCase();
    const liste = [...new Set([login, ...(await learnedSenders(client))])].filter((s) => s !== '');
    if (process.env.MBX_SENDERS_FILE) {
        try {
            writeFileSync(process.env.MBX_SENDERS_FILE, JSON.stringify(liste));
        }
        catch {
            // smtp-mcp lässt dann nur seinen eigenen Absender zu.
        }
    }
    return liste;
}
async function checkedSender(client, from) {
    const address = from.trim().toLowerCase();
    const allowed = await allowedSenders(client);
    if (!allowed.includes(address)) {
        throw new ToolInputError(\`imap-mcp: \${address} is not one of the configured sender addresses (\${allowed.join(', ')}).\`);
    }
    return address;
}
function senderHeader(address) {
    const name = (process.env.MBX_FROM_NAME ?? '').replace(/[\\r\\n"\\\\]/g, '').trim();
    return name === '' ? address : \`"\${name}" <\${address}>\`;
}
function envelopeAddresses(envelope) {
    // Empfänger zuerst, dann der Absender (Antwort auf eine eigene, gesendete Mail).
    return ['to', 'cc', 'from'].flatMap((key) => (envelope?.[key] ?? []).map((entry) => String(entry?.address ?? '').toLowerCase()));
}
async function pickSender(client, { in_reply_to, reply_to_uid, mailbox }) {
    const allowed = await allowedSenders(client);
    let candidates = [];
    let foundIn = null;
    try {
        if (in_reply_to !== undefined) {
            const { mailboxes } = await client.listMailboxes();
            const boxes = [...new Set([
                client.defaultMailbox,
                ...mailboxes.filter((box) => box.specialUse === '\\\\Sent' || box.specialUse === '\\\\Archive').map((box) => box.path),
            ])];
            for (const box of boxes) {
                const message = await client.withMailbox(box, true, async (connection) => {
                    const uids = await client.search(connection, { header: { 'message-id': in_reply_to } });
                    return uids.length === 0 ? undefined : (await client.fetchSummaries(connection, uids.slice(0, 1)))[0];
                });
                if (message !== undefined) {
                    candidates = envelopeAddresses(message.envelope);
                    foundIn = box;
                    break;
                }
            }
        }
        else if (reply_to_uid !== undefined) {
            const message = await client.withMailbox(mailbox, true, async (connection) => (await client.fetchSummaries(connection, [reply_to_uid]))[0]);
            if (message !== undefined) {
                candidates = envelopeAddresses(message.envelope);
                foundIn = mailbox ?? client.defaultMailbox;
            }
        }
    }
    catch {
        // Die Suche nach dem passenden Absender darf einen Entwurf nie verhindern: dann gilt der Standard.
        candidates = [];
    }
    const hit = candidates.find((address) => allowed.includes(address));
    return { from: hit ?? allowed[0], matched: hit !== undefined, found_in: foundIn };
}
`;

patchen(join(dist, 'tools', 'write.js'), schreibWerkzeuge, absenderCode);
patchen(join(dist, 'tools', 'catalogue.js'), [
    ["    'save_draft',\n", "    'reply_sender',\n    'save_draft',\n"],
]);
console.log('imap_mcp: save_draft mit in_reply_to/references und Absender, reply_sender');
