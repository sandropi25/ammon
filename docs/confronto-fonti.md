# Confronto tra le fonti di dati

Data: 2026-11-05. Fonte usata in automatico dall'app: **API-Football**. Le altre app compaiono solo come link nella pagina della partita, per il controllo visivo: nessuna viene letta in automatico.

Legenda: ✅ disponibile · ➖ parziale · ❌ assente · ❓ da verificare a mano.

## Cosa serve al modello

| Dato (fattore del modello) | API-Football | Sofascore | FBref | FotMob | WhoScored | Transfermarkt | Diretta |
|---|---|---|---|---|---|---|---|
| Gialli e rossi per partita (base) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Minuti giocati (base) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ |
| Falli commessi per partita (giocatore "in ritardo") | ✅ | ✅ | ❓ ¹ | ✅ | ✅ | ❌ | ➖ |
| Falli subiti per partita (duello) | ✅ | ✅ | ❓ ¹ | ✅ | ✅ | ❌ | ❌ |
| Dribbling tentati / riusciti (duello) | ✅ | ✅ | ❓ ¹ | ✅ | ✅ | ❌ | ❌ |
| Tiri, gol, assist, voto (forma) | ✅ | ✅ | ➖ ¹ | ✅ | ✅ | ➖ | ➖ |
| Posizione in campo nella formazione (avversario diretto) | ✅ ² | ✅ | ❌ | ✅ | ✅ | ❌ | ➖ |
| Nome dell'arbitro | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Statistiche arbitro (gialli a partita) | ➖ ³ | ✅ | ❌ | ❓ | ❓ | ✅ | ❌ |
| Formazioni ufficiali | ✅ | ✅ | ➖ | ✅ | ✅ | ➖ | ✅ |
| Formazioni probabili | ❌ ⁴ | ✅ | ❌ | ✅ | ✅ | ❌ | ➖ |
| Diffide / squalifiche | ➖ ⁵ | ➖ | ❌ | ➖ | ➖ | ✅ | ➖ |
| Storico multi-stagione e con altre maglie | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ➖ |

Note:
1. **FBref** a gennaio 2026 ha perso i dati avanzati Opta (accordo chiuso da Stats Perform). Restano i dati base storici; falli, dribbling e le tabelle "Miscellaneous" con ogni probabilità non ci sono più per le partite nuove: da verificare sul sito.
2. La posizione (`grid`) arriva con le formazioni (`/fixtures/lineups`). Per le partite passate l'app la ricava dalla formazione ufficiale salvata; resta da verificare con la chiave se `/fixtures?id=X` la restituisce anche per lo storico (vedi README, "Da verificare con la chiave").
3. API-Football dà solo il nome dell'arbitro: l'app **calcola** gialli e falli a partita dallo storico salvato (spec §3.2). Con poche partite registrate il fattore arbitro resta vicino a 1.
4. Nel piano gratuito l'app usa come probabili l'ultimo undici schierato, correggibile a mano (spec §5). Probabili automatiche: Sportmonks (estensione prevista, spec §8).
5. L'app conta i gialli in Serie A della stagione e applica le soglie di diffida (da verificare sul regolamento in vigore).

## Accesso

| | API-Football | Sofascore | FBref | FotMob | WhoScored | Transfermarkt | Diretta |
|---|---|---|---|---|---|---|---|
| API pubblica | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Lettura automatica consentita | ✅ (chiave) | ❌ | ❌ (blocca i bot) | ❌ | ❌ | ❌ | ❌ |
| Costo | gratis 100 richieste/giorno; Pro 19 $/mese | gratis (app) | gratis | gratis (app) | gratis | gratis | gratis (app) |
| Fornitore dei dati | proprio | proprio | dati base | Opta | Opta | proprio | proprio |

## Conclusione

- Per i numeri che il modello usa (gialli, falli commessi e subiti, dribbling, minuti, forma, posizione) **API-Football copre tutto** ed è l'unica fonte che si può leggere in automatico nel rispetto delle regole.
- Dove API-Football è più debole: **formazioni probabili** e **statistiche arbitri già pronte**. L'app compensa con l'ultimo undici e con il calcolo dallo storico; Sofascore, FotMob e WhoScored (probabili) e Transfermarkt (arbitri, squalifiche) restano utili come controllo a occhio dai link.
- **FBref** dopo gennaio 2026 non è più un riferimento per falli e dribbling: utile solo per lo storico di base.
- Cosa controllare a mano la prima settimana: confrontare per 3-4 giocatori i falli e i gialli della stagione su API-Football (pagina Dettaglio, tabella del duello) con Sofascore o FotMob. Differenze piccole sono normali (fornitori diversi contano i falli in modo leggermente diverso); differenze grandi indicano un problema di caricamento.
