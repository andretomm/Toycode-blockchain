"""Cloud storage HTTP reale (Flask). Sostituisce CloudStorage in-memory per demo di rete.

Endpoints:
    POST /blob          body = ciphertext bytes -> ritorna {"uri": "..."}
    GET  /blob/<id>     ritorna ciphertext bytes
    PUT  /blob/<id>     body = bytes (rimpiazzo: usato per simulare tampering)
    DELETE /blob/<id>
"""
import uuid
from flask import Flask, request, jsonify, abort, Response

app = Flask(__name__)
_BLOBS: dict[str, bytes] = {}
BASE_URI = "cloud://medvault/"


@app.post("/blob")
def write_blob():
    bid = uuid.uuid4().hex
    _BLOBS[bid] = request.get_data()
    return jsonify(uri=BASE_URI + bid)


@app.get("/blob/<bid>")
def read_blob(bid: str):
    if bid not in _BLOBS:
        abort(404)
    return Response(_BLOBS[bid], mimetype="application/octet-stream")


@app.put("/blob/<bid>")
def tamper_blob(bid: str):
    if bid not in _BLOBS:
        abort(404)
    _BLOBS[bid] = request.get_data()
    return "", 204


@app.delete("/blob/<bid>")
def delete_blob(bid: str):
    _BLOBS.pop(bid, None)
    return "", 204


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055)
