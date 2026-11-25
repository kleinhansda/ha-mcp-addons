// Build-Patch für @ni-c/imap-mcp: save_draft verkettet Antwort-Entwürfe auch über die Message-ID.
//
// imap-mcp findet die beantwortete Mail nur über reply_to_uid. UIDs gelten aber je Ordner: liegt die
// Mail woanders als angegeben, legt das Modell den Entwurf ohne Verlauf ab. Neu sind in_reply_to und
// references (beide aus get_message, wie bei reply_mail von smtp-mcp). Sie hängen den Entwurf an den
// Verlauf, egal in welchem Ordner die Mail liegt. Jede Message-ID wird wie bei reply_to_uid geprüft
// (isMessageId: spitze Klammern, keine Leer- oder unsichtbaren Zeichen), buildDraft prüft die Kopfzeilen
// zusätzlich auf Zeilenumbrüche. Findet reply_to_uid nichts, nennt der Fehler beide Auswege.
//
// Aufruf: node imap_draft_thread.mjs <pfad zu dist/tools/write.js>
// Passt ein Muster nicht genau einmal (neue imap-mcp-Version), bricht der Build ab.
import { readFileSync, writeFileSync } from 'node:fs';

const datei = process.argv[2];
let text = readFileSync(datei, 'utf8');

const ersetzungen = [
    [
        "import { buildDraft } from '../draft.js';",
        "import { buildDraft } from '../draft.js';\nimport { isMessageId } from '../message.js';",
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
];

for (const [alt, neu] of ersetzungen) {
    const n = text.split(alt).length - 1;
    if (n !== 1) {
        console.error(`imap_draft_thread: Muster ${n}x statt 1x gefunden: ${alt.slice(0, 80)}`);
        process.exit(1);
    }
    text = text.replace(alt, () => neu);
}
writeFileSync(datei, text);
console.log('imap_draft_thread: save_draft kennt in_reply_to und references');
