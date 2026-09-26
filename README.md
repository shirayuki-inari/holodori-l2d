# holodori-l2d

非官方的 `hololive Dreams` Live2D 资源处理工具。输入目标 ID，脚本会用 [holodori-asset-tools](https://github.com/HolodoriDB/holodori-asset-tools) 查询资源索引、下载游戏包、提取模型与表情，并生成可供 Cubism 播放器打开的 `.model3.json`。原始下载文件会缓存；生成的模型与素材不会随本仓库发布。

请先阅读[游戏模型与素材版权声明](COPYRIGHT.md)。本项目与 COVER、QualiArts、Live2D 均无官方关联。

## 安装

需要 Python 3.10 或更新版本、Git，以及网络连接。在项目目录运行：

```powershell
python -m pip install -e ".[assets]"
```

Windows 用户也可以安装后双击 `run_live2d.bat`，按提示输入 ID。

## 下载并导出

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

下载缓存默认位于当前目录的 `input/.holodori_assets/`；可用 `--cache-root` 和 `--catalog` 指定其他位置。已有不同内容的输出不会覆盖；需要重建时使用 `--force` 或换一个输出目录。旧 ZIP 不会在未加 `--force` 时被覆盖。

## 批量下载并导出

建立一个 UTF-8 文本文件（例如 `cards.txt`），每行先写**卡牌 ID**，再写**自定义保存文件夹名**：

```text
# 卡牌ID 保存文件夹名
00006-5-uniq-0007-00 fubuki-狐のお宮でこんこんこん
00006-5-uniq-0074-00 fubuki-渚で魅せるtwinkle
```

第一个空格或 Tab 分隔两列，后面的整段文字就是文件夹名，**可以包含空格，不需要加引号**。模型资源仍由卡牌 ID 自动查找；第二列只影响保存名称，不是资源索引名或本机路径。可写多行；空行及以 `#` 开头的整行注释会跳过。文件夹名不能包含路径分隔符或 Windows 禁用字符，同一批次不能重复。运行：

```powershell
holodori-l2d --batch cards.txt
holodori-l2d --batch cards.txt --no-motions --output-root D:\exports
```

上述第一行会输出到 `output/fubuki-狐のお宮でこんこんこん/`，并生成 `output/fubuki-狐のお宮でこんこんこん.zip`。每行独立处理，某行出错不会跳过后面的记录；结束时输出成功/失败数和逐行结果。只要有失败，命令退出码就是 1。`--force`、`--no-zip`、缓存和动作选项对所有行生效。单项命令仍沿用默认的 `live2d_<模型ID>` 输出名。

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

## 测试

测试只使用合成数据，不下载或提交游戏素材：

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```
