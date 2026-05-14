"""End-to-end demo estesa:
- cloud HTTP reale (cloud_server in subprocess)
- firma Ed25519 del macchinario
- anti-replay on-chain
- tampering rilevato + firma invalida + replay rifiutato
"""
import os
import sys
import time
import subprocess
import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blockchain import Blockchain
from cloud_client import HttpCloudStorage
from contracts.medical_data import (
    MedicalDataContract,
    InvalidSignatureError,
    ReplayAttackError,
)
from contracts.access_log import AccessLogContract
from gateway import Gateway
from machine import MedicalMachine
from doctor import Doctor


def banner(text: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def print_chain(chain: Blockchain) -> None:
    for b in chain.chain:
        payload_short = {
            k: (v[:20] + "…" if isinstance(v, str) and len(v) > 24 else v)
            for k, v in b.payload.items()
        }
        print(f"  [#{b.index}] validator={b.validator:20s} hash={b.hash[:16]}…")
        print(f"          payload={payload_short}")


def start_cloud_server() -> subprocess.Popen:
    here = os.path.dirname(os.path.abspath(__file__))
    proc = subprocess.Popen(
        [sys.executable, os.path.join(here, "cloud_server.py")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # wait for readiness
    import requests

    for _ in range(40):
        try:
            requests.get("http://127.0.0.1:5055/blob/ping", timeout=0.2)
            return proc
        except Exception:
            time.sleep(0.1)
    return proc


def main() -> None:
    cloud_proc = start_cloud_server()
    try:
        validators = ["hospital-A", "clinic-B", "ministry-of-health"]
        data_chain = Blockchain("medical-data", validators)
        access_chain = Blockchain("access-log", validators)

        cloud = HttpCloudStorage()  # HTTP reale!
        key_registry: dict[str, bytes] = {}

        medical_contract = MedicalDataContract(data_chain, cloud)
        access_contract = AccessLogContract(access_chain, key_registry)
        gateway = Gateway(cloud, medical_contract, key_registry)

        # ---- registrazione macchinario nella PKI on-chain ----
        banner("0) Registrazione macchinario (pubkey Ed25519) on-chain")
        machine = MedicalMachine("ECG-001", "patient-42")
        medical_contract.registerMachine(machine.machine_id, machine.public_key_bytes())
        data_chain.mine_all()
        print(f"  pubkey registrata per {machine.machine_id}")

        # ---- 1) ingestione ----
        banner("1) Ingest: macchinario firma -> gateway cifra -> cloud HTTP -> on-chain")
        rec = gateway.ingest(machine, n_samples=3)
        print(f"  hash={rec['hash'][:16]}…  uri={rec['uri']}")
        print(f"  signature={rec['signature'][:32]}…")
        data_chain.mine_all()
        print_chain(data_chain)

        # ---- 2) permessi ----
        banner("2) grantAccess + grantConsent")
        access_contract.grantAccess("doc-Rossi", "cardiology-read")
        access_contract.grantConsent("patient-42", "doc-Rossi")
        access_chain.mine_all()

        # ---- 3) accesso autorizzato ----
        banner("3) Medico autorizzato -> requestAccess -> decifra blob HTTP")
        doc_ok = Doctor("doc-Rossi", access_contract, cloud)
        data = doc_ok.fetch("patient-42", rec["uri"])
        print(f"  Dati decifrati ({len(data)} sample): {data[0]}")
        access_chain.mine_all()

        # ---- 4) accesso negato ----
        banner("4) Medico non autorizzato -> negato (loggato comunque)")
        doc_evil = Doctor("doc-Mallory", access_contract, cloud)
        print(f"  Risultato: {doc_evil.fetch('patient-42', rec['uri'])}")
        access_chain.mine_all()

        # ---- 5) integrità ----
        banner("5) verifyIntegrity OK -> tampering HTTP -> rilevato")
        print(f"  Integrità pre-tamper: {medical_contract.verifyIntegrity(rec['hash'], rec['uri'])}")
        cloud.tamper(rec["uri"], b"PAYLOAD MALICIOSO VIA HTTP PUT")
        print(f"  Integrità post-tamper: {medical_contract.verifyIntegrity(rec['hash'], rec['uri'])}")

        # ---- 6) anti-replay: rinviamo stessa (hash, uri) ----
        banner("6) Anti-replay: rinvio dello stesso record")
        try:
            medical_contract.registerData(
                data_hash=rec["hash"],
                uri=rec["uri"],
                patient_id="patient-42",
                machine_id="ECG-001",
                signature=bytes.fromhex(rec["signature"]),
            )
            print("  ERRORE: replay accettato!")
        except ReplayAttackError as e:
            print(f"  Replay rifiutato come atteso: {e}")

        # ---- 7) firma invalida: macchinario impersonato ----
        banner("7) Firma invalida: attaccante prova a registrare dato spoofato")
        fake_machine = MedicalMachine("ECG-001", "patient-42")  # stesso id, KEY DIVERSA
        # firma con la chiave SBAGLIATA (quella nuova, non quella registrata)
        fake_payload = b"deadbeef|cloud://medvault/fakefakefake|patient-42|ECG-001"
        bad_sig = fake_machine.sign(fake_payload)
        try:
            medical_contract.registerData(
                data_hash="deadbeef",
                uri="cloud://medvault/fakefakefake",
                patient_id="patient-42",
                machine_id="ECG-001",
                signature=bad_sig,
            )
            print("  ERRORE: firma invalida accettata!")
        except InvalidSignatureError as e:
            print(f"  Firma rifiutata come atteso: {e}")

        # ---- 8) chain integrity ----
        banner("8) Verifica concatenazione hash blocchi")
        print(f"  data-chain valida?   {data_chain.verify_chain()}")
        print(f"  access-chain valida? {access_chain.verify_chain()}")

        banner("DEMO ESTESA COMPLETATA")
    finally:
        cloud_proc.send_signal(signal.SIGTERM)
        cloud_proc.wait(timeout=3)


if __name__ == "__main__":
    main()
