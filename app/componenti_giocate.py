"""Logica delle pagine Giocate e Impostazioni, senza dipendenze da Streamlit:
le pagine si limitano a mostrare quello che restituiscono queste funzioni."""
from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

import componenti
from ammonizioni.config import (
    NOMI_CAMPIONATI,
    SERIE_A,
    campionato_di,
)
from ammonizioni.db.modelli import Giocata, Giocatore, Partita, Squadra
from ammonizioni.giocate.registro import aggiungi_giocata, statistiche_per_fonte
from ammonizioni.motore.classifica import converti_quota
from ammonizioni.motore.pesi import Pesi, valida_pesi
from ammonizioni.motore.tipi import decimale

GIORNI_FINESTRA = 7
FONTI = ("io", "modello", "tipster")
FONTE_TIPSTER = "tipster"
ESITI = {
    "in_attesa": "in attesa",
    "vinta": "vinta",
    "persa": "persa",
    "rimborsata": "rimborsata",
}
COLONNE_REGISTRO = ("Data", "Partita", "Giocatore", "Fonte", "Quota", "Puntata", "Esito")
COLONNE_STATISTICHE = (
    "Fonte", "Giocate", "Successo", "Prob. implicita media", "Profitto", "Rendimento",
)
LUNGHEZZA_TUPLE = {"pesi_stagioni": 3, "limiti_fattore": 2, "limiti_probabilita": 2}
CHIAVE_MASCHERA = "••••"


# ---------------------------------------------------------------- formattazione

def euro(valore: float) -> str:
    """"10,00 €" con la virgola decimale."""
    return f"{decimale(valore, 2)} €"


def maschera_chiave(chiave: str | None) -> str:
    """Solo "••••" e gli ultimi 4 caratteri; chiavi cortissime non vengono rivelate."""
    if not chiave:
        return "non impostata"
    if len(chiave) <= 4:
        return CHIAVE_MASCHERA
    return CHIAVE_MASCHERA + chiave[-4:]


# ---------------------------------------------------------------- pagina Giocate

def _nomi_squadre(s: Session) -> dict[int, str]:
    return {sq.id: sq.nome for sq in s.execute(select(Squadra)).scalars()}


def partite_selezionabili(
    s: Session,
    ora: datetime,
    giorni: int = GIORNI_FINESTRA,
    includi: int | None = None,
    campionati: tuple[int, ...] = (SERIE_A,),
) -> list[tuple[int, str]]:
    """Partite dei campionati dati (la Serie A se non indicati) degli ultimi e dei prossimi
    `giorni` giorni, in ordine di data (id, etichetta; con più campionati l'etichetta comincia
    col nome del campionato). `includi` aggiunge una partita richiesta dall'URL anche se
    fuori finestra."""
    partite = list(
        s.execute(
            select(Partita)
            .where(
                Partita.competizione_id.in_(campionati),
                Partita.data_utc >= ora - timedelta(days=giorni),
                Partita.data_utc <= ora + timedelta(days=giorni),
            )
            .order_by(Partita.data_utc)
        ).scalars()
    )
    if includi is not None and all(p.id != includi for p in partite):
        extra = s.get(Partita, includi)
        if extra is not None:
            partite = sorted([*partite, extra], key=lambda p: p.data_utc)
    nomi = _nomi_squadre(s)
    return [
        (
            p.id,
            (f"{NOMI_CAMPIONATI.get(p.competizione_id, '')} · " if len(campionati) > 1 else "")
            + f"{componenti.data_breve(p.data_utc)} {nomi.get(p.casa_id, p.casa_id)} – "
            f"{nomi.get(p.trasferta_id, p.trasferta_id)}",
        )
        for p in partite
    ]


def giocatori_partita(s: Session, partita_id: int) -> list[tuple[int, str]]:
    """Giocatori delle due squadre della partita (id, "Nome (Squadra)"), per nome."""
    partita = s.get(Partita, partita_id)
    if partita is None:
        return []
    nomi = _nomi_squadre(s)
    trovati: dict[int, str] = {}
    for sq in (partita.casa_id, partita.trasferta_id):
        for gid, nome in componenti.giocatori_squadra(s, sq, []):
            trovati.setdefault(gid, f"{nome} ({nomi.get(sq, sq)})")
    return sorted(trovati.items(), key=lambda r: r[1])


def converti_puntata(testo: str) -> float:
    """"10,50" o "10.50" -> 10.5; deve essere un numero maggiore di 0."""
    errore = ValueError("Puntata non valida: deve essere un numero maggiore di 0")
    try:
        puntata = float(str(testo).strip().replace(",", "."))
    except ValueError:
        raise errore from None
    if not math.isfinite(puntata) or puntata <= 0:
        raise errore
    return puntata


def nome_fonte(scelta: str, tipster: str) -> str:
    """Fonte da salvare: "io", "modello" oppure il nome del tipster."""
    if scelta != FONTE_TIPSTER:
        return scelta
    nome = tipster.strip()
    if not nome:
        raise ValueError("Inserisci il nome del tipster")
    return nome


def registra_giocata(
    s: Session,
    giorno: date,
    partita_id: int,
    giocatore_id: int,
    scelta_fonte: str,
    tipster: str,
    quota_testo: str,
    puntata_testo: str,
) -> Giocata:
    """Valida i testi del form e registra la giocata. ValueError con messaggio italiano."""
    fonte = nome_fonte(scelta_fonte, tipster)
    quota = converti_quota(quota_testo)
    puntata = converti_puntata(puntata_testo)
    return aggiungi_giocata(s, partita_id, giocatore_id, fonte, quota, puntata, giorno)


# ---------------------------------------------------------------- riquadro "Scommetti"

FONTE_MIA = "io"


@dataclass(frozen=True)
class Valutazione:
    """Quota del bookmaker confrontata con il modello."""
    quota: float
    prob_bookmaker: float  # 1 / quota
    prob_modello: float
    valore: float  # prob_modello - prob_bookmaker
    conviene: bool

    @property
    def testo(self) -> str:
        """"Conviene · valore +8%" oppure "Non conviene · −5%" (meno tipografico)."""
        punti = round(self.valore * 100)
        if self.conviene:
            return f"Conviene · valore +{punti}%"
        return f"Non conviene · {'−' if punti < 0 else ''}{abs(punti)}%"


def valuta_quota(probabilita: float, quota: float) -> Valutazione:
    implicita = 1 / quota
    valore = probabilita - implicita
    return Valutazione(quota, implicita, probabilita, valore, conviene=round(valore * 100) > 0)


def testo_giocata(puntata: float, quota: float) -> str:
    """"Giocata registrata: 10 € a 4,50"."""
    importo = f"{puntata:g}".replace(".", ",") if float(puntata).is_integer() else decimale(puntata, 2)
    return f"Giocata registrata: {importo} € a {decimale(quota, 2)}"


def registra_scommessa(
    s: Session, partita_id: int, giocatore_id: int, quota: float, puntata_testo: str, giorno: date
) -> Giocata:
    """"L'ho giocata": fonte "io", data di oggi, quota e puntata. Una sola giocata per
    giocatore e partita da qui: il doppione è rifiutato (ValueError con messaggio)."""
    puntata = converti_puntata(puntata_testo)
    esiste = s.scalars(
        select(Giocata.id).where(
            Giocata.partita_id == partita_id, Giocata.giocatore_id == giocatore_id
        ).limit(1)
    ).first()
    if esiste is not None:
        raise ValueError("Hai già registrato una giocata su questo giocatore in questa partita")
    return aggiungi_giocata(s, partita_id, giocatore_id, FONTE_MIA, quota, puntata, giorno)


def partite_con_giocate(s: Session, campionati: tuple[int, ...] | None) -> set[int] | None:
    """Id delle partite con giocate che appartengono ai campionati dati: il campionato, la sua
    coppa nazionale, le coppe europee con una squadra di quel campionato nella stagione.
    `None` (nessun filtro) se `campionati` è None."""
    if campionati is None:
        return None
    squadre: dict[tuple[int, int], set[int]] = {}

    def squadre_di(campionato: int, stagione: int) -> set[int]:
        if (campionato, stagione) not in squadre:
            righe = s.execute(
                select(Partita.casa_id, Partita.trasferta_id).where(
                    Partita.competizione_id == campionato, Partita.stagione == stagione
                )
            ).all()
            squadre[(campionato, stagione)] = {i for riga in righe for i in riga}
        return squadre[(campionato, stagione)]

    ids = set()
    partite = s.scalars(
        select(Partita).where(Partita.id.in_(select(Giocata.partita_id).distinct()))
    ).all()
    for p in partite:
        proprio = campionato_di(p.competizione_id)
        if proprio is not None:
            if proprio in campionati:
                ids.add(p.id)
        elif any(
            {p.casa_id, p.trasferta_id} & squadre_di(c, p.stagione) for c in campionati
        ):
            ids.add(p.id)
    return ids


def righe_registro(
    s: Session, campionati: tuple[int, ...] | None = (SERIE_A,)
) -> list[dict[str, str]]:
    """Giocate registrate, la più recente per prima. Solo quelle sulle partite dei campionati
    dati (la Serie A se non indicati), delle loro coppe nazionali e delle coppe europee con
    squadre di quei campionati; `None` = tutte."""
    nomi = _nomi_squadre(s)
    interrogazione = (
        select(Giocata, Partita, Giocatore)
        .join(Partita, Partita.id == Giocata.partita_id)
        .join(Giocatore, Giocatore.id == Giocata.giocatore_id)
        .order_by(Giocata.data.desc(), Giocata.id.desc())
    )
    ids = partite_con_giocate(s, campionati)
    if ids is not None:
        interrogazione = interrogazione.where(Partita.id.in_(ids))
    righe = s.execute(interrogazione).all()
    return [
        {
            "Data": f"{g.data:%d/%m/%Y}",
            "Partita": f"{nomi.get(p.casa_id, p.casa_id)} – {nomi.get(p.trasferta_id, p.trasferta_id)}",
            "Giocatore": gioc.nome,
            "Fonte": g.fonte,
            "Quota": decimale(g.quota, 2),
            "Puntata": euro(g.puntata),
            "Esito": ESITI.get(g.esito, g.esito),
        }
        for g, p, gioc in righe
    ]


def righe_statistiche(
    s: Session, campionati: tuple[int, ...] | None = (SERIE_A,)
) -> list[dict[str, object]]:
    """Statistiche per fonte, con lo stesso filtro del registro (`None` = tutte)."""
    return [
        {
            "Fonte": st.fonte,
            "Giocate": st.giocate,
            "Successo": componenti.percentuale(st.percentuale_successo),
            "Prob. implicita media": componenti.percentuale(st.prob_implicita_media),
            "Profitto": euro(st.profitto),
            "Rendimento": componenti.percentuale(st.rendimento),
        }
        for st in statistiche_per_fonte(s, partite_con_giocate(s, campionati))
    ]


# ---------------------------------------------------------------- pesi

def campi_pesi() -> tuple[list[tuple[str, type]], list[str]]:
    """([(nome, int | float)] per i campi scalari, [nomi] dei campi tupla) di Pesi."""
    default = Pesi()
    scalari, tuple_ = [], []
    for campo in fields(Pesi):
        valore = getattr(default, campo.name)
        if isinstance(valore, tuple):
            tuple_.append(campo.name)
        else:
            scalari.append((campo.name, int if isinstance(valore, int) else float))
    return scalari, tuple_


def tupla_da_testo(testo: str, tipo: type, lunghezza: int | None = None) -> tuple:
    """"0.6, 0.3, 0.1" -> (0.6, 0.3, 0.1). Con ";" come separatore si può usare la virgola
    decimale ("0,6; 0,3; 0,1"). ValueError con messaggio italiano se non valido."""
    if ";" in testo:
        pezzi = [p.strip().replace(",", ".") for p in testo.split(";")]
    else:
        pezzi = [p.strip() for p in testo.split(",")]
    errore = ValueError(
        "usa numeri " + ("interi " if tipo is int else "") + "separati da virgole (es. "
        + ("4, 9, 13" if tipo is int else "0.6, 0.3, 0.1") + ")"
    )
    valori = []
    for p in pezzi:
        try:
            v = tipo(p)
        except ValueError:
            raise errore from None
        if not math.isfinite(v):
            raise errore
        valori.append(v)
    if lunghezza is not None and len(valori) != lunghezza:
        raise ValueError(f"servono esattamente {lunghezza} valori")
    return tuple(valori)


def testo_tupla(valori: tuple) -> str:
    return ", ".join(str(v) for v in valori)


def costruisci_pesi(scalari: dict[str, float], testi: dict[str, str]) -> Pesi:
    """Pesi dai valori del form. ValueError con messaggio italiano (e il nome del campo)."""
    default = Pesi()
    valori: dict[str, object] = {}
    for nome, tipo in campi_pesi()[0]:
        valori[nome] = tipo(scalari[nome])
        if valori[nome] < 0:
            raise ValueError(f"{nome}: il valore non può essere negativo")
    for nome, testo in testi.items():
        tipo = int if all(isinstance(v, int) for v in getattr(default, nome)) else float
        try:
            valori[nome] = tupla_da_testo(testo, tipo, LUNGHEZZA_TUPLE.get(nome))
        except ValueError as errore:
            raise ValueError(f"{nome}: {errore}") from None
        if nome.startswith("limiti_") and valori[nome][0] >= valori[nome][1]:
            raise ValueError(f"{nome}: il primo valore deve essere minore del secondo")
        if nome == "limiti_probabilita" and not 0 < valori[nome][0] < valori[nome][1] < 1:
            raise ValueError(f"{nome}: servono due probabilità con 0 < minimo < massimo < 1")
    pesi = replace(default, **valori)
    valida_pesi(pesi)  # i valori che bloccherebbero il motore
    return pesi
