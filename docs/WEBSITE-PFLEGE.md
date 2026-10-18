# Websites mit Claude pflegen

Zusammenspiel von [GitHub MCP](../github_mcp/DOCS.md) und [Netlify MCP](../netlify_mcp/DOCS.md)
für statische Websites (z. B. Hugo) mit Quelle auf GitHub und Hosting auf Netlify.

## Ablauf

```
Claude → GitHub MCP → Branch, Commits, Pull Request
       → Netlify baut automatisch eine Deploy Preview
       → Claude prüft Build-Log und Preview über Netlify MCP
       → Mensch prüft die Preview-URL und merged
       → main wird live
```

Jede Änderung ist ein Commit, Rollback ist ein `git revert`. Es gibt keinen Zustand außerhalb
von Git, und beide Server gelten accountweit: Ein neues Web-Projekt braucht keine Änderung an
den Add-ons.

## Voraussetzungen im Repo

### Branch-Schutz

Pflicht, bevor der GitHub-Token Schreibrechte bekommt: Ruleset auf `main` mit
Pull-Request-Pflicht. Ohne den Schutz kann ein Modell direkt auf `main` schreiben, und die
Regeln in `AGENTS.md` sind nur noch eine Bitte.

### AGENTS.md

Projektwissen gehört ins Repo, nicht in die Infrastruktur. Eine `AGENTS.md` im Repo-Root sagt:

- welche Pfade geändert werden dürfen (z. B. `content/`, `data/`) und welche nicht
  (`layouts/`, `themes/`, Build-Konfiguration),
- wie gebaut wird und welche Hugo-Version gilt,
- welche Konventionen für Inhalte, Bilder und Sprache gelten,
- dass Änderungen immer über Branch und Pull Request laufen und erst nach Freigabe gemergt werden.

### Deploy Previews mit richtiger baseURL

Netlify baut für jeden Pull Request eine Preview unter `deploy-preview-<nr>--<site>.netlify.app`.
Damit Hugo dort keine Links auf die Live-Domain erzeugt, in `netlify.toml`:

```toml
[build]
  command = "hugo --gc --minify"
  publish = "public"

[build.environment]
  HUGO_VERSION = "0.125.6"

[context.deploy-preview]
  command = "hugo --gc --minify -b $DEPLOY_PRIME_URL"

[context.branch-deploy]
  command = "hugo --gc --minify -b $DEPLOY_PRIME_URL"
```

`$DEPLOY_PRIME_URL` setzt Netlify selbst.

> [!WARNING]
> Stehen Build-Befehl und Publish-Ordner in `netlify.toml`, ignoriert Netlify die Einstellungen
> in der Oberfläche stillschweigend. Umstellungen zuerst in einem Branch testen.

## Kein lokaler Build

Die Deploy Preview **ist** der Build-Test und liefert zusätzlich die Ansicht. Ein zweiter Build
in einem eigenen Container brächte nichts Neues, bräuchte aber einen projektspezifischen
Ordner und würde die Add-ons an ein Repo binden. Preis: 30 bis 60 Sekunden bis zur Preview.

## Risiken

- **Pfadregeln sind nur Text.** `AGENTS.md` kann ein Modell überschreiten. Harte Grenzen sind
  der Branch-Schutz und die Freigabe durch einen Menschen.
- **Tokens gelten breit.** Der Netlify-Token gilt für alle Sites des Accounts, der GitHub-Token
  für alle freigegebenen Repos. Rechte und Ablaufdaten siehe [GITHUB.md](GITHUB.md) und
  [NETLIFY.md](NETLIFY.md). Jedes Repo, in dem Claude schreibt, braucht seinen eigenen Branch-Schutz.
