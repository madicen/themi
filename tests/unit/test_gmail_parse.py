import base64
from datetime import UTC, datetime

from themi.connectors.gmail.parse import MAX_BODY, html_to_text, parse_message


def b64(text: str, encoding: str = "utf-8") -> str:
    return base64.urlsafe_b64encode(text.encode(encoding)).decode().rstrip("=")


HEADERS = [
    {"name": "From", "value": '"Pacific Gas" <Billing@PGE.example>'},
    {"name": "To", "value": "erin@gmail.com, Husband <him@gmail.com>"},
    {"name": "Cc", "value": "rentals@example.com"},
    {"name": "Subject", "value": "Your bill is ready"},
    {"name": "Message-ID", "value": "<abc123@pge.example>"},
]


def message(payload: dict, **extra) -> dict:
    return {
        "id": "m1",
        "threadId": "t1",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Your bill",
        "internalDate": "1792900000000",
        "payload": {"headers": HEADERS, **payload},
        **extra,
    }


def test_headers_and_dates() -> None:
    parsed = parse_message(message({"mimeType": "text/plain", "body": {"data": b64("Hi")}}))
    assert (parsed.from_name, parsed.from_address) == ("Pacific Gas", "billing@pge.example")
    assert parsed.to == ("erin@gmail.com", "him@gmail.com", "rentals@example.com")
    assert parsed.subject == "Your bill is ready"
    assert parsed.message_id_header == "<abc123@pge.example>"
    assert parsed.received_at == datetime.fromtimestamp(1792900000, UTC)
    assert parsed.label_ids == ("INBOX", "UNREAD") and parsed.thread_id == "t1"


def test_plain_text_is_preferred_over_html() -> None:
    parsed = parse_message(
        message(
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": b64("Amount due: $84.20")}},
                    {"mimeType": "text/html", "body": {"data": b64("<p>HTML version</p>")}},
                ],
            }
        )
    )
    assert parsed.text == "Amount due: $84.20"


def test_html_only_mail_is_stripped_to_text() -> None:
    html = (
        "<html><head><title>x</title><style>p{color:red}</style></head><body>"
        "<p>Hello&nbsp;Erin,</p><div>Your <b>order</b> shipped &amp; arrives Friday.</div>"
        "<script>alert('hi')</script><ul><li>Cat food</li><li>Rice</li></ul></body></html>"
    )
    parsed = parse_message(message({"mimeType": "text/html", "body": {"data": b64(html)}}))
    assert parsed.text == "Hello Erin,\n\nYour order shipped & arrives Friday.\n\nCat food\n\nRice"
    assert "alert" not in parsed.text and "color" not in parsed.text


def test_attachments_are_listed_not_downloaded() -> None:
    parsed = parse_message(
        message(
            {
                "mimeType": "multipart/mixed",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": b64("See attached.")}},
                    {
                        "mimeType": "application/pdf",
                        "filename": "lease.pdf",
                        "body": {"attachmentId": "a1", "size": 48213},
                    },
                ],
            }
        )
    )
    assert parsed.text == "See attached."
    ((attachment),) = parsed.attachments
    assert (attachment.filename, attachment.mime_type, attachment.size) == (
        "lease.pdf",
        "application/pdf",
        48213,
    )


def test_charsets_and_broken_data() -> None:
    latin = {
        "mimeType": "text/plain",
        "headers": [{"name": "Content-Type", "value": 'text/plain; charset="iso-8859-1"'}],
        "body": {"data": b64("Café crème", "iso-8859-1")},
    }
    assert parse_message(message(latin)).text == "Café crème"
    broken = {"mimeType": "text/plain", "body": {"data": "!!!not base64"}}
    assert parse_message(message(broken)).text == ""


def test_bodies_are_capped() -> None:
    huge = "word " * (MAX_BODY // 2)
    parsed = parse_message(message({"mimeType": "text/plain", "body": {"data": b64(huge)}}))
    assert len(parsed.text) == MAX_BODY


def test_html_to_text_keeps_line_structure() -> None:
    assert html_to_text("a<br>b<p>c</p>") == "a\nb\nc"
