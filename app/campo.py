"""Campo con le formazioni (pagina Dettaglio) disegnato in SVG inline, senza JavaScript.

Su schermi larghi il campo è orizzontale (casa a sinistra, trasferta a destra) con le
panchine sotto le due metà; su telefono è verticale (casa sotto, trasferta sopra) con la
panchina della trasferta sopra e quella di casa sotto. Ogni giocatore (stile fantacalcio):
tondo nei colori della squadra con la foto del giocatore, numero nel bollino, cognome in
un'etichetta scura sotto, bordo per il rischio di giallo (verde < 15%, giallo 15-30%,
rosso > 30%); se la foto non c'è o non si carica resta il numero al centro del tondo.

Toccare un giocatore porta alla sua scheda nella classifica (ancora `#cand-<id>`); il CSS
`:has(:target)` evidenzia lui e il suo avversario diretto con una linea tratteggiata.
Tutti i testi e gli URL hanno l'escape."""
from __future__ import annotations

import re
from html import escape

import componenti
import stile
from componenti_campo import DatiCampo, GiocatoreCampo, SquadraCampo, livello_rischio

LARGO, ALTO = 1050, 680  # campo orizzontale (105 x 68 m); il verticale è ruotato
MARGINE = 46
X_RIGA = {1: 66, 2: 155, 3: 255, 4: 350, 5: 448}  # distanza dalla propria porta per riga
GIALLO_DUELLO = "#F5C518"
COLORI_RISCHIO = {"verde": "#3DD68C", "giallo": "#F5C518", "rosso": "#E5484D"}
MAGLIA = (
    "M-14,-20 L-25,-14 L-31,-1 L-21,4 L-18,-2 L-18,22 L18,22 L18,-2 L21,4 L31,-1 "
    "L25,-14 L14,-20 Q0,-10 -14,-20 Z"
)
MAX_COGNOME = 10
SCALA_GIOCATORE = 1.2
URL_SICURO = re.compile(r"https://[A-Za-z0-9./_-]+")  # nel CSS di uno style: niente apici


def coordinate(riga: int, colonna: int, in_riga: int, casa: bool, verticale: bool) -> tuple[float, float]:
    """Centro della maglietta. La colonna 1 è la destra del giocatore: la casa attacca verso
    destra (orizzontale) o verso l'alto (verticale), la trasferta al contrario, così i due
    lati si specchiano e il terzino destro sta davanti all'esterno sinistro avversario."""
    profondita = X_RIGA.get(riga, X_RIGA[3])
    n = max(in_riga, 1)
    larghezza = ALTO - 2 * MARGINE  # il lato corto del campo, in entrambi i versi
    if casa:
        trasversale = MARGINE + larghezza * (n - colonna + 0.5) / n
    else:
        trasversale = MARGINE + larghezza * (colonna - 0.5) / n
    if not verticale:
        x = profondita if casa else LARGO - profondita
        return x, trasversale
    y = LARGO - profondita if casa else profondita
    return trasversale, y


def colori_squadre(casa: SquadraCampo, trasferta: SquadraCampo) -> tuple[str, str]:
    """Colori delle magliette: quelli ESPN, altrimenti ricavati dal nome; se le due squadre
    si somigliano troppo la trasferta usa il colore alternativo."""
    c = casa.colore or stile._colore_stemma(casa.nome)
    t = trasferta.colore or stile._colore_stemma(trasferta.nome)
    if distanza_colori(c, t) < SOGLIA_SIMILI and trasferta.colore_alt:
        t = trasferta.colore_alt
    return c, t


SOGLIA_SIMILI = 110  # distanza RGB sotto la quale due magliette si confondono


def distanza_colori(a: str, b: str) -> float:
    """Distanza euclidea fra due colori "#RRGGBB" (0 = uguali, ~441 = bianco e nero):
    conta la tinta, non solo la luminosità (rosso e blu scuri non si confondono)."""
    ra, rb = (tuple(int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)) for c in (a, b))
    return sum((x - y) ** 2 for x, y in zip(ra, rb)) ** 0.5


def colore_numero(colore: str) -> str:
    return "#FFFFFF" if stile.contrasto(colore, "#FFFFFF") >= stile.contrasto(colore, "#15171C") else "#15171C"


def _testo_corto(testo: str, massimo: int = MAX_COGNOME) -> str:
    return testo if len(testo) <= massimo else testo[: massimo - 1] + "…"


def _titolo(g: GiocatoreCampo) -> str:
    numero = f" · n. {g.numero}" if g.numero is not None else ""
    prob = f" · giallo {componenti.percentuale(g.probabilita)}" if g.probabilita is not None else ""
    return f"{g.nome}{numero}{prob}"


# omino generico (testa e spalle) nel tondo quando non ci sono né foto né numero
SAGOMA = (
    '<g class="cr-sagoma" fill="rgba(255,255,255,.55)"><circle cx="0" cy="-7" r="9"/>'
    '<path d="M-17,19 Q-17,4 0,4 Q17,4 17,19 Z"/></g>'
)
RAGGIO = 25  # tondo del giocatore (stile fantacalcio): foto sopra il colore della squadra


def _larghezza_nome(testo: str) -> float:
    """Larghezza dell'etichetta del nome (font 16 grassetto, stima per carattere)."""
    return 9.6 * len(testo) + 16


def _maglia(g: GiocatoreCampo, colore: str, clip: str) -> str:
    """Tondo del giocatore stile fantacalcio, centro in 0,0: fondo nei colori della squadra,
    foto scontornata sopra (se c'è), bordo del rischio, numero nel bollino; senza foto il
    numero sta al centro del tondo."""
    livello = livello_rischio(g.probabilita)
    bordo = (
        f'stroke="{COLORI_RISCHIO[livello]}" stroke-width="4"' if livello in COLORI_RISCHIO
        else 'stroke="rgba(255,255,255,.75)" stroke-width="2.5"'
    )
    url = componenti.url_https(g.volto)
    ha_foto = bool(url and URL_SICURO.fullmatch(url))
    numero = "" if ha_foto else SAGOMA
    if g.numero is not None and not ha_foto:
        numero = (
            f'<text class="cr-numero" x="0" y="8" text-anchor="middle" font-size="22" '
            f'fill="{colore_numero(colore)}">{escape(str(g.numero))}</text>'
        )
    volto = bollino = ""
    if ha_foto:
        # sfondo CSS e non <image>: se la foto non esiste il browser non disegna niente
        # (un <image> SVG rotto mostra l'icona dell'immagine mancante)
        volto = (
            f'<foreignObject x="-{RAGGIO - 2}" y="-{RAGGIO - 2}" width="{2 * RAGGIO - 4}" '
            f'height="{2 * RAGGIO - 4}"><div xmlns="http://www.w3.org/1999/xhtml" class="cr-volto" '
            f"style=\"background-color:{escape(colore)};background-image:url('{escape(url)}')\">"
            "</div></foreignObject>"
        )
        if g.numero is not None:
            bollino = (
                f'<g class="cr-bollino"><circle cx="19" cy="-19" r="10" fill="{colore}" '
                'stroke="#FFFFFF" stroke-width="2"/>'
                f'<text x="19" y="-14.5" text-anchor="middle" font-size="12.5" '
                f'fill="{colore_numero(colore)}">{escape(str(g.numero))}</text></g>'
            )
    # alone bianco sotto il bordo del rischio: resta visibile anche su un fondo dello stesso colore
    alone = (
        f'<circle r="{RAGGIO}" fill="none" stroke="rgba(255,255,255,.92)" stroke-width="9"/>'
        if livello in COLORI_RISCHIO else ""
    )
    tondo = f'<circle class="cr-maglia" r="{RAGGIO}" fill="{colore}" {bordo}/>'
    # con la foto il numero è nel bollino; la foto ha sotto il colore della squadra, così una
    # foto scontornata non lascia vedere niente dietro (se non si carica resta il tondo pieno)
    return f"{alone}{tondo}{numero}{volto}{bollino}"


def _giocatore(g: GiocatoreCampo, x: float, y: float, colore: str, clip: str) -> str:
    gruppo = (
        f'<g class="cr-pl cr-pl-{g.id} cr-rischio--{livello_rischio(g.probabilita)}" '
        f'transform="translate({x:.0f},{y:.0f}) scale({SCALA_GIOCATORE})">'
        f"<title>{escape(_titolo(g))}</title>"
        f"{_maglia(g, colore, clip)}{_etichetta(g.cognome)}</g>"
    )
    # solo i candidati hanno una scheda nella classifica a cui portare
    return f'<a href="#cand-{g.id}">{gruppo}</a>' if g.probabilita is not None else gruppo


def _etichetta(cognome: str) -> str:
    """Nome sotto il tondo in un'etichetta scura arrotondata, come nelle app di fantacalcio."""
    testo = _testo_corto(cognome)
    w = _larghezza_nome(testo)
    return (
        f'<rect class="cr-etichetta" x="{-w / 2:.1f}" y="30" width="{w:.1f}" height="22" rx="11" '
        'fill="rgba(12,14,18,.86)" stroke="rgba(255,255,255,.18)" stroke-width="1"/>'
        f'<text class="cr-nome-pl" x="0" y="46" text-anchor="middle" font-size="16">'
        f"{escape(testo)}</text>"
    )


def _prato(verticale: bool) -> str:
    """Erba a strisce, linee bianche, aree, cerchio di centrocampo e dischetti."""
    w, h = (ALTO, LARGO) if verticale else (LARGO, ALTO)
    strisce = []
    n = 10
    for i in range(n):
        colore = "#2F7D34" if i % 2 == 0 else "#358C3A"
        if verticale:
            strisce.append(f'<rect x="0" y="{i * h / n:.0f}" width="{w}" height="{h / n + 1:.0f}" fill="{colore}"/>')
        else:
            strisce.append(f'<rect x="{i * w / n:.0f}" y="0" width="{w / n + 1:.0f}" height="{h}" fill="{colore}"/>')
    linee = 'fill="none" stroke="rgba(255,255,255,.82)" stroke-width="3"'

    def r(x, y, lx, ly):  # rettangolo nel sistema orizzontale, ruotato se verticale
        if verticale:
            x, y, lx, ly = y, LARGO - x - lx, ly, lx
        return f'<rect x="{x:.0f}" y="{y:.0f}" width="{lx:.0f}" height="{ly:.0f}" {linee}/>'

    def punto(x, y, raggio=4):
        if verticale:
            x, y = y, LARGO - x
        return f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{raggio}" fill="rgba(255,255,255,.82)"/>'

    meta = (
        f'<line x1="0" y1="{h / 2:.0f}" x2="{w}" y2="{h / 2:.0f}" {linee}/>' if verticale
        else f'<line x1="{w / 2:.0f}" y1="0" x2="{w / 2:.0f}" y2="{h}" {linee}/>'
    )
    centro_x, centro_y = w / 2, h / 2
    disegni = [
        r(8, 8, LARGO - 16, ALTO - 16),
        meta,
        f'<circle cx="{centro_x:.0f}" cy="{centro_y:.0f}" r="91" {linee}/>',
        punto(LARGO / 2, ALTO / 2),
        # aree di rigore (16,5 x 40,3 m) e piccole aree (5,5 x 18,3 m)
        r(8, ALTO / 2 - 201, 165, 402), r(LARGO - 8 - 165, ALTO / 2 - 201, 165, 402),
        r(8, ALTO / 2 - 91, 55, 182), r(LARGO - 8 - 55, ALTO / 2 - 91, 55, 182),
        punto(118, ALTO / 2), punto(LARGO - 118, ALTO / 2),
    ]
    return "".join(strisce) + "".join(disegni)


def _svg(dati: DatiCampo, verticale: bool, colori: tuple[str, str]) -> str:
    w, h = (ALTO, LARGO) if verticale else (LARGO, ALTO)
    clip = "cr-testa-v" if verticale else "cr-testa-o"
    posizioni: dict[int, tuple[float, float]] = {}
    giocatori = []
    for squadra, casa, colore in ((dati.casa, True, colori[0]), (dati.trasferta, False, colori[1])):
        for g in squadra.titolari:
            x, y = coordinate(g.riga, g.colonna, g.in_riga, casa, verticale)
            posizioni[g.id] = (x, y)
            giocatori.append(_giocatore(g, x, y, colore, clip))
    linee = []
    for squadra in (dati.casa, dati.trasferta):
        for g in squadra.titolari:
            if g.avversario_id in posizioni:
                (x1, y1), (x2, y2) = posizioni[g.id], posizioni[g.avversario_id]
                linee.append(
                    f'<line class="cr-duello cr-dl-{g.id}" x1="{x1:.0f}" y1="{y1:.0f}" '
                    f'x2="{x2:.0f}" y2="{y2:.0f}" stroke="{GIALLO_DUELLO}" stroke-width="4" '
                    'stroke-dasharray="12 9" stroke-linecap="round"/>'
                )
    return (
        f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Formazioni in campo: {escape(dati.casa.nome)} contro {escape(dati.trasferta.nome)}">'
        f"{_prato(verticale)}{''.join(linee)}{''.join(giocatori)}</svg>"
    )


def _gettone(g: GiocatoreCampo, colore: str, clip: str) -> str:
    """Panchinaro: maglietta (e volto), numero e nome; bordo del rischio se è un subentrante."""
    numero = f"{g.numero} " if g.numero is not None else ""
    # i probabili subentranti portano alla loro scheda; gli altri panchinari no
    tag, link = ("a", f' href="#cand-{g.id}"') if g.probabilita is not None else ("span", "")
    return (
        f'<{tag} class="cr-panca-g cr-rischio--{livello_rischio(g.probabilita)}"{link} '
        f'title="{escape(_titolo(g))}">'
        f'<svg viewBox="-31 -31 62 62" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        f"{_maglia(g, colore, clip)}</svg>"
        f"<span>{escape(numero + g.cognome)}</span></{tag}>"
    )


def _panca(squadra: SquadraCampo, colore: str, ufficiali: bool, suffisso: str) -> str:
    titolo = "Panchina" if (ufficiali or squadra.ufficiale) else "Probabili subentranti"
    if squadra.panchina:
        gettoni = "".join(
            _gettone(g, colore, f"cr-tp-{suffisso}-{g.id}") for g in squadra.panchina
        )
    else:
        gettoni = '<span class="cr-panca-vuota">Nessuno</span>'
    return (
        f'<div><div class="cr-panca-titolo">{escape(titolo)} · {escape(squadra.nome)}</div>'
        f'<div class="cr-panca">{gettoni}</div></div>'
    )


def _testa(squadra: SquadraCampo, a_destra: bool = False) -> str:
    modulo = f'<b class="cr-campo-modulo">{escape(squadra.modulo)}</b>' if squadra.modulo else ""
    nome = f"<span>{escape(squadra.nome)}</span>"
    pezzi = [stile.stemma(squadra.nome, squadra.logo, "mini"), nome, modulo]
    if a_destra:
        pezzi.reverse()
    return f'<div class="cr-campo-sq">{"".join(pezzi)}</div>'


def legenda() -> str:
    voci = (("verde", "sotto il 15%"), ("giallo", "15–30%"), ("rosso", "oltre il 30%"))
    return '<div class="cr-legenda">' + "".join(
        f'<span><i style="border-color:{COLORI_RISCHIO[l]}"></i>{escape(t)}</span>' for l, t in voci
    ) + "<span>Tocca un giocatore per la sua scheda</span></div>"


def campo_html(dati: DatiCampo) -> str:
    """Il riquadro del campo (orizzontale e verticale: il CSS mostra quello giusto)."""
    colori = colori_squadre(dati.casa, dati.trasferta)
    if dati.ufficiali:
        tipo = "Formazioni ufficiali"
    elif dati.casa.ufficiale or dati.trasferta.ufficiale:
        uff, prob = (dati.casa, dati.trasferta) if dati.casa.ufficiale else (dati.trasferta, dati.casa)
        tipo = f"Ufficiale: {uff.nome} · probabile: {prob.nome}"
    else:
        tipo = "Formazioni probabili (calcolate)"
    orizzontale = (
        '<div class="cr-campo-o">'
        f'<div class="cr-campo-testa">{_testa(dati.casa)}{_testa(dati.trasferta, True)}</div>'
        f"{_svg(dati, False, colori)}"
        '<div class="cr-panche">'
        f"{_panca(dati.casa, colori[0], dati.ufficiali, 'oc')}"
        f"{_panca(dati.trasferta, colori[1], dati.ufficiali, 'ot')}</div></div>"
    )
    verticale = (
        '<div class="cr-campo-v">'
        f'<div class="cr-panche">{_panca(dati.trasferta, colori[1], dati.ufficiali, "vt")}</div>'
        f'<div class="cr-campo-testa">{_testa(dati.trasferta)}</div>'
        f"{_svg(dati, True, colori)}"
        f'<div class="cr-campo-testa">{_testa(dati.casa)}</div>'
        f'<div class="cr-panche">{_panca(dati.casa, colori[0], dati.ufficiali, "vc")}</div></div>'
    )
    return (
        f'<div class="cr-campo"><div class="cr-campo-tipo">{escape(tipo)}</div>'
        f"{orizzontale}{verticale}{legenda()}</div>"
    )


def campo_css(dati: DatiCampo) -> str:
    """Regole dell'evidenza: con la scheda `#cand-<id>` aperta (`:target`) il giocatore e il
    suo avversario diretto restano accesi, la linea tratteggiata li unisce, gli altri sbiadiscono."""
    regole = []
    tutti = [*dati.casa.titolari, *dati.trasferta.titolari, *dati.casa.panchina, *dati.trasferta.panchina]
    for g in tutti:
        bersaglio = f"body:has(#cand-{g.id}:target)"
        accesi = [g.id] + ([g.avversario_id] if g.avversario_id else [])
        esclusi = "".join(f":not(.cr-pl-{i})" for i in accesi)
        regole.append(f"{bersaglio} .cr-pl{esclusi} {{ opacity: .4; }}")
        regole.append(
            ", ".join(f"{bersaglio} .cr-pl-{i} .cr-maglia" for i in accesi)
            + f" {{ stroke: {GIALLO_DUELLO}; stroke-width: 6; }}"
        )
        if g.avversario_id:
            regole.append(f"{bersaglio} .cr-dl-{g.id} {{ display: inline; }}")
    return "\n".join(regole)
