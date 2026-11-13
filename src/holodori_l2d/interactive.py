"""Keyboard-first card search, multi-selection and download."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime

from . import search
from .naming import export_key, export_names, exported_keys
from .search import character_label, downloadable
from .util import cache_dir, output_dir, report_item, report_summary, status, summarize


HELP = ("↑↓ 移动  空格 多选  A 全选/清空  Enter 下载（未勾选时下载当前项）  Z 开关 ZIP 打包  "
        "P 当前角色全模型打包  Esc 重新搜索  Ctrl+C 退出")
MOVES = {"up": -1, "down": 1, "pageup": -10, "pagedown": 10}


@dataclass(frozen=True)
class CharacterPackRequest:
    character_id: str


def select_cards(rows: list[dict], *, exported: set[str] = frozenset(), settings: dict | None = None,
                 input=None, output=None) -> list[dict] | CharacterPackRequest | None:
    """Return the chosen rows, a character-pack request, or None to search again.

    ``settings["zip"]`` is toggled in place with Z and kept for later searches.
    """
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import Dimension
    from prompt_toolkit.styles import Style

    cursor, selected = 0, set()
    settings = {"zip": False} if settings is None else settings
    available = {i for i, row in enumerate(rows) if downloadable(row)}
    if not available:
        return []
    bindings = KeyBindings()

    def mover(step: int):
        def move(event):
            nonlocal cursor
            cursor = min(max(cursor + step, 0), len(rows) - 1)
        return move

    for key, step in MOVES.items():
        bindings.add(key)(mover(step))

    @bindings.add(" ")
    def toggle(event):
        if cursor in available:
            selected.symmetric_difference_update({cursor})

    @bindings.add("a")
    def toggle_all(event):
        if selected == available:
            selected.clear()
        else:
            selected.update(available)

    @bindings.add("enter")
    def accept(event):
        chosen = selected or ({cursor} & available)
        if chosen:
            event.app.exit(result=[rows[i] for i in sorted(chosen)])

    @bindings.add("escape")
    def back(event):
        event.app.exit(result=None)

    @bindings.add("z")
    def toggle_zip(event):
        settings["zip"] = not settings.get("zip")

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
            focused, enabled = i == cursor, i in available
            if focused:
                fragments.append(("[SetCursorPosition]", ""))
            style = ("class:cursor " if focused else "") + ("" if enabled else "class:disabled")
            mark = "[x]" if i in selected else "[ ]" if enabled else "[-]"
            identity = row.get("card_id") or f"服装模型 {row['resource_name']}"
            text = " ".join(f"{'>' if focused else ' '} {mark} {row['name']}  · {character_label(row)}  · {identity}".split())
            if not enabled:
                text += "  （暂无模型）"
            elif export_key(row) in exported:
                text += "  （已导出）"
            fragments.append((style, text))
            fragments.append(("", "\n" if i < len(rows) - 1 else ""))
        return fragments

    control = FormattedTextControl(render, focusable=True, show_cursor=False)
    layout = Layout(HSplit([
        Window(FormattedTextControl(lambda: f"找到 {len(rows)} 项 · 已选 {len(selected)} 项 · "
                                            f"ZIP 打包：{'开' if settings.get('zip') else '关'}"), height=1),
        Window(control, height=Dimension(min=1, max=12), wrap_lines=False),
        Window(FormattedTextControl(HELP), height=3, wrap_lines=True),
    ]), focused_element=control)
    return Application(
        layout=layout, key_bindings=bindings, full_screen=False,
        style=Style.from_dict({"cursor": "reverse", "disabled": "#888888"}),
        input=input, output=output,
    ).run()


def download_cards(rows: list[dict], index: dict, *, make_zip: bool = False, **options) -> dict:
    """Export each row into its own folder; ``make_zip`` packs all successful ones into one ZIP."""
    from .cli import bundle_exports, prefetch, prepare

    root = output_dir(options.get("output_root"))
    prefetch([(row["resource_name"], row["card_id"]) for row in rows if downloadable(row)], **options)
    names = export_names(rows, search.browse_rows(index), root)
    results = []
    for number, (row, (folder, title)) in enumerate(zip(rows, names), 1):
        label = f"[{number}/{len(rows)}] {row['name']} · {character_label(row)}"
        item = {"card_id": row["card_id"], "name": row["name"]}
        with status.scope(label):
            try:
                if not downloadable(row):
                    raise ValueError("资源索引中没有此卡牌的模型")
                card_info = {"card_id": row["card_id"], "export_id": export_key(row),
                             "card_name": row["name"], "resource_name": row["resource_name"]}
                item["result"] = prepare(row["resource_name"], output_name=folder, model_name=title,
                                         card_info=card_info, make_zip=False, **options)
                item["status"] = "ok"
            except Exception as error:
                item.update(status="error", error=str(error))
        results.append(item)
        report_item(label, item)
    summary = summarize(results)
    report_summary(summary)
    if make_zip:
        archive = bundle_exports(results, root, datetime.now().strftime("live2d_%Y%m%d-%H%M%S"),
                                 force=bool(options.get("force")))
        if archive is not None:
            summary["zip"] = str(archive)
    return summary


def _pack_character(character_id: str, index: dict, prompt, **options) -> dict | None:
    from .character_pack import character_models, download_character

    models = character_models(index, character_id)
    if not models:
        print("资源目录中没有此角色的模型。")
        return None
    answer = prompt(f"将下载「{character_label(models[0])}」的全部 {len(models)} 个模型并生成角色 ZIP，"
                    "确认？(Y/n)：")
    if answer.strip().lower() not in ("", "y", "yes"):
        return None
    return download_character(character_id, index, **options)


def run(query: str | None, *, language: str, character: str | None,
        refresh: bool, app_version: str, **options) -> dict | None:
    """Search and download repeatedly until Ctrl+C; summarize every download."""
    from prompt_toolkit import prompt

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("光标选择需要交互终端；请在终端启动，或使用 ID / --batch 下载")
    status.update("正在加载卡牌目录……")
    try:
        index = search.load_index(cache_dir(options.get("cache_root")) / "master",
                                  language=language, refresh=refresh, app_version=app_version)
    except ImportError:
        raise
    except Exception as error:
        raise RuntimeError(f"加载卡牌目录失败：{error}") from error
    finally:
        status.clear()
    root = output_dir(options.get("output_root"))
    settings = {"zip": bool(options.pop("make_zip", False))}
    results = []
    while True:
        try:
            text = prompt("搜索卡牌名或角色名（留空浏览全部，Ctrl+C 退出）：") if query is None else query
            query = None
            rows = (search.search_cards(index, text, character) if search.normalize(text)
                    else search.browse_rows(index, character))
            if not rows:
                print("没有匹配的卡牌，请换个关键词。")
                continue
            if not any(map(downloadable, rows)):
                print("匹配的卡牌暂时没有可下载模型，请换个关键词。")
                continue
            chosen = select_cards(rows, exported=exported_keys(root), settings=settings)
            if not chosen:
                continue
            try:
                if isinstance(chosen, CharacterPackRequest):
                    result = _pack_character(chosen.character_id, index, prompt, **options)
                else:
                    result = download_cards(chosen, index, make_zip=settings["zip"], **options)
            except (ValueError, RuntimeError, OSError) as error:
                status.print(f"下载失败：{error}")
                result = {"results": [{"status": "error", "error": str(error)}]}
        except (KeyboardInterrupt, EOFError):
            status.print("\n已退出。")
            break
        if result:
            results += result["results"]
            print("可继续搜索下载；Ctrl+C 退出。")
    return summarize(results) if results else None
