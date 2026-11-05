# Ammonizioni Serie A

App per prevedere quali giocatori hanno più probabilità di essere ammoniti nelle prossime partite di Serie A.
Scarica da ESPN (gratuita, senza chiave) calendario, formazioni e statistiche dei giocatori e da football-data.org (gratuita, con chiave) gli arbitri (Serie A, Coppa Italia,
Champions, Europa League, Conference), le salva in un database e calcola per ogni partita una classifica di
probabilità di ammonizione, con quote e valore atteso per le giocate. L'interfaccia è un'app Streamlit in italiano.

Due job programmati tengono i dati aggiornati:

- `python -m ammonizioni.scheduler.notte`: ogni notte aggiorna calendario, risultati e statistiche e fa avanzare il caricamento dello storico (stagioni 2026, 2025, 2024).
- `python -m ammonizioni.scheduler.pre_partita`: ogni 10 minuti, da 75 minuti prima del calcio d'inizio, controlla se sono uscite le formazioni ufficiali. Fuori finestra esce subito senza fare richieste.

## Fonti dati

- **ESPN (predefinita)**: API pubblica, gratuita e senza chiave, ma non ufficiale: la struttura può cambiare senza preavviso. Il programma fa al massimo 30 richieste al minuto. Fornisce partite, formazioni e statistiche dei giocatori (non ha dribbling, voto e arbitro: il modello usa solo i dati presenti).
- **football-data.org** (chiave gratuita, 10 richieste al minuto): fornisce gli arbitri della Serie A, collegati alle partite ESPN per data e squadre. Senza chiave tutto funziona ma le partite restano senza arbitro (fattore arbitro neutro) e nel log compare l'avviso sulla chiave mancante.
- **API-Football** (opzionale, a pagamento per le stagioni recenti): resta nel codice come fonte alternativa. Si attiva con `FONTE_DATI=api_football` (e `API_FOOTBALL_KEY`); con `FONTE_DATI` assente, vuota o `espn` si usa ESPN e `API_FOOTBALL_KEY` non serve.

### Chiave di football-data.org

1. Registrati su <https://www.football-data.org/client/register> (piano gratuito) e copia il token ricevuto per email.
2. In locale, una volta sola, in PowerShell: `setx FOOTBALL_DATA_KEY "il-tuo-token"` (vale dalle nuove finestre del terminale).
3. Su GitHub: **Settings > Secrets and variables > Actions > New repository secret**, nome `FOOTBALL_DATA_KEY`.
4. Su Streamlit Community Cloud: aggiungi `FOOTBALL_DATA_KEY = "il-tuo-token"` ai **Secrets** dell'app (livello principale, come `DATABASE_URL`).

### Controllo di salute di ESPN

Poiché ESPN non è ufficiale, `python scripts/controlla_espn.py` scarica una partita di Serie A nota (1 richiesta) e verifica i campi che il programma usa (roster, titolari, id e posizione dei giocatori, falli e cartellini, minuti degli eventi). Esce con 0 se è tutto a posto, con 1 e l'elenco dei campi mancanti se la struttura è cambiata. Lo stesso controllo gira all'inizio del job notturno: se fallisce, nel log compare "La struttura dei dati ESPN è cambiata: ..." e l'aggiornamento "notte" risulta incompleto (`completo=False`), ma il resto del lavoro viene fatto.

### Primo caricamento dello storico

Con ESPN lo storico delle tre stagioni richiede circa 1500 richieste a 30 al minuto, cioè circa 50 minuti. Il job notturno ferma lo storico dopo `STORICO_MAX_MINUTI` minuti (variabile d'ambiente o variabile del repository GitHub; default 40) e il giorno dopo riprende da dove era arrivato: **il primo caricamento può richiedere 2 notti**. Poi la notte dura pochi minuti. Insieme allo storico vengono collegati gli arbitri di ogni stagione (una richiesta a football-data.org per stagione).

Il vecchio limite di 100 richieste al giorno riguarda solo API-Football (piano gratuito: 100 richieste al giorno e 10 al minuto, storico in circa 2 settimane).

## Uso in locale

Serve Python 3.12 o successivo.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Copia `.env.example` in `.env` e imposta le chiavi (il file `.env` non viene committato). Con ESPN serve solo la chiave di football-data.org (per gli arbitri); `API_FOOTBALL_KEY` serve solo con `FONTE_DATI=api_football`:

```
FOOTBALL_DATA_KEY=il-tuo-token
DATABASE_URL=sqlite:///ammonizioni.db
```

Il codice legge le variabili d'ambiente, non il file `.env`: caricale nella shell, ad esempio in PowerShell

```powershell
Get-Content .env | ForEach-Object { $n, $v = $_ -split '=', 2; Set-Item "Env:$n" $v }
```

Poi:

```powershell
python -m ammonizioni.scheduler.notte        # caricamento notturno + avanzamento storico
python -m ammonizioni.scheduler.pre_partita  # controllo formazioni
streamlit run app/Partite.py                 # l'app
python -m pytest tests -v                    # test
```

Se `DATABASE_URL` manca, si usa il database SQLite `ammonizioni.db` nella cartella corrente. In locale l'app non chiede la password
se non esiste `.streamlit/secrets.toml`.

### Verifica delle stagioni di API-Football (solo con `FONTE_DATI=api_football`)

Prima di caricare lo storico va verificato che la chiave API-Football dia accesso alla stagione 2026
(il piano gratuito potrebbe limitare le stagioni accessibili). Con la chiave impostata:

```powershell
python scripts/controlla_stagioni.py
```

Usa 3 richieste del piano giornaliero. Se la stagione 2026 non risulta accessibile serve il piano Pro (19 $ al mese).

### Limite di richieste di API-Football (piano gratuito o Pro, solo con `FONTE_DATI=api_football`)

I job usano al massimo 100 richieste al giorno, di cui 30 riservate all'uso di oggi (calendario, statistiche
recenti, formazioni): lo storico ne usa al massimo 70. I due valori si cambiano con le variabili d'ambiente
`API_RICHIESTE_GIORNO` (default 100) e `API_RISERVA_OGGI` (default 30). Con il piano Pro (7500 richieste al
giorno) imposta per esempio `API_RICHIESTE_GIORNO=7500` e `API_RISERVA_OGGI=500`: lo storico si carica in un
paio di giorni. Su GitHub crea le due voci in **Settings > Secrets and variables > Actions > Variables** (non
sono segreti); se mancano valgono i default. Il ritmo resta di 10 richieste al minuto.

### Da verificare con la chiave: griglia delle partite passate

Le statistiche dei giocatori arrivano da `/fixtures/players`, che non contiene la posizione in campo (la "griglia",
es. `2:3`). La griglia serve a trovare l'avversario diretto (fattore duello). Oggi viene salvata solo per le partite
di cui il controllo pre-partita ha letto la formazione ufficiale (`/fixtures/lineups`); per le partite dello storico
resta vuota, quindi prima delle formazioni ufficiali e in tutta la prova del modello il duello vale 1 (neutro).

Con la chiave, verifica se `/fixtures?id=X` restituisce in una sola chiamata anche `lineups` (con `grid`) e
`players` (le statistiche). Se sì, conviene usarlo per lo storico al posto di `/fixtures/players`: stessa spesa di
richieste, ma con la griglia, così anche la prova del modello misura il fattore duello.

### Prova del modello (backtest)

Dopo aver caricato lo storico, per confrontare il modello con la scelta semplice (il giocatore con più gialli in stagione) sulla scorsa stagione:

```powershell
python scripts/prova_stagione.py --stagione 2025 --k 3
```

## Messa online

Architettura: database Postgres su Supabase, job programmati con GitHub Actions, app su Streamlit Community Cloud.
I passi 1, 3 e 4 richiedono i tuoi account e le tue password: vanno fatti da te.

### 1. Database su Supabase

1. Crea un account su <https://supabase.com> e un nuovo progetto (scegli una regione europea e una password per il database: conservala).
2. Nel progetto apri **Connect** e copia la stringa di connessione **Session pooler** (porta 5432), che funziona anche da GitHub Actions e Streamlit Cloud (la connessione diretta usa solo IPv6). Ha la forma `postgresql://postgres.xxxx:PASSWORD@aws-0-regione.pooler.supabase.com:5432/postgres`.
3. Sostituisci `PASSWORD` con la password del database. Questo è il valore di `DATABASE_URL`.
4. Non devi creare le tabelle a mano: l'app e i job le creano al primo avvio. Il prefisso `postgresql://` (o `postgres://`) viene convertito automaticamente nel formato per il driver psycopg 3 (`postgresql+psycopg://`).

Prova facoltativa dal tuo PC (installa prima il driver con `pip install -e ".[dev,online]"`). Il test usa uno schema temporaneo che elimina alla fine e non tocca i dati esistenti:

```powershell
$env:DATABASE_URL = "postgresql://..."
python -m pytest -m postgres -v
```

Senza un `DATABASE_URL` Postgres i test marcati `postgres` vengono saltati.

### 2. GitHub: repository e segreti delle Actions

1. Crea su GitHub un repository **privato** e fai il push del progetto (i workflow sono in `.github/workflows/`).
2. Nel repository: **Settings > Secrets and variables > Actions > New repository secret**. Crea due segreti:
   - `FOOTBALL_DATA_KEY`: il token di football-data.org (arbitri);
   - `DATABASE_URL`: la stringa di Supabase del punto 1.

   `API_FOOTBALL_KEY` (segreto) e `FONTE_DATI` (variabile, in **Variables**) servono solo per tornare ad API-Football: con `FONTE_DATI` vuota o assente si usa ESPN. `STORICO_MAX_MINUTI` (variabile, facoltativa) cambia il tetto di 40 minuti dello storico.
3. Lancia il caricamento a mano: scheda **Actions > Caricamento notturno > Run workflow**. Nei log del passo `python -m ammonizioni.scheduler.notte` controlla le righe `Notte: ... richieste, ... partite aggiornate, completo=...` e `Storico: ...`: devono comparire il numero di richieste usate e `completo=True` (o `False` se lo storico si è fermato per il tempo massimo `STORICO_MAX_MINUTI`, se il controllo di salute di ESPN ha trovato la struttura cambiata, se football-data ha dato errore o se è stato raggiunto il limite giornaliero, caso normale mentre lo storico si carica).
4. Da quel momento: `notte.yml` parte ogni giorno alle 03:00 UTC; `pre_partita.yml` parte ogni 10 minuti ma solo dalle 10:00 alle 19:50 UTC (cron `*/10 10-19 * * *`). Entrambi si possono lanciare anche a mano (`workflow_dispatch`) e hanno un gruppo di concorrenza che impedisce due esecuzioni sovrapposte.

Nota: GitHub può ritardare l'avvio dei cron di qualche minuto (e a volte saltarne qualcuno nei momenti di carico). Per il controllo delle formazioni, a intervalli di 10 minuti, non è un problema. I cron dei repository senza attività per 60 giorni vengono disattivati da GitHub: basta riattivarli dalla scheda Actions.

#### Minuti di GitHub Actions e orari del cron

Con ESPN il pre-partita pesa circa 1800 minuti al mese (cron `*/10 10-19 * * *`) e le prime due notti di storico fino a 40 minuti ciascuna (poi la notte dura pochi minuti): in totale si sta vicino ai 2000 minuti mensili del piano Free, quindi **si consiglia un repository pubblico** (minuti illimitati; i segreti restano protetti, il codice è visibile). La descrizione seguente, con i numeri del "primo mese", è calcolata sui limiti di API-Football.

Un repository privato sul piano GitHub Free ha 2000 minuti di Actions al mese e ogni esecuzione conta almeno 1 minuto. Un cron ogni 10 minuti tutto il giorno farebbe circa 4320 esecuzioni al mese ed esaurirebbe la quota in circa due settimane, dopo di che i job si fermerebbero. Per questo `pre_partita.yml` gira solo nelle ore in cui un calcio d'inizio può cadere nella finestra di 75 minuti: 10-19 UTC, cioè 6 esecuzioni x 10 ore = 60 al giorno, circa 1800 al mese, più circa 30 della notte: circa 1830 minuti al mese, sotto il limite.

Attenzione al primo mese: finché lo storico si carica, il job notturno usa tutte le 100 richieste al ritmo di 10
al minuto e dura circa 10-12 minuti, non 1. Sono circa 300-360 minuti al mese invece di 30: con il pre-partita si
arriva a circa 2100-2200 minuti, sopra i 2000 del piano Free, e negli ultimi giorni del mese i job si fermerebbero.
Quando lo storico è completo (`Storico: ... completo=True` per più notti) la notte torna a 1-2 minuti. Per il
periodo di caricamento hai due strade:

- rendere pubblico il repository (minuti illimitati, vedi sotto);
- oppure ridurre temporaneamente le ore del cron pre-partita in `.github/workflows/pre_partita.yml` (per esempio
  `*/10 15-19 * * *` nei giorni feriali senza anticipi), tenendo conto che ogni ora in meno risparmia circa
  180 minuti al mese ma lascia scoperti i calci d'inizio in quella fascia.

- Copertura: calci d'inizio dalle 12:30 alle 20:45 ora italiana, sia con ora solare (CET) sia con ora legale (CEST).
- Se una partita è mai fuori da questo intervallo (per esempio un anticipo alle 12:00 o un orario tardivo), allarga le ore del cron in `.github/workflows/pre_partita.yml`, tenendo d'occhio la quota (ogni ora in più costa circa 180 minuti al mese).
- Un repository pubblico ha minuti illimitati, quindi il cron potrebbe girare tutto il giorno. I segreti restano protetti, ma il codice sarebbe visibile a tutti.

### 3. Streamlit Community Cloud

1. Vai su <https://share.streamlit.io>, accedi con GitHub e scegli **Create app** sul repository privato (concedi l'accesso quando richiesto).
2. Branch: quello da pubblicare. **Main file path**: `app/Partite.py`.
3. In **Advanced settings** scegli Python 3.12 e incolla nei **Secrets** il contenuto di `.streamlit/secrets.toml.example` con i valori veri:

   ```toml
   password = "la-password-condivisa"
   DATABASE_URL = "postgresql://..."
   FOOTBALL_DATA_KEY = "il-tuo-token"
   ```

   (`API_FOOTBALL_KEY` solo se usi `FONTE_DATI = "api_football"`.)

4. **Deploy**. Le dipendenze vengono installate da `requirements.txt` (una sola riga, `.[online]`: installa il pacchetto `ammonizioni` con le sue dipendenze e il driver Postgres).
5. Apri l'URL dell'app e verifica: richiesta della password, pagina **Partite** con la data dell'ultimo aggiornamento, e una classifica nel dettaglio di una partita.

Streamlit rende disponibili come variabili d'ambiente i segreti di primo livello di tipo testo o numero (`os.environ`), quindi `DATABASE_URL` e `FOOTBALL_DATA_KEY` (e `API_FOOTBALL_KEY`, se usi API-Football) arrivano al codice senza altre modifiche. Tienili al livello principale dei segreti, fuori da sezioni `[tabella]`. Per sviluppare in locale con gli stessi segreti basta copiare `.streamlit/secrets.toml.example` in `.streamlit/secrets.toml` (ignorato da git) e compilarlo.
