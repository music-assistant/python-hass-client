"""Tests for the auth helpers in hass_client.utils."""

from unittest.mock import AsyncMock, MagicMock, patch

from hass_client.utils import get_auth_url, get_token


def test_get_auth_url_without_pkce() -> None:
    """Test that the auth URL carries no PKCE parameters by default."""
    url = get_auth_url("https://ha.example.com", "https://ma.example.com/cb", state="abc")

    assert url == (
        "https://ha.example.com/auth/authorize?client_id=https%3A//ma.example.com"
        "&redirect_uri=https%3A//ma.example.com/cb&state=abc"
    )


def test_get_auth_url_with_pkce() -> None:
    """Test that a code challenge is added with the S256 method."""
    url = get_auth_url(
        "https://ha.example.com/",
        "https://ma.example.com/cb",
        state="abc",
        code_challenge="E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
    )

    assert url.endswith(
        "&state=abc&code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        "&code_challenge_method=S256"
    )


def test_get_auth_url_encodes_state() -> None:
    """Test that reserved characters in the state are percent-encoded."""
    url = get_auth_url("https://ha.example.com", "https://ma.example.com/cb", state="a&b=c+d#e/f")

    assert url.endswith("&state=a%26b%3Dc%2Bd%23e%2Ff")


async def _post_body(code: str = "the-code", **kwargs: str) -> str:
    """Call get_token against a mocked session and return the posted body."""
    resp = MagicMock()
    resp.json = AsyncMock(return_value={"access_token": "token"})
    session = MagicMock()
    session.post = AsyncMock(return_value=resp)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    with patch("hass_client.utils.ClientSession", return_value=session):
        result = await get_token("https://ha.example.com", code, "https://ma.example.com", **kwargs)
    assert result == {"access_token": "token"}
    return str(session.post.call_args.kwargs["data"])


async def test_get_token_without_pkce() -> None:
    """Test that the token request carries no code verifier by default."""
    body = await _post_body()

    assert body == "grant_type=authorization_code&client_id=https%3A//ma.example.com&code=the-code"


async def test_get_token_with_pkce() -> None:
    """Test that the code verifier is sent with the authorization code."""
    body = await _post_body(code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")

    assert body.endswith("&code=the-code&code_verifier=dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")


async def test_get_token_encodes_code() -> None:
    """Test that reserved characters in the authorization code are percent-encoded."""
    body = await _post_body(code="a&b=c+d#e/f")

    assert body.endswith("&code=a%26b%3Dc%2Bd%23e%2Ff")


async def test_get_token_refresh() -> None:
    """Test that a refresh grant sends an encoded refresh token and no code verifier."""
    body = await _post_body(
        code="a&b=c+d#e/f", grant_type="refresh_token", code_verifier="the-verifier"
    )

    assert body == (
        "grant_type=refresh_token&client_id=https%3A//ma.example.com"
        "&refresh_token=a%26b%3Dc%2Bd%23e%2Ff"
    )
