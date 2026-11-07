# holodori-l2d

简体中文 | [English](README.en.md)

非官方的 `hololive Dreams` Live2D 模型导出工具：搜索卡牌或角色，选中后自动下载游戏资源，生成可在 Cubism 播放器和 VTube Studio 中使用的模型文件夹与 ZIP。

> 本项目与 COVER、QualiArts、Live2D 均无官方关联。仓库不包含任何游戏素材；生成的文件仍属于原权利人，使用前请阅读[版权声明](COPYRIGHT.md)。

## 安装

需要 Python 3.10+ 和网络连接，**不需要 Git**。打开 [Releases 页面](https://github.com/shirayuki-inari/holodori-l2d/releases/latest)，复制其中的安装命令运行即可。以 1.0.0 为例：

```powershell
python -m pip install "holodori-l2d[assets] @ https://github.com/shirayuki-inari/holodori-l2d/releases/download/v1.0.0/holodori_l2d-1.0.0-py3-none-any.whl"
```

Windows 用户可以同时从 Releases 页面下载 `run_live2d.bat`，放到想保存模型的文件夹里。更新时运行新版本 Release 中的安装命令即可。

开发者也可以从源码安装：`git clone` 本仓库后，在项目目录运行 `python -m pip install -e ".[assets]"`。

## 快速开始

Windows 双击 `run_live2d.bat`，或在终端运行：

```powershell
holodori-l2d
```

输入卡牌名、角色名、英文角色名或角色编号（支持部分匹配，留空浏览全部），然后在列表中选择：

| 按键 | 作用 |
| --- | --- |
| ↑ ↓ / PageUp PageDown | 移动 / 翻页 |
| 空格 | 勾选或取消（可多选） |
| A | 全选 / 清空 |
| Enter | 下载勾选项；未勾选时下载当前项 |
| P | 打包当前角色的全部模型为一个 ZIP（会先确认） |
| Esc | 返回重新搜索 |
| Ctrl+C | 退出 |

列表中“暂无模型”的卡牌不能选择，“已导出”表示输出目录里已有该模型。下载完成后会回到搜索框，可以继续搜索。

导出结果在当前目录的 `output/` 下。把模型文件夹整个复制到 VTube Studio 的 `Live2DModels/` 即可使用。

## 常用命令

```powershell
holodori-l2d "宝物"                                # 直接搜索并进入选择列表
holodori-l2d "We are hololive!" --character 00023  # 同名卡牌按角色筛选
holodori-l2d "寶藏" --lang cht                     # 使用繁体中文数据搜索
holodori-l2d --pack-character "白上吹雪"           # 打包角色全部模型（也可用角色编号）
holodori-l2d 04016-5-uniq-0079-00                  # 按卡牌 ID / 模型 ID / 资源名下载
holodori-l2d --batch batch.txt                     # 批量下载
holodori-l2d-search "宝物"                         # 只查询，输出 JSON
```

`holodori-l2d` 也可以写成 `python -m holodori_l2d`。

### 角色整包

在列表中按 **P**，或使用 `--pack-character`，会导出该角色在资源目录中的**全部**模型（包括没有对应卡牌的服装模型），生成 `output/<角色名>.zip`。ZIP 内每个模型一个文件夹，另有 `holodori-character.json` 记录模型清单。

只有全部模型都导出成功才会生成或更新 ZIP；有失败时保留原有 ZIP。如果同名 ZIP 不是本工具生成的，新 ZIP 名会追加角色编号。

### 按 ID 下载

接受三种写法：卡牌 ID `04016-5-uniq-0079-00`、模型 ID `04016-uniq-0079-00`、资源名 `live2d_mdl_04016-uniq-0079-00`。输出文件夹为 `live2d_<模型ID>`，模型文件沿用游戏内的名称。

### 批量下载

UTF-8 文本文件，每行写一个 ID（同上三种写法）和保存文件夹名，用第一个空格或 Tab 分隔；文件夹名可以包含空格，`#` 开头的行为注释：

```text
# ID 保存文件夹名
00006-5-uniq-0007-00 fubuki-狐のお宮でこんこんこん
live2d_mdl_00024-nrml-0020-00 my model 2
```

每行独立处理，出错不影响其他行；结束时输出每行的结果。同一批次中的文件夹名不能重复。

### 仅查询

`holodori-l2d-search` 输出 JSON，适合脚本使用。`model_exists` 为 `true` 时，可把结果中的 `resource_name` 交给 `holodori-l2d` 下载。

搜索匹配的是游戏原文：简体与繁体（`--lang`）不会互相转换。

## 输出内容

```text
output/
├─ 独占宝物♡水力加农炮/
│  ├─ 独占宝物♡水力加农炮.model3.json   ← 用播放器打开这个文件
│  ├─ 独占宝物♡水力加农炮.moc3
│  ├─ 独占宝物♡水力加农炮.physics3.json
│  ├─ 独占宝物♡水力加农炮.4096/         纹理
│  ├─ 独占宝物♡水力加农炮.vtube.json    VTube Studio 配置
│  ├─ icon.jpg                           卡牌缩略图
│  ├─ expressions/                       表情
│  └─ motions/                           动作（仅启用实验性动作时）
└─ 独占宝物♡水力加农炮.zip
```

- **命名**：从搜索列表下载时，文件夹和模型文件以卡牌名命名；卡牌重名时，文件夹名会追加角色名或 ID。Windows 不允许的符号会转为全角。
- **图标**：`icon.jpg` 来自对应卡牌的缩略图。找不到唯一对应的缩略图时跳过，不会借用其他卡牌的图片。
- **VTube Studio 配置**：`.vtube.json` 只在首次导出时生成，之后即使加 `--force` 也不会改写，以保留你在 VTube Studio 中的设置。
- **覆盖规则**：已有文件内容不同时默认报错，加 `--force` 才会覆盖；已有的单模型 ZIP 也只在加 `--force` 时更新。
- **重新导出**：`.holodori-model.json` 记录本工具生成的文件。重新导出时，会删除上次生成、这次不再生成的文件；你自己放入的文件、`.vtube.json` 和 `icon.jpg` 不会被删除。

## 选项

| 选项 | 说明 |
| --- | --- |
| `--lang chs\|cht` | 搜索使用简体（默认）或繁体中文数据 |
| `--character <名称或编号>` | 按角色筛选搜索结果 |
| `--refresh` | 更新卡牌目录（游戏推出新卡后使用） |
| `-o, --output-root <目录>` | 输出目录，默认 `./output` |
| `--cache-root <目录>` | 下载缓存目录，默认 `./input/.holodori_assets` |
| `--no-zip` | 不生成单模型 ZIP（不能与 `--pack-character` 同用） |
| `--force` | 覆盖内容不同的已有输出 |
| `--experimental-motions` | **实验性**：同时导出候选动作 |
| `--motion-level <等级>` | 配合上一项选择动作等级，默认 `lv05` |
| `--app-version <版本>` | 官方接口的客户端版本，默认 `1.2.1`；游戏更新后查询失败时指定新版本 |
| `--catalog <文件>` | 使用指定的资源索引文件 |
| `--version` | 显示版本 |

命令出错或有下载失败时，退出码不为 0。

## 还原范围与局限

- MOC3 与纹理 PNG 原样复制；表情、物理由游戏数据转换为 Cubism JSON。
- **动作是实验性的**：由 Unity 动画曲线近似重建，过渡时间统一为 0.5 秒，与游戏内播放不一定一致；导出的是索引中共用的候选动作，并非针对该角色逐个确认的动作。
- `.vtube.json` 只包含名称、模型和图标引用，追踪参数和热键需要在 VTube Studio 中设置。
- 预览表情可使用 Cubism Viewer (for OW)；请打开 `.model3.json`，不要只打开 `.moc3`。

## 进阶：处理已提取的资源

如果已用 [holodori-asset-tools](https://github.com/HolodoriDB/holodori-asset-tools) 提取了模型包和表情包，可以直接重建：

```powershell
holodori-l2d-rebuild "D:\extracted\live2d_mdl_04016-uniq-0079-00" -o "D:\exports\model"
```

实验性动作转换可用 `--motion-bundle`（可重复）或 `--motion-dir` 加 `--motion-pattern` 指定原始的 `live2d_mot_*` Unity 包。

## 数据来源与隐私

查询直接使用游戏官方的主数据接口和资源索引，不经过第三方数据镜像；资源下载与提取使用 [holodori-asset-tools](https://github.com/HolodoriDB/holodori-asset-tools)。工具不需要游戏账号或登录信息。查询数据缓存在 `input/.holodori_assets/master/`，之后可离线搜索。

## 开发

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

测试只使用合成数据。`input/`、`output/` 和模型文件已加入 `.gitignore`，请勿把下载或导出的素材提交到仓库。

## 许可

本项目的代码以 [MIT 许可证](LICENSE)发布。该许可**仅适用于本仓库的代码**，不适用于工具下载或生成的游戏素材；素材的权利说明见 [COPYRIGHT.md](COPYRIGHT.md)。下载与使用前请自行确认符合游戏服务条款。
