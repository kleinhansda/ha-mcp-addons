// Build-Patch für @ni-c/smtp-mcp (mailbox.org MCP): Absender je Aufruf.
//
// smtp-mcp kennt genau einen Absender (SMTP_FROM). send_mail, reply_mail und forward_mail bekommen den
// Parameter from; erlaubt sind nur die Adressen aus MBX_FROM_ADDRESSES (kommagetrennt, wie bei
// imap-mcp), angezeigt mit MBX_FROM_NAME, und immer die Adresse aus SMTP_FROM. Ohne from gilt SMTP_FROM wie bisher. Der Absender wird nur
// in einer Kopie der Konfiguration für diesen einen Aufruf ersetzt: Bestätigungsdialog, Kopfzeile,
// SMTP-Umschlag und Protokoll nennen dieselbe Adresse. Die Empfänger-Allowlist bleibt unverändert.
// Passt ein Muster nicht genau einmal oder ist die Datei schon gepatcht, bricht der Build ab.
//
// Aufruf: node smtp_mcp.mjs <pfad zu @ni-c/smtp-mcp/dist>
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const datei = join(process.argv[2], 'tools', 'send.js');
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
    // drei Werkzeuge: send_mail, reply_mail, forward_mail
    ["            confirm_token: confirmTokenParam,\n", fromParam + "            confirm_token: confirmTokenParam,\n", 3],
    ["'SMTP_ALLOWED_RECIPIENTS. There is no \"from\" parameter — the sender is ' +\n            'fixed by SMTP_FROM. ",
        "'SMTP_ALLOWED_RECIPIENTS. The sender is SMTP_FROM unless from names another ' +\n            'configured sender address. ", 1],
    ["            label: 'From (fixed by SMTP_FROM)',\n", "            label: 'From',\n", 1],
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
    if (!MBX_SENDERS.includes(address)) {
        throw new ToolInputError(\`smtp-mcp: \${address} is not one of the configured sender addresses (\${MBX_SENDERS.join(', ') || ctx.config.smtp.fromAddress}).\`);
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
