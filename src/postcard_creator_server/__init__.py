import importlib.metadata
import io
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Annotated

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from postcard_creator import (
    Address,
    FreeQuotaExceededException,
    PostcardCreator,
    PostcardCreatorException,
    Quota,
)

from ._token import AuthToken, TokenDep

_LOGGER = logging.getLogger(__name__)

try:
    version = importlib.metadata.version(__package__ or "")
except importlib.metadata.PackageNotFoundError:
    # package is not installed
    version = "unknown"


app = FastAPI(title="Postcard Creator API", version=version)


def _get_postcard_creator(token: TokenDep) -> PostcardCreator:
    return PostcardCreator(token)


PostcardCreatorDep = Annotated[PostcardCreator, Depends(_get_postcard_creator)]


@app.get("/token")
def get_token(*, token: TokenDep) -> AuthToken:
    return AuthToken.from_token(token)


@app.get("/quota")
def get_quota(*, creator: PostcardCreatorDep) -> Quota:
    return creator.get_quota()


class PictureUrl(BaseModel):
    url: str = Field(
        json_schema_extra={
            "format": "uri",
        }
    )


class PictureBase64(BaseModel):
    base64: str = Field(
        json_schema_extra={
            "format": "byte",
        }
    )


class MessageAndPicture(BaseModel):
    message: str
    picture: PictureUrl | PictureBase64

    @contextmanager
    def open_picture(self) -> Iterator[IO[bytes]]:
        if isinstance(self.picture, PictureUrl):
            import requests

            _LOGGER.info("Downloading picture from %s", self.picture.url)
            with requests.get(self.picture.url) as resp:
                resp.raise_for_status()
                yield io.BytesIO(resp.content)
        elif isinstance(self.picture, PictureBase64):  # type: ignore
            import base64

            data = base64.b64decode(self.picture.base64)
            yield io.BytesIO(data)


class SendCardData(BaseModel):
    sender: Address
    recipient: Address
    content: MessageAndPicture
    mock_send: bool = False


@app.post("/send-card")
def send_card(
    data: SendCardData,
    *,
    creator: PostcardCreatorDep,
) -> None:
    try:
        with data.content.open_picture() as picture:
            res = creator.send_card(
                message=data.content.message,
                picture=picture,
                sender=data.sender,
                recipient=data.recipient,
                mock_send=data.mock_send,
                image_export=True,
            )

    except FreeQuotaExceededException as err:
        raise HTTPException(
            status_code=429,
            detail=str(err),
        )
    except PostcardCreatorException as err:
        raise HTTPException(
            status_code=500,
            detail=str(err),
        )
    return res
