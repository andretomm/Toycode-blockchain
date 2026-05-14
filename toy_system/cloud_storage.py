"""Storage cloud giocattolo: dict in-memory che indicizza blob cifrati per URI.

In un sistema reale sarebbe S3/Azure Blob/GCS. Qui interfaccia minimale: write/read/delete/tamper.
"""
import uuid


class CloudStorage:
    BASE_URI = "cloud://medvault/"

    def __init__(self):
        self._blobs: dict[str, bytes] = {}

    def write(self, ciphertext: bytes) -> str:
        uri = self.BASE_URI + uuid.uuid4().hex
        self._blobs[uri] = ciphertext
        return uri

    def read(self, uri: str) -> bytes | None:
        return self._blobs.get(uri)

    def tamper(self, uri: str, new_blob: bytes) -> None:
        """Simulazione di un attacco che modifica il dato cifrato sul cloud."""
        if uri in self._blobs:
            self._blobs[uri] = new_blob

    def delete(self, uri: str) -> None:
        self._blobs.pop(uri, None)
