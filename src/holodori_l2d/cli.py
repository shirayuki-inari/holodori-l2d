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
from pathlib import Path

import httpx

from . import __version__
from .icon import card_thumbnail_name, save_icon, select_thumbnail
from .master import APP_VERSION
from .naming import EXPORT_INFO, export_owner, model_id_from_input, read_export_info, validate_name
from .rebuild import rebuild
from .util import cache_dir, json_bytes, output_dir, summarize, use_utf8_stdio, write_atomic, write_zip
from .vtube import ensure_config


def _is_id(value: str) -> bool:
    try:
        model_id_from_input(value)
        return True
    except ValueError:
        return False


def _batch_entry(card_id: str, folder_name: str) -> None:
    if not _is_id(card_id):
        raise ValueError(f"卡牌或模型 ID 格式不正确：{card_id}")
    validate_name(folder_name)


def _run_upstream(*args: str) -> None:
    result = subprocess.run([sys.executable, "-m", "holodori_asset_tools", *args], check=False)
    if result.returncode:
        raise RuntimeError(f"holodori-asset-tools 运行失败（退出码 {result.returncode}）")


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
    return {entry["name"] for entry in json.loads(path.read_text(encoding="utf-8"))["assetBundles"]}


def _load_catalog(catalog: Path, wanted: list[str], *, refreshable: bool) -> set[str]:
    # The upstream catalog loader fetches only when its cache is absent.
    # Refresh once if the model or its exact card thumbnail is newer than the cache.
    from holodori_asset_tools import catalog as upstream_catalog

    catalog.parent.mkdir(parents=True, exist_ok=True)
    upstream_catalog.get(catalog)
    names = _catalog_entries(catalog)
    if refreshable and not set(wanted) <= names:
        print("缓存索引没有这个模型或卡牌缩略图，正在获取最新索引……")
        upstream_catalog.fetch().save(catalog)
        names = _catalog_entries(catalog)
    return names


def _selected_assets(
    names: set[str], model_id: str, character: str, motion_level: str | None
) -> tuple[list[str], list[str]]:
    if f"live2d_mdl_{model_id}" not in names:
        raise ValueError(f"游戏资源索引中找不到模型：live2d_mdl_{model_id}")
    expressions = sorted(n for n in names if re.fullmatch(rf"live2d_exp_.+_{character}_000", n))
    if not motion_level:
        return expressions, []
    motions = sorted(n for n in names if re.fullmatch(rf"live2d_mot_.+_{motion_level}(?:_lp)?", n))
    if not motions:
        raise ValueError(f"游戏资源索引中找不到 {motion_level} 动作")
    return expressions, motions


def _nonempty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _make_zip(folder: Path, *, force: bool) -> Path:
    destination = folder.with_name(folder.name + ".zip")
    if destination.exists() and not force:
        print(f"压缩包已存在，未覆盖：{destination}（需要更新时加 --force）")
        return destination
    return write_zip(destination, [folder])


def _cache_paths(cache_root: Path | None, catalog_path: Path | None) -> tuple[Path, Path]:
    cache_root = cache_dir(cache_root).resolve()
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root, (catalog_path or cache_root / "octo_list.json").resolve()


def _download(cache_root: Path, catalog: Path, names: list[str]) -> None:
    """Fetch the bundles missing from the cache; cached ones need no upstream call."""
    raw_bundles = cache_root / "raw" / "assetbundles"
    missing = [name for name in names if not _nonempty(raw_bundles / name)]
    if missing:
        _run_upstream(
            "download", str(cache_root / "raw"), "--catalog", str(catalog), "--no-overwrite",
            "--filter", "^(?:" + "|".join(map(re.escape, missing)) + ")$",
        )
        missing = [name for name in missing if not _nonempty(raw_bundles / name)]
    if missing:
        raise RuntimeError("下载后仍缺少资源：" + ", ".join(missing))


def _remove_stale(folder: Path, files: list[str]) -> list[str]:
    """Delete files that the previous export generated but this one did not."""
    root = folder.resolve()
    stale = sorted(set(read_export_info(folder).get("files", [])) - set(files))
    for relative in stale:
        path = (folder / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            continue
        path.unlink()
        for parent in path.parents:
            if parent == root or any(parent.iterdir()):
                break
            parent.rmdir()
    return stale


def prefetch(models: list[tuple[str, str | None]], *, cache_root: Path | None = None,
             catalog_path: Path | None = None, motion_level: str | None = None, **_: object) -> None:
    """Download several models' assets in one upstream call.

    ``models`` holds (asset ID, card ID) pairs. Failures are only reported here:
    each model's ``prepare`` retries what is still missing and records the error.
    """
    if len(models) < 2 or importlib.util.find_spec("holodori_asset_tools") is None:
        return
    try:
        cache_root, catalog = _cache_paths(cache_root, catalog_path)
        parsed = [(*model_id_from_input(asset_id), card_id) for asset_id, card_id in models]
        wanted = [f"live2d_mdl_{model_id}" for model_id, _, _ in parsed]
        names = _load_catalog(catalog, wanted, refreshable=catalog_path is None)
        selected = []
        for model_id, character, card_id in parsed:
            try:
                expressions, motions = _selected_assets(names, model_id, character, motion_level)
            except ValueError:
                continue
            thumbnail = select_thumbnail(names, card_id)
            selected += [f"live2d_mdl_{model_id}", *expressions, *motions, *([thumbnail] if thumbnail else [])]
        print(f"批量下载/检查 {len(models)} 个模型的资源……", flush=True)
        _download(cache_root, catalog, list(dict.fromkeys(selected)))
    except Exception as error:  # Best effort only: prepare() retries and reports per model.
        print(f"批量下载未全部完成，将逐个重试：{error}", flush=True)


def prepare(
    asset_id: str,
    *,
    output_name: str | None = None,
    model_name: str | None = None,
    card_info: dict | None = None,
    output_root: Path | None = None,
    cache_root: Path | None = None,
    catalog_path: Path | None = None,
    motion_level: str | None = None,
    force: bool = False,
    make_zip: bool = True,
) -> dict:
    """Download, extract and rebuild one model; ``model_name`` renames its files.

    Motions are experimental and exported only when ``motion_level`` (e.g. "lv05") is given.
    """
    if importlib.util.find_spec("holodori_asset_tools") is None:
        raise RuntimeError('请先运行：python -m pip install ".[assets]"')
    if motion_level is not None and not re.fullmatch(r"lv\d{2}", motion_level):
        raise ValueError("动作等级应为 lv05 这样的格式")
    if output_name is not None:
        _batch_entry(asset_id, output_name)
    if model_name is not None:
        validate_name(model_name)

    model_id, character = model_id_from_input(asset_id)
    bundle = f"live2d_mdl_{model_id}"
    card_id = card_info.get("card_id") if card_info is not None else asset_id
    destination = output_dir(output_root).resolve() / (output_name or f"live2d_{model_id}")
    if (card_info is not None and destination.exists()
            and export_owner(destination) != (card_info.get("export_id") or card_info["card_id"])):
        raise ValueError(f"输出目录不属于此卡牌，请换一个目录：{destination}")
    cache_root, catalog = _cache_paths(cache_root, catalog_path)
    raw_bundles = cache_root / "raw" / "assetbundles"

    names = _load_catalog(catalog, [bundle, *filter(None, [card_thumbnail_name(card_id)])],
                          refreshable=catalog_path is None)
    expressions, motions = _selected_assets(names, model_id, character, motion_level)
    thumbnail = select_thumbnail(names, card_id)
    if thumbnail is None:
        print("未找到唯一对应的卡牌缩略图，跳过 icon.jpg。", flush=True)
    thumbnails = [thumbnail] if thumbnail else []
    print(f"下载/检查：1 个模型、{len(expressions)} 个表情、{len(motions)} 个候选动作、"
          f"{len(thumbnails)} 张卡牌缩略图", flush=True)
    _download(cache_root, catalog, [bundle, *expressions, *motions, *thumbnails])

    with tempfile.TemporaryDirectory(prefix="live2d-extract-", dir=cache_root) as temp:
        extracted = Path(temp)
        for name in [bundle, *expressions, *thumbnails]:
            _extract_bundle(raw_bundles / name, extracted)
        model_dir = extracted / bundle
        if not model_dir.is_dir() or not any(model_dir.glob("*.png")):
            raise RuntimeError(f"模型包提取失败：{bundle}")
        missing = [name for name in expressions if not _nonempty(extracted / name / f"{name}.json")]
        if missing:
            raise RuntimeError("表情包提取失败：" + ", ".join(missing))
        summary = rebuild(model_dir, destination, motion_bundles=[raw_bundles / name for name in motions],
                          force=force, model_name=model_name)
        if thumbnail:
            summary["icon"] = str(save_icon(extracted / thumbnail, destination, force=force))
            summary["icon_asset"] = thumbnail

    summary["vtube"] = str(ensure_config(Path(summary["model"])))
    files = summary.pop("files")
    removed = _remove_stale(destination, files)
    if removed:
        summary["removed"] = removed
        print(f"已删除上次导出遗留、本次未生成的 {len(removed)} 个文件。", flush=True)
    write_atomic(destination / EXPORT_INFO, json_bytes({**(card_info or {}), "files": files}))
    summary["asset_id"] = model_id
    if output_name is not None:
        summary.update(card_id=card_id, output_name=output_name)
    summary["output_dir"] = str(destination)
    if make_zip:
        summary["zip"] = str(_make_zip(destination, force=force))
    return summary


def prepare_batch(batch_file: Path, **options: object) -> dict:
    """Process card/custom-folder pairs; report all line-level failures."""
    results = []
    used_names = set()
    for line_number, line in enumerate(batch_file.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(maxsplit=1)
        item: dict = {"line": line_number, **dict(zip(("card_id", "output_name"), fields))}
        try:
            if len(fields) != 2:
                raise ValueError("每行应为：卡牌/模型ID 自定义保存文件夹名")
            card_id, output_name = fields
            _batch_entry(card_id, output_name)
            if output_name.casefold() in used_names:
                raise ValueError(f"保存文件夹名重复：{output_name}")
            used_names.add(output_name.casefold())
            item.update(result=prepare(card_id, output_name=output_name, **options), status="ok")
        except Exception as error:
            item.update(status="error", error=str(error))
        results.append(item)
        print(f"第 {line_number} 行：{item['status']}", flush=True)
    if not results:
        raise ValueError("批量文件没有可处理的记录")
    return summarize(results)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add = parser.add_argument
    add("--version", action="version", version=f"%(prog)s {__version__}")
    add("asset_id", nargs="?", help="卡牌名或角色名搜索词；也可直接输入卡牌/模型 ID")
    add("--lang", choices=("chs", "cht"), default="chs", help="搜索语言：简中/繁中")
    add("--character", help="按角色名或编号筛选搜索结果")
    add("--pack-character", metavar="角色名或编号", help="下载角色全部模型，生成角色名.zip")
    add("--refresh", action="store_true", help="刷新官方卡牌目录")
    add("--app-version", default=APP_VERSION, help="游戏客户端版本（默认 auto，过期时自动查询官方商店）")
    add("--batch", type=Path, help="批量清单：每行一个卡牌/模型 ID 和自定义保存文件夹名（允许空格）")
    add("-o", "--output-root", type=Path, help="输出根目录（默认当前目录/output）")
    add("--cache-root", type=Path, help="下载缓存（默认当前目录/input/.holodori_assets）")
    add("--catalog", type=Path, help="指定游戏资源索引文件")
    add("--experimental-motions", action="store_true",
        help="实验性：额外导出候选动作（由游戏动画近似重建，可能与游戏内不一致）")
    add("--motion-level", help="配合 --experimental-motions 选择候选动作等级，默认 lv05")
    # Motions used to be on by default; keep the old opt-out flag working as a no-op.
    add("--no-motions", dest="experimental_motions", action="store_false", help=argparse.SUPPRESS)
    add("--no-zip", action="store_true", help="不生成压缩包")
    add("--force", action="store_true", help="覆盖已有的生成文件")
    return parser


def main() -> None:
    use_utf8_stdio()
    parser = _parser()
    args = parser.parse_args()
    if args.batch is not None and args.asset_id is not None:
        parser.error("--batch 与单项 ID 不能同时使用")
    if args.pack_character is not None and (args.batch is not None or args.asset_id is not None or args.no_zip):
        parser.error("--pack-character 不能与搜索词、--batch 或 --no-zip 同时使用")
    if args.motion_level is not None and not args.experimental_motions:
        parser.error("--motion-level 需要配合 --experimental-motions 使用")
    options = dict(
        output_root=args.output_root,
        cache_root=args.cache_root,
        catalog_path=args.catalog,
        motion_level=(args.motion_level or "lv05") if args.experimental_motions else None,
        force=args.force,
        make_zip=not args.no_zip,
    )
    try:
        if args.pack_character is not None:
            from . import search
            from .character_pack import download_character, resolve_character
            index = search.load_index(cache_dir(args.cache_root) / "master", language=args.lang,
                                      refresh=args.refresh, app_version=args.app_version)
            result = download_character(resolve_character(index, args.pack_character), index, **options)
        elif args.batch is not None:
            result = prepare_batch(args.batch, **options)
        elif args.asset_id is not None and _is_id(args.asset_id):
            result = prepare(args.asset_id, **options)
        else:
            from .interactive import run
            result = run(args.asset_id, language=args.lang, character=args.character,
                         refresh=args.refresh, app_version=args.app_version, **options)
            if result and result.get("failed"):
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
    if result.get("failed"):
        parser.exit(1)


if __name__ == "__main__":
    main()
