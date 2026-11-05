# Confronto tra le fonti di dati

Data: 2026-11-05. Fonti usate in automatico dall'app: **ESPN** (calendario, formazioni, statistiche dei giocatori) e **football-data.org** (arbitri di Serie A e Liga). **API-Football** resta nel codice come fonte alternativa (`FONTE_DATI=api_football`). Le altre app compaiono solo come link nella pagina della partita, per il controllo visivo: nessuna viene letta in automatico.

Legenda: ✅ disponibile · ➖ parziale · ❌ assente · ❓ da verificare a mano.

## Cosa serve al modello

| Dato (fattore del modello) | ESPN | football-data.org | API-Football | Sofascore | FBref | FotMob | WhoScored | Transfermarkt | Diretta |
|---|---|---|---|---|---|---|---|---|---|
| Gialli e rossi per partita (base) | ✅ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Minuti giocati (base) | ➖ ⁶ | ❌ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ |
| Falli commessi per partita (giocatore "in ritardo") | ✅ | ❌ | ✅ | ✅ | ❓ ¹ | ✅ | ✅ | ❌ | ➖ |
| Falli subiti per partita (duello) | ✅ | ❌ | ✅ | ✅ | ❓ ¹ | ✅ | ✅ | ❌ | ❌ |
| Dribbling tentati / riusciti (duello) | ❌ | ❌ | ✅ | ✅ | ❓ ¹ | ✅ | ✅ | ❌ | ❌ |
| Tiri, gol, assist (forma) | ✅ | ❌ | ✅ | ✅ | ➖ ¹ | ✅ | ✅ | ➖ | ➖ |
| Voto del giocatore (forma) | ❌ | ❌ | ✅ | ✅ | ➖ ¹ | ✅ | ✅ | ➖ | ➖ |
| Posizione in campo nella formazione (avversario diretto) | ✅ ⁷ | ❌ | ✅ ² | ✅ | ❌ | ✅ | ✅ | ❌ | ➖ |
| Nome dell'arbitro | ❌ | ✅ ⁸ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Statistiche arbitro (gialli a partita) | ❌ | ❌ | ➖ ³ | ✅ | ❌ | ❓ | ❓ | ✅ | ❌ |
| Formazioni ufficiali | ✅ | ❌ | ✅ | ✅ | ➖ | ✅ | ✅ | ➖ | ✅ |
| Formazioni probabili | ❌ ⁴ | ❌ | ❌ ⁴ | ✅ | ❌ | ✅ | ✅ | ❌ | ➖ |
| Diffide / squalifiche | ➖ ⁵ | ❌ | ➖ ⁵ | ➖ | ❌ | ➖ | ➖ | ✅ | ➖ |
| Storico multi-stagione e con altre maglie | ✅ | ➖ ⁹ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ |

Note:
1. **FBref** a gennaio 2026 ha perso i dati avanzati Opta (accordo chiuso da Stats Perform). Restano i dati base storici; falli, dribbling e le tabelle "Miscellaneous" con ogni probabilità non ci sono più per le partite nuove: da verificare sul sito.
2. La posizione (`grid`) di API-Football arriva con le formazioni (`/fixtures/lineups`). Per le partite passate l'app la ricava dalla formazione ufficiale salvata; resta da verificare con la chiave se `/fixtures?id=X` la restituisce anche per lo storico (vedi README, "Da verificare con la chiave").
3. API-Football dà solo il nome dell'arbitro: l'app **calcola** gialli e falli a partita dallo storico salvato (spec §3.2). Con poche partite registrate il fattore arbitro resta vicino a 1. Lo stesso vale con football-data.org.
4. L'app usa come probabili l'ultimo undici schierato, correggibile a mano (spec §5). Probabili automatiche: Sportmonks (estensione prevista, spec §8).
5. L'app conta i gialli della stagione nel campionato della partita e applica le soglie di diffida di ciascun campionato (da verificare sul regolamento in vigore).
6. ESPN non dà i minuti giocati: l'app li **ricava** da titolari, sostituzioni e minuti degli eventi della partita, quindi sono una stima (non conta il recupero esatto).
7. ESPN dà la posizione (ruolo) di ogni giocatore e i titolari nella formazione, con cui l'app individua l'avversario diretto.
8. football-data.org dà l'arbitro di Serie A (`SA`) e Liga (`PD`) già nel piano gratuito (10 richieste al minuto, con chiave). Non copre Coppa Italia, Copa del Rey e coppe europee.
9. football-data.org è usata solo per gli arbitri, collegati alle partite ESPN per data e squadre; l'app chiede una stagione per volta (una richiesta per campionato e stagione) e, se una stagione non è accessibile col piano gratuito, quelle partite restano senza arbitro.

## Accesso

| | ESPN | football-data.org | API-Football | Sofascore | FBref | FotMob | WhoScored | Transfermarkt | Diretta |
|---|---|---|---|---|---|---|---|---|---|
| API pubblica | ✅ (non ufficiale) | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Lettura automatica consentita | ✅ (senza chiave, non documentata) | ✅ (chiave gratuita) | ✅ (chiave) | ❌ | ❌ (blocca i bot) | ❌ | ❌ | ❌ | ❌ |
| Costo | gratis, nessun limite dichiarato (l'app usa 30 richieste/minuto) | gratis, 10 richieste/minuto | gratis 100 richieste/giorno (stagione corrente solo con Pro, 19 $/mese) | gratis (app) | gratis | gratis (app) | gratis | gratis | gratis (app) |
| Fornitore dei dati | proprio | proprio | proprio | proprio | dati base | Opta | Opta | proprio | proprio |
| Rischio | la struttura può cambiare senza preavviso (controllo notturno `scripts/controlla_espn.py`) | limiti del piano gratuito | piano gratuito senza stagione corrente | - | - | - | - | - | - |

## Conclusione

- **Default attuale: ESPN + football-data.org.** ESPN fornisce gratis tutto ciò che serve al modello tranne dribbling, voto e arbitro (il modello usa solo i dati presenti, quindi dribbling e voto non pesano); i minuti sono ricavati dagli eventi. football-data.org aggiunge l'arbitro di Serie A e Liga gratis. Costo totale: zero, senza il piano Pro di API-Football.
- Il rischio di ESPN è che non è ufficiale: per questo c'è il controllo di salute notturno, che avvisa nel log se la struttura cambia. Se diventa inaffidabile si torna ad **API-Football** con `FONTE_DATI=api_football` (per la stagione corrente serve il piano Pro), che copre tutto (gialli, falli commessi e subiti, dribbling, minuti, forma, posizione) ed è l'altra fonte leggibile in automatico nel rispetto delle regole.
- Dove le fonti automatiche sono più deboli: **formazioni probabili** e **statistiche arbitri già pronte**. L'app compensa con l'ultimo undici e con il calcolo dallo storico; Sofascore, FotMob e WhoScored (probabili) e Transfermarkt (arbitri, squalifiche) restano utili come controllo a occhio dai link.
- **FBref** dopo gennaio 2026 non è più un riferimento per falli e dribbling: utile solo per lo storico di base.
- Cosa controllare a mano la prima settimana: confrontare per 3-4 giocatori i falli e i gialli della stagione su ESPN (pagina Dettaglio, tabella del duello) con Sofascore o FotMob. Differenze piccole sono normali (fornitori diversi contano i falli in modo leggermente diverso); differenze grandi indicano un problema di caricamento.
