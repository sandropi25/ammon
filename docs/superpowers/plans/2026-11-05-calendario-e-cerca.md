# Calendario per giornata e pagina Cerca – Piano di esecuzione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** (1) vista Calendario per campionato e giornata con tutte le partite della stagione; (2) pagina "Cerca" per giocatore (scheda statistiche) e per squadra (partite in programma).

**Spec:** `2026-11-04-piattaforma-ammonizioni-design.md` §5 (schermate). Richieste dell'utente del 2026-11-05.

## Global Constraints
- Serie A predefinita e prima ovunque; Liga secondaria.
- Ora italiana (Europe/Rome) in tutte le date: giorno della settimana e mese per esteso ("sabato 8 novembre 2026 · 20:45").
- Ogni cartellino conta (subentrati e panchina).
- Database remoto (Supabase): poche query raggruppate, niente `carica_dati` per partita nelle liste; caching `st.cache_data` come nelle pagine esistenti.
- Logica in funzioni pure testate (`app/componenti*.py`), pagine sottili; `richiedi_password()` in cima a ogni pagina.

## Task 1: Numero di giornata
- ESPN non dà la giornata: `arbitri_fd.collega` (che già abbina ogni partita a quella di football-data) salva anche `Partita.giornata` dal campo `matchday` di football-data quando è vuota. Le partite già collegate prima ricevono la giornata alla prossima esecuzione: aggiungere un passo una tantum che, per le stagioni dei campionati, abbina anche le partite che hanno già l'arbitro ma non la giornata (una richiesta per stagione, percorso stagione intera).
- Test: giornata salvata; non sovrascrive una giornata già presente; partita senza corrispondenza resta None.

## Task 2: Pagina Calendario
- `app/pages/1_Calendario.py` (rinumerare le pagine se serve: Partite, Calendario, Dettaglio, Giocate, Impostazioni, Cerca).
- Selettori: campionato (Serie A predefinita, Liga) e giornata (predefinita la giornata in corso = la prima con partite non finite; frecce ◀ ▶). Se la stagione non ha giornate (dati senza `giornata`), raggruppa per settimana.
- Partite divise per giorno (stessa funzione di raggruppamento della pagina Partite), con orario; giocate: risultato, arbitro, gialli e rossi totali; da giocare: arbitro se designato, stato formazioni, link al Dettaglio.
- Test con DB di prova: giornata in corso, navigazione, giocate vs da giocare, nessun crash senza giornate.

## Task 2b: Derby e partite calde automatici (richiesta dell'utente: non deve inserirli lui)
- `config.DERBY_PREDEFINITI`: elenco curato di derby e rivalità vere, per nome squadra (risolto sugli id del DB con la stessa normalizzazione dei nomi di `arbitri_fd`; le squadre assenti dal DB vengono ignorate). Serie A: Inter–Milan, Roma–Lazio, Juventus–Torino, Genoa–Sampdoria, Juventus–Inter, Napoli–Roma, Fiorentina–Juventus, Juventus–Napoli, Atalanta–Brescia, Verona–Chievo, Cagliari–Torino? (no: solo rivalità riconosciute), Lazio–Napoli. Liga: Real Madrid–Barcelona, Real Madrid–Atlético Madrid, Barcelona–Espanyol, Sevilla–Real Betis, Athletic Club–Real Sociedad, Valencia–Levante, Celta Vigo–Deportivo, Atlético Madrid–Barcelona, Osasuna–Athletic Club. Il motore usa l'unione di questi e delle righe `ListaManuale` già presenti nel DB (l'utente ne aveva inserita una).
- **Campo caldo automatico** (non più a mano): una squadra ha il "campo caldo" se nelle partite casalinghe di campionato delle ultime 2 stagioni la media di cartellini (gialli + rossi, entrambe le squadre) supera di almeno il 20% la media del campionato, con almeno 15 partite casalinghe.
- **Impostazioni**: rimuovere le sezioni "Derby e rivalità" e "Campi caldi" dalla pagina (richiesta dell'utente: "non serve"). Al loro posto, sola lettura: elenco dei derby riconosciuti e dei campi caldi calcolati, con il motivo (es. "Napoli in casa: 5,1 cartellini a partita contro 4,0 di media").
- **Partita calda automatica** (`componenti.calore_partita`): punteggio = cartellini attesi della partita stimati da: media cartellini dei precedenti diretti (ultimi 5), media cartellini dell'arbitro designato, media cartellini delle due squadre nella stagione, derby/rivalità, posta in classifica. Una partita è "calda" se i cartellini attesi ≥ 5,5 (Serie A media ~4) oppure è un derby. Motivazioni in chiaro ("derby", "precedenti: 6,4 cartellini", "arbitro severo: 5,8").
- **Nuova pagina "Partite calde"**: tutte le partite **in programma della stagione** (Serie A e Liga, filtro con Serie A predefinita), ordinate per data, divise per giorno con orario, con i cartellini attesi e le motivazioni; in cima le prossime 7 giorni. Le partite di altri campionati ad alto rischio (piano subentranti) entreranno qui.
- Test: derby predefinito riconosciuto anche se il nome nel DB è diverso (alias); partita con precedenti molto nervosi segnata calda; partita tranquilla no; nessuna lista manuale necessaria.

## Task 2c: Formazioni probabili automatiche (richiesta dell'utente: non deve modificarle lui)
- Nessuna fonte gratuita e consentita dà le probabili (ESPN: rosters vuoti prima delle ufficiali, verificato). Decisione: le calcola l'app.
- `caricamento/formazioni.probabili_automatiche(s, squadra_id, prima_di) -> list[Titolare]`: modulo più usato nelle ultime 5 partite di campionato; per ogni posto del modulo il giocatore titolare più spesso in quel ruolo/corsia nelle ultime 5; esclusi gli squalificati noti (rosso nell'ultima partita; gialli nel campionato che raggiungono una soglia di squalifica di `SOGLIE_DIFFIDA` + 1 all'ultima partita); al loro posto il più usato dello stesso ruolo non squalificato. Griglia sintetica coerente. Sostituisce `ultimo_xi` come ricaduta quando mancano le ufficiali.
- Il job pre-partita resta: ufficiali appena escono (da 75 minuti prima), sostituiscono le probabili.
- App: rimuovere dalla pagina Dettaglio la correzione manuale delle formazioni probabili; mostrare la scritta "formazioni probabili (calcolate)" o "formazioni ufficiali".
- Usare anche le quote 1X2 che ESPN dà nel summary (`odds`, DraftKings) per sapere quale squadra è sfavorita (servirà ai subentranti): salvare probabilità implicite casa/pareggio/trasferta sulla partita se presenti.
- Test: squalificato per rosso escluso e sostituito dallo stesso ruolo; modulo più usato; ricaduta senza storico.

## Task 3: Pagina Cerca
- Casella unica; ricerca senza accenti e maiuscole su `Giocatore.nome` e `Squadra.nome` (normalizzazione in Python sui nomi caricati una volta e messi in cache; al massimo 20 risultati).
- Giocatore → scheda: squadra e ruolo attuali (ultima presenza), prossima partita della sua squadra con link e sua probabilità (da `MercatoAmmonizioni` solo per quella partita); tabella per stagione e competizione: presenze (minuti > 0), minuti, gialli (compresi quelli dalla panchina), rossi, falli commessi e subiti, totali e per 90'; diffidato sì/no (campionato); ultime 5 partite (data, avversario, minuti, falli, giallo); gialli presi con l'arbitro della prossima partita (se designato); storia contro l'avversario della prossima partita e nei derby (riuso di `storia_contro`).
- Squadra → partite in programma (prossime 30 giorni) divise per giorno con link.
- Test: ricerca "calhanoglu" trova "Çalhanoğlu"; scheda con giallo dalla panchina conteggiato; squadra mostra le partite in programma in ordine.
