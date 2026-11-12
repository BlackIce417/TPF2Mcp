# 修复 TPF2 Workshop Mod 的 DDS mipmap 缺失

## 适用现象

游戏画面在移动镜头、缩放或车辆进入视野时出现短暂卡顿，`stdout.txt` 中反复出现：

```text
A texture *<Workshop ID>_1::<path>.dds ... does not have full mipmap chain
... texture_cache/... not in file cache!
```

前一条可直接核验：DDS 文件头里的 mipmap 数量低于该分辨率应有的完整层数。例如 2048×2048 贴图只有 1 层而非 12 层。

日志中的 `texture_cache` 未命中不能单独归因；应先确认实际缺少 mipmap 的贴图，并在相同存档和视角下对比修复前后的体验。

## 注意事项

- 先完全退出游戏。回到主菜单、重载存档不等同于重新启动 `TransportFever2.exe`。
- Workshop 内容会被 Steam 更新覆盖；修复前必须保存原件，更新后应重新核验。
- 从已压缩 DDS 重新生成 mipmap 会再次压缩低分辨率层。最佳方案仍是由 Mod 作者从原始贴图重新导出；本教程适用于本地修复。
- 不修改 Lua、DLL、存档或游戏可执行文件。

## 1. 定位问题 Mod

`stdout.txt` 位于 TPF2 用户数据目录的 `crash_dump` 下。搜索：

```powershell
rg -n "does not have full mipmap chain" "<TPF2 user data>\crash_dump\stdout.txt"
```

日志形如 `*2827359945_1::...` 时，`2827359945` 是 Workshop 条目 ID；通常目录为：

```text
<Steam library>\steamapps\workshop\content\1066780\2827359945
```

不要因单条日志直接判定卡顿根因。先确认当前游戏中没有待排查的后台程序或旧 Mod 采集任务，再解析贴图文件头。

## 2. 核验 DDS mipmap 层数

DDS 头部的宽、高、mipmap 数分别在偏移量 16、12、28。完整 mipmap 层数为：

```text
floor(log2(max(width, height))) + 1
```

以下 PowerShell 只读取文件并统计缺陷：

```powershell
$root = "<Workshop Mod root>"
$bad = foreach ($f in Get-ChildItem -LiteralPath $root -Recurse -File -Filter '*.dds') {
    $b = [IO.File]::ReadAllBytes($f.FullName)
    if ($b.Length -lt 128 -or [Text.Encoding]::ASCII.GetString($b, 0, 4) -ne 'DDS ') { continue }
    $w = [BitConverter]::ToInt32($b, 16)
    $h = [BitConverter]::ToInt32($b, 12)
    $mips = [BitConverter]::ToInt32($b, 28)
    $expected = [math]::Floor([math]::Log([math]::Max($w, $h), 2)) + 1
    if ($mips -lt $expected) {
        [pscustomobject]@{ File = $f.FullName; Width = $w; Height = $h; Mips = $mips; Expected = $expected }
    }
}
$bad | Format-Table -AutoSize
```

只修复同时满足以下条件的文件：日志点名，且此核验显示缺层。

## 3. 安装转换工具

使用 Microsoft DirectXTex 的 `texconv`，而不是 Windows 自带的 `convert.exe`。官方 Winget 包：

```powershell
winget install --id Microsoft.DirectXTex.Texconv --exact
```

安装后先执行 `texconv --help`。转换时不指定 `-f`，让工具保留输入 DDS 的格式；本次实测 DXT1 与 DXT5 都保持原格式和原始尺寸。

## 4. 先生成副本并验证

不要直接覆盖 Workshop 文件。以下示例为一个 Mod 的所有 DDS 生成副本；`-m 0` 表示生成完整 mipmap 链，`-r:keep` 保留原目录结构。

```powershell
$texconv = "<texconv.exe path>"
$source = "<Workshop Mod root>"
$output = "<project>\diagnostics\mipmap-repair\generated\<Workshop ID>"
& $texconv -r:keep -m 0 -o $output -y -- (Join-Path $source '*.dds')
if ($LASTEXITCODE -ne 0) { throw 'texconv failed' }
```

随后对每个原本缺层的文件核验：

- 输出文件存在且相对路径一致；
- 宽、高与原文件一致；
- DDS FourCC／DX10 标记与原文件一致；
- 输出 mipmap 数不少于完整层数。

本次修复的样本中，2048×2048 DXT5 从 1 层变为 12 层，1024×1024 DXT1／DXT5 从 1 层变为 11 层。

## 5. 备份并安装通过核验的文件

只复制已确认缺层且已通过验证的文件。将原件镜像保存到项目诊断目录，然后复制生成副本到原相对路径。复制完成后对输出与安装位置计算 SHA-256，确保二者相同。

不要删除整项 Workshop 内容，也不要覆盖本来就完整的贴图。Steam 后续下载或更新可能覆盖安装位置；保留备份和生成副本即可重复安装。

## 6. 完整重启并验证结果

1. 退出 TPF2，确认任务管理器中没有 `TransportFever2.exe`。
2. 从 Steam 启动游戏，进入原来的存档和相近视角。
3. 在新的启动日志区段中搜索被修复 Workshop ID；它们不应再出现 `does not have full mipmap chain`。
4. 仍可能有其他 Mod 或游戏自带资源产生同类警告。按 Workshop ID 分组后逐项处理，不能把旧日志总数当作新一次启动的结果。
5. 对比相同镜头移动、缩放和列车通过场景的流畅度；若仍有卡顿，再检查其他 Mod、Overlay、显存和帧时间。

## 本次本机实例

已修复的条目为中国铁路 25G 型客车、SS3 型电力机车、普速铁路信号设备和 CTCS2/3 信号设备，共 248 张 DDS。所有修复文件均通过了尺寸、压缩格式和完整 mipmap 层数的核验；原文件备份保存在项目 `diagnostics/mipmap-repair-20261021/original-backup` 下。

Steam 后续下载的 `3555757877` 是 CR400-AF-Z 清漆材质包，与上述四个条目独立，未覆盖修复结果。
