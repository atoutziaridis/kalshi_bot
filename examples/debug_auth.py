"""Debug Kalshi API authentication."""

from __future__ import annotations

import base64
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
import httpx


def load_private_key(file_path: str):
    with open(file_path, "rb") as key_file:
        return serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend(),
        )


def sign_pss_text(private_key, text: str) -> str:
    message = text.encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def test_auth():
    api_key = "a952bcbe-ec3b-4b5b-b8f9-11dae589608c"
    private_key = load_private_key("config/trade.txt")

    timestamp_ms = int(time.time() * 1000)
    timestamp_str = str(timestamp_ms)

    method = "GET"
    path = "/trade-api/v2/portfolio/balance"

    msg_string = timestamp_str + method + path
    print(f"Message to sign: {msg_string}")

    sig = sign_pss_text(private_key, msg_string)
    print(f"Signature: {sig[:50]}...")

    headers = {
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_str,
    }

    base_url = "https://demo-api.kalshi.co"
    url = base_url + path

    print(f"\nURL: {url}")
    print(f"Headers: {headers}")

    response = httpx.get(url, headers=headers)
    print(f"\nStatus: {response.status_code}")
    print(f"Response: {response.text}")


if __name__ == "__main__":
    test_auth()
