import hashlib
import hmac
import sqlite3
import struct

import h2.config
import h2.connection
import h2.events
import httpx
import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from holodori_l2d import master


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def string(number, value):
    value = value.encode() if isinstance(value, str) else value
    return varint((number << 3) | 2) + varint(len(value)) + value


def encrypt(data, key, iv):
    encoder = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encoder.update(data) + encoder.finalize()


def test_master_manifest_from_encrypted_frame(monkeypatch):
    pack = (string(1, "Card") + string(2, "synthetic") + b"\x18\x80\x20"
            + string(4, "01" * 32) + string(5, "https://example.invalid/Card"))
    plain = string(1, "version-test") + string(2, pack)
    message_key = b"synthetic-message-key"
    header = struct.pack("<HBB", len(message_key) + 2, 0, len(message_key)) + message_key
    padder = PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    encrypted = encrypt(padded, hashlib.md5(master.NETWORK_KEYWORD).digest(),
                        hashlib.md5(master.NETWORK_KEYWORD + message_key).digest())
    wire = header + encrypted
    frame = b"\0" + struct.pack(">I", len(wire)) + wire
    monkeypatch.setattr(master, "_master_request", lambda *args: frame)
    manifest = master.fetch_master("chs")
    assert manifest["version"] == "version-test"
    assert manifest["packs"]["Card"]["file_size"] == 4096
    assert manifest["packs"]["Card"]["crypto_key"] == "01" * 32
    with pytest.raises(ValueError, match="长度"):
        master._master_payload(frame[:-1])
    with pytest.raises(ValueError, match="压缩"):
        master._master_payload(frame[:7] + b"\x01" + frame[8:])


@pytest.mark.parametrize("payload", [b"\x80", b"\x0a\x05ab", b"\x09abc", b"\x00", b"\x0f"])
def test_rejects_invalid_protobuf(payload):
    with pytest.raises(ValueError):
        list(master.fields(payload))


def test_grpc_error_in_trailers_is_not_http_success(monkeypatch):
    server = h2.connection.H2Connection(config=h2.config.H2Configuration(client_side=False))
    server.initiate_connection()

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def selected_alpn_protocol(self):
            return "h2"

        def sendall(self, data):
            for event in server.receive_data(data):
                if isinstance(event, h2.events.StreamEnded):
                    server.send_headers(1, [(":status", "200"), ("content-type", "application/grpc")])
                    server.send_headers(1, [("grpc-status", "14"), ("grpc-message", "try%20later")], end_stream=True)

        def recv(self, size):
            return server.data_to_send()

    stream = Stream()

    class Context:
        def set_alpn_protocols(self, protocols):
            pass

        def wrap_socket(self, connection, **kwargs):
            return stream

    monkeypatch.setattr(master.socket, "create_connection", lambda *a, **kw: stream)
    monkeypatch.setattr(master.ssl, "create_default_context", Context)
    with pytest.raises(RuntimeError, match="gRPC 14 try later"):
        master._master_request("chs", "1.2.1")


def test_sqlcipher_pages_and_tampering():
    key, salt = bytes(range(32)), bytes(range(16))
    auth_key = hashlib.pbkdf2_hmac("sha512", key, bytes(x ^ 0x3A for x in salt), 2, 32)
    raw, expected = bytearray(), bytearray(b"SQLite format 3\0")
    for number in (1, 2):
        size = 4000 if number == 1 else 4016
        payload = bytes([number]) * size
        if number == 1:
            payload = b"\x10\x00\x01\x01\x50" + payload[5:]
        iv = bytes([number]) * 16
        ciphertext = encrypt(payload, key, iv)
        signature = hmac.new(auth_key, ciphertext + iv + struct.pack("<I", number), "sha512").digest()
        raw.extend((salt if number == 1 else b"") + ciphertext + iv + signature)
        expected.extend(payload + b"\0" * 80)
    assert master.decrypt_pack(bytes(raw), key.hex()) == bytes(expected)
    for offset in (0, 200, 4035, 4300):
        damaged = bytearray(raw)
        damaged[offset] ^= 1
        with pytest.raises(ValueError, match="校验失败"):
            master.decrypt_pack(bytes(damaged), key.hex())
    with pytest.raises(ValueError, match="页大小"):
        master.decrypt_pack(bytes(raw[:-1]), key.hex())


def test_reads_protobuf_rows_from_sqlite_and_checks_ids(tmp_path, monkeypatch):
    path = tmp_path / "fixture.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE Lang(id TEXT PRIMARY KEY, data BLOB)")
        db.execute("INSERT INTO Lang VALUES (?,?)", ("name-1", string(1, "name-1") + string(1000, "测试卡牌")))
    blob = path.read_bytes()
    monkeypatch.setattr(master, "decrypt_pack", lambda data, key: blob)
    pack = {"type": "LangCard_Chs", "file_name": "test", "file_size": 4,
            "crypto_key": "00" * 32, "download_url": "https://example.invalid/pack"}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"pack"))
    with httpx.Client(transport=transport) as client:
        rows = master.read_table(client, pack, {1: "id", 1000: "text"}, tmp_path / "cache")
        assert rows == [{"id": "name-1", "text": "测试卡牌"}]
        with sqlite3.connect(path) as db:
            db.execute("UPDATE Lang SET id='wrong-id'")
        blob = path.read_bytes()
        with pytest.raises(ValueError, match="ID 不符"):
            master.read_table(client, pack, {1: "id", 1000: "text"}, tmp_path / "cache")
