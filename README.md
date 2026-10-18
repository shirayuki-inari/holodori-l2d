# holodori-l2d

非官方的 `hololive Dreams` Live2D 资源处理工具。输入中文卡牌名或角色名，用方向键和空格多选，即可下载并生成可供 Cubism / VTube Studio 导入的模型。查询使用游戏官方主数据；资源提取使用 [holodori-asset-tools](https://github.com/HolodoriDB/holodori-asset-tools)。原始下载文件会缓存；生成的模型与素材不会随本仓库发布。

请先阅读[游戏模型与素材版权声明](COPYRIGHT.md)。本项目与 COVER、QualiArts、Live2D 均无官方关联。

## 安装

需要 Python 3.10 或更新版本、Git，以及网络连接。在项目目录运行：

```powershell
git clone https://github.com/shirayuki-inari/holodori-l2d.git
cd holodori-l2d
python -m pip install -e ".[assets]"
```

Windows 用户安装后双击 `run_live2d.bat` 即可进入搜索。已有安装也请执行上面的命令更新交互界面依赖。

## 搜索、选择并下载（默认入口）

```powershell
holodori-l2d
```

也可以运行 `python -m holodori_l2d`。输入卡牌名、角色名或角色编号，支持部分名称（例如“吹雪”），留空可浏览全部卡牌。搜索会同时匹配卡牌和角色，结果显示卡名、角色和卡牌 ID：

- **↑ / ↓**：移动光标；**PageUp / PageDown**：翻页。
- **空格**：勾选/取消，多选。
- **A**：全选/清空可下载项。
- **Enter**：下载勾选项；未勾选时下载光标所在项。
- **P**：下载光标所在角色的全部模型，自动生成角色名 ZIP。
- **Esc**：返回重新搜索；**Ctrl+C**：退出。

也可直接带搜索词启动列表：

```powershell
holodori-l2d "宝物"
holodori-l2d "白上吹雪"
holodori-l2d "We are hololive!" --character 00023
holodori-l2d "寶藏" --lang cht
holodori-l2d --refresh
```

首次加载官方卡牌目录，之后使用缓存；`--refresh` 获取新卡牌。没有模型的卡牌标为“暂无模型”，不能勾选。多个下载逐项执行，失败会显示原因并继续其余项。

**搜索下载以卡牌名称命名文件夹和模型文件**，例如：

```text
output/
├─ 独占宝物♡水力加农炮/
│  ├─ 独占宝物♡水力加农炮.model3.json
│  ├─ 独占宝物♡水力加农炮.moc3
│  ├─ 独占宝物♡水力加农炮.physics3.json
│  ├─ icon.jpg
│  ├─ 独占宝物♡水力加农炮.4096/
│  ├─ expressions/
│  └─ motions/
└─ 独占宝物♡水力加农炮.zip
```

将整个模型文件夹复制到 VTube Studio 的 `Live2DModels/`，首次导入以卡牌名作为模型名称（由同名 `.model3.json` 创建 VTS 配置）。同名卡牌的文件夹追加角色名，仍冲突时追加 ID；模型文件名仍使用卡牌名。Windows 禁用符号转换为全角符号，过长名称会截短。目录中的 `.holodori-model.json` 记录卡牌归属，以便重跑时识别已导出的模型。

下载时会同时获取对应卡牌的 `img_card_live_thumb_*` 图片包，提取并转换为真正的 JPEG，保存为模型目录中的 **`icon.jpg`**，新生成的单模型 ZIP 和角色整包也会包含它。保持原图尺寸；透明区域以白色填充。搜索/角色打包按对应卡牌 ID 精确匹配；直接按模型 ID 下载时，仅在缩略图匹配唯一时使用。没有卡牌或找不到唯一对应缩略图时会提示跳过，不借用其他卡牌图片。已有不同内容的 `icon.jpg` 不会覆盖，需加 `--force`；更新已有单模型 ZIP 同样需要 `--force`。

## 角色全模型打包

搜索角色名后，在结果列表按 **P** 即可。即使当前只搜到该角色的一张卡，也会从完整资源目录取出该角色的全部模型，按资源名去重，包含没有对应卡牌的服装模型。

也可以直接运行：

```powershell
holodori-l2d --pack-character "白上吹雪"
holodori-l2d --pack-character 00009
holodori-l2d --pack-character "白上吹雪" --refresh --no-motions
```

默认生成 `output/白上吹雪.zip`，包内各模型保持独立文件夹，解压后可将这些文件夹放入 VTube Studio 的 `Live2DModels/`。卡牌模型沿用卡牌名；无卡牌模型使用官方服装名，缺少名称时使用模型 ID。根目录的 `holodori-character.json` 记录角色、模型清单及目录版本。

整包模式只生成一个角色 ZIP，模型文件夹仍保存在输出目录中。相同资源不会重复下载；所有模型导出成功后才生成或更新整包。任一模型失败时显示失败项，本次不生成新整包，已有整包会保留。再次执行会更新本工具生成的同角色 ZIP；如果同名 ZIP 属于其他内容，会自动追加角色编号避让。

`--pack-character` 支持完整/部分角色名及编号；匹配多个角色时会列出候选编号。可用 `--lang cht`、`--output-root`、`--motion-level`、`--no-motions` 等选项。`--no-zip` 用于普通下载，不能与 `--pack-character` 同时使用；在列表中按 P 始终执行角色 ZIP 打包。

## 按 ID 下载并导出

```powershell
holodori-l2d 04016-5-uniq-0079-00
```

也可以运行 `python -m holodori_l2d 04016-5-uniq-0079-00`。接受卡牌 ID、`04016-uniq-0079-00` 模型 ID，以及 `live2d_mdl_04016-uniq-0079-00` 资源名。默认在当前工作目录生成：

```text
output/
├─ live2d_04016-uniq-0079-00/
│  ├─ 04016_004.model3.json
│  ├─ 04016_004.moc3
│  ├─ 04016_004.4096/
│  │  └─ t_live2d_04016-uniq-0079-00_texture_00.png
│  ├─ 04016_004.physics3.json
│  ├─ expressions/
│  └─ motions/
└─ live2d_04016-uniq-0079-00.zip
```

请保持整个模型目录结构不变，在支持 Cubism 5 的播放器中打开 `.model3.json`，不要只打开 `.moc3`。表情预览可使用 **Cubism Viewer (for OW)**；独立的 Viewer for Unity 没有相同的表情列表。

默认下载角色表情和索引中共用的 `lv05` 候选动作。动作并非逐个针对该角色确认过的专属清单。常用选项：

```powershell
holodori-l2d 04016-5-uniq-0079-00 --no-motions
holodori-l2d 04016-5-uniq-0079-00 --motion-level lv04
holodori-l2d 04016-5-uniq-0079-00 --output-root D:\exports --no-zip
```

下载缓存默认位于当前目录的 `input/.holodori_assets/`；可用 `--cache-root` 和 `--catalog` 指定其他位置。已有不同内容的输出不会覆盖；需要重建时使用 `--force` 或换一个输出目录。普通单模型 ZIP 不会在未加 `--force` 时被覆盖；角色整包采用上节所述的更新规则。

## 批量下载并导出

建立一个 UTF-8 文本文件（例如 `batch.txt`），每行先写**卡牌 ID、模型 ID 或 `live2d_mdl_*` 资源名**，再写**自定义保存文件夹名**：

```text
# 卡牌/模型ID或资源名 保存文件夹名
00006-5-uniq-0007-00 fubuki-狐のお宮でこんこんこん
00006-5-uniq-0074-00 fubuki-渚で魅せるtwinkle
live2d_mdl_00024-nrml-0020-00 live2d_00024-nrml-0020-00
```

第一个空格或 Tab 分隔两列，后面的整段文字就是文件夹名，**可以包含空格，不需要加引号**。第一列用于查找模型资源；第二列只影响保存名称，不是资源索引名或本机路径。可写多行；空行及以 `#` 开头的整行注释会跳过。文件夹名不能包含路径分隔符或 Windows 禁用字符，同一批次不能重复。运行：

```powershell
holodori-l2d --batch batch.txt
holodori-l2d --batch batch.txt --no-motions --output-root D:\exports
```

上述第一行会输出到 `output/fubuki-狐のお宮でこんこんこん/`，并生成 `output/fubuki-狐のお宮でこんこんこん.zip`。每行独立处理，某行出错不会跳过后面的记录；结束时输出成功/失败数和逐行结果。只要有失败，命令退出码就是 1。`--force`、`--no-zip`、缓存和动作选项对所有行生效。单项命令仍沿用默认的 `live2d_<模型ID>` 输出名。

## 仅查询（JSON / 脚本使用）

`holodori-l2d-search` 适合只需要 ID 或 JSON 结果的场景。查询功能直接从游戏官方 `/rpc.api.Master/Get` 获取主数据包，并从官方 Octo 索引核实模型是否存在；查询时不访问第三方数据仓库：

```powershell
holodori-l2d-search "宝物"
holodori-l2d-search "We are hololive!" --character 00023
holodori-l2d-search "宝物" --refresh
```

也可以使用 `python -m holodori_l2d.search`。支持卡牌名、角色名、角色编号、部分名称及 `--lang cht` 繁体中文；搜索使用游戏原文，简繁不会自动互转。同名卡牌全部返回，可用 `--character` 按角色名或编号进一步筛选。

例如搜索“宝物”会返回“独占宝物♡水力加农炮”、`card-00023-5-uniq-0085-00` 和 `live2d_mdl_00023-uniq-0085-00`。输出包含 `model_exists`；只有它为 `true` 才表示该资源在此次查询的索引中存在。查询成功后可将 `resource_name` 交给下载命令：

```powershell
holodori-l2d live2d_mdl_00023-uniq-0085-00
```

映射优先使用 `Card.reward_costume_id → Costume.asset_id`；没有服装奖励的卡牌按 `Card.asset_id` 去掉稀有度段得到候选模型，并核对目录，结果中用 `mapping_source` 标明来源。无卡牌模型也可按角色或服装名搜索，结果标为“服装模型”，JSON 中 `card_id` 为 `null`、`mapping_source` 为 `catalog_costume`。

首次查询下载卡牌、角色、服装及各自名称共六张表和模型索引；缓存位于 `input/.holodori_assets/master/`。旧版仅卡牌缓存会在首次使用时联网升级。之后默认使用缓存，可离线搜索。`--refresh` 更新，`--cache-root` 更改缓存目录；输出的主数据版本、资源索引版本和抓取时间用于判断新旧。“全部模型”以该缓存版本为准，新内容需刷新。刷新失败会保留原有查询索引并报错。

官方接口需要客户端版本号，当前默认 `1.2.1`，版本检查失败时可用 `--app-version <游戏当前版本>` 指定。已验证的主数据格式为 SQLCipher 4（4096 字节页、raw key、逐页 HMAC-SHA512 校验），表记录为 protobuf；不需要安装 SQLCipher。上游改动协议、密钥或压缩格式时可能需要更新读取器。

## 使用已有的提取资源

如果模型包和表情包已经由上游工具提取，也可以直接运行底层命令：

```powershell
holodori-l2d-rebuild "D:\extracted\live2d_mdl_04016-uniq-0079-00" -o "D:\exports\model"
```

`--motion-bundle` 可重复指定原始 `live2d_mot_*` 包；或用 `--motion-dir` 与 `--motion-pattern` 批量指定。动作需要使用原始 Unity 包，不要使用上游 `extract` 输出的同名动作定义 JSON。

## 还原范围与局限

- MOC3 字节与 PNG 纹理直接复制，不重编码；纹理放入与 MOC 同名前缀的 `.4096/` 目录。
- 表情的参数 ID、数值、混合方式、淡变时间由游戏包转换为 `.exp3.json`；`04016` 示例已逐项比对。
- 物理配置从 Unity 序列化数据重建。少数原始组名可能因提取时字符解码而使用占位名，数值不因此改变。
- `.motion3.json` 是由 Unity `AnimationClip` 的参数曲线反向重建，数值被舍入到 5 位小数，过渡时间统一设为 0.5 秒。它可用于预览，**不保证与游戏内播放完全一致，也不是原始 motion3 文件的无损副本**。
- 不包含 VTube Studio 的 `.vtube.json` 配置、面部追踪参数映射或热键设置，导入后需要自行配置。文件结构和引用已验证；不代表已在所有播放器或操作系统中完成实机验证。

## 公开范围与许可

仓库仅公开工具代码、文档及合成测试，不包含游戏数据库、下载包或导出模型。`input/`、`output/`、主数据缓存和常见模型文件均已加入 `.gitignore`；使用自定义缓存/导出目录时，也请勿将其提交或作为仓库附件上传。

代码目前**未指定对外许可证**；公开可查看不等同于授予开源使用、修改或再分发许可。游戏数据及素材的权利归属独立于工具代码，详见 [COPYRIGHT.md](COPYRIGHT.md)。代码中的客户端协议常量不属于个人登录凭据；工具不需要游戏账号或会话令牌。下载及使用仍须自行确认符合服务条款与适用规定。

## 测试

测试只使用合成数据，不下载或提交游戏素材：

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```
