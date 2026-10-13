from app import platforms


URL = 'https://www.julajups.sv/anuncio/toyota-4-runner-trd-2019-4x4-N3tSneYO52'


def test_individual_julajups_url_supported_in_readonly_pilot():
    assert platforms.is_allowed(URL)
    assert platforms.is_listing_url(URL)
    assert platforms.is_readonly_public_pilot(URL)


def test_julajups_catalog_not_accepted():
    assert not platforms.is_listing_url('https://www.julajups.sv/anuncio/')
    assert not platforms.is_listing_url('https://www.julajups.sv/')
    assert not platforms.is_listing_url('https://www.julajups.sv/anuncio/foo/extra')


def test_julajups_non_https_and_custom_ports_denied():
    assert not platforms.is_allowed('http://www.julajups.sv/anuncio/foo')
    assert not platforms.is_allowed('https://www.julajups.sv:444/anuncio/foo')
