"""Client HTTP per cloud_server. Espone stessa interfaccia di CloudStorage in-memory."""
import requests


class HttpCloudStorage:
    BASE_URI = "cloud://medvault/"

    def __init__(self, base_url: str = "http://127.0.0.1:5055"):
        self.base_url = base_url

    def _bid(self, uri: str) -> str:
        return uri.removeprefix(self.BASE_URI)

    def write(self, ciphertext: bytes) -> str:
        r = requests.post(f"{self.base_url}/blob", data=ciphertext, timeout=5)
        r.raise_for_status()
        return r.json()["uri"]

    def read(self, uri: str) -> bytes | None:
        r = requests.get(f"{self.base_url}/blob/{self._bid(uri)}", timeout=5)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.content

    def tamper(self, uri: str, new_blob: bytes) -> None:
        requests.put(
            f"{self.base_url}/blob/{self._bid(uri)}", data=new_blob, timeout=5
        ).raise_for_status()

    def delete(self, uri: str) -> None:
        requests.delete(f"{self.base_url}/blob/{self._bid(uri)}", timeout=5)
