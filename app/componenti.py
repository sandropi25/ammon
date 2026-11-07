"""Logica dell'app (caricamento dati, formattazione, scritture) senza dipendenze da Streamlit:
le pagine si limitano a mostrare quello che restituiscono queste funzioni."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ammonizioni.caricamento.formazioni import riepilogo_cambi
from ammonizioni.config import (
    CAMPIONATI,
    NOMI_CAMPIONATI,
    SERIE_A,
    SOGLIA_CARTELLINI_ATTESI,
    STATI_FINITI,
)
from ammonizioni.db import repo
from ammonizioni.db.modelli import (
    Arbitro,
    DuelloManuale,
    Formazione,
    Giocata,
    Giocatore,
    Partita,
    Presenza,
    Segnalazione,
    Squadra,
    UltimoAggiornamento,
)
from ammonizioni.motore import affidabilita, modello
from ammonizioni.motore.classifica import converti_quota
from ammonizioni.motore.dati import carica_dati, carica_dati_calda
from ammonizioni.motore.fattori.arbitro import fattore_arbitro
from ammonizioni.motore.pesi import carica_pesi
from ammonizioni.motore.tipi import Candidato, DatiPartita, decimale

ROMA = ZoneInfo("Europe/Rome")
GIORNI = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")
GIORNI_ESTESI = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
MESI = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)
GIORNI_PROSSIME = 7
SOGLIA_PARTITA_CALDA = 1.1
FONTI_NON_TIPSTER = ("io", "modello")
COLONNE_TABELLA = (
    "Giocatore", "Squadra", "Probabilità", "Motivazioni", "Affidabilità",
    "Quota", "Implicita", "Valore", "Tipster",
)
COLONNE_SUBENTRANTI = (
    "Giocatore", "Squadra", "Ruolo", "Probabilità", "Entra", "Minuti", "Al posto di",
    "Gialli 90'", "Falli 90'", "Sopra la media",
)


# ---------------------------------------------------------------- formattazione

def data_italiana(dt_utc: datetime) -> str:
    """"sab 08/11 20:45" in Europe/Rome."""
    locale = dt_utc.astimezone(ROMA)
    return f"{GIORNI[locale.weekday()]} {locale:%d/%m %H:%M}"


def data_breve(dt_utc: datetime) -> str:
    """"08/11 20:45" in Europe/Rome."""
    return f"{dt_utc.astimezone(ROMA):%d/%m %H:%M}"


def percentuale(p: float) -> str:
    return f"{round(p * 100)}%"


# livello di affidabilità -> (pallino, nome, tipo di badge)
LIVELLI_AFFIDABILITA = {
    "alta": ("🟢", "Alta", "verde"),
    "media": ("🟡", "Media", "giallo"),
    "bassa": ("🔴", "Bassa", "rosso"),
}
# "Puntata più solida": affidabilità alta e probabilità non lontana dalla migliore
SOGLIA_PROB_SOLIDA = 0.5  # almeno metà della probabilità più alta tra i candidati


def testo_affidabilita(c: Candidato) -> str:
    """"🟢 Alta 86": livello e punteggio 0-100."""
    pallino, nome, _ = LIVELLI_AFFIDABILITA[affidabilita.livello(c.affidabilita_punti)]
    return f"{pallino} {nome} {c.affidabilita_punti}"


def tipo_badge_affidabilita(c: Candidato) -> str:
    return LIVELLI_AFFIDABILITA[affidabilita.livello(c.affidabilita_punti)][2]


def motivi_affidabilita(c: Candidato) -> str:
    """La riga con i motivi del punteggio, in chiaro."""
    return " · ".join(c.affidabilita_motivi)


def ordina_candidati(candidati: list[Candidato], per_affidabilita: bool) -> list[Candidato]:
    """Per probabilità (come arriva dalla classifica) oppure per affidabilità decrescente,
    a parità la probabilità più alta per prima."""
    if not per_affidabilita:
        return list(candidati)
    return sorted(candidati, key=lambda c: (-c.affidabilita_punti, -c.probabilita, c.giocatore_id))


def puntata_piu_solida(candidati: list[Candidato]) -> Candidato | None:
    """Il candidato con probabilità e affidabilità alte insieme: tra quelli con affidabilità
    alta (70 o più) e probabilità almeno metà della più alta, il maggior prodotto
    probabilità × affidabilità. None se nessuno ha i requisiti."""
    if not candidati:
        return None
    soglia = max(c.probabilita for c in candidati) * SOGLIA_PROB_SOLIDA
    adatti = [
        c for c in candidati
        if c.affidabilita_punti >= affidabilita.SOGLIA_ALTA and c.probabilita >= soglia
    ]
    if not adatti:
        return None
    return max(adatti, key=lambda c: (c.probabilita * c.affidabilita_punti, -c.giocatore_id))


def valore_testo(v: float) -> str:
    """Differenza in punti percentuali con segno: "+12%" / "-3%"."""
    return f"{round(v * 100):+d}%"


def link_sofascore(giocatore) -> str:
    """Pagina Sofascore del giocatore se nota, altrimenti una ricerca."""
    if giocatore.sofascore_url:
        return giocatore.sofascore_url
    return "https://www.google.com/search?q=sofascore+" + "+".join(giocatore.nome.split())


def _ricerca_google_sito(sito: str, nome: str) -> str:
    return "https://www.google.com/search?q=" + quote_plus(f"site:{sito} {nome}")


def link_esterni(giocatore) -> list[tuple[str, str]]:
    """Link per il controllo visivo del giocatore sulle app più usate (nessuna viene letta
    in automatico). FBref e Transfermarkt hanno una ricerca propria; per le altre si usa
    una ricerca Google limitata al sito."""
    nome = " ".join(giocatore.nome.split())
    return [
        ("Sofascore", link_sofascore(giocatore)),
        ("FBref", "https://fbref.com/search/search.fcgi?search=" + quote_plus(nome)),
        ("FotMob", _ricerca_google_sito("fotmob.com", nome)),
        ("WhoScored", _ricerca_google_sito("whoscored.com", nome)),
        ("Transfermarkt",
         "https://www.transfermarkt.it/schnellsuche/ergebnis/schnellsuche?query=" + quote_plus(nome)),
        ("Diretta", _ricerca_google_sito("diretta.it", nome)),
    ]


# ---------------------------------------------------------------- pagina Partite

TUTTI = "Tutti"
# Selettore del campionato delle pagine Partite e Giocate: "Serie A", "Liga", "Tutti"
FILTRO_CAMPIONATI = (*NOMI_CAMPIONATI.values(), TUTTI)
FILTRO_PREDEFINITO = NOMI_CAMPIONATI[SERIE_A]


def campionati_del_filtro(etichetta: str) -> tuple[int, ...]:
    """Campionati scelti nel selettore; un valore sconosciuto vale il predefinito (Serie A)."""
    if etichetta == TUTTI:
        return CAMPIONATI
    for campionato, nome in NOMI_CAMPIONATI.items():
        if nome == etichetta:
            return (campionato,)
    return (SERIE_A,)


@dataclass(frozen=True)
class RigaPartita:
    id: int
    quando: str
    giornata: int | None
    casa: str
    trasferta: str
    arbitro: str | None
    calda: bool
    formazioni: str
    campionato: str = ""
    ora: str = ""  # "20:45" in Europe/Rome
    data_utc: datetime | None = None
    derby: bool = False  # rivalità nelle liste manuali (per il badge)
    arbitro_severo: bool = False  # fattore arbitro >= soglia per almeno una squadra
    # solo per le partite finite (Calendario): risultato e cartellini totali della partita
    stato: str = ""
    finita: bool = False
    gol_casa: int | None = None
    gol_trasferta: int | None = None
    gialli: int | None = None  # compresi quelli presi dalla panchina; None: statistiche mancanti
    rossi: int | None = None
    # solo per la pagina Partite calde: cartellini attesi e motivi in chiaro
    attesi: float | None = None
    motivi: tuple[str, ...] = ()
    # stemmi ESPN (None: immagini spente o stemma non noto -> iniziali)
    logo_casa: str | None = None
    logo_trasferta: str | None = None
    arbitro_id: int | None = None  # per il link alla scheda dell'arbitro (pagina Arbitri)


# ---------------------------------------------------------------- immagini ESPN

CHIAVE_IMMAGINI = "immagini_espn"  # Impostazione: stemmi e volti da ESPN (accesa di default)
URL_VOLTO = "https://a.espncdn.com/i/headshots/soccer/players/full/{}.png"
NOTA_IMMAGINI = (
    "Stemmi e volti vengono caricati dal browser direttamente dal sito di ESPN, per solo uso "
    "personale: sono immagini protette da diritti. Da spegnere (o sostituire) in caso di uso "
    "commerciale o pubblico dell'app."
)


def immagini_attive(s: Session) -> bool:
    """True se l'impostazione "Immagini da ESPN" è accesa (predefinito: accesa)."""
    return bool(repo.leggi_impostazione(s, CHIAVE_IMMAGINI, True))


def imposta_immagini(s: Session, attive: bool) -> None:
    repo.scrivi_impostazione(s, CHIAVE_IMMAGINI, bool(attive))


def url_https(valore) -> str | None:
    """L'URL solo se è https (le immagini si caricano dal browser: niente altri schemi)."""
    return valore if isinstance(valore, str) and valore.startswith("https://") else None


def url_volto(giocatore_id: int) -> str:
    """Foto ESPN del giocatore (può non esistere: allora resta la maglietta)."""
    return URL_VOLTO.format(int(giocatore_id))


def ora_italiana(dt_utc: datetime) -> str:
    """"20:45" in Europe/Rome."""
    return f"{dt_utc.astimezone(ROMA):%H:%M}"


def nella_finestra(
    righe: list[RigaPartita], adesso_utc: datetime, giorni: int = GIORNI_PROSSIME
) -> list[RigaPartita]:
    """Le partite da `adesso_utc` fino a `giorni` giorni dopo (per filtrare dopo la cache)."""
    fine = adesso_utc + timedelta(days=giorni)
    return [r for r in righe if adesso_utc <= r.data_utc <= fine]


def intestazione_giorno(giorno: date, oggi: date) -> str:
    """"Oggi · giovedì 6 novembre 2026", "Domani · ..." o solo "sabato 8 novembre 2026"."""
    testo = f"{GIORNI_ESTESI[giorno.weekday()]} {giorno.day} {MESI[giorno.month - 1]} {giorno.year}"
    if giorno == oggi:
        return f"Oggi · {testo}"
    if giorno == oggi + timedelta(days=1):
        return f"Domani · {testo}"
    return testo


def raggruppa_per_giorno(
    righe: list[RigaPartita], adesso_utc: datetime
) -> list[tuple[str, list[RigaPartita]]]:
    """Partite raggruppate per giorno di Europe/Rome (giorni in ordine, partite per orario
    di inizio), con l'intestazione del giorno."""
    def locale(r: RigaPartita) -> datetime:
        dt = r.data_utc
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(ROMA)

    oggi = adesso_utc.astimezone(ROMA).date()
    gruppi: dict[date, list[RigaPartita]] = {}
    for r in sorted(righe, key=lambda r: (locale(r), r.id)):
        gruppi.setdefault(locale(r).date(), []).append(r)
    return [(intestazione_giorno(g, oggi), rr) for g, rr in gruppi.items()]


# ---------------------------------------------------------------- calore di una partita

PRECEDENTI_MINIMI = 2  # precedenti diretti con statistiche per contare
PARTITE_ARBITRO_MINIME = 5
PARTITE_SQUADRA_MINIME = 3
ECCESSO_MOTIVO = 1.15  # un dato spiega il calore se supera la media del campionato del 15%
BONUS_DERBY = 0.8
BONUS_CAMPO_CALDO = 0.4
BONUS_POSTA = 0.15  # per ogni squadra con qualcosa in palio
MEDIA_LEGA_PREDEFINITA = 4.4  # cartellini (gialli + rossi) a partita senza dati


@dataclass(frozen=True)
class Calore:
    """Quanto si prevede "calda" una partita: cartellini attesi (gialli + rossi, entrambe le
    squadre; None senza dati) e le ragioni in chiaro."""
    attesi: float | None
    calda: bool
    motivi: tuple[str, ...]


def numero_it(valore: float) -> str:
    return f"{valore:.1f}".replace(".", ",")


def calore_partita(
    *,
    derby: str | None = None,
    campo_caldo: str | None = None,
    precedenti: list[int] | tuple[int, ...] = (),
    arbitro: str | None = None,
    arbitro_medi: float | None = None,
    arbitro_partite: int = 0,
    medie_squadre: tuple[float | None, float | None] = (None, None),
    media_lega: float = MEDIA_LEGA_PREDEFINITA,
    posta: tuple[tuple[str, str], ...] = (),
) -> Calore:
    """Cartellini attesi della partita: media di quello che dicono i dati disponibili
    (precedenti diretti già limitati agli ultimi 5, cartellini a partita dell'arbitro
    designato, media delle due squadre nella stagione) più piccoli bonus per derby, campo caldo
    e posta in classifica (`posta`: coppie (squadra, posta)). Calda se i cartellini attesi
    arrivano alla soglia di `config.SOGLIA_CARTELLINI_ATTESI` oppure è un derby."""
    valori: list[float] = []
    motivi: list[str] = []
    if derby:
        motivi.append(derby)
    if campo_caldo:
        motivi.append(f"campo caldo: {campo_caldo}")

    def alto(valore: float) -> bool:
        return valore >= media_lega * ECCESSO_MOTIVO

    if len(precedenti) >= PRECEDENTI_MINIMI:
        media_prec = sum(precedenti) / len(precedenti)
        valori.append(media_prec)
        if alto(media_prec):
            motivi.append(f"precedenti: {numero_it(media_prec)} cartellini")
    if arbitro_medi is not None and arbitro_partite >= PARTITE_ARBITRO_MINIME:
        valori.append(arbitro_medi)
        if alto(arbitro_medi):
            nome = f" ({arbitro})" if arbitro else ""
            motivi.append(f"arbitro severo{nome}: {numero_it(arbitro_medi)} cartellini a partita")
    squadre = [m for m in medie_squadre if m is not None]
    if squadre:
        media_sq = sum(squadre) / len(squadre)
        valori.append(media_sq)
        if alto(media_sq):
            motivi.append(f"squadre nervose: {numero_it(media_sq)} cartellini a partita")
    for squadra, in_palio in posta:
        motivi.append(f"posta in classifica: {squadra} ({in_palio})")

    if not valori:
        return Calore(attesi=None, calda=bool(derby), motivi=tuple(motivi))
    attesi = (
        sum(valori) / len(valori)
        + (BONUS_DERBY if derby else 0.0)
        + (BONUS_CAMPO_CALDO if campo_caldo else 0.0)
        + BONUS_POSTA * len(posta)
    )
    calda = bool(derby) or attesi >= SOGLIA_CARTELLINI_ATTESI
    if calda and not motivi:
        motivi.append("cartellini attesi elevati")
    return Calore(attesi=attesi, calda=calda, motivi=tuple(motivi))


def stato_aggiornamento(s: Session) -> tuple[str, bool]:
    """(testo "Dati aggiornati: ...", ultimo job notturno completo?)."""
    quando = repo.ultimo_aggiornamento(s, "notte")
    if quando is None:
        return "Dati non ancora aggiornati", True
    riga = s.get(UltimoAggiornamento, "notte")
    return f"Dati aggiornati: {data_breve(quando)}", bool(riga.completo)


def e_partita_calda(dati: DatiPartita, pesi) -> bool:
    """Rivalità, campo caldo o arbitro con fattore >= 1.1 (per almeno una delle due squadre)."""
    return _calda(
        dati.contesto.rivalita, dati.contesto.campo_caldo, dati.arbitro, dati.medie,
        dati.casa_id, dati.trasferta_id, pesi,
    )


def _calda(rivalita, campo_caldo, arbitro, medie, casa_id, trasferta_id, pesi) -> bool:
    if rivalita or campo_caldo:
        return True
    return _arbitro_severo(arbitro, medie, casa_id, trasferta_id, pesi)


def _arbitro_severo(arbitro, medie, casa_id, trasferta_id, pesi) -> bool:
    return any(
        fattore_arbitro(arbitro, sq, medie, pesi).valore >= SOGLIA_PARTITA_CALDA
        for sq in (casa_id, trasferta_id)
    )


def prossime_partite(
    s: Session,
    ora: datetime,
    giorni: int = GIORNI_PROSSIME,
    campionati: tuple[int, ...] = (SERIE_A,),
    squadra_id: int | None = None,
) -> list[RigaPartita]:
    """Partite dei prossimi `giorni` giorni dei campionati dati (la Serie A se non indicati),
    se indicata solo quelle della squadra."""
    filtri = [
        Partita.competizione_id.in_(campionati),
        Partita.data_utc >= ora,
        Partita.data_utc <= ora + timedelta(days=giorni),
    ]
    if squadra_id is not None:
        filtri.append((Partita.casa_id == squadra_id) | (Partita.trasferta_id == squadra_id))
    partite = s.execute(select(Partita).where(*filtri).order_by(Partita.data_utc)).scalars().all()
    return righe_partite(s, list(partite))


def righe_partite(s: Session, partite: list[Partita]) -> list[RigaPartita]:
    """Righe (per le schede) di partite già lette, con query raggruppate per tutte insieme.
    Da giocare: badge (calda, derby, arbitro severo) dai dati del motore. Finite: risultato,
    arbitro e cartellini totali (gialli e rossi di tutte le presenze, panchina compresa)."""
    if not partite:
        return []
    ids_squadre = {p.casa_id for p in partite} | {p.trasferta_id for p in partite}
    squadre = list(s.execute(select(Squadra).where(Squadra.id.in_(ids_squadre))).scalars())
    nomi = {sq.id: sq.nome for sq in squadre}
    loghi = (
        {sq.id: url_https(sq.logo_url) for sq in squadre} if immagini_attive(s) else {}
    )
    finite = [p for p in partite if p.stato in STATI_FINITI]
    da_giocare = [p for p in partite if p.stato not in STATI_FINITI]
    # per il badge servono solo liste manuali e arbitro: query raggruppate per tutte le partite
    calde = carica_dati_calda(s, da_giocare) if da_giocare else {}
    pesi = carica_pesi(s) if da_giocare else None
    arbitri_finite = {}
    ids_arbitri = {p.arbitro_id for p in finite if p.arbitro_id is not None}
    if ids_arbitri:
        arbitri_finite = {
            a.id: a.nome_visualizzato
            for a in s.execute(select(Arbitro).where(Arbitro.id.in_(ids_arbitri))).scalars()
        }
    cartellini = cartellini_partite(s, [p.id for p in finite if p.statistiche_scaricate])
    righe = []
    for p in partite:
        comune = dict(
            id=p.id,
            quando=data_italiana(p.data_utc),
            giornata=p.giornata,
            casa=nomi.get(p.casa_id, str(p.casa_id)),
            trasferta=nomi.get(p.trasferta_id, str(p.trasferta_id)),
            formazioni=p.stato_formazioni,
            campionato=NOMI_CAMPIONATI.get(p.competizione_id, ""),
            ora=ora_italiana(p.data_utc),
            data_utc=p.data_utc,
            stato=p.stato,
            logo_casa=loghi.get(p.casa_id),
            logo_trasferta=loghi.get(p.trasferta_id),
            arbitro_id=p.arbitro_id,
        )
        if p.stato in STATI_FINITI:
            gialli, rossi = cartellini.get(p.id, (None, None))
            if gialli is None and p.gialli_totali is not None and p.rossi_totali is not None:
                gialli, rossi = p.gialli_totali, p.rossi_totali  # dal tabellone ESPN
            righe.append(RigaPartita(
                **comune, arbitro=arbitri_finite.get(p.arbitro_id), calda=False, finita=True,
                gol_casa=p.gol_casa, gol_trasferta=p.gol_trasferta, gialli=gialli, rossi=rossi,
            ))
            continue
        dc = calde[p.id]
        righe.append(RigaPartita(
            **comune,
            arbitro=dc.arbitro.nome if dc.arbitro and dc.arbitro.nome else None,
            calda=_calda(
                dc.rivalita, dc.campo_caldo, dc.arbitro, dc.medie,
                dc.casa_id, dc.trasferta_id, pesi,
            ),
            derby=bool(dc.rivalita),
            arbitro_severo=_arbitro_severo(dc.arbitro, dc.medie, dc.casa_id, dc.trasferta_id, pesi),
        ))
    return righe


def cartellini_partite(s: Session, partite_ids: list[int]) -> dict[int, tuple[int, int]]:
    """(gialli, rossi) totali di ogni partita, di entrambe le squadre e di tutte le presenze
    (anche i subentrati e chi è stato ammonito dalla panchina), con una sola query. Su
    Postgres SUM restituisce Decimal: convertito in int."""
    if not partite_ids:
        return {}
    righe = s.execute(
        select(Presenza.partita_id, func.sum(Presenza.gialli), func.sum(Presenza.rossi))
        .where(Presenza.partita_id.in_(partite_ids))
        .group_by(Presenza.partita_id)
    ).all()
    return {pid: (int(g or 0), int(r or 0)) for pid, g, r in righe}


# ---------------------------------------------------------------- pagina Dettaglio

@dataclass(frozen=True)
class InfoPartita:
    id: int
    data_utc: datetime
    giornata: int | None
    stato_formazioni: str
    arbitro_id: int | None = None  # per il link alla scheda dell'arbitro


@dataclass(frozen=True)
class Dettaglio:
    partita: InfoPartita
    dati: DatiPartita
    candidati: list[Candidato]
    tipster: dict[int, list[str]]
    nomi_giocatori: dict[int, str]
    subentranti: list[Candidato] = field(default_factory=list)  # tabella a parte


def id_partita(valore) -> int | None:
    """Id dal parametro dell'URL; None se assente o non numerico."""
    try:
        return int(valore)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PaginaDettaglio:
    """Tutto quello che serve alla pagina Dettaglio, caricato con poche query (senza quote)."""
    dettaglio: Dettaglio
    cambi: list[str]
    extra: dict[int, dict]
    campo: object | None = None  # componenti_campo.DatiCampo
    # giocate già registrate in questa partita: giocatore_id -> (puntata, quota)
    giocate: dict[int, tuple[float, float]] = field(default_factory=dict)


def etichetta_formazioni(stato: str) -> str:
    """Scritta sulle formazioni usate: ufficiali oppure calcolate dall'app."""
    return "formazioni ufficiali" if stato == "ufficiali" else "formazioni probabili (calcolate)"


def applica_quote(candidati: list[Candidato], quote: dict[int, float]) -> list[Candidato]:
    """Candidati con quota, probabilità implicita e valore delle quote inserite (la classifica
    non dipende dalle quote, quindi basta ricalcolare questi tre campi)."""
    if not quote:
        return candidati
    risultato = []
    for c in candidati:
        quota = quote.get(c.giocatore_id)
        if not quota:
            risultato.append(c)
            continue
        implicita = 1 / quota
        risultato.append(
            replace(c, quota=quota, prob_implicita=implicita, valore=c.probabilita - implicita)
        )
    return risultato


def carica_pagina_dettaglio(s: Session, partita_id: int) -> PaginaDettaglio | None:
    """Dettaglio, cambi ed extra per candidato. Un solo
    `carica_dati`; statistiche per 90' e storia con l'avversaria in query raggruppate."""
    det = carica_dettaglio(s, partita_id, {})
    if det is None:
        return None
    dati, partita = det.dati, det.partita
    cambi = righe_cambi(s, det)

    ids_giocatori = {c.giocatore_id for c in det.candidati}
    avversari = {c.avversario_diretto_id for c in det.candidati if c.avversario_diretto_id}
    stat = statistiche_90_batch(s, ids_giocatori | avversari, dati.stagione, dati.data)
    def sq_avv(c: Candidato) -> int:
        return dati.trasferta_id if c.squadra_id == dati.casa_id else dati.casa_id

    storie = storia_contro_batch(
        s, {(c.giocatore_id, sq_avv(c)) for c in det.candidati}, dati.data
    )
    giocatori = {
        g.id: g
        for g in s.execute(select(Giocatore).where(Giocatore.id.in_(ids_giocatori))).scalars()
    } if ids_giocatori else {}
    extra = {}
    for c in det.candidati:
        avv_id = c.avversario_diretto_id
        sq = sq_avv(c)
        extra[c.giocatore_id] = {
            "stat": stat[c.giocatore_id],
            "stat_avv": stat[avv_id] if avv_id else {"minuti": 0},
            "storia": testo_storia(*storie[(c.giocatore_id, sq)], dati.nomi_squadre.get(sq, "")),
            "link": link_esterni(giocatori[c.giocatore_id]),
            "avversari": avversari_possibili(dati, c),
        }
    import componenti_campo  # qui: componenti_campo importa questo modulo

    campo = componenti_campo.carica_campo(
        s, s.get(Partita, partita_id), dati.titolari, det.candidati, det.subentranti
    )
    return PaginaDettaglio(
        dettaglio=det, cambi=cambi, extra=extra, campo=campo,
        giocate=giocate_partita(s, partita_id),
    )


def giocate_partita(s: Session, partita_id: int) -> dict[int, tuple[float, float]]:
    """Prima giocata registrata per ogni giocatore della partita: (puntata, quota)."""
    righe = s.execute(
        select(Giocata.giocatore_id, Giocata.puntata, Giocata.quota)
        .where(Giocata.partita_id == partita_id)
        .order_by(Giocata.id)
    ).all()
    giocate: dict[int, tuple[float, float]] = {}
    for gid, puntata, quota in righe:
        # Postgres può dare Decimal: sempre float (la cache vuole dati semplici)
        giocate.setdefault(int(gid), (float(puntata), float(quota)))
    return giocate


def carica_dettaglio(s: Session, partita_id: int, quote: dict[int, float]) -> Dettaglio | None:
    partita = s.get(Partita, partita_id)
    if partita is None:
        return None
    dati = carica_dati(s, partita_id, con_panchina=True)
    # una sola lettura dei dati: le classifiche lavorano sullo snapshot gia' caricato;
    # il modello (V1 o V2) è quello scelto in Impostazioni
    pesi = carica_pesi(s)
    scelto = modello.modello_scelto(s)
    coeff = modello.carica_coefficienti(s) if scelto == modello.V2 else None
    candidati, subentranti = modello.candidati(dati, pesi, quote or None, scelto, coeff)
    return Dettaglio(
        partita=InfoPartita(
            partita.id, partita.data_utc, partita.giornata, partita.stato_formazioni,
            partita.arbitro_id,
        ),
        dati=dati,
        candidati=candidati,
        tipster=tipster_per_giocatore(s, partita_id),
        nomi_giocatori={t.giocatore_id: t.nome for t in dati.titolari},
        subentranti=subentranti,
    )


def etichetta_subentro(c: Candidato) -> str:
    """"subentrante · può entrare al posto di X" (senza nome se nessun titolare dello stesso
    ruolo viene sostituito)."""
    nome = c.subentro.al_posto_di_nome if c.subentro else None
    return f"subentrante · può entrare al posto di {nome}" if nome else "subentrante · può entrare"


def _numero(x: float | None, cifre: int) -> str:
    return "n.d." if x is None else decimale(x, cifre)


def medie_subentro(c: Candidato) -> str:
    """Gialli e falli per 90' del subentrante accanto alla media del suo ruolo."""
    s = c.subentro
    return (
        f"Gialli 90' {_numero(s.gialli90, 2)} (ruolo {decimale(s.media_gialli90, 2)}) · "
        f"Falli 90' {_numero(s.falli90, 1)} (ruolo {decimale(s.media_falli90, 1)})"
    )


def ingresso_subentro(c: Candidato) -> str:
    s = c.subentro
    return f"Entra {percentuale(s.probabilita_ingresso)} · {round(s.minuti_medi)}' di media"


RUOLI_ESTESI = {"G": "Portiere", "D": "Difensore", "M": "Centrocampista", "F": "Attaccante"}


def righe_subentranti(
    subentranti: list[Candidato], nomi_squadre: dict[int, str]
) -> list[dict[str, str]]:
    """Righe della tabella dei probabili subentranti (già ordinati per probabilità)."""
    return [
        {
            "Giocatore": c.nome,
            "Squadra": nomi_squadre.get(c.squadra_id, ""),
            "Ruolo": RUOLI_ESTESI.get(c.ruolo, ""),
            "Probabilità": percentuale(c.probabilita),
            "Entra": percentuale(c.subentro.probabilita_ingresso),
            "Minuti": f"{round(c.subentro.minuti_medi)}'",
            "Al posto di": c.subentro.al_posto_di_nome or "",
            "Gialli 90'": _numero(c.subentro.gialli90, 2),
            "Falli 90'": _numero(c.subentro.falli90, 1),
            "Sopra la media": "sì" if c.subentro.sopra_media else "",
        }
        for c in subentranti
    ]


def tipster_per_giocatore(s: Session, partita_id: int) -> dict[int, list[str]]:
    risultato: dict[int, list[str]] = {}
    righe = s.execute(
        select(Segnalazione.giocatore_id, Segnalazione.fonte)
        .where(Segnalazione.partita_id == partita_id, Segnalazione.fonte.not_in(FONTI_NON_TIPSTER))
        .order_by(Segnalazione.id)
    ).all()
    for giocatore_id, fonte in righe:
        if fonte not in risultato.setdefault(giocatore_id, []):
            risultato[giocatore_id].append(fonte)
    return risultato


def righe_contesto(dati: DatiPartita) -> list[str]:
    c = dati.contesto
    a = dati.arbitro
    if a is None or not a.nome:
        arbitro = "Arbitro: non ancora designato"
    else:
        arbitro = (
            f"Arbitro: {a.nome} · {decimale(a.gialli_medi)} gialli e "
            f"{decimale(a.falli_medi)} falli a partita ({a.partite} partite)"
        )
    posta = ", ".join(
        f"{dati.nomi_squadre.get(sq, sq)}: {p}"
        for sq, p in c.posta.items()
        if p
    ) or "nessuna in particolare"
    if c.precedenti_n and c.precedenti_gialli_medi is not None:
        precedenti = (
            f"Precedenti: {c.precedenti_n} partite, {decimale(c.precedenti_gialli_medi)} gialli di media"
        )
    else:
        precedenti = "Precedenti: nessuno nei dati"
    return [
        arbitro,
        f"Rivalità: {'sì' if c.rivalita else 'no'}" + (" · campo caldo" if c.campo_caldo else ""),
        f"Posta in palio: {posta}",
        precedenti,
    ]


def righe_cambi(s: Session, dettaglio: Dettaglio) -> list[str]:
    """Una riga per squadra con i cambi tra formazione probabile e ufficiale."""
    if dettaglio.partita.stato_formazioni != "ufficiali":
        return []
    cambi = riepilogo_cambi(s, dettaglio.partita.id)
    ids = {g for entrati, usciti in cambi.values() for g in entrati + usciti}
    nomi = {
        g.id: g.nome
        for g in s.execute(select(Giocatore).where(Giocatore.id.in_(ids))).scalars()
    } if ids else {}

    def elenco(lista: list[int]) -> str:
        return ", ".join(nomi.get(g, str(g)) for g in lista) or "nessuno"

    return [
        f"{dettaglio.dati.nomi_squadre.get(sq, sq)}: entrati {elenco(entrati)}; usciti {elenco(usciti)}"
        for sq, (entrati, usciti) in cambi.items()
    ]


def righe_tabella(
    candidati: list[Candidato], nomi_squadre: dict[int, str], tipster: dict[int, list[str]]
) -> list[dict[str, str]]:
    return [
        {
            "Giocatore": c.nome,
            "Squadra": nomi_squadre.get(c.squadra_id, ""),
            "Probabilità": percentuale(c.probabilita),
            "Motivazioni": " · ".join(c.motivazioni),
            "Affidabilità": testo_affidabilita(c),
            "Quota": decimale(c.quota, 2) if c.quota else "",
            "Implicita": percentuale(c.prob_implicita) if c.prob_implicita else "",
            "Valore": valore_testo(c.valore) if c.valore is not None else "",
            "Tipster": ", ".join(tipster.get(c.giocatore_id, [])),
        }
        for c in candidati
    ]


def colore_valore(testo: str) -> str:
    """Stile CSS della cella Valore: verde se positivo."""
    return "background-color: #c8f0c8; color: #14532d" if testo.startswith("+") and testo != "+0%" else ""


def avversari_possibili(dati: DatiPartita, candidato: Candidato) -> list[tuple[int, str]]:
    return [
        (t.giocatore_id, t.nome) for t in dati.titolari if t.squadra_id != candidato.squadra_id
    ]


def statistiche_90_batch(
    s: Session, giocatori: set[int], stagione: int, prima_di: datetime
) -> dict[int, dict[str, float]]:
    """Medie per 90 minuti (gialli, falli, falli subiti, dribbling) nelle ultime 3 stagioni
    di più giocatori con una sola query raggruppata."""
    risultato: dict[int, dict[str, float]] = {g: {"minuti": 0} for g in giocatori}
    if not giocatori:
        return risultato
    righe = s.execute(
        select(
            Presenza.giocatore_id,
            func.sum(Presenza.minuti),
            func.sum(Presenza.gialli),
            func.sum(Presenza.falli_commessi),
            func.sum(Presenza.falli_subiti),
            func.sum(Presenza.dribbling_tentati),
        )
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(
            Presenza.giocatore_id.in_(giocatori),
            Partita.data_utc < prima_di,
            Partita.stagione.in_((stagione, stagione - 1, stagione - 2)),
        )
        .group_by(Presenza.giocatore_id)
    ).all()
    for gid, minuti, gialli, falli, subiti, dribbling in righe:
        minuti = int(minuti or 0)
        if minuti <= 0:
            continue

        def per90(valore) -> float:
            return int(valore or 0) / minuti * 90

        risultato[gid] = {
            "minuti": minuti,
            "gialli90": per90(gialli),
            "falli90": per90(falli),
            "falli_subiti90": per90(subiti),
            "dribbling90": per90(dribbling),
        }
    return risultato


def statistiche_90(s: Session, giocatore_id: int, stagione: int, prima_di: datetime) -> dict[str, float]:
    """Medie per 90 minuti (gialli, falli, falli subiti, dribbling) nelle ultime 3 stagioni."""
    return statistiche_90_batch(s, {giocatore_id}, stagione, prima_di)[giocatore_id]


def righe_duello(stat_a: dict[str, float], stat_b: dict[str, float]) -> list[dict[str, str]]:
    """Tabella affiancata delle statistiche per 90 minuti dei due giocatori."""
    etichette = (
        ("gialli90", "Gialli per 90'"),
        ("falli90", "Falli commessi per 90'"),
        ("falli_subiti90", "Falli subiti per 90'"),
        ("dribbling90", "Dribbling tentati per 90'"),
    )

    def cella(stat: dict[str, float], chiave: str) -> str:
        return decimale(stat[chiave], 2) if chiave in stat else "n.d."

    return [
        {"Statistica": nome, "Giocatore": cella(stat_a, k), "Avversario": cella(stat_b, k)}
        for k, nome in etichette
    ]


def storia_contro_batch(
    s: Session, coppie: set[tuple[int, int]], prima_di: datetime
) -> dict[tuple[int, int], tuple[int, int]]:
    """Per ogni (giocatore, squadra avversaria): (partite giocate, gialli presi) contro di
    essa, con una sola query."""
    risultato = {c: (0, 0) for c in coppie}
    if not coppie:
        return risultato
    giocatori = {g for g, _ in coppie}
    squadre = {q for _, q in coppie}
    righe = s.execute(
        select(Presenza.giocatore_id, Presenza.squadra_id, Presenza.gialli,
               Partita.casa_id, Partita.trasferta_id)
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(
            Presenza.giocatore_id.in_(giocatori),
            Presenza.minuti > 0,
            Partita.data_utc < prima_di,
            Partita.casa_id.in_(squadre) | Partita.trasferta_id.in_(squadre),
        )
    ).all()
    for gid, sq_giocatore, gialli, casa, trasf in righe:
        for avversaria in (casa, trasf):
            chiave = (gid, avversaria)
            if chiave in risultato and sq_giocatore != avversaria:
                giocate, presi = risultato[chiave]
                risultato[chiave] = (giocate + 1, presi + gialli)
    return risultato


def storia_contro(
    s: Session, giocatore_id: int, squadra_avversaria_id: int, prima_di: datetime
) -> tuple[int, int]:
    """(partite giocate, gialli presi) dal giocatore contro la squadra avversaria."""
    chiave = (giocatore_id, squadra_avversaria_id)
    return storia_contro_batch(s, {chiave}, prima_di)[chiave]


def testo_storia(partite: int, gialli: int, squadra: str) -> str:
    if partite == 0:
        return f"Contro {squadra}: nessun precedente nei dati"
    return f"Contro {squadra}: {partite} partite, {gialli} gialli"


def giocatori_squadra(s: Session, squadra_id: int, inclusi: list[int]) -> list[tuple[int, str]]:
    """Giocatori noti della squadra (presenze, formazioni, più quelli in `inclusi`), per nome."""
    ids = set(inclusi)
    ids.update(
        s.execute(select(Presenza.giocatore_id).where(Presenza.squadra_id == squadra_id)).scalars()
    )
    ids.update(
        s.execute(select(Formazione.giocatore_id).where(Formazione.squadra_id == squadra_id)).scalars()
    )
    righe = s.execute(select(Giocatore.id, Giocatore.nome).where(Giocatore.id.in_(ids))).all()
    return sorted(((i, n) for i, n in righe), key=lambda r: r[1])


# ---------------------------------------------------------------- scritture

def salva_segnalazione(
    s: Session, partita_id: int, giocatore_id: int, tipster: str, quota_testo: str = ""
) -> None:
    """Segnalazione di un tipster; la quota è facoltativa. ValueError con messaggio italiano."""
    nome = tipster.strip()
    if not nome:
        raise ValueError("Inserisci il nome del tipster")
    quota = converti_quota(quota_testo) if quota_testo.strip() else None
    s.add(Segnalazione(partita_id=partita_id, giocatore_id=giocatore_id, fonte=nome, quota=quota))
    s.flush()


def rimuovi_duello(s: Session, partita_id: int, giocatore_id: int) -> None:
    """Annulla la scelta manuale dell'avversario diretto (torna quello automatico)."""
    precedenti = s.execute(
        select(DuelloManuale).where(
            DuelloManuale.partita_id == partita_id, DuelloManuale.giocatore_id == giocatore_id
        )
    ).scalars().all()
    for p in precedenti:
        s.delete(p)
    s.flush()


def salva_duello(s: Session, partita_id: int, giocatore_id: int, avversario_id: int) -> None:
    """Avversario diretto scelto a mano (sostituisce la scelta precedente per quel giocatore)."""
    rimuovi_duello(s, partita_id, giocatore_id)
    s.add(DuelloManuale(partita_id=partita_id, giocatore_id=giocatore_id, avversario_id=avversario_id))
    s.flush()
