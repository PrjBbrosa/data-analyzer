# 扩展安装器的本地发布配置

这是给本机试打 `installer.exe` 的第一版配置，不是正式发布源。`updates.example.invalid` 是保留域名，旁边的 `root.json` 也不是 TUF 信任根。正式对外发布前，发布负责人要换成真实 HTTPS 源、官方 `root.json` 和根密钥保管记录。不要把这份占位文件当成已经可以在线安装扩展。

## 两条包各打各的

1. `tools/build_windows_extension_installer.ps1` 只冻结扩展管理器。它读 `repository.json`，把其中的 `bootstrap_root` 指到的 `root.json` 一并打进单文件 `dist\TraceLabExtensionManager\installer.exe`，并在旁边写下 `manager-build.json`。它不生成分析器目录，也不生成生产私钥。
2. `tools/build_windows_folder_lite_modular.ps1` 才打 `TraceLabAnalyzer<版本>-modular`。它不调用上一步脚本，只接受已经自检过的 `installer.exe`。没有这个文件就会拒绝开工。

原来的 `build_windows_folder.ps1` 和 `build_windows_folder_lite.ps1` 仍是完整包和普通 Lite 包，不走这条扩展链。

## 本机试打

在仓库根目录：

```bat
tools\build_windows_extension_installer.bat -RepositoryConfig configs\extension-release\local\repository.json
tools\build_windows_folder_lite_modular.bat -ManagerSource dist\TraceLabExtensionManager\installer.exe
```

第一条需要 Windows x64，以及带 `tkinter` 的 Python。第二条要等 `installer.exe` 已经生成。
