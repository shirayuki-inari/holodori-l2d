"""Keyboard-first card search, multi-selection and download."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from . import search
from .naming import export_key, export_names


@dataclass(frozen=True)
class CharacterPackRequest:
    character_id: str


def select_cards(rows: list[dict], *, input=None, output=None) -> list[dict] | CharacterPackRequest | None:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.styles import Style

    cursor, selected = 0, set()
    available = {i for i, row in enumerate(rows) if row.get("model_exists") and row.get("resource_name")}
    if not available:
        return []
    bindings = KeyBindings()

    @bindings.add("up")
    def up(event):
        nonlocal cursor
        cursor = max(0, cursor - 1)

    @bindings.add("down")
    def down(event):
        nonlocal cursor
        cursor = min(len(rows) - 1, cursor + 1)

    @bindings.add("pageup")
    def pageup(event):
        nonlocal cursor
        cursor = max(0, cursor - 10)

    @bindings.add("pagedown")
    def pagedown(event):
        nonlocal cursor
        cursor = min(len(rows) - 1, cursor + 10)

    @bindings.add(" ")
    def toggle(event):
        if cursor in available:
            selected.symmetric_difference_update({cursor})

    @bindings.add("a")
    def all_items(event):
        if selected == available:
            selected.clear()
        else:
            selected.update(available)

    @bindings.add("enter")
    def accept(event):
        chosen = selected or ({cursor} if cursor in available else set())
        if chosen:
            event.app.exit(result=[rows[i] for i in sorted(chosen)])

    @bindings.add("escape")
    def back(event):
        event.app.exit(result=None)

    @bindings.add("p")
    def pack_character(event):
        event.app.exit(result=CharacterPackRequest(rows[cursor]["character_id"]))

    @bindings.add("c-c")
    @bindings.add("c-d")
    def cancel(event):
        event.app.exit(exception=KeyboardInterrupt())

    def render():
        fragments = []
        for i, row in enumerate(rows):
            if i == cursor:
                fragments.append(("[SetCursorPosition]", ""))
            style = "class:cursor" if i == cursor else ""
            if i not in available:
                style += " class:disabled"
            mark = "[x]" if i in selected else "[ ]" if i in available else "[-]"
            identity = row.get("card_id") or f"服装模型 {row['resource_name']}"
            text = f"{'>' if i == cursor else ' '} {mark} {row['name']}  · {row.get('character') or row['character_id']}  · {identity}"
            text = " ".join(text.split())
            fragments.append((style, text + ("  （暂无模型）" if i not in available else "")))
            fragments.append(("", "\n" if i < len(rows) - 1 else ""))
        return fragments

    control = FormattedTextControl(render, focusable=True, show_cursor=False)
    layout = Layout(HSplit([
        Window(FormattedTextControl(lambda: f"找到 {len(rows)} 项 · 已选 {len(selected)} 项"), height=1),
        Window(control, height=Dimension(min=1, max=12), wrap_lines=False),
        Window(FormattedTextControl("↑↓ 移动  空格 多选  A 全选/清空  Enter 下载（未勾选时下载当前项）  P 当前角色全模型打包  Esc 重新搜索  Ctrl+C 退出"), height=3, wrap_lines=True),
    ]), focused_element=control)
    return Application(
        layout=layout, key_bindings=bindings, full_screen=False,
        style=Style.from_dict({"cursor": "reverse", "disabled": "#888888"}),
        input=input, output=output,
    ).run()


def download_cards(rows: list[dict], index: dict, **options) -> dict:
    from .cli import prepare

    root = options.get("output_root") or Path.cwd() / "output"
    names = export_names(rows, search.browse_rows(index), root)
    results = []
    for number, (row, (folder, title)) in enumerate(zip(rows, names), 1):
        print(f"\n[{number}/{len(rows)}] {row['name']} · {row.get('character') or row['character_id']}", flush=True)
        item = {"card_id": row["card_id"], "name": row["name"]}
        try:
            if not row.get("model_exists") or not row.get("resource_name"):
                raise ValueError("资源索引中没有此卡牌的模型")
            item["result"] = prepare(
                row["resource_name"], output_name=folder, model_name=title,
                card_info={"card_id": row["card_id"], "export_id": export_key(row), "card_name": row["name"],
                           "resource_name": row["resource_name"]}, **options,
            )
            item["status"] = "ok"
            print(f"已保存：{item['result']['output_dir']}", flush=True)
        except Exception as error:
            item.update(status="error", error=str(error))
            print(f"下载失败：{error}", flush=True)
        results.append(item)
    failed = sum(row["status"] == "error" for row in results)
    print(f"\n完成：成功 {len(results) - failed}，失败 {failed}。", flush=True)
    return {"total": len(results), "succeeded": len(results) - failed, "failed": failed, "results": results}


def run(query: str | None, *, language: str, character: str | None,
        refresh: bool, app_version: str, **options) -> dict | None:
    from prompt_toolkit import prompt

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("光标选择需要交互终端；请在终端启动，或使用 ID / --batch 下载")
    cache = (options.get("cache_root") or Path.cwd() / "input/.holodori_assets") / "master"
    print("正在加载卡牌目录……", flush=True)
    try:
        index = search.load_index(cache, language=language, refresh=refresh, app_version=app_version)
    except ImportError:
        raise
    except Exception as error:
        raise RuntimeError(f"加载卡牌目录失败：{error}") from error
    while True:
        if query is None:
            query = prompt("搜索卡牌名或角色名（留空浏览全部，Ctrl+C 退出）：").strip()
        rows = (search.search_cards(index, query, character) if query else
                [r for r in search.browse_rows(index) if not character or any(
                    search._normalized(character) in search._normalized(r.get(k) or "")
                    for k in ("character", "character_id"))])
        if not rows:
            print("没有匹配的卡牌，请换个关键词。")
        elif not any(r.get("model_exists") and r.get("resource_name") for r in rows):
            print("匹配的卡牌暂时没有可下载模型，请换个关键词。")
        else:
            chosen = select_cards(rows)
            if isinstance(chosen, CharacterPackRequest):
                from .character_pack import download_character
                return download_character(chosen.character_id, index, **options)
            if chosen:
                return download_cards(chosen, index, **options)
        query = None
