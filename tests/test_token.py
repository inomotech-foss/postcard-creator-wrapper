import importlib.resources
import json
import logging

import pytest
import requests
import requests_mock

from postcard_creator import (
    PostcardCreator,
    PostcardCreatorException,
    Token,
)

logging.basicConfig(level=logging.INFO, format="%(name)s (%(levelname)s): %(message)s")
logging.getLogger("postcard_creator").setLevel(10)

URL_TOKEN_SAML = "mock://account.post.ch/SAML/IdentityProvider/"
URL_TOKEN_SSO = "mock://postcardcreator.post.ch/saml/SSO/alias/defaultAlias"
URL_PCC_HOST = "mock://postcardcreator.post.ch/rest/2.1"

adapter_token = None
adapter_pcc = None


def create_mocked_session(self):
    global adapter_token
    session = requests.Session()
    session.mount("mock", adapter_token)
    return session


def create_token():
    global adapter_token
    adapter_token = requests_mock.Adapter()
    Token._create_session = create_mocked_session
    return Token(_protocol="mock://")


def create_postcard_creator():
    global adapter_pcc
    adapter_pcc = requests_mock.Adapter()
    PostcardCreator._create_session = create_mocked_session
    token = create_token()
    token.token_expires_in = 3600
    token.token_type = "Bearer"
    token.token = 0
    return PostcardCreator(token=token)


def create_token_with_successful_login():
    token = create_token()
    saml_response = importlib.resources.read_text(__package__, "saml_response.html")
    access_token = {"access_token": 0, "token_type": "token_type", "expires_in": 3600}

    adapter_token.register_uri("GET", URL_TOKEN_SAML, text="", reason="")
    adapter_token.register_uri("POST", URL_TOKEN_SAML, reason="", text=saml_response)
    adapter_token.register_uri(
        "POST", URL_TOKEN_SSO, reason="", text=json.dumps(access_token)
    )
    return token


def test_token_invalid_args():
    with pytest.raises(PostcardCreatorException):
        token = create_token()
        token.fetch_token(None, None)
