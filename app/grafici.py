"""Grafici della Home (Altair), con i colori del tema scelto: sfondo trasparente, assi e
griglia tenui, testo nei colori del testo (mai in quelli delle serie), tooltip su ogni
segno. Un solo asse per grafico; le serie hanno colori fissi per campionato (giallo per
la Serie A, blu per la Liga: coppia leggibile anche con i difetti della vista più comuni).
Le funzioni restituiscono il grafico, la pagina lo mostra con `st.altair_chart(theme=None)`."""
from __future__ import annotations

import altair as alt

import stile

# seconda serie (Liga) per tema: blu, lontano dal giallo per tinta e luminosità
BLU = {"scuro": "#5B9BFF", "chiaro": "#2F6FDB"}
ALTEZZA_BARRA = 22
ALTEZZA_GRAFICO = 300


def colori_campionati(tema: str) -> tuple[list[str], list[str]]:
    p = stile.PALETTE[tema]
    return ["Serie A", "Liga"], [p["giallo"], BLU[tema]]


def _tema(grafico: alt.Chart, tema: str) -> alt.Chart:
    p = stile.PALETTE[tema]
    return (
        grafico.configure(background="transparent", font="Barlow")
        .configure_view(strokeWidth=0)
        .configure_axis(
            labelColor=p["testo2"], titleColor=p["testo2"], gridColor=p["bordo"],
            domainColor=p["bordo"], tickColor=p["bordo"], labelFontSize=12, titleFontSize=12,
            labelLimit=140, titleFontWeight=600,
        )
        .configure_legend(
            labelColor=p["testo"], titleColor=p["testo2"], orient="top", labelFontSize=12,
            titleFontSize=12,
        )
    )


def barre_primi(dati: list[dict], tema: str) -> alt.Chart:
    """I più ammoniti: barre orizzontali gialle (una sola serie, nessuna legenda)."""
    p = stile.PALETTE[tema]
    base = alt.Chart(alt.Data(values=dati)).encode(
        y=alt.Y("Giocatore:N", sort="-x", title=None),
        x=alt.X("Gialli:Q", title="Gialli", axis=alt.Axis(tickMinStep=1, format="d")),
        tooltip=[
            alt.Tooltip("Giocatore:N"), alt.Tooltip("Squadra:N"), alt.Tooltip("Gialli:Q"),
            alt.Tooltip("Rossi:Q"),
        ],
    )
    barre = base.mark_bar(color=p["giallo"], cornerRadiusEnd=4, height=ALTEZZA_BARRA - 6)
    etichette = base.mark_text(align="left", dx=4, color=p["testo"], fontWeight=600).encode(
        text="Gialli:Q"
    )
    return _tema(
        (barre + etichette).properties(height=max(len(dati), 1) * ALTEZZA_BARRA), tema
    )


def dispersione(dati: list[dict], tema: str) -> alt.Chart:
    """Falli per 90' (x) contro gialli per 90' (y); "in ritardo" in rosso e pieni, gli altri
    grigi e vuoti (forma oltre al colore)."""
    p = stile.PALETTE[tema]
    return _tema(
        alt.Chart(alt.Data(values=dati))
        .mark_point(size=70, strokeWidth=2)
        .encode(
            x=alt.X("Falli90:Q", title="Falli commessi per 90'"),
            y=alt.Y("Gialli90:Q", title="Gialli per 90'"),
            color=alt.Color(
                "Gruppo:N", title=None,
                scale=alt.Scale(domain=["In ritardo", "Altri"], range=[p["rosso"], p["testo2"]]),
            ),
            fill=alt.Fill(
                "Gruppo:N", title=None,
                scale=alt.Scale(domain=["In ritardo", "Altri"], range=[p["rosso"], "transparent"]),
            ),
            opacity=alt.condition("datum.Gruppo == 'In ritardo'", alt.value(1), alt.value(0.55)),
            tooltip=[
                alt.Tooltip("Giocatore:N"), alt.Tooltip("Squadra:N"),
                alt.Tooltip("Falli90:Q", title="Falli per 90'", format=".2f"),
                alt.Tooltip("Gialli90:Q", title="Gialli per 90'", format=".2f"),
                alt.Tooltip("Gialli:Q"), alt.Tooltip("Minuti:Q"),
            ],
        )
        .properties(height=ALTEZZA_GRAFICO),
        tema,
    )


def per_giornata(dati: list[dict], tema: str) -> alt.Chart:
    """Gialli per giornata: una linea per campionato (legenda solo se sono due)."""
    p = stile.PALETTE[tema]
    dominio, colori = colori_campionati(tema)
    presenti = sorted({d["Campionato"] for d in dati}, key=dominio.index) if dati else dominio[:1]
    colore = alt.Color(
        "Campionato:N", title=None,
        scale=alt.Scale(domain=dominio, range=colori),
        legend=alt.Legend() if len(presenti) > 1 else None,
    )
    base = alt.Chart(alt.Data(values=dati)).encode(
        x=alt.X("Giornata:O", title="Giornata", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("Gialli:Q", title="Gialli (panchina compresa)"),
        color=colore,
        tooltip=[
            alt.Tooltip("Campionato:N"), alt.Tooltip("Giornata:O"), alt.Tooltip("Gialli:Q"),
            alt.Tooltip("Media a partita:Q", format=".2f"),
        ],
    )
    linee = base.mark_line(strokeWidth=2)
    punti = base.mark_point(filled=True, size=70, stroke=p["sfondo"], strokeWidth=2)
    return _tema((linee + punti).properties(height=ALTEZZA_GRAFICO), tema)


def per_squadra(dati: list[dict], tema: str) -> alt.Chart:
    """Media gialli a partita per squadra: barre orizzontali, dalla più alta."""
    p = stile.PALETTE[tema]
    base = alt.Chart(alt.Data(values=dati)).encode(
        y=alt.Y("Squadra:N", sort="-x", title=None),
        x=alt.X("Media:Q", title="Gialli a partita"),
        tooltip=[
            alt.Tooltip("Squadra:N"), alt.Tooltip("Media:Q", format=".2f"),
            alt.Tooltip("Gialli:Q"), alt.Tooltip("Partite:Q"),
        ],
    )
    barre = base.mark_bar(color=p["giallo"], cornerRadiusEnd=4, height=ALTEZZA_BARRA - 6)
    etichette = base.mark_text(align="left", dx=4, color=p["testo"], fontWeight=600).encode(
        text=alt.Text("Media:Q", format=".1f")
    )
    return _tema(
        (barre + etichette).properties(height=max(len(dati), 1) * ALTEZZA_BARRA), tema
    )
