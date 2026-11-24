# Marcatori (beta) — progetto breve

## Perché
L'utente vuole pronosticare anche chi segna ("come i cartellini ma con precisione"), per poi
combinare marcatore + ammonito. Prima in beta, su un link separato, per seguirne l'andamento senza
toccare l'app dei cartellini.

## Obiettivi / non obiettivi
- Obiettivo: per ogni partita dei 4 campionati (Serie A, Liga, Premier, Ligue 1) la classifica dei
  giocatori con la probabilità di segnare almeno un gol, verificata fuori campione.
- Obiettivo: cernita salvata prima del via e resoconto a fine giornata (chi ha segnato), automatici.
- Non obiettivi: combinate nell'app, coppe, scommesse "primo marcatore", modifiche all'app attuale.
- Anti-obiettivo: probabilità non calibrate presentate come affidabili.

## Approcci considerati
1. **Gol attesi di squadra × quota del giocatore × minuti** (scelto): forza attacco/difesa per
   squadra con vantaggio casa e decadimento nel tempo; quota del giocatore da gol e tiri della sua
   squadra (con restringimento verso la media del ruolo); probabilità = 1 − exp(−λ·quota·minuti/90).
   Calibrazione Platt sul 2024, verifica sul 2025.
2. Solo "gol del giocatore per 90 minuti": è il riferimento semplice da battere, non il modello.
3. Quote 1X2 per i gol di squadra: le abbiamo solo per ~40 partite recenti, inutilizzabile ora.

## Come
- Modulo `ammonizioni.marcatori` (modello + backtest), funzioni pure sulle righe del database,
  ogni partita vede solo i dati precedenti al calcio d'inizio.
- Coefficienti in Impostazione `marcatori_coefficienti`; cernita in `marcatori_cernita_<partita>`;
  resoconto in `marcatori_resoconto_<comp>_<stagione>_<giornata>`, precisione in
  `marcatori_precisione`. Agganciati agli stessi job (pre-partita, orchestratore).
- App separata `app_marcatori/Marcatori.py` (stesso repo, stessi secrets e password, sola
  lettura): partite dei prossimi giorni → classifica marcatori con probabilità; una pagina con la
  precisione della beta.
- Deploy: l'utente crea la nuova app su share.streamlit.io (main file `app_marcatori/Marcatori.py`).

## Lasciato al costruttore
Pesi del decadimento, forza del restringimento, soglie: scelti con la verifica 2024→2025.
