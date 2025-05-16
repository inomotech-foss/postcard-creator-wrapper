import dataclasses


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
