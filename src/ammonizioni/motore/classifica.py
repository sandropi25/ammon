import math
from dataclasses import replace

from ammonizioni.config import campionato_di
from ammonizioni.motore import affidabilita as aff, subentranti
from ammonizioni.motore.fattori.base import (
    MOTIVAZIONE_RITARDO,
    base_giocatore,
    tasso_base90,
    tasso_e_ritardo,
)
from ammonizioni.motore.fattori.arbitro import fattore_arbitro
from ammonizioni.motore.fattori.contesto import fattore_contesto
from ammonizioni.motore.fattori.duello import avversario_diretto, fattore_duello
from ammonizioni.motore.fattori.situazione import fattore_situazione
from ammonizioni.motore.fattori.storia import fattore_storia
from ammonizioni.motore.pesi import Pesi
from ammonizioni.motore.tipi import (
    Candidato,
    DatiPartita,
    Fattore,
    InfoSubentro,
    RigaPresenza,
)

MAX_MOTIVAZIONI = 3


def converti_quota(testo: str) -> float:
    """Converte "2,10" o "2.10" in numero; la quota deve essere maggiore di 1."""
    errore = ValueError("Quota non valida: deve essere un numero maggiore di 1")
    try:
        quota = float(str(testo).strip().replace(",", "."))
    except ValueError:
        raise errore from None
    if not math.isfinite(quota) or quota <= 1:
        raise errore
    return quota


def _motivazioni(fattori: list[Fattore], pesi: Pesi) -> list[str]:
    candidate: list[tuple[float, str]] = []
    for f in fattori:
        if f.motivazione is None:
            continue
        if f.nome == "base":
            # il testo di base c'e' solo se "in ritardo": peso fisso del bonus
            forza = abs(math.log(pesi.bonus_ritardo))
        else:
            forza = abs(math.log(f.valore))
        candidate.append((forza, f.motivazione))
    candidate.sort(key=lambda c: -c[0])  # sort stabile: a parita' resta l'ordine dei fattori
    return [testo for _, testo in candidate[:MAX_MOTIVAZIONI]]


def classifica(
    dati: DatiPartita, pesi: Pesi, quote: dict[int, float] | None = None
) -> list[Candidato]:
    """Candidati (portieri esclusi) in ordine di probabilita' decrescente."""
    quote = quote or {}
    medie = dati.medie
    per_id = {t.giocatore_id: t for t in dati.titolari}
    basso, alto = pesi.limiti_probabilita
    risultato: list[Candidato] = []

    for t in dati.titolari:
        if t.ruolo == "G":
            continue
        ruolo = t.ruolo if t.ruolo in medie.per_ruolo else "M"
        storico = dati.storico.get(t.giocatore_id, [])
        compagni = [x for x in dati.titolari if x.squadra_id == t.squadra_id]
        avversari = [x for x in dati.titolari if x.squadra_id != t.squadra_id]
        avversario_squadra = dati.trasferta_id if t.squadra_id == dati.casa_id else dati.casa_id

        avv_id = avversario_diretto(
            t, avversari, dati.duelli_manuali.get(t.giocatore_id), compagni=compagni
        )
        avv = per_id.get(avv_id) if avv_id is not None else None
        if avv is None:
            avv_id = None
        storico_avv = dati.storico.get(avv_id, []) if avv_id is not None else []

        # base e situazione: solo campionato della partita, sua coppa ed Europa (un altro
        # campionato ha un'altra severita'); la storia con l'avversario usa tutto lo storico
        storico_lega = [
            r for r in storico
            if campionato_di(r.competizione_id) in (None, dati.campionato_id)
        ]

        base = base_giocatore(storico_lega, ruolo, medie, dati.stagione, pesi)
        duello = fattore_duello(avv, storico_avv, medie, pesi)
        arbitro = fattore_arbitro(dati.arbitro, t.squadra_id, medie, pesi)
        contesto = fattore_contesto(dati.contesto, t.squadra_id, medie, pesi)
        storia = fattore_storia(
            storico,
            avversario_squadra,
            dati.contesto.rivalita,
            storico_avv,
            tasso_base90(storico_lega, ruolo, medie, dati.stagione, pesi),
            pesi,
            nome_avversario=dati.nomi_squadre.get(avversario_squadra, ""),
            nome_avv_diretto=avv.nome if avv else "",
        )
        situazione = fattore_situazione(storico_lega, dati.stagione, pesi, dati.campionato_id)
        fattori = [base, duello, arbitro, contesto, storia, situazione]

        p = base.valore
        for f in fattori[1:]:
            p *= f.valore
        p = max(basso, min(alto, p))

        if avv_id is None:
            certezza = aff.INCERTO
        elif dati.duelli_manuali.get(t.giocatore_id) is not None or dati.formazioni_ufficiali:
            certezza = aff.CERTO
        else:
            certezza = aff.PROBABILE
        affidabile = aff.calcola(
            storico=storico,
            data=dati.data,
            arbitro=dati.arbitro,
            formazione_ufficiale=dati.formazioni_ufficiali,
            avversario_squadra_id=avversario_squadra,
            nome_avversario=dati.nomi_squadre.get(avversario_squadra, ""),
            derby=dati.contesto.rivalita,
            avversario_diretto=certezza,
        )
        quota = quote.get(t.giocatore_id)
        prob_implicita = 1 / quota if quota else None
        risultato.append(
            Candidato(
                giocatore_id=t.giocatore_id,
                nome=t.nome,
                squadra_id=t.squadra_id,
                ruolo=t.ruolo,
                probabilita=p,
                motivazioni=_motivazioni(fattori, pesi),
                affidabilita=aff.vecchia_etichetta(affidabile.punti),
                avversario_diretto_id=avv_id,
                fattori=fattori,
                quota=quota if prob_implicita is not None else None,
                prob_implicita=prob_implicita,
                valore=p - prob_implicita if prob_implicita is not None else None,
                affidabilita_punti=affidabile.punti,
                affidabilita_motivi=affidabile.motivi,
            )
        )

    risultato.sort(key=lambda c: -c.probabilita)
    return risultato


MINUTI_MINIMI_MEDIE90 = 90  # sotto, gialli e falli per 90' non sono indicativi


def _per90(storico: list[RigaPresenza]) -> tuple[float | None, float | None]:
    """(gialli, falli) per 90' nei dati; ogni giallo conta, anche dalla panchina."""
    righe = [r for r in storico if r.minuti > 0 or r.gialli > 0]
    minuti = sum(r.minuti for r in righe)
    if minuti < MINUTI_MINIMI_MEDIE90:
        return None, None
    return (
        sum(r.gialli for r in righe) / minuti * 90,
        sum(r.falli_commessi for r in righe) / minuti * 90,
    )


def classifica_subentranti(
    dati: DatiPartita, pesi: Pesi, quote: dict[int, float] | None = None
) -> list[Candidato]:
    """Probabili subentranti (portieri esclusi) in ordine di probabilità decrescente: tutti
    quelli con probabilità di ingresso di almeno 0,15, anche se meno fallosi della media
    (lo dice solo l'evidenza "sopra la media"). Probabilità = ingresso ×
    (1 − e^(−gialli90 × minuti medi da subentrato / 90)) × arbitro, contesto, situazione,
    storia; niente duello (l'avversario diretto non si conosce). I titolari non cambiano."""
    quote = quote or {}
    medie = dati.medie
    basso, alto = pesi.limiti_probabilita
    risultato: list[tuple[float, Candidato]] = []  # (probabilità prima del limite, candidato)
    for b in dati.panchina:
        if b.ruolo == "G":
            continue
        ruolo = b.ruolo if b.ruolo in medie.per_ruolo else "M"
        storico = dati.storico.get(b.giocatore_id, [])
        storico_lega = [
            r for r in storico if campionato_di(r.competizione_id) in (None, dati.campionato_id)
        ]
        profilo = subentranti.profilo_subentro(b.giocatore_id, ruolo, storico_lega)
        if profilo is None or subentranti.non_entra_mai(profilo):
            continue
        e_sfavorita = subentranti.sfavorita(dati, b.squadra_id)
        tendenza = subentranti.fattori_tendenza(
            dati.tendenza_cambi.get(b.squadra_id, {}), e_sfavorita, pesi
        )
        ingresso = min(1.0, profilo.probabilita_ingresso * tendenza[ruolo])
        if ingresso < subentranti.SOGLIA_INGRESSO:
            continue

        avversario_squadra = dati.trasferta_id if b.squadra_id == dati.casa_id else dati.casa_id
        tasso, in_ritardo = tasso_e_ritardo(storico_lega, ruolo, medie, dati.stagione, pesi)
        in_campo = 1 - math.exp(-tasso * profilo.minuti_medi / 90)
        base = Fattore(
            "base", in_campo, MOTIVAZIONE_RITARDO if in_ritardo else None,
            sum(r.minuti for r in storico_lega),
        )
        fattore_ingresso = Fattore("ingresso", ingresso, None, profilo.panchine)
        arbitro = fattore_arbitro(dati.arbitro, b.squadra_id, medie, pesi)
        contesto = fattore_contesto(dati.contesto, b.squadra_id, medie, pesi)
        storia = fattore_storia(
            storico, avversario_squadra, dati.contesto.rivalita, [], tasso, pesi,
            nome_avversario=dati.nomi_squadre.get(avversario_squadra, ""),
        )
        # solo la diffida: "spesso sostituito presto" non vale per chi entra dalla panchina
        situazione = fattore_situazione(
            [replace(r, titolare=False) for r in storico_lega], dati.stagione, pesi,
            dati.campionato_id,
        )
        fattori = [base, fattore_ingresso, arbitro, contesto, storia, situazione]
        grezza = (
            ingresso * in_campo * arbitro.valore * contesto.valore * storia.valore
            * situazione.valore
        )
        p = max(basso, min(alto, grezza))

        sostituito = subentranti.titolare_da_sostituire(b, dati.titolari, dati.storico)
        gialli90, falli90 = _per90(storico_lega)
        media = medie.per_ruolo[ruolo]
        sopra = (gialli90 is not None and gialli90 > media.gialli90) or (
            falli90 is not None and falli90 > media.falli90
        )
        quota = quote.get(b.giocatore_id)
        prob_implicita = 1 / quota if quota else None
        info = InfoSubentro(
            probabilita_ingresso=ingresso,
            minuti_medi=profilo.minuti_medi,
            panchine=profilo.panchine,
            ingressi=profilo.ingressi,
            al_posto_di_id=sostituito.giocatore_id if sostituito else None,
            al_posto_di_nome=sostituito.nome if sostituito else None,
            gialli90=gialli90,
            falli90=falli90,
            media_gialli90=media.gialli90,
            media_falli90=media.falli90,
            sopra_media=sopra,
            sfavorita=e_sfavorita,
        )
        affidabile = aff.calcola(
            storico=storico,
            data=dati.data,
            arbitro=dati.arbitro,
            formazione_ufficiale=dati.formazioni_ufficiali,
            avversario_squadra_id=avversario_squadra,
            nome_avversario=dati.nomi_squadre.get(avversario_squadra, ""),
            derby=dati.contesto.rivalita,
            subentro=info,
            tendenza_nota=bool(dati.tendenza_cambi.get(b.squadra_id)),
        )
        candidato = Candidato(
            giocatore_id=b.giocatore_id,
            nome=b.nome,
            squadra_id=b.squadra_id,
            ruolo=b.ruolo,
            probabilita=p,
            motivazioni=_motivazioni([f for f in fattori if f.nome != "ingresso"], pesi),
            affidabilita=aff.vecchia_etichetta(affidabile.punti),
            avversario_diretto_id=None,
            fattori=fattori,
            quota=quota if prob_implicita is not None else None,
            prob_implicita=prob_implicita,
            valore=p - prob_implicita if prob_implicita is not None else None,
            subentro=info,
            affidabilita_punti=affidabile.punti,
            affidabilita_motivi=affidabile.motivi,
        )
        risultato.append((grezza, candidato))
    # molti subentranti stanno al 2% minimo: l'ordine usa la probabilità prima del limite
    risultato.sort(key=lambda x: (-x[0], x[1].giocatore_id))
    return [c for _, c in risultato]
