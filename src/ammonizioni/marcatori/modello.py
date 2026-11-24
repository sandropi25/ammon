"""Modello marcatori: probabilita' che un giocatore segni almeno un gol in una partita.

Tre pezzi, tutti con somme che decadono nel tempo (emivita in giorni):
1. gol attesi della squadra: media del campionato (casa/trasferta) x attacco della squadra x
   difesa dell'avversaria, ristretti verso la media con `prior_squadra` partite fittizie;
2. ritmo del giocatore (gol per 90'): gol e tiri (i tiri x conversione del campionato) con
   `prior_minuti` minuti fittizi al ritmo medio del suo ruolo nel campionato;
3. minuti attesi: media dei minuti da titolare o dalla panchina.
Attesi = ritmo x minuti/90 x (gol attesi squadra / media campionato); probabilita' con la
calibrazione logistica sul logaritmo degli attesi piu' i fattori di contesto (stessa logica dei
cartellini): forma recente (gol e tiri con emivita breve rispetto al ritmo di fondo), derby
(importanza della partita), rientro dopo un'assenza e minuti giocati negli ultimi 7 giorni
(condizione fisica). I pesi dei fattori si stimano sui dati e restano 0 se non servono. `Storico` si aggiorna partita dopo partita in
ordine di data: una previsione vede solo le partite gia' aggiunte."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, fields
from datetime import datetime

PROBABILITA_MASSIMA = 0.95
CHIAVE_COEFFICIENTI = "marcatori_coefficienti"  # Impostazione con i Parametri stimati
MEDIA_CASA, MEDIA_TRASFERTA = 1.5, 1.2  # gol a partita prima di avere dati del campionato
PRIOR_LEGA = 20  # partite fittizie per la media del campionato
CONVERSIONE_PREDEFINITA = 0.11  # gol per tiro
RITMO_RUOLO_PREDEFINITO = {"F": 0.35, "M": 0.12, "D": 0.04, "G": 0.0, "?": 0.10}
PRIOR_RUOLO_MINUTI = 9000  # minuti fittizi per il ritmo medio del ruolo
MINUTI_TITOLARE, PRIOR_TITOLARE = 80.0, 3.0
MINUTI_PANCHINA, PRIOR_PANCHINA = 8.0, 5.0
ATTESI_MINIMI = 1e-4


@dataclass(frozen=True)
class Parametri:
    emivita_giorni: float = 600.0
    prior_squadra: float = 8.0
    prior_minuti: float = 500.0
    peso_tiri: float = 0.7
    emivita_forma: float = 45.0
    prior_forma: float = 270.0  # minuti fittizi al ritmo di fondo nella forma recente
    a: float = 0.0  # p = sigmoide(a + b*log(attesi) + c_forma*forma + c_derby*derby + ...)
    b: float = 1.0
    c_forma: float = 0.0
    c_derby: float = 0.0
    c_rientro: float = 0.0
    c_fatica: float = 0.0

    def a_json(self) -> dict:
        return asdict(self)

    @classmethod
    def da_json(cls, valore: dict | None) -> "Parametri":
        nomi = {f.name for f in fields(cls)}
        return cls(**{k: float(v) for k, v in (valore or {}).items() if k in nomi})


def carica_parametri(s) -> Parametri:
    from ammonizioni.db import repo

    return Parametri.da_json(repo.leggi_impostazione(s, CHIAVE_COEFFICIENTI, None))


@dataclass(frozen=True)
class PartitaM:
    id: int
    data: datetime
    competizione_id: int
    stagione: int
    casa_id: int
    trasferta_id: int
    gol_casa: int | None = None
    gol_trasferta: int | None = None


@dataclass(frozen=True)
class PresenzaM:
    giocatore_id: int
    squadra_id: int
    titolare: bool
    ruolo: str | None
    minuti: int
    gol: int
    tiri: int


@dataclass(frozen=True)
class Giocante:
    giocatore_id: int
    squadra_id: int
    titolare: bool
    ruolo: str | None = None


@dataclass(frozen=True)
class Fattori:
    attesi: float
    forma: float  # log(ritmo recente / ritmo di fondo)
    derby: float  # 1 se derby
    rientro: float  # 1 se non gioca da almeno 21 giorni (ma ha uno storico)
    fatica: float  # minuti giocati negli ultimi 7 giorni / 90
    ritmo: float = 0.0  # gol a 90' stimati (gol e tiri, verso la media del ruolo): per l'app
    minuti_attesi: float = 0.0  # per l'app

    def vettore(self) -> tuple[float, ...]:
        return (math.log(self.attesi), self.forma, self.derby, self.rientro, self.fatica)


@dataclass(frozen=True)
class Previsione:
    giocatore_id: int
    squadra_id: int
    titolare: bool
    ruolo: str
    attesi: float
    probabilita: float
    fattori: Fattori | None = None


def _giorni(quando: datetime) -> float:
    return quando.timestamp() / 86400.0


def sigmoide(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x)) if x > -500 else 0.0


class _Decadute:
    """Somme che decadono: chiave -> [giorno ultimo aggiornamento, valori...]."""

    def __init__(self, emivita: float, n: int):
        self.emivita, self.n = emivita, n
        self.dati: dict = {}

    def _fattore(self, da: float, a: float) -> float:
        return 0.5 ** (max(a - da, 0.0) / self.emivita)

    def aggiungi(self, chiave, giorno: float, *valori: float) -> None:
        voce = self.dati.get(chiave)
        if voce is None:
            self.dati[chiave] = [giorno, *valori]
            return
        f = self._fattore(voce[0], giorno)
        voce[0] = giorno
        for i, v in enumerate(valori, 1):
            voce[i] = voce[i] * f + v

    def leggi(self, chiave, giorno: float) -> list[float]:
        voce = self.dati.get(chiave)
        if voce is None:
            return [0.0] * self.n
        f = self._fattore(voce[0], giorno)
        return [x * f for x in voce[1:]]


GIORNI_RIENTRO = 21
GIORNI_FATICA = 7


class Storico:
    def __init__(self, parametri: Parametri, derby: set[frozenset[int]] | None = None):
        self.p = parametri
        self.derby = derby or set()
        h = parametri.emivita_giorni
        self.forma = _Decadute(parametri.emivita_forma, 3)  # gol, tiri, minuti (recenti)
        self.ultima: dict[int, float] = {}  # giocatore -> giorno dell'ultima partita giocata
        self.recenti: dict[int, list[tuple[float, int]]] = defaultdict(list)  # (giorno, minuti)
        self.lega = _Decadute(h, 3)  # gol casa, gol trasferta, partite
        self.lega_tiri = _Decadute(h, 2)  # gol dei giocatori, tiri
        self.squadre = _Decadute(h, 3)  # gol fatti, gol subiti, partite
        self.ruoli = _Decadute(h, 2)  # (lega, ruolo): gol, minuti
        self.giocatori = _Decadute(h, 3)  # gol, tiri, minuti
        self.titolare = _Decadute(h, 2)  # minuti da titolare, presenze da titolare
        self.panchina = _Decadute(h, 2)  # minuti dalla panchina, volte in panchina
        self.ruolo_visto: dict[int, Counter] = defaultdict(Counter)
        self.partite_squadra: Counter = Counter()  # partite viste (senza decadimento)

    def ruolo(self, giocatore_id: int, ruolo: str | None = None) -> str:
        if ruolo in RITMO_RUOLO_PREDEFINITO:
            return ruolo
        visti = self.ruolo_visto.get(giocatore_id)
        return visti.most_common(1)[0][0] if visti else "?"

    def aggiorna(self, partita: PartitaM, presenze: list[PresenzaM]) -> None:
        if partita.gol_casa is None or partita.gol_trasferta is None:
            return
        g = _giorni(partita.data)
        comp = partita.competizione_id
        self.lega.aggiungi(comp, g, partita.gol_casa, partita.gol_trasferta, 1)
        self.squadre.aggiungi(partita.casa_id, g, partita.gol_casa, partita.gol_trasferta, 1)
        self.squadre.aggiungi(partita.trasferta_id, g, partita.gol_trasferta, partita.gol_casa, 1)
        self.partite_squadra.update((partita.casa_id, partita.trasferta_id))
        for pr in presenze:
            if pr.ruolo in RITMO_RUOLO_PREDEFINITO:
                self.ruolo_visto[pr.giocatore_id][pr.ruolo] += 1
        gol_tot = tiri_tot = 0
        for pr in presenze:
            ruolo = self.ruolo(pr.giocatore_id, pr.ruolo)
            if pr.titolare:
                self.titolare.aggiungi(pr.giocatore_id, g, pr.minuti, 1)
            else:
                self.panchina.aggiungi(pr.giocatore_id, g, pr.minuti, 1)
            if pr.minuti <= 0:
                continue
            self.giocatori.aggiungi(pr.giocatore_id, g, pr.gol, pr.tiri, pr.minuti)
            self.forma.aggiungi(pr.giocatore_id, g, pr.gol, pr.tiri, pr.minuti)
            self.ultima[pr.giocatore_id] = g
            recenti = self.recenti[pr.giocatore_id]
            recenti.append((g, pr.minuti))
            del recenti[:-4]
            self.ruoli.aggiungi((comp, ruolo), g, pr.gol, pr.minuti)
            gol_tot += pr.gol
            tiri_tot += pr.tiri
        self.lega_tiri.aggiungi(comp, g, gol_tot, tiri_tot)

    def gol_attesi(self, partita: PartitaM) -> tuple[float, float, float]:
        """(gol attesi casa, gol attesi trasferta, media gol per squadra del campionato)."""
        g = _giorni(partita.data)
        gc, gt, n = self.lega.leggi(partita.competizione_id, g)
        media_casa = (gc + MEDIA_CASA * PRIOR_LEGA) / (n + PRIOR_LEGA)
        media_trasf = (gt + MEDIA_TRASFERTA * PRIOR_LEGA) / (n + PRIOR_LEGA)
        media = (media_casa + media_trasf) / 2
        k = self.p.prior_squadra

        def forza(squadra_id):
            fatti, subiti, partite = self.squadre.leggi(squadra_id, g)
            att = (fatti + k * media) / (partite + k) / media
            dif = (subiti + k * media) / (partite + k) / media
            return att, dif

        att_c, dif_c = forza(partita.casa_id)
        att_t, dif_t = forza(partita.trasferta_id)
        return media_casa * att_c * dif_t, media_trasf * att_t * dif_c, media

    def prevedi(self, partita: PartitaM, rosa: list[Giocante]) -> list[Previsione]:
        """Previsioni dei giocatori in `rosa`, dalla piu' alla meno probabile."""
        p = self.p
        risultato = []
        for gioc, f in zip(rosa, self.fattori(partita, rosa)):
            x = f.vettore()
            logit = (p.a + p.b * x[0] + p.c_forma * x[1] + p.c_derby * x[2]
                     + p.c_rientro * x[3] + p.c_fatica * x[4])
            prob = min(sigmoide(logit), PROBABILITA_MASSIMA)
            risultato.append(Previsione(
                gioc.giocatore_id, gioc.squadra_id, gioc.titolare,
                self.ruolo(gioc.giocatore_id, gioc.ruolo), f.attesi, prob, f,
            ))
        return sorted(risultato, key=lambda x: -x.probabilita)

    def fattori(self, partita: PartitaM, rosa: list[Giocante]) -> list[Fattori]:
        g = _giorni(partita.data)
        comp = partita.competizione_id
        lam_casa, lam_trasf, media = self.gol_attesi(partita)
        gol_lega, tiri_lega = self.lega_tiri.leggi(comp, g)
        conv = (gol_lega + CONVERSIONE_PREDEFINITA * 200) / (tiri_lega + 200)
        derby = 1.0 if frozenset((partita.casa_id, partita.trasferta_id)) in self.derby else 0.0
        w, pm, pf = self.p.peso_tiri, self.p.prior_minuti, self.p.prior_forma
        risultato = []
        for gioc in rosa:
            gid = gioc.giocatore_id
            ruolo = self.ruolo(gid, gioc.ruolo)
            gol_r, min_r = self.ruoli.leggi((comp, ruolo), g)
            base = RITMO_RUOLO_PREDEFINITO[ruolo]
            ritmo_ruolo = (gol_r * 90 + base * PRIOR_RUOLO_MINUTI) / (min_r + PRIOR_RUOLO_MINUTI)
            gol, tiri, minuti = self.giocatori.leggi(gid, g)
            ritmo = ((1 - w) * gol + w * conv * tiri) * 90 / (minuti + pm) + ritmo_ruolo * pm / (minuti + pm)
            gol_f, tiri_f, min_f = self.forma.leggi(gid, g)
            recente = ((1 - w) * gol_f + w * conv * tiri_f) * 90 / (min_f + pf) + ritmo * pf / (min_f + pf)
            if gioc.titolare:
                m, n = self.titolare.leggi(gid, g)
                minuti_attesi = (m + MINUTI_TITOLARE * PRIOR_TITOLARE) / (n + PRIOR_TITOLARE)
            else:
                m, n = self.panchina.leggi(gid, g)
                minuti_attesi = (m + MINUTI_PANCHINA * PRIOR_PANCHINA) / (n + PRIOR_PANCHINA)
            lam = lam_casa if gioc.squadra_id == partita.casa_id else lam_trasf
            attesi = max(ritmo * minuti_attesi / 90 * lam / media, ATTESI_MINIMI)
            ultima = self.ultima.get(gid)
            rientro = 1.0 if ultima is not None and g - ultima >= GIORNI_RIENTRO else 0.0
            fatica = sum(m for d, m in self.recenti.get(gid, []) if g - d <= GIORNI_FATICA) / 90
            forma = math.log(max(recente, 1e-6) / max(ritmo, 1e-6))
            risultato.append(Fattori(attesi, forma, derby, rientro, fatica, ritmo, minuti_attesi))
        return risultato
