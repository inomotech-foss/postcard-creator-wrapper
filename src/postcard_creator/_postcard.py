import dataclasses
from typing import BinaryIO


@dataclasses.dataclass(frozen=True, kw_only=True)
class Sender:
    prename: str
    lastname: str
    street: str
    zip_code: int
    place: str
    company: str = ""
    country: str = ""


@dataclasses.dataclass(frozen=True, kw_only=True)
class Recipient:
    prename: str
    lastname: str
    street: str
    zip_code: int
    place: str
    company: str = ""
    company_addition: str = ""
    salutation: str = ""


@dataclasses.dataclass(frozen=True, kw_only=True)
class Postcard:
    sender: Sender
    recipient: Recipient
    picture_stream: BinaryIO
    message: str = ""
