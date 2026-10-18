# GitHub: Hintergrund

Bedienung in [github_mcp/DOCS.md](../github_mcp/DOCS.md).

## Warum selbst gehostet

GitHub bietet einen gehosteten MCP-Server (`https://api.githubcopilot.com/mcp/`). In der
Claude-App läuft er über eine GitHub-App, die ohne Installation auf dem Account nur lesen kann.
Schreiben endet mit `403 Resource not accessible by integration`, und die Repo-Freigabe ist nur
grob steuerbar. Der offizielle Server als Binary nimmt dagegen einen eigenen Token mit genau
festgelegten Rechten und funktioniert mit jedem Client. Er spricht nur stdio, daher der Proxy.

## Token

Fine-grained Personal Access Token:

| Einstellung | Wert |
|---|---|
| Resource owner | eigenes Konto oder Organisation |
| Repository access | nur die Repos, in denen Claude arbeiten soll (oder alle, dann Branch-Schutz überall) |
| Contents | Read and write |
| Pull requests | Read and write |
| Issues | nach Bedarf |
| Actions | Read, wenn Claude Build-Logs lesen soll |
| Metadata | Read (Pflicht) |
| Administration | **nein**: damit könnte der Token Repos löschen oder Rulesets ändern |
| Ablauf | z. B. 90 Tage, Datum notieren |

Klassische Tokens mit Scope `repo` nicht verwenden, sie gelten für alles.

`toolsets` steuert, welche Tools Claude sieht, der Token, welche davon funktionieren.
`all` zeigt alle 91 Tools (Stand 2.0.2), `default` eine kleinere Auswahl. Weniger Tools
schonen den Kontext in Claude.

## Risiken

- Der Token kann in jedem freigegebenen Repo Branches und Pull Requests anlegen und, wo kein
  Branch-Schutz besteht, direkt auf den Standard-Branch schreiben.
- Läuft der Token ab, antwortet GitHub mit 401. Das Add-on meldet dabei nichts, erst Claude
  sieht die Fehler. Ablaufdatum notieren und rechtzeitig erneuern.

## Getestet

2026-10-18, github-mcp-server 2.0.2 (x86_64): Tool-Liste ohne gültigen Token (91 Tools mit
`--toolsets=all`), Start mit `--read-only` und eigener Toolset-Liste, Token kommt beim Server an,
das OIDC-Secret nicht. Schreibender Zugriff über einen selbst gehosteten Server mit
Fine-grained-Token in der Praxis bestätigt (Repo anlegen, Dateien pushen).
