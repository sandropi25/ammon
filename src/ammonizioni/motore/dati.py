"""Caricamento dal DB dello snapshot di una partita. Ogni query vede solo righe con
Partita.data_utc < prima_di (default: calcio d'inizio), cosi' la prova storica non vede il futuro."""
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ammonizioni.caricamento.formazioni import (
    probabili_automatiche,
    titolare_da,
    ultimo_xi,
)
from ammonizioni.config import CAMPIONATI, SERIE_A, STATI_FINITI, campionato_di
from ammonizioni.db.modelli import (
    DuelloManuale,
    Formazione,
    Giocatore,
    Partita,
    Presenza,
    Squadra,
    Arbitro,
)
from ammonizioni.motore import rivalita, subentranti
from ammonizioni.motore.fattori.contesto import posta_in_classifica
from ammonizioni.motore.tipi import (
    RUOLI,
    ContestoInfo,
    DatiPartita,
    MedieCampionato,
    MedieRuolo,
    RigaPresenza,
    StatArbitro,
    Titolare,
)

PRECEDENTI_MAX = 5

MEDIE_PREDEFINITE = MedieCampionato(
    gialli_partita=4.2,
    falli_partita=25.0,
    per_ruolo={
        "D": MedieRuolo(0.20, 1.4, 1.0, 0.5, 0.10, 6.1),
        "M": MedieRuolo(0.22, 1.3, 1.2, 1.0, 0.20, 6.2),
        "F": MedieRuolo(0.12, 1.1, 1.5, 1.8, 0.40, 6.2),
        "G": MedieRuolo(0.03, 0.1, 0.1, 0.0, 0.0, 6.2),
    },
)


def _ruolo(ruolo: str | None) -> str:
    return ruolo if ruolo in RUOLI else "M"


def _positivo(valore: float | None, predefinito: float) -> float:
    return valore if valore is not None and valore > 0 else predefinito


def _coppia(a: int, b: int) -> frozenset[int]:
    return frozenset((a, b))


def _derby(s: Session) -> set[frozenset[int]]:
    """Derby riconosciuti: elenco predefinito (per nome) e righe manuali già nel database."""
    return rivalita.derby_noti(s)


def _totali_partite(s: Session, partita_ids: list[int]) -> dict[int, tuple[int, int]]:
    """partita_id -> (gialli totali, falli commessi totali), solo partite con presenze."""
    if not partita_ids:
        return {}
    righe = s.execute(
        select(
            Presenza.partita_id,
            func.sum(Presenza.gialli),
            func.sum(Presenza.falli_commessi),
        )
        .where(Presenza.partita_id.in_(partita_ids))
        .group_by(Presenza.partita_id)
    ).all()
    return {pid: (int(g or 0), int(f or 0)) for pid, g, f in righe}


def _media(valori: list[float]) -> float | None:
    return sum(valori) / len(valori) if valori else None


def _campionato_partita(s: Session, partita: Partita) -> int:
    """Il campionato i cui dati valgono per la partita: il suo, o quello della coppa nazionale.
    Una coppa europea prende il campionato delle squadre (in stagione), la Serie A per prima;
    senza indicazioni, la Serie A."""
    campionato = campionato_di(partita.competizione_id)
    if campionato is not None:
        return campionato
    squadre = (partita.casa_id, partita.trasferta_id)
    for candidato in CAMPIONATI:  # la Serie A prima
        trovata = s.scalars(
            select(Partita.id)
            .where(
                Partita.competizione_id == candidato,
                Partita.stagione == partita.stagione,
                or_(Partita.casa_id.in_(squadre), Partita.trasferta_id.in_(squadre)),
            )
            .limit(1)
        ).first()
        if trovata is not None:
            return candidato
    return SERIE_A


def _medie_campionato(
    s: Session, stagione: int, prima_di: datetime, campionato_id: int = SERIE_A
) -> MedieCampionato:
    # partite del campionato con statistiche, nelle 3 stagioni, prima di `prima_di`
    filtro_partite = (
        Partita.competizione_id == campionato_id,
        Partita.statistiche_scaricate.is_(True),
        Partita.data_utc < prima_di,
        Partita.stagione.in_((stagione, stagione - 1, stagione - 2)),
    )
    # totali per partita (solo partite con presenze), aggregati in SQL
    per_partita = (
        select(
            func.sum(Presenza.gialli).label("gialli"),
            func.sum(Presenza.falli_commessi).label("falli"),
        )
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(*filtro_partite)
        .group_by(Presenza.partita_id)
        .subquery()
    )
    n, tot_gialli, tot_falli = s.execute(
        select(func.count(), func.sum(per_partita.c.gialli), func.sum(per_partita.c.falli))
    ).one()
    # su Postgres la SUM di una SUM e' un Decimal: float() per non mescolare i tipi
    gialli_partita = _positivo(
        float(tot_gialli) / n if n else None, MEDIE_PREDEFINITE.gialli_partita
    )
    falli_partita = _positivo(
        float(tot_falli) / n if n else None, MEDIE_PREDEFINITE.falli_partita
    )

    ruolo_eff = func.coalesce(Presenza.ruolo, Giocatore.ruolo)
    righe = s.execute(
        select(
            ruolo_eff,
            func.sum(Presenza.minuti),
            func.sum(Presenza.gialli),
            func.sum(Presenza.falli_commessi),
            func.sum(Presenza.falli_subiti),
            func.sum(Presenza.dribbling_tentati),
            func.sum(Presenza.gol + Presenza.assist),
            func.sum(Presenza.voto),
            func.count(Presenza.voto),
        )
        .join(Partita, Partita.id == Presenza.partita_id)
        .join(Giocatore, Giocatore.id == Presenza.giocatore_id)
        # anche chi ha 0 minuti ma un giallo (ammonito dalla panchina senza entrare): ogni
        # giallo conta, come nel tasso del giocatore; i minuti sommano solo quelli giocati
        .where(*filtro_partite, or_(Presenza.minuti > 0, Presenza.gialli > 0))
        .group_by(ruolo_eff)
    ).all()
    # ruoli sconosciuti o None confluiscono in "M"
    somme: dict[str, list[float]] = {r: [0.0] * 8 for r in RUOLI}
    for ruolo, *valori in righe:
        acc = somme[_ruolo(ruolo)]
        for i, v in enumerate(valori):
            acc[i] += float(v or 0)

    # "dato assente" (fonte senza dribbling/voto) e' diverso da "nessun dato" (DB vuoto):
    # solo nel secondo caso valgono i predefiniti. Con minuti ma zero dribbling in tutta la
    # lega, dribbling90 = 0 (il duello lo tratta come neutro); senza alcun voto, voto = None.
    ci_sono_minuti = sum(v[0] for v in somme.values()) > 0
    lega_senza_dribbling = ci_sono_minuti and sum(v[4] for v in somme.values()) == 0
    lega_senza_voti = ci_sono_minuti and sum(v[7] for v in somme.values()) == 0

    medie: dict[str, MedieRuolo] = {}
    for ruolo in RUOLI:
        minuti, gialli, falli, subiti, drib, ga, voto_somma, voto_n = somme[ruolo]
        pre = MEDIE_PREDEFINITE.per_ruolo[ruolo]

        def per90(valore: float) -> float | None:
            return valore / minuti * 90 if minuti > 0 else None

        medie[ruolo] = MedieRuolo(
            gialli90=_positivo(per90(gialli), pre.gialli90),
            falli90=_positivo(per90(falli), pre.falli90),
            falli_subiti90=_positivo(per90(subiti), pre.falli_subiti90),
            dribbling90=0.0
            if lega_senza_dribbling
            else _positivo(per90(drib), pre.dribbling90),
            ga90=_positivo(per90(ga), pre.ga90),
            voto=None
            if lega_senza_voti
            else _positivo(voto_somma / voto_n if voto_n else None, pre.voto),
        )
    return MedieCampionato(gialli_partita, falli_partita, medie)

def _stat_arbitro(s: Session, partita: Partita, prima_di: datetime) -> StatArbitro | None:
    if partita.arbitro_id is None:
        return None
    arbitro = s.get(Arbitro, partita.arbitro_id)
    sue = s.execute(
        select(Partita).where(
            Partita.arbitro_id == partita.arbitro_id,
            Partita.statistiche_scaricate.is_(True),
            Partita.data_utc < prima_di,
            Partita.id != partita.id,
        )
    ).scalars().all()
    totali = _totali_partite(s, [p.id for p in sue])
    return _stat_da_righe(
        arbitro.nome_visualizzato if arbitro else "",
        [(p.casa_id, p.trasferta_id, *totali[p.id]) for p in sue if p.id in totali],
    )


def _stat_da_righe(nome: str, righe: list[tuple[int, int, int, int]]) -> StatArbitro:
    """StatArbitro dalle partite con presenze dell'arbitro: (casa, trasferta, gialli, falli)."""
    gialli = [r[2] for r in righe]
    falli = [r[3] for r in righe]
    con: dict[int, tuple[float, int]] = {}
    for squadra in {r[0] for r in righe} | {r[1] for r in righe}:
        g = [r[2] for r in righe if squadra in (r[0], r[1])]
        con[squadra] = (sum(g) / len(g), len(g)) if g else (0.0, 0)
    return StatArbitro(
        nome=nome,
        partite=len(gialli),
        gialli_medi=_media(gialli) or 0.0,
        falli_medi=_media(falli) or 0.0,
        gialli_medi_con={q: v for q, v in con.items() if v[1] > 0},
    )


@dataclass(frozen=True)
class DatiCalda:
    """Quanto serve per il badge "partita calda": niente storico dei giocatori."""
    casa_id: int
    trasferta_id: int
    rivalita: bool
    campo_caldo: bool
    arbitro: StatArbitro | None
    medie: MedieCampionato


def carica_dati_calda(s: Session, partite: list[Partita]) -> dict[int, DatiCalda]:
    """DatiCalda di piu' partite con poche query raggruppate (invece di un `carica_dati` per
    partita): liste manuali una volta, statistiche degli arbitri in un'unica query, medie del
    campionato una volta per (campionato, stagione) quando e' esatto. Stessi valori di
    `carica_dati` per ogni partita."""
    if not partite:
        return {}
    derby = _derby(s)

    # statistiche degli arbitri coinvolti: una query raggruppata per partita arbitrata
    arbitri_ids = {p.arbitro_id for p in partite if p.arbitro_id is not None}
    nomi_arbitri: dict[int, str] = {}
    giocate: dict[int, list[tuple[int, int, int, int, int, datetime]]] = {}
    if arbitri_ids:
        nomi_arbitri = {
            a.id: a.nome_visualizzato
            for a in s.execute(select(Arbitro).where(Arbitro.id.in_(arbitri_ids))).scalars()
        }
        limite = max(p.data_utc for p in partite if p.arbitro_id is not None)
        for arb, pid, casa, trasf, data, g, f in s.execute(
            select(
                Partita.arbitro_id, Partita.id, Partita.casa_id, Partita.trasferta_id,
                Partita.data_utc, func.sum(Presenza.gialli), func.sum(Presenza.falli_commessi),
            )
            .join(Presenza, Presenza.partita_id == Partita.id)
            .where(
                Partita.arbitro_id.in_(arbitri_ids),
                Partita.statistiche_scaricate.is_(True),
                Partita.data_utc < limite,
            )
            .group_by(Partita.arbitro_id, Partita.id, Partita.casa_id, Partita.trasferta_id,
                      Partita.data_utc)
        ).all():
            giocate.setdefault(arb, []).append((pid, casa, trasf, int(g or 0), int(f or 0), data))

    # Le medie dipendono dal "prima di" di ogni partita. Se fra la prima e l'ultima partita
    # non c'e' nessuna partita con statistiche, il risultato e' identico per tutte e si
    # calcola una volta per (campionato, stagione); altrimenti si calcola per partita.
    primo = min(p.data_utc for p in partite)
    ultimo = max(p.data_utc for p in partite)
    condivise = s.scalar(
        select(func.count()).select_from(Partita).where(
            Partita.statistiche_scaricate.is_(True),
            Partita.data_utc >= primo,
            Partita.data_utc < ultimo,
        )
    ) == 0

    medie: dict[tuple, MedieCampionato] = {}
    caldi: dict[tuple, set[int]] = {}  # campi caldi per (stagione, "prima di"), come le medie
    risultato: dict[int, DatiCalda] = {}
    for p in partite:
        chiave_caldi = (p.stagione, primo if condivise else p.data_utc)
        if chiave_caldi not in caldi:
            caldi[chiave_caldi] = rivalita.campi_caldi_noti(s, p.stagione, chiave_caldi[1])
        campi_caldi = caldi[chiave_caldi]
        campionato = _campionato_partita(s, p)
        chiave = (campionato, p.stagione) if condivise else (campionato, p.stagione, p.data_utc)
        if chiave not in medie:
            prima = primo if condivise else p.data_utc
            medie[chiave] = _medie_campionato(s, p.stagione, prima, campionato)
        arbitro = None
        if p.arbitro_id is not None:
            arbitro = _stat_da_righe(
                nomi_arbitri.get(p.arbitro_id, ""),
                [
                    (casa, trasf, g, f)
                    for pid, casa, trasf, g, f, data in giocate.get(p.arbitro_id, [])
                    if data < p.data_utc and pid != p.id
                ],
            )
        risultato[p.id] = DatiCalda(
            casa_id=p.casa_id,
            trasferta_id=p.trasferta_id,
            rivalita=_coppia(p.casa_id, p.trasferta_id) in derby,
            campo_caldo=p.casa_id in campi_caldi,
            arbitro=arbitro,
            medie=medie[chiave],
        )
    return risultato


def _contesto(
    s: Session,
    partita: Partita,
    prima_di: datetime,
    derby: set[frozenset[int]],
    campionato_id: int = SERIE_A,
) -> ContestoInfo:
    campo_caldo = partita.casa_id in rivalita.campi_caldi_noti(s, partita.stagione, prima_di)

    giocate = [
        (c, t, gc, gt)
        for c, t, gc, gt in s.execute(
            select(
                Partita.casa_id, Partita.trasferta_id, Partita.gol_casa, Partita.gol_trasferta
            ).where(
                Partita.competizione_id == campionato_id,
                Partita.stagione == partita.stagione,
                Partita.stato.in_(STATI_FINITI),
                Partita.data_utc < prima_di,
                Partita.gol_casa.is_not(None),
                Partita.gol_trasferta.is_not(None),
            )
        ).all()
    ]
    posta = {sq: posta_in_classifica(giocate, sq) for sq in (partita.casa_id, partita.trasferta_id)}
    punti_partita = _punti_partita(giocate, (partita.casa_id, partita.trasferta_id))

    precedenti = s.execute(
        select(Partita.id)
        .where(
            ((Partita.casa_id == partita.casa_id) & (Partita.trasferta_id == partita.trasferta_id))
            | ((Partita.casa_id == partita.trasferta_id) & (Partita.trasferta_id == partita.casa_id)),
            Partita.statistiche_scaricate.is_(True),
            Partita.data_utc < prima_di,
            Partita.id != partita.id,
        )
        .order_by(Partita.data_utc.desc())
        .limit(PRECEDENTI_MAX)
    ).scalars().all()
    totali = _totali_partite(s, list(precedenti))
    gialli_prec = [g for g, _ in totali.values()]
    return ContestoInfo(
        rivalita=_coppia(partita.casa_id, partita.trasferta_id) in derby,
        campo_caldo=campo_caldo,
        posta=posta,
        precedenti_n=len(totali),
        precedenti_gialli_medi=_media(gialli_prec),
        punti_partita=punti_partita,
    )


PARTITE_MINIME_PUNTI = 3


def _punti_partita(
    giocate: list[tuple[int, int, int, int]], squadre: tuple[int, int]
) -> dict[int, float]:
    """Punti per partita in campionato delle squadre con almeno 3 partite giocate."""
    punti = {sq: 0 for sq in squadre}
    partite = {sq: 0 for sq in squadre}
    for casa, trasferta, gc, gt in giocate:
        gc, gt = int(gc), int(gt)
        for sq, fatti, subiti in ((casa, gc, gt), (trasferta, gt, gc)):
            if sq in punti:
                partite[sq] += 1
                punti[sq] += 3 if fatti > subiti else 1 if fatti == subiti else 0
    return {
        sq: punti[sq] / partite[sq] for sq in squadre if partite[sq] >= PARTITE_MINIME_PUNTI
    }


def _da_formazione(s: Session, partita_id: int, squadra_id: int, tipo: str) -> list[Titolare]:
    righe = s.execute(
        select(Formazione, Giocatore)
        .join(Giocatore, Giocatore.id == Formazione.giocatore_id)
        .where(
            Formazione.partita_id == partita_id,
            Formazione.squadra_id == squadra_id,
            Formazione.tipo == tipo,
        )
        .order_by(Giocatore.id)
    ).all()
    return [titolare_da(g, squadra_id, f.griglia, None) for f, g in righe]


def _titolari(s: Session, partita: Partita, prima_di: datetime) -> list[Titolare]:
    risultato: list[Titolare] = []
    for squadra in (partita.casa_id, partita.trasferta_id):
        scelti = (
            _da_formazione(s, partita.id, squadra, "ufficiale")
            or _da_formazione(s, partita.id, squadra, "probabile")
            # senza ufficiali né probabili salvate: probabili calcolate, poi l'ultimo XI
            or probabili_automatiche(s, squadra, prima_di)
            or ultimo_xi(s, squadra, prima_di)
        )
        risultato.extend(scelti)
    return risultato


PARTITE_PANCHINA = 5  # con le probabili: entrati in almeno 2 delle ultime 5 di campionato
INGRESSI_MINIMI_PANCHINA = 2


def _panchina_salvata(s: Session, partita: Partita) -> dict[int, list[Titolare]]:
    """Panchina in distinta salvata con le formazioni ufficiali (una query per le due squadre)."""
    righe = s.execute(
        select(Formazione.squadra_id, Giocatore)
        .join(Giocatore, Giocatore.id == Formazione.giocatore_id)
        .where(Formazione.partita_id == partita.id, Formazione.tipo == "panchina")
        .order_by(Giocatore.id)
    ).all()
    risultato: dict[int, list[Titolare]] = {}
    for squadra_id, g in righe:
        risultato.setdefault(squadra_id, []).append(titolare_da(g, squadra_id, None, None))
    return risultato


def _panchina_automatica(
    s: Session, squadre: list[int], prima_di: datetime, stagione: int
) -> dict[int, list[Titolare]]:
    """Senza panchina nota: i giocatori della squadra entrati in campo (anche 1 minuto) in
    almeno 2 delle sue ultime 5 partite di campionato. Due query per tutte le squadre;
    i titolari vanno tolti da chi chiama."""
    risultato: dict[int, list[Titolare]] = {sq: [] for sq in squadre}
    if not squadre:
        return risultato
    partite = s.execute(
        select(Presenza.squadra_id, Presenza.partita_id, Partita.data_utc)
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(
            Presenza.squadra_id.in_(squadre),
            Partita.competizione_id.in_(CAMPIONATI),
            Partita.data_utc < prima_di,
            Partita.stagione.in_((stagione, stagione - 1)),
        )
        .distinct()
    ).all()
    per_squadra: dict[int, list[tuple[datetime, int]]] = {}
    for sq, pid, data in partite:
        per_squadra.setdefault(sq, []).append((data, pid))
    ultime = {
        sq: {pid for _, pid in sorted(lista, reverse=True)[:PARTITE_PANCHINA]}
        for sq, lista in per_squadra.items()
    }
    ids = set().union(*ultime.values()) if ultime else set()
    if not ids:
        return risultato
    righe = s.execute(
        select(Presenza.squadra_id, Presenza.partita_id, Presenza.ruolo, Giocatore)
        .join(Giocatore, Giocatore.id == Presenza.giocatore_id)
        .where(
            Presenza.partita_id.in_(ids),
            Presenza.squadra_id.in_(squadre),
            Presenza.minuti > 0,
        )
        .order_by(Giocatore.id)
    ).all()
    volte: dict[tuple[int, int], int] = {}
    giocatori: dict[int, Giocatore] = {}
    ruoli: dict[int, str | None] = {}
    for sq, pid, ruolo, g in righe:
        if pid not in ultime.get(sq, set()):
            continue
        volte[(sq, g.id)] = volte.get((sq, g.id), 0) + 1
        giocatori[g.id] = g
        ruoli[g.id] = ruoli.get(g.id) or ruolo
    for (sq, gid), n in sorted(volte.items()):
        if n >= INGRESSI_MINIMI_PANCHINA:
            risultato[sq].append(titolare_da(giocatori[gid], sq, None, ruoli.get(gid)))
    return risultato


def _panchina(
    s: Session, partita: Partita, prima_di: datetime, titolari: list[Titolare]
) -> list[Titolare]:
    """Panchinari delle due squadre: quelli in distinta salvati con le formazioni ufficiali,
    altrimenti (formazioni probabili) quelli calcolati dalle ultime partite. Mai un titolare."""
    squadre = [partita.casa_id, partita.trasferta_id]
    salvata = _panchina_salvata(s, partita)
    mancanti = [sq for sq in squadre if not salvata.get(sq)]
    automatica = (
        _panchina_automatica(s, mancanti, prima_di, partita.stagione) if mancanti else {}
    )
    in_campo = {t.giocatore_id for t in titolari}
    risultato: list[Titolare] = []
    for sq in squadre:
        for b in salvata.get(sq) or automatica.get(sq, []):
            if b.giocatore_id not in in_campo:
                risultato.append(b)
    return risultato


def _storico(
    s: Session,
    giocatori: list[int],
    stagione: int,
    prima_di: datetime,
    escludi_partita: int,
    derby: set[frozenset[int]],
) -> dict[int, list[RigaPresenza]]:
    storico: dict[int, list[RigaPresenza]] = {g: [] for g in giocatori}
    if not giocatori:
        return storico
    righe = s.execute(
        select(Presenza, Partita)
        .join(Partita, Partita.id == Presenza.partita_id)
        .where(
            Presenza.giocatore_id.in_(giocatori),
            Partita.data_utc < prima_di,
            Partita.id != escludi_partita,
            Partita.stagione.in_((stagione, stagione - 1, stagione - 2)),
        )
        .order_by(Partita.data_utc)
    ).all()
    for p, m in righe:
        avversario = m.trasferta_id if p.squadra_id == m.casa_id else m.casa_id
        storico[p.giocatore_id].append(
            RigaPresenza(
                partita_id=m.id,
                data=m.data_utc,
                stagione=m.stagione,
                competizione_id=m.competizione_id,
                squadra_id=p.squadra_id,
                avversario_id=avversario,
                minuti=p.minuti,
                gialli=p.gialli,
                rossi=p.rossi,
                falli_commessi=p.falli_commessi,
                falli_subiti=p.falli_subiti,
                dribbling_tentati=p.dribbling_tentati,
                dribbling_riusciti=p.dribbling_riusciti,
                tiri=p.tiri,
                gol=p.gol,
                assist=p.assist,
                voto=p.voto,
                titolare=p.titolare,
                rivalita=_coppia(p.squadra_id, avversario) in derby,
            )
        )
    return storico


def carica_dati(
    s: Session,
    partita_id: int,
    prima_di: datetime | None = None,
    titolari: list[Titolare] | None = None,
    *,
    con_panchina: bool = False,
    panchina: list[Titolare] | None = None,
) -> DatiPartita:
    """Snapshot della partita. Con `con_panchina` (o una `panchina` data, come nella prova
    storica) carica anche i panchinari, il loro storico e la tendenza dei cambi; senza, i
    dati dei titolari sono esattamente quelli di sempre."""
    partita = s.get(Partita, partita_id)
    if partita is None:
        raise ValueError(f"Partita {partita_id} non trovata")
    prima_di = prima_di or partita.data_utc
    derby = _derby(s)
    campionato_id = _campionato_partita(s, partita)

    if titolari is None:
        titolari = _titolari(s, partita, prima_di)
    if panchina is None and con_panchina:
        panchina = _panchina(s, partita, prima_di, titolari)
    panchina = panchina or []
    tendenze = (
        subentranti.tendenze_cambi(
            s, [partita.casa_id, partita.trasferta_id], prima_di, partita.stagione
        )
        if panchina else {}
    )
    prob_vittoria = (
        {partita.casa_id: float(partita.prob_casa), partita.trasferta_id: float(partita.prob_trasferta)}
        if panchina and partita.prob_casa is not None and partita.prob_trasferta is not None
        else {}
    )
    nomi = {
        sq.id: sq.nome
        for sq in s.execute(
            select(Squadra).where(Squadra.id.in_((partita.casa_id, partita.trasferta_id)))
        ).scalars()
    }
    duelli = {
        d.giocatore_id: d.avversario_id
        for d in s.execute(
            select(DuelloManuale).where(DuelloManuale.partita_id == partita.id)
        ).scalars()
    }
    return DatiPartita(
        partita_id=partita.id,
        data=partita.data_utc,
        stagione=partita.stagione,
        casa_id=partita.casa_id,
        trasferta_id=partita.trasferta_id,
        nomi_squadre=nomi,
        titolari=titolari,
        storico=_storico(
            s,
            [t.giocatore_id for t in titolari] + [b.giocatore_id for b in panchina],
            partita.stagione, prima_di, partita.id, derby,
        ),
        arbitro=_stat_arbitro(s, partita, prima_di),
        medie=_medie_campionato(s, partita.stagione, prima_di, campionato_id),
        contesto=_contesto(s, partita, prima_di, derby, campionato_id),
        duelli_manuali=duelli,
        campionato_id=campionato_id,
        panchina=panchina,
        tendenza_cambi=tendenze,
        prob_vittoria=prob_vittoria,
    )
