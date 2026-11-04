from ammonizioni.scheduler import comune


def test_crea_limite_valori_predefiniti(sessione, monkeypatch):
    monkeypatch.delenv("API_RICHIESTE_GIORNO", raising=False)
    monkeypatch.delenv("API_RISERVA_OGGI", raising=False)
    limite = comune.crea_limite(sessione)
    assert (limite.max_giorno, limite.riserva_oggi, limite.max_minuto) == (100, 30, 10)


def test_crea_limite_da_variabili_ambiente(sessione, monkeypatch):
    monkeypatch.setenv("API_RICHIESTE_GIORNO", "7500")
    monkeypatch.setenv("API_RISERVA_OGGI", "500")
    limite = comune.crea_limite(sessione)
    assert (limite.max_giorno, limite.riserva_oggi) == (7500, 500)


def test_crea_limite_variabili_vuote_usano_i_predefiniti(sessione, monkeypatch):
    monkeypatch.setenv("API_RICHIESTE_GIORNO", "")
    monkeypatch.setenv("API_RISERVA_OGGI", "")
    limite = comune.crea_limite(sessione)
    assert (limite.max_giorno, limite.riserva_oggi) == (100, 30)
