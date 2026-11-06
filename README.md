# Ammonizioni Serie A e Liga

App per prevedere quali giocatori hanno più probabilità di essere ammoniti nelle prossime partite di Serie A e di Liga (la Serie A è il campionato principale e ha sempre la precedenza).
Scarica da ESPN (gratuita, senza chiave) calendario, formazioni e statistiche dei giocatori e da football-data.org (gratuita, con chiave) gli arbitri dei due campionati (Coppa Italia, Copa del Rey,
Champions, Europa League e Conference League hanno le partite ma non gli arbitri), le salva in un database e calcola per ogni partita una classifica di
probabilità di ammonizione, con quote e valore atteso per le giocate. L'interfaccia è un'app Streamlit in italiano.

Medie di campionato, posta in classifica e diffide (con le soglie di ciascun campionato) sono calcolate sul campionato della partita: aggiungere la Liga non cambia i risultati della Serie A. Nelle pagine **Partite** e **Giocate** il selettore del campionato (Serie A / Liga / Tutti) parte da Serie A; in **Impostazioni** derby e campi caldi offrono le squadre di entrambi i campionati, con il campionato fra parentesi.

Tre job programmati tengono i dati aggiornati:

- `python -m ammonizioni.scheduler.orchestratore`: parte ogni ora (minuto 05) ma decide da solo (ora italiana, nessuna richiesta se non serve): **aggiornamento della giornata** 6-7 ore prima della prima partita del giorno (per una prima partita alle 15:00, tra le 08:00 e le 09:00): calendario, statistiche delle partite giocate, arbitri, probabili formazioni, biografie e storico (col suo tetto di tempo); **chiusura** delle partite finite da almeno 2 ore e non ancora chiuse (statistiche ed esiti delle giocate); nei giorni senza partite non fa nulla. Se un cron salta, l'aggiornamento della giornata si recupera fino a 3 ore prima della prima partita. Lo stato ("giornata aggiornata", "partite chiuse") è in Impostazione, quindi nulla gira due volte.
- `python -m ammonizioni.scheduler.notte`: una volta a settimana (lunedì 03:00 UTC), come rete di sicurezza, aggiorna calendario, risultati e statistiche (prima la Serie A, poi la Liga) e fa avanzare il caricamento dello storico (stagioni 2026, 2025, 2024).
- `python -m ammonizioni.scheduler.pre_partita`: ogni 10 minuti, da 75 minuti prima del calcio d'inizio, controlla se sono uscite le formazioni ufficiali (Serie A e Liga). Fuori finestra esce subito senza fare richieste.

## Fonti dati

- **ESPN (predefinita)**: API pubblica, gratuita e senza chiave, ma non ufficiale: la struttura può cambiare senza preavviso. Il programma fa al massimo 30 richieste al minuto. Fornisce partite, formazioni e statistiche dei giocatori (non ha dribbling, voto e arbitro: il modello usa solo i dati presenti).
- **football-data.org** (chiave gratuita, 10 richieste al minuto): fornisce gli arbitri di Serie A e Liga, collegati alle partite ESPN per data e squadre. Senza chiave tutto funziona ma le partite restano senza arbitro (fattore arbitro neutro) e nel log compare l'avviso sulla chiave mancante.
- **API-Football** (opzionale; per la stagione corrente serve il piano Pro, 19 $ al mese): resta nel codice come fonte alternativa, con dribbling, voto e arbitro. Si usa con `FONTE_DATI=api_football` (e `API_FOOTBALL_KEY`, anche dalla pagina Impostazioni); con `FONTE_DATI` assente, vuota o `espn` si usa ESPN e `API_FOOTBALL_KEY` non serve. **Cambiare fonte richiede un database nuovo e vuoto**: gli id di ESPN e di API-Football si sovrappongono (squadre e giocatori diversi con lo stesso id) e i dati si mescolerebbero. La fonte è memorizzata nel database al primo uso (impostazione `fonte_dati_db`) e i job escono con errore se `FONTE_DATI` non coincide; un database con partite ma senza il valore (creato prima di questo controllo) si considera ESPN.

### Chiave di football-data.org

1. Registrati su <https://www.football-data.org/client/register> (piano gratuito) e copia il token ricevuto per email.
2. In locale, una volta sola, in PowerShell: `setx FOOTBALL_DATA_KEY "il-tuo-token"` (vale dalle nuove finestre del terminale).
3. Su GitHub: **Settings > Secrets and variables > Actions > New repository secret**, nome `FOOTBALL_DATA_KEY`.
4. Su Streamlit Community Cloud: aggiungi `FOOTBALL_DATA_KEY = "il-tuo-token"` ai **Secrets** dell'app (livello principale, come `DATABASE_URL`).
5. In alternativa, dalla pagina **Impostazioni** dell'app (campo "Chiave football-data.org", mostrata mascherata): la chiave viene salvata nel database e la usano anche i job. Se è impostata la variabile d'ambiente `FOOTBALL_DATA_KEY`, ha la precedenza su quella salvata.

### Controllo di salute di ESPN

Poiché ESPN non è ufficiale, `python scripts/controlla_espn.py` scarica una partita di Serie A nota (1 richiesta) e verifica i campi che il programma usa (roster, titolari, id e posizione dei giocatori, falli e cartellini, minuti degli eventi). Esce con 0 se è tutto a posto, con 1 e l'elenco dei campi mancanti se la struttura è cambiata. Lo stesso controllo gira all'inizio del job notturno: se fallisce, nel log compare "La struttura dei dati ESPN è cambiata: ..." e l'aggiornamento "notte" risulta incompleto (`completo=False`), ma il resto del lavoro viene fatto.

### Primo caricamento dello storico

Con ESPN il primo caricamento reale dello storico della Serie A (tre stagioni, con Coppa Italia e coppe europee) è di 2.203 richieste a 30 al minuto, cioè circa 74 minuti; con la Liga e la Copa del Rey si arriva a circa 3.300 richieste (comunque entro circa 3 notti a 40 minuti per notte). Il job notturno ferma lo storico dopo `STORICO_MAX_MINUTI` minuti (variabile d'ambiente o variabile del repository GitHub; default 40) e il giorno dopo riprende da dove era arrivato: **il primo caricamento può richiedere 3 notti**. La Serie A viene sempre caricata per prima: i calendari della Serie A prima di quelli della Liga e, per le statistiche, prima le partite di Serie A (e le coppe delle squadre di Serie A), poi quelle di Liga. Poi la notte dura pochi minuti. Insieme allo storico vengono collegati gli arbitri di ogni stagione (una richiesta a football-data.org per campionato e stagione, la Serie A per prima).

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

### Da verificare con la chiave (solo con `FONTE_DATI=api_football`): griglia delle partite passate

Con ESPN non c'è nulla da verificare: la prova del modello aveva la griglia in 380 partite su 380. Quanto segue vale solo per API-Football. Le statistiche dei giocatori arrivano da `/fixtures/players`, che non contiene la posizione in campo (la "griglia",
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

Predefinito: Serie A. Per la Liga aggiungi `--campionato 140`: il modello usa le medie, la classifica e le diffide della Liga.

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

1. Crea su GitHub un repository e fai il push del progetto (i workflow sono in `.github/workflows/`). Con Serie A e Liga il pre-partita supera i 2000 minuti mensili del piano Free (vedi "Minuti di GitHub Actions" più sotto): **si consiglia un repository pubblico** (minuti illimitati; i segreti restano protetti, il codice è visibile); se lo tieni privato, metti in conto minuti a pagamento.
2. Nel repository: **Settings > Secrets and variables > Actions > New repository secret**. Crea due segreti:
   - `FOOTBALL_DATA_KEY`: il token di football-data.org (arbitri);
   - `DATABASE_URL`: la stringa di Supabase del punto 1.

   `API_FOOTBALL_KEY` (segreto) e `FONTE_DATI` (variabile, in **Variables**) servono solo per tornare ad API-Football: con `FONTE_DATI` vuota o assente si usa ESPN. `STORICO_MAX_MINUTI` (variabile, facoltativa) cambia il tetto di 40 minuti dello storico.
3. Lancia il caricamento a mano: scheda **Actions > Caricamento notturno > Run workflow**. Nei log del passo `python -m ammonizioni.scheduler.notte` controlla le righe `Notte: ... richieste, ... partite aggiornate, completo=...` e `Storico: ...`: devono comparire il numero di richieste usate e `completo=True` (o `False` se lo storico si è fermato per il tempo massimo `STORICO_MAX_MINUTI`, se il controllo di salute di ESPN ha trovato la struttura cambiata, se football-data ha dato errore o se è stato raggiunto il limite giornaliero, caso normale mentre lo storico si carica).
4. Da quel momento: `orchestratore.yml` parte ogni ora (cron `5 * * * *`) e decide se aggiornare la giornata, chiudere le partite finite o non fare nulla; `notte.yml` parte solo il lunedì alle 03:00 UTC (rete di sicurezza); `pre_partita.yml` parte ogni 10 minuti ma solo dalle 10:00 alle 20:50 UTC (cron `*/10 10-20 * * *`). Entrambi si possono lanciare anche a mano (`workflow_dispatch`) e hanno un gruppo di concorrenza che impedisce due esecuzioni sovrapposte.

Nota: GitHub può ritardare l'avvio dei cron di qualche minuto (e a volte saltarne qualcuno nei momenti di carico). Per il controllo delle formazioni, a intervalli di 10 minuti, non è un problema. I cron dei repository senza attività per 60 giorni vengono disattivati da GitHub: basta riattivarli dalla scheda Actions.

#### Minuti di GitHub Actions e orari del cron

Con Serie A e Liga il pre-partita gira dalle 10:00 alle 20:50 UTC (la Liga arriva fino alle 21:00 spagnole, cioè le 19:00 o le 20:00 UTC): 11 ore x 6 esecuzioni = 66 al giorno, circa **1980 minuti al mese** (ogni esecuzione conta almeno 1 minuto), a cui si aggiungono l'orchestratore (24 esecuzioni al giorno, circa 720 al mese: ogni esecuzione conta almeno 1 minuto anche quando non fa nulla, quindi **circa 750-900 minuti al mese**, più gli aggiornamenti della giornata e lo storico finché non è completo: fino a 40 minuti per le prime giornate) e il job settimanale di sicurezza (circa 4-5 esecuzioni al mese). In totale si va **oltre i 2000 minuti mensili** del piano GitHub Free per i repository privati. Le strade sono due, e la scelta è tua:

- **rendere pubblico il repository** (minuti illimitati; i segreti restano protetti, il codice è visibile a tutti): è la strada consigliata;
- **accettare i minuti a pagamento** oltre la quota di 2000 (o restare privati e ridurre le ore del cron, rinunciando a coprire alcuni calci d'inizio).

Se non fai nessuna delle due, negli ultimi giorni del mese i job si fermano.

Un repository privato sul piano GitHub Free ha 2000 minuti di Actions al mese e ogni esecuzione conta almeno 1 minuto. Un cron ogni 10 minuti tutto il giorno farebbe circa 4320 esecuzioni al mese ed esaurirebbe la quota in circa due settimane, dopo di che i job si fermerebbero. Per questo `pre_partita.yml` gira solo nelle ore in cui un calcio d'inizio può cadere nella finestra di 75 minuti.

Attenzione al primo caricamento dello storico: finché non è completo, il job notturno dura fino a 40 minuti (`STORICO_MAX_MINUTI`) per le prime 3 notti, poi torna a pochi minuti (`Storico: ... completo=True`). Per questo periodo, se resti su un repository privato, puoi ridurre temporaneamente le ore del cron pre-partita in `.github/workflows/pre_partita.yml` (per esempio `*/10 15-20 * * *` nei giorni senza anticipi): ogni ora in meno risparmia circa 180 minuti al mese ma lascia scoperti i calci d'inizio in quella fascia. Con un repository pubblico il problema non esiste.

- Copertura: calci d'inizio della Serie A dalle 12:30 alle 20:45 ora italiana e della Liga fino alle 21:00 ora spagnola, sia con ora solare (CET) sia con ora legale (CEST).
- Se una partita è mai fuori da questo intervallo (per esempio un anticipo alle 12:00 o un orario tardivo), allarga le ore del cron in `.github/workflows/pre_partita.yml`, tenendo d'occhio la quota (ogni ora in più costa circa 180 minuti al mese).
- Un repository pubblico ha minuti illimitati, quindi il cron potrebbe girare tutto il giorno. I segreti restano protetti, ma il codice sarebbe visibile a tutti.

### 3. Streamlit Community Cloud

1. Vai su <https://share.streamlit.io>, accedi con GitHub e scegli **Create app** sul repository (pubblico, come consigliato per i minuti di GitHub Actions, oppure privato: concedi l'accesso quando richiesto).
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
