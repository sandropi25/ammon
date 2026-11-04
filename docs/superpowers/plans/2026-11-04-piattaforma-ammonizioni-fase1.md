# Piattaforma ammonizioni – Fase 1 (Serie A) – Piano di esecuzione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Web app Streamlit che per ogni partita di Serie A mostra la classifica dei giocatori più a rischio giallo, con motivazioni, affidabilità, valore rispetto alla quota, registro giocate e prova sulla scorsa stagione.

**Architecture:** Pacchetto Python `ammonizioni` a blocchi separati: `fonti/` (API-Football → dataclass interne), `db/` (SQLAlchemy), `caricamento/` + `scheduler/` (job notturno e pre-partita), `motore/` (funzioni pure su uno snapshot `DatiPartita` costruito dal DB con filtro `prima_di`, così la stessa logica serve la app e la prova storica), `giocate/`, `backtest/`, `app/` (Streamlit). Il motore è organizzato per "mercato" (`MercatoAmmonizioni`) per accogliere marcatori/assist in fase 4.

**Tech Stack:** Python 3.12, httpx, SQLAlchemy 2.x, Streamlit (con `streamlit.testing.v1.AppTest`), pytest, respx (mock httpx), SQLite in sviluppo / Postgres Supabase online, GitHub Actions.

**Spec:** `2026-11-04-piattaforma-ammonizioni-design.md`

## Global Constraints

- Python 3.12; dipendenze: `httpx`, `sqlalchemy>=2`, `streamlit`, `pytest`, `respx`, `psycopg[binary]` (solo online).
- API-Football piano gratuito: **100 richieste al giorno, 10 al minuto**. Base URL `https://v3.football.api-sports.io`, header `x-apisports-key`.
- Storico: **stagione in corso + 2 precedenti** (oggi: 2026, 2025, 2024 – API-Football indica la stagione con l'anno di inizio), tutte le competizioni coperte, qualunque squadra.
- Competizioni coperte per lo storico (id API-Football): Serie A `135`, Coppa Italia `137`, Champions `2`, Europa League `3`, Conference `848`. Classifica prodotta solo per Serie A in fase 1.
- Probabilità finale limitata tra **2% e 70%**.
- Pesi base: stagione corrente **60%**, scorsa **30%**, precedente **10%**; ultime **5** partite della stagione corrente pesano **il doppio**.
- Arbitro con **meno di 5 partite** → fattore vicino a 1. Storia personale con **meno di 2 precedenti** → fattore vicino a 1.
- Probabilità implicita = `1/quota`; valore = probabilità stimata − probabilità implicita.
- Formazioni ufficiali: controllo **da 75 minuti prima** del calcio d'inizio, **ogni 10 minuti** finché escono.
- Sofascore mai letto in automatico: solo link.
- Tutti gli orari salvati in UTC; mostrati in `Europe/Rome`.
- Testi dell'interfaccia e motivazioni in italiano, decimali con la virgola (`5,4`).

## Review Focus

1. **Nome arbitro scritto in modi diversi** (API-Football dà solo una stringa: "D. Doveri", "Daniele Doveri", "Doveri D.") → deve risultare un solo arbitro con lo storico unito. Test in Task 4.
2. **Giocatore senza minuti nello storico** (acquisto dall'estero, primavera) → resta in classifica con "dati insufficienti", nessuna divisione per zero. Test in Task 5 e Task 9.
3. **Quota inserita male** ("2,10" con la virgola, "1", "0", testo) → la virgola è accettata, quota ≤ 1 o non numerica rifiutata con messaggio, nessun crash. Test in Task 9.
4. **Limite richieste raggiunto a metà job** → i dati già scaricati restano salvati, il job termina senza eccezioni, l'app mostra "ultimo aggiornamento". Test in Task 4 e Task 12.
5. **Partita rinviata o formazioni mai pubblicate** → il controllo pre-partita smette dopo il calcio d'inizio e salta le partite con stato `PST`/`CANC`, senza consumare richieste. Test in Task 11.

---

## Struttura dei file

```
pyproject.toml
.env.example                          # API_FOOTBALL_KEY, DATABASE_URL
scripts/controlla_stagioni.py
src/ammonizioni/
  config.py                           # Impostazioni (env + DB), costanti competizioni
  db/modelli.py                       # tabelle SQLAlchemy
  db/sessione.py                      # engine, crea_tabelle, sessione()
  db/repo.py                          # upsert e query usate da caricamento/giocate/app
  fonti/tipi.py                       # dataclass interne (PartitaDati, PresenzaDati, FormazioneDati)
  fonti/base.py                       # Protocol Fonte
  fonti/limite.py                     # LimiteRichieste, Priorita
  fonti/api_football.py               # ApiFootball
  caricamento/arbitri.py              # normalizzazione nomi
  caricamento/notturno.py             # calendario, risultati, statistiche, esiti
  caricamento/storico.py              # caricamento graduale
  caricamento/formazioni.py           # probabili (ultimo XI) e ufficiali
  motore/tipi.py                      # DatiPartita, RigaPresenza, Fattore, Candidato, ...
  motore/pesi.py                      # Pesi (V1) + carica/salva
  motore/dati.py                      # carica_dati(sessione, partita_id, prima_di) -> DatiPartita
  motore/fattori/base.py
  motore/fattori/duello.py
  motore/fattori/arbitro.py
  motore/fattori/contesto.py
  motore/fattori/storia.py
  motore/fattori/situazione.py
  motore/classifica.py                # classifica(), affidabilità, motivazioni, quote
  motore/mercati.py                   # Protocol Mercato, MercatoAmmonizioni
  giocate/registro.py
  backtest/prova.py
  scheduler/notte.py                  # entrypoint python -m
  scheduler/pre_partita.py            # entrypoint python -m
app/
  Partite.py                          # pagina principale
  auth.py
  pages/1_Dettaglio_partita.py
  pages/2_Giocate.py
  pages/3_Impostazioni.py
.github/workflows/notte.yml
.github/workflows/pre_partita.yml
tests/  (specchio di src/, + tests/app/, tests/dati_prova/)
```

---

### Task 1: Progetto e verifica stagioni accessibili (cancello)

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `src/ammonizioni/__init__.py`, `src/ammonizioni/config.py`, `scripts/controlla_stagioni.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.COMPETIZIONI: dict[str, int]` (`{"serie_a": 135, "coppa_italia": 137, "champions": 2, "europa": 3, "conference": 848}`), `config.STAGIONE_CORRENTE = 2026`, `config.STAGIONI = (2026, 2025, 2024)`, `config.chiave_api(sessione=None) -> str | None` (prima env `API_FOOTBALL_KEY`, poi tabella impostazioni se `sessione` passata), `config.url_database() -> str` (env `DATABASE_URL`, default `sqlite:///ammonizioni.db`).

- [ ] **Step 1:** `git init`; `pyproject.toml` con pacchetto in `src/`, dipendenze dei Global Constraints, `[tool.pytest.ini_options] pythonpath=["src"]`. `.gitignore` con `.env`, `*.db`, `.venv/`.
- [ ] **Step 2: Test che fallisce**

```python
def test_chiave_da_env(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY", "abc")
    assert config.chiave_api() == "abc"

def test_url_database_default(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert config.url_database() == "sqlite:///ammonizioni.db"

def test_stagioni():
    assert config.STAGIONI == (2026, 2025, 2024)
```

- [ ] **Step 3:** `pytest tests/test_config.py -v` → FAIL.
- [ ] **Step 4:** Implementare `config.py` (la parte "da DB" di `chiave_api` arriva in Task 2; per ora accetta `sessione=None`).
- [ ] **Step 5:** `pytest tests/test_config.py -v` → PASS.
- [ ] **Step 6: Script `scripts/controlla_stagioni.py`.** Con `httpx` chiama `GET /leagues?id=135` e `GET /leagues?id=2`, stampa le stagioni con `coverage.fixtures.statistics_players` e `coverage.fixtures.lineups`; poi prova `GET /fixtures?league=135&season=2026&next=1` e stampa il campo `errors` della risposta (il piano gratuito rifiuta qui le stagioni non incluse). Consuma 3 richieste.
- [ ] **Step 7: CANCELLO – eseguire con la chiave reale dell'utente.**

Run: `python scripts/controlla_stagioni.py`
Expected: stagioni 2024, 2025, 2026 accessibili con statistiche giocatori e formazioni.
**Se la 2026 non è accessibile: fermarsi e chiedere all'utente di passare al piano Pro (19 $/mese) prima di proseguire** (spec §3.1). Annotare l'esito in `docs/superpowers/plans/esito-stagioni.md`.

- [ ] **Step 8: Commit** `chore: scaffold progetto e verifica stagioni API`

---

### Task 2: Database

**Files:**
- Create: `src/ammonizioni/db/modelli.py`, `db/sessione.py`, `db/repo.py`
- Test: `tests/db/test_modelli.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: `config.url_database()`
- Produces (tabelle, chiavi primarie = id API-Football dove esiste):
  - `Squadra(id, nome)`
  - `Giocatore(id, nome, ruolo: "G"|"D"|"M"|"F", sofascore_url: str | None)`
  - `Arbitro(id autoinc, nome_normalizzato unique, nome_visualizzato)`
  - `Partita(id, data_utc, competizione_id, stagione, giornata: int|None, casa_id, trasferta_id, arbitro_id|None, gol_casa|None, gol_trasferta|None, stato: str  # "NS","FT","PST","CANC",…, stato_formazioni: "probabili"|"ufficiali", statistiche_scaricate: bool)`
  - `Presenza(partita_id, giocatore_id, squadra_id, titolare: bool, ruolo, griglia: str|None, minuti, gialli, rossi, falli_commessi, falli_subiti, dribbling_tentati, dribbling_riusciti, tiri, gol, assist, voto: float|None)` PK (partita_id, giocatore_id)
  - `Formazione(partita_id, squadra_id, giocatore_id, griglia|None, tipo: "probabile"|"ufficiale")` – la probabile resta salvata per il riepilogo cambi
  - `ListaManuale(id, tipo: "derby"|"campo_caldo", squadra_a_id, squadra_b_id|None)` (campo caldo: solo `squadra_a_id`)
  - `DuelloManuale(partita_id, giocatore_id, avversario_id)`
  - `Segnalazione(id, partita_id, giocatore_id, fonte: str  # "io","modello", nome tipster, quota|None)`
  - `Giocata(id, data, partita_id, giocatore_id, fonte, quota, puntata, esito: "in_attesa"|"vinta"|"persa"|"rimborsata")`
  - `ContatoreRichieste(giorno: date PK, usate: int)`
  - `Impostazione(chiave PK, valore_json)`
  - `UltimoAggiornamento(job PK, quando_utc, completo: bool)`
- `sessione.crea_engine(url) -> Engine`, `sessione.crea_tabelle(engine)`, `sessione.apri(url=None) -> Session` (context manager)
- `repo.upsert(s, oggetto)` generico via `merge`, `repo.leggi_impostazione(s, chiave, default)`, `repo.scrivi_impostazione(s, chiave, valore)`, `repo.segna_aggiornamento(s, job, completo: bool)`, `repo.ultimo_aggiornamento(s, job) -> datetime|None`
- `conftest.py`: fixture `sessione` su SQLite in memoria con tabelle create.

- [ ] **Step 1: Test che fallisce** – `test_upsert_presenza_idempotente` (due upsert della stessa presenza → una riga, valori aggiornati); `test_impostazione_roundtrip` (`scrivi_impostazione(s,"pesi",{"a":1})` → `leggi_impostazione` restituisce `{"a":1}`); `test_ultimo_aggiornamento_none_se_mai_eseguito`.
- [ ] **Step 2:** `pytest tests/db -v` → FAIL.
- [ ] **Step 3:** Implementare modelli, sessione, repo. Completare `config.chiave_api(sessione)` leggendo `Impostazione("chiave_api")`.
- [ ] **Step 4:** `pytest tests -v` → PASS.
- [ ] **Step 5: Commit** `feat(db): modelli e repository`

---

### Task 3: Fonte API-Football con limite richieste e retry

**Files:**
- Create: `fonti/tipi.py`, `fonti/base.py`, `fonti/limite.py`, `fonti/api_football.py`
- Test: `tests/fonti/test_limite.py`, `tests/fonti/test_api_football.py`, `tests/dati_prova/api/*.json` (risposte reali ridotte, una per endpoint)

**Interfaces:**
- Consumes: `ContatoreRichieste`, `config.chiave_api`
- Produces:
  - `fonti.tipi`: `PartitaDati(id, data_utc, competizione_id, stagione, giornata, casa_id, casa_nome, trasferta_id, trasferta_nome, arbitro_nome|None, gol_casa, gol_trasferta, stato)`, `PresenzaDati(...)` con gli stessi campi di `Presenza` + `giocatore_nome`, `FormazioneDati(partita_id, squadra_id, titolari: list[tuple[giocatore_id, nome, ruolo, griglia|None]])`
  - `fonti.base.Fonte` (Protocol): `partite(competizione_id, stagione) -> list[PartitaDati]`, `partita(id) -> PartitaDati`, `statistiche(partita_id) -> list[PresenzaDati]`, `formazioni(partita_id) -> list[FormazioneDati]` (lista vuota se non ancora uscite)
  - `fonti.limite`: `class Priorita(Enum): OGGI, STORICO`; `class LimiteSuperato(Exception)`; `LimiteRichieste(sessione, max_giorno=100, max_minuto=10, riserva_oggi=30, orologio=time.monotonic, dormi=time.sleep, oggi=date.today)` con `prendi(priorita)` che solleva `LimiteSuperato` se il budget del giorno è esaurito (per `STORICO` il tetto è `max_giorno - riserva_oggi`) e altrimenti attende quanto basta per restare a 10/minuto, poi incrementa il contatore nel DB; `rimanenti(priorita) -> int`.
  - `fonti.api_football.ApiFootball(chiave, limite: LimiteRichieste, client: httpx.Client | None = None, priorita=Priorita.OGGI)` implementa `Fonte`. Endpoint: `/fixtures?league&season`, `/fixtures?id`, `/fixtures/players?fixture`, `/fixtures/lineups?fixture`. Mappe: `cards.yellow/red`, `fouls.committed/drawn`, `dribbles.attempts/success`, `shots.total`, `goals.total/assists`, `games.minutes/position/rating`, `games.substitute`; `grid` e `startXI` da lineups. Valori `null` → 0 (voto → `None`).
  - Retry: su `httpx.TransportError`, 429 e 5xx, 4 tentativi con attese 1, 2, 4, 8 s (funzione `dormi` iniettabile); poi `ErroreFonte`. Campo `errors` non vuoto nella risposta → `ErroreFonte` col messaggio.

- [ ] **Step 1: Test che falliscono (limite)**

```python
def test_storico_non_tocca_la_riserva(sessione):
    l = LimiteRichieste(sessione, max_giorno=100, riserva_oggi=30, dormi=lambda s: None)
    for _ in range(70): l.prendi(Priorita.STORICO)
    with pytest.raises(LimiteSuperato): l.prendi(Priorita.STORICO)
    l.prendi(Priorita.OGGI)  # la riserva è ancora disponibile

def test_undicesima_richiesta_nel_minuto_attende(sessione):
    attese = []
    t = FakeClock()
    l = LimiteRichieste(sessione, orologio=t, dormi=lambda s: (attese.append(s), t.avanza(s)))
    for _ in range(11): l.prendi(Priorita.OGGI)
    assert attese and attese[0] > 0

def test_contatore_persistito_e_azzerato_il_giorno_dopo(sessione): ...
```

- [ ] **Step 2: Test che falliscono (fonte)** con `respx`: `test_statistiche_conversione` (dalla fixture JSON: un giocatore con `cards.yellow=1`, `fouls.committed=3` → `PresenzaDati.gialli==1`, `falli_commessi==3`; `rating "7.1"` → `7.1`; `null` → 0); `test_formazioni_vuote_se_non_uscite`; `test_retry_su_500_poi_successo` (2×500 poi 200 → risultato, attese `[1, 2]`); `test_errors_nella_risposta_solleva_errore_fonte`; `test_partita_rinviata_stato_PST`.
- [ ] **Step 3:** `pytest tests/fonti -v` → FAIL.
- [ ] **Step 4:** Implementare `tipi`, `base`, `limite`, `api_football`.
- [ ] **Step 5:** `pytest tests/fonti -v` → PASS.
- [ ] **Step 6: Commit** `feat(fonti): client API-Football con limite e retry`

---

### Task 4: Caricamento notturno, storico graduale, arbitri

**Files:**
- Create: `caricamento/arbitri.py`, `caricamento/notturno.py`, `caricamento/storico.py`
- Test: `tests/caricamento/test_arbitri.py`, `test_notturno.py`, `test_storico.py` (con una `FonteFinta` in `tests/conftest.py` che implementa `Fonte` in memoria e conta le chiamate)

**Interfaces:**
- Consumes: `Fonte`, `LimiteSuperato`, `repo.*`
- Produces:
  - `arbitri.normalizza(nome: str) -> str`: minuscolo, senza accenti, toglie iniziali puntate e virgole, tiene il **cognome** (ultima parola lunga > 2 caratteri; per "Doveri D." la prima). `arbitri.trova_o_crea(s, nome) -> Arbitro | None` (`None` se nome vuoto).
  - `notturno.aggiorna_calendario(s, fonte, stagione=STAGIONE_CORRENTE)`: partite Serie A della stagione (1 richiesta).
  - `notturno.scarica_statistiche_giocate(s, fonte)`: per le partite `FT` con `statistiche_scaricate=False`, dalla più recente.
  - `notturno.esegui(s, fonte) -> RiepilogoJob(richieste_usate, partite_aggiornate, completo: bool)`: calendario → statistiche → `giocate.registro.aggiorna_esiti(s)` (Task 10; fino ad allora chiamata protetta da import lazy) → `segna_aggiornamento("notte", completo)`. Su `LimiteSuperato` committa quanto fatto e restituisce `completo=False`. Su `ErroreFonte` per una partita la salta e prosegue.
  - `storico.coda_storico(s, oggi) -> list[tuple[competizione_id, stagione]]` e `storico.prossime_da_scaricare(s, oggi) -> list[int]` (id partite): prima le partite passate (tutte le competizioni coperte, 3 stagioni) di squadre che giocano nei prossimi 7 giorni, poi le altre, dalla più recente.
  - `storico.avanza(s, fonte_storico) -> RiepilogoJob`: usa una `ApiFootball` con `priorita=Priorita.STORICO`; prima scarica gli elenchi partite mancanti per (competizione, stagione) (una richiesta ciascuno, segnati in `Impostazione("calendari_scaricati")`), poi le statistiche nell'ordine sopra, fino a `LimiteSuperato`.

- [ ] **Step 1: Test che falliscono**

```python
@pytest.mark.parametrize("nome", ["D. Doveri", "Daniele Doveri", "Doveri D.", "DOVERI, Daniele"])
def test_normalizza_arbitro(nome):
    assert normalizza(nome) == "doveri"

def test_stesso_arbitro_una_riga(sessione):
    a = trova_o_crea(sessione, "D. Doveri"); b = trova_o_crea(sessione, "Daniele Doveri")
    assert a.id == b.id

def test_limite_a_meta_job_salva_il_parziale(sessione):
    fonte = FonteFinta(partite_ft=5, limite_dopo=3)   # la 4ª chiamata solleva LimiteSuperato
    r = notturno.esegui(sessione, fonte)
    assert r.completo is False
    assert conta_presenze_scaricate(sessione) == 2   # calendario + 2 partite
    assert repo.ultimo_aggiornamento(sessione, "notte") is not None

def test_storico_prima_le_squadre_della_prossima_giornata(sessione): ...
def test_partita_con_errore_saltata_le_altre_scaricate(sessione): ...
```

- [ ] **Step 2:** `pytest tests/caricamento -v` → FAIL.
- [ ] **Step 3:** Implementare i tre moduli.
- [ ] **Step 4:** `pytest tests/caricamento -v` → PASS.
- [ ] **Step 5: Commit** `feat(caricamento): job notturno e storico graduale`

---

### Task 5: Motore – tipi, pesi V1, base del giocatore

**Files:**
- Create: `motore/tipi.py`, `motore/pesi.py`, `motore/fattori/base.py`
- Test: `tests/motore/test_base.py`, `tests/motore/test_pesi.py`, `tests/motore/costruttori.py` (helper `riga(**kw) -> RigaPresenza`, `medie_standard() -> MedieCampionato`)

**Interfaces:**
- Produces (`motore/tipi.py`, tutte `@dataclass(frozen=True)`):
  - `RigaPresenza(partita_id, data, stagione, competizione_id, squadra_id, avversario_id, minuti, gialli, rossi, falli_commessi, falli_subiti, dribbling_tentati, dribbling_riusciti, tiri, gol, assist, voto, titolare, rivalita: bool)`
  - `MedieRuolo(gialli90, falli90, falli_subiti90, dribbling90, ga90, voto)`; `MedieCampionato(gialli_partita, falli_partita, per_ruolo: dict[str, MedieRuolo])`
  - `StatArbitro(nome, partite, gialli_medi, falli_medi, gialli_medi_con: dict[squadra_id, tuple[float, int]])`
  - `ContestoInfo(rivalita: bool, campo_caldo: bool, posta: dict[squadra_id, str|None]  # "titolo"/"Europa"/"salvezza", precedenti_n: int, precedenti_gialli_medi: float|None)`
  - `Titolare(giocatore_id, nome, squadra_id, ruolo, griglia|None, sofascore_url|None)`
  - `DatiPartita(partita_id, data, stagione, casa_id, trasferta_id, nomi_squadre: dict[int,str], titolari: list[Titolare], storico: dict[giocatore_id, list[RigaPresenza]], arbitro: StatArbitro|None, medie: MedieCampionato, contesto: ContestoInfo, duelli_manuali: dict[int,int])`
  - `Fattore(nome: str, valore: float, motivazione: str|None, n_dati: int)`
  - `Candidato(giocatore_id, nome, squadra_id, ruolo, probabilita, motivazioni: list[str], affidabilita: Literal["alto","medio","dati insufficienti"], avversario_diretto_id|None, fattori: list[Fattore], quota|None, prob_implicita|None, valore|None)`
- `motore/pesi.py`: `Pesi` dataclass con questi default (V1, tutti modificabili dalle impostazioni):
  `pesi_stagioni=(0.6,0.3,0.1)`, `moltiplicatore_ultime5=2.0`, `minuti_prior=900`, `soglia_ritardo_falli=1.3`, `bonus_ritardo=1.10`, `coeff_falli_subiti=0.25`, `coeff_dribbling=0.15`, `coeff_forma=0.10`, `coeff_gialli_arbitro=1.0`, `coeff_falli_arbitro=0.2`, `soglia_partite_arbitro=5`, `rivalita=1.20`, `campo_caldo=1.08`, `posta=1.07`, `coeff_precedenti=0.3`, `coeff_storia=0.3`, `soglia_precedenti=2`, `diffidato=0.85`, `sostituzione=0.90`, `minuti_sostituzione=60`, `soglie_diffida=(4,9,13,16,19)` (**da verificare sul regolamento Serie A in corso**), `attenuazione_pochi_dati=0.2`, `limiti_fattore=(0.7,1.6)`, `limiti_probabilita=(0.02,0.70)`.
  `carica_pesi(s) -> Pesi`, `salva_pesi(s, pesi)` (JSON in `Impostazione("pesi")`; chiavi mancanti → default).
  Helper condivisi: `attenua(valore, n, soglia, pesi) -> float` = `1 + (valore-1) * (pesi.attenuazione_pochi_dati if n < soglia else 1)`; `limita(valore, pesi) -> float` su `limiti_fattore`.
- `motore/fattori/base.py`: `base_giocatore(storico: list[RigaPresenza], ruolo: str, medie: MedieCampionato, stagione: int, pesi: Pesi) -> Fattore` – `valore` è una **probabilità**:
  1. gialli/90 per stagione (stagione, −1, −2), dentro la corrente le ultime 5 righe contano `moltiplicatore_ultime5` volte (sia gialli sia minuti); media pesata con `pesi_stagioni` rinormalizzati sulle stagioni con minuti > 0;
  2. restringimento al ruolo: `tasso = (tasso*minuti_tot + medie.per_ruolo[ruolo].gialli90*minuti_prior) / (minuti_tot + minuti_prior)`;
  3. "in ritardo": se falli/90 ≥ `soglia_ritardo_falli` × media ruolo e gialli/90 < media ruolo → `× bonus_ritardo`, motivazione "Tanti falli, pochi gialli: in ritardo";
  4. `p = 1 - exp(-tasso * minuti_attesi/90)` con `minuti_attesi` = media minuti delle ultime 5 da titolare (90 se nessuna).
  `n_dati` = minuti totali.

- [ ] **Step 1: Test che falliscono**

```python
def test_giocatore_senza_storico_usa_media_ruolo():
    f = base_giocatore([], "D", medie_standard(), 2026, Pesi())
    assert f.n_dati == 0
    assert f.valore == pytest.approx(1 - math.exp(-medie_standard().per_ruolo["D"].gialli90))

def test_ultime_5_pesano_doppio():
    # stesse partite e gialli, ma i gialli nelle ultime 5 vs nelle prime 5 → base più alta nel primo caso
def test_stagione_corrente_pesa_piu_della_precedente(): ...
def test_in_ritardo_alza_la_base_e_lo_dice():
    f = base_giocatore(storico_tanti_falli_zero_gialli, "M", medie_standard(), 2026, Pesi())
    assert "in ritardo" in f.motivazione
def test_pesi_roundtrip_e_chiavi_mancanti(sessione): ...
def test_attenua_sotto_soglia():
    assert attenua(1.5, n=1, soglia=2, pesi=Pesi()) == pytest.approx(1.1)
```

- [ ] **Step 2:** `pytest tests/motore -v` → FAIL.
- [ ] **Step 3:** Implementare `tipi.py`, `pesi.py`, `fattori/base.py`.
- [ ] **Step 4:** `pytest tests/motore -v` → PASS.
- [ ] **Step 5: Commit** `feat(motore): tipi, pesi V1, base giocatore`

---

### Task 6: Motore – avversario diretto e fattore duello

**Files:**
- Create: `motore/fattori/duello.py`
- Test: `tests/motore/test_duello.py`

**Interfaces:**
- Consumes: `Titolare`, `RigaPresenza`, `MedieCampionato`, `Pesi`, `attenua`, `limita`
- Produces:
  - `avversario_diretto(giocatore: Titolare, avversari: list[Titolare], manuale: int|None) -> int|None`: se `manuale` → quello. Altrimenti dalla `griglia` "riga:colonna" di API-Football: corsia normalizzata in [0,1] nella propria riga; linea opposta D↔F, M↔M, G → nessuno; sceglie l'avversario della linea opposta con corsia più vicina a `1 - corsia` (specchio: terzino destro ↔ esterno sinistro). Se la linea opposta è vuota usa M. Senza griglia → `None`.
  - `fattore_duello(avversario: Titolare|None, storico_avv: list[RigaPresenza], medie, pesi) -> Fattore`:
    `1 + coeff_falli_subiti*(fs90/media_ruolo - 1) + coeff_dribbling*(drib90/media_ruolo - 1) + coeff_forma*forma`,
    con `forma` = media di `(ga90 ultime 5 / ga90 stagione − 1)` e `(voto ultime 5 / voto stagione − 1)`, ciascuno limitato a [−1, 1]; poi `attenua(…, n=minuti/90, soglia=5)` e `limita`. Nessun avversario → `Fattore("duello", 1.0, None, 0)`.
    Motivazione se valore ≥ 1.05: `"marca {nome}, {g} gol nelle ultime {k}"` se ha segnato nelle ultime 3, altrimenti `"marca {nome}, {x} falli subiti a partita"` (una cifra decimale, virgola).

- [ ] **Step 1: Test che falliscono** – `test_terzino_destro_contro_esterno_sinistro` (formazioni 4-3-3 con griglie reali API-Football), `test_duello_manuale_ha_precedenza`, `test_senza_griglia_nessun_avversario`, `test_dribblatore_in_forma_alza_il_fattore` (> 1 e motivazione contiene "marca" e "gol nelle ultime"), `test_avversario_nella_media_fattore_circa_1`, `test_fattore_limitato_a_1_6`.
- [ ] **Step 2:** `pytest tests/motore/test_duello.py -v` → FAIL.
- [ ] **Step 3:** Implementare.
- [ ] **Step 4:** → PASS.
- [ ] **Step 5: Commit** `feat(motore): avversario diretto e fattore duello`

---

### Task 7: Motore – fattore arbitro e fattore contesto

**Files:**
- Create: `motore/fattori/arbitro.py`, `motore/fattori/contesto.py`
- Test: `tests/motore/test_arbitro.py`, `tests/motore/test_contesto.py`

**Interfaces:**
- Produces:
  - `fattore_arbitro(arbitro: StatArbitro|None, squadra_id: int, medie, pesi) -> Fattore`: `1 + coeff_gialli_arbitro*(gialli_medi/medie.gialli_partita - 1) + coeff_falli_arbitro*(falli_medi/medie.falli_partita - 1)`; se l'arbitro ha ≥ 2 partite con `squadra_id`, moltiplica per `attenua(gialli_con/gialli_medi, n, 2)`. Poi `attenua(n=partite, soglia=soglia_partite_arbitro)` e `limita`. Motivazione: `"arbitro da {gialli_medi:,1f} gialli"` (virgola decimale, es. "arbitro da 5,4 gialli") se valore ≥ 1.05; se fischia molto ma ammonisce poco (falli > media e gialli < media) `"arbitro: tanti falli, pochi gialli"`. `None` → 1.0.
  - `fattore_contesto(ctx: ContestoInfo, squadra_id, medie, pesi) -> Fattore`: prodotto di `rivalita`, `campo_caldo`, `posta` (se `ctx.posta[squadra_id]`), e `attenua(1 + coeff_precedenti*(precedenti_gialli_medi/medie.gialli_partita - 1), precedenti_n, 3)`; `limita`. Motivazioni: "Derby/rivalità", "Campo caldo", "In lotta per {posta}", "Precedenti nervosi".
  - `contesto.posta_in_classifica(partite_giocate: list[tuple[casa, trasferta, gc, gt]], squadra_id) -> str|None`: classifica a punti calcolata dalle partite (3/1/0); posta solo se la squadra ha giocato ≥ 19 partite; "titolo" se entro 3 punti dal 1° posto, "Europa" entro 3 punti dal 4° o dal 6°, "salvezza" entro 3 punti dal 17° (dall'alto o dal basso). Il primo che si applica in quest'ordine.

- [ ] **Step 1: Test che falliscono** – `test_arbitro_severo_alza_e_motiva` (gialli_medi 5.4, media 4.2, 20 partite → > 1, motivazione `"arbitro da 5,4 gialli"`), `test_arbitro_con_4_partite_resta_vicino_a_1` (|valore−1| ≤ 0.2·|valore pieno−1|), `test_arbitro_assente_fattore_1`, `test_derby_alza_contesto`, `test_posta_salvezza_dopo_giornata_19`, `test_nessuna_posta_prima_di_giornata_19`.
- [ ] **Step 2:** → FAIL. **Step 3:** Implementare. **Step 4:** → PASS.
- [ ] **Step 5: Commit** `feat(motore): fattori arbitro e contesto`

---

### Task 8: Motore – storia personale e situazione

**Files:**
- Create: `motore/fattori/storia.py`, `motore/fattori/situazione.py`
- Test: `tests/motore/test_storia.py`, `tests/motore/test_situazione.py`

**Interfaces:**
- Produces:
  - `fattore_storia(storico: list[RigaPresenza], avversario_squadra_id: int, oggi_rivalita: bool, storico_avv_diretto: list[RigaPresenza], tasso_base90: float, pesi) -> Fattore`. Tre sottoinsiemi dello storico del giocatore (tutte le stagioni salvate, qualunque maglia, qualunque competizione):
    a) righe con `avversario_id == avversario_squadra_id`;
    b) se `oggi_rivalita`: righe con `rivalita == True`;
    c) righe la cui `partita_id` compare in `storico_avv_diretto` con `squadra_id` diverso (il duello c'è già stato).
    Per ogni sottoinsieme con ≥ 1 partita: `r = gialli90_sottoinsieme / tasso_base90`; `f = attenua(1 + coeff_storia*(r - 1), n_partite, soglia_precedenti)`. Valore = prodotto, `limita`. Motivazione del sottoinsieme più forte con ≥ 2 partite: `"Ammonito negli ultimi {k} derby"` (b, k = gialli consecutivi più recenti), `"{g} gialli in {n} partite contro {squadra}"` (a), `"già ammonito contro {nome}"` (c).
  - `fattore_situazione(storico, stagione: int, pesi) -> Fattore`: diffidato se i gialli in Serie A (`competizione_id == 135`) nella stagione corrente sono in `soglie_diffida` → `× diffidato`, motivazione "Diffidato"; minuti medi nelle ultime 5 da titolare < `minuti_sostituzione` → `× sostituzione`, motivazione "Spesso sostituito presto".
  - `rivalita` su `RigaPresenza` è calcolata in `motore/dati.py` (Task 9) dalla `ListaManuale`.

- [ ] **Step 1: Test che falliscono**

```python
def test_due_gialli_negli_ultimi_due_derby_alza_storia():
    f = fattore_storia(storico_2_derby_2_gialli, 99, True, [], tasso_base90=0.2, pesi=Pesi())
    assert f.valore > 1
    assert f.motivazione == "Ammonito negli ultimi 2 derby"

def test_un_solo_precedente_resta_vicino_a_1(): ...
def test_storia_con_altra_maglia_conta(): ...   # righe con squadra_id diverso dall'attuale contro lo stesso avversario
def test_diffidato_abbassa():
    f = fattore_situazione(storico_4_gialli_serie_a_2026, 2026, Pesi())
    assert f.valore == pytest.approx(0.85) and f.motivazione == "Diffidato"
def test_gialli_in_coppa_non_contano_per_diffida(): ...
```

- [ ] **Step 2:** → FAIL. **Step 3:** Implementare. **Step 4:** → PASS.
- [ ] **Step 5: Commit** `feat(motore): storia personale e situazione`

---

### Task 9: Motore – caricamento dati, classifica, quote, mercato

**Files:**
- Create: `motore/dati.py`, `motore/classifica.py`, `motore/mercati.py`
- Test: `tests/motore/test_classifica.py`, `tests/motore/test_dati.py`

**Interfaces:**
- Consumes: tutti i fattori (Task 5–8), modelli DB, `Formazione`
- Produces:
  - `dati.carica_dati(s, partita_id, prima_di: datetime|None = None, titolari: list[Titolare]|None = None) -> DatiPartita`. **Ogni query filtra `Partita.data_utc < prima_di`** (default: calcio d'inizio della partita), così la prova storica (Task 14) non vede il futuro. Titolari: se `titolari` passato, quelli; altrimenti `Formazione` ufficiale, altrimenti probabile, altrimenti ultimo XI (Task 11). Medie di campionato e per ruolo dalle presenze Serie A delle 3 stagioni prima di `prima_di`. Statistiche arbitro dalle sue partite con statistiche scaricate.
  - `classifica.converti_quota(testo: str) -> float`: accetta "2,10" e "2.10"; solleva `ValueError("Quota non valida: deve essere un numero maggiore di 1")` se non numerica o ≤ 1.
  - `classifica.affidabilita(base: Fattore, arbitro: StatArbitro|None, pesi) -> str`: "dati insufficienti" se minuti < 270; "alto" se minuti ≥ 900 e arbitro con ≥ `soglia_partite_arbitro` partite; altrimenti "medio".
  - `classifica.classifica(dati: DatiPartita, pesi: Pesi, quote: dict[int, float] | None = None) -> list[Candidato]`: per ogni titolare non portiere (`ruolo != "G"`): `p = base × duello × arbitro × contesto × storia × situazione`, limitata a `limiti_probabilita`; motivazioni = fino a 3 testi dei fattori con `motivazione` non nulla, ordinati per `|log(valore)|` decrescente (base usa il suo testo solo se "in ritardo"), uniti dall'app con `" · "`; con quota: `prob_implicita = 1/quota`, `valore = p - prob_implicita`. Ordine per `probabilita` decrescente.
  - `mercati.Mercato` (Protocol): `nome: str`, `classifica(s, partita_id, quote=None, prima_di=None, titolari=None) -> list[Candidato]`. `mercati.MercatoAmmonizioni` lo implementa con `carica_dati` + `carica_pesi` + `classifica`.

- [ ] **Step 1: Test che falliscono**

```python
def test_probabilita_limitata_tra_2_e_70(): ...           # fattori estremi → 0.70; base minima → 0.02
def test_portieri_esclusi(): ...
def test_motivazioni_al_massimo_3_le_piu_forti(): ...
def test_valore_con_quota():
    c = classifica(dati, Pesi(), quote={10: 4.0})
    cand = next(x for x in c if x.giocatore_id == 10)
    assert cand.prob_implicita == pytest.approx(0.25)
    assert cand.valore == pytest.approx(cand.probabilita - 0.25)
@pytest.mark.parametrize("t,atteso", [("2,10", 2.10), ("2.10", 2.10)])
def test_converti_quota_ok(t, atteso): ...
@pytest.mark.parametrize("t", ["1", "0", "-3", "abc", ""])
def test_converti_quota_rifiutata(t):
    with pytest.raises(ValueError): converti_quota(t)
def test_giocatore_senza_storico_in_classifica_con_dati_insufficienti(): ...
def test_carica_dati_non_vede_partite_successive(sessione): ...   # presenza con data > prima_di esclusa
def test_mercato_ammonizioni_end_to_end(sessione): ...            # DB popolato con dati di prova → lista ordinata
```

- [ ] **Step 2:** → FAIL. **Step 3:** Implementare. **Step 4:** `pytest tests/motore -v` → PASS.
- [ ] **Step 5: Commit** `feat(motore): classifica, quote e mercato ammonizioni`

---

### Task 10: Registro giocate ed esiti automatici

**Files:**
- Create: `giocate/registro.py`
- Test: `tests/giocate/test_registro.py`

**Interfaces:**
- Produces:
  - `aggiungi_giocata(s, partita_id, giocatore_id, fonte: str, quota: float, puntata: float, data: date) -> Giocata`
  - `aggiorna_esiti(s) -> int`: per giocate `in_attesa` su partite `FT` con statistiche scaricate: nessuna presenza o `minuti == 0` → "rimborsata"; `gialli ≥ 1` → "vinta"; altrimenti "persa" (rosso diretto senza giallo = persa; conta solo il cartellino finale registrato dalla fonte). Partita `CANC` → "rimborsata".
  - `statistiche_per_fonte(s) -> list[StatFonte]` con `StatFonte(fonte, giocate, vinte, perse, percentuale_successo, profitto, rendimento, prob_implicita_media)`; le rimborsate escluse da tutto; `profitto = Σ(vinte: puntata*(quota-1)) − Σ(perse: puntata)`; `rendimento = profitto / Σ puntate`; `prob_implicita_media` = media di `1/quota` (per confrontare il successo con quanto implicano le quote, spec §1).

- [ ] **Step 1: Test che falliscono** – `test_giallo_vinta`, `test_non_entrato_rimborsata`, `test_rimborsate_escluse_dalle_statistiche`, `test_profitto_e_rendimento` (2 giocate da 10 €, quota 3,00 vinta e quota 2,00 persa → profitto 10, rendimento 0,5, successo 50%, prob implicita media 0,4167), `test_partita_non_giocata_resta_in_attesa`.
- [ ] **Step 2:** → FAIL. **Step 3:** Implementare; rimuovere l'import lazy in `notturno.esegui`. **Step 4:** `pytest tests -v` → PASS.
- [ ] **Step 5: Commit** `feat(giocate): registro ed esiti automatici`

---

### Task 11: Formazioni probabili e controllo pre-partita

**Files:**
- Create: `caricamento/formazioni.py`, `scheduler/pre_partita.py`, `scheduler/notte.py`
- Test: `tests/caricamento/test_formazioni.py`, `tests/scheduler/test_pre_partita.py`

**Interfaces:**
- Produces:
  - `formazioni.ultimo_xi(s, squadra_id, prima_di) -> list[Titolare]`: titolari dell'ultima partita (qualsiasi competizione) della squadra prima di `prima_di`.
  - `formazioni.salva_probabili(s, partita_id, titolari_per_squadra: dict[int, list[int]])`: scrive `Formazione(tipo="probabile")` (usata anche dalle correzioni manuali nell'app).
  - `formazioni.riepilogo_cambi(s, partita_id) -> dict[squadra_id, tuple[list[entrati], list[usciti]]]` probabile vs ufficiale.
  - `pre_partita.partite_da_controllare(s, adesso_utc) -> list[Partita]`: Serie A con `stato_formazioni == "probabili"`, `stato` non in (`PST`, `CANC`) e `data_utc − 75 min ≤ adesso < data_utc`. Nessuna richiesta API se la lista è vuota.
  - `pre_partita.esegui(s, fonte, adesso_utc) -> int`: per ciascuna, se mancano le probabili le salva da `ultimo_xi`; poi `fonte.formazioni(id)`; se non vuote salva `tipo="ufficiale"` e imposta `stato_formazioni="ufficiali"`. La classifica si ricalcola alla prossima apertura della pagina (il motore è istantaneo).
  - `python -m ammonizioni.scheduler.pre_partita` e `python -m ammonizioni.scheduler.notte` (notte = `notturno.esegui` + `storico.avanza` con il budget rimasto). Entrambi: `main() -> int` exit code 0 anche con limite raggiunto.

- [ ] **Step 1: Test che falliscono** – `test_finestra_75_minuti` (a −76 min no, a −75 sì, a +1 min no), `test_partita_rinviata_saltata_senza_richieste` (FonteFinta conta 0 chiamate), `test_ufficiali_salvate_e_stato_aggiornato`, `test_formazioni_non_uscite_resta_probabili`, `test_riepilogo_cambi`, `test_ultimo_xi_anche_da_coppa`.
- [ ] **Step 2:** → FAIL. **Step 3:** Implementare. **Step 4:** → PASS.
- [ ] **Step 5: Commit** `feat(scheduler): formazioni probabili e controllo pre-partita`

---

### Task 12: App – Partite e Dettaglio partita

**Files:**
- Create: `app/Partite.py`, `app/auth.py`, `app/pages/1_Dettaglio_partita.py`, `app/componenti.py`
- Test: `tests/app/test_partite.py`, `tests/app/test_dettaglio.py` (con `AppTest.from_file`, DB SQLite temporaneo via `DATABASE_URL`)

**Interfaces:**
- Consumes: `MercatoAmmonizioni`, `riepilogo_cambi`, `salva_probabili`, `converti_quota`, `repo.ultimo_aggiornamento`, `Segnalazione`, `DuelloManuale`
- Produces:
  - `auth.richiedi_password() -> bool`: se `st.secrets` ha `password`, chiede la password e blocca con `st.stop()` finché non è giusta; senza segreto (sviluppo locale) passa.
  - `componenti.data_italiana(dt_utc) -> str` (Europe/Rome, "sab 08/11 20:45"), `componenti.percentuale(p) -> "34%"`, `componenti.link_sofascore(giocatore) -> str` (il campo `sofascore_url` se presente, altrimenti ricerca `https://www.google.com/search?q=sofascore+<nome>`).
  - **Partite:** prossime partite Serie A (7 giorni) con data, squadre, arbitro, badge "partita calda" (rivalità o campo caldo o arbitro con fattore ≥ 1.1), stato formazioni; in testa "Dati aggiornati: {data}" da `ultimo_aggiornamento("notte")` e avviso se l'ultimo job è `completo=False`. Clic → dettaglio (`st.query_params["partita"]`).
  - **Dettaglio:** contesto (arbitro con gialli/falli medi, rivalità, posta, precedenti); se ci sono ufficiali, riepilogo cambi; tabella candidati (giocatore, squadra, probabilità, motivazioni con " · ", affidabilità, quota, implicita, valore evidenziato in verde se > 0, colonna "Tipster" con i nomi che lo consigliano); per ogni candidato un expander con duello affiancato (statistiche per 90 dei due), storia contro l'avversario, link Sofascore, selectbox per correggere l'avversario diretto (scrive `DuelloManuale`); form "Quota" per giocatore (errore leggibile da `converti_quota`) e form "Segnalazione tipster" (nome tipster + giocatore) che salvano `Segnalazione`; con formazioni probabili, multiselect per correggere gli 11 di ciascuna squadra (`salva_probabili`); pulsante "Registra giocata" che apre il form di Task 13.

- [ ] **Step 1: Test che falliscono** – `test_partite_mostra_prossime_e_ultimo_aggiornamento`, `test_avviso_dati_parziali_se_job_incompleto`, `test_dettaglio_mostra_classifica_ordinata`, `test_quota_con_virgola_accettata_e_valore_mostrato`, `test_quota_non_valida_mostra_errore_senza_eccezioni` (`at.exception` vuoto), `test_password_richiesta_se_configurata`.
- [ ] **Step 2:** `pytest tests/app -v` → FAIL. **Step 3:** Implementare. **Step 4:** → PASS.
- [ ] **Step 5: Verifica manuale:** `streamlit run app/Partite.py` con il DB popolato dai job reali; aprire una partita della prossima giornata e controllare che le motivazioni siano leggibili.
- [ ] **Step 6: Commit** `feat(app): pagine Partite e Dettaglio`

---

### Task 13: App – Giocate e Impostazioni

**Files:**
- Create: `app/pages/2_Giocate.py`, `app/pages/3_Impostazioni.py`
- Test: `tests/app/test_giocate.py`, `tests/app/test_impostazioni.py`

**Interfaces:**
- Consumes: `aggiungi_giocata`, `statistiche_per_fonte`, `Pesi`, `carica_pesi`, `salva_pesi`, `ListaManuale`, `repo.scrivi_impostazione`
- Produces:
  - **Giocate:** form (data, partita, giocatore, fonte = "io" / "modello" / nome tipster libero, quota con `converti_quota`, puntata > 0); tabella registro con esito; tabella per fonte da `statistiche_per_fonte` (successo %, prob. implicita media %, profitto €, rendimento %).
  - **Impostazioni:** liste derby/rivalità (coppie di squadre Serie A) e campi caldi (squadra), con aggiungi/rimuovi; un `number_input` per ogni campo di `Pesi` con pulsante "Ripristina valori predefiniti"; campo password per la chiave API (salvata in `Impostazione("chiave_api")`, mostrata solo come "••••1234").

- [ ] **Step 1: Test che falliscono** – `test_registra_giocata_e_compare_nel_registro`, `test_puntata_zero_rifiutata`, `test_statistiche_per_fonte_mostrate`, `test_aggiungi_derby_persistito`, `test_modifica_peso_persistita_e_ripristino`, `test_chiave_api_mascherata`.
- [ ] **Step 2:** → FAIL. **Step 3:** Implementare. **Step 4:** → PASS.
- [ ] **Step 5: Commit** `feat(app): registro giocate e impostazioni`

---

### Task 14: Prova sulla scorsa stagione

**Files:**
- Create: `backtest/prova.py`, `scripts/prova_stagione.py`
- Test: `tests/backtest/test_prova.py`

**Interfaces:**
- Consumes: `MercatoAmmonizioni.classifica(s, partita_id, prima_di=…, titolari=…)`
- Produces:
  - `prova_stagione(s, stagione: int, k: int = 3) -> RisultatoProva(partite: int, successi_modello: int, successi_base: int, tasso_modello: float, tasso_base: float)`. Per ogni partita Serie A `FT` della stagione con statistiche: titolari = presenze con `titolare=True` (formazione reale), `prima_di` = calcio d'inizio; successo modello se almeno uno dei primi `k` candidati ha `gialli ≥ 1` in quella partita; scelta semplice = i `k` titolari con più gialli in Serie A nella stessa stagione prima della partita (pari merito: più minuti).
  - `scripts/prova_stagione.py --stagione 2025` stampa il risultato in tabella.

- [ ] **Step 1: Test che falliscono** – `test_successo_se_uno_dei_primi_3_ammonito`, `test_nessun_dato_futuro` (un giocatore con molti gialli **dopo** la partita non deve salire in classifica), `test_scelta_semplice_piu_gialli_in_stagione`.
- [ ] **Step 2:** → FAIL. **Step 3:** Implementare. **Step 4:** → PASS.
- [ ] **Step 5: Esecuzione reale** (richiede lo storico 2024–2025 caricato dal Task 4):

Run: `python scripts/prova_stagione.py --stagione 2025`
Expected: tabella con ~380 partite e i due tassi. Riportare i numeri all'utente; se il modello non batte la scelta semplice, segnalarlo prima della messa online (i pesi si correggono dalle impostazioni).

- [ ] **Step 6: Commit** `feat(backtest): prova sulla scorsa stagione`

---

### Task 15: Messa online

**Files:**
- Create: `.github/workflows/notte.yml`, `.github/workflows/pre_partita.yml`, `.streamlit/secrets.toml.example`, `requirements.txt` (per Streamlit Cloud), `README.md` (istruzioni d'uso e messa online)
- Test: `tests/test_postgres.py` (marcato `@pytest.mark.postgres`, saltato se `DATABASE_URL` non è Postgres)

**Interfaces:**
- `notte.yml`: `schedule: cron "0 3 * * *"` (03:00 UTC) + `workflow_dispatch`; Python 3.12, `pip install .`, `python -m ammonizioni.scheduler.notte` con secrets `API_FOOTBALL_KEY`, `DATABASE_URL`.
- `pre_partita.yml`: `cron "*/10 * * * *"`; `python -m ammonizioni.scheduler.pre_partita` (esce subito senza richieste fuori finestra). Nota nel README: GitHub può ritardare i cron di qualche minuto.
- Streamlit Community Cloud: entrypoint `app/Partite.py`, segreti `password`, `DATABASE_URL`, `API_FOOTBALL_KEY`.

- [ ] **Step 1:** Creare il progetto Supabase (azione dell'utente: account e password li inserisce lui); impostare `DATABASE_URL` localmente.
- [ ] **Step 2:** `pytest -m postgres -v` → crea le tabelle su Postgres e ripete `test_upsert_presenza_idempotente` e `test_mercato_ammonizioni_end_to_end`. Expected: PASS.
- [ ] **Step 3:** Push su GitHub (repository privato dell'utente), segreti delle Actions impostati dall'utente; lanciare `notte` a mano con `workflow_dispatch` e controllare nei log `completo` e richieste usate.
- [ ] **Step 4:** Deploy su Streamlit Cloud; aprire l'URL, verificare la richiesta della password, la pagina Partite con la data di aggiornamento e una classifica.
- [ ] **Step 5: Commit** `chore: workflow programmati e messa online`

---

## Ordine e dipendenze

Task 1 → 2 → 3 → 4. Il motore (5 → 6, 7, 8 → 9) dipende solo da 2 ed è testato con dati di prova, quindi si può sviluppare mentre lo storico si carica (≈ 2 settimane a 70 richieste/giorno per 3 stagioni di partite). 10 dopo 4; 11 dopo 4 e 9; 12–13 dopo 9–11; 14 dopo 9 e a storico caricato; 15 per ultimo.
