"""Petitioner (medico/ricercatore): richiede accesso a un dato, decifra se autorizzato."""
import json
from crypto_utils import decrypt
from cloud_storage import CloudStorage
from contracts.access_log import AccessLogContract


class Doctor:
    def __init__(
        self,
        doctor_id: str,
        access_contract: AccessLogContract,
        cloud: CloudStorage,
    ):
        self.id = doctor_id
        self.access_contract = access_contract
        self.cloud = cloud

    def fetch(self, patient_id: str, uri: str) -> list[dict] | None:
        """Richiede accesso al contratto. Se approvato: scarica blob, decifra con chiave restituita."""
        approved, key = self.access_contract.requestAccess(
            petitioner_id=self.id, patient_id=patient_id, uri=uri
        )
        if not approved or key is None:
            return None
        blob = self.cloud.read(uri)
        if blob is None:
            return None
        plaintext = decrypt(blob, key)
        return json.loads(plaintext.decode())
