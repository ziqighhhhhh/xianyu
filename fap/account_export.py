"""Password-encrypted account export format (AES-256-GCM + PBKDF2)."""

from __future__ import annotations

import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

FORMAT = "fap-accounts-encrypted"
ITERATIONS = 200_000


class DecryptError(Exception):
    pass


def _derive(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS)
    return kdf.derive(password.encode("utf-8"))


def encrypt(accounts: list[dict], password: str) -> dict:
    salt = os.urandom(16)
    nonce = os.urandom(12)
    plaintext = json.dumps(accounts, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(_derive(password, salt)).encrypt(nonce, plaintext, FORMAT.encode())
    return {
        "format": FORMAT,
        "version": 1,
        "kdf": "pbkdf2-sha256",
        "iterations": ITERATIONS,
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def decrypt(blob: dict, password: str) -> list[dict]:
    if blob.get("format") != FORMAT:
        raise DecryptError("不是加密账号文件")
    try:
        salt = base64.b64decode(blob["salt"])
        nonce = base64.b64decode(blob["nonce"])
        ciphertext = base64.b64decode(blob["ciphertext"])
        plaintext = AESGCM(_derive(password, salt)).decrypt(nonce, ciphertext, FORMAT.encode())
        data = json.loads(plaintext)
    except Exception as exc:
        raise DecryptError("密码错误或文件损坏") from exc
    if not isinstance(data, list):
        raise DecryptError("文件内容不是账号数组")
    return data
