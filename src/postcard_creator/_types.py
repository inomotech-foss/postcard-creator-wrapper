import dataclasses


@dataclasses.dataclass(frozen=True, kw_only=True)
class Address:
    first_name: str
    last_name: str
    street: str
    zip_code: int
    place: str
    company: str = ""
    country: str = ""
    company_addition: str = ""
    salutation: str = ""
