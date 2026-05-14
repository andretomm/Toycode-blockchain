"""Macchinario medicale giocattolo: produce un flusso di vitali (HR, SpO2, BP, temp).

Ora firma ogni lotto con chiave Ed25519 per mitigare fake data injection: il gateway
(e on-chain) accettano il dato solo se la firma è valida rispetto alla public key
registrata del machine_id.
"""
import random
import time
import json
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)


class MedicalMachine:
    def __init__(self, machine_id: str, patient_id: str):
        self.machine_id = machine_id
        self.patient_id = patient_id
        self._sk = Ed25519PrivateKey.generate()

    def public_key_bytes(self) -> bytes:
        return self._sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def sign(self, payload: bytes) -> bytes:
        return self._sk.sign(payload)

    @staticmethod
    def verify(pubkey_bytes: bytes, payload: bytes, signature: bytes) -> bool:
        try:
            Ed25519PublicKey.from_public_bytes(pubkey_bytes).verify(signature, payload)
            return True
        except Exception:
            return False

    def read_sample(self) -> dict:
        return {
            "machine_id": self.machine_id,
            "patient_id": self.patient_id,
            "timestamp": time.time(),
            "heart_rate": random.randint(60, 100),
            "spo2": round(random.uniform(95.0, 99.9), 1),
            "blood_pressure": [
                random.randint(110, 130),
                random.randint(70, 85),
            ],
            "temperature_c": round(random.uniform(36.2, 37.4), 1),
        }

    def stream(self, n_samples: int = 5, interval_s: float = 0.0) -> list[dict]:
        samples = []
        for _ in range(n_samples):
            samples.append(self.read_sample())
            if interval_s:
                time.sleep(interval_s)
        return samples

    @staticmethod
    def serialize(samples: list[dict]) -> bytes:
        return json.dumps(samples, sort_keys=True).encode()
