// Nachgebautes imapflow für test_smtp.mjs: merkt sich, was in „Gesendet“ abgelegt würde.
export class ImapFlow {
    constructor(options) {
        globalThis.__imap = { options, appended: globalThis.__imap?.appended ?? [] };
    }
    async connect() {
        if (globalThis.__imapFehler) throw new Error('Login fehlgeschlagen');
    }
    async list() {
        return [{ path: 'INBOX' }, { path: 'Gesendet', specialUse: '\\Sent' }];
    }
    async append(path, raw, flags) {
        globalThis.__imap.appended.push({ path, raw: raw.toString('utf8'), flags });
    }
    async logout() {}
}
