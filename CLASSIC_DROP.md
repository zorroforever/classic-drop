# Classic Drop

Classic Drop 是 macOS 上面向 Apple 原厂固件 iPod Classic 的增量导入工具。它读取现有的 `iTunesDB` 和 `ArtworkDB`，只把新选择的音乐追加到曲库，保留旧歌曲、播放历史、播放列表和未知数据库数据。每次导入都有可恢复记录，导入中断时可从界面恢复上一次曲库。

## 使用

开发环境中运行：

```shell
uv sync --locked
uv run classic-drop
```

打包 macOS 应用：

```shell
uv run pyinstaller --clean --noconfirm packaging/classic-drop.spec
open "dist/Classic Drop.app"
```

应用数据、日志和主机侧恢复记录位于 `~/Library/Application Support/Classic Drop`。转码需要系统可以找到 `ffmpeg` 和 `ffprobe`；兼容格式会直接复制，不会为了导入而重编码。应用只接受识别为 iPod Classic 且曲库可读的设备，Rockbox 不在范围内。

界面支持 English、简体中文和日本語，可通过右上角菜单切换；语言偏好保存在 Classic Drop 的应用设置中。标题、按钮、操作状态和数量会随语言切换更新，用户编辑的曲目信息和文件路径保持原样。

封面优先使用文件内嵌图片，也会查找同目录的 `cover`、`folder` 或 `front` JPG/PNG。导入前可以逐曲修改标题、艺人、专辑、碟号、曲号和封面。疑似重复歌曲默认不勾选。

连接设备后，首个“iPod 曲库”标签会显示原厂固件当前已读取的歌曲，可按标题、艺人或专辑搜索。该列表是只读的；“待导入”标签独立管理本次要追加的文件。导入或恢复完成后曲库列表会自动重新读取。

曲库支持“列表”和“专辑”两种视图。专辑视图按专辑艺人和专辑归组，以封面卡片展示；双击专辑可查看封面、年代、曲数和歌曲列表。封面从 iPod 的 ArtworkDB 按需读取，读取不到时显示占位图，不影响曲库浏览。

## 验证和限制

虚拟 iPod fixture 已覆盖追加写入、HASH58 签名、ArtworkDB RGB565 缩略图、源文件变更拒绝、取消和恢复流程。真实 A1238 SSD 设备仍需在用户自己的备份和可恢复条件下验证；请先安全弹出并确认 iPod 菜单能正常读取曲库。

本工具复用 iOpenPod 2.0.15 的 GPL-3.0-or-later 代码和数据库实现，相关许可证见仓库根目录与 `LICENSES/`。
