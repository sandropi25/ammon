# Probabili subentranti e partite ad alto rischio – Piano di esecuzione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (A) mettere in classifica anche i giocatori della panchina che probabilmente entreranno, con una probabilità ridotta in base ai minuti che giocano di solito; (B) aggiungere poche sfide di altri campionati, scelte per nome, che storicamente hanno almeno 6,5 cartellini a partita.

**Architecture:** (A) nuovo modulo `motore/subentranti.py` che stima, dallo storico, quanto spesso un panchinaro entra, quanti minuti gioca e il ruolo dei cambi della sua squadra; `classifica` aggiunge i candidati con l'etichetta "subentrante". (B) `config.SFIDE_ALTO_RISCHIO` (coppie di squadre ESPN per campionato) + nuova competizione "altri campionati" caricata solo per le squadre in elenco; un filtro di soglia sugli scontri diretti decide quali sfide mostrare.

**Spec:** `2026-11-04-piattaforma-ammonizioni-design.md` (§4: per ogni titolare; questo piano estende ai subentranti per richiesta dell'utente del 2026-11-05). Piano precedente: `2026-11-05-fonte-espn-e-liga.md`.

## Decisioni dell'utente (2026-11-05)

- Contare ogni cartellino: subentrati anche 1 minuto, ammoniti in panchina (già in corso sul branch `panchina`).
- Candidati: titolari **e** probabili subentranti, anche se il dato è meno preciso; per ruolo e tenendo conto della tendenza dei cambi (squadra che deve rincorrere → più attaccanti).
- Sfide di altri campionati: solo derby o sfide storicamente "calde", e solo se la media di cartellini (gialli + rossi) negli scontri diretti è **almeno 6,5**; altrimenti non si inseriscono.
- Modalità live (risultato durante la partita) **fuori da questo piano**: estensione successiva.

## Global Constraints

- Serie A resta la competizione fondamentale: nessun risultato di Serie A per i titolari cambia (test di regressione).
- Fonte ESPN; nessuna lettura automatica di altri siti.
- Tutti i cartellini contano (vedi decisioni).
- Testi in italiano, decimali con la virgola.

## Review Focus

1. Squadra senza panchina nota (formazioni probabili) → nessun subentrante, nessun errore.
2. Giocatore che non entra mai (terzo portiere) → probabilità di subentro ~0, non compare.
3. Sfida in elenco con pochi scontri diretti (< 3) → non mostrata, con motivo nel log.
4. Campionato extra con dati ESPN incompleti (senza `stats`) → sfida saltata, nessun crash.
5. Le partite extra non entrano nelle medie di Serie A e Liga né nelle loro classifiche.

---

### Task A1: Statistiche di subentro

**Files:** Create `src/ammonizioni/motore/subentranti.py`, tests.
**Produces:** `ProfiloSubentro(giocatore_id, panchine, ingressi, minuti_medi, ruolo)`; `profilo_subentro(storico: list[RigaPresenza]) -> ProfiloSubentro` sulle ultime 15 partite in cui il giocatore era in distinta (titolare False); `probabilita_ingresso = ingressi / panchine` con restringimento verso la media del ruolo (8 panchine di prior).
- [ ] Test: entra 7 volte su 10 → ~0,6–0,7; terzo portiere 0 su 15 → < 0,05; nessuna panchina → None.

### Task A2: Tendenza dei cambi della squadra

**Produces:** `tendenza_cambi(s, squadra_id, prima_di) -> dict[ruolo, float]` = quota dei subentri per ruolo nelle ultime 10 partite della squadra; `sfavorita(dati, squadra_id) -> bool` dalla posta/classifica (squadra con meno punti per partita dell'avversaria di almeno 0,5). Se sfavorita, i subentri di attaccanti pesano ×1,2 e quelli di difensori ×0,8 (valori in `Pesi`, modificabili).
- [ ] Test: squadra che fa entrare soprattutto attaccanti → quota F alta; sfavorita → F pesa di più.

### Task A3: Subentranti in classifica

**Files:** Modify `motore/classifica.py`, `motore/dati.py` (panchina: giocatori in distinta della formazione ufficiale; con le probabili, i giocatori della rosa entrati in almeno 2 delle ultime 5 partite), `motore/tipi.py` (`Candidato.subentrante: bool`), app (etichetta "subentrante").
- **Quali subentranti mostrare (decisione dell'utente, aggiornata):** **tutti** i panchinari che hanno una possibilità concreta di entrare, anche se non sono più fallosi della media (l'utente a volte scommette proprio su quelli). Regole: (1) `probabilita_ingresso ≥ 0,15` (esclude chi non entra quasi mai, es. terzo portiere); (2) ognuno viene collegato al titolare dello **stesso ruolo** più spesso sostituito (minuti medi da titolare più bassi) → "può entrare al posto di X" (se nessun titolare di quel ruolo viene sostituito, "può entrare" senza nome). (3) Gialli90 / falli90 sopra la media del ruolo **non filtrano**: danno solo un'evidenza ("sopra la media") nell'app. I subentranti stanno in una tabella separata sotto i titolari, ordinati per probabilità.
- Probabilità del subentrante = `probabilita_ingresso × (1 − exp(−tasso_base90 × minuti_medi/90))` × fattori arbitro, contesto, situazione, storia (niente duello: avversario diretto ignoto). Limite 2–70%.
- App: etichetta "subentrante · può entrare al posto di X", con i suoi gialli e falli per 90' accanto alla media del ruolo.
- [ ] Test di regressione: probabilità e ordine dei **titolari** di una partita di Serie A identici a prima. Test: subentrante che entra spesso, collegato al titolare dello stesso ruolo più sostituito; subentrante con gialli e falli sotto la media → compare comunque, senza evidenza; sopra la media → compare con evidenza; nessun titolare dello stesso ruolo sostituito → "può entrare" senza nome; terzo portiere (entra < 15%) → non compare.

### Task A4: Prova sulla scorsa stagione con i subentranti

- `prova_stagione` conta un successo anche se tra i primi 3 c'è un subentrante ammonito; riga in più "di cui subentranti nei primi 3: N". Opzione `--solo-titolari` per confrontare con prima.

### Task B1: Sfide ad alto rischio – configurazione e caricamento

**Files:** `config.py` (`CAMPIONATI_EXTRA = {"arg.1": ..., "tur.1": ..., "gre.1": ..., "sco.1": ..., "srb.1": ..., "bra.1": ..., "por.1": ...}` con slug verificati dal vivo; `SFIDE_ALTO_RISCHIO` con le coppie: Boca–River, Galatasaray–Fenerbahçe, Olympiacos–Panathinaikos, Celtic–Rangers, Stella Rossa–Partizan, Flamengo–Fluminense, Benfica–Porto, con gli id ESPN verificati), `caricamento/extra.py`.
- Scarica calendario e statistiche **solo delle partite delle squadre in elenco** (tutte le loro partite di campionato, per lo storico dei giocatori), dopo Serie A e Liga, dentro il tetto di tempo dello storico.
- [ ] Test con fonte finta: solo le squadre in elenco vengono scaricate; ordine dopo Serie A e Liga.

### Task B2: Soglia e pagina

- `media_cartellini_scontri(s, squadra_a, squadra_b, prima_di) -> (n, media)` sugli scontri diretti delle ultime 3 stagioni (gialli + rossi di tutte e due le squadre, panchina compresa); sfida mostrata se `n ≥ 3` e `media ≥ SOGLIA_ALTO_RISCHIO = 6,5` (modificabile in Impostazioni).
- App: sezione "Partite ad alto rischio" nella pagina Partite (separata dai campionati), stessa pagina Dettaglio; fattore arbitro neutro (nessun arbitro), indicato.
- [ ] Test: sfida con media 7,2 su 4 scontri → mostrata; media 5,8 → no; 2 scontri → no.

### Task B3: Documentazione

- README e confronto fonti: subentranti, sfide ad alto rischio, limiti (niente arbitro, dati ESPN meno ricchi in alcuni campionati).
