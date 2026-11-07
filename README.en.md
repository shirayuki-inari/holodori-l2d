# holodori-l2d

[简体中文](README.md) | English

An unofficial Live2D model exporter for `hololive Dreams`. Search for a card or character, pick what you want, and the tool downloads the game assets and builds model folders and ZIPs that work in Cubism viewers and VTube Studio.

> This project is not affiliated with COVER, QualiArts or Live2D. The repository contains no game assets; exported files still belong to their rights holders. Read the [copyright notice](COPYRIGHT.md) (in Chinese; summarized under [License](#license)) before use.

## Installation

Requires Python 3.10+ and an internet connection; **Git is not needed**. Open the [Releases page](https://github.com/shirayuki-inari/holodori-l2d/releases/latest) and run the install command shown there. For 1.0.0:

```powershell
python -m pip install "holodori-l2d[assets] @ https://github.com/shirayuki-inari/holodori-l2d/releases/download/v1.0.0/holodori_l2d-1.0.0-py3-none-any.whl"
```

On Windows, also download `run_live2d.bat` from the Releases page and put it in the folder where models should be saved. To update, run the install command from the newer release.

Developers can install from source instead: clone this repository and run `python -m pip install -e ".[assets]"` in it.

## Quick start

On Windows, double-click `run_live2d.bat`, or run in a terminal:

```powershell
holodori-l2d
```

Enter a card name, character name, English character name or character number (partial matches work; leave empty to browse everything), then choose from the list:

| Key | Action |
| --- | --- |
| ↑ ↓ / PageUp PageDown | Move / page |
| Space | Select or deselect (multiple allowed) |
| A | Select all / clear |
| Enter | Download the selection, or the current item if nothing is selected |
| P | Pack every model of the current character into one ZIP (asks first) |
| Esc | Back to search |
| Ctrl+C | Quit |

Cards marked “暂无模型” (no model) cannot be selected; “已导出” (exported) means the model is already in the output folder. After a download finishes you return to the search prompt.

Exports go to `output/` in the current directory. Copy a model folder as a whole into VTube Studio's `Live2DModels/` to use it.

> Card and character names come from the game's Chinese text (Simplified by default, Traditional with `--lang cht`). Character names can also be searched in English; card names cannot.

## Common commands

```powershell
holodori-l2d "宝物"                                # Search and open the selection list
holodori-l2d "We are hololive!" --character 00023  # Filter same-named cards by character
holodori-l2d "寶藏" --lang cht                     # Search Traditional Chinese data
holodori-l2d --pack-character "白上吹雪"           # Pack all models of a character (name or number)
holodori-l2d 04016-5-uniq-0079-00                  # Download by card ID / model ID / resource name
holodori-l2d --batch batch.txt                     # Batch download
holodori-l2d-search "宝物"                         # Search only, print JSON
```

`holodori-l2d` can also be run as `python -m holodori_l2d`.

### Character packs

Press **P** in the list, or use `--pack-character`, to export **every** model the character has in the asset catalog (including costume models without a card) into `output/<character name>.zip`. Each model gets its own folder in the ZIP, and `holodori-character.json` lists the contents.

The ZIP is created or updated only when every model exports successfully; on failure the previous ZIP is kept. If a ZIP with the same name was not created by this tool, the new one gets the character number appended.

### Download by ID

Three forms are accepted: card ID `04016-5-uniq-0079-00`, model ID `04016-uniq-0079-00`, or resource name `live2d_mdl_04016-uniq-0079-00`. The output folder is `live2d_<model ID>` and model files keep their in-game name.

### Batch download

A UTF-8 text file with one ID (any of the three forms) and an output folder name per line, separated by the first space or tab. Folder names may contain spaces; lines starting with `#` are comments:

```text
# ID  folder name
00006-5-uniq-0007-00 fubuki-狐のお宮でこんこんこん
live2d_mdl_00024-nrml-0020-00 my model 2
```

Each line is processed independently; an error does not stop the others, and a per-line report is printed at the end. Folder names must be unique within a batch.

### Search only

`holodori-l2d-search` prints JSON for scripts. When `model_exists` is `true`, pass the result's `resource_name` to `holodori-l2d` to download it.

Searches match the game's original text; Simplified and Traditional Chinese (`--lang`) are not converted into each other.

## Output

```text
output/
├─ 独占宝物♡水力加农炮/
│  ├─ 独占宝物♡水力加农炮.model3.json   ← open this file in a viewer
│  ├─ 独占宝物♡水力加农炮.moc3
│  ├─ 独占宝物♡水力加农炮.physics3.json
│  ├─ 独占宝物♡水力加农炮.4096/         textures
│  ├─ 独占宝物♡水力加农炮.vtube.json    VTube Studio settings
│  ├─ icon.jpg                           card thumbnail
│  ├─ expressions/
│  └─ motions/                           only with experimental motions
└─ 独占宝物♡水力加农炮.zip
```

- **Naming**: downloads from the search list are named after the card. When card names collide, the folder name gets the character name or ID appended. Characters Windows does not allow become full-width equivalents.
- **Icon**: `icon.jpg` is the matching card's thumbnail. If no unique thumbnail is found it is skipped; another card's image is never used.
- **VTube Studio settings**: `.vtube.json` is created only on the first export and is never rewritten afterwards, even with `--force`, so your VTube Studio settings are preserved.
- **Overwriting**: existing files with different content cause an error unless `--force` is given; an existing single-model ZIP is also only updated with `--force`.
- **Re-exporting**: `.holodori-model.json` records the files this tool generated. A re-export deletes files from the previous export that are no longer produced; files you added yourself, `.vtube.json` and `icon.jpg` are never deleted.

## Options

| Option | Description |
| --- | --- |
| `--lang chs\|cht` | Search Simplified (default) or Traditional Chinese data |
| `--character <name or number>` | Filter search results by character |
| `--refresh` | Update the card catalog (after new cards are released) |
| `-o, --output-root <dir>` | Output folder, default `./output` |
| `--cache-root <dir>` | Download cache, default `./input/.holodori_assets` |
| `--no-zip` | Do not create single-model ZIPs (not with `--pack-character`) |
| `--force` | Overwrite existing output with different content |
| `--experimental-motions` | **Experimental**: also export candidate motions |
| `--motion-level <level>` | Motion level for the option above, default `lv05` |
| `--app-version <version>` | Client version for the official API, default `1.2.1`; set the current game version if searches fail after a game update |
| `--catalog <file>` | Use a specific asset catalog file |
| `--version` | Show the version |

The exit code is non-zero when the command fails or any download fails.

## Fidelity and limitations

- MOC3 files and texture PNGs are copied unchanged; expressions and physics are converted from game data to Cubism JSON.
- **Motions are experimental**: they are approximated from Unity animation curves with a fixed 0.5 s fade and may not match in-game playback. They are the catalog's shared candidate motions, not a verified per-character set.
- `.vtube.json` only contains the name, model and icon references; set up tracking and hotkeys in VTube Studio.
- To preview expressions, use Cubism Viewer (for OW). Open the `.model3.json` file, not the `.moc3` alone.

## Advanced: rebuilding extracted assets

If you have already extracted the model and expression bundles with [holodori-asset-tools](https://github.com/HolodoriDB/holodori-asset-tools), rebuild them directly:

```powershell
holodori-l2d-rebuild "D:\extracted\live2d_mdl_04016-uniq-0079-00" -o "D:\exports\model"
```

For experimental motion conversion, pass the original `live2d_mot_*` Unity bundles with `--motion-bundle` (repeatable) or `--motion-dir` plus `--motion-pattern`.

## Data sources and privacy

Searches use the game's official master-data API and asset index directly, with no third-party data mirror; downloading and extraction use [holodori-asset-tools](https://github.com/HolodoriDB/holodori-asset-tools). No game account or login is needed. Search data is cached in `input/.holodori_assets/master/`, so later searches work offline.

## Development

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

Tests use synthetic data only. `input/`, `output/` and model files are in `.gitignore`; never commit downloaded or exported assets.

## License

The code in this repository is released under the [MIT License](LICENSE). The license covers **only this repository's code**, not the game assets the tool downloads or the files it generates. Game assets © COVER / © QualiArts, Inc. and their respective rights holders; this project grants no rights to them. See [COPYRIGHT.md](COPYRIGHT.md) (in Chinese), and make sure your use complies with the game's terms of service.
