"""Primitive crittografiche: AES-256-GCM per cifratura dati, SHA-256 per hash di integrità."""
import os
import hashlib
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def generate_key() -> bytes:
    return AESGCM.generate_key(bit_length=256)


def encrypt(plaintext: bytes, key: bytes) -> bytes:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
    return nonce + ct


def decrypt(ciphertext: bytes, key: bytes) -> bytes:
    nonce, ct = ciphertext[:12], ciphertext[12:]
    return AESGCM(key).decrypt(nonce, ct, associated_data=None)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
