"""Caricamento dal DB dello snapshot di una partita. Ogni query vede solo righe con
Partita.data_utc < prima_di (default: calcio d'inizio), cosi' la prova storica non vede il futuro."""
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ammonizioni.caricamento.formazioni import titolare_da, ultimo_xi
from ammonizioni.config import CAMPIONATI, SERIE_A, STATI_FINITI, campionato_di
from ammonizioni.db.modelli import (
    DuelloManuale,
    Formazione,
    Giocatore,
    ListaManuale,
    Partita,
    Presenza,
    Squadra,
    Arbitro,
)
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
    righe = s.execute(
        select(ListaManuale.squadra_a_id, ListaManuale.squadra_b_id).where(
            ListaManuale.tipo == "derby", ListaManuale.squadra_b_id.is_not(None)
        )
    ).all()
    return {_coppia(a, b) for a, b in righe}


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
    gialli = [totali[p.id][0] for p in sue if p.id in totali]
    falli = [totali[p.id][1] for p in sue if p.id in totali]
    con: dict[int, tuple[float, int]] = {}
    for squadra in {p.casa_id for p in sue} | {p.trasferta_id for p in sue}:
        g = [
            totali[p.id][0]
            for p in sue
            if p.id in totali and squadra in (p.casa_id, p.trasferta_id)
        ]
        con[squadra] = (sum(g) / len(g), len(g)) if g else (0.0, 0)
    return StatArbitro(
        nome=arbitro.nome_visualizzato if arbitro else "",
        partite=len(gialli),
        gialli_medi=_media(gialli) or 0.0,
        falli_medi=_media(falli) or 0.0,
        gialli_medi_con={q: v for q, v in con.items() if v[1] > 0},
    )


def _contesto(
    s: Session,
    partita: Partita,
    prima_di: datetime,
    derby: set[frozenset[int]],
    campionato_id: int = SERIE_A,
) -> ContestoInfo:
    campo_caldo = s.execute(
        select(ListaManuale.id).where(
            ListaManuale.tipo == "campo_caldo", ListaManuale.squadra_a_id == partita.casa_id
        )
    ).first() is not None

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
    )


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
            or ultimo_xi(s, squadra, prima_di)
        )
        risultato.extend(scelti)
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
) -> DatiPartita:
    partita = s.get(Partita, partita_id)
    if partita is None:
        raise ValueError(f"Partita {partita_id} non trovata")
    prima_di = prima_di or partita.data_utc
    derby = _derby(s)
    campionato_id = _campionato_partita(s, partita)

    if titolari is None:
        titolari = _titolari(s, partita, prima_di)
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
            s, [t.giocatore_id for t in titolari], partita.stagione, prima_di, partita.id, derby
        ),
        arbitro=_stat_arbitro(s, partita, prima_di),
        medie=_medie_campionato(s, partita.stagione, prima_di, campionato_id),
        contesto=_contesto(s, partita, prima_di, derby, campionato_id),
        duelli_manuali=duelli,
        campionato_id=campionato_id,
    )
