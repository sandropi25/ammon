# Schermata di accesso, Home con statistiche e menu dei campionati – Piano di esecuzione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

Richieste dell'utente del 2026-11-06.

## Task L1: Schermata di accesso
- Al posto del solo campo password: pagina di benvenuto a tutto schermo con lo sfondo a cartellini animato, logo grande, titolo **"Benvenuto nel mondo del Yellow!"**, sottotitolo breve (es. "Pronostici sui cartellini di Serie A e Liga"), scheda centrale con campo password stilizzato, pulsante "Entra", messaggio d'errore gentile se sbagliata, opzione "Ricordami su questo dispositivo" (cookie/parametro firmato con scadenza 30 giorni; senza salvare la password in chiaro).
- Nessun menu visibile prima dell'accesso. Funziona su telefono (tastiera che non copre il pulsante).
- Sicurezza invariata: password nei Secrets, confronto a tempo costante (`hmac.compare_digest`), comportamento fail-closed già esistente in `app/auth.py` conservato; tentativi sbagliati ripetuti → breve attesa.

## Task L2: Menu dei campionati a tendina con le partite della giornata
- Nella barra in alto, al posto dei pulsanti Serie A / Liga / Tutti: due voci **Serie A ▾** e **Liga ▾**. Aprendo la tendina: titolo "Giornata 11" e l'elenco delle partite della **giornata corrente** (orario, squadre, badge 🔥 se calda); un clic apre direttamente il Dettaglio della partita. In fondo "Tutto il calendario →".
- La scelta del campionato per le pagine (filtro) resta, ma passa da queste voci (clic sul nome del campionato = filtro).
- Su telefono: le tendine diventano un pannello a scomparsa.
- Realizzazione: `st.popover` nella barra (Streamlit ≥ 1.31) o componente HTML; dati dalla cache esistente (giornata corrente come nel Calendario).

## Task L3: Pagina Home (prima voce della barra)
- **Home** diventa la pagina iniziale.
- Riquadri in alto: partite di oggi/domani, partita più calda della giornata, giocatore più a rischio della giornata, ultime giocate e rendimento.
- **Classifica degli ammoniti** della stagione (campionato scelto): dal più ammonito al meno, con gialli, rossi, gialli per 90', falli commessi per 90', presenze; ricerca e ordinamento; clic → scheda del giocatore (pagina Cerca).
- **Grafici**: barre dei 15 più ammoniti; dispersione falli/90' vs gialli/90' (chi fa tanti falli e prende pochi gialli = "in ritardo", evidenziati); gialli per giornata nel campionato; media gialli per squadra. Libreria: grafici nativi Streamlit / Altair (già incluso), colori del tema, entrambi i temi, leggibili su telefono.
- **Biografie**: dati anagrafici da ESPN (età, nazionalità, altezza, ruolo — endpoint atleta, una richiesta per giocatore, salvati nel DB con aggiornamento al massimo mensile) e un breve profilo da **Wikipedia** (API REST di riepilogo, gratuita, testo CC BY-SA con link e attribuzione "Fonte: Wikipedia"); caricati nel job notturno solo per i giocatori di Serie A e Liga che non li hanno, con limite di richieste per notte. Niente foto.
- Regole: aggregati Postgres convertiti (Decimal), query raggruppate, cache con `max_entries`, html.escape, prova nel browser (scuro/chiaro, 375 px).
