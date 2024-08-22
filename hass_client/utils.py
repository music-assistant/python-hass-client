"""Various helpers and utilities."""

from __future__ import annotations

import asyncio
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

from aiohttp import ClientSession

if TYPE_CHECKING:
    from hass_client.models import TokenDetails


def get_websocket_url(url: str) -> str:
    """Extract Websocket URL from Home Assistant URL."""
    if not url or "://" not in url:
        msg = f"{url} is not a valid url"
        raise RuntimeError(msg)
    ws_url = url.replace("http", "ws")
    if not ws_url.endswith("/"):
        ws_url += "/"
    if not ws_url.endswith("/api/"):
        ws_url += "api/"
    return ws_url + "websocket"


def is_supervisor() -> bool:
    """Return if we're running inside the HA Supervisor (e.g. HAOS)."""
    try:
        urllib.request.urlopen("http://supervisor/core", timeout=1)
    except urllib.error.URLError as err:
        # this should return a 401 unauthorized if it exists
        return getattr(err, "code", 999) == 401
    except TimeoutError:
        return False
    return False


async def async_is_supervisor() -> bool:
    """Return if we're running inside the HA Supervisor (e.g. HAOS), async friendly."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, is_supervisor)


def get_auth_url(
    hass_url: str,
    redirect_uri: str,
    client_id: str | None = None,
    state: str | None = None,
) -> str:
    """
    Return URL to auth flow.

    The client ID you need to use is the website of your application.
    The redirect url has to be of the same host and port as the client ID.

    If client_id is omitted, it will be derived from the redirect url.

    https://developers.home-assistant.io/docs/auth_api#token
    """
    if not hass_url or "://" not in hass_url:
        msg = f"{hass_url} is not a valid url"
        raise RuntimeError(msg)
    url = hass_url
    if not url.endswith("/"):
        url += "/"
    if not client_id:
        client_id = base_url(redirect_uri)
    enc_client_id = urllib.parse.quote(client_id)
    enc_redirect_uri = urllib.parse.quote(redirect_uri)
    url += f"auth/authorize?client_id={enc_client_id}&redirect_uri={enc_redirect_uri}"
    if state:
        url += f"&state={state}"
    return url


async def get_token(
    hass_url: str, code: str, client_id: str, grant_type: str = "authorization_code"
) -> TokenDetails:
    """
    Return tokens given valid grants.

    The token endpoint returns tokens given valid grants.
    This grant is either an authorization code retrieved from the
    authorize endpoint or a refresh token.

    https://developers.home-assistant.io/docs/auth_api#token
    """
    if not hass_url or "://" not in hass_url:
        msg = f"{hass_url} is not a valid url"
        raise RuntimeError(msg)
    url = hass_url
    if not url.endswith("/"):
        url += "/"
    enc_client_id = urllib.parse.quote(client_id)
    url += "auth/token"
    body = f"grant_type={grant_type}&client_id={enc_client_id}"
    if grant_type == "authorization_code":
        body += f"&code={code}"
    elif grant_type == "refresh_token":
        body += f"&refresh_token={code}"

    async with ClientSession() as session:
        resp = await session.post(
            url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        result = await resp.json()
        if "error" in result:
            error_msg = result["error"]
            if error_desc := result.get("error_description"):
                error_msg += f": {error_desc}"
            raise RuntimeError(error_msg)
        return result


async def get_long_lived_token(
    hass_url: str,
    access_token: str,
    client_name: str,
    client_icon: str | None = None,
    lifespan: int = 365,
) -> str:
    """Request a Long Lived token with a short lived access token."""
    # prevent circular import
    # pylint: disable-next=import-outside-toplevel
    from .client import HomeAssistantClient

    ws_url = get_websocket_url(hass_url)
    async with HomeAssistantClient(ws_url, access_token) as hass:
        return await hass.send_command(
            "auth/long_lived_access_token",
            client_name=client_name,
            client_icon=client_icon,
            lifespan=lifespan,
        )


def base_url(url: str) -> str:
    """Get the base URL for given url."""
    parsed = urllib.parse.urlparse(url)
    parsed = parsed._replace(path="")
    parsed = parsed._replace(params="")
    parsed = parsed._replace(query="")
    parsed = parsed._replace(fragment="")
    return parsed.geturl()
