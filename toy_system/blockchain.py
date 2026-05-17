"""Simplified blockchain for the project: each block is linked to the
previous one through its hash, there is a mempool for the pending
transactions and the validators take turns (round-robin). It's permissioned,
so not anyone can validate."""
import time
import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Block:
    index: int
    timestamp: float
    payload: dict  # the actual data the block carries
    prev_hash: str
    validator: str
    hash: str = ""

    def compute_hash(self) -> str:
        body = json.dumps(
            {k: v for k, v in asdict(self).items() if k != "hash"},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(body.encode()).hexdigest()


class Blockchain:
    """Permissioned chain. Only the validators I put in the list (hospitals,
    clinics, ministry) can create blocks: this is to prevent any random node
    from writing on the chain."""

    def __init__(self, name: str, validators: list[str]):
        self.name = name
        self.validators = validators
        self._rr_idx = 0
        self.chain: list[Block] = []
        self.mempool: list[dict] = []
        # genesis block: I build it by hand since it has no predecessor,
        # so prev_hash is all zeros
        gen = Block(0, time.time(), {"genesis": name}, "0" * 64, "system")
        gen.hash = gen.compute_hash()
        self.chain.append(gen)

    def submit(self, payload: dict) -> None:
        self.mempool.append(payload)

    def _next_validator(self) -> str:
        v = self.validators[self._rr_idx % len(self.validators)]
        self._rr_idx += 1
        return v

    def mine_one(self) -> Block | None:
        if not self.mempool:
            return None
        payload = self.mempool.pop(0)
        prev = self.chain[-1]
        validator = self._next_validator()
        blk = Block(
            index=len(self.chain),
            timestamp=time.time(),
            payload=payload,
            prev_hash=prev.hash,
            validator=validator,
        )
        blk.hash = blk.compute_hash()
        self.chain.append(blk)
        return blk

    def mine_all(self) -> list[Block]:
        out = []
        while self.mempool:
            b = self.mine_one()
            if b:
                out.append(b)
        return out

    def find(self, predicate) -> list[Block]:
        return [b for b in self.chain if predicate(b.payload)]

    def verify_chain(self) -> bool:
        for i in range(1, len(self.chain)):
            if self.chain[i].prev_hash != self.chain[i - 1].hash:
                return False
            if self.chain[i].hash != self.chain[i].compute_hash():
                return False
        return True
