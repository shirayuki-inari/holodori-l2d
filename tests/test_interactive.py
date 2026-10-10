import json
import sys

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from holodori_l2d import cli, interactive, naming


def card(number, name="同名卡牌", *, available=True):
    return {"card_id": f"card-{number:05d}-5-uniq-0001-00", "name": name,
            "character": f"角色{number}", "character_id": f"chr-{number:05d}",
            "resource_name": f"live2d_mdl_{number:05d}-uniq-0001-00",
            "model_exists": available}


@pytest.mark.parametrize("keys,indices", [
    ("\r", [0]),
    (" \x1b[B \r", [0, 1]),
    ("  \x1b[B\r", [1]),
    ("a\r", [0, 1]),
    ("\x1b[B\x1b[B \x1b[A\r", [1]),  # Missing models cannot be selected.
    ("\x1b", None),
])
def test_real_keyboard_selection(keys, indices):
    rows = [card(1), card(2), card(3, available=False)]
    with create_pipe_input() as pipe:
        pipe.send_text(keys)
        result = interactive.select_cards(rows, input=pipe, output=DummyOutput())
    assert result == (None if indices is None else [rows[i] for i in indices])


def test_keyboard_cancel_does_not_download():
    with create_pipe_input() as pipe:
        pipe.send_text("\x03")
        with pytest.raises(KeyboardInterrupt):
            interactive.select_cards([card(1)], input=pipe, output=DummyOutput())


def test_paging_and_all_toggle():
    rows = [card(i) for i in range(25)]
    with create_pipe_input() as pipe:
        pipe.send_text("aa\x1b[6~\x1b[6~\x1b[5~\r")
        result = interactive.select_cards(rows, input=pipe, output=DummyOutput())
    assert result == [rows[10]]


def test_names_stable_across_separate_downloads(tmp_path):
    rows = [card(1), card(2)]
    names = naming.export_names(rows, rows, tmp_path)
    assert names == [("同名卡牌（角色1）", "同名卡牌"), ("同名卡牌（角色2）", "同名卡牌")]
    assert naming.export_names([rows[1]], rows, tmp_path) == [names[1]]
    folder = tmp_path / names[1][0]
    folder.mkdir()
    # An unrelated existing directory, even with the intended name, is not reused.
    other = naming.export_names([rows[1]], rows, tmp_path)[0][0]
    assert other != folder.name
    (folder / naming.EXPORT_INFO).write_text(json.dumps({"card_id": rows[1]["card_id"]}))
    assert naming.export_names([rows[1]], rows, tmp_path) == [names[1]]


def test_illegal_names_collisions_and_zip_only(tmp_path):
    rows = [card(1, 'a/b:*?'), card(2, 'a／b：＊？')]
    names = naming.export_names(rows, rows, tmp_path)
    assert names[0][0] != names[1][0]
    assert names[0][1] == 'a／b：＊？'
    assert naming.card_filename('CON') == '_CON'
    for name in ('.', '..', '\x00', '长' * 200):
        sanitized = naming.card_filename(name)
        naming.validate_name(sanitized)
        assert len(sanitized.encode()) <= 120
    one = card(1, "独立卡牌")
    (tmp_path / "独立卡牌.zip").write_bytes(b"existing archive")
    assert naming.export_names([one], [one], tmp_path)[0][0] != "独立卡牌"


def test_selected_downloads_continue_after_failure(tmp_path, monkeypatch):
    rows = [card(1, "第一张卡"), card(2, "第二张卡")]
    calls = []

    def prepare(asset_id, **options):
        calls.append((asset_id, options))
        if len(calls) == 1:
            raise RuntimeError("synthetic failure")
        return {"output_dir": str(tmp_path / options["output_name"])}

    monkeypatch.setattr(cli, "prepare", prepare)
    result = interactive.download_cards(rows, {"cards": rows}, output_root=tmp_path, motion_level=None)
    assert result["succeeded"] == result["failed"] == 1
    assert calls[1][0] == rows[1]["resource_name"]
    assert calls[1][1]["model_name"] == "第二张卡"
    assert calls[1][1]["card_info"]["card_id"] == rows[1]["card_id"]
    assert calls[1][1]["motion_level"] is None


@pytest.mark.parametrize("query", [None, "卡牌名"])
def test_default_entry_routes_to_interactive_search(query, monkeypatch):
    argv = ["holodori-l2d"] + ([query] if query else [])
    monkeypatch.setattr(sys, "argv", argv)
    calls = []
    monkeypatch.setattr(interactive, "run", lambda value, **options: calls.append((value, options)))
    cli.main()
    assert calls[0][0] == query
    assert calls[0][1]["language"] == "chs"


def test_search_retry_and_escape(monkeypatch):
    import prompt_toolkit

    row = card(1, "第一张卡")
    queries = iter(["无匹配", "第一张", "第一张"])
    choices = iter([None, [row]])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(prompt_toolkit, "prompt", lambda text: next(queries))
    monkeypatch.setattr(interactive.search, "load_index", lambda *a, **kw: {"cards": [row]})
    monkeypatch.setattr(interactive, "select_cards", lambda rows: next(choices))
    monkeypatch.setattr(interactive, "download_cards", lambda rows, *a, **kw: {"selected": rows})
    result = interactive.run(None, language="chs", character=None, refresh=False, app_version="1.2.1")
    assert result == {"selected": [row]}
