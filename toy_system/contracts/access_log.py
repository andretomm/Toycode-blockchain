"""Smart contract per gestione permessi e access logging (Layer 1 — access log side)."""
import time
from blockchain import Blockchain


class AccessLogContract:
    """Gestisce permessi petitioner ed esegue logging di ogni richiesta di accesso.

    Stato (permessi e consensi) è mantenuto come "world state" derivabile rieseguendo
    le transazioni della chain — qui per semplicità manteniamo dict in memoria a fianco
    del log immutabile, come fa Hyperledger Fabric con CouchDB/LevelDB.
    """

    def __init__(self, chain: Blockchain, key_registry: dict[str, bytes]):
        self.chain = chain
        # permissions[petitioner_id] -> set di access_level
        self.permissions: dict[str, set[str]] = {}
        # consents[patient_id] -> set di petitioner_id autorizzati dal paziente
        self.consents: dict[str, set[str]] = {}
        # registro chiavi: uri -> chiave AES (in un sistema reale starebbe in un KMS)
        self.key_registry = key_registry

    # ---- amministrazione permessi ----

    def grantAccess(self, petitioner_id: str, access_level: str) -> dict:
        self.permissions.setdefault(petitioner_id, set()).add(access_level)
        rec = {
            "type": "GRANT",
            "petitioner_id": petitioner_id,
            "access_level": access_level,
            "timestamp": time.time(),
        }
        self.chain.submit(rec)
        return rec

    def revokeAccess(self, petitioner_id: str) -> dict:
        self.permissions.pop(petitioner_id, None)
        rec = {
            "type": "REVOKE",
            "petitioner_id": petitioner_id,
            "timestamp": time.time(),
        }
        self.chain.submit(rec)
        return rec

    def grantConsent(self, patient_id: str, petitioner_id: str) -> dict:
        """Il paziente acconsente che uno specifico petitioner acceda ai suoi dati."""
        self.consents.setdefault(patient_id, set()).add(petitioner_id)
        rec = {
            "type": "CONSENT",
            "patient_id": patient_id,
            "petitioner_id": petitioner_id,
            "timestamp": time.time(),
        }
        self.chain.submit(rec)
        return rec

    def checkPermissions(self, patient_id: str, petitioner_id: str) -> bool:
        """Verifica se petitioner può accedere ai dati del paziente (ruolo + consenso)."""
        has_role = bool(self.permissions.get(petitioner_id))
        has_consent = petitioner_id in self.consents.get(patient_id, set())
        return has_role and has_consent

    # ---- richiesta accesso a un dato ----

    def requestAccess(
        self, petitioner_id: str, patient_id: str, uri: str
    ) -> tuple[bool, bytes | None]:
        """Endpoint usato dai medici: registra il tentativo nel log e, se autorizzato,
        restituisce la chiave AES per decifrare il dato dal cloud.
        """
        approved = self.checkPermissions(patient_id, petitioner_id)
        rec = {
            "type": "ACCESS_REQUEST",
            "petitioner_id": petitioner_id,
            "patient_id": patient_id,
            "uri": uri,
            "approved": approved,
            "timestamp": time.time(),
        }
        self.chain.submit(rec)
        if approved:
            return True, self.key_registry.get(uri)
        return False, None
