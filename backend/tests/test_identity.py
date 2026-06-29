from app.services.identity import normalize_email, normalize_phone


def test_gmail_dots_and_tags_normalized():
    assert normalize_email("John.Doe+promo@gmail.com") == "johndoe@gmail.com"
    assert normalize_email("johndoe@gmail.com") == "johndoe@gmail.com"


def test_plus_tag_dropped_for_all_domains():
    assert normalize_email("support+ticket@acme.com") == "support@acme.com"
    # Non-gmail keeps dots.
    assert normalize_email("first.last@acme.com") == "first.last@acme.com"


def test_phone_normalization():
    assert normalize_phone("+1 (415) 555-0117") == "4155550117"
    assert normalize_phone("415.555.0117") == "4155550117"
