from app.redaction import redact, unredact


def test_email_redacted_and_restored():
    text = "Contact me at sarah.chen@acme.com about order 123."
    r = redact(text)
    assert "sarah.chen@acme.com" not in r.text
    assert "<EMAIL_1>" in r.text
    assert unredact(r.text, r.mapping) == text


def test_phone_and_card_and_ssn_redacted():
    text = "Call +1 415-555-0117, card 4242 4242 4242 4242, ssn 123-45-6789."
    r = redact(text)
    assert "415-555-0117" not in r.text
    assert "4242 4242 4242 4242" not in r.text
    assert "123-45-6789" not in r.text
    assert unredact(r.text, r.mapping) == text


def test_same_value_same_token():
    text = "a@x.com wrote to a@x.com"
    r = redact(text)
    assert r.text.count("<EMAIL_1>") == 2
    assert len(r.mapping) == 1
