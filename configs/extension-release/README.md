# 扩展安装器的本地发布配置

这是给本机试打 `installer.exe` 的第一版配置，不是正式发布源。`updates.example.invalid` 是保留域名，旁边的 `root.json` 也不是 TUF 信任根。正式对外发布前，发布负责人要换成真实 HTTPS 源、官方 `root.json` 和根密钥保管记录。不要把这份占位文件当成已经可以在线安装扩展。

## 一键打包

在 Windows 上直接双击 `tools/build_windows_folder_lite_modular.bat`。它会先构建、自检 `installer.exe`，再打包 Modular 并把 installer 放进成品目录；结束后窗口保留成功或失败信息。默认成品为 `dist\TraceLabAnalyzer8.3.2-modular\`。

无需每次填写参数。未指定仓库配置时，installer 使用本目录下的 `local/repository.json`；目前它仍是上述占位配置，打包成功不代表在线扩展源可用。正式发布应通过 `-RepositoryConfig` 指定真实配置。脚本不生成信任根或私钥。

只打 installer 时，可以直接双击 `tools/build_windows_extension_installer.bat`。两个 BAT 都只在无参数调用时暂停，带参数调用保留退出码且不暂停。

## 两条脚本的职责

1. `tools/build_windows_extension_installer.ps1` 只冻结扩展管理器。它读 `repository.json`，把其中的 `bootstrap_root` 指到的 `root.json` 一并打进单文件 `dist\TraceLabExtensionManager\installer.exe`，并在旁边写下 `manager-build.json`。它不生成分析器目录，也不生成生产私钥。
2. `tools/build_windows_folder_lite_modular.ps1` 打 `TraceLabAnalyzer<版本>-modular`。默认自动调用上一步脚本，installer 失败便停止；显式传入 `-ManagerSource` 时复用指定的、已自检的 installer，跳过 installer 构建。原有文件哈希和自检证据检查仍然生效。

原来的 `build_windows_folder.ps1` 和 `build_windows_folder_lite.ps1` 仍是完整包和普通 Lite 包，不走这条扩展链。

## 命令行覆盖默认配置

在仓库根目录：

```bat
tools\build_windows_folder_lite_modular.bat -RepositoryConfig "C:\release\repository.json"
```

也可以沿用分开构建的方式：

```bat
tools\build_windows_extension_installer.bat -RepositoryConfig "C:\release\repository.json"
tools\build_windows_folder_lite_modular.bat -ManagerSource dist\TraceLabExtensionManager\installer.exe
```

第一条需要 Windows x64，以及带 `tkinter` 的 Python。第二条要等 `installer.exe` 已经生成。

installer 会检查实际 Python 构建架构及 tkinter。需要新建环境时，依次尝试仓库的 `.build-tools/python312-x64/python.exe`、分析器构建环境 `.venv-build-win` 和系统 `python`。已有 installer 环境若不兼容，会先保留为 `.venv-extension-manager.incompatible-*`，再用验证通过的 x64 Python 重建；不会修改系统 Python。

Modular 的 `-SkipInstall` 和 `-Console` 也传给自动构建的 installer。新建或修复 installer 环境时仍会安装必要依赖；已有健康环境才会跳过安装。

## 运行和更新成品

BAT 用于开发时重新打包。日常使用直接打开成品目录里的主程序 EXE，可以为它创建桌面快捷方式。这里的 `installer.exe` 是扩展管理器，扩展安装到所选主程序目录的 `extensions/`，包含组件、启用状态和下载缓存；它不是主程序的安装向导。主程序诊断日志另存于 `%LOCALAPPDATA%\TraceLab\logs`。

把成品整个文件夹放到 Windows 本地磁盘后运行；扩展安装要求本地 NTFS，不能直接安装到 Parallels 的 Z: 共享目录。更新时先退出主程序和扩展管理器，保留旧目录作备份，将新成品放到新目录，再复制旧目录的完整 `extensions/`。EXE、`_internal/`、`core.json` 和 `core-files.json` 必须来自同一次构建，不能只替换 EXE 或混用旧依赖。

扩展按 `runtime_id` 匹配。新旧构建运行时身份相同才会复用原有选择；身份改变时，需要安装对应运行时的扩展。普通复制文件夹不会自动完成扩展版本迁移。
