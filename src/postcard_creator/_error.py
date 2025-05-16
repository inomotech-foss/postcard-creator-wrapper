class PostcardCreatorException(Exception):
    server_response: str | None = None


class FreeQuotaExceededException(PostcardCreatorException): ...
