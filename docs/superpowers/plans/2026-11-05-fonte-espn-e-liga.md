# Fonte ESPN gratuita, arbitri da football-data.org e Liga spagnola – Piano di esecuzione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Usare dati gratuiti per la stagione in corso e la scorsa: ESPN (API pubblica, senza chiave) come fonte di partite, formazioni e statistiche giocatore; football-data.org (chiave gratuita) per gli arbitri; aggiungere la Liga spagnola accanto alla Serie A.

**Architecture:** Nuova classe `fonti/espn.py` che implementa il Protocol `Fonte` esistente; `fonti/football_data.py` fornisce gli arbitri, collegati alle partite ESPN per data e squadre. Il motore resta uguale tranne due adattamenti per i dati che ESPN non ha (dribbling, voto). I campionati diventano una lista configurabile (Serie A, Liga) invece della costante Serie A. `ApiFootball` resta nel codice come fonte alternativa (per chi passa al Pro).

**Tech Stack:** come fase 1 (Python, httpx, SQLAlchemy, Streamlit, pytest, respx).

**Spec:** `2026-11-04-piattaforma-ammonizioni-design.md` (§2: "Cambiare fonte dati vuol dire scrivere una nuova classe in `fonti/`"; §8 estensioni). Piano fase 1: `docs/superpowers/plans/2026-11-04-piattaforma-ammonizioni-fase1.md`.

## Verifiche già fatte (2026-11-05, chiamate reali)

- ESPN `https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates=AAAA&limit=1000` → tutte le partite dell'anno solare (Serie A 2025: 368). `dates=AAAAMMGG` → un giorno. Un intervallo di date dà 400.
- `.../{slug}/summary?event={id}` → `rosters[]` (per squadra: `formation`, `roster[]` con `starter`, `athlete.id`, `athlete.displayName`, `position.abbreviation`, `formationPlace`, `stats[]`), `keyEvents[]` (Substitution con `clock.displayValue` "57'" e `participants`, Yellow Card, ...).
- `stats` per giocatore: `foulsCommitted`, `foulsSuffered`, `yellowCards`, `redCards`, `totalShots`, `shotsOnTarget`, `totalGoals`, `goalAssists`, `offsides`, `subIns`, `appearances` (+ `saves`, `goalsConceded` per i portieri). **Mancano** dribbling, voto, minuti, arbitro.
- Slug verificati: `ita.1`, `ita.coppa_italia`, `esp.1`, `esp.copa_del_rey`, `uefa.champions`, `uefa.europa`, `uefa.europa.conf`. Storico Serie A 2024 e 2025 presente con statistiche. `athlete.id` è unico tra competizioni e maglie (es. De Gea alla Fiorentina).
- Ruoli titolari osservati: `G`, `RB`, `CD-R`, `CD-L`, `LB`, `CM`, `CM-R`, `CM-L`, `RM`, `LM`, `AM`, `AM-R`, `AM-L`, `RF`, `LF`, `F`.
- football-data.org: Serie A e Liga nel piano gratuito ("free forever"); la risorsa Match ha `referees[]` con `id`, `name`, `type` ("REFEREE", ...). **Da verificare con una chiave:** che `referees` sia valorizzato nel piano gratuito.

## Global Constraints

- Nessuna lettura automatica di Sofascore, FotMob, WhoScored, Diretta, FBref, Transfermarkt (solo link).
- ESPN è un'API non ufficiale: richieste educate (al massimo 30 al minuto, `User-Agent` del progetto, nessun parallelismo), retry come `ApiFootball` (attese 1, 2, 4, 8 s), nessun crash se la struttura cambia: errore chiaro nei log e job che termina con `completo=False`.
- football-data.org piano gratuito: **10 richieste al minuto**; chiave in `FOOTBALL_DATA_KEY` (env) o impostazione `chiave_football_data`.
- Stagioni: corrente + 2 precedenti, come la fase 1. Stagione S = partite dal 1° luglio S al 30 giugno S+1.
- Id interni delle competizioni invariati e aggiunti: Serie A `135`, Coppa Italia `137`, Liga `140`, Copa del Rey `143`, Champions `2`, Europa League `3`, Conference `848`.
- Tutto il resto delle Global Constraints della fase 1 resta valido (UTC, italiano, decimali con la virgola, 2–70%).

## Review Focus

1. **Struttura ESPN cambiata o campo mancante** (es. `stats` assente, `position` vuota) → il giocatore viene saltato con un log, la partita non viene segnata come scaricata se nessun giocatore ha statistiche, nessuna eccezione. Test in Task 2.
2. **Partita ESPN senza corrispondenza su football-data.org** (orario spostato, nome squadra diverso) → arbitro `None`, fattore arbitro neutro, nessun errore; tabella di alias per i nomi. Test in Task 3.
3. **Giocatore espulso o entrato e uscito** → minuti corretti (entrata dal minuto della sostituzione, uscita a sostituzione o rosso, recuperi conteggiati come 90). Test in Task 2.
4. **Campionato senza dribbling o voto** → duello e forma usano solo i dati presenti, senza dimezzare il segnale. Test in Task 4.
5. **Partite di Liga e Serie A nello stesso giorno** → classifica, posta, diffide e derby separati per campionato. Test in Task 5.

---

### Task 0: Cancello – arbitri su football-data.org (azione dell'utente + verifica)

- [ ] **Utente:** registrazione gratuita su football-data.org, `setx FOOTBALL_DATA_KEY "..."`.
- [ ] **Controllore:** `GET https://api.football-data.org/v4/competitions/SA/matches?dateFrom=…&dateTo=…` con header `X-Auth-Token` su una giornata giocata; stessa cosa per `PD` (Liga). Esito atteso: `referees` con almeno un `type == "REFEREE"`. Se vuoto nel piano gratuito: **fermarsi** e decidere con l'utente (arbitri inseriti a mano, oppure fattore arbitro disattivato).

### Task 1: Configurazione campionati

**Files:** Modify `src/ammonizioni/config.py`, `tests/test_config.py`.
**Produces:** `COMPETIZIONI` con le 7 voci; `CAMPIONATI: tuple[int, ...] = (135, 140)`; `SLUG_ESPN: dict[int, str]`; `CODICE_FOOTBALL_DATA: dict[int, str] = {135: "SA", 140: "PD"}`; `COPPE_NAZIONALI: dict[int, int] = {135: 137, 140: 143}`; `SOGLIE_DIFFIDA: dict[int, tuple[int, ...]]` con Serie A `(4, 9, 13, 16, 19)` e Liga `(4, 9, 14, 19)` (**entrambe da verificare sui regolamenti in vigore**); `fonte_dati()` legge env `FONTE_DATI` (`"espn"` predefinito, `"api_football"` alternativa).
- [ ] Test: slug e codici per ogni competizione; `fonte_dati()` predefinito e da env; errore chiaro per valore sconosciuto.

### Task 2: Fonte ESPN

**Files:** Create `src/ammonizioni/fonti/espn.py`, `tests/fonti/test_espn.py`, `tests/dati_prova/espn/*.json` (risposte reali ridotte: scoreboard anno, summary Serie A con sostituzioni e un giallo, summary con espulsione, summary prima delle formazioni).
**Interfaces:** `Espn(limite: LimiteRichieste, client=None, dormi=time.sleep)` implementa `Fonte`.
- `partite(competizione_id, stagione)`: due chiamate (`dates=S` e `dates=S+1`, `limit=1000`), filtro 1/7/S–30/6/S+1. Mappa: `id`=event id, `data_utc` da `date`, squadre da `competitions[0].competitors` (`homeAway`), gol, `stato`: `STATUS_FULL_TIME`→`FT`, dopo i supplementari→`AET`, rigori→`PEN`, `STATUS_SCHEDULED`→`NS`, `STATUS_POSTPONED`→`PST`, `STATUS_CANCELED`→`CANC`, altri→stringa originale. `giornata`: dalla settimana del campionato se presente, altrimenti `None`. `arbitro_nome=None` (arriva dal Task 3).
- `statistiche(partita_id)`: da `rosters`. Ruolo: `G`→G; `RB/LB/CD*/SW/RWB/LWB`→D; `CM*/DM*/RM/LM/AM*`→M; `F/CF*/RF/LF/ST/RW/LW`→F (sconosciuto → M con log). **Minuti:** titolare 0→90, sostituito → minuto della sostituzione; entrato → 90 − minuto di entrata; rosso → minuto del rosso; minuti "45'+2" contano 45, "90'+3" contano 90. `dribbling_tentati = dribbling_riusciti = 0`, `voto = None`.
- `formazioni(partita_id)`: titolari solo se `rosters` ha 11 `starter` per squadra; altrimenti `[]`. **Griglia sintetica:** riga per linea (G=1, D=2, DM/CM/RM/LM=3, AM=4, F=5); dentro la riga i giocatori ordinati da destra a sinistra (R, CR, C, CL, L) e numerati da 1 → `"riga:colonna"`, così `avversario_diretto` funziona senza modifiche.
- Dopo ogni chiamata `limite.prendi(Priorita.…)`; il `LimiteRichieste` per ESPN si crea con `max_minuto=30`, `max_giorno=5000`.
- [ ] Test (respx + JSON reali): conversione statistiche e ruoli; minuti (titolare intero, sostituito al 57', entrato al 61', espulso al 70', recupero "90'+3"); griglia sintetica 4-3-3 vs 4-2-3-1 e avversario diretto terzino destro ↔ esterno sinistro; formazioni non uscite → `[]`; giocatore senza `stats` saltato; risposta senza `rosters` → `ErroreFonte` con messaggio chiaro; stati AET/PEN/PST.

### Task 3: Arbitri da football-data.org

**Files:** Create `src/ammonizioni/fonti/football_data.py`, `src/ammonizioni/caricamento/arbitri_fd.py`, tests e JSON di prova.
**Interfaces:** `FootballData(chiave, limite, client=None)` con `arbitri(codice: str, dal: date, al: date) -> list[ArbitroPartita(data_utc, casa, trasferta, arbitro_id, arbitro_nome)]` (una chiamata per intervallo; limite 10/minuto). `arbitri_fd.collega(s, fonte_fd, competizione_id, dal, al) -> int`: per ogni partita del DB senza arbitro, trova quella di football-data con stessa data (±3 ore) e squadre uguali dopo normalizzazione (minuscolo, senza accenti, senza "FC", "AC", "SSC", "CF", "Calcio", "Club", anno) più una tabella `ALIAS_SQUADRE` (es. "Internazionale"↔"Inter", "AS Roma"↔"Roma", "Atlético Madrid"↔"Club Atlético de Madrid"); salva `Arbitro` per `id` football-data (nome visualizzato dal campo `name`) e `Partita.arbitro_id`. Restituisce i collegamenti fatti; le partite non collegate sono loggate.
- [ ] Test: collegamento riuscito; orario spostato di 2 ore; alias; nessuna corrispondenza → arbitro None e log; stesso arbitro in Serie A e Champions → una riga.

### Task 4: Motore con dati mancanti

**Files:** Modify `motore/fattori/duello.py`, `motore/dati.py`, tests.
- Duello: se la media di ruolo del campionato per `dribbling90` è 0 (fonte senza dribbling) il termine dribbling vale 0 (rapporto neutro), e così per `falli_subiti90`.
- Forma: media **solo delle componenti disponibili** (`ga90` sempre; `voto` solo se l'avversario ha voti), non più "componente mancante = 0".
- [ ] Test: avversario senza voti con forma in gol → stesso fattore che con il solo `ga90`; media dribbling 0 → nessun effetto; con API-Football (dribbling e voti presenti) i risultati della fase 1 non cambiano (test esistenti verdi).

### Task 5: Più campionati

**Files:** Modify `caricamento/notturno.py`, `caricamento/storico.py`, `motore/dati.py` (medie, posta, diffide per campionato), `motore/fattori/situazione.py` (soglie per campionato), `app/componenti.py` e pagine (filtro campionato), `scheduler/pre_partita.py`, tests.
- Ogni uso di `135` come "il campionato" diventa `CAMPIONATI` / il `competizione_id` della partita. Medie di campionato calcolate sul campionato della partita. Posta sulla classifica di quel campionato. Diffida: gialli nel campionato della partita, soglie di `SOGLIE_DIFFIDA`. Storico: competizioni = campionati + coppe nazionali + coppe europee.
- App: selettore "Serie A / Liga / Tutti" nella pagina Partite e nel registro; liste derby e campi caldi con le squadre di entrambi i campionati.
- [ ] Test: due partite lo stesso giorno, una per campionato → medie e posta separate; diffida in Liga con 4 gialli in Liga e 3 in Copa del Rey → diffidato; filtro app.

### Task 6: Scheduler e job con la nuova fonte

**Files:** Modify `scheduler/comune.py`, `scheduler/notte.py`, `scheduler/pre_partita.py`, `.github/workflows/*.yml`, README.
- `crea_fonte(s)` sceglie `Espn` o `ApiFootball` da `fonte_dati()`. Notte: calendari e statistiche dei campionati (ultimi 7 giorni), poi `arbitri_fd.collega` per le partite dei prossimi 7 giorni e degli ultimi 7, poi esiti, poi storico (senza tetto giornaliero stretto: ESPN non lo ha, resta il tetto di cortesia).
- Pre-partita: finestra 75 minuti per tutti i campionati. Cron `*/10 10-20 * * *` (Liga fino alle 21:00 ora spagnola). README: minuti GitHub ≈ 2000+/mese → repository pubblico consigliato.
- Controllo di salute: `scripts/controlla_espn.py` scarica una partita nota e verifica i campi usati; lo esegue anche il job notturno e, se fallisce, scrive `completo=False` con un messaggio chiaro ("La struttura dei dati ESPN è cambiata").
- [ ] Test: scelta della fonte da env; notte con Espn finta e FootballData finta; controllo di salute che segnala un campo mancante.

### Task 7: Prova sulla scorsa stagione per entrambi i campionati

**Files:** Modify `backtest/prova.py`, `scripts/prova_stagione.py` (`--campionato 135|140`), tests.
- [ ] Test esistenti adattati; scelta semplice per campionato.
- [ ] **Esecuzione reale:** carica lo storico con ESPN (gratis, una notte), poi `--stagione 2025 --campionato 135` e `--campionato 140`; riportare i numeri all'utente.

### Task 8: Documentazione

- [ ] README (fonte predefinita ESPN, chiave football-data, come tornare ad API-Football con `FONTE_DATI=api_football`), `docs/confronto-fonti.md` (colonna ESPN e football-data.org).
