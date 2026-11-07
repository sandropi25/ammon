"""Modelli SQLAlchemy. Le chiavi primarie sono gli id API-Football dove esistono."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


class DataOraUTC(TypeDecorator):
    """Datetime sempre aware UTC: rifiuta i naive in scrittura, restituisce aware UTC in lettura."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime senza fuso orario: usa un datetime aware UTC")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class Squadra(Base):
    __tablename__ = "squadre"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    nome: Mapped[str] = mapped_column(String)
    # stemma (URL del CDN ESPN, caricato dal browser) e colori "#RRGGBB" della squadra
    logo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    colore: Mapped[str | None] = mapped_column(String, nullable=True)
    colore_alt: Mapped[str | None] = mapped_column(String, nullable=True)


class Giocatore(Base):
    __tablename__ = "giocatori"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    nome: Mapped[str] = mapped_column(String)
    ruolo: Mapped[str | None] = mapped_column(String(1), nullable=True)  # G, D, M, F
    sofascore_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Biografia (job notturno, al più una volta al mese): anagrafica da ESPN, breve profilo
    # da Wikipedia (testo CC BY-SA: si mostra sempre con link e "Fonte: Wikipedia").
    data_nascita: Mapped[date | None] = mapped_column(Date, nullable=True)
    nazionalita: Mapped[str | None] = mapped_column(String, nullable=True)
    altezza_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    posizione: Mapped[str | None] = mapped_column(String, nullable=True)
    wiki_titolo: Mapped[str | None] = mapped_column(String, nullable=True)
    wiki_url: Mapped[str | None] = mapped_column(String, nullable=True)
    wiki_estratto: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ultimo tentativo (anche senza risultati): si riprova solo dopo un mese
    bio_aggiornata: Mapped[datetime | None] = mapped_column(DataOraUTC, nullable=True)
    # Foto (ritaglio senza sfondo) da TheSportsDB; foto_controllata = ultimo tentativo,
    # anche senza risultato (si riprova dopo 30 giorni, con foto dopo 90)
    foto_url: Mapped[str | None] = mapped_column(String, nullable=True)
    foto_controllata: Mapped[datetime | None] = mapped_column(DataOraUTC, nullable=True)


class Arbitro(Base):
    __tablename__ = "arbitri"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome_normalizzato: Mapped[str] = mapped_column(String, unique=True)
    nome_visualizzato: Mapped[str] = mapped_column(String)


class Partita(Base):
    __tablename__ = "partite"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    data_utc: Mapped[datetime] = mapped_column(DataOraUTC)
    competizione_id: Mapped[int] = mapped_column(Integer)
    stagione: Mapped[int] = mapped_column(Integer)
    giornata: Mapped[int | None] = mapped_column(Integer, nullable=True)
    casa_id: Mapped[int] = mapped_column(ForeignKey("squadre.id"))
    trasferta_id: Mapped[int] = mapped_column(ForeignKey("squadre.id"))
    arbitro_id: Mapped[int | None] = mapped_column(ForeignKey("arbitri.id"), nullable=True)
    gol_casa: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gol_trasferta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stato: Mapped[str] = mapped_column(String, default="NS")  # NS, FT, PST, CANC, ...
    stato_formazioni: Mapped[str] = mapped_column(String, default="probabili")  # probabili | ufficiali
    statistiche_scaricate: Mapped[bool] = mapped_column(Boolean, default=False)
    # Probabilità implicite 1X2 prima della partita (quote ESPN, normalizzate a somma 1):
    # per ora solo salvate (servono a capire quale squadra è sfavorita).
    prob_casa: Mapped[float | None] = mapped_column(Float, nullable=True)
    prob_pareggio: Mapped[float | None] = mapped_column(Float, nullable=True)
    prob_trasferta: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Cartellini e falli totali della partita (entrambe le squadre, panchina compresa): dalle
    # presenze se ci sono le statistiche dei giocatori, altrimenti dal tabellone ESPN.
    # None = dato non noto (diverso da 0).
    gialli_totali: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rossi_totali: Mapped[int | None] = mapped_column(Integer, nullable=True)
    falli_totali: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Presenza(Base):
    __tablename__ = "presenze"
    partita_id: Mapped[int] = mapped_column(ForeignKey("partite.id"), primary_key=True)
    giocatore_id: Mapped[int] = mapped_column(ForeignKey("giocatori.id"), primary_key=True)
    squadra_id: Mapped[int] = mapped_column(ForeignKey("squadre.id"))
    titolare: Mapped[bool] = mapped_column(Boolean, default=False)
    ruolo: Mapped[str | None] = mapped_column(String(1), nullable=True)
    griglia: Mapped[str | None] = mapped_column(String, nullable=True)
    minuti: Mapped[int] = mapped_column(Integer, default=0)
    gialli: Mapped[int] = mapped_column(Integer, default=0)
    rossi: Mapped[int] = mapped_column(Integer, default=0)
    falli_commessi: Mapped[int] = mapped_column(Integer, default=0)
    falli_subiti: Mapped[int] = mapped_column(Integer, default=0)
    dribbling_tentati: Mapped[int] = mapped_column(Integer, default=0)
    dribbling_riusciti: Mapped[int] = mapped_column(Integer, default=0)
    tiri: Mapped[int] = mapped_column(Integer, default=0)
    gol: Mapped[int] = mapped_column(Integer, default=0)
    assist: Mapped[int] = mapped_column(Integer, default=0)
    voto: Mapped[float | None] = mapped_column(Float, nullable=True)
    maglia: Mapped[int | None] = mapped_column(Integer, nullable=True)  # numero di maglia


class Formazione(Base):
    """Formazione probabile o ufficiale; la probabile resta salvata per il riepilogo cambi."""
    __tablename__ = "formazioni"
    partita_id: Mapped[int] = mapped_column(ForeignKey("partite.id"), primary_key=True)
    squadra_id: Mapped[int] = mapped_column(ForeignKey("squadre.id"), primary_key=True)
    giocatore_id: Mapped[int] = mapped_column(ForeignKey("giocatori.id"), primary_key=True)
    # probabile | ufficiale | panchina (panchinari in distinta con la formazione ufficiale)
    tipo: Mapped[str] = mapped_column(String, primary_key=True)
    griglia: Mapped[str | None] = mapped_column(String, nullable=True)
    maglia: Mapped[int | None] = mapped_column(Integer, nullable=True)  # numero di maglia


class ListaManuale(Base):
    __tablename__ = "liste_manuali"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tipo: Mapped[str] = mapped_column(String)  # derby | campo_caldo
    squadra_a_id: Mapped[int] = mapped_column(ForeignKey("squadre.id"))
    squadra_b_id: Mapped[int | None] = mapped_column(ForeignKey("squadre.id"), nullable=True)


class DuelloManuale(Base):
    __tablename__ = "duelli_manuali"
    partita_id: Mapped[int] = mapped_column(ForeignKey("partite.id"), primary_key=True)
    giocatore_id: Mapped[int] = mapped_column(ForeignKey("giocatori.id"), primary_key=True)
    avversario_id: Mapped[int] = mapped_column(ForeignKey("giocatori.id"), primary_key=True)


class Segnalazione(Base):
    __tablename__ = "segnalazioni"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    partita_id: Mapped[int] = mapped_column(ForeignKey("partite.id"))
    giocatore_id: Mapped[int] = mapped_column(ForeignKey("giocatori.id"))
    fonte: Mapped[str] = mapped_column(String)  # "io", "modello", nome tipster
    quota: Mapped[float | None] = mapped_column(Float, nullable=True)


class Giocata(Base):
    __tablename__ = "giocate"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    data: Mapped[date] = mapped_column(Date)
    partita_id: Mapped[int] = mapped_column(ForeignKey("partite.id"))
    giocatore_id: Mapped[int] = mapped_column(ForeignKey("giocatori.id"))
    fonte: Mapped[str] = mapped_column(String)
    quota: Mapped[float] = mapped_column(Float)
    puntata: Mapped[float] = mapped_column(Float)
    esito: Mapped[str] = mapped_column(String, default="in_attesa")  # in_attesa|vinta|persa|rimborsata


class ContatoreRichieste(Base):
    __tablename__ = "contatore_richieste"
    giorno: Mapped[date] = mapped_column(Date, primary_key=True)
    usate: Mapped[int] = mapped_column(Integer, default=0)


class Impostazione(Base):
    __tablename__ = "impostazioni"
    chiave: Mapped[str] = mapped_column(String, primary_key=True)
    valore_json: Mapped[object] = mapped_column(JSON, nullable=True)


class UltimoAggiornamento(Base):
    __tablename__ = "ultimi_aggiornamenti"
    job: Mapped[str] = mapped_column(String, primary_key=True)
    quando_utc: Mapped[datetime] = mapped_column(DataOraUTC)
    completo: Mapped[bool] = mapped_column(Boolean, default=False)
