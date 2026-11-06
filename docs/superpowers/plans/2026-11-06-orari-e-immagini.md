# Aggiornamenti a orari intelligenti, stemmi, volti, panchine e affidabilità – Piano di esecuzione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

Richieste dell'utente del 2026-11-06.

## Task O1: Orari intelligenti degli aggiornamenti
- Un solo workflow GitHub Actions orario (`orchestratore.yml`, cron `5 * * * *`) + il pre-partita esistente ogni 10 minuti 10–20 UTC (finestra 75 minuti, invariato). Lo script `scheduler/orchestratore.py` decide:
  1. **Aggiornamento della giornata**: se la prima partita di oggi (ora italiana) inizia tra 6 e 7 ore e non è già stato fatto oggi → calendario, statistiche delle partite giocate, arbitri, probabili, storico (con il tetto di tempo).
  2. **Chiusura**: partite finite da almeno 2 ore e non ancora chiuse → statistiche, esiti delle giocate.
  3. Altrimenti esce subito (nessuna richiesta).
- Il job notturno resta come rete di sicurezza ma solo **una volta a settimana** (lunedì notte) per lo storico e i controlli.
- README: nuovo schema e stima dei minuti GitHub.
- Test con orologio iniettato: giorno con partita alle 15:00 → aggiornamento alle ~08:xx; giorno senza partite → nessuna azione; chiusura dopo la fine; nessun doppione.

## Task O2: Immagini da ESPN (uso personale, opzione)
- **Stemmi delle squadre** al posto delle iniziali: URL `team.logo` dallo scoreboard ESPN (già scaricato, nessuna richiesta in più), salvato su `Squadra.logo_url` (migrazione idempotente). Fallback: iniziali nel cerchio.
- **Volti dei giocatori**: URL `https://a.espncdn.com/i/headshots/soccer/players/full/{athlete_id}.png` (verificare che esista; fallback maglietta); salvato/derivato senza scaricare file.
- Impostazione **"Immagini da ESPN (stemmi e volti) – solo uso personale"**, accesa di default, con nota: immagini protette da diritti, da spegnere/sostituire in caso di uso commerciale.
- Immagini caricate dal browser direttamente dal CDN ESPN (`<img loading="lazy">`), con `alt` e dimensioni fisse.

## Task O3: Panchine sul campo
- Nel campo (piano campo-e-scommetti F1): sotto ogni metà campo la panchina (riserve dalla formazione ufficiale; con le probabili, i probabili subentranti), maglietta/volto, numero, nome, bordo per il rischio dei subentranti.

## Task O4: Affidabilità precisa
- Punteggio 0–100 per candidato da: minuti nelle 3 stagioni, costanza dei gialli (dispersione per partita), formazione ufficiale/probabile, arbitro designato e sue partite nei dati, avversario diretto certo, numero di precedenti/derby, attività recente.
- Badge 🟢 Alta (≥ 70) · 🟡 Media (40–69) · 🔴 Bassa (< 40) col numero; riga di dettaglio con i motivi in chiaro.
- Ordinamento alternativo "per affidabilità"; riquadro "Puntata più solida" (probabilità e affidabilità alte insieme).
- Non cambia la probabilità. Test sui livelli e sulle motivazioni.
