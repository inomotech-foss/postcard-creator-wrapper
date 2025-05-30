import base64
import logging
from typing import Any

import requests
from PIL import ImageFont

from ._error import PostcardCreatorException
from ._img_util import create_text_image, rotate_and_scale_image
from ._postcard import (
    Postcard,
    Recipient,
    Sender,
)
from ._token import Token

_LOGGER = logging.getLogger(__package__)


def _dump_request(response: requests.Response) -> None:
    from requests_toolbelt.utils import dump  # type: ignore

    data = dump.dump_all(response)
    try:
        _LOGGER.debug(data.decode())
    except Exception:
        data = str(data).replace("\\r\\n", "\r\n")
        _LOGGER.debug(data)


def _send_free_card_defaults(func):
    def wrapped(*args, **kwargs):
        kwargs["image_target_width"] = (
            kwargs.get("image_target_width") or 154
        )  # legacy only
        kwargs["image_target_height"] = (
            kwargs.get("image_target_height") or 111
        )  # legacy only
        kwargs["image_quality_factor"] = (
            kwargs.get("image_quality_factor") or 20
        )  # legacy only
        kwargs["image_rotate"] = kwargs.get("image_rotate") or True
        kwargs["image_export"] = kwargs.get("image_export") or False
        return func(*args, **kwargs)

    return wrapped


def _format_sender(sender: Sender) -> dict[str, Any]:
    return {
        "city": sender.place,
        "company": sender.company,
        "firstname": sender.prename,
        "lastname": sender.lastname,
        "street": sender.street,
        "zip": sender.zip_code,
    }


def _format_recipient(recipient: Recipient) -> dict[str, Any]:
    return {
        "city": recipient.place,
        "company": recipient.company,
        "companyAddon": recipient.company_addition,
        "country": "SWITZERLAND",
        "firstname": recipient.prename,
        "lastname": recipient.lastname,
        "street": recipient.street,
        "title": recipient.salutation,
        "zip": recipient.zip_code,
    }


class PostcardCreator:
    def __init__(self, token: Token) -> None:
        self.token = token
        self._session = self._create_session()
        self.host = "https://pccweb.api.post.ch/secure/api/mobile/v1"

    def _get_headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0.1; wv) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Version/4.0 Chrome/52.0.2743.98 Mobile Safari/537.36",
            "Authorization": "Bearer {}".format(self.token.token),
        }

    def _create_session(self):
        return requests.Session()

    # XXX: we share some functionality with legacy wrapper here
    # however, it is little and not worth the lack of extensibility if generalized in super class
    def _do_op(self, method, endpoint, **kwargs):
        url = self.host + endpoint
        if "headers" not in kwargs or kwargs["headers"] is None:
            kwargs["headers"] = self._get_headers()

        _LOGGER.debug("{}: {}".format(method, url))
        response = self._session.request(method, url, **kwargs)
        _dump_request(response)

        if response.status_code not in [200, 201, 204]:
            e = PostcardCreatorException(
                "error in request {} {}. status_code: {}, text: {}".format(
                    method, url, response.status_code, response.text or ""
                )
            )
            e.server_response = response.text
            raise e
        return response

    def _validate_model_response(self, endpoint, payload):
        if payload.get("errors"):
            raise PostcardCreatorException(
                f"cannot fetch {endpoint}: {payload['errors']}"
            )

    def get_quota(self):
        _LOGGER.debug("fetching quota")
        endpoint = "/user/quota"

        payload = self._do_op("get", endpoint).json()
        self._validate_model_response(endpoint, payload)
        return payload["model"]

    def has_free_postcard(self):
        return self.get_quota()["available"]

    def get_user_info(self):
        _LOGGER.debug("fetching user information")
        endpoint = "/user/current"

        payload = self._do_op("get", endpoint).json()
        self._validate_model_response(endpoint, payload)
        return payload["model"]

    def get_billing_saldo(self):
        _LOGGER.debug("fetching billing saldo")
        endpoint = "/billingOnline/accountSaldo"

        payload = self._do_op("get", endpoint).json()
        self._validate_model_response(endpoint, payload)
        return payload["model"]

    @_send_free_card_defaults
    def send_free_card(
        self,
        postcard: Postcard,
        mock_send: bool = False,
        image_export: bool = False,
        **kwargs: Any,
    ) -> Any:
        if not postcard:
            raise PostcardCreatorException("Postcard must be set")

        # XXX: endpoint no longer supports user specified w/h
        kwargs["image_target_width"] = 1819
        kwargs["image_quality_factor"] = 1
        kwargs["image_target_height"] = 1311
        img_base64 = base64.b64encode(
            rotate_and_scale_image(
                postcard.picture_stream,
                img_format="jpeg",
                image_export=image_export,
                enforce_size=True,
                **kwargs,
            )
        ).decode("ascii")
        img_text_base64 = base64.b64encode(
            self.create_text_cover(postcard.message)
        ).decode("ascii")
        endpoint = "/card/upload"
        payload = {
            "lang": "en",
            "paid": False,
            "recipient": _format_recipient(postcard.recipient),
            "sender": _format_sender(postcard.sender),
            "text": "",
            "textImage": img_text_base64,  # jpeg, JFIF standard 1.01, 720x744
            "image": img_base64,  # jpeg, JFIF standard 1.01, 1819x1311
            "stamp": None,
        }

        if mock_send:
            copy = dict(payload)
            copy["textImage"] = "omitted"
            copy["image"] = "omitted"
            _LOGGER.info(f"mock_send=True, endpoint: {endpoint}, payload: {copy}")
            return False

        if not self.has_free_postcard():
            raise PostcardCreatorException(
                "Limit of free postcards exceeded. Try again tomorrow at "
                + self.get_quota()["next"]
            )

        payload = self._do_op("post", endpoint, json=payload).json()
        _LOGGER.debug(f"{endpoint} with response {payload}")

        self._validate_model_response(endpoint, payload)

        _LOGGER.info(f"postcard submitted, orderid {payload['model'].get('orderId')}")
        return payload["model"]

    def create_text_cover(self, msg: str) -> ImageFont.FreeTypeFont:
        """
        Create a jpg with given text
        """
        return create_text_image(msg, image_export=True)
