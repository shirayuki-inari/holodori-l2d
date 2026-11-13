"""Read official master packs and the Octo model index, without a data mirror.

The wire format is gRPC + Qua.Network AES-CBC, followed by protobuf. Master
packs use SQLCipher 4 pages with raw AES keys, containing protobuf rows.
Only the fields needed for card/model lookup are decoded here.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import socket
import sqlite3
import ssl
import struct
import tempfile
from pathlib import Path
from urllib.parse import unquote

from .util import write_atomic


HOST = "us.game-hololive-dreams.com"
APP_VERSION = "auto"
BUNDLED_APP_VERSION = "1.2.101"
APP_BUNDLE_ID = "game.qualiarts.hololive.dreams.com"
# Shared game-client protocol constants, not user credentials or session tokens.
# Raw master-pack keys are obtained at runtime and are not bundled with the tool.
NETWORK_KEYWORD = b"BJYZ0w3DJm"
OCTO_KEY = "B46OtKlGGHoz6sxbOWDe3VUvBsagXxr5av38IQIKUKo="
OCTO_CLIENT_KEY = "CwFhQ+S5m4nERWVaq5oFZIP0cZLc0j7O/zllG0UYVNo="
FIXED_SIZES = {1: 8, 5: 4}  # protobuf wire types: fixed64 / fixed32


class MasterRequestError(RuntimeError):
    def __init__(self, http_status: str | None, grpc_status: str | None, detail: str):
        self.outdated = http_status == "200" and grpc_status == "3" and detail == "OUTDATED_APP"
        super().__init__(
            f"Master 请求失败：HTTP {http_status} / gRPC {grpc_status} {detail}；"
            "请检查 --app-version"
        )


def _validated_version(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError("游戏客户端版本应为三段数字，例如 1.2.101")
    return value


def _google_play_version(client) -> str:
    response = client.get(
        "https://play.google.com/store/apps/details",
        params={"id": APP_BUNDLE_ID, "hl": "en", "gl": "US"},
    )
    response.raise_for_status()
    # Play's SoftwareApplication JSON-LD omits the version. Its embedded app
    # details contain this nested version entry; fail closed if the layout changes.
    versions = set(re.findall(r'\[\[\["([0-9]+\.[0-9]+\.[0-9]+)"\]\],\[\[', response.text))
    if len(versions) != 1:
        raise ValueError("Google Play 页面缺少唯一的客户端版本")
    return _validated_version(versions.pop())


def _app_store_version(client) -> str:
    response = client.get(
        "https://itunes.apple.com/lookup", params={"id": "6756641249", "country": "us"},
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        for app in data["results"]:
            if isinstance(app, dict) and app.get("bundleId") == APP_BUNDLE_ID:
                return _validated_version(app.get("version"))
    raise ValueError("App Store 未返回国际服客户端版本")


def _versioned_master_request(language: str, app_version: str) -> bytes:
    if app_version != "auto":
        # An explicit override must be honored, including outdated versions.
        return _master_request(language, _validated_version(app_version))
    try:
        return _master_request(language, BUNDLED_APP_VERSION)
    except MasterRequestError as error:
        if not error.outdated:
            raise
        original = error

    import httpx

    logging.getLogger(__name__).warning(
        "游戏客户端版本 %s 已过期，正在从官方商店查询新版本……", BUNDLED_APP_VERSION,
    )
    tried = {BUNDLED_APP_VERSION}
    failures = []
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for source, lookup in (("Google Play", _google_play_version), ("App Store", _app_store_version)):
            try:
                version = lookup(client)
            except (httpx.HTTPError, ValueError) as error:
                failures.append(f"{source}：{error}")
                continue
            if version in tried:
                failures.append(f"{source} 返回的版本 {version} 仍已过期")
                continue
            tried.add(version)
            try:
                return _master_request(language, version)
            except MasterRequestError as error:
                if not error.outdated:
                    raise
                failures.append(f"{source} 版本 {version}：OUTDATED_APP")
    raise RuntimeError(
        "自动获取可用客户端版本失败；可用 --app-version <当前游戏版本> 手动指定。"
        + "；".join(failures)
    ) from original


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("protobuf varint 被截断")
        byte = data[offset]
        offset += 1
        if shift == 63 and byte > 1:
            raise ValueError("protobuf varint 超出 uint64")
        value |= (byte & 127) << shift
        if not byte & 128:
            return value, offset
    raise ValueError("无效 protobuf varint")


def fields(data: bytes):
    """Yield protobuf fields, skipping no bytes and rejecting truncated payloads."""
    offset = 0
    while offset < len(data):
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if not 0 < number < (1 << 29):
            raise ValueError("无效 protobuf 字段编号")
        if wire == 0:
            value, offset = _varint(data, offset)
        else:
            if wire == 2:
                size, offset = _varint(data, offset)
            elif wire in FIXED_SIZES:
                size = FIXED_SIZES[wire]
            else:
                raise ValueError(f"不支持的 protobuf wire type：{wire}")
            if size > len(data) - offset:
                raise ValueError("protobuf 字段被截断")
            value = data[offset:offset + size]
            offset += size
        yield number, wire, value


def _strings(data: bytes, schema: dict[int, str]) -> dict[str, str]:
    return {
        schema[number]: value.decode("utf-8")
        for number, wire, value in fields(data)
        if number in schema and wire == 2
    }


def _cbc(data: bytes, key: bytes, iv: bytes, *, padded: bool = False) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    decoder = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = decoder.update(data) + decoder.finalize()
    if padded:
        unpadder = PKCS7(128).unpadder()
        plain = unpadder.update(plain) + unpadder.finalize()
    return plain


def _master_payload(body: bytes) -> bytes:
    if len(body) < 5 or body[0] != 0:
        raise ValueError("不支持的 Master gRPC 帧")
    size = int.from_bytes(body[1:5], "big")
    if size != len(body) - 5:
        raise ValueError("Master gRPC 帧长度不符")
    wire = body[5:]
    if len(wire) < 4:
        raise ValueError("Master 加密头被截断")
    header_size = int.from_bytes(wire[:2], "little") + 2
    key_end = 4 + wire[3]
    if not 4 <= key_end <= header_size < len(wire):
        raise ValueError("无效 Master 加密头")
    if wire[2] != 0:
        raise ValueError("暂不支持此 Master 响应压缩格式")
    key = hashlib.md5(NETWORK_KEYWORD).digest()
    iv = hashlib.md5(NETWORK_KEYWORD + wire[4:key_end]).digest()
    return _cbc(wire[header_size:], key, iv, padded=True)


def _master_request(language: str, app_version: str) -> bytes:
    # Read HTTP/2 trailers explicitly: HTTP 200 alone does not mean gRPC success.
    import h2.config
    import h2.connection
    import h2.events

    context = ssl.create_default_context()
    context.set_alpn_protocols(["h2"])
    response = bytearray()
    headers = {}
    with socket.create_connection((HOST, 443), timeout=30) as connection:
        with context.wrap_socket(connection, server_hostname=HOST) as stream:
            if stream.selected_alpn_protocol() != "h2":
                raise RuntimeError("官方主数据接口需要 HTTP/2")
            client = h2.connection.H2Connection(
                config=h2.config.H2Configuration(client_side=True, header_encoding="utf-8")
            )
            client.initiate_connection()
            client.send_headers(1, [
                (":method", "POST"), (":scheme", "https"), (":authority", HOST),
                (":path", "/rpc.api.Master/Get"),
                ("content-type", "application/grpc+proto-enc"), ("te", "trailers"),
                ("grpc-accept-encoding", "identity"), ("x-app-version", app_version),
                ("x-app-bundle-id", APP_BUNDLE_ID),
                ("x-app-lang-type", language), ("x-app-os-type", "Android"),
                ("x-app-store-type", "GooglePlay"),
            ])
            client.send_data(1, b"\0" * 5, end_stream=True)
            stream.sendall(client.data_to_send())
            ended = False
            while not ended:
                incoming = stream.recv(65536)
                if not incoming:
                    raise RuntimeError("Master 响应未完成，连接已关闭")
                for event in client.receive_data(incoming):
                    if isinstance(event, (h2.events.ResponseReceived, h2.events.TrailersReceived)):
                        headers.update(event.headers)
                    elif isinstance(event, h2.events.DataReceived):
                        response.extend(event.data)
                        client.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                    elif isinstance(event, h2.events.StreamEnded):
                        ended = True
                    elif isinstance(event, (h2.events.StreamReset, h2.events.ConnectionTerminated)):
                        if not ended:
                            raise RuntimeError(f"Master HTTP/2 连接中断：{event}")
                outgoing = client.data_to_send()
                if outgoing:
                    stream.sendall(outgoing)
    if headers.get(":status") != "200" or headers.get("grpc-status") != "0":
        detail = unquote(headers.get("grpc-message", ""))
        raise MasterRequestError(headers.get(":status"), headers.get("grpc-status"), detail)
    return bytes(response)


def fetch_master(language: str, app_version: str = APP_VERSION) -> dict:
    plain = _master_payload(_versioned_master_request(language, app_version))
    manifest = {"version": "", "packs": {}}
    schema = {1: "type", 2: "file_name", 4: "crypto_key", 5: "download_url"}
    for number, wire, value in fields(plain):
        if number == 1 and wire == 2:
            manifest["version"] = value.decode("utf-8")
        elif number == 2 and wire == 2:
            pack = _strings(value, schema)
            pack["file_size"] = next((v for n, w, v in fields(value) if n == 3 and w == 0), 0)
            if not all(pack.get(k) for k in schema.values()) or pack["file_size"] <= 0:
                raise ValueError("Master 返回了不完整的数据包条目")
            manifest["packs"][pack["type"]] = pack
    if not manifest["version"] or not manifest["packs"]:
        raise ValueError("Master 响应缺少版本或数据包列表")
    return manifest


def decrypt_pack(data: bytes, key_hex: str) -> bytes:
    """Authenticate every SQLCipher 4 page before producing a SQLite database."""
    if not re.fullmatch(r"[a-fA-F0-9]{64}", key_hex):
        raise ValueError("主数据包密钥应为 32 字节十六进制 raw key")
    if not data or len(data) % 4096:
        raise ValueError("主数据包长度不是 SQLCipher 4 页大小的倍数")
    key = bytes.fromhex(key_hex)
    salt = bytes(byte ^ 0x3A for byte in data[:16])
    auth_key = hashlib.pbkdf2_hmac("sha512", key, salt, 2, 32)
    plain = bytearray(b"SQLite format 3\0")
    for offset in range(0, len(data), 4096):
        page = data[offset:offset + 4096]
        encrypted = page[16 if offset == 0 else 0:-80]
        iv, signature = page[-80:-64], page[-64:]
        number = offset // 4096 + 1
        expected = hmac.new(auth_key, encrypted + iv + struct.pack("<I", number), "sha512").digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError(f"主数据包第 {number} 页校验失败（文件损坏或密钥不匹配）")
        plain.extend(_cbc(encrypted, key, iv))
        plain.extend(b"\0" * 80)
    if plain[16:21] != b"\x10\x00\x01\x01\x50":
        raise ValueError("不支持的主数据 SQLite 页格式")
    return bytes(plain)


def read_table(client, pack: dict, schema: dict[int, str], cache_root: Path) -> list[dict]:
    identity = hashlib.sha256((pack["type"] + ":" + pack["file_name"]).encode()).hexdigest()
    path = cache_root / "packs" / (identity + ".pack")
    data = path.read_bytes() if path.exists() else b""
    plain = None
    if len(data) == pack["file_size"]:
        try:
            plain = decrypt_pack(data, pack["crypto_key"])
        except ValueError:
            pass  # Re-fetch a corrupt cached pack; validate before replacing it.
    if plain is None:
        response = client.get(pack["download_url"])
        response.raise_for_status()
        data = response.content
        if len(data) != pack["file_size"]:
            raise ValueError(f"主数据包下载长度不符：{pack['type']}")
        plain = decrypt_pack(data, pack["crypto_key"])
    if not path.exists() or path.read_bytes() != data:
        write_atomic(path, data)
    table = "Lang" if pack["type"].startswith("Lang") else pack["type"]
    if table not in {"Lang", "Card", "Character", "Costume"}:
        raise ValueError(f"不支持的主数据表：{table}")
    # A temporary file also supports Python 3.10 (no sqlite3.deserialize).
    with tempfile.TemporaryDirectory(prefix="master-", dir=cache_root) as temporary:
        database = Path(temporary) / "master.db"
        database.write_bytes(plain)
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            rows = []
            for row_id, blob in connection.execute(f'SELECT id, data FROM "{table}"'):
                row = _strings(blob, schema)
                if row.get("id") != row_id:
                    raise ValueError(f"主数据记录 ID 不符：{table} / {row_id}")
                rows.append(row)
            return rows
        finally:
            connection.close()


def fetch_models(client) -> tuple[int, set[str]]:
    response = client.get(
        f"https://{HOST}/asset/v2/pub/a/5/v/200001/list/0",
        headers={"X-OCTO-KEY": OCTO_KEY, "X-APP-OCTO-KEY": OCTO_CLIENT_KEY},
    )
    response.raise_for_status()
    body = response.content
    if len(body) < 32:
        raise ValueError("Octo 索引响应过短")
    plain = _cbc(body[16:], hashlib.sha256(OCTO_KEY.encode()).digest(), body[:16], padded=True)
    revision, models = 0, set()
    for number, wire, value in fields(plain):
        if number == 1 and wire == 0:
            revision = value
        elif number == 2 and wire == 2:
            name = _strings(value, {2: "name"}).get("name", "")
            if name.startswith("live2d_mdl_"):
                models.add(name)
    if not revision or not models:
        raise ValueError("Octo 索引缺少版本或 Live2D 模型")
    return revision, models
