"""Grafica "Cartellino": palette, CSS dei due temi, sfondo a cartellini, intestazione,
pulsante sole/luna, pulsanti dei campionati e componenti HTML (schede, barre, badge).

Le funzioni che restituiscono HTML non usano Streamlit e fanno l'escape di tutti i dati
(nomi di squadre, giocatori, arbitri): le pagine le mostrano con
`st.markdown(..., unsafe_allow_html=True)`. Il nome dell'app si cambia solo qui."""
from __future__ import annotations

import colorsys
import hashlib
import random
from html import escape
from urllib.parse import quote

import streamlit as st

import componenti
from ammonizioni.motore.tipi import decimale

NOME_APP = "Cartellino"

TEMA_PREDEFINITO = "scuro"
TEMA_CHIARO = "chiaro"
CHIAVE_TEMA = "tema"  # session_state e parametro dell'URL (?tema=chiaro)
CHIAVE_CAMPIONATO = "campionato"  # scelta che resta valida su tutte le pagine
WIDGET_CAMPIONATO = "scelta_campionato"
PARAMETRO_CAMPIONATO = "campionato"  # ?campionato=serie-a

PALETTE: dict[str, dict[str, str]] = {
    "scuro": {
        "sfondo": "#0F1115",
        "superficie": "#181B22",
        "superficie2": "#20242D",
        "testo": "#ECEDEE",
        "testo2": "#A0A4AB",
        "giallo": "#F5C518",
        "rosso": "#E5484D",
        "verde": "#3DD68C",
        "bordo": "#2A2E37",
        "link": "#F5C518",
        "traccia": "#2A2E37",
    },
    "chiaro": {
        "sfondo": "#F7F7F5",
        "superficie": "#FFFFFF",
        "superficie2": "#EFEFEC",
        "testo": "#15171C",
        "testo2": "#5B6069",
        "giallo": "#C99A00",
        "rosso": "#D1343A",
        "verde": "#1E9E5A",
        "bordo": "#E3E4E1",
        "link": "#7A5C00",
        "traccia": "#E9E9E5",
    },
}
# opacità dei cartellini dello sfondo: 4-7% sul tema scuro, 6-9% sul chiaro
OPACITA_SFONDO = {"scuro": 0.055, "chiaro": 0.08}
OMBRA = {
    "scuro": "0 1px 2px rgba(0,0,0,.35), 0 6px 18px rgba(0,0,0,.28)",
    "chiaro": "0 1px 2px rgba(20,22,28,.06), 0 6px 18px rgba(20,22,28,.07)",
}
TIPI_BADGE = ("giallo", "rosso", "verde", "neutro")
RUOLI = {"G": "Portiere", "D": "Difensore", "M": "Centrocampista", "F": "Attaccante"}
AFFIDABILITA = {
    "alto": ("Affidabilità alta", "verde"),
    "medio": ("Affidabilità media", "giallo"),
    "dati insufficienti": ("Dati insufficienti", "neutro"),
}
ESITI_BADGE = {"vinta": "verde", "persa": "rosso"}
PROBABILITA_MASSIMA = 0.70  # la barra piena corrisponde al 70%
LARGHEZZA_MINIMA = 3  # percento: anche il 2% resta visibile

FONT_URL = (
    "https://fonts.googleapis.com/css2?family=Barlow:wght@400;500;600;700"
    "&family=Barlow+Condensed:wght@600;700;800&display=swap"
)


# ---------------------------------------------------------------- colori

def _luminanza(colore: str) -> float:
    r, g, b = (int(colore.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def canale(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * canale(r) + 0.7152 * canale(g) + 0.0722 * canale(b)


def contrasto(a: str, b: str) -> float:
    """Rapporto di contrasto WCAG fra due colori "#RRGGBB"."""
    la, lb = sorted((_luminanza(a), _luminanza(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _rgba(colore: str, alfa: float) -> str:
    r, g, b = (int(colore.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alfa})"


# ---------------------------------------------------------------- disegni SVG

def logo_svg(lato: int = 38) -> str:
    """Due cartellini sovrapposti: rosso dietro, giallo davanti, leggermente inclinati."""
    return (
        f'<svg class="cr-logo" width="{lato}" height="{lato}" viewBox="0 0 40 40" '
        'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        '<rect x="9" y="6" width="17" height="24" rx="3" fill="#E5484D" '
        'transform="rotate(-14 17.5 18)"/>'
        '<rect x="15" y="10" width="17" height="24" rx="3" fill="#F5C518" '
        'stroke="rgba(0,0,0,.18)" stroke-width="1" transform="rotate(9 23.5 22)"/>'
        "</svg>"
    )


def sfondo_svg(tema: str, telefono: bool = False) -> str:
    """Motivo ripetibile di piccoli cartellini (gialli, qualche rosso) ruotati a caso ma
    sempre allo stesso modo (seme fisso), come data URI. Su telefono è più rado."""
    p = PALETTE[tema]
    celle, lato = (3, 330) if telefono else (4, 280)
    rnd = random.Random(1990)
    passo = lato / celle
    rossi = set(rnd.sample(range(celle * celle), 2))
    pezzi = []
    for i in range(celle * celle):
        riga, col = divmod(i, celle)
        x = col * passo + rnd.uniform(8, passo - 26)
        y = riga * passo + rnd.uniform(8, passo - 30)
        angolo = rnd.uniform(-38, 38)
        colore = p["rosso"] if i in rossi else p["giallo"]
        pezzi.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="15" height="21" rx="2.5" fill="{colore}" '
            f'transform="rotate({angolo:.0f} {x + 7.5:.1f} {y + 10.5:.1f})"/>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{lato}" height="{lato}" '
        f'viewBox="0 0 {lato} {lato}"><g fill-opacity="{OPACITA_SFONDO[tema]}">'
        + "".join(pezzi) + "</g></svg>"
    )
    return "data:image/svg+xml," + quote(svg)


# ---------------------------------------------------------------- CSS

def css_tema(tema: str) -> str:
    """Tutto il CSS dell'app per il tema dato (variabili, sfondo, widget nativi, componenti)."""
    p = PALETTE[tema]
    chiaro = tema == TEMA_CHIARO
    variabili = "\n".join(f"  --cr-{nome}: {valore};" for nome, valore in p.items())
    tenui = "\n".join(
        f"  --cr-{nome}-tenue: {_rgba(p[nome], 0.16 if chiaro else 0.18)};"
        for nome in ("giallo", "rosso", "verde")
    )
    sfondo, sfondo_tel = sfondo_svg(tema), sfondo_svg(tema, telefono=True)
    # il dataframe di Streamlit è disegnato su canvas con i colori del tema scuro di base:
    # nel tema chiaro lo si inverte (resta leggibile e chiaro)
    dataframe = (
        '[data-testid="stDataFrame"] { filter: invert(1) hue-rotate(180deg); }'
        if chiaro else ""
    )
    return f"""@import url('{FONT_URL}');
:root {{
{variabili}
{tenui}
  --cr-neutro-tenue: {_rgba(p["testo2"], 0.16)};
  --cr-ombra: {OMBRA[tema]};
  --cr-su-giallo: #15171C;
  color-scheme: {"light" if chiaro else "dark"};
}}
html, body, .stApp {{
  background-color: var(--cr-sfondo) !important;
  color: var(--cr-testo) !important;
  font-family: 'Barlow', system-ui, -apple-system, 'Segoe UI', sans-serif;
}}
[data-testid="stAppViewContainer"] {{
  background-color: var(--cr-sfondo) !important;
  background-image: url("{sfondo}");
  background-repeat: repeat;
  background-attachment: fixed;
}}
[data-testid="stMain"], [data-testid="stBottomBlockContainer"] {{ background: transparent !important; }}
[data-testid="stMainBlockContainer"] {{ max-width: 1180px; padding-top: 4.6rem; padding-bottom: 3rem; }}
[data-testid="stDecoration"] {{ display: none; }}
[data-testid="stHeader"] {{
  background: {_rgba(p["sfondo"], 0.88)} !important;
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--cr-bordo);
}}
[data-testid="stHeader"] a, [data-testid="stHeader"] span, [data-testid="stHeader"] p,
[data-testid="stHeader"] button, [data-testid="stHeader"] svg {{ color: var(--cr-testo) !important; }}
[data-testid="stHeader"] a {{ font-family: 'Barlow', sans-serif; font-weight: 600; border-radius: 10px; }}
[data-testid="stHeader"] a:hover {{ background: var(--cr-giallo-tenue) !important; }}
[data-testid="stHeader"] a[aria-current="page"], [data-testid="stHeader"] a[aria-selected="true"] {{
  background: var(--cr-giallo-tenue) !important; box-shadow: inset 0 -2px 0 var(--cr-giallo);
}}
[data-baseweb="popover"] > div, [data-baseweb="popover"] ul, [data-baseweb="menu"], [role="listbox"],
[data-testid="stSelectboxVirtualDropdown"], [data-testid="stMultiSelectVirtualDropdown"] {{
  background-color: var(--cr-superficie) !important; color: var(--cr-testo) !important;
  border-color: var(--cr-bordo) !important;
}}
[data-baseweb="popover"] a, [data-baseweb="popover"] span, [data-baseweb="popover"] li,
[role="option"], [role="option"] * {{ color: var(--cr-testo) !important; }}
[role="option"]:hover, [role="option"][aria-selected="true"] {{ background-color: var(--cr-giallo-tenue) !important; }}

/* testo e titoli */
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {{
  font-family: 'Barlow Condensed', 'Barlow', sans-serif !important;
  color: var(--cr-testo) !important; letter-spacing: .01em;
}}
.stApp h1 {{ font-weight: 800 !important; }}
.stApp h2, .stApp h3 {{ font-weight: 700 !important; }}
.stApp h3 {{ border-left: 4px solid var(--cr-giallo); padding-left: .55rem !important; margin-top: .6rem; }}
.stApp p, .stApp li, .stApp label, .stApp td, .stApp th {{ color: var(--cr-testo); }}
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] * {{ color: var(--cr-testo) !important; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {{ color: var(--cr-testo2) !important; }}
.stApp a {{ color: var(--cr-link); }}

/* campi, menu a tendina, date */
[data-baseweb="input"], [data-baseweb="base-input"], [data-baseweb="textarea"],
[data-baseweb="select"] > div, [data-testid="stNumberInputContainer"], [data-testid="stDateInputField"],
[data-testid="stTextInputRootElement"], [data-testid="stTextAreaRootElement"],
[data-testid="stSelectbox"] [role="group"], [data-testid="stMultiSelect"] [role="group"],
[data-testid="stDateInput"] [role="group"], [data-testid="stTimeInput"] [role="group"] {{
  background-color: var(--cr-superficie) !important; border-color: var(--cr-bordo) !important;
  color: var(--cr-testo) !important; border-radius: 10px !important;
}}
.stApp input, .stApp textarea {{
  background-color: transparent !important; color: var(--cr-testo) !important;
  -webkit-text-fill-color: var(--cr-testo) !important; caret-color: var(--cr-giallo);
  min-height: 42px; font-family: 'Barlow', sans-serif !important;
}}
.stApp input::placeholder, .stApp textarea::placeholder {{
  color: var(--cr-testo2) !important; -webkit-text-fill-color: var(--cr-testo2) !important;
}}
[data-baseweb="select"] *, [data-baseweb="select"] svg,
[data-testid="stSelectbox"] [role="group"] *, [data-testid="stMultiSelect"] [role="group"] *,
[data-testid="stDateInput"] [role="group"] *, [data-testid="stTimeInput"] [role="group"] *,
[data-testid="stTextInputRootElement"] *, [data-testid="stNumberInputContainer"] * {{ color: var(--cr-testo) !important; }}
[data-baseweb="tag"] {{ background-color: var(--cr-giallo-tenue) !important; }}
[data-baseweb="tag"] * {{ color: var(--cr-testo) !important; }}
[data-testid="stNumberInputContainer"] button {{
  background: var(--cr-superficie2) !important; color: var(--cr-testo) !important;
}}
[data-baseweb="calendar"], [data-baseweb="calendar"] div {{ background-color: var(--cr-superficie) !important; }}
[data-baseweb="calendar"] * {{ color: var(--cr-testo); }}
[data-baseweb="calendar"] [aria-selected="true"] div {{ background: var(--cr-giallo) !important; color: var(--cr-su-giallo) !important; }}

/* pulsanti */
.stButton button, .stFormSubmitButton button, .stDownloadButton button {{
  min-height: 44px; border-radius: 10px !important; font-weight: 600;
  font-family: 'Barlow', sans-serif;
  background: var(--cr-superficie) !important; color: var(--cr-testo) !important;
  border: 1px solid var(--cr-bordo) !important;
}}
.stButton button:hover, .stFormSubmitButton button:hover {{ border-color: var(--cr-giallo) !important; }}
.stButton button *, .stFormSubmitButton button * {{ color: inherit !important; }}
[data-testid^="stBaseButton-primary"] {{
  background: var(--cr-giallo) !important; color: var(--cr-su-giallo) !important;
  border-color: var(--cr-giallo) !important;
}}

/* pulsanti dei campionati (segmented control) */
[data-testid="stButtonGroup"] button {{
  min-height: 44px; padding: 0 1.15rem; font-weight: 700; font-size: 1rem;
  font-family: 'Barlow', sans-serif;
  background: var(--cr-superficie) !important; color: var(--cr-testo) !important;
  border-color: var(--cr-bordo) !important;
}}
[data-testid="stButtonGroup"] button * {{ color: inherit !important; }}
[data-testid="stButtonGroup"] button[aria-checked="true"],
[data-testid="stButtonGroup"] [data-testid="stBaseButton-segmented_controlActive"] {{
  background: var(--cr-giallo) !important; color: var(--cr-su-giallo) !important;
  border-color: var(--cr-giallo) !important;
}}
.st-key-scelta_campionato {{ margin-bottom: .4rem; }}

/* schede di Streamlit: expander, form, tab, tabelle, avvisi */
[data-testid="stExpander"] details {{
  background: var(--cr-superficie) !important; border: 1px solid var(--cr-bordo) !important;
  border-radius: 14px !important; box-shadow: var(--cr-ombra);
}}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * {{ color: var(--cr-testo) !important; }}
[data-testid="stExpander"] summary:hover {{ background: var(--cr-giallo-tenue) !important; border-radius: 14px; }}
[data-testid="stForm"] {{
  background: var(--cr-superficie); border: 1px solid var(--cr-bordo) !important;
  border-radius: 14px !important; box-shadow: var(--cr-ombra);
}}
[data-baseweb="tab-list"] {{ gap: .25rem; }}
[data-baseweb="tab"] {{ min-height: 44px; }}
[data-baseweb="tab"], [data-baseweb="tab"] *, [data-testid="stTab"], [data-testid="stTab"] * {{
  color: var(--cr-testo2) !important; font-weight: 600;
}}
[data-baseweb="tab"][aria-selected="true"], [data-baseweb="tab"][aria-selected="true"] *,
[data-testid="stTab"][aria-selected="true"], [data-testid="stTab"][aria-selected="true"] * {{ color: var(--cr-testo) !important; }}
[data-baseweb="tab-highlight"] {{ background-color: var(--cr-giallo) !important; }}
[data-baseweb="tab-border"] {{ background-color: var(--cr-bordo) !important; }}
[data-testid="stTable"] table {{ background: var(--cr-superficie); border-radius: 10px; }}
[data-testid="stTable"] th, [data-testid="stTable"] td {{
  color: var(--cr-testo) !important; border-color: var(--cr-bordo) !important; background: transparent !important;
}}
[data-testid="stAlertContainer"] {{ border-radius: 12px; }}
[data-testid="stAlertContainer"] * {{ color: var(--cr-testo) !important; }}
{dataframe}

/* pulsante sole/luna: fisso in alto a destra, fuori da ogni menu */
.st-key-cambia_tema {{
  position: fixed !important; top: 10px; right: 58px; z-index: 1000002; width: auto !important;
}}
.st-key-cambia_tema button {{
  width: 40px; height: 40px; min-height: 40px; padding: 0 !important; border-radius: 50% !important;
  font-size: 1.15rem; line-height: 1; box-shadow: var(--cr-ombra);
}}

/* intestazione */
.cr-intestazione {{ display: flex; align-items: center; gap: .7rem; margin: 0 0 .6rem; flex-wrap: wrap; }}
.cr-intestazione .cr-nome-app {{
  font-family: 'Barlow Condensed', sans-serif; font-weight: 800; font-size: 1.9rem;
  line-height: 1; letter-spacing: .02em; color: var(--cr-testo);
}}
.cr-aggiornato {{
  font-size: .85rem; color: var(--cr-testo2); background: var(--cr-superficie);
  border: 1px solid var(--cr-bordo); border-radius: 999px; padding: .2rem .7rem;
}}

/* badge */
.cr-badge {{
  display: inline-flex; align-items: center; gap: .3rem; font-size: .8rem; font-weight: 600;
  padding: .18rem .6rem; border-radius: 999px; color: var(--cr-testo);
  border: 1px solid transparent; white-space: nowrap; line-height: 1.35;
}}
.cr-badge--giallo {{ background: var(--cr-giallo-tenue); border-color: var(--cr-giallo); }}
.cr-badge--rosso {{ background: var(--cr-rosso-tenue); border-color: var(--cr-rosso); }}
.cr-badge--verde {{ background: var(--cr-verde-tenue); border-color: var(--cr-verde); }}
.cr-badge--neutro {{ background: var(--cr-neutro-tenue); border-color: var(--cr-bordo); }}
.cr-badges {{ display: flex; flex-wrap: wrap; gap: .35rem; margin-top: .55rem; }}

/* schede delle partite: tutta la scheda porta al dettaglio */
[class*="st-key-giorno_"] {{
  display: grid !important; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); gap: 14px;
}}
[class*="st-key-scheda_partita_"] {{
  position: relative; background: var(--cr-superficie); border: 1px solid var(--cr-bordo);
  border-radius: 14px; box-shadow: var(--cr-ombra); padding: 14px 16px 10px; gap: .2rem;
  transition: transform .12s ease, border-color .12s ease;
}}
[class*="st-key-scheda_partita_"]:hover {{ border-color: var(--cr-giallo); transform: translateY(-2px); }}
[class*="st-key-scheda_partita_"] [data-testid="stElementContainer"],
[class*="st-key-scheda_partita_"] [data-testid="stPageLink"],
[class*="st-key-scheda_partita_"] [data-testid="stPageLink"] div,
[class*="st-key-scheda_partita_"] [data-testid="stPageLink"] a {{ position: static !important; }}
[class*="st-key-scheda_partita_"] > [data-testid="stElementContainer"]:last-child {{ margin: .5rem 0 0 !important; }}
[class*="st-key-scheda_partita_"] [data-testid="stPageLink"] a {{
  justify-content: flex-end; background: transparent !important; padding: 0 !important;
}}
[class*="st-key-scheda_partita_"] [data-testid="stPageLink"] a::after {{
  content: ""; position: absolute; inset: 0; border-radius: 14px; z-index: 1;
}}
[class*="st-key-scheda_partita_"] [data-testid="stPageLink"] a * {{
  color: var(--cr-link) !important; font-weight: 700; font-size: .9rem;
}}
.cr-partita-testa {{ display: flex; justify-content: space-between; align-items: baseline; gap: .5rem; }}
.cr-ora {{
  font-family: 'Barlow Condensed', sans-serif; font-weight: 800; font-size: 1.75rem; line-height: 1;
  color: var(--cr-testo);
}}
.cr-meta {{ font-size: .8rem; color: var(--cr-testo2); text-transform: uppercase; letter-spacing: .06em; font-weight: 600; }}
.cr-squadre {{ display: grid; gap: .35rem; margin-top: .7rem; }}
.cr-squadra {{ display: flex; align-items: center; gap: .6rem; font-size: 1.1rem; font-weight: 700; }}
.cr-stemma {{
  width: 30px; height: 30px; border-radius: 50%; display: inline-flex; align-items: center;
  justify-content: center; font-size: .72rem; font-weight: 800; color: #FFFFFF; flex: 0 0 30px;
  letter-spacing: .02em; box-shadow: inset 0 0 0 2px rgba(255,255,255,.18);
}}
.cr-arbitro {{ margin-top: .55rem; font-size: .88rem; color: var(--cr-testo2); }}

/* sezioni a scheda (Impostazioni) */
[class*="st-key-riquadro_"] {{
  background: var(--cr-superficie); border: 1px solid var(--cr-bordo); border-radius: 14px;
  box-shadow: var(--cr-ombra); padding: 16px 18px;
}}
[class*="st-key-riquadro_"] h2 {{ font-size: 1.5rem !important; }}

/* contesto della partita */
.cr-scheda {{
  background: var(--cr-superficie); border: 1px solid var(--cr-bordo); border-radius: 14px;
  box-shadow: var(--cr-ombra); padding: 14px 16px; margin-bottom: .8rem;
}}
.cr-scheda ul {{ margin: 0; padding-left: 1.1rem; }}
.cr-scheda li {{ margin: .15rem 0; }}

/* candidati: barre di probabilità */
.cr-candidato {{
  background: var(--cr-superficie); border: 1px solid var(--cr-bordo); border-radius: 14px;
  box-shadow: var(--cr-ombra); padding: 12px 14px; margin-bottom: 10px;
}}
.cr-cand-testa {{ display: flex; justify-content: space-between; align-items: flex-start; gap: .6rem; }}
.cr-cand-nome {{ font-weight: 700; font-size: 1.08rem; color: var(--cr-testo); }}
.cr-cand-info {{ font-size: .85rem; color: var(--cr-testo2); }}
.cr-perc {{
  font-family: 'Barlow Condensed', sans-serif; font-weight: 800; font-size: 1.7rem; line-height: 1;
  color: var(--cr-testo);
}}
.cr-barra {{ height: 10px; background: var(--cr-traccia); border-radius: 999px; overflow: hidden; margin: .5rem 0; }}
.cr-barra > span {{
  display: block; height: 100%; border-radius: 999px;
  background: linear-gradient(90deg, var(--cr-giallo), #FFD84D);
}}
.cr-motivi {{ font-size: .85rem; color: var(--cr-testo2); }}

/* giocate e statistiche */
.cr-griglia {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; margin-bottom: 1rem; }}
.cr-tessera {{
  background: var(--cr-superficie); border: 1px solid var(--cr-bordo); border-radius: 14px;
  box-shadow: var(--cr-ombra); padding: 12px 14px;
}}
.cr-tessera-titolo {{ font-weight: 700; font-size: 1.05rem; color: var(--cr-testo); }}
.cr-tessera-sotto {{ font-size: .85rem; color: var(--cr-testo2); }}
.cr-voci {{ display: grid; grid-template-columns: 1fr auto; gap: .2rem .8rem; margin-top: .5rem; font-size: .9rem; }}
.cr-voci dt {{ color: var(--cr-testo2); }}
.cr-voci dd {{ margin: 0; font-weight: 700; text-align: right; color: var(--cr-testo); }}

/* pagina Cerca: tabelle a scorrimento orizzontale e schede dei risultati */
.cr-tabella-scroll {{
  overflow-x: auto; background: var(--cr-superficie); border: 1px solid var(--cr-bordo);
  border-radius: 14px; box-shadow: var(--cr-ombra); margin-bottom: 1rem;
}}
.cr-tabella {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
.cr-tabella th {{
  text-align: right; padding: .55rem .7rem; color: var(--cr-testo2); font-weight: 600;
  font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; white-space: nowrap;
  border-bottom: 1px solid var(--cr-bordo);
}}
.cr-tabella td {{ text-align: right; padding: .5rem .7rem; color: var(--cr-testo); white-space: nowrap; }}
.cr-tabella tr + tr td {{ border-top: 1px solid var(--cr-bordo); }}
.cr-tabella th:first-child, .cr-tabella td:first-child,
.cr-tabella th:nth-child(2), .cr-tabella td:nth-child(2) {{ text-align: left; }}
.cr-tabella td.cr-forte {{ font-weight: 700; }}
.cr-testa-giocatore {{
  background: var(--cr-superficie); border: 1px solid var(--cr-bordo); border-radius: 14px;
  box-shadow: var(--cr-ombra); padding: 14px 16px; margin-bottom: .8rem;
}}
.cr-testa-nome {{
  font-family: 'Barlow Condensed', sans-serif; font-weight: 800; font-size: 2rem; line-height: 1.05;
  color: var(--cr-testo);
}}

/* telefono: una colonna, sfondo più rado, niente tabelle larghe */
@media (max-width: 640px) {{
  [data-testid="stAppViewContainer"] {{ background-image: url("{sfondo_tel}"); }}
  [data-testid="stMainBlockContainer"] {{ padding-left: 16px !important; padding-right: 16px !important; padding-top: 4.2rem; }}
  [class*="st-key-giorno_"] {{ grid-template-columns: 1fr; }}
  [class*="st-key-solo_desktop"] {{ display: none !important; }}
  .cr-intestazione .cr-nome-app {{ font-size: 1.6rem; }}
  .cr-griglia {{ grid-template-columns: 1fr; }}
  [data-testid="stButtonGroup"] button {{ padding: 0 .9rem; }}
}}
@media (min-width: 641px) {{
  [class*="st-key-solo_telefono"] {{ display: none !important; }}
}}
"""


# ---------------------------------------------------------------- componenti HTML

def badge(testo: str, tipo: str = "neutro") -> str:
    """Etichetta arrotondata con i colori della palette (giallo, rosso, verde, neutro)."""
    if tipo not in TIPI_BADGE:
        raise ValueError(f"tipo di badge sconosciuto: {tipo}")
    return f'<span class="cr-badge cr-badge--{tipo}">{escape(testo)}</span>'


def iniziali(nome: str) -> str:
    """"Casa FC" -> "CF", "Inter" -> "IN": per lo stemma quando manca il logo."""
    parole = [p for p in nome.split() if p[:1].isalnum() and (p[:1].isupper() or p[:1].isdigit())]
    if not parole:
        parole = nome.split()
    if not parole:
        return "?"
    if len(parole) == 1:
        return parole[0][:2].upper()
    return (parole[0][0] + parole[-1][0]).upper()


def _colore_stemma(nome: str) -> str:
    tinta = int(hashlib.sha1(nome.encode("utf-8")).hexdigest()[:4], 16) / 0xFFFF
    r, g, b = colorsys.hls_to_rgb(tinta, 0.36, 0.55)
    return f"#{round(r * 255):02X}{round(g * 255):02X}{round(b * 255):02X}"


def _squadra(nome: str) -> str:
    return (
        f'<div class="cr-squadra"><span class="cr-stemma" style="background:{_colore_stemma(nome)}">'
        f"{escape(iniziali(nome))}</span><span>{escape(nome)}</span></div>"
    )


def scheda_partita(riga: componenti.RigaPartita) -> str:
    """Scheda di una partita: orario grande, squadre con stemma, campionato e giornata,
    arbitro e badge (calda, derby, arbitro severo, formazioni)."""
    meta = " · ".join(
        x for x in (riga.campionato, f"Giornata {riga.giornata}" if riga.giornata else "") if x
    )
    arbitro = f"Arbitro: {riga.arbitro}" if riga.arbitro else "Arbitro da designare"
    badges = []
    if riga.calda:
        badges.append(badge("🔥 Partita calda", "rosso"))
    if riga.derby:
        badges.append(badge("⚔️ Derby", "rosso"))
    if riga.arbitro_severo:
        badges.append(badge("🟨 Arbitro severo", "giallo"))
    if riga.formazioni == "ufficiali":
        badges.append(badge("✅ Formazioni ufficiali", "verde"))
    else:
        badges.append(badge(f"📋 Formazioni {riga.formazioni}", "neutro"))
    return (
        '<div class="cr-partita">'
        f'<div class="cr-partita-testa"><span class="cr-ora">{escape(riga.ora)}</span>'
        f'<span class="cr-meta">{escape(meta)}</span></div>'
        f'<div class="cr-squadre" title="{escape(riga.casa)} – {escape(riga.trasferta)}">'
        f"{_squadra(riga.casa)}{_squadra(riga.trasferta)}</div>"
        f'<div class="cr-arbitro">{escape(arbitro)}</div>'
        f'<div class="cr-badges">{"".join(badges)}</div>'
        "</div>"
    )


def larghezza_barra(probabilita: float) -> int:
    """Percentuale di riempimento della barra: proporzionale, piena al 70%."""
    quota = round(probabilita / PROBABILITA_MASSIMA * 100)
    return max(LARGHEZZA_MINIMA, min(100, quota))


def barra_probabilita(candidato, squadra: str, tipster: list[str] | tuple = ()) -> str:
    """Candidato all'ammonizione: nome, squadra e ruolo, barra gialla, percentuale,
    motivazioni, affidabilità, quota e valore (verde se positivo), tipster."""
    c = candidato
    ruolo = RUOLI.get(c.ruolo or "", "")
    info = " · ".join(x for x in (squadra, ruolo) if x)
    testo_aff, tipo_aff = AFFIDABILITA.get(c.affidabilita, (str(c.affidabilita), "neutro"))
    badges = [badge(testo_aff, tipo_aff)]
    if c.quota:
        implicita = f" · implicita {componenti.percentuale(c.prob_implicita)}" if c.prob_implicita else ""
        badges.append(badge(f"Quota {decimale(c.quota, 2)}{implicita}", "neutro"))
    if c.valore is not None:
        testo = componenti.valore_testo(c.valore)
        positivo = testo.startswith("+") and testo != "+0%"
        badges.append(badge(f"Valore {testo}", "verde" if positivo else "neutro"))
    if tipster:
        badges.append(badge("Tipster: " + ", ".join(tipster), "giallo"))
    motivi = " · ".join(c.motivazioni)
    return (
        '<div class="cr-candidato">'
        '<div class="cr-cand-testa"><div>'
        f'<div class="cr-cand-nome">{escape(c.nome)}</div>'
        f'<div class="cr-cand-info">{escape(info)}</div></div>'
        f'<div class="cr-perc">{escape(componenti.percentuale(c.probabilita))}</div></div>'
        f'<div class="cr-barra"><span style="width: {larghezza_barra(c.probabilita)}%"></span></div>'
        + (f'<div class="cr-motivi">{escape(motivi)}</div>' if motivi else "")
        + f'<div class="cr-badges">{"".join(badges)}</div>'
        "</div>"
    )


def scheda_contesto(righe: list[str]) -> str:
    voci = "".join(f"<li>{escape(r)}</li>" for r in righe)
    return f'<div class="cr-scheda"><ul>{voci}</ul></div>'


def _voci(coppie: list[tuple[str, object]]) -> str:
    return '<dl class="cr-voci">' + "".join(
        f"<dt>{escape(str(k))}</dt><dd>{escape(str(v))}</dd>" for k, v in coppie
    ) + "</dl>"


def scheda_giocata(riga: dict) -> str:
    """Una giocata del registro come scheda (al posto della tabella su telefono)."""
    esito = str(riga.get("Esito", ""))
    return (
        '<div class="cr-tessera">'
        '<div class="cr-partita-testa">'
        f'<span class="cr-tessera-titolo">{escape(str(riga.get("Giocatore", "")))}</span>'
        f'{badge(esito, ESITI_BADGE.get(esito, "neutro"))}</div>'
        f'<div class="cr-tessera-sotto">{escape(str(riga.get("Partita", "")))}</div>'
        + _voci([
            ("Data", riga.get("Data", "")), ("Fonte", riga.get("Fonte", "")),
            ("Quota", riga.get("Quota", "")), ("Puntata", riga.get("Puntata", "")),
        ])
        + "</div>"
    )


def riquadro_statistiche(riga: dict) -> str:
    """Statistiche di una fonte come riquadro."""
    voci = [(k, v) for k, v in riga.items() if k != "Fonte"]
    return (
        '<div class="cr-tessera">'
        f'<div class="cr-tessera-titolo">{escape(str(riga.get("Fonte", "")))}</div>'
        + _voci(voci) + "</div>"
    )


def tabella(colonne: tuple[str, ...] | list[str], righe: list[list[str]]) -> str:
    """Tabella HTML che scorre in orizzontale dentro la sua scheda (nessuno scorrimento della
    pagina); tutte le celle sono testo con escape."""
    testa = "".join(f"<th>{escape(c)}</th>" for c in colonne)
    corpo = "".join(
        "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in riga) + "</tr>" for riga in righe
    )
    return (
        '<div class="cr-tabella-scroll"><table class="cr-tabella">'
        f"<thead><tr>{testa}</tr></thead><tbody>{corpo}</tbody></table></div>"
    )


def tessera(titolo: str, sotto: str, coppie: list[tuple[str, object]]) -> str:
    """Riquadro con titolo, sottotitolo e voci etichetta/valore (stagioni su telefono)."""
    return (
        '<div class="cr-tessera">'
        f'<div class="cr-tessera-titolo">{escape(titolo)}</div>'
        f'<div class="cr-tessera-sotto">{escape(sotto)}</div>' + _voci(coppie) + "</div>"
    )


def testa_giocatore(nome: str, sotto: str, badges: list[str]) -> str:
    """Intestazione della scheda del giocatore; `badges` sono HTML già pronto (da `badge`)."""
    return (
        '<div class="cr-testa-giocatore">'
        f'<div class="cr-testa-nome">{escape(nome)}</div>'
        f'<div class="cr-tessera-sotto">{escape(sotto)}</div>'
        f'<div class="cr-badges">{"".join(badges)}</div></div>'
    )


def risultato_ricerca(titolo: str, sotto: str) -> str:
    """Contenuto di una scheda cliccabile dei risultati di ricerca (giocatore o squadra)."""
    return (
        f'<div class="cr-tessera-titolo">{escape(titolo)}</div>'
        f'<div class="cr-tessera-sotto">{escape(sotto)}</div>'
    )


def griglia(pezzi: list[str]) -> str:
    return '<div class="cr-griglia">' + "".join(pezzi) + "</div>"


def intestazione(testo_aggiornamento: str) -> str:
    return (
        '<div class="cr-intestazione">'
        f'{logo_svg()}<span class="cr-nome-app">{escape(NOME_APP)}</span>'
        f'<span class="cr-aggiornato">{escape(testo_aggiornamento)}</span>'
        "</div>"
    )


# ---------------------------------------------------------------- parametri dell'URL

SLUG_CAMPIONATI = {
    nome: nome.lower().replace(" ", "-") for nome in componenti.FILTRO_CAMPIONATI
}


def tema_da_parametro(valore) -> str:
    return TEMA_CHIARO if valore == TEMA_CHIARO else TEMA_PREDEFINITO


def campionato_da_parametro(valore) -> str:
    for nome, slug in SLUG_CAMPIONATI.items():
        if valore == slug:
            return nome
    return componenti.FILTRO_PREDEFINITO


def slug_campionato(nome: str) -> str:
    return SLUG_CAMPIONATI.get(nome, SLUG_CAMPIONATI[componenti.FILTRO_PREDEFINITO])


# ---------------------------------------------------------------- Streamlit

def tema_corrente() -> str:
    """Tema della sessione; al primo caricamento si legge da ?tema= (scuro predefinito)."""
    if CHIAVE_TEMA not in st.session_state:
        st.session_state[CHIAVE_TEMA] = tema_da_parametro(st.query_params.get(CHIAVE_TEMA))
    return st.session_state[CHIAVE_TEMA]


def _alterna_tema() -> None:
    st.session_state[CHIAVE_TEMA] = (
        TEMA_PREDEFINITO if tema_corrente() == TEMA_CHIARO else TEMA_CHIARO
    )


def _scrivi_tema_nell_url(tema: str) -> None:
    if tema == TEMA_CHIARO:
        if st.query_params.get(CHIAVE_TEMA) != TEMA_CHIARO:
            st.query_params[CHIAVE_TEMA] = TEMA_CHIARO
    elif CHIAVE_TEMA in st.query_params:
        del st.query_params[CHIAVE_TEMA]


def interruttore_tema() -> None:
    """Pulsante tondo ☀️/🌙 fisso in alto a destra (fuori dai menu)."""
    chiaro = tema_corrente() == TEMA_CHIARO
    st.button(
        "🌙" if chiaro else "☀️",
        key="cambia_tema",
        on_click=_alterna_tema,
        help="Passa al tema scuro" if chiaro else "Passa al tema chiaro",
    )


def applica_stile() -> None:
    """Da chiamare in cima a ogni pagina, subito dopo `richiedi_password()`: CSS del tema,
    pulsante sole/luna e intestazione con "Dati aggiornati"."""
    import cache_dati  # qui: cache_dati importa streamlit e il DB solo quando serve

    tema = tema_corrente()
    _scrivi_tema_nell_url(tema)
    st.html(f"<style>{css_tema(tema)}</style>")
    interruttore_tema()
    testo, _ = cache_dati.stato_aggiornamento()
    st.markdown(intestazione(testo), unsafe_allow_html=True)


def campionato_corrente() -> str:
    """Campionato scelto (vale su tutte le pagine); al primo caricamento da ?campionato=."""
    if CHIAVE_CAMPIONATO not in st.session_state:
        st.session_state[CHIAVE_CAMPIONATO] = campionato_da_parametro(
            st.query_params.get(PARAMETRO_CAMPIONATO)
        )
    return st.session_state[CHIAVE_CAMPIONATO]


def _scegli_campionato() -> None:
    scelto = st.session_state.get(WIDGET_CAMPIONATO)
    if scelto is not None:
        st.session_state[CHIAVE_CAMPIONATO] = scelto


def selettore_campionato() -> str:
    """Pulsanti Serie A · Liga · Tutti; la scelta resta nelle altre pagine e nell'URL."""
    corrente = campionato_corrente()
    # il valore del widget si riallinea a ogni pagina (il widget di un'altra pagina viene
    # dimenticato da Streamlit, la scelta no)
    st.session_state[WIDGET_CAMPIONATO] = corrente
    st.segmented_control(
        "Campionato",
        componenti.FILTRO_CAMPIONATI,
        key=WIDGET_CAMPIONATO,
        on_change=_scegli_campionato,
        required=True,
        label_visibility="collapsed",
    )
    slug = slug_campionato(corrente)
    if st.query_params.get(PARAMETRO_CAMPIONATO) != slug:
        st.query_params[PARAMETRO_CAMPIONATO] = slug
    return corrente
