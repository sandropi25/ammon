# Classifiche dei campionati e sfondo animato – Piano di esecuzione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Richiesta dell'utente (2026-11-06):** classifiche dei campionati con grafica curata; cartellini dello sfondo più visibili e in movimento con un effetto 3D.

## Task C1: Pagina Classifica
- Nuova pagina **Classifica** nel menu (dopo Partite calde). Pulsanti campionato condivisi (Serie A predefinita, Liga; "Tutti" mostra entrambe una sotto l'altra).
- Calcolata dai risultati nel database (partite finite della stagione in corso, nessuna richiesta esterna): posizione, squadra (iniziali nel cerchio colorato come nelle schede), punti, giocate, V/N/P, gol fatti/subiti, differenza reti, **forma ultime 5** (pallini V verde / N grigio / P rosso), e due colonne del nostro tema: **gialli e rossi a partita** della squadra (gialli dalla panchina compresi).
- Zone colorate a sinistra della riga: Champions (1–4), Europa (5–6), Conference (7), retrocessione (ultime 3) — valori in config per campionato.
- Criteri di classifica a parità di punti: differenza reti, gol fatti, poi nome (documentare che gli scontri diretti, usati dalla Serie A, non sono applicati).
- Su telefono: colonne essenziali (pos, squadra, punti, G, DR, forma), le altre in una riga espandibile.
- Clic su una squadra → pagina Cerca della squadra.
- Regole: aggregati Postgres convertiti (Decimal), query raggruppate, cache con `max_entries`, html.escape, prova nel browser (scuro/chiaro, 375 px).

## Task C2: Sfondo con cartellini animati in 3D
- Cartellini dello sfondo **più visibili** (opacità circa doppia rispetto a ora, ma sempre sotto il 15% sul testo: le schede restano piene e leggibili).
- **Movimento 3D** solo CSS (niente JavaScript, niente librerie): 12–18 cartellini su livelli diversi (`perspective` sul contenitore, `transform: translate3d + rotateX/rotateY/rotateZ`), che fluttuano lentamente con `@keyframes` di durate diverse (20–45 s) e ritardi sfalsati; i più lontani più piccoli e sfocati (`filter: blur`), i vicini più grandi: effetto profondità. Un leggero riflesso lucido sul cartellino (gradiente).
- Prestazioni: solo `transform`/`opacity` animati (GPU), `will-change: transform`, su telefono metà dei cartellini e animazione più lenta.
- Accessibilità: con `prefers-reduced-motion: reduce` i cartellini restano fermi.
- Interruttore nelle Impostazioni "Sfondo animato" (acceso di default), ricordato come il tema (`?anim=0`).
- Entrambi i temi: colori dei cartellini adattati (sul chiaro un po' più saturi).
- Prova nel browser (scuro/chiaro, 375 px) e controllo che lo scorrimento resti fluido.
