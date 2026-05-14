# Toy System — Blockchain 2-Layer per Healthcare

Sistema giocattolo che riproduce l'infrastruttura descritta in `Blockchains in healthcare.key`:
macchinari medicali → gateway (cifratura) → cloud storage + blockchain dati medici, con seconda
blockchain dedicata all'access logging e ai permessi.

> Scopo: dimostrazione didattica. Tutti i componenti sono in-process / localhost.
> NON usare in produzione.

---

## Architettura

```
+-----------+   samples    +---------+   AES-256-GCM   +---------------+
| Machine   | -----------> | Gateway | --------------> | Cloud (HTTP)  |
| (Ed25519) |              |         |                 |  Flask :5055  |
+-----------+              +----+----+                 +-------+-------+
                                |                              |
                                | (hash, uri, sig, ids)        | blob cifrato
                                v                              |
                       +-----------------+                     |
                       |  Medical Data   |                     |
                       |  smart contract |                     |
                       |  + chain        |                     |
                       +-----------------+                     |
                                                               |
+---------+    requestAccess     +----------------+   key      |
| Doctor  | -------------------> |  Access Log    | --------+  |
|         | <------- key ------- |  smart contract|         |  |
+---------+                      |  + chain       |         |  |
                                 +----------------+         v  v
                                                     decrypt(blob)
```

Due blockchain separate (permissioned, round-robin tra `hospital-A`, `clinic-B`,
`ministry-of-health`), entrambe in-memory.

---

## Layout file

| File | Ruolo |
|---|---|
| `crypto_utils.py` | AES-256-GCM (encrypt/decrypt) + SHA-256 |
| `blockchain.py` | `Block`, `Blockchain`, mempool, validatori round-robin |
| `cloud_server.py` | Server Flask sulla porta 5055 (POST/GET/PUT/DELETE blob) |
| `cloud_client.py` | `HttpCloudStorage` — client HTTP del cloud |
| `cloud_storage.py` | Variante in-memory (alternativa rapida senza rete) |
| `machine.py` | `MedicalMachine` — genera vitali, firma Ed25519 |
| `gateway.py` | `Gateway.ingest()` — pipeline aggregazione → cifra → cloud → on-chain |
| `doctor.py` | `Doctor.fetch()` — richiede accesso, decifra |
| `contracts/medical_data.py` | `registerMachine`, `registerData`, `verifyIntegrity` |
| `contracts/access_log.py` | `grantAccess`, `revokeAccess`, `grantConsent`, `checkPermissions`, `requestAccess` |
| `demo.py` | Orchestratore end-to-end (8 step, poi termina) |
| `live.py` | Runner "live": il sistema continua a girare e stampa un log in streaming |

---

## Setup

Una sola volta:

```bash
cd "toy_system"
python3 -m venv .venv
.venv/bin/pip install cryptography flask requests
```

Già fatto se `.venv/` è presente.

---

## Eseguire la demo

```bash
cd "toy_system"
.venv/bin/python demo.py
```

`demo.py` avvia automaticamente `cloud_server.py` come subprocess sulla porta 5055
e lo spegne alla fine. Stampa 8 step:

| # | Step | Cosa mostra |
|---|---|---|
| 0 | `registerMachine` | PKI on-chain (pubkey Ed25519 del macchinario) |
| 1 | `ingest` | Firma → cifratura → upload HTTP → submit on-chain |
| 2 | `grantAccess` + `grantConsent` | Setup permessi e consenso paziente |
| 3 | `requestAccess` autorizzato | Medico ottiene chiave, decifra blob |
| 4 | `requestAccess` negato | Tentativo loggato comunque |
| 5 | `verifyIntegrity` + tampering | Modifica blob su cloud → rilevata |
| 6 | Replay attack | Reinvio stesso record → rifiutato |
| 7 | Firma invalida | Macchinario spoofato → rifiutato |
| 8 | `verify_chain` | Catena hash dei blocchi valida |

---

## Modalità live

`demo.py` esegue 8 step e poi termina. `live.py` invece **non termina**: avvia il
cloud server, registra macchinari e medici, poi entra in un loop che continua a
generare attività e la stampa in streaming, una riga per evento.

```bash
cd "toy_system"
.venv/bin/python live.py            # ritmo di default
.venv/bin/python live.py --fast     # eventi e blocchi più frequenti
.venv/bin/python live.py --seed 7   # run deterministico
```

`Ctrl-C` (o `SIGTERM`) per fermare — spegne anche `cloud_server.py`.

Cosa genera in continuo:

| Evento | Significato |
|---|---|
| `INGEST` | un macchinario firma un lotto → gateway cifra → upload HTTP → submit on-chain |
| `MINED` | un blocco esce dal mempool, validato round-robin (`hospital-A`/`clinic-B`/`ministry-of-health`) |
| `ACCESS` | un medico fa `requestAccess`: `GRANTED` (decifra), `DENIED` (loggato comunque) o `GRANTED ma blob CORROTTO` se il blob è stato manomesso |
| `ATTACK tamper` | `PUT` malevolo sul cloud → `verifyIntegrity=False` |
| `ATTACK replay` | reinvio di `(hash, uri)` già on-chain → rifiutato |
| `ATTACK fake-signature` | macchinario impersonato (chiave diversa) → firma Ed25519 invalida → rifiutato |
| `ATTACK unknown-machine` | macchinario non in PKI on-chain → rifiutato |
| `STATUS` | numero blocchi / validità catena / mempool / record prodotti |

Mining e generazione eventi girano su thread separati con un lock sulle chain.

---

## Uso interattivo (REPL)

```python
from blockchain import Blockchain
from cloud_storage import CloudStorage          # variante in-memory
from contracts.medical_data import MedicalDataContract
from contracts.access_log import AccessLogContract
from gateway import Gateway
from machine import MedicalMachine
from doctor import Doctor

validators = ["hospital-A", "clinic-B", "ministry-of-health"]
data_chain = Blockchain("medical-data", validators)
access_chain = Blockchain("access-log", validators)
cloud = CloudStorage()
keys = {}

med = MedicalDataContract(data_chain, cloud)
acl = AccessLogContract(access_chain, keys)
gw  = Gateway(cloud, med, keys)

m = MedicalMachine("ECG-001", "patient-42")
med.registerMachine(m.machine_id, m.public_key_bytes())
rec = gw.ingest(m, n_samples=5)
data_chain.mine_all()

acl.grantAccess("doc-Rossi", "cardiology-read")
acl.grantConsent("patient-42", "doc-Rossi")
access_chain.mine_all()

d = Doctor("doc-Rossi", acl, cloud)
print(d.fetch("patient-42", rec["uri"]))
```

Sostituisci `CloudStorage()` con `HttpCloudStorage()` (da `cloud_client`) se hai
`cloud_server.py` in esecuzione separatamente:

```bash
.venv/bin/python cloud_server.py    # in un altro terminale
```

---

## Ispezione delle blockchain

```python
for b in data_chain.chain:
    print(b.index, b.validator, b.hash[:12], b.payload)

data_chain.verify_chain()       # True/False
access_chain.find(lambda p: p.get("type") == "ACCESS_REQUEST")
```

---

## Cose da provare in presentazione

1. **Audit trail**: dopo accesso negato (step 4 demo), stampa
   `access_chain.find(lambda p: p.get("approved") is False)` — vedi richiesta loggata.
2. **Opacità del cloud**: `print(cloud.read(rec["uri"])[:60])` → solo bytes cifrati.
3. **Scalability**: aumenta `n_samples=1000` in `gw.ingest()` — blob cloud cresce,
   record on-chain resta costante (~250 byte).
4. **MITM simulato**: avvia `cloud_server.py`, fai `curl -X PUT
   http://127.0.0.1:5055/blob/<id> -d 'tampered'`, poi
   `med.verifyIntegrity(rec["hash"], rec["uri"])` → `False`.
5. **Replay**: chiama `med.registerData(...)` due volte con stessa coppia
   `(hash, uri)` → `ReplayAttackError`.

---

## Estensioni possibili

- Sostituire la chain in-memory con un network multi-nodo (asyncio + WebSocket).
- Riscrivere i due smart contract in Solidity (Hardhat) o Chaincode Go (Fabric).
- Aggiungere KMS dedicato al posto del `key_registry` dict.
- Salvare la chain su LevelDB per persistenza tra esecuzioni.
- Firme a soglia (threshold) per validatori (BLS) invece di round-robin.

---

## Mapping presentazione → codice

| Slide | Implementazione |
|---|---|
| "Gateway aggrega/cifra AES-256/hash SHA-256" | `gateway.py::Gateway.ingest` |
| `registerData(...)` | `contracts/medical_data.py` |
| `verifyIntegrity(...)` | idem (rileva tampering) |
| `grantAccess` / `revokeAccess` / `checkPermissions` | `contracts/access_log.py` |
| Hyperledger Fabric round-robin permissioned | `Blockchain._next_validator()` |
| Log accessi (approvati + negati) | `requestAccess` → submit on-chain sempre |
| MITM machine↔gateway | firma Ed25519 + AES-GCM authenticated |
| Cloud breach / tampering | demo step 5 |
| Fake identity / key theft | demo step 7 + access log immutabile |
