
## Ergänzt von der App Open Terminal (ha-mcp-addons)
## CRAN ohne Rückfrage (das Modell arbeitet nicht interaktiv), Pakete parallel bauen.
local({
  options(repos = c(CRAN = "https://cloud.r-project.org"))
  options(Ncpus = max(1L, parallel::detectCores(logical = FALSE), na.rm = TRUE))
})
