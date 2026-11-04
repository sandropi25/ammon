# Piattaforma ammonizioni – Specifica di design

Data: 2026-11-04
Stato: in revisione

## 1. Obiettivo

Una web app che, per ogni partita di Serie A (e poi di Champions League), mostri i giocatori con la
probabilità più alta di essere ammoniti. Ogni giocatore ha una motivazione leggibile e, se viene
inserita la quota, il confronto tra probabilità stimata e probabilità implicita nella quota.

Sostituisce il processo manuale attuale: probabili formazioni → arbitro e contesto → formazioni
ufficiali un'ora prima → statistiche giocatore per giocatore su Sofascore/Diretta → confronto con i
tipster su Telegram.

**Successo:**
- La classifica di una partita è pronta in pochi secondi invece che in 20-30 minuti.
- Dopo alcune settimane il registro delle giocate mostra se il modello, l'utente e ciascun tipster
  indovinano più spesso di quanto implicano le quote.

**Fuori perimetro (per ora):** marcatori e assist, altri mercati, app iPhone. Il design però li
prevede (vedi §8).

## 2. Architettura

```
API-Football ──►  Raccolta dati  ──►  Database  ──►  Motore di punteggio  ──►  Interfacce
Liste manuali ──►                                                              ├ Web app Streamlit
(derby, campi)                                                                 ├ Bot Telegram (fase 2)
                                                                               └ App iPhone (fase 4)
```

Ogni blocco ha un solo compito e un'interfaccia chiara:

| Blocco | Compito | Dipende da |
|---|---|---|
| `fonti/` | Scarica i dati da una fonte esterna e li converte nel formato interno. Una classe per fonte (`ApiFootball`, in futuro `Sportmonks`) | Solo la rete |
| `db/` | Salva partite, giocatori, presenze, eventi, arbitri, liste manuali e giocate (SQLite in locale, Postgres online) | Nessuno |
| `motore/` | Riceve una partita e restituisce la classifica dei candidati con probabilità e motivazioni. Non sa dove verrà mostrata | `db/` |
| `app/` | Interfaccia Streamlit | `motore/`, `db/` |
| `scheduler/` | Aggiornamento notturno e controllo delle formazioni prima della partita | `fonti/`, `db/` |

Cambiare fonte dati vuol dire scrivere una nuova classe in `fonti/`. Il resto non cambia.

## 3. Dati

### 3.1 Fonte
- **API-Football**, piano gratuito: 100 richieste al giorno, 10 al minuto.
- Il piano gratuito limita le stagioni disponibili. **Primo controllo da fare con una chiave reale:**
  quali stagioni di Serie A e Champions sono accessibili. Se la stagione in corso non lo è, si passa
  al piano Pro (19 $/mese) prima di scrivere il resto.
- Per ogni giocatore un link alla sua pagina Sofascore, per il controllo visivo. Sofascore non viene
  letto in automatico.

### 3.2 Cosa si salva
- **Partite:** data, competizione, squadre, arbitro, risultato, stato formazioni (probabili/ufficiali).
- **Presenze per partita e giocatore:** squadra, ruolo e posizione, minuti, gialli, rossi, falli
  commessi e subiti, dribbling tentati e riusciti, tiri, gol, assist, voto.
- **Storico multi-stagione:** la stagione in corso più le **2 precedenti**, in tutte le competizioni
  coperte e con **qualunque squadra** il giocatore abbia giocato. Così un giocatore passato da un
  club all'altro porta con sé la sua storia.
- **Arbitri:** calcolati dallo storico: gialli a partita, falli fischiati a partita, gialli con le due
  squadre in campo.
- **Liste manuali:** derby e rivalità, campi caldi. Le compila l'utente nelle impostazioni.

### 3.3 Caricamento dello storico
Con 100 richieste al giorno lo storico si carica gradualmente: prima le partite delle squadre della
prossima giornata, poi il resto. Un contatore impedisce di superare il limite e dà sempre la
precedenza alle partite del giorno.

## 4. Modello di punteggio

Per ogni giocatore titolare:

**probabilità = base del giocatore × fattore duello × fattore arbitro × fattore contesto × fattore
storia personale × fattore situazione**

Il risultato viene poi limitato tra il 2% e il 70%.

### 4.1 Base del giocatore
- Gialli ogni 90 minuti, con media pesata: stagione in corso 60%, stagione scorsa 30%, quella
  prima 10%. Dentro la stagione in corso le **ultime 5 partite** pesano il doppio.
- Falli commessi ogni 90 minuti: se un giocatore fa molti falli ma ha pochi gialli, la base sale
  leggermente (candidato "in ritardo").
- Con pochi minuti giocati, la base viene avvicinata alla media del suo ruolo, per non fidarsi di
  numeri casuali.

### 4.2 Fattore duello
Per ogni giocatore si individua l'avversario diretto dalla posizione in campo (ad esempio terzino
destro contro esterno sinistro). L'utente può correggerlo.

L'avversario diretto alza il fattore se:
- subisce molti falli e tenta molti dribbling, il che indica velocità e tecnica;
- è **in forma**: gol, assist, tiri e voto nelle ultime 3-5 partite sopra la sua media. Un attaccante
  in forma va fermato più spesso.

### 4.3 Fattore arbitro
- Gialli a partita dell'arbitro rispetto alla media del campionato.
- Falli fischiati a partita, tenuti separati: c'è chi fischia molto ma ammonisce poco.
- Se l'arbitro ha meno di 5 partite registrate, il fattore resta vicino a 1.

### 4.4 Fattore contesto
- Derby o rivalità (lista manuale).
- Campo caldo (lista manuale).
- Posta in classifica: lotta per il titolo, per l'Europa o per la salvezza.
- Precedenti tra le due squadre con molti cartellini.

### 4.5 Fattore storia personale (nuovo)
Guarda gli scontri del giocatore contro **quella squadra** e in **quel tipo di partita**, su tutte le
stagioni salvate e con qualunque maglia:
- gialli presi contro l'avversario di oggi, anche in coppa;
- gialli presi nei derby o nelle partite della lista rivalità;
- gialli presi contro lo stesso avversario diretto, se c'è già stato quel duello.

Esempio: ammonito negli ultimi 2 derby → il fattore sale, e la motivazione lo dice.
Con pochi precedenti (meno di 2 partite) il fattore resta vicino a 1, per non dare troppo peso a un
singolo episodio.

### 4.6 Fattore situazione
- **Diffidato** (a un giallo dalla squalifica): fattore sotto 1, perché tende a giocare con prudenza.
- Probabile sostituzione presto (minuti medi bassi): fattore sotto 1.

### 4.7 Uscita
Per ogni giocatore:
- la probabilità;
- le 2-3 motivazioni principali in una riga, ad esempio *"Ammonito negli ultimi 2 derby · marca X,
  2 gol nelle ultime 2 · arbitro da 5,4 gialli"*;
- un indicatore di affidabilità del dato (alto, medio, "dati insufficienti");
- se c'è la quota: la probabilità implicita (1/quota) e il **valore** (probabilità stimata meno
  probabilità implicita), evidenziato quando è positivo.

### 4.8 Versioni del modello
- **V1:** pesi fissi e trasparenti, modificabili dalle impostazioni.
- **V2 (fase 3):** pesi ricalcolati sullo storico (regressione logistica) e probabilità calibrate.

## 5. Schermate

1. **Partite:** prossime partite con arbitro, indicatore "partita calda" e stato delle formazioni.
2. **Dettaglio partita:**
   - in alto il contesto: arbitro, derby o rivalità, posta in gioco, precedenti;
   - la classifica dei candidati con probabilità, motivazioni e affidabilità;
   - per ogni candidato il duello con le statistiche affiancate, la sua storia contro quell'avversario
     e il link Sofascore;
   - campi per la quota e per i giocatori consigliati dai tipster, che compaiono accanto alla
     classifica;
   - se le formazioni sono passate da probabili a ufficiali, un riepilogo dei cambi.
3. **Giocate:** registro con data, partita, giocatore, fonte (io, modello, nome tipster), quota,
   puntata, esito. Mostra percentuale di successo, rendimento e profitto o perdita per fonte.
4. **Impostazioni:** derby e rivalità, campi caldi, pesi del modello V1, chiave API.

Le probabili formazioni, nella fase gratuita, sono l'ultimo undici schierato e si correggono con
pochi tocchi.

## 6. Flusso e casi difficili

- **Ogni notte:** calendario, risultati, eventi, statistiche delle partite giocate, esito automatico
  delle giocate registrate (giallo sì o no).
- **Da 75 minuti prima del calcio d'inizio:** controllo delle formazioni ufficiali ogni 10 minuti
  finché non escono, poi ricalcolo della classifica.
- **Limite richieste raggiunto:** l'app funziona con i dati già salvati e mostra quando sono stati
  aggiornati l'ultima volta.
- **Errore della fonte:** riprova con attesa crescente; nessun crash dell'interfaccia.
- **Giocatore o arbitro con pochi dati:** resta in classifica con l'avviso "dati insufficienti".
- **Rosso o giallo annullato al VAR:** conta solo il cartellino finale registrato dalla fonte.
- **Giocata su giocatore non entrato in campo:** esito "rimborsata", esclusa dalle statistiche.

## 7. Verifica

- Test automatici per ogni fattore del motore con dati di prova (ad esempio: due gialli nei derby
  precedenti → fattore storia sopra 1).
- Test sul limite delle richieste e sulla conversione dei dati della fonte.
- **Prova sulla scorsa stagione:** il modello calcola la classifica di ogni partita usando solo i dati
  disponibili prima di quella partita. Si misura quante volte almeno uno dei primi 3 candidati è stato
  ammonito, e lo si confronta con una scelta semplice (il giocatore con più gialli in stagione).

## 8. Estensioni previste

- **Marcatori e assist:** il motore è organizzato per "mercato". Ogni mercato ha i suoi fattori e
  riusa gli stessi dati. La forma recente (gol e assist nelle ultime partite) e il duello sono già
  calcolati e servono anche lì.
- **Champions League:** stessa logica, con meno partite per stagione: lo storico pesa di più sulle
  partite di campionato del giocatore.
- **Bot Telegram:** riepilogo il giorno prima, classifica aggiornata all'uscita delle formazioni,
  esiti dopo la partita.
- **App iPhone:** nuova interfaccia sullo stesso motore.
- **Sportmonks:** nuova classe in `fonti/` per probabili formazioni automatiche e dati arbitri.

## 9. Fasi

1. Web app Serie A: dati, motore V1, dettaglio partita, registro giocate, prova sulla scorsa stagione.
2. Champions League e bot Telegram.
3. Modello V2 calibrato.
4. Marcatori e assist; app iPhone.

## 10. Tecnologie

- Python 3.12, `httpx`, SQLAlchemy, Streamlit, `pytest`.
- Database: SQLite durante lo sviluppo; online un Postgres gratuito gestito (Supabase).
- Interfaccia online: Streamlit Community Cloud (gratuito), protetta da password.
- Aggiornamenti automatici: GitHub Actions programmate (notte e finestra pre-partita), perché
  Streamlit Cloud non esegue processi pianificati.
