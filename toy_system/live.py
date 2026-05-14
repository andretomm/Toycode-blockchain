"""Live runner: invece di terminare, il sistema continua a girare e stampa
un log in streaming di ciò che accade — ingest dei macchinari, mining dei
blocchi, richieste di accesso dei medici e attacchi simulati.

Uso:
    .venv/bin/python live.py            # ritmo di default
    .venv/bin/python live.py --fast     # eventi più frequenti
    .venv/bin/python live.py --seed 7   # deterministico

Ctrl-C per fermare (spegne anche il cloud_server).
"""
import os
import sys
import time
import random
import signal
import argparse
import threading
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blockchain import Blockchain
from cloud_client import HttpCloudStorage
from contracts.medical_data import (
    MedicalDataContract,
    InvalidSignatureError,
    ReplayAttackError,
    UnknownMachineError,
)
from contracts.access_log import AccessLogContract
from gateway import Gateway
from machine import MedicalMachine
from doctor import Doctor


# ---------------------------------------------------------------- logging ----

_LOG_LOCK = threading.Lock()


def log(tag: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    with _LOG_LOCK:
        print(f"[{ts}] {tag:8s} {msg}", flush=True)


# ------------------------------------------------------------ cloud server ----

def start_cloud_server() -> subprocess.Popen:
    here = os.path.dirname(os.path.abspath(__file__))
    proc = subprocess.Popen(
        [sys.executable, os.path.join(here, "cloud_server.py")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    import requests

    for _ in range(40):
        try:
            requests.get("http://127.0.0.1:5055/blob/ping", timeout=0.2)
            return proc
        except Exception:
            time.sleep(0.1)
    return proc


# ------------------------------------------------------------------ world ----

class World:
    """Tiene insieme chain, contratti, macchinari, medici e gli URI noti."""

    def __init__(self) -> None:
        self.chain_lock = threading.Lock()
        validators = ["hospital-A", "clinic-B", "ministry-of-health"]
        self.data_chain = Blockchain("medical-data", validators)
        self.access_chain = Blockchain("access-log", validators)
        self.cloud = HttpCloudStorage()
        self.key_registry: dict[str, bytes] = {}
        self.medical = MedicalDataContract(self.data_chain, self.cloud)
        self.access = AccessLogContract(self.access_chain, self.key_registry)
        self.gateway = Gateway(self.cloud, self.medical, self.key_registry)

        # macchinari registrati on-chain (PKI)
        self.machines = [
            MedicalMachine("ECG-001", "patient-42"),
            MedicalMachine("SPO2-007", "patient-99"),
            MedicalMachine("BP-013", "patient-42"),
        ]
        for m in self.machines:
            self.medical.registerMachine(m.machine_id, m.public_key_bytes())
            log("REGISTER", f"machine {m.machine_id} pubkey on-chain  (patient={m.patient_id})")

        # un medico autorizzato e uno no
        self.access.grantAccess("doc-Rossi", "cardiology-read")
        self.access.grantConsent("patient-42", "doc-Rossi")
        self.access.grantConsent("patient-99", "doc-Rossi")
        log("GRANT", "doc-Rossi -> cardiology-read  + consenso patient-42, patient-99")
        self.doctors = [
            Doctor("doc-Rossi", self.access, self.cloud),     # autorizzato
            Doctor("doc-Mallory", self.access, self.cloud),   # NON autorizzato
        ]

        # URI prodotti finora: (uri, hash, machine_id, signature_hex, patient_id)
        self.records: list[dict] = []

    # ---- azioni del mondo ----

    def do_ingest(self) -> None:
        m = random.choice(self.machines)
        n = random.randint(2, 6)
        with self.chain_lock:
            rec = self.gateway.ingest(m, n_samples=n)
        self.records.append({**rec, "machine_id": m.machine_id})
        log("INGEST", f"{m.machine_id}  n={n}  uri={rec['uri']}  hash={rec['hash'][:12]}…")

    def do_access(self) -> None:
        if not self.records:
            return
        rec = random.choice(self.records)
        doc = random.choice(self.doctors)
        patient = next(m.patient_id for m in self.machines if m.machine_id == rec["machine_id"])
        try:
            with self.chain_lock:
                data = doc.fetch(patient, rec["uri"])
        except Exception:
            # blob manomesso sul cloud: AES-GCM rifiuta la decifratura
            log("ACCESS", f"{doc.id}  {patient}  {rec['uri']}  -> GRANTED ma blob CORROTTO (AES-GCM tag fail)")
            return
        if data is None:
            log("ACCESS", f"{doc.id}  {patient}  {rec['uri']}  -> DENIED (loggato on-chain)")
        else:
            log("ACCESS", f"{doc.id}  {patient}  {rec['uri']}  -> GRANTED, decifrati {len(data)} sample")

    def do_tamper(self) -> None:
        if not self.records:
            return
        rec = random.choice(self.records)
        with self.chain_lock:
            self.cloud.tamper(rec["uri"], b"PAYLOAD MALICIOSO " + os.urandom(4).hex().encode())
            ok = self.medical.verifyIntegrity(rec["hash"], rec["uri"])
        log("ATTACK", f"tamper {rec['uri']}  -> verifyIntegrity={ok}")

    def do_replay(self) -> None:
        if not self.records:
            return
        rec = random.choice(self.records)
        patient = next(m.patient_id for m in self.machines if m.machine_id == rec["machine_id"])
        try:
            with self.chain_lock:
                self.medical.registerData(
                    data_hash=rec["hash"],
                    uri=rec["uri"],
                    patient_id=patient,
                    machine_id=rec["machine_id"],
                    signature=bytes.fromhex(rec["signature"]),
                )
            log("ATTACK", f"replay {rec['uri']}  -> ACCETTATO (BUG!)")
        except ReplayAttackError:
            log("ATTACK", f"replay {rec['uri']}  -> rifiutato (anti-replay on-chain)")

    def do_fake_signature(self) -> None:
        impostor = MedicalMachine("ECG-001", "patient-42")  # stesso id, chiave diversa
        h = os.urandom(8).hex()
        uri = "cloud://medvault/" + os.urandom(6).hex()
        payload = f"{h}|{uri}|patient-42|ECG-001".encode()
        try:
            with self.chain_lock:
                self.medical.registerData(
                    data_hash=h, uri=uri, patient_id="patient-42",
                    machine_id="ECG-001", signature=impostor.sign(payload),
                )
            log("ATTACK", "fake-signature ECG-001  -> ACCETTATO (BUG!)")
        except InvalidSignatureError:
            log("ATTACK", "fake-signature ECG-001  -> rifiutato (firma Ed25519 invalida)")

    def do_unknown_machine(self) -> None:
        rogue = MedicalMachine("ROGUE-666", "patient-42")
        h = os.urandom(8).hex()
        uri = "cloud://medvault/" + os.urandom(6).hex()
        payload = f"{h}|{uri}|patient-42|ROGUE-666".encode()
        try:
            with self.chain_lock:
                self.medical.registerData(
                    data_hash=h, uri=uri, patient_id="patient-42",
                    machine_id="ROGUE-666", signature=rogue.sign(payload),
                )
            log("ATTACK", "unknown-machine ROGUE-666  -> ACCETTATO (BUG!)")
        except UnknownMachineError:
            log("ATTACK", "unknown-machine ROGUE-666  -> rifiutato (non in PKI on-chain)")

    def do_status(self) -> None:
        with self.chain_lock:
            d, a = self.data_chain, self.access_chain
            log("STATUS",
                f"data-chain: {len(d.chain)} blk valid={d.verify_chain()} mempool={len(d.mempool)}  | "
                f"access-chain: {len(a.chain)} blk valid={a.verify_chain()} mempool={len(a.mempool)}  | "
                f"records={len(self.records)}")


# ------------------------------------------------------------ mining loop ----

def miner_loop(world: World, stop: threading.Event, period: float) -> None:
    while not stop.is_set():
        time.sleep(period)
        with world.chain_lock:
            b1 = world.data_chain.mine_one()
            b2 = world.access_chain.mine_one()
        if b1:
            log("MINED", f"data  #{b1.index}  {b1.validator:18s} {b1.payload.get('type','?')}  {b1.hash[:12]}…")
        if b2:
            log("MINED", f"access #{b2.index}  {b2.validator:18s} {b2.payload.get('type','?')}  {b2.hash[:12]}…")


# ------------------------------------------------------------------- main ----

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="eventi/blocchi più frequenti")
    ap.add_argument("--seed", type=int, default=None, help="seed RNG per run deterministico")
    args = ap.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    event_period = (0.4, 1.2) if args.fast else (1.5, 4.0)
    mine_period = 0.7 if args.fast else 2.0

    # SIGTERM -> trattalo come Ctrl-C, così il finally spegne il cloud_server
    def _on_sigterm(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, _on_sigterm)

    cloud_proc = start_cloud_server()
    stop = threading.Event()
    try:
        log("BOOT", "cloud_server :5055 pronto — avvio sistema live")
        world = World()

        miner = threading.Thread(target=miner_loop, args=(world, stop, mine_period), daemon=True)
        miner.start()

        # azioni pesate: l'ingest è il caso normale, gli attacchi sono rari
        actions = [
            (world.do_ingest,         6),
            (world.do_access,         5),
            (world.do_status,         2),
            (world.do_tamper,         1),
            (world.do_replay,         1),
            (world.do_fake_signature, 1),
            (world.do_unknown_machine,1),
        ]
        population = [fn for fn, w in actions for _ in range(w)]

        log("READY", "Ctrl-C per fermare\n" + "-" * 78)
        while True:
            random.choice(population)()
            time.sleep(random.uniform(*event_period))
    except KeyboardInterrupt:
        print()
        log("STOP", "interrotto dall'utente")
    finally:
        stop.set()
        cloud_proc.send_signal(signal.SIGTERM)
        try:
            cloud_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            cloud_proc.kill()


if __name__ == "__main__":
    main()
