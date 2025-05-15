import base64
import datetime
import hashlib
import logging
import re
import secrets
from collections.abc import Sequence
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse, urlencode

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from ._error import PostcardCreatorException

_LOGGER = logging.getLogger(__package__)


def base64_encode(string: bytes) -> str:
    encoded = base64.urlsafe_b64encode(string).decode("ascii")
    return encoded.rstrip("=")


def base64_decode(string: str) -> bytes:
    padding = 4 - (len(string) % 4)
    string = string + ("=" * padding)
    return base64.urlsafe_b64decode(string)


class Token(object):
    def __init__(self, _protocol: str = "https://") -> None:
        self.protocol = _protocol
        self.base = "{}account.post.ch".format(self.protocol)
        self.swissid = "{}login.swissid.ch".format(self.protocol)
        self.token_url = "{}postcardcreator.post.ch/saml/SSO/alias/defaultAlias".format(
            self.protocol
        )
        self.user_agent = (
            "Mozilla/5.0 (Linux; Android 6.0.1; wv) "
            + "AppleWebKit/537.36 (KHTML, like Gecko) "
            + "Version/4.0 Chrome/52.0.2743.98 Mobile Safari/537.36"
        )
        self.legacy_headers = {"User-Agent": self.user_agent}
        self.swissid_headers = {"User-Agent": self.user_agent}

        self.token: str | None = None
        self.token_type: str | None = None
        self.token_expires_in: int | None = None
        self.token_fetched_at: datetime.datetime | None = None
        self.cache_token = False

    def has_valid_credentials(
        self,
        username: str,
        password: str,
        method: Literal["mixed", "legacy", "swissid"] = "mixed",
    ):
        try:
            self.fetch_token(username, password, method=method)
            return True
        except PostcardCreatorException:
            return False

    def fetch_token(
        self,
        username: str,
        password: str,
        method: Literal["mixed", "legacy", "swissid"] = "mixed",
    ):
        _LOGGER.debug("fetching postcard account token")

        methods = ["mixed", "legacy", "swissid"]
        if method not in methods:
            raise PostcardCreatorException(
                "unknown method. choose from: " + repr(methods)
            )

        success = False
        access_token = None
        implementation_type = ""
        if method != "swissid":
            _LOGGER.info("using legacy username password authentication")
            session = self._create_session()
            try:
                access_token = self._get_access_token_legacy(
                    session, username, password
                )
                _LOGGER.debug("legacy username/password authentication was successful")
                success = True
                implementation_type = "legacy"
            except Exception as e:
                _LOGGER.info("legacy username password authentication failed")
                _LOGGER.info(e)
                if method == "mixed":
                    _LOGGER.info("Trying swissid now because method=legacy")
                else:
                    _LOGGER.info("giving up")
                    raise e
                pass
        if method != "legacy" and not success:
            _LOGGER.info("using swissid username password authentication")
            try:
                session = self._create_session()
                access_token = self._get_access_token_swissid(
                    session, username, password
                )
                _LOGGER.debug("swissid username/password authentication was successful")
                implementation_type = "swissid"
            except Exception as e:
                _LOGGER.info("swissid username password authentication failed")
                _LOGGER.info(e)
                raise e

        try:
            _LOGGER.debug(access_token)
            self.token = access_token["access_token"]  # type: ignore
            self.token_type = access_token["token_type"]  # type: ignore
            self.token_expires_in = access_token["expires_in"]  # type: ignore
            self.token_fetched_at = datetime.datetime.now()
            self.token_implementation = implementation_type
            _LOGGER.info("access_token successfully fetched")

        except Exception as e:
            _LOGGER.info(
                "access_token does not contain required values. someting broke"
            )
            raise e

    def _create_session(
        self,
        retries: int = 5,
        backoff_factor: float = 0.5,
        status_forcelist: Sequence[int] = (500, 502, 504),
    ):
        # XXX: Backend will terminate connection if we request too frequently
        session = requests.Session()
        retry = Retry(
            total=retries,
            read=retries,
            connect=retries,
            backoff_factor=backoff_factor,
            status_forcelist=status_forcelist,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _get_code_verifier(self) -> str:
        return base64_encode(secrets.token_bytes(64))

    def _get_code(self, code_verifier: str) -> str:
        m = hashlib.sha256()
        m.update(code_verifier.encode("utf-8"))
        return base64_encode(m.digest())

    def _get_access_token_legacy(
        self, session: requests.Session, username: str, password: str
    ) -> Any:
        code_verifier = self._get_code_verifier()
        code_resp_uri = self._get_code(code_verifier)
        redirect_uri = "ch.post.pcc://auth/1016c75e-aa9c-493e-84b8-4eb3ba6177ef"
        client_id = "ae9b9894f8728ca78800942cda638155"
        client_secret = "89ff451ede545c3f408d792e8caaddf0"
        init_data = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": "PCCWEB offline_access",
            "response_mode": "query",
            "state": "abcd",
            "code_challenge": code_resp_uri,
            "code_challenge_method": "S256",
            "lang": "en",
        }
        url = "https://pccweb.api.post.ch/OAuth/authorization?"
        resp = session.get(
            url + urlencode(init_data),
            allow_redirects=True,
            headers=self.legacy_headers,
        )

        url_payload = {
            "targetURL": "https://pccweb.api.post.ch/SAML/ServiceProvider/?redirect_uri="
            + redirect_uri,
            "profile": "default",
            "app": "pccwebapi",
            "inMobileApp": "true",
            "layoutType": "standard",
        }
        data_payload = {
            "isiwebuserid": username,
            "isiwebpasswd": password,
            "confirmLogin": "",
        }
        url = "https://account.post.ch/idp/?login&"
        resp = session.post(
            url + urlencode(url_payload),
            allow_redirects=True,
            headers=self.legacy_headers,
            data=data_payload,
        )

        resp = session.post(
            url + urlencode(url_payload),
            allow_redirects=True,
            headers=self.legacy_headers,
        )

        saml_soup = BeautifulSoup(resp.text, "html.parser")
        saml_response = saml_soup.find("input", {"name": "SAMLResponse"})

        if saml_response is None or saml_response.get("value") is None:
            raise PostcardCreatorException(
                "Username/password authentication failed. Are your credentials valid?."
            )

        saml_response = saml_response["value"]
        relay_state = (saml_soup.find("input", {"name": "RelayState"})["value"],)

        url = "https://pccweb.api.post.ch/OAuth/"  # important: '/' at the end
        customer_headers = self.legacy_headers
        customer_headers["Origin"] = "https://account.post.ch"
        customer_headers["X-Requested-With"] = "ch.post.it.pcc"
        customer_headers["Upgrade-Insecure-Requests"] = str(1)
        saml_payload = {"RelayState": relay_state, "SAMLResponse": saml_response}
        resp = session.post(
            url, headers=customer_headers, data=saml_payload, allow_redirects=False
        )  # do not follow redirects as we cannot redirect to android uri
        try:
            code_resp_uri = resp.headers["Location"]
            init_data = parse_qs(urlparse(code_resp_uri).query)
            resp_code = init_data["code"][0]
        except Exception as e:
            print(e)
            raise PostcardCreatorException(
                "response does not have code attribute: "
                + url
                + ". Did endpoint break?"
            )

        # get access token
        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": resp_code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        }
        url = "https://pccweb.api.post.ch/OAuth/token"
        resp = requests.post(
            url, data=data, headers=self.legacy_headers, allow_redirects=False
        )

        if "access_token" not in resp.json() or resp.status_code != 200:
            raise PostcardCreatorException(
                "not able to fetch access token: " + resp.text
            )

        return resp.json()

    def _get_access_token_swissid(
        self, session: requests.Session, username: str, password: str
    ) -> Any:
        code_verifier = self._get_code_verifier()
        code_resp_uri = self._get_code(code_verifier)
        redirect_uri = "ch.post.pcc://auth/1016c75e-aa9c-493e-84b8-4eb3ba6177ef"
        client_id = "ae9b9894f8728ca78800942cda638155"
        client_secret = "89ff451ede545c3f408d792e8caaddf0"

        init_data = {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": "PCCWEB offline_access",
            "response_mode": "query",
            "state": "abcd",
            "code_challenge": code_resp_uri,
            "code_challenge_method": "S256",
            "lang": "en",
        }
        url = "https://pccweb.api.post.ch/OAuth/authorization?"
        resp = session.get(
            url + urlencode(init_data),
            allow_redirects=True,
            headers=self.swissid_headers,
        )

        saml_payload = {"externalIDP": "externalIDP"}
        url = (
            "https://account.post.ch/idp/?login"
            "&targetURL=https://pccweb.api.post.ch/SAML/ServiceProvider/"
            "?redirect_uri=" + redirect_uri + "&profile=default"
            "&app=pccwebapi&inMobileApp=true&layoutType=standard"
        )
        resp = session.post(
            url, data=saml_payload, allow_redirects=True, headers=self.swissid_headers
        )
        if len(resp.history) == 0:
            raise PostcardCreatorException("fail to fetch " + url)

        step1_goto_url = resp.history[len(resp.history) - 1].headers["Location"]
        goto_param = re.search(r"goto=(.*?)$", step1_goto_url).group(1)
        try:
            goto_param = goto_param.split("&")[0]
        except Exception:
            # only use goto_param without further params
            pass
        _LOGGER.debug("goto parm=" + goto_param)
        if goto_param is None or goto_param == "":
            raise PostcardCreatorException("swissid: cannot fetch goto param")

        url = (
            "https://login.swissid.ch/api-login/authenticate/token/status?locale=en&goto="
            + goto_param
            + "&acr_values=loa-1&realm=%2Fsesam&service=qoa1"
        )
        resp = session.get(url, allow_redirects=True)

        url = (
            "https://login.swissid.ch/api-login/welcome-pack?locale=en"
            + goto_param
            + "&acr_values=loa-1&realm=%2Fsesam&service=qoa1"
        )
        resp = session.get(url, allow_redirects=True)

        # login with username and password
        url = (
            "https://login.swissid.ch/api-login/authenticate/init?locale=en&goto="
            + goto_param
            + "&acr_values=loa-1&realm=%2Fsesam&service=qoa1"
        )
        resp = session.post(url, allow_redirects=True)

        # submit username and password
        url_query_string = (
            "locale=en&goto="
            + goto_param
            + "&acr_values=loa-1&realm=%2Fsesam&service=qoa1"
        )

        url = (
            "https://login.swissid.ch/api-login/authenticate/basic?" + url_query_string
        )
        headers = self.swissid_headers
        headers["authId"] = resp.json()["tokens"]["authId"]
        step_data = {"username": username, "password": password}
        resp = session.post(url, json=step_data, headers=headers, allow_redirects=True)

        # anomaly detection
        resp = self._swiss_id_anomaly_detection(session, resp, url_query_string)

        try:
            url = resp.json()["nextAction"]["successUrl"]
        except Exception:
            _LOGGER.info("failed to login. username/password wrong?")
            raise PostcardCreatorException("failed to login, username/password wrong?")

        resp = session.get(url, headers=self.swissid_headers, allow_redirects=True)

        step7_soup = BeautifulSoup(resp.text, "html.parser")
        url = step7_soup.find("form", {"name": "LoginForm"})["action"]
        resp = session.post(url, headers=self.swissid_headers)

        # find saml response
        step7_soup = BeautifulSoup(resp.text, "html.parser")
        saml_response = step7_soup.find("input", {"name": "SAMLResponse"})

        if saml_response is None or saml_response.get("value") is None:
            raise PostcardCreatorException(
                "Username/password authentication failed. Are your credentials valid?."
            )

        # prepare access token
        url = "https://pccweb.api.post.ch/OAuth/"  # important: '/' at the end
        customer_headers = self.swissid_headers
        customer_headers["Origin"] = "https://account.post.ch"
        customer_headers["X-Requested-With"] = "ch.post.it.pcc"
        customer_headers["Upgrade-Insecure-Requests"] = str(1)
        saml_payload = {
            "RelayState": step7_soup.find("input", {"name": "RelayState"})["value"],
            "SAMLResponse": saml_response.get("value"),
        }
        resp = session.post(
            url, headers=customer_headers, data=saml_payload, allow_redirects=False
        )  # do not follow redirects as we cannot redirect to android uri
        try:
            code_resp_uri = resp.headers["Location"]
            init_data = parse_qs(urlparse(code_resp_uri).query)
            resp_code = init_data["code"][0]
        except Exception as e:
            print(e)
            raise PostcardCreatorException(
                "response does not have code attribute: "
                + url
                + ". Did endpoint break?"
            )

        # get access token
        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": resp_code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        }
        url = "https://pccweb.api.post.ch/OAuth/token"
        resp = requests.post(
            url,  # we do not use session here!
            data=data,
            headers=self.swissid_headers,
            allow_redirects=False,
        )

        if "access_token" not in resp.json() or resp.status_code != 200:
            raise PostcardCreatorException(
                "not able to fetch access token: " + resp.text
            )

        return resp.json()

    def _swiss_id_anomaly_detection(
        self,
        session: requests.Session,
        prev_response: requests.Response,
        url_query_string: str,
    ) -> requests.Response:
        # XXX: Starting 2022-10, endpoints introduce anomaly detection, possibly to further restrict automated access
        # Currently, any valid device_print payload seems to work
        # useragent in request and payload can differ and still be valid
        url = (
            "https://login.swissid.ch/api-login/anomaly-detection/device-print?"
            + url_query_string
        )
        device_print_ctx = prev_response.json()
        try:
            next_action = device_print_ctx["nextAction"]["type"]
            if next_action != "SEND_DEVICE_PRINT":
                _LOGGER.warning(
                    "next action must be SEND_DEVICE_PRINT but got " + next_action
                )
            auth_id_device_print = device_print_ctx["tokens"]["authId"]
            device_print = self._formulate_anomaly_detection()
            headers = self.swissid_headers
            headers["authId"] = auth_id_device_print
            resp = session.post(url, json=device_print, headers=headers)
        except Exception as e:
            msg = (
                "Anomaly detection step failed. \n"
                + f"previous response body: {device_print_ctx}\n"
                + f"pending request: {url} \n"
            )
            _LOGGER.info(msg)
            _LOGGER.info(e)
            raise PostcardCreatorException(msg, e)
        return resp

    def _formulate_anomaly_detection(self) -> dict[str, Any]:
        # Valid device_print generated in an x86 android 12 emulator,
        # XXX: if something breaks in the future, we may have to get more clever here
        device_print = {
            "appCodeName": "Mozilla",
            "appName": "Netscape",
            # Mozilla/5.0
            "appVersion": self.user_agent.replace("Mozilla/", ""),
            "fonts": {
                "installedFonts": "cursive;monospace;serif;sans-serif;fantasy;default;Arial;Courier;"
                + "Courier New;Georgia;Tahoma;Times;Times New Roman;Verdana"
            },
            "language": "de",
            "platform": "Linux x86_64",
            "plugins": {"installedPlugins": ""},
            "product": "Gecko",
            "productSub": "20030107",
            "screen": {
                "screenColourDepth": 24,
                "screenHeight": 732,
                "screenWidth": 412,
            },
            "timezone": {"timezone": -120},
            "userAgent": self.user_agent,
            "vendor": "Google Inc.",
        }

        return device_print

    def to_json(self) -> dict[str, Any]:
        return {
            "fetched_at": self.token_fetched_at,
            "token": self.token,
            "expires_in": self.token_expires_in,
            "type": self.token_type,
            "implementation": self.token_implementation,
        }
