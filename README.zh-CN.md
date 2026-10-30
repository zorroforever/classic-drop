# Classic Drop

[English](README.md) | 简体中文 | [日本語](README.ja.md)

[![平台：macOS](https://img.shields.io/badge/platform-macOS-111111?logo=apple&logoColor=white)](#运行要求)
[![Python：3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](#开发指南)
[![许可证：GPL-3.0-or-later](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)](LICENSE)
[![状态：Alpha](https://img.shields.io/badge/status-alpha-orange)](#项目状态)

Classic Drop 是一款原生 macOS 音乐导入工具，面向运行 **Apple 原厂固件的 iPod Classic**。它将选中的音乐追加到现有 iPod 曲库，无需像传统 iTunes/iTools 工作流那样执行耗时、可能移除已有内容的全量核对。

如果你希望保留 iPod 上已有的音乐，快速添加几张专辑，同时保留设备现有的数据库数据、专辑封面和元数据，Classic Drop 就是为这样的使用方式设计的。

> **重要提示：** Classic Drop 仍是实验性软件。首次写入前，请完整备份 iPod。应用已在改装 SSD 的 A1238 iPod Classic 上进行过测试，但尚未充分覆盖其他硬件配置和数据库损坏的情况。

## 主要功能

- **增量导入：** 仅追加选中的曲目，正常导入不会移除已有歌曲。
- **Apple 数据库支持：** 通过 iOpenPod 数据库层读取和写入原厂固件使用的 `iTunesDB` 和 `ArtworkDB`。
- **元数据编辑：** 导入前可检查并修改标题、艺人、专辑、专辑艺人、碟号和曲号。
- **封面保留：** 使用音频文件的内嵌封面，或同目录中以 `cover`、`folder`、`front` 命名的图片，并写入适合设备的封面格式。
- **浏览现有曲库：** 以只读方式查看 iPod 曲库，按曲目、艺人或专辑搜索。
- **专辑视图：** 在歌曲列表和封面网格之间切换，双击专辑即可查看曲目、年份、时长和封面。
- **重复曲目提示：** 疑似重复的歌曲默认不勾选，可在导入前逐项检查。
- **可恢复移除：** 在独立工作区中检查并明确选择要移除的音乐曲目，恢复数据保留在 iPod 上。
- **恢复操作：** 写入中断后保留恢复记录，并在应用中提供恢复入口。
- **macOS 工作区：** 提供侧栏导航、原生工具栏、可折叠封面检查器和系统配色，界面支持英语、简体中文和日语。
- **只读设备发现：** 连接、发现和浏览设备不会修改 iPod。

## 支持范围与非目标

Classic Drop 目前面向：

- macOS 电脑；
- 运行 Apple 原厂固件的 iPod Classic；
- 可通过文件系统访问，且 iTunes 数据库可读的设备；
- 音乐导入、封面与元数据处理，以及明确选择后的可恢复音乐曲目移除。

以下内容不在当前范围内：

- 使用 Rockbox 管理的设备；
- iPod touch、iPhone 或 iPod shuffle；
- 永久删除，或根据镜像同步自动删除内容；
- 移除播客、有声书、视频或其他非音乐媒体；
- 替代 Finder/iTunes 的完整设备管理功能；
- 云音乐服务或在线元数据查询。

导入始终只追加内容。移除已有音乐需要进入独立的 **To Remove（待移除）** 工作区，在确认前检查所选曲目及受影响的播放列表。移除曲目也会移除它们在各播放列表中的条目，原始数据库和媒体文件则保留在 iPod 上用于恢复。恢复数据仍占用设备容量，因此移除不会立即释放这些空间。执行一次移除后，必须先恢复该次操作，才能再次导入或移除；连续导入仍然允许，并可逐次恢复。恢复需要原来的 iPod 和电脑上保存的操作历史。详见 [ADR-0177](docs/adr/0177-classic-drop-recoverable-track-removal.md)。

## 运行要求

- macOS 12.3 或更高版本；
- 开发构建使用 Python 3.12；
- 已挂载且可通过文件系统访问的 Apple iPod Classic；
- 开发工作流使用 `uv`；
- 导入需要转换的音频格式时，`PATH` 中须有 `ffmpeg` 和 `ffprobe`。

原生应用会在连接后自动挂载受支持的 iPod Classic 卷，无需先在 Finder 中打开设备。
不要同时运行其他正在写入 iPod 数据库的应用；请一次只使用一个管理工具，并在断开连接前安全弹出设备。

## 安装开发版本

```shell
git clone https://github.com/zorroforever/classic-drop.git
cd classic-drop
uv sync --locked
```

当前主要通过源代码分发，尚未发布经过签名和公证的正式安装包。

## 构建 macOS 应用

液态玻璃新 UI 使用 SwiftUI，开发构建内置无界面的 Python helper。
请使用以下命令构建并启动原生应用：

```shell
uv run python scripts/build_classic_drop_native.py
open "dist/native/Classic Drop.app"
```

构建选项、协议和待完成的硬件验证见[原生应用文档](docs/classic-drop-native.md)。
`uv run classic-drop` 以及下面的打包命令仍启动保留用于对照的 Qt 界面：

```shell
uv sync --locked
uv run pyinstaller --clean --noconfirm packaging/classic-drop.spec
open "dist/Classic Drop.app"
```

在当前开发机器上构建会生成 Apple Silicon 版本。打包时会包含工具栏和专辑占位图所需的 SVG 图标资源。

## 常用流程

1. 连接 iPod；原生应用会自动发现并挂载受支持的卷。
2. 打开 Classic Drop；如果没有列出设备，点击 **Refresh（刷新）**。
3. 选择 iPod。**iPod Library（iPod 曲库）** 工作区以只读方式展示曲库，可在列表或专辑视图中搜索；通过侧栏切换工作区。
4. 打开 **To Import（待导入）**，添加文件或文件夹，检查识别出的元数据和封面。
5. 保持不需要导入或重复的曲目未勾选，然后明确点击 **Import Selected（导入所选）**。
6. 等待验证完成，再通过应用的弹出操作安全移除设备。

设备发现、选择、曲库浏览、搜索和专辑浏览均不会执行实际写入。只有提交操作才会将新音乐写入 iPod。

## 开发指南

项目采用 `src/` 目录布局和锁定依赖的 `uv` 环境。

```shell
uv sync --locked
uv run pytest -q tests/classic_drop tests/iOpenPod/GUI/presentation/test_icons.py
uv run ruff check src/classic_drop tests/classic_drop packaging/classic-drop.spec
uv run mypy src/classic_drop
```

Classic Drop 的主要实现模块：

- `src/classic_drop/engine.py`：增量导入与恢复流程协调；
- `src/classic_drop/worker.py`：串行执行设备与媒体操作；
- `src/classic_drop/window.py`：Qt 应用窗口及导入、曲库工作流；
- `src/classic_drop/albums.py`：专辑分组、封面卡片与专辑展示；
- `src/classic_drop/removal.py`、`removal_view.py` 和 `removal_review.py`：音乐筛选、移除选择与确认；
- `src/classic_drop/shell.py`、`library_view.py`、`import_view.py` 和 `presentation.py`：工作区框架、各视图组件及共享的系统配色呈现；
- `tests/classic_drop/`：引擎、媒体、后台工作线程和界面回归测试。

底层 iPod 数据库与存储代码来自本仓库中的 iOpenPod 项目。更多背景见 [`CLASSIC_DROP.md`](CLASSIC_DROP.md)、[`docs/adr/`](docs/adr/) 中的架构决策记录及上游致谢。

## 设备安全

在真实硬件上测试前：

1. 完整备份 iPod 的所有内容；
2. 确认 macOS 能正常挂载和弹出 iPod；
3. 关闭 Finder/iTunes 等可能写入同一数据库的管理工具；
4. 先少量导入，在 iPod 上验证后再进行批量导入；
5. 保持设备连接，直到 Classic Drop 报告操作完成或提供恢复入口。

Classic Drop 不保证能够修复已损坏或被其他程序同时修改的数据库。恢复记录可以改善故障后的处理，但不能代替备份。

## 项目状态

Classic Drop 目前处于 Alpha 阶段，主要围绕真实硬件场景开发。当前已知可用的配置为：改装 SSD 的 A1238 iPod Classic、Apple 原厂固件、可读的 iTunes 数据库以及 macOS 电脑。更多 iPod 代际、Intel macOS 构建、发布签名和更广泛的硬件测试样本仍需验证。

提交问题报告时，请包含：

- iPod 型号及固件信息；
- 是否更换过存储设备；
- macOS 版本与 CPU 架构；
- Finder 是否挂载了 iPod，以及是否启用了磁盘使用模式；
- 具体操作步骤及可见的错误信息；
- **More → Show backups and logs（更多 → 显示备份和日志）** 中的相关日志。

公开日志前，请移除个人音乐路径和设备序列号。

## 许可证与致谢

Classic Drop 采用 [GNU General Public License v3.0 或更高版本](LICENSE)，复用 iOpenPod 2.0.15 的数据库、存储及应用组件。项目归属和第三方许可证信息见 [`ACKNOWLEDGEMENTS.md`](ACKNOWLEDGEMENTS.md)、[`COPYING.md`](COPYING.md) 和 [`packaging/third-party/`](packaging/third-party/)。

## 路线图

- 发布经过签名和公证的 macOS 构建产物；
- 扩大 A1238 和 iPod Classic 的测试样本覆盖；
- 改善设备剩余空间不足时的导入预览；
- 提供更丰富的发布信息和可选的在线封面查询。
