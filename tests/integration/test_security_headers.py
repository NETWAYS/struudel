from flask.testing import FlaskClient


def test_csp_header_set_on_response(client: FlaskClient) -> None:
    resp = client.get("/_health/live")
    csp = resp.headers.get("Content-Security-Policy")
    assert csp is not None
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_companion_security_headers(client: FlaskClient) -> None:
    resp = client.get("/_health/live")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert resp.headers.get("X-Frame-Options") == "DENY"
