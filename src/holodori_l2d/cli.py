"""搜索卡牌，光标多选并下载 Live2D 模型；也支持 ID 和批量文件。"""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import re
import subprocess
import sys
import tempfile
import types
import zipfile
from pathlib import Path

import httpx

from .rebuild import rebuild
from .naming import EXPORT_INFO, export_owner, validate_name
from .icon import card_thumbnail_name, save_icon, select_thumbnail
from .vtube import ensure_config


CARD_ID = re.compile(r"^(\d{5})-(?:\d+-)?([a-z0-9]+)-(\d{4})-(\d{2})$")


def model_id_from_input(value: str) -> tuple[str, str]:
    """Accept a card ID, model ID, or full live2d_mdl_* asset name."""
    value = value.removeprefix("live2d_mdl_").removeprefix("card-")
    match = CARD_ID.fullmatch(value)
    if match is None:
        raise ValueError(
            "ID 格式应为 04016-5-uniq-0079-00 或 04016-uniq-0079-00"
        )
    character, variant, costume, suffix = match.groups()
    return f"{character}-{variant}-{costume}-{suffix}", character


def _batch_entry(card_id: str, folder_name: str) -> None:
    try:
        model_id_from_input(card_id)
    except ValueError:
        raise ValueError(f"卡牌或模型 ID 格式不正确：{card_id}") from None
    validate_name(folder_name)


def _run_upstream(*args: str, quiet: bool = False) -> None:
    command = [sys.executable, "-m", "holodori_asset_tools", *args]
    result = subprocess.run(
        command,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE if quiet else None,
        stderr=subprocess.PIPE if quiet else None,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"holodori-asset-tools 运行失败：{detail}")


def _extract_bundle(source: Path, destination: Path) -> None:
    from holodori_asset_tools.entrypoint.extract import AssetBundle

    if platform.system() == "Android":
        # UnityPy imports the FMOD audio toolkit while loading its texture converter.
        # FMOD has no Android build, but these Live2D bundles contain no audio.
        sys.modules.setdefault("fmod_toolkit", types.ModuleType("fmod_toolkit"))
    try:
        AssetBundle(source, source.name).extract(destination)
    except Exception as error:
        raise RuntimeError(f"资源包提取失败：{source.name}：{error}") from error


def _catalog_entries(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {entry["name"] for entry in data["assetBundles"]}


def _selected_assets(
    names: set[str], model_id: str, character: str, motion_level: str | None
) -> tuple[list[str], list[str]]:
    model_name = f"live2d_mdl_{model_id}"
    if model_name not in names:
        raise ValueError(f"游戏资源索引中找不到模型：{model_name}")
    expressions = sorted(
        name for name in names
        if re.fullmatch(rf"live2d_exp_.+_{character}_000", name)
    )
    motions = (
        sorted(
            name for name in names
            if re.fullmatch(rf"live2d_mot_.+_{motion_level}(?:_lp)?", name)
        )
        if motion_level else []
    )
    if motion_level and not motions:
        raise ValueError(f"游戏资源索引中找不到 {motion_level} 动作")
    return expressions, motions


def _nonempty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _make_zip(folder: Path, *, force: bool) -> Path:
    destination = folder.with_name(folder.name + ".zip")
    if destination.exists() and not force:
        print(f"压缩包已存在，未覆盖：{destination}（需要更新时加 --force）")
        return destination
    with tempfile.NamedTemporaryFile(
        prefix="live2d-", suffix=".zip", dir=folder.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with zipfile.ZipFile(temporary_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, folder.name + "/" + path.relative_to(folder).as_posix())
        temporary_path.replace(destination)
    finally:
        temporary_path.unlink(missing_ok=True)
    return destination


def prepare(
    asset_id: str,
    *,
    output_name: str | None = None,
    model_name: str | None = None,
    card_info: dict | None = None,
    output_root: Path | None = None,
    cache_root: Path | None = None,
    catalog_path: Path | None = None,
    motion_level: str | None = "lv05",
    force: bool = False,
    make_zip: bool = True,
) -> dict:
    if importlib.util.find_spec("holodori_asset_tools") is None:
        raise RuntimeError('请先运行：python -m pip install ".[assets]"')
    if motion_level is not None and not re.fullmatch(r"lv\d{2}", motion_level):
        raise ValueError("动作等级应为 lv05 这样的格式")

    if output_name is not None:
        _batch_entry(asset_id, output_name)
    if model_name is not None:
        validate_name(model_name)
    export_model_name = model_name
    model_id, character = model_id_from_input(asset_id)
    model_name = f"live2d_mdl_{model_id}"
    thumbnail_input = card_info.get("card_id") if card_info is not None else asset_id
    expected_thumbnail = card_thumbnail_name(thumbnail_input)
    cache_root = (cache_root or Path.cwd() / "input" / ".holodori_assets").resolve()
    raw_bundles = cache_root / "raw" / "assetbundles"
    catalog = (catalog_path or cache_root / "octo_list.json").resolve()
    output_root = (output_root or Path.cwd() / "output").resolve()
    output_dir = output_root / (output_name or f"live2d_{model_id}")
    if card_info is not None and output_dir.exists():
        if export_owner(output_dir) != (card_info.get("export_id") or card_info["card_id"]):
            raise ValueError(f"输出目录不属于此卡牌，请换一个目录：{output_dir}")
    cache_root.mkdir(parents=True, exist_ok=True)
    catalog.parent.mkdir(parents=True, exist_ok=True)

    # The upstream catalog loader fetches only when its cache is absent.
    # Refresh once if the model or its exact card thumbnail is newer than the cache.
    from holodori_asset_tools import catalog as upstream_catalog

    upstream_catalog.get(catalog)
    names = _catalog_entries(catalog)
    if catalog_path is None and (model_name not in names or
                                (expected_thumbnail is not None and expected_thumbnail not in names)):
        print("缓存索引没有这个模型或卡牌缩略图，正在获取最新索引……")
        upstream_catalog.fetch().save(catalog)
        names = _catalog_entries(catalog)
    expressions, motions = _selected_assets(names, model_id, character, motion_level)
    thumbnail = select_thumbnail(names, thumbnail_input)
    if thumbnail is None:
        print("未找到唯一对应的卡牌缩略图，跳过 icon.jpg。", flush=True)
    selected = [model_name, *expressions, *motions]
    if thumbnail is not None:
        selected.append(thumbnail)
    pattern = "^(?:" + "|".join(map(re.escape, selected)) + ")$"

    print(
        f"下载/检查：1 个模型、{len(expressions)} 个表情、{len(motions)} 个候选动作、{int(thumbnail is not None)} 张卡牌缩略图",
        flush=True,
    )
    _run_upstream(
        "download", str(cache_root / "raw"), "--filter", pattern,
        "--catalog", str(catalog), "--no-overwrite",
    )
    missing = [name for name in selected if not _nonempty(raw_bundles / name)]
    if missing:
        raise RuntimeError("下载后仍缺少资源：" + ", ".join(missing))

    with tempfile.TemporaryDirectory(prefix="live2d-extract-", dir=cache_root) as temp:
        extracted = Path(temp)
        for name in [model_name, *expressions]:
            _extract_bundle(raw_bundles / name, extracted)
        model_dir = extracted / model_name
        if not model_dir.is_dir() or not any(model_dir.glob("*.png")):
            raise RuntimeError(f"模型包提取失败：{model_name}")
        missing_expressions = [
            name for name in expressions
            if not _nonempty(extracted / name / f"{name}.json")
        ]
        if missing_expressions:
            raise RuntimeError("表情包提取失败：" + ", ".join(missing_expressions))
        if thumbnail is not None:
            _extract_bundle(raw_bundles / thumbnail, extracted)
        summary = rebuild(
            model_dir, output_dir,
            motion_bundles=[raw_bundles / name for name in motions],
            force=force,
            model_name=export_model_name,
        )
        if thumbnail is not None:
            summary["icon"] = str(save_icon(extracted / thumbnail, output_dir, force=force))
            summary["icon_asset"] = thumbnail

    summary["vtube"] = str(ensure_config(Path(summary["model"])))
    if card_info is not None:
        from .master import write_atomic
        write_atomic(output_dir / EXPORT_INFO, (json.dumps(card_info, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    summary["asset_id"] = model_id
    if output_name is not None:
        summary["card_id"] = card_info["card_id"] if card_info else asset_id
        summary["output_name"] = output_name
    summary["output_dir"] = str(output_dir)
    if make_zip:
        summary["zip"] = str(_make_zip(output_dir, force=force))
    return summary


def prepare_batch(batch_file: Path, **options: object) -> dict:
    """Process card/custom-folder pairs; report all line-level failures."""
    lines = batch_file.read_text(encoding="utf-8-sig").splitlines()
    results = []
    used_names = set()
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=1)
        item: dict = {"line": line_number}
        item["card_id"] = fields[0]
        if len(fields) > 1:
            item["output_name"] = fields[1]
        try:
            if len(fields) != 2:
                raise ValueError("每行应为：卡牌/模型ID 自定义保存文件夹名")
            _batch_entry(fields[0], fields[1])
            folded_name = fields[1].casefold()
            if folded_name in used_names:
                raise ValueError(f"保存文件夹名重复：{fields[1]}")
            used_names.add(folded_name)
            item["result"] = prepare(fields[0], output_name=fields[1], **options)
            item["status"] = "ok"
        except Exception as error:
            item["status"] = "error"
            item["error"] = str(error)
        results.append(item)
        print(f"第 {line_number} 行：{item['status']}", flush=True)
    if not results:
        raise ValueError("批量文件没有可处理的记录")
    failed = sum(item["status"] == "error" for item in results)
    return {
        "total": len(results),
        "succeeded": len(results) - failed,
        "failed": failed,
        "results": results,
    }


def main() -> None:
    # PowerShell pipes expect UTF-8 even when Python inherited a legacy code page.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("asset_id", nargs="?", help="卡牌名或角色名搜索词；也可直接输入卡牌/模型 ID")
    parser.add_argument("--lang", choices=("chs", "cht"), default="chs", help="搜索语言：简中/繁中")
    parser.add_argument("--character", help="按角色名或编号筛选搜索结果")
    parser.add_argument("--pack-character", metavar="角色名或编号", help="下载角色全部模型，生成角色名.zip")
    parser.add_argument("--refresh", action="store_true", help="刷新官方卡牌目录")
    parser.add_argument("--app-version", default="1.2.1", help="官方主数据接口使用的客户端版本")
    parser.add_argument(
        "--batch", type=Path,
        help="批量清单：每行一个卡牌/模型 ID 和自定义保存文件夹名（允许空格）",
    )
    parser.add_argument("-o", "--output-root", type=Path, help="输出根目录（默认当前目录/output）")
    parser.add_argument("--cache-root", type=Path, help="下载缓存（默认当前目录/input/.holodori_assets）")
    parser.add_argument("--catalog", type=Path, help="指定游戏资源索引文件")
    parser.add_argument("--motion-level", default="lv05", help="候选动作等级，默认 lv05")
    parser.add_argument("--no-motions", action="store_true", help="仅生成模型与表情")
    parser.add_argument("--no-zip", action="store_true", help="不生成压缩包")
    parser.add_argument("--force", action="store_true", help="覆盖已有的生成文件")
    args = parser.parse_args()
    if args.batch is not None and args.asset_id is not None:
        parser.error("--batch 与单项 ID 不能同时使用")
    if args.pack_character is not None and (args.batch is not None or args.asset_id is not None or args.no_zip):
        parser.error("--pack-character 不能与搜索词、--batch 或 --no-zip 同时使用")
    direct_id = False
    if args.asset_id is not None:
        try:
            model_id_from_input(args.asset_id)
            direct_id = True
        except ValueError:
            pass
    try:
        options = dict(
            output_root=args.output_root,
            cache_root=args.cache_root,
            catalog_path=args.catalog,
            motion_level=None if args.no_motions else args.motion_level,
            force=args.force,
            make_zip=not args.no_zip,
        )
        if args.pack_character is not None:
            from . import search
            from .character_pack import download_character, resolve_character
            cache = (args.cache_root or Path.cwd() / "input/.holodori_assets") / "master"
            index = search.load_index(cache, language=args.lang, refresh=args.refresh, app_version=args.app_version)
            result = download_character(resolve_character(index, args.pack_character), index, **options)
        elif args.batch is not None:
            result = prepare_batch(args.batch, **options)
        elif direct_id:
            result = prepare(args.asset_id, **options)
        else:
            from .interactive import run
            result = run(args.asset_id, language=args.lang, character=args.character,
                         refresh=args.refresh, app_version=args.app_version, **options)
            if result and result["failed"]:
                parser.exit(1)
            return
    except (KeyboardInterrupt, EOFError):
        print("\n已取消。")
        return
    except ImportError:
        parser.exit(1, '请先安装依赖：python -m pip install -e ".[assets]"\n')
    except (ValueError, RuntimeError, OSError, httpx.HTTPError) as error:
        parser.exit(1, f"错误：{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if (args.batch is not None or args.pack_character is not None) and result["failed"]:
        parser.exit(1)


if __name__ == "__main__":
    main()
