"""Experimental LWP frame builders.

Frame shapes are reconstructed from the original Android symbols
(`BuildRegisterFrame`, `BuildTextMessageFrame`, `BuildLWPRequestFrame`, ...).
They are not yet verified against a logged-in goofish account.
"""

from __future__ import annotations

import uuid

APP_KEY = "444e9908a51d1cb236a27862abc769c9"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def new_mid() -> str:
    return uuid.uuid4().hex


def build_common_ws_headers(app_key: str = APP_KEY, ua: str = UA, *, token: str = "",
                            device_id: str = "", mid: str = "", dt: str = "",
                            wv: str = "", sync: str = "", cache_header: str = "") -> dict:
    """Header map reconstructed from the binary literals.

    The Android binary contains the literals ``lwp``, ``headers``, ``app-key``,
    ``token``, ``ua``, ``dt``, ``wv``, ``sync``, ``did``, ``mid`` and
    ``cache-header`` in the same builder.  Values other than app-key/ua are
    account/runtime specific, so they are only included when supplied.
    """
    headers = {"app-key": app_key, "ua": ua}
    for key, value in (("token", token), ("dt", dt), ("wv", wv), ("sync", sync),
                       ("did", device_id), ("mid", mid), ("cache-header", cache_header)):
        if value:
            headers[key] = value
    return headers


def build_register_frame(app_key: str = APP_KEY, ua: str = UA, **header_values) -> dict:
    return {"lwp": "/reg", "headers": build_common_ws_headers(app_key, ua, **header_values), "body": {}}


def build_ack_frame(mid: str, sync_pkg) -> dict:
    return {"lwp": "/r/SyncStatus/ackDiff", "headers": {"mid": mid}, "body": {"syncPkg": sync_pkg}}


def build_lwp_request(lwp: str, body: dict, headers: dict | None = None) -> dict:
    return {"lwp": lwp, "headers": headers or {"mid": new_mid()}, "body": body}


def build_text_frame(conversation_id: str, receiver_id: str, text: str,
                     mid: str | None = None, sid: str = "") -> dict:
    body = {
        "conversationId": str(conversation_id),
        "receiver": {"userId": str(receiver_id)},
        "message": {"contentType": 1, "text": {"text": text}},
    }
    return build_lwp_request("/r/MessageSend/sendByReceiverScope", body,
                             {"mid": mid or new_mid(), "sid": sid})
