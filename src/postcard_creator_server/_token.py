import functools
import logging
from datetime import datetime
from typing import Annotated, Self

from fastapi import Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

from postcard_creator import Token

_LOGGER = logging.getLogger(__name__)


class AuthToken(BaseModel):
    fetched_at: datetime | None
    token: str | None
    expires_in: int | None
    type: str | None
    implementation: str

    @classmethod
    def from_token(cls, token: Token) -> Self:
        return cls(
            fetched_at=token.token_fetched_at,
            token=token.token,
            expires_in=token.token_expires_in,
            type=token.token_type,
            implementation=token.token_implementation,
        )


class TokenManager:
    def __init__(self) -> None:
        self._tokens: dict[str, Token] = {}

    @classmethod
    @functools.cache
    def singleton(cls) -> Self:
        return cls()

    def get(self, creds: HTTPBasicCredentials) -> Token:
        try:
            token = self._tokens[creds.username]
        except KeyError:
            token = self._tokens[creds.username] = Token()
        if token.is_expired():
            _LOGGER.info("Token for %s expired, fetching new token", creds.username)
            token.fetch_token(creds.username, creds.password)
        return token


TokenManagerDep = Annotated[TokenManager, Depends(TokenManager.singleton)]

_HTTP_BASIC = HTTPBasic()


def _get_token(
    *,
    credentials: Annotated[HTTPBasicCredentials, Depends(_HTTP_BASIC)],
    token_manager: TokenManagerDep,
) -> Token:
    token = token_manager.get(credentials)
    return token


TokenDep = Annotated[Token, Depends(_get_token)]
