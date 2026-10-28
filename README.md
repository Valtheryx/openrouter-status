# OpenRouter Status

Eigene OpenRouter-Nutzungsuebersicht: Credits, Monatskosten, Verbrauch pro Modell und pro API-Key.

## Endpunkte
- Website: http://172.30.1.3:8097
- API: /api/data, /api/refresh (POST), /api/config (GET/POST), /api/status

## Datenspeicherung (data/)
- `hourly.json` — stuendliche Verdichtung: pro Stunde `total` (USD) und `keys` (USD je Key).
  Basis: alle 5 Min (`SAMPLE_SECONDS`) werden die kumulativen Zaehler (`total_usage` aus
  /credits und `usage` je Key aus /keys) gelesen und die Differenz in den laufenden
  Stundenbucket gelegt. Vorhalt: 93 Tage (`RETENTION_DAYS`), also ~3 Monate.
- `state.json` — letzter Zaehlerstand (Baseline fuer die Delta-Bildung, uebersteht Restarts).
- `history.json` — Tagesaggregate je Modell, Workspace und Key (aus /activity) fuer die
  30-Tage-/7-Tage-Charts und die 3-Monats-Kostentabelle; ebenfalls 93 Tage Vorhalt.
- Rohdaten (5-Min-Samples) werden NICHT dauerhaft gespeichert, nur der jeweils letzte Stand.

Hinweise:
- Die OpenRouter-API liefert Activity nur ~30 Tage zurueck; aeltere Tage stammen aus dem
  lokalen Verlauf. Monate vor dem ersten Abruf sind leer und werden als Teilmonat markiert.
- Stundenwerte pro Modell gibt es nicht (activity ist tagesgenau). Die 24h-Modellansicht
  zeigt daher eine einfarbige kumulierte Stundensumme aus den lokalen Zählerständen;
  die Schraffierung kennzeichnet diese Sampler-Werte, nicht eine Modellschätzung.
  Die Tagesansicht verwendet ebenfalls nur eine Schraffur-Summe für den aktuellen Tag.
- Aktualisierungsintervall: Env `REFRESH_MINUTES` (Default 60) oder per UI (data/config.json).
- UI: Reload = sofortiger Abruf, Live = Abruf + Nachladen alle 10 s.
- API-Key liegt als Portainer-Stack-Env `OPENROUTER_MANAGEMENT_API_KEY`; bei Rotation
  im Stack UND im Custom Template aendern.
