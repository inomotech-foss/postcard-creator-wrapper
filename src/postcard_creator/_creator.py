import base64
import logging
from typing import IO, Any

import requests

from ._auth import Token
from ._error import FreeQuotaExceededException, PostcardCreatorException
from ._img_util import create_text_image, rotate_and_scale_image
from ._types import (
    Address,
    Quota,
)

_LOGGER = logging.getLogger(__package__)


def _format_sender(sender: Address) -> dict[str, Any]:
    return {
        "city": sender.place,
        "company": sender.company,
        "firstname": sender.first_name,
        "lastname": sender.last_name,
        "street": sender.street,
        "zip": sender.zip_code,
    }


def _format_recipient(recipient: Address) -> dict[str, Any]:
    return {
        "city": recipient.place,
        "company": recipient.company,
        "companyAddon": recipient.company_addition,
        "country": "SWITZERLAND",
        "firstname": recipient.first_name,
        "lastname": recipient.last_name,
        "street": recipient.street,
        "title": recipient.salutation,
        "zip": recipient.zip_code,
    }


class PostcardCreator:
    def __init__(self, token: Token) -> None:
        self.token = token
        self._session = requests.Session()
        self.host = "https://pccweb.api.post.ch/secure/api/mobile/v1"

    def _get_headers(self):
        return {
            "User-Agent": "Mozilla/5.0 (Linux; Android 6.0.1; wv) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Version/4.0 Chrome/52.0.2743.98 Mobile Safari/537.36",
            "Authorization": "Bearer {}".format(self.token.token),
        }

    # XXX: we share some functionality with legacy wrapper here
    # however, it is little and not worth the lack of extensibility if generalized in super class
    def _do_op(self, method: str, endpoint: str, **kwargs: Any) -> requests.Response:
        url = self.host + endpoint
        if "headers" not in kwargs or kwargs["headers"] is None:
            kwargs["headers"] = self._get_headers()

        _LOGGER.debug("{}: {}".format(method, url))
        response = self._session.request(method, url, **kwargs)

        if response.status_code not in [200, 201, 204]:
            e = PostcardCreatorException(
                "error in request {} {}. status_code: {}, text: {}".format(
                    method, url, response.status_code, response.text or ""
                )
            )
            e.server_response = response.text
            raise e
        return response

    def _validate_model_response(self, endpoint: str, payload: dict[str, Any]) -> None:
        if payload.get("errors"):
            raise PostcardCreatorException(
                f"cannot fetch {endpoint}: {payload['errors']}"
            )

    def get_quota(self) -> Quota:
        _LOGGER.debug("fetching quota")
        endpoint = "/user/quota"

        payload = self._do_op("get", endpoint).json()
        self._validate_model_response(endpoint, payload)
        return Quota.from_model(payload["model"])

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

    def send_card(
        self,
        *,
        message: str,
        picture: IO[bytes],
        recipient: Address,
        sender: Address,
        mock_send: bool = False,
        image_export: bool = False,
        image_rotate: bool = True,
        paid: bool = False,
    ) -> Any:
        img_base64 = base64.b64encode(
            rotate_and_scale_image(
                picture,
                img_format="jpeg",
                image_export=image_export,
                image_rotate=image_rotate,
                enforce_size=True,
                image_target_width=1819,
                image_quality_factor=1,
                image_target_height=1311,
            )
        ).decode("ascii")
        img_text_base64 = base64.b64encode(
            create_text_image(message, image_export=image_export)
        ).decode("ascii")
        endpoint = "/card/upload"
        payload: dict[str, Any] = {
            "lang": "en",
            "paid": paid,
            "recipient": _format_recipient(recipient),
            "sender": _format_sender(sender),
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

        if not paid:
            quota = self.get_quota()
            if not quota.available:
                raise FreeQuotaExceededException(
                    "Limit of free postcards exceeded. Try again at "
                    + quota.next.isoformat()
                )

        payload = self._do_op("post", endpoint, json=payload).json()
        _LOGGER.debug(f"{endpoint} with response {payload}")

        self._validate_model_response(endpoint, payload)

        _LOGGER.info(f"postcard submitted, orderid {payload['model'].get('orderId')}")
        return payload["model"]
