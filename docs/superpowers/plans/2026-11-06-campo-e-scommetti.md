# Campo con le formazioni e riquadro "Scommetti" – Piano di esecuzione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

Richieste dell'utente del 2026-11-06.

## Task F1: Campo con le formazioni nel Dettaglio partita
- **Posizione (indicata dall'utente con uno screenshot):** in alto a destra della pagina Dettaglio, accanto al titolo "Venezia – Udinese" e alla riga data/giornata/formazioni, nello spazio vuoto a destra (colonna destra su desktop, ~45% della larghezza); su telefono sotto il titolo, a tutta larghezza, campo in verticale.
- Campo verde disegnato in SVG inline (strisce d'erba alternate, linee bianche, aree, cerchio di centrocampo), casa a sinistra e trasferta a destra (desktop), casa sotto e trasferta sopra (telefono).
- Giocatori posizionati dalla griglia sintetica salvata (`riga:colonna`, 1 portiere … 5 attacco; corsia da destra a sinistra come nel motore) e dal modulo (scritto sopra ogni metà, es. "4-3-3").
- Ogni giocatore: maglietta SVG nei colori della squadra (colore ESPN `team.color` / `alternateColor` se disponibili: salvarli su `Squadra` con migrazione idempotente; altrimenti colore derivato dal nome), numero di maglia (ESPN `jersey`: salvarlo su Presenza/Formazione con migrazione idempotente), cognome sotto; bordo colorato secondo la probabilità di ammonizione (verde < 15%, giallo 15–30%, rosso > 30%). Niente foto (diritti).
- Tocco/clic su un giocatore: evidenzia lui e il suo avversario diretto (linea tratteggiata gialla) e apre la sua scheda nella classifica sotto (ancora). Componente HTML/SVG con un poco di JS inline via `st.components.v1.html` solo se necessario; altrimenti CSS `:target`.
- Scritta "probabili (calcolate)" o "ufficiali" sopra il campo.
- Entrambi i temi, 375 px, html.escape dei nomi; test sul rendering (posizioni coerenti con le griglie, colori per soglia, escape).

## Task F2: Riquadro "Scommetti" nella scheda del giocatore
- Sostituisce il campo "Quota" attuale nella scheda espansa del giocatore.
- Campo "Quota del bookmaker (giocatore ammonito)", accetta la virgola; mostra subito: probabilità del bookmaker (1/quota) e del modello affiancate, badge **"Conviene · valore +8%"** verde o **"Non conviene · −5%"** rosso.
- Pulsante **"L'ho giocata"**: apre una casella "Puntata (€)" con conferma; salva la Giocata (data e ora automatiche, fonte "io", quota, puntata, partita, giocatore) con `aggiungi_giocata`. Se esiste già una giocata su quel giocatore in quella partita: mostra "Giocata registrata: 10 € a 4,50" invece del pulsante.
- La quota inserita resta in sessione per la partita (come oggi), il valore compare anche sulla barra del giocatore.
- Test: valore positivo/negativo, quota non valida (messaggio), registrazione e blocco del doppione, svuotamento cache dopo la scrittura.
