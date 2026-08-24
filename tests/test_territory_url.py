from stato_italia.territories import boundary_url


def test_istat_url_eras_are_explicit() -> None:
    assert boundary_url(2006).endswith("generalizzati/Limiti01012006_g.zip")
    assert boundary_url(2021).endswith("generalizzati/Limiti2021_g.zip")
    assert boundary_url(2024).endswith("generalizzati/2024/Limiti01012024_g.zip")
    assert boundary_url(2025).endswith("generalizzati/2025/Limiti01012025_g.zip")
