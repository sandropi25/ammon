"""Logica delle pagine Giocate e Impostazioni, senza dipendenze da Streamlit:
le pagine si limitano a mostrare quello che restituiscono queste funzioni."""
from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

import componenti
from ammonizioni.config import (
    CAMPIONATI,
    COPPE_NAZIONALI,
    NOMI_CAMPIONATI,
    SERIE_A,
    STAGIONE_CORRENTE,
)
from ammonizioni.db.modelli import Giocata, Giocatore, ListaManuale, Partita, Squadra
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


def righe_registro(
    s: Session, campionati: tuple[int, ...] | None = (SERIE_A,)
) -> list[dict[str, str]]:
    """Giocate registrate, la più recente per prima. Solo quelle sulle partite dei campionati
    dati e delle loro coppe nazionali (la Serie A se non indicati); `None` = tutte, comprese
    le coppe europee."""
    nomi = _nomi_squadre(s)
    interrogazione = (
        select(Giocata, Partita, Giocatore)
        .join(Partita, Partita.id == Giocata.partita_id)
        .join(Giocatore, Giocatore.id == Giocata.giocatore_id)
        .order_by(Giocata.data.desc(), Giocata.id.desc())
    )
    if campionati is not None:
        competizioni = {*campionati, *(COPPE_NAZIONALI[c] for c in campionati if c in COPPE_NAZIONALI)}
        interrogazione = interrogazione.where(Partita.competizione_id.in_(competizioni))
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


def righe_statistiche(s: Session) -> list[dict[str, object]]:
    return [
        {
            "Fonte": st.fonte,
            "Giocate": st.giocate,
            "Successo": componenti.percentuale(st.percentuale_successo),
            "Prob. implicita media": componenti.percentuale(st.prob_implicita_media),
            "Profitto": euro(st.profitto),
            "Rendimento": componenti.percentuale(st.rendimento),
        }
        for st in statistiche_per_fonte(s)
    ]


# ---------------------------------------------------------------- liste manuali

@dataclass(frozen=True)
class VoceLista:
    id: int
    testo: str


def squadre_campionati(s: Session) -> list[tuple[int, str]]:
    """Squadre dei campionati nella stagione corrente: (id, "Nome (Campionato)"), la Serie A
    per prima, in ordine alfabetico dentro ciascun campionato."""
    risultato: list[tuple[int, str]] = []
    for campionato in CAMPIONATI:
        partite = select(Partita.casa_id, Partita.trasferta_id).where(
            Partita.competizione_id == campionato, Partita.stagione == STAGIONE_CORRENTE
        )
        ids = {i for coppia in s.execute(partite).all() for i in coppia}
        righe = s.execute(select(Squadra.id, Squadra.nome).where(Squadra.id.in_(ids))).all()
        risultato.extend(
            (i, f"{n} ({NOMI_CAMPIONATI[campionato]})") for i, n in sorted(righe, key=lambda r: r[1])
        )
    return risultato


def voci_lista(s: Session, tipo: str) -> list[VoceLista]:
    nomi = _nomi_squadre(s)
    voci = []
    for r in s.execute(
        select(ListaManuale).where(ListaManuale.tipo == tipo).order_by(ListaManuale.id)
    ).scalars():
        testo = nomi.get(r.squadra_a_id, str(r.squadra_a_id))
        if r.squadra_b_id is not None:
            testo += f" – {nomi.get(r.squadra_b_id, str(r.squadra_b_id))}"
        voci.append(VoceLista(r.id, testo))
    return voci


def aggiungi_derby(s: Session, squadra_a: int, squadra_b: int) -> None:
    """Coppia di squadre in rivalità, salvata una volta sola a prescindere dall'ordine."""
    if squadra_a == squadra_b:
        raise ValueError("Scegli due squadre diverse")
    a, b = sorted((squadra_a, squadra_b))
    esiste = s.execute(
        select(ListaManuale.id).where(
            ListaManuale.tipo == "derby",
            or_(
                (ListaManuale.squadra_a_id == a) & (ListaManuale.squadra_b_id == b),
                (ListaManuale.squadra_a_id == b) & (ListaManuale.squadra_b_id == a),
            ),
        )
    ).first()
    if esiste is not None:
        raise ValueError("Derby già presente nell'elenco")
    s.add(ListaManuale(tipo="derby", squadra_a_id=a, squadra_b_id=b))
    s.flush()


def aggiungi_campo_caldo(s: Session, squadra: int) -> None:
    esiste = s.execute(
        select(ListaManuale.id).where(
            ListaManuale.tipo == "campo_caldo", ListaManuale.squadra_a_id == squadra
        )
    ).first()
    if esiste is not None:
        raise ValueError("Campo caldo già presente nell'elenco")
    s.add(ListaManuale(tipo="campo_caldo", squadra_a_id=squadra, squadra_b_id=None))
    s.flush()


def rimuovi_voce(s: Session, voce_id: int) -> None:
    riga = s.get(ListaManuale, voce_id)
    if riga is not None:
        s.delete(riga)
        s.flush()


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
