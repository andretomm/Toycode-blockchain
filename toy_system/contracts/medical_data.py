"""Smart contract per registrazione e verifica integrità dati medici (Layer 1 — data side).

Estensioni:
- Registro chiavi pubbliche dei macchinari (registerMachine).
- Verifica firma Ed25519 del lotto prima di accettare registerData.
- Anti-replay: rifiuto di (hash, uri) già presenti on-chain.
"""
import time
from blockchain import Blockchain
from machine import MedicalMachine


class ReplayAttackError(Exception):
    pass


class InvalidSignatureError(Exception):
    pass


class UnknownMachineError(Exception):
    pass


class MedicalDataContract:
    def __init__(self, chain: Blockchain, cloud):
        self.chain = chain
        self.cloud = cloud
        # registro pubkey macchinari (in produzione: PKI / CA dedicata)
        self.machine_keys: dict[str, bytes] = {}
        # indice fast-lookup per anti-replay (proiezione del ledger)
        self._seen: set[tuple[str, str]] = set()

    def registerMachine(self, machine_id: str, pubkey: bytes) -> dict:
        self.machine_keys[machine_id] = pubkey
        rec = {
            "type": "REGISTER_MACHINE",
            "machine_id": machine_id,
            "pubkey": pubkey.hex(),
            "timestamp": time.time(),
        }
        self.chain.submit(rec)
        return rec

    def registerData(
        self,
        data_hash: str,
        uri: str,
        patient_id: str,
        machine_id: str,
        signature: bytes,
        timestamp: float | None = None,
    ) -> dict:
        """Validazione on-chain prima di accettare:
        1. macchinario registrato
        2. firma Ed25519 valida sul payload (hash || uri || patient_id || machine_id)
        3. coppia (hash, uri) non già vista (anti-replay)
        """
        # 1) macchinario noto
        pubkey = self.machine_keys.get(machine_id)
        if pubkey is None:
            raise UnknownMachineError(machine_id)

        # 2) firma valida
        signed_payload = f"{data_hash}|{uri}|{patient_id}|{machine_id}".encode()
        if not MedicalMachine.verify(pubkey, signed_payload, signature):
            raise InvalidSignatureError(machine_id)

        # 3) anti-replay
        key = (data_hash, uri)
        if key in self._seen:
            raise ReplayAttackError(f"already registered: {key}")
        self._seen.add(key)

        record = {
            "type": "REGISTER_DATA",
            "hash": data_hash,
            "uri": uri,
            "patient_id": patient_id,
            "machine_id": machine_id,
            "signature": signature.hex(),
            "timestamp": timestamp or time.time(),
        }
        self.chain.submit(record)
        return record

    def verifyIntegrity(self, data_hash: str, uri: str) -> bool:
        from crypto_utils import sha256

        blob = self.cloud.read(uri)
        if blob is None:
            return False
        recomputed = sha256(blob)
        on_chain = self.chain.find(
            lambda p: p.get("type") == "REGISTER_DATA" and p.get("uri") == uri
        )
        if not on_chain:
            return False
        stored_hash = on_chain[-1].payload["hash"]
        return recomputed == data_hash == stored_hash
