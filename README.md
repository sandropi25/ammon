# Ammonizioni Serie A

App per prevedere quali giocatori hanno più probabilità di essere ammoniti nelle prossime partite di Serie A.
Scarica da API-Football calendario, arbitri, formazioni e statistiche dei giocatori (Serie A, Coppa Italia,
Champions, Europa League, Conference), le salva in un database e calcola per ogni partita una classifica di
probabilità di ammonizione, con quote e valore atteso per le giocate. L'interfaccia è un'app Streamlit in italiano.

Due job programmati tengono i dati aggiornati:

- `python -m ammonizioni.scheduler.notte`: ogni notte aggiorna calendario, risultati e statistiche e fa avanzare il caricamento dello storico (stagioni 2026, 2025, 2024).
- `python -m ammonizioni.scheduler.pre_partita`: ogni 10 minuti, da 75 minuti prima del calcio d'inizio, controlla se sono uscite le formazioni ufficiali. Fuori finestra esce subito senza fare richieste.

Il piano gratuito di API-Football consente 100 richieste al giorno e 10 al minuto: il caricamento dello storico procede a piccoli passi (circa 2 settimane per le tre stagioni).

## Uso in locale

Serve Python 3.12 o successivo.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Copia `.env.example` in `.env` e imposta la chiave (il file `.env` non viene committato):

```
API_FOOTBALL_KEY=la-tua-chiave
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

### Verifica delle stagioni (ancora da fare)

Prima di caricare lo storico va verificato che la chiave API-Football dia accesso alla stagione 2026
(il piano gratuito potrebbe limitare le stagioni accessibili). Con la chiave impostata:

```powershell
python scripts/controlla_stagioni.py
```

Usa 3 richieste del piano giornaliero. Se la stagione 2026 non risulta accessibile serve il piano Pro (19 $ al mese).

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
   - `API_FOOTBALL_KEY`: la chiave API-Football;
   - `DATABASE_URL`: la stringa di Supabase del punto 1.
3. Lancia il caricamento a mano: scheda **Actions > Caricamento notturno > Run workflow**. Nei log del passo `python -m ammonizioni.scheduler.notte` controlla le righe `Notte: ... richieste, ... partite aggiornate, completo=...` e `Storico: ...`: devono comparire il numero di richieste usate e `completo=True` (o `False` se è stato raggiunto il limite giornaliero, caso normale mentre lo storico si carica).
4. Da quel momento: `notte.yml` parte ogni giorno alle 03:00 UTC; `pre_partita.yml` parte ogni 10 minuti ma solo dalle 10:00 alle 19:50 UTC (cron `*/10 10-19 * * *`). Entrambi si possono lanciare anche a mano (`workflow_dispatch`) e hanno un gruppo di concorrenza che impedisce due esecuzioni sovrapposte.

Nota: GitHub può ritardare l'avvio dei cron di qualche minuto (e a volte saltarne qualcuno nei momenti di carico). Per il controllo delle formazioni, a intervalli di 10 minuti, non è un problema. I cron dei repository senza attività per 60 giorni vengono disattivati da GitHub: basta riattivarli dalla scheda Actions.

#### Minuti di GitHub Actions e orari del cron

Un repository privato sul piano GitHub Free ha 2000 minuti di Actions al mese e ogni esecuzione conta almeno 1 minuto. Un cron ogni 10 minuti tutto il giorno farebbe circa 4320 esecuzioni al mese ed esaurirebbe la quota in circa due settimane, dopo di che i job si fermerebbero. Per questo `pre_partita.yml` gira solo nelle ore in cui un calcio d'inizio può cadere nella finestra di 75 minuti: 10-19 UTC, cioè 6 esecuzioni x 10 ore = 60 al giorno, circa 1800 al mese, più circa 30 della notte: circa 1830 minuti al mese, sotto il limite.

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
   API_FOOTBALL_KEY = "la-tua-chiave"
   ```

4. **Deploy**. Le dipendenze vengono installate da `requirements.txt` (una sola riga, `.[online]`: installa il pacchetto `ammonizioni` con le sue dipendenze e il driver Postgres).
5. Apri l'URL dell'app e verifica: richiesta della password, pagina **Partite** con la data dell'ultimo aggiornamento, e una classifica nel dettaglio di una partita.

Streamlit rende disponibili come variabili d'ambiente i segreti di primo livello di tipo testo o numero (`os.environ`), quindi `DATABASE_URL` e `API_FOOTBALL_KEY` arrivano al codice senza altre modifiche. Tienili al livello principale dei segreti, fuori da sezioni `[tabella]`. Per sviluppare in locale con gli stessi segreti basta copiare `.streamlit/secrets.toml.example` in `.streamlit/secrets.toml` (ignorato da git) e compilarlo.
