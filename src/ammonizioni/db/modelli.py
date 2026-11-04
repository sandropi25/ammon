"""Modelli SQLAlchemy. Le chiavi primarie sono gli id API-Football dove esistono."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String
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


class Giocatore(Base):
    __tablename__ = "giocatori"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    nome: Mapped[str] = mapped_column(String)
    ruolo: Mapped[str | None] = mapped_column(String(1), nullable=True)  # G, D, M, F
    sofascore_url: Mapped[str | None] = mapped_column(String, nullable=True)


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


class Formazione(Base):
    """Formazione probabile o ufficiale; la probabile resta salvata per il riepilogo cambi."""
    __tablename__ = "formazioni"
    partita_id: Mapped[int] = mapped_column(ForeignKey("partite.id"), primary_key=True)
    squadra_id: Mapped[int] = mapped_column(ForeignKey("squadre.id"), primary_key=True)
    giocatore_id: Mapped[int] = mapped_column(ForeignKey("giocatori.id"), primary_key=True)
    tipo: Mapped[str] = mapped_column(String, primary_key=True)  # probabile | ufficiale
    griglia: Mapped[str | None] = mapped_column(String, nullable=True)


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
