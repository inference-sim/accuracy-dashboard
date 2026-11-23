"""dump_extract: the archive reader, the COPY text, the pin and the extract hash check -- on small archives built here, no
network and no dump. (Its end-to-end equality with the frozen anchor extract is shown by running it on the real parts.)"""
import gzip
import hashlib
import http.server
import io
import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dump_extract as dx  # noqa: E402

HAVE_ZSTD = shutil.which("zstd") is not None


# ---------------------------------------------------------------- a pg_dump -Fc archive, written the way pg_dump does
def w_int(v):
    return bytes([1 if v < 0 else 0]) + abs(v).to_bytes(4, "little")


def w_str(s):
    if s is None:
        return w_int(-1)
    b = s.encode()
    return w_int(len(b)) + b


def toc_entry(dump_id, tag, copy):
    out = w_int(dump_id) + w_int(1)
    for s in ("0", "0", tag, "TABLE DATA"):
        out += w_str(s)
    out += w_int(3)                                           # section: data
    for s in ("", "", copy, "public", None, None):            # defn, drop, copy, namespace, tablespace, tableam
        out += w_str(s)
    out += w_int(ord("r")) + w_str("owner") + w_str("false")  # relkind, owner, withOids
    out += w_str(None)                                        # no dependencies
    return out + bytes([2]) + (0).to_bytes(8, "little")       # the data offset, unknown on a pipe


def archive(tables, chunk=7, tail=b"\n\n"):
    """tables: [(tag, columns, [row text, ...])]; the data is cut into chunks of `chunk` bytes whatever the rows are."""
    out = b"PGDMP" + bytes([1, 16, 0, 4, 8, 1, 0])
    out += b"".join(w_int(0) for _ in range(7)) + w_str("db") + w_str("17.11") + w_str("18.4")
    out += w_int(len(tables))
    for i, (tag, cols, _) in enumerate(tables, 1):
        out += toc_entry(i, tag, f'COPY public.{tag} ({", ".join(cols)}) FROM stdin;\n')
    for i, (_, _, rows) in enumerate(tables, 1):
        data = "".join(r + "\n" for r in rows).encode() + tail
        out += bytes([1]) + w_int(i)
        for k in range(0, len(data), chunk):
            piece = data[k:k + chunk]
            out += w_int(len(piece)) + piece
        out += w_int(0)
    return out


TABLES = [
    ("t1", ["id", "v"], ["1\talpha", "22\tbe\\tta\\nline", "333\t\\N", "4\tdelta"]),
    ("other", ["id"], ["9"]),
]


def read_all(a):
    got = {}
    for e in a.blocks():
        got[e["tag"]] = [r for r in dx.rows(a)]
    return got


def test_reader_reads_header_toc_and_rows_whatever_the_chunking():
    for chunk in (1, 3, 7, 4096):
        a = dx.Archive(io.BytesIO(archive(TABLES, chunk)))
        assert a.version == (1, 16, 0) and a.dbname == "db" and a.server_version == "17.11"
        assert [e["tag"] for e in a.toc.values()] == ["t1", "other"]
        assert dx.columns(a.toc[1]["copy"]) == ["id", "v"]
        got = read_all(a)
        assert got["t1"] == [b"1\talpha", b"22\tbe\\tta\\nline", b"333\t\\N", b"4\tdelta"], chunk
        assert got["other"] == [b"9"]


def test_row_filter_drops_rejected_rows_without_holding_them_and_keeps_the_rest():
    for chunk in (1, 5, 4096):
        a = dx.Archive(io.BytesIO(archive(TABLES, chunk)))
        next(a.blocks())
        assert list(dx.rows(a, keep=lambda first: first in (b"22", b"4"))) == [b"22\tbe\\tta\\nline", b"4\tdelta"]


def test_a_chunk_larger_than_a_piece_is_read_in_pieces(monkeypatch):
    monkeypatch.setattr(dx, "PIECE", 4)
    a = dx.Archive(io.BytesIO(archive(TABLES, 4096)))
    assert read_all(a)["t1"][1] == b"22\tbe\\tta\\nline"


def test_skip_block_moves_to_the_next_table():
    a = dx.Archive(io.BytesIO(archive(TABLES, 5)))
    next(a.blocks())
    dx.skip_block(a)
    e = next(a.blocks())
    assert e["tag"] == "other" and list(dx.rows(a)) == [b"9"]


def test_reader_refuses_what_it_does_not_read():
    good = archive(TABLES)
    with pytest.raises(dx.DumpError, match="not a pg_dump"):
        dx.Archive(io.BytesIO(b"NOTADUMP" + good[5:]))
    with pytest.raises(dx.DumpError, match="version"):
        dx.Archive(io.BytesIO(good[:5] + bytes([1, 17, 0]) + good[8:]))
    with pytest.raises(dx.DumpError, match="compressed"):
        dx.Archive(io.BytesIO(good[:11] + bytes([2]) + good[12:]))
    with pytest.raises(dx.DumpError, match="short"):
        a = dx.Archive(io.BytesIO(good[:-3]))
        read_all(a)


def test_a_block_that_ends_inside_a_row_stops_the_read():
    torn = archive([("t1", ["id", "v"], ["1\talpha"])], 4, tail=b"2\tbe")
    a = dx.Archive(io.BytesIO(torn))
    next(a.blocks())
    with pytest.raises(dx.DumpError, match="inside a row"):
        list(dx.rows(a))


def test_copy_values():
    assert dx.copy_value(b"\\N") is None
    assert dx.copy_value(b"plain") == "plain"
    assert dx.copy_value(b"a\\tb\\nc\\rd\\\\e") == "a\tb\nc\rd\\e"
    assert dx.copy_value("é".encode()) == "é"
    assert dx.copy_value(b"\\101\\x42") == "AB"
    with pytest.raises(dx.DumpError):
        dx.record(["a", "b"], b"only-one")


@pytest.mark.parametrize("ts,want", [
    ("2026-04-17 13:00:12+00", "2026-04-17 13:00:12+00"),
    ("2026-04-17 13:00:12.123456+00", "2026-04-17 13:00:12+00"),
    ("2026-04-17 15:00:12+02", "2026-04-17 13:00:12+00"),
    ("2026-04-17 08:30:12-04:30", "2026-04-17 13:00:12+00"),
    ("2026-04-17 00:10:00+01", "2026-04-16 23:10:00+00"),
    (None, None),
])
def test_run_start_is_printed_in_utc(ts, want):
    assert dx.utc_text(ts) == want


# ---------------------------------------------------------------- the pin
def pin_doc():
    parts = [{"name": f"p{i}", "sha256": hashlib.sha256(bytes([i])).hexdigest()} for i in range(3)]
    listing = "".join(f"{p['sha256']}  {p['name']}\n" for p in parts)
    return {"ref": "db-dump/2026-09-28", "base_url": "http://x", "parts": parts, "extract_sha256": "a" * 64,
            "sha256sums": hashlib.sha256(listing.encode()).hexdigest()}


def test_committed_pin_is_consistent_and_names_the_cache_key():
    pin = dx.load_pin()
    assert len(pin["parts"]) == 17 and pin["ref"] == "db-dump/2026-09-28"
    assert dx.cache_key(pin) == f"dump-extract-2026-09-28-{pin['extract_sha256']}"


def test_pin_refuses_a_part_hash_that_is_not_the_pinned_sums(tmp_path):
    doc = pin_doc()
    (tmp_path / "ok.json").write_text(json.dumps(doc))
    assert dx.load_pin(tmp_path / "ok.json")["ref"] == doc["ref"]
    doc["parts"][1]["sha256"] = "0" * 64
    (tmp_path / "bad.json").write_text(json.dumps(doc))
    with pytest.raises(dx.DumpError, match="SHA256SUMS"):
        dx.load_pin(tmp_path / "bad.json")
    doc = pin_doc()
    doc["ref"] = "latest"
    (tmp_path / "ref.json").write_text(json.dumps(doc))
    with pytest.raises(dx.DumpError, match="db-dump/"):
        dx.load_pin(tmp_path / "ref.json")


# ---------------------------------------------------------------- the extract hash
def make_extract(root, logs=("log one\r\n", "log two\n"), pulled_at="2026-11-01T00:00:00Z"):
    points = []
    for i, text in enumerate(logs):
        pid = f"{i:064x}"
        raw = text.encode()
        d = root / "points" / pid
        d.mkdir(parents=True)
        (d / "server_log.gz").write_bytes(gzip.compress(raw, mtime=0))
        points.append({"point_id": pid, "files": {"server_log": {"path": "server_log.gz", "sha256": hashlib.sha256(raw).hexdigest()}}})
    m = {"pulled_at": pulled_at, "base_models": {"org/m": None}, "source": "x", "window": ["2026-01-01", "2026-02-01"],
         "ledger": {"revision": "db-dump/2026-09-28", "unlisted": []}, "points": points}
    (root / "manifest.json").write_text(json.dumps(m, sort_keys=True) + "\n")
    return root


def pin_for(root):
    return {"extract_sha256": dx.content_sha256(root)}


def test_content_hash_ignores_when_and_how_the_extract_was_cut_and_nothing_else(tmp_path):
    a, b = make_extract(tmp_path / "a"), make_extract(tmp_path / "b", pulled_at="2027-01-01T00:00:00Z")
    assert dx.content_sha256(a) == dx.content_sha256(b)
    m = json.loads((b / "manifest.json").read_text())
    m["source"] = "elsewhere"
    (b / "manifest.json").write_text(json.dumps(m))
    assert dx.content_sha256(a) == dx.content_sha256(b)
    m["window"] = ["2026-01-01", "2026-02-02"]
    (b / "manifest.json").write_text(json.dumps(m))
    assert dx.content_sha256(a) != dx.content_sha256(b)
    c = make_extract(tmp_path / "c", logs=("log one\n", "log two\n"))
    assert dx.content_sha256(a) != dx.content_sha256(c)         # a log that differs only by a CR is another extract


def test_content_hash_covers_base_models_because_scoring_reads_them(tmp_path):
    """A lookup_failed (or an edited base_model) turns a point into a G5 refusal, so two extracts that differ only there
    must not both match one pin."""
    a, b = make_extract(tmp_path / "a"), make_extract(tmp_path / "b")
    m = json.loads((b / "manifest.json").read_text())
    for changed in ({"org/m": "org/base"}, {"org/m": {"lookup_failed": "HTTP 429"}}):
        m["base_models"] = changed
        (b / "manifest.json").write_text(json.dumps(m))
        assert dx.content_sha256(a) != dx.content_sha256(b)
    assert not dx.verify(a, pin_for(a))
    assert dx.verify(b, pin_for(a))


def test_verify_passes_an_intact_extract(tmp_path):
    root = make_extract(tmp_path / "e")
    assert dx.verify(root, pin_for(root)) == []


def test_verify_refuses_each_way_an_extract_can_differ(tmp_path):
    root = make_extract(tmp_path / "e")
    pin = pin_for(root)
    pid = f"{0:064x}"
    assert any("not the pinned" in p for p in dx.verify(root, {"extract_sha256": "f" * 64}))
    f = root / "points" / pid / "server_log.gz"
    good = f.read_bytes()
    f.write_bytes(gzip.compress(b"tampered", mtime=0))
    assert any("not the bytes the manifest hashes" in p for p in dx.verify(root, pin))
    f.unlink()
    assert any("is missing" in p for p in dx.verify(root, pin))
    f.write_bytes(good)
    (root / "points" / pid / "extra.gz").write_bytes(b"x")
    assert any("not in the manifest" in p for p in dx.verify(root, pin))
    (root / "points" / pid / "extra.gz").unlink()
    (root / "manifest.json").unlink()
    assert dx.verify(root, pin) == ["no manifest.json"]


def test_cli_verify_exits_nonzero_on_a_mismatch(tmp_path):
    root = make_extract(tmp_path / "e")
    pin = pin_doc() | pin_for(root)
    (tmp_path / "pin.json").write_text(json.dumps(pin))
    assert dx.main(["--pin", str(tmp_path / "pin.json"), "verify", "--extract", str(root)]) == 0
    (root / "points" / f"{0:064x}" / "server_log.gz").write_bytes(gzip.compress(b"tampered", mtime=0))
    assert dx.main(["--pin", str(tmp_path / "pin.json"), "verify", "--extract", str(root)]) == 1
    assert dx.main(["--pin", str(tmp_path / "pin.json"), "verify", "--extract", str(tmp_path / "none")]) == 1


# ---------------------------------------------------------------- the parts
def parts_of(payload: bytes, n=3):
    cut = [len(payload) * i // n for i in range(n + 1)]
    out = []
    for i in range(n):
        blob = subprocess.run(["zstd", "-q", "-c"], input=payload[cut[i]:cut[i + 1]], capture_output=True, check=True).stdout
        out.append((f"part{i:02d}", blob))
    return out


def pin_of(parts, base_url="http://x"):
    ps = [{"name": n, "sha256": hashlib.sha256(b).hexdigest()} for n, b in parts]
    listing = "".join(f"{p['sha256']}  {p['name']}\n" for p in ps)
    return {"ref": "db-dump/2026-09-28", "base_url": base_url, "parts": ps, "extract_sha256": "a" * 64,
            "sha256sums": hashlib.sha256(listing.encode()).hexdigest()}


@pytest.mark.skipif(not HAVE_ZSTD, reason="zstd not installed")
def test_part_stream_yields_the_archive_and_checks_every_part(tmp_path):
    payload = archive(TABLES, 5)
    parts = parts_of(payload)
    for n, b in parts:
        (tmp_path / n).write_bytes(b)
    ps = dx.PartStream(pin_of(parts), tmp_path)
    a = dx.Archive(ps.out)
    assert read_all(a)["t1"][0] == b"1\talpha"
    ps.close()
    # one flipped byte in the last part: the archive is read to its end, then the run stops
    last = tmp_path / parts[-1][0]
    blob = bytearray(last.read_bytes())
    blob[-1] ^= 1
    last.write_bytes(bytes(blob))
    ps = dx.PartStream(pin_of(parts), tmp_path)
    with pytest.raises(dx.DumpError):
        try:
            read_all(dx.Archive(ps.out))
        finally:
            ps.close()


@pytest.mark.skipif(not HAVE_ZSTD, reason="zstd not installed")
def test_part_stream_refuses_a_part_whose_hash_is_not_the_pin(tmp_path):
    parts = parts_of(archive(TABLES, 5))
    for n, b in parts:
        (tmp_path / n).write_bytes(b)
    pin = pin_of(parts)
    pin["parts"][1]["sha256"] = "0" * 64
    ps = dx.PartStream(pin, tmp_path)
    with pytest.raises(dx.DumpError, match="part01.*not the pinned"):
        try:
            while ps.out.read(1 << 16):
                pass
        finally:
            ps.close()


class RangeHandler(http.server.BaseHTTPRequestHandler):
    blobs: dict = {}
    cut_once: set = set()

    def log_message(self, *a):
        pass

    def do_GET(self):
        blob = self.blobs.get(self.path.rsplit("/", 1)[-1])
        if blob is None:
            self.send_error(404)
            return
        start = 0
        rng = self.headers.get("Range")
        if rng:
            start = int(rng.split("=")[1].rstrip("-"))
        self.send_response(206 if rng else 200)
        self.send_header("Content-Length", str(len(blob) - start))
        self.end_headers()
        body = blob[start:]
        name = self.path.rsplit("/", 1)[-1]
        if name in self.cut_once and not rng:
            self.cut_once.discard(name)
            self.wfile.write(body[: len(body) // 2])
            self.wfile.flush()
            self.connection.close()
            return
        self.wfile.write(body)


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_download_resumes_a_broken_transfer_where_it_stopped(server, monkeypatch):
    monkeypatch.setattr(dx.time, "sleep", lambda s: None)
    blob = bytes(range(256)) * 4000
    RangeHandler.blobs, RangeHandler.cut_once = {"p": blob}, {"p"}
    assert b"".join(dx._read_url(f"{server}/p")) == blob


def test_download_of_a_missing_part_stops(server):
    RangeHandler.blobs, RangeHandler.cut_once = {}, set()
    with pytest.raises(dx.DumpError, match="404"):
        list(dx._read_url(f"{server}/gone"))


@pytest.mark.skipif(not HAVE_ZSTD, reason="zstd not installed")
def test_part_stream_over_http(server, monkeypatch):
    monkeypatch.setattr(dx.time, "sleep", lambda s: None)
    parts = parts_of(archive(TABLES, 5))
    RangeHandler.blobs, RangeHandler.cut_once = dict(parts), {parts[1][0]}
    ps = dx.PartStream(pin_of(parts, server), None)
    got = read_all(dx.Archive(ps.out))
    ps.close()
    assert got["other"] == [b"9"]


def test_a_night_names_its_own_engine_ref_on_the_extracts_unresolved_builds():
    # Run 45072844801: the dump lane's 1011 points recorded v0.32.0, the extract's ref, in a night whose engine is a
    # commit, and the snapshot's validation refused every one. The extract never resolved a build, so it takes the
    # night's ref; a build it did resolve, and an API-lane point, keep theirs.
    def pt(source, why, match, ref="v0.32.0"):
        return {"source": source, "build": {"ref": ref, "match": match, "why": why, "distance": None}}
    manifest = {"vllm_ref": "v0.32.0", "source": "db-dump/2026-09-28 via dump_extract.py (offline adapter)",
                "points": [pt(dx.SOURCE_LABEL, "commit_unresolvable", "estimated"),
                           pt(dx.SOURCE_LABEL, None, "exact"),
                           pt("api", "commit_unresolvable", "estimated")]}
    ref = "0fda86a35419c9c70dbfada224c838c10fbb62ad"
    assert dx.anchor_to_ref(manifest, ref) == 1
    assert [p["build"]["ref"] for p in manifest["points"]] == [ref, "v0.32.0", "v0.32.0"]
    assert manifest["vllm_ref"] == ref
    assert dx.anchor_to_ref(manifest, ref) == 0
    api_manifest = {"vllm_ref": "v0.32.0", "source": "SemiAnalysis InferenceX API", "points": []}
    dx.anchor_to_ref(api_manifest, ref)
    assert api_manifest["vllm_ref"] == "v0.32.0"
