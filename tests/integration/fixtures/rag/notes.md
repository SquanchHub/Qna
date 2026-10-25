# Networking Notes

These notes are a small fixture for the RAG integration tests. Each section
uses a made-up term that appears nowhere else in the corpus, so a question
about that term has exactly one correct source.

## Quindlewort protocol

The Quindlewort protocol requires three handshakes before any packet is
accepted. The first handshake announces the sender, the second confirms the
channel, and the third locks the session key. A Quindlewort session that skips
a handshake is dropped without a reply.

## Session timeouts

An idle session expires after ninety seconds. Clients should send a keepalive
every thirty seconds to stay connected, and reconnect with a fresh handshake
sequence if the server closes the session.

## Example client

The client below sends the three handshakes in order.

```python
# not a heading: this line is inside a fenced code block
def connect(sock):
    for step in ("announce", "confirm", "lock"):
        sock.send(step.encode())
```

A fenced comment that starts with a hash must never start a new section.
