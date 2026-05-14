# Blockchain in Healthcare — Infrastrutture 2-Layer

*Andrea Tommasi, Sara Risaliti, Ilaria Leka*

---

## 1. Introduzione: perché una blockchain "tradizionale" non basta

L'idea di archiviare cartelle cliniche, referti e flussi di telemetria medica direttamente
su una blockchain pubblica è seducente sul piano della tamper-resistance, ma si scontra
con due ostacoli sostanziali. Il primo è la **privacy**: una blockchain pubblica replica
ogni dato su tutti i nodi della rete, e questo è incompatibile con la natura sensibile dei
dati sanitari, oltre che con i vincoli normativi imposti dal GDPR (in particolare il
"diritto all'oblio", art. 17, difficilmente conciliabile con un registro per costruzione
immutabile). Il secondo è la **scalabilità**: i blocchi di una blockchain hanno
dimensioni limitate, il throughput è dell'ordine di poche decine di transazioni al
secondo per le reti più mature, e ogni byte scritto on-chain ha un costo significativo
sia in termini di memoria — replicata su tutti i nodi — sia di tempo di validazione.

Per superare questi limiti la letteratura ha consolidato il pattern delle
**blockchain a 2 layer** (2L), nelle quali la blockchain custodisce solo metadati e prove
di integrità, mentre i dati veri e propri vivono in uno storage layer esterno.
Approcci di riferimento sono MedRec del MIT [1] ed Ancile [2], che hanno entrambi
introdotto un disaccoppiamento tra catena e storage in ambito sanitario; più in generale,
il pattern è stato sistematizzato in numerose survey, fra cui [3] e [4].

---

## 2. Fondamenti di una blockchain 2-Layer

In un'infrastruttura 2L il flusso di scrittura segue uno schema preciso:

1. il dato grezzo è memorizzato in modo sicuro in uno storage layer (database, cloud, IPFS);
2. di quel dato viene calcolato un hash crittografico (tipicamente SHA-256);
3. l'hash, insieme a un riferimento al dato (URI/URL) e ai relativi metadati, è inviato
   a uno smart contract che genera una transazione on-chain;
4. la blockchain conserva quindi solo il "fingerprint" e il puntatore: il dato è
   altrove, ma qualsiasi modifica successiva alla sua copia di storage produrrebbe un
   hash diverso da quello on-chain, rendendo la manomissione immediatamente rilevabile.

Si parla in questo senso di **tamper-evidence**: il dato non è reso immodificabile, ma
ogni alterazione è rilevabile in tempo costante confrontando l'hash ricalcolato con
quello sigillato on-chain.

### Tre famiglie di storage layer

- **Database storage** — un DBMS locale (relazionale o documentale). È la soluzione più
  semplice, ma trasforma il database in un *single point of failure*: se viene
  compromesso o reso indisponibile, la blockchain conserva solo puntatori a vuoto.
- **Cloud storage** — un'infrastruttura cloud-edge, in cui un gateway intermedio
  pre-processa e cifra i dati prima del caricamento. È l'approccio adottato in questo
  progetto e in lavori come [2] e [5].
- **IPFS** — una rete peer-to-peer ad indirizzamento per contenuto, in cui il
  riferimento on-chain è un *Content Identifier* (CID) derivato dall'hash stesso del
  dato; tamper-evidence è quindi una proprietà intrinseca del meccanismo di lookup.
  L'uso di IPFS in ambito medicale è discusso ad esempio in [6].

---

## 3. L'infrastruttura proposta: blockchain + cloud per macchinari sanitari

L'architettura presentata è pensata per uno scenario di tipo *machine-to-blockchain*:
un parco di macchinari medicali (ECG, pulsossimetri, monitor multiparametrici) produce
in modo continuo dati di telemetria sui pazienti; questi dati devono essere conservati
in modo verificabile, accessibili a medici e ricercatori autorizzati, e tracciabili a
livello di ogni singolo accesso.

### 3.1 Layer 2 — Cloud storage cifrato

Il cloud storage del nostro sistema svolge un ruolo strettamente passivo: archivia blob
opachi. Tutta la cifratura avviene a monte, prima della trasmissione, perché trasmettere
in chiaro tra gateway e cloud aprirebbe la strada a un attacco *man-in-the-middle* (MITM):
chi intercetta il traffico leggerebbe direttamente cartelle cliniche.
Lo schema di cifratura adottato è **AES-256-GCM**, scelta standard per *authenticated
encryption with associated data* [7], che fornisce in un'unica primitiva confidenzialità
e integrità del singolo blob.

### 3.2 Il cloud gateway

Il gateway è la *trust boundary* fra macchinari e cloud. Svolge cinque compiti:

- riceve i sample dal macchinario;
- aggrega e pre-processa il lotto;
- cifra il lotto con AES-256 usando una chiave fresca per ogni lotto;
- carica il blob cifrato sul cloud, ottenendo un URI;
- calcola lo SHA-256 del blob cifrato e lo invia, insieme all'URI e ai metadati, allo
  smart contract.

In questo modo la chiave AES non lascia il gateway (tipicamente verrebbe affidata a un
KMS dedicato), il cloud vede solo bytes opachi e l'on-chain conserva la prova di
integrità.

### 3.3 Layer 1 — La blockchain dei dati medici

Sulla blockchain dei dati medici lo smart contract `registerData` riceve hash, URI,
ID paziente, ID macchinario e timestamp, costruisce il payload e lo inserisce nella
**mempool**, da cui un validatore — selezionato in *round-robin* fra ospedali, cliniche
e ministero della sanità — lo estrae e lo "mina" in un blocco. Si tratta dunque di una
blockchain **permissioned**, secondo il modello di Hyperledger Fabric [8]: solo le
entità accreditate possono validare, il consenso non richiede proof-of-work e il
throughput è molto più alto delle reti pubbliche.

Uno **smart contract** [9] è un programma deterministico, archiviato sulla chain stessa,
che codifica regole di tipo *if-else* per gestire le transazioni: in questo contesto
opera come intermediario tra macchinari e ledger, validando ogni richiesta di scrittura
prima che diventi un blocco.

### 3.4 Layer 1 — La blockchain dell'access log

Una seconda blockchain, distinta dalla prima, conserva il **log immutabile degli accessi**.
Quando un medico o un ricercatore vuole consultare un dato:

1. invia una `requestAccess` allo smart contract `AccessLog`;
2. il contratto verifica il consenso del paziente e il ruolo del richiedente;
3. se autorizzato, restituisce la chiave AES per decifrare il blob; in caso contrario
   nega l'accesso;
4. **in entrambi i casi** la richiesta viene loggata on-chain.

Il fatto che anche gli accessi negati siano scritti sulla chain è cruciale per gli audit:
un'analisi posteriore del log può rivelare pattern di attacco (es. tentativi di accesso
con identità rubate) che altrimenti resterebbero invisibili.

Le funzioni esposte dal contratto sono:

- `registerData(...)` — scrive un nuovo record sulla chain dei dati;
- `verifyIntegrity(hash, uri)` — verifica che il blob sul cloud non sia stato manomesso;
- `grantAccess(petitioner, level)` / `revokeAccess(petitioner)` — gestione ruoli;
- `grantConsent(patient, petitioner)` — consenso paziente-specifico;
- `checkPermissions(patient, petitioner)` — verifica congiunta ruolo + consenso.

### 3.5 Validazione permissioned e Hyperledger Fabric

L'uso di Hyperledger Fabric come substrato è coerente con la natura del dominio: in
sanità non esiste una rete di partecipanti anonimi, ma un insieme noto di
organizzazioni accreditate. Il consenso PBFT/Raft di Fabric e la sua *Membership
Service Provider* permettono un controllo fine di chi può validare e leggere [8].
Il sistema giocattolo usa un semplice round-robin come stand-in didattico per il
selettore di validatori.

---

## 4. Problematiche di sicurezza: lo spostamento, non la rimozione, dei problemi

L'architettura 2L non elimina le minacce: ne ridistribuisce la superficie. Le principali
emergenze identificate sono quattro.

**4.1 Malfunzionamento del macchinario e fake data injection.** Un macchinario guasto
può produrre dati errati; un medico malintenzionato può iniettarli ad arte. Le
conseguenze sono cliniche: diagnosi sbagliata, terapia inadeguata, peggioramento del
paziente. La blockchain *non* è in grado di riconoscere se un dato firmato è
*plausibile*: garantisce solo che provenga effettivamente dal macchinario registrato e
non sia stato alterato dopo. Una difesa robusta richiede validazione semantica
(es. range fisiologici, redundancy cross-device) e attestazione hardware [10].

**4.2 MITM tra macchinario e gateway.** Un attaccante in posizione *on-path* potrebbe
leggere, manipolare o tagliare il flusso. Cifrare *direttamente dal macchinario* può
sembrare la soluzione ovvia, ma è errato per due motivi: (i) molti macchinari
medicali sono dispositivi *legacy* con capacità crittografiche limitate; (ii) cifrando
prima del gateway si nega al gateway stesso la possibilità di aggregare e validare il
dato in chiaro. La soluzione realistica passa per canale autenticato (TLS mutuo) o per
firma asimmetrica del lotto, come nel toy system.

**4.3 Compromissione dell'infrastruttura cloud.** Un attaccante con accesso al cloud
può leggere (in chiaro? no, perché tutto è cifrato), cancellare, cifrare a riscatto o
rendere indisponibile lo storage. Un attacco DDoS può privare gli ospedali dell'accesso
ai dati. La blockchain mitiga solo l'aspetto di *tampering rilevabile*, non la
disponibilità, che resta una proprietà del cloud.

**4.4 Furto di identità e di chiavi.** In una rete a chiavi pubbliche, *possedere la
chiave equivale ad essere il legittimo proprietario*. Se un attaccante ruba la chiave
di un medico con privilegi ampi, ottiene de facto i suoi privilegi. L'access log
blockchain è qui un alleato investigativo: una post-mortem analysis può rivelare
pattern anomali (accessi notturni, query massive, anomalie geografiche) [11].

---

## Riferimenti

[1] Azaria, A., Ekblaw, A., Vieira, T., Lippman, A. *"MedRec: Using Blockchain for
Medical Data Access and Permission Management"*, OBD 2016.

[2] Dagher, G. G., Mohler, J., Milojkovic, M., Marella, P. B. *"Ancile: Privacy-preserving
framework for access control and interoperability of electronic health records using
blockchain technology"*, Sustainable Cities and Society, 2018.

[3] Hölbl, M., Kompara, M., Kamišalić, A., Nemec Zlatolas, L. *"A Systematic Review of
the Use of Blockchain in Healthcare"*, Symmetry, 2018.

[4] Agbo, C. C., Mahmoud, Q. H., Eklund, J. M. *"Blockchain Technology in Healthcare:
A Systematic Review"*, Healthcare, 2019.

[5] Esposito, C., De Santis, A., Tortora, G., Chang, H., Choo, K. K. R. *"Blockchain:
A Panacea for Healthcare Cloud-Based Data Security and Privacy?"*, IEEE Cloud Computing,
2018.

[6] Kumar, R., Marchang, N., Tripathi, R. *"Distributed Off-Chain Storage of Patient
Diagnostic Reports in Healthcare System Using IPFS and Blockchain"*, COMSNETS 2020.

[7] NIST SP 800-38D. *"Recommendation for Block Cipher Modes of Operation:
Galois/Counter Mode (GCM) and GMAC"*, 2007.

[8] Androulaki, E., et al. *"Hyperledger Fabric: A Distributed Operating System for
Permissioned Blockchains"*, EuroSys 2018.

[9] Szabo, N. *"Smart Contracts: Building Blocks for Digital Markets"*, 1996.

[10] Halperin, D., et al. *"Pacemakers and Implantable Cardiac Defibrillators: Software
Radio Attacks and Zero-Power Defenses"*, IEEE S&P 2008.

[11] OWASP. *"Logging and Monitoring Cheat Sheet"*, owasp.org.

[12] Documentazione `cryptography` (PyCA), `https://cryptography.io`.

[13] Documentazione Flask, `https://flask.palletsprojects.com`.

---

# Parte II — Traduzione dell'infrastruttura in codice Python

Il sistema giocattolo (`toy_system/`) implementa fedelmente l'architettura descritta
nelle slide, con tutti i componenti in-process o su `localhost`. L'obiettivo è
didattico: riprodurre i meccanismi di sicurezza chiave (firme, cifratura autenticata,
permissioned validation, anti-replay, access log immutabile) in poche centinaia di
righe leggibili.

## 5. Mappa dell'infrastruttura → moduli Python

| Componente dell'architettura | Modulo Python |
|---|---|
| Macchinario medicale (firma Ed25519) | `machine.py` |
| Gateway di cifratura e aggregazione | `gateway.py` |
| Cloud storage (blob opachi via HTTP) | `cloud_server.py`, `cloud_client.py` |
| Variante in-memory del cloud | `cloud_storage.py` |
| Blockchain permissioned + mempool + round-robin | `blockchain.py` |
| Smart contract dati medici | `contracts/medical_data.py` |
| Smart contract access log + permessi | `contracts/access_log.py` |
| Petitioner (medico) | `doctor.py` |
| Primitive crittografiche (AES-256-GCM, SHA-256) | `crypto_utils.py` |
| Demo end-to-end | `demo.py` |
| Modalità live (loop continuo + attacchi) | `live.py` |

## 6. Componenti fondamentali

### 6.1 `crypto_utils.py` — Le primitive

Lo strato crittografico è volutamente minimale: tre funzioni che incapsulano la libreria
PyCA `cryptography` [12]. `encrypt` genera un nonce a 96 bit con `os.urandom`, applica
AES-GCM e restituisce `nonce || ciphertext`. `sha256` calcola lo hash che diventerà la
prova di integrità on-chain.

```python
def encrypt(plaintext: bytes, key: bytes) -> bytes:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, associated_data=None)
    return nonce + ct
```

Importante: GCM è un *AEAD*, quindi la decifratura fallisce automaticamente se il blob
è stato manomesso anche di un singolo byte — una seconda linea di difesa rispetto alla
verifica SHA-256 lato blockchain.

### 6.2 `machine.py` — Macchinario con firma Ed25519

Ogni macchinario ha una coppia di chiavi Ed25519 generata al boot. La chiave pubblica
viene registrata on-chain via `registerMachine` e usata dallo smart contract per
verificare la firma di ogni lotto. Ed25519 [scelta su curva Edwards] è preferito a
RSA per dimensione delle chiavi, velocità di firma e resistenza a side-channel.

```python
class MedicalMachine:
    def __init__(self, machine_id, patient_id):
        self._sk = Ed25519PrivateKey.generate()

    def sign(self, payload: bytes) -> bytes:
        return self._sk.sign(payload)
```

I "vitali" generati (heart rate, SpO2, pressione, temperatura) sono casuali ma in range
fisiologico: bastano a popolare la pipeline.

### 6.3 `gateway.py` — La pipeline di ingest

Il metodo `Gateway.ingest()` è la traduzione diretta della slide "Il cloud gateway".
Esegue, nell'ordine, le sei operazioni descritte:

```python
def ingest(self, machine, n_samples=5):
    samples = machine.stream(n_samples=n_samples)
    plaintext = MedicalMachine.serialize(samples)

    key = generate_key()                # chiave fresca per lotto
    ciphertext = encrypt(plaintext, key)
    uri = self.cloud.write(ciphertext)  # upload
    data_hash = sha256(ciphertext)      # signature

    self.key_registry[uri] = key        # depositata per l'access log

    signed_payload = f"{data_hash}|{uri}|{machine.patient_id}|{machine.machine_id}".encode()
    signature = machine.sign(signed_payload)

    return self.contract.registerData(
        data_hash=data_hash, uri=uri,
        patient_id=machine.patient_id, machine_id=machine.machine_id,
        signature=signature,
    )
```

Da notare: la chiave AES *non* viene mai trasmessa al cloud; resta nel `key_registry`,
indicizzato per URI, che sarà l'unico canale tramite cui un petitioner autorizzato
potrà ottenerla.

### 6.4 `blockchain.py` — Catena permissioned con mempool

La blockchain è una lista di `Block` collegati da `prev_hash`. Ogni blocco contiene il
payload (dizionario JSON-serializzabile), il timestamp, l'ID del validatore e l'hash
del blocco precedente.

Punti notevoli:

- `submit(payload)` mette il payload nella **mempool**, replicando il flusso slide
  "block is then inserted in the mempool waiting for validation".
- `mine_one()` estrae un payload, sceglie il validatore successivo tramite
  `_next_validator()` (round-robin su `["hospital-A", "clinic-B", "ministry-of-health"]`)
  e ne crea il blocco.
- `verify_chain()` ricalcola in cascata gli hash e verifica che ogni `prev_hash` punti
  effettivamente al blocco precedente: è il check di integrità della catena.

```python
def _next_validator(self):
    v = self.validators[self._rr_idx % len(self.validators)]
    self._rr_idx += 1
    return v
```

Round-robin è uno stand-in didattico per il consenso ordinato di Fabric (Raft/PBFT) [8]:
in produzione sostituirebbe i protocolli reali, mantenendo invariata la semantica
"permissioned".

### 6.5 `contracts/medical_data.py` — Smart contract dati

Implementa la slide "Layer 1: the blockchain, data side" con tre controlli che vengono
eseguiti *prima* di accettare un record:

1. il macchinario è registrato (chiave pubblica nota);
2. la firma Ed25519 è valida sul payload `hash|uri|patient_id|machine_id`;
3. la coppia `(hash, uri)` non è già stata vista (**anti-replay**).

```python
if pubkey is None: raise UnknownMachineError(...)
if not MedicalMachine.verify(pubkey, signed_payload, signature):
    raise InvalidSignatureError(...)
if (data_hash, uri) in self._seen:
    raise ReplayAttackError(...)
```

`verifyIntegrity(hash, uri)` realizza il test "il blob sul cloud è stato manomesso?":
ricalcola lo SHA-256 del blob, lo confronta con quello on-chain e con quello passato
dal chiamante. Se il blob è stato alterato, i tre hash non coincidono e la funzione
restituisce `False`.

### 6.6 `contracts/access_log.py` — Permessi e log immutabile

Mantiene due strutture di "world state" — `permissions` (ruoli) e `consents` (consensi
paziente-petitioner) — accanto al log immutabile delle transazioni. Lo stesso pattern
di Hyperledger Fabric, che affianca a CouchDB/LevelDB il ledger replicato [8].

Il cuore è `requestAccess`:

```python
def requestAccess(self, petitioner_id, patient_id, uri):
    approved = self.checkPermissions(patient_id, petitioner_id)
    self.chain.submit({
        "type": "ACCESS_REQUEST", "petitioner_id": petitioner_id,
        "patient_id": patient_id, "uri": uri, "approved": approved,
        "timestamp": time.time(),
    })
    if approved:
        return True, self.key_registry.get(uri)
    return False, None
```

Si noti che `chain.submit(...)` è invocato **prima** del `return`, e in entrambi i rami:
ogni tentativo finisce sulla chain, anche se negato. È esattamente il comportamento
descritto nelle slide ("The transaction, either approved or denied, is still saved on
the access log blockchain") e il prerequisito per audit forensi.

### 6.7 `cloud_server.py` e `cloud_client.py` — Cloud HTTP

Il cloud è un piccolo server Flask [13] in ascolto su `127.0.0.1:5055` che espone
quattro endpoint REST (`POST/GET/PUT/DELETE /blob/<id>`). Il client è `HttpCloudStorage`,
con la stessa interfaccia della variante in-memory `CloudStorage` — sostituibili
indifferentemente nel resto del codice. La PUT esposta è quella che il `live.py` userà
per simulare un attacco di tampering.

### 6.8 `doctor.py` — Il petitioner

Un medico che vuole leggere un dato esegue una sequenza in due passi: chiede la chiave
al contratto di access log e, se autorizzato, decifra il blob scaricato dal cloud.

```python
approved, key = self.access_contract.requestAccess(...)
if not approved or key is None: return None
plaintext = decrypt(self.cloud.read(uri), key)
```

L'autorizzazione e la decifratura sono **decisamente disaccoppiate**: solo la
combinazione di entrambe restituisce dato leggibile.

## 7. Demo e modalità live

`demo.py` esegue otto step end-to-end, ciascuno corrispondente a uno scenario discusso
nelle slide:

| Step | Concetto delle slide |
|---|---|
| 0. `registerMachine` | PKI on-chain delle pubkey macchinario |
| 1. `ingest` | Pipeline gateway → cloud → on-chain |
| 2. `grantAccess` + `grantConsent` | Setup permessi e consenso |
| 3. `requestAccess` autorizzato | Recupero chiave + decifratura |
| 4. `requestAccess` negato | Log su chain del tentativo |
| 5. Tampering del blob cloud | `verifyIntegrity` ritorna `False` |
| 6. Replay attack | `ReplayAttackError` |
| 7. Firma invalida (macchinario spoofato) | `InvalidSignatureError` |
| 8. `verify_chain` | Coerenza della catena |

`live.py` rimuove la natura "scriptata" della demo: avvia il cloud, registra macchinari
e medici, e poi entra in un loop multi-thread che genera continuamente eventi di
ingest, accesso e attacchi (tamper, replay, fake-signature, unknown-machine),
stampando un log in streaming. È pensato per dimostrare in presentazione come il sistema
reagisce *runtime* alle anomalie.

## 8. Cosa il toy system mostra (e cosa no)

**Mostra**: il pattern 2L (hash on-chain, dato off-chain), tamper-evidence via
SHA-256 + AEAD, permissioned validation, access log immutabile come strumento di audit,
mitigazione concreta di replay, MITM e impersonificazione di macchinari.

**Non mostra**: rete multi-nodo, persistenza, KMS hardware, gestione chiavi al ciclo
di vita, validazione semantica dei dati (es. range fisiologici), defense-in-depth
sull'identità dei petitioner (MFA, attestazione). Le slide ne discutono i limiti nella
sezione sulla sicurezza; il codice li riproduce solo nella misura necessaria a renderli
osservabili.
