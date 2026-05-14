"""Gateway: aggrega lotti, cifra AES-256, carica su cloud, ottiene URI, hasha, submit on-chain."""
from crypto_utils import generate_key, encrypt, sha256
from cloud_storage import CloudStorage
from contracts.medical_data import MedicalDataContract
from machine import MedicalMachine


class Gateway:
    """Trust boundary tra macchinari e cloud. Tiene un registro chiavi che condivide
    col contratto AccessLog (in produzione: KMS dedicato)."""

    def __init__(
        self,
        cloud: CloudStorage,
        medical_contract: MedicalDataContract,
        key_registry: dict[str, bytes],
    ):
        self.cloud = cloud
        self.contract = medical_contract
        self.key_registry = key_registry

    def ingest(self, machine: MedicalMachine, n_samples: int = 5) -> dict:
        # 1. raccolta + aggregazione
        samples = machine.stream(n_samples=n_samples)
        plaintext = MedicalMachine.serialize(samples)

        # 2. cifratura AES-256-GCM con chiave fresca per lotto
        key = generate_key()
        ciphertext = encrypt(plaintext, key)

        # 3. upload cloud -> URI
        uri = self.cloud.write(ciphertext)

        # 4. hash SHA-256 del ciphertext (firma del dato)
        data_hash = sha256(ciphertext)

        # 5. chiave AES depositata nel registro indicizzato per URI
        self.key_registry[uri] = key

        # 6. firma Ed25519 del payload da parte del macchinario
        signed_payload = (
            f"{data_hash}|{uri}|{machine.patient_id}|{machine.machine_id}".encode()
        )
        signature = machine.sign(signed_payload)

        # 7. submit on-chain via smart contract (validerà firma + anti-replay)
        record = self.contract.registerData(
            data_hash=data_hash,
            uri=uri,
            patient_id=machine.patient_id,
            machine_id=machine.machine_id,
            signature=signature,
        )
        return record
