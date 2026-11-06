import ssl

from themi.http import tls


def test_one_verifying_context_is_shared() -> None:
    context = tls()
    assert context is tls()
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert context.cert_store_stats()["x509_ca"] > 0  # the CA bundle is loaded
