"""Tests for the WhatsApp click-to-chat adapter and the QR payload builder.

Both are pure functions that turn a value the product knows into a string another system will parse,
and both have one failure mode that matters: a payload that looks right and is not.

**The link survives punctuation.** A product called `Beans & Rice (5kg)` and an inquiry with a
newline in it must produce a link that opens with the text intact. The ampersand is the interesting
one: unescaped, it ends the message and starts a parameter, and the link still "works" - it just
says something else.

**The number is refused rather than guessed at.** The adapter is handed the international dialling
form, and a value that is not it is refused with a sentence about what a dialling number is. A
`wa.me` URL with a malformed number opens WhatsApp on an error screen, which looks like the product
is broken rather than the number.

**The QR payload is a public address and nothing else.** A shop, a product, a shared invoice. An
admin path, a query string and a fragment are refused, because a printed code is read by a camera
and shown to whoever is holding it - and a code whose payload nobody reviewed is a code that
publishes whatever somebody passed.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from ahia.core.errors import InvalidInputError
from ahia.integrations.qr.qr_payload import (
    MAXIMUM_PAYLOAD_LENGTH,
    PUBLIC_PATH_PREFIXES,
    build_qr_payload,
)
from ahia.integrations.whatsapp.click_to_chat import (
    MAXIMUM_MESSAGE_LENGTH,
    build_click_to_chat_link,
    product_inquiry_message,
)
from ahia.models.entities.phone_number import international_digits_for

BASE = "https://ahia.app"


# ---------------------------------------------------------------------------
# The WhatsApp link
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_local_number_becomes_the_dialling_form() -> None:
    assert international_digits_for("0803 123 4567", default_country_code="+234") == "2348031234567"
    assert (
        international_digits_for("+2348031234567", default_country_code="+234") == "2348031234567"
    )


@pytest.mark.unit
def test_a_number_that_states_its_country_is_left_alone() -> None:
    """Guessing a country for a number that states one would corrupt it silently."""
    assert international_digits_for("+4480812345", default_country_code="+234") == "4480812345"


@pytest.mark.unit
def test_a_number_that_could_not_be_dialled_produces_nothing() -> None:
    assert international_digits_for("call the shop", default_country_code="+234") is None
    assert international_digits_for("123", default_country_code="+234") is None


@pytest.mark.unit
def test_a_link_addresses_the_number_and_carries_the_message() -> None:
    link = build_click_to_chat_link(
        whatsapp_number="2348031234567", message="Hello, is the rice available?"
    )

    parsed = urlparse(link.url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "wa.me"
    assert parsed.path == "/2348031234567"
    assert parse_qs(parsed.query)["text"] == ["Hello, is the rice available?"]
    assert link.whatsapp_number == "2348031234567"


@pytest.mark.unit
def test_the_message_survives_punctuation_and_newlines() -> None:
    """An unescaped ampersand ends the message and starts a parameter, and the link still opens."""
    message = "Beans & Rice (5kg)\nIs it in stock? #urgent"

    link = build_click_to_chat_link(whatsapp_number="2348031234567", message=message)

    assert parse_qs(urlparse(link.url).query)["text"] == [message]
    assert "#" not in link.url, "a fragment never reaches the server"
    assert link.url.count("?") == 1


@pytest.mark.unit
def test_a_product_name_with_punctuation_survives_the_inquiry_message() -> None:
    message = product_inquiry_message(
        business_name="Obi & Sons",
        product_name="Beans & Rice (5kg)",
        product_url=f"{BASE}/shop/obi-sons/product/beans-rice",
        price_text="4500.00",
    )

    link = build_click_to_chat_link(whatsapp_number="2348031234567", message=message)

    assert parse_qs(urlparse(link.url).query)["text"] == [message]
    assert "Obi & Sons" in message
    assert "4500.00" in message


@pytest.mark.unit
def test_a_number_that_is_not_the_dialling_form_is_refused() -> None:
    with pytest.raises(InvalidInputError, match="7 to 15 digits"):
        build_click_to_chat_link(whatsapp_number="+234 803 123 4567", message="Hello")

    with pytest.raises(InvalidInputError, match="7 to 15 digits"):
        build_click_to_chat_link(whatsapp_number="123456", message="Hello")


@pytest.mark.unit
def test_an_empty_or_oversized_message_is_refused() -> None:
    with pytest.raises(InvalidInputError, match="needs a message"):
        build_click_to_chat_link(whatsapp_number="2348031234567", message="   ")

    with pytest.raises(InvalidInputError, match="exceeds"):
        build_click_to_chat_link(
            whatsapp_number="2348031234567", message="x" * (MAXIMUM_MESSAGE_LENGTH + 1)
        )


@pytest.mark.unit
def test_the_error_does_not_repeat_the_number_that_failed() -> None:
    """A phone number in a log line outlives the request that contained it."""
    with pytest.raises(InvalidInputError) as raised:
        build_click_to_chat_link(whatsapp_number="+2348031234567", message="Hello")

    assert "2348031234567" not in str(raised.value)


@pytest.mark.unit
def test_the_base_url_comes_from_configuration() -> None:
    link = build_click_to_chat_link(
        whatsapp_number="2348031234567",
        message="Hello",
        base_url="https://wa.example.test/",
    )

    assert link.url.startswith("https://wa.example.test/2348031234567?text=")


# ---------------------------------------------------------------------------
# The QR payload
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_a_shop_address_becomes_an_absolute_url() -> None:
    payload = build_qr_payload(path="/shop/obi-electronics", base_url=BASE)

    assert payload.payload == f"{BASE}/shop/obi-electronics"
    assert payload.public_url == payload.payload
    assert payload.path == "/shop/obi-electronics"


@pytest.mark.unit
def test_a_product_and_a_shared_invoice_are_both_encodable() -> None:
    product = build_qr_payload(path="/shop/obi/product/beans-rice", base_url=BASE)
    invoice = build_qr_payload(path="/share/bFnmFH8Ndptr", base_url=BASE)

    assert product.payload.endswith("/shop/obi/product/beans-rice")
    assert invoice.payload.endswith("/share/bFnmFH8Ndptr")


@pytest.mark.unit
def test_a_path_this_product_does_not_publish_is_refused() -> None:
    """A convenience that encodes whatever it is handed encodes an admin URL one day."""
    for path in ("/admin/users", "/api/v1/tenants", "shop/obi", "https://elsewhere.test/shop/obi"):
        with pytest.raises(InvalidInputError):
            build_qr_payload(path=path, base_url=BASE)


@pytest.mark.unit
def test_a_query_string_or_a_fragment_is_refused() -> None:
    with pytest.raises(InvalidInputError, match="no query string"):
        build_qr_payload(path="/shop/obi?tenant=1", base_url=BASE)

    with pytest.raises(InvalidInputError, match="no query string"):
        build_qr_payload(path="/shop/obi#top", base_url=BASE)


@pytest.mark.unit
def test_a_payload_too_long_to_scan_is_refused() -> None:
    long_path = "/shop/" + "a" * (MAXIMUM_PAYLOAD_LENGTH + 10)

    with pytest.raises(InvalidInputError, match="would not scan"):
        build_qr_payload(path=long_path, base_url=BASE)


@pytest.mark.unit
def test_the_public_path_prefixes_are_the_ones_this_product_serves() -> None:
    """The closed set, asserted so that adding a public surface is a decision somebody makes."""
    assert set(PUBLIC_PATH_PREFIXES) == {"/shop/", "/share/"}


@pytest.mark.unit
def test_the_payload_base_is_configuration_rather_than_a_constant() -> None:
    """A deployment that moves its domain changes one setting, not every poster on a wall."""
    payload = build_qr_payload(path="/shop/obi", base_url="https://shop.example.test/")

    assert payload.payload == "https://shop.example.test/shop/obi"
