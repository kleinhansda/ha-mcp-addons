// Build-Patch für @ni-c/smtp-mcp (mailbox.org MCP): Absender je Aufruf.
//
// smtp-mcp kennt genau einen Absender (SMTP_FROM). send_mail, reply_mail und forward_mail bekommen den
// Parameter from; erlaubt sind nur die Adressen aus MBX_FROM_ADDRESSES (kommagetrennt, wie bei
// imap-mcp), angezeigt mit MBX_FROM_NAME, und immer die Adresse aus SMTP_FROM. Ohne from gilt SMTP_FROM wie bisher. Der Absender wird nur
// in einer Kopie der Konfiguration für diesen einen Aufruf ersetzt: Bestätigungsdialog, Kopfzeile,
// SMTP-Umschlag und Protokoll nennen dieselbe Adresse. Die Empfänger-Allowlist bleibt unverändert.
// Ohne MBX_FROM_ADDRESSES gelten zusätzlich die Adressen, die imap-mcp aus „Gesendet“ gelernt und nach
// MBX_SENDERS_FILE geschrieben hat.
//
// Kopie in „Gesendet“: Beim Versand über SMTP legt der Mailserver keine Kopie ab; das tun sonst die
// Mailprogramme. Mit MBX_SENT_COPY=true legt smtp-mcp nach dem Senden genau die gesendeten Bytes per
// IMAP APPEND als gelesen im Ordner mit Sonderverwendung \Sent ab (Zugang aus MBX_SENT_IMAP_*).
// Scheitert das, bleibt die Mail gesendet; die Antwort sagt es in note. Kein Werkzeug dafür: ein
// Modell kann so keine erfundenen Mails in „Gesendet“ ablegen.
// Passt ein Muster nicht genau einmal oder ist die Datei schon gepatcht, bricht der Build ab.
//
// Aufruf: node smtp_mcp.mjs <pfad zu @ni-c/smtp-mcp/dist> <pfad zur imapflow-Einstiegsdatei>
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { join } from 'node:path';

const datei = join(process.argv[2], 'tools', 'send.js');
const imapflow = process.argv[3];
if (!imapflow || !existsSync(imapflow)) {
    console.error(`smtp_mcp: imapflow nicht gefunden: ${imapflow}`);
    process.exit(1);
}
let text = readFileSync(datei, 'utf8');
if (text.includes('MBX_FROM_ADDRESSES')) {
    console.error(`smtp_mcp: ${datei} ist schon gepatcht`);
    process.exit(1);
}

const fromParam =
    "            from: z\n" +
    "                .string()\n" +
    "                .max(254)\n" +
    "                .optional()\n" +
    "                .describe('Sender address, one of the configured sender addresses (MBX_FROM_ADDRESSES). ' +\n" +
    "                'Leave out for the default sender. For a reply use the address the original was sent to.'),\n";

const ersetzungen = [
    ["import { z } from 'zod';\n", "import { z } from 'zod';\nimport { readFileSync } from 'node:fs';\n", 1],
    // drei Werkzeuge: send_mail, reply_mail, forward_mail
    ["            confirm_token: confirmTokenParam,\n", fromParam + "            confirm_token: confirmTokenParam,\n", 3],
    ["'SMTP_ALLOWED_RECIPIENTS. There is no \"from\" parameter — the sender is ' +\n            'fixed by SMTP_FROM. ",
        "'SMTP_ALLOWED_RECIPIENTS. The sender is SMTP_FROM unless from names another ' +\n            'configured sender address. ", 1],
    ["            label: 'From (fixed by SMTP_FROM)',\n", "            label: 'From',\n", 1],
    ["        note: sent.rejected.length === 0\n            ? 'The SMTP server accepted the message. It cannot be recalled.'\n            : 'The SMTP server accepted the message for some recipients and ' +\n                'refused others — see \"rejected\". Those people did not receive it.',\n",
        "        note: (sent.rejected.length === 0\n            ? 'The SMTP server accepted the message. It cannot be recalled.'\n            : 'The SMTP server accepted the message for some recipients and ' +\n                'refused others — see \"rejected\". Those people did not receive it.') +\n            (await saveSentCopy(prepared.composed.raw)),\n", 1],
    ["async function performSend(server, mcp, ctx, confirmations, tool, verb, args, confirmToken) {\n",
        "async function performSend(server, mcp, ctx, confirmations, tool, verb, args, confirmToken) {\n" +
        "    ({ ctx, args } = withSender(ctx, args));\n", 1],
];

for (const [alt, neu, anzahl] of ersetzungen) {
    const n = text.split(alt).length - 1;
    if (n !== anzahl) {
        console.error(`smtp_mcp: Muster ${n}x statt ${anzahl}x gefunden: ${alt.slice(0, 80)}`);
        process.exit(1);
    }
    text = text.split(alt).join(neu);
}

text += `
// --- Patch mailbox.org MCP: Absender je Aufruf ---
const MBX_SENDERS = (process.env.MBX_FROM_ADDRESSES ?? '')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter((s) => /^[^\\s@<>",;]+@[^\\s@<>",;]+$/.test(s));
function allowedSenders() {
    if (MBX_SENDERS.length > 0 || !process.env.MBX_SENDERS_FILE) {
        return MBX_SENDERS;
    }
    try {
        const liste = JSON.parse(readFileSync(process.env.MBX_SENDERS_FILE, 'utf8'));
        return Array.isArray(liste)
            ? liste.map((s) => String(s).trim().toLowerCase()).filter((s) => /^[^\\s@<>",;]+@[^\\s@<>",;]+$/.test(s))
            : [];
    }
    catch {
        return [];
    }
}
const IMAPFLOW = ${JSON.stringify(pathToFileURL(imapflow).href)};
async function saveSentCopy(raw) {
    if (process.env.MBX_SENT_COPY !== 'true') {
        return '';
    }
    let imap;
    try {
        const mod = await import(IMAPFLOW);
        const ImapFlow = mod.ImapFlow ?? mod.default?.ImapFlow ?? mod.default;
        imap = new ImapFlow({
            host: process.env.MBX_SENT_IMAP_HOST,
            port: Number(process.env.MBX_SENT_IMAP_PORT ?? 993),
            secure: true,
            auth: { user: process.env.MBX_SENT_IMAP_USER, pass: process.env.MBX_SENT_IMAP_PASSWORD },
            logger: false,
        });
        await imap.connect();
        const sent = (await imap.list()).find((box) => box.specialUse === '\\\\Sent');
        if (sent === undefined) {
            return ' No copy was saved: the account has no Sent folder.';
        }
        await imap.append(sent.path, raw, ['\\\\Seen']);
        return \` A copy was saved to the Sent folder (\${sent.path}).\`;
    }
    catch (error) {
        const reason = String(error instanceof Error ? error.message : error).replace(/\\s+/g, ' ').slice(0, 200);
        console.error(\`smtp-mcp Gesendet-Kopie FEHLER: \${reason}\`);
        return \` The message was sent, but saving a copy to the Sent folder failed: \${reason}\`;
    }
    finally {
        try {
            await imap?.logout();
        }
        catch {
            // Verbindung schon zu
        }
    }
}
function withSender(ctx, args) {
    const { from, ...rest } = args;
    if (from === undefined || from.trim() === '') {
        return { ctx, args: rest };
    }
    const address = from.trim().toLowerCase();
    // Ohne Liste ist nur SMTP_FROM erlaubt (so meldet es auch reply_sender von imap-mcp).
    if (address === String(ctx.config.smtp.fromAddress ?? '').toLowerCase()) {
        return { ctx, args: rest };
    }
    const allowed = allowedSenders();
    if (!allowed.includes(address)) {
        throw new ToolInputError(\`smtp-mcp: \${address} is not one of the configured sender addresses (\${allowed.join(', ') || ctx.config.smtp.fromAddress}).\`);
    }
    const name = (process.env.MBX_FROM_NAME ?? '').replace(/[\\r\\n"\\\\]/g, '').trim();
    const header = name === '' ? address : \`"\${name}" <\${address}>\`;
    return {
        ctx: { ...ctx, config: { ...ctx.config, smtp: { ...ctx.config.smtp, from: header, fromAddress: address } } },
        args: rest,
    };
}
`;
writeFileSync(datei, text);
console.log('smtp_mcp: send_mail, reply_mail und forward_mail kennen from');
