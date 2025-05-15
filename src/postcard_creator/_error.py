import requests


class PostcardCreatorException(Exception):
    server_response: requests.Response | None = None
