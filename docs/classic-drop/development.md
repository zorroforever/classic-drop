# Classic Drop 开发清单与首阶段实施计划

Status: active-handoff

日期：2026-10-28。用户已要求从规划进入开发。执行范围为 Classic Drop；原 PRD 中“仅规划”的历史记录保留，本文件记录后续授权和实际进度。

> 执行方式：使用 writing-plans 和 executing-plans，在当前会话按任务串行推进；完成主要功能后使用 requesting-code-review 做独立审查。本文件与路线图属于公开开发文档，随代码一起维护。

**Goal:** 整理全部待开发内容，并交付第一个可验证的中日英多语言增量，为后续 macOS UI、查重与删除工作区提供基础。

**Architecture:** 保留现有 Classic Drop → iOpenPod / iPodDB / Storage 依赖方向；语言属于表示层，工作流使用语言无关的消息模板。采用 Qt QTranslator 和独立 Classic Drop catalogs；重译不重建导入状态、不重新发起设备操作。

**Tech Stack:** Python 3.12、UV 锁定环境、PySide6、Qt Linguist、Ruff、Mypy、Pytest、Rumdl。

**Spec:** [路线图](roadmap.md) 与 [UI 设计](ui-design.md)（尤其多语言章节）。

## 2026-10-29 进度更新

多语言基础已随 `96e9b13` 合入。当前工作区已实现第二阶段 macOS UI 的基础外壳：来源列表侧栏、原生 `QToolBar`、可折叠检查器及独立恢复入口；窗口构建已拆为 `shell.py`、`library_view.py`、`import_view.py` 与 `presentation.py`。保留现有引擎和 worker 的设备权限、追加导入与恢复契约；本轮实现尚未提交。

当前外壳采用 Qt 原生平台样式和系统语义调色板，启动不再强制 Fusion；不透明内容表面是这一增量的明确实现范围，不宣称实现 Liquid Glass 或 AppKit 材料一致性。940×580 时默认折叠检查器，用户可重新打开，提交与取消仍在独立底栏。曲库默认四列，表头菜单可展开其他列；排序保持 Track、筛选与检查器关联。音乐删除现已支持六维筛选、累积清单、影响复核、Storage 设备端恢复及上次曲库变更恢复；原生实机验收仍待完成。

本机定向回归 80 项通过，包含侧栏切换保留编辑、英中日重译、空状态、调色板图标、最小窗口、曲库排序及检查器、恢复可用性、快捷键可用性与取消关闭。Ruff 格式/lint、Classic Drop 源码及新增测试的定向 Mypy 和锁文件检查通过。36 张实际 Qt 控件渲染覆盖三语、浅深色、两种窗口尺寸和三个工作区，使用明确标记的合成曲目，未连接真实 iPod。

上述图片由 offscreen 后端的 Fusion 回退样式生成，证明布局和状态，不证明原生 macOS 材料。原生 macOS 样式不适用于 offscreen 后端；原生窗口、Retina、VoiceOver、系统辅助功能、macOS 12.3 与实机 iPod 仍需分别验收。独立代码审查及修复已完成，最终打包与检查限制见末尾执行记录。

## 全局约束

- 保持 macOS 12.3 最低系统声明；最新系统真实材料和硬件兼容需 Mac 实机验证，Windows 测试不替代实机验收。
- 不扩大到整个 iOpenPod 产品，不引入新依赖，不改变 CI、根配置或公共 schema。
- 只通过 Storage 写设备；开发测试使用虚拟设备，不对真实 iPod 执行操作。
- 保留歌曲、路径、设备标识、原始诊断等用户数据原文。
- 在独立本地开发分支 codex/classic-drop-development 工作；本次提交公开规划与设计资料，功能实现是否已发布以 Git 历史为准。
- 现有 window.py / engine.py 已超过行数限制；首增量不做大规模重构，新模块按职责控制规模，后续 UI 阶段有独立拆分任务。

## 全部待开发项与顺序

| 顺序 | 工作项 | 具体交付 | 当前状态 |
| --- | --- | --- | --- |
| 1 | 中日英多语言 | 独立翻译目录、系统默认/手动选择、运行时重译、状态保留、离线打包 | 已合入 `96e9b13`；原生平台验收仍需补齐 |
| 2 | macOS UI 与窗口职责拆分 | 侧栏/统一工具栏/检查器、语义配色、原生平台样式、浅深色/辅助功能、旧系统回退 | 当前工作区已实现不透明 Qt 外壳；平台和辅助功能验收待完成 |
| 3 | 导入查重增强 | 队列内/曲库匹配、精确/历史/疑似分层、匹配依据、人工覆盖、复核及选择保留 | 当前增量已实现；仍需扩展边界回归与独立审查 |
| 4 | 六维筛选和删除包 | AND/OR 条件、多选/全匹配加入、去重、移出/清空、设备/快照绑定、最终复核 | 已实现；需继续扩展故障注入和实机验收 |
| 5 | 可恢复删除与恢复入口 | 新 ADR、设备端保留、事务验证、中断/重连、共享媒体、末次写入顺序 | 已实现并由 ADR-0177 记录；需继续扩展故障注入和实机验收 |
| 6 | 容量预估与故障反馈 | 媒体/转码/数据库/临时空间估算，状态未知/需恢复反馈 | 待开发 |
| 7 | Classic Drop 发布与实机验证 | 产品文档边界、独立安装包、资源、签名/公证、机型/架构验证表 | 待开发；CI/发布前单独确认 |

在线封面和音频指纹未确认，不纳入执行范围。现有导入保留 Host Recovery；音乐移除按 ADR-0177 使用独立的设备端事务恢复策略。

## 2026-10-29 查重增强进度

当前工作区已实现导入查重的第一批增量：

- 队列状态跨多轮追加保留；同一原始 SHA-256 的不同路径标为“已确认重复”，默认取消勾选。
- 对当前 iPod 曲库建立标题/艺人索引，再用时长阈值寻找候选；历史收据只作为候选提示，不再直接证明设备仍有相同内容。
- 候选设备文件通过只读 Storage Session 指纹校验；内容一致才标为“已确认重复”。收据存在但设备内容已变化时标为“历史记录匹配”；无法完成候选读取时标为“检查未完成”；元数据候选但内容不一致时标为“疑似重复”。
- 导入队列增加状态筛选。重复、历史匹配、疑似匹配和未完成检查可以通过复核对话框显式继续导入，用户的勾选不会因筛选或追加文件被静默重置；状态说明保留匹配对象和判断依据。
- 中日英 catalog 已补齐新增状态和复核提示；没有引入在线识别或音频指纹，也没有修改设备写入边界。

本增量的定向回归覆盖队列内重复、跨批次追加、设备内容核验、收据失效、状态筛选和显式覆盖。当前工作区已实现并覆盖可恢复音乐移除、筛选组合、累积清单、设备/来源失效和重启恢复；容量预估、更多事务故障注入和真实设备验收仍未完成。

## 首阶段任务清单

- [x] 阅读当前规格、启动入口、窗口、上游翻译维护规范和测试；确认工作区基线与分支。
- [x] 准备锁定环境，运行现有 Classic Drop 定向基线。
- [x] 先增加语言选择、catalog、占位符和热切换保留队列的失败测试。
- [x] 实现独立语言管理、两份翻译源/编译目录，接入菜单选择与窗口重译。
- [x] 迁移可见静态/动态提示与应用错误模板，保留诊断参数原文；打包目录资源。
- [x] 完成定向测试、静态检查、独立代码审查与必要修复，并记录证据；全仓检查未通过项见执行记录。
- [x] 汇报首阶段结果及仍待开发项，不把多语言交付等同于整条路线完成。

## 第二阶段任务清单：macOS UI 基础外壳

- [x] 采用系统平台样式和语义调色板，移除启动时强制 Fusion，补齐可翻译空状态。
- [x] 实现来源列表侧栏、统一工具栏、三个现有能力工作区和可折叠检查器，保留底栏进度与取消。
- [x] 拆分窗口构建模块，保持引擎与 worker 契约；曲库排序、筛选与检查器关联同一 Track。
- [x] 覆盖切换工作区/语言后的状态保留、最小窗口、快捷键和取消安全关闭；更新三语 catalogs。
- [x] 完成 36 张 Qt 控件布局渲染、定向回归、静态检查、独立审查和 Apple Silicon 本地打包。
- [ ] 验收原生 macOS 窗口、Retina、VoiceOver、系统辅助功能及 macOS 12.3；确认目标材料表现。
- [ ] 完成真实 iPod 回归与正式签名/公证；这些不属于本轮基础外壳交付。

## Task 1：语言管理与 catalog

**Files:** 新增 src/classic_drop/i18n.py、src/classic_drop/translations/classic_drop_zh_CN.ts / .qm、classic_drop_ja_JP.ts / .qm；新增 tests/classic_drop/test_i18n.py。

**Interfaces:** resolve_language(preferences: Sequence[str]) -> str；LanguageManager(application, directory=None)；language / locale / set_language() / languageChanged；tr(source, *, n=-1) 与 render_text(source)；设置隔离到 Classic Drop 主机目录。

先测试 zh-Hans、zh_CN、ja-JP、en-US、繁中、不支持语言及首选列表顺序；测试加载编译目录后查找和变量替换。英语为源文案，简中/日语 catalog 无未完结条目。

命令：uv run pytest tests/classic_drop/test_i18n.py -q。先验证失败，再实现；编译使用 uv run pyside6-lrelease，沿用现有锁定工具。

## Task 2：接入并保留交互状态

**Files:** 修改 src/classic_drop/**main**.py、window.py、albums.py；新增 src/classic_drop/window_text.py；扩展 test_i18n.py 和按语言调整现有 test_window.py 的文案断言。

静态控件重译和动态文案集中到 window_text.py；窗口刷新仅重绘已有状态，不重新运行 _build、show_entries、设备刷新或事务。语言菜单使用原生自称，选择持久化。Qt 采用系统支持的应用语言，系统拥有的权限提示不承诺热切换。

关键测试草案：添加两项 PreviewEntry，改标题与勾选，切换 ja_JP，断言表头变为日语，edited_entries() 与切换前相同，选择行/进度/设备保持不变；切换英语再验证动态标签与菜单。

## Task 3：工作流消息和分发资源

**Files:** 修改 src/classic_drop/engine.py、media.py、worker.py、packaging/classic-drop.spec；必要时新增本地目录维护脚本；新增/更新对应 tests/classic_drop 测试。

工作流继续输出语言无关模板和参数，表示层翻译后格式化，避免 worker 提前翻译后无法热切换。已知应用提示可翻译；第三方原始异常与用户路径作为参数保留。catalog、Qt 翻译目录随 app 离线携带，不改公共接口或第三方依赖。

## Task 4：质量门禁

运行首阶段定向测试后执行仓库要求的 uv lock --check、uv run ruff format --check .、uv run ruff check .、uv run rumdl check .、uv run mypy、uv run pytest；记录退出码及已有基线问题。若全量检查不可用，说明实际原因，不声称验证通过。独立 reviewer 只审本次增量；真实 macOS、VoiceOver、签名安装包和 iPod 硬件留到具备环境时验证。

## 执行记录

- 已建立 codex/classic-drop-development 分支；起点跟踪文件干净。
- 已启动 uv sync --locked，为本机创建 Python 3.12 锁定环境；未编辑 pyproject.toml 或 uv.lock。
- 本机已接入 Classic Drop 独立中日英目录、语言菜单与偏好、界面动态重译、后台消息模板、Qt 和 macOS 权限文案资源；这些功能代码当前仍是未提交工作区变更，不在本次文档提交中。真实 Mac bundle、VoiceOver 和原生外观仍待验证。
- 本机多语言定向测试 26 项通过；Classic Drop 回归 55 项通过、1 项因 Windows 缺少创建符号链接权限而排除。验证结果对应未提交的本机实现，换电脑后需先取得该代码提交或重新实现。
- uv lock --check、全仓 Ruff、相关文件 Mypy、修改文档 Rumdl 均通过。全仓 Rumdl 因已有 podcast 文档链接到缺失的 .scratch 文件失败；全仓 Mypy 仍有既有 Classic Drop 测试类型错误。
- 全仓 pytest 曾运行至 7063 passed、34 failed、3 errors、121 skipped；未达到全量通过。上游德语/西语 catalog 测试单独复现 pyside6-lupdate 进程异常退出；其余失败未逐项定位。Windows 符号链接权限失败在本轮开发前的基线中已存在。
- 已自行检查代码与打包资源；独立 review 尚未执行。Task 2 原计划中的 `__main__.py` / `window_text.py` 文件名是规划示例，实际实现以当前代码结构和后续提交为准。

### 2026-10-29 macOS UI 验证记录

- 本节更新上述历史记录：多语言已合入 `96e9b13`；UI 实现在当前 `classic-drop` 分支工作区，未提交或推送。
- `uv run pytest -q tests/classic_drop tests/iOpenPod/GUI/presentation/test_icons.py`：80 passed。另以不同文件顺序运行窗口、语言和调色板回归：58 passed，验证设置隔离。
- `uv lock --check`、`uv run ruff format --check .`（1091 files）、`uv run ruff check .` 通过；`uv run mypy src/classic_drop tests/classic_drop/test_shell.py tests/classic_drop/test_palette.py tests/classic_drop/conftest.py` 检查 16 个源文件通过。
- 修改文档的定向 Rumdl 与 `git diff --check` 通过。全仓 Mypy 仍报五个原有测试文件中的 98 个类型错误；全仓 Rumdl 仍因 `docs/research/podcast-authoring-comparison-notes.md` 的两条缺失私有文件链接失败。本轮未运行全仓 Pytest，不声明全仓通过。
- 独立审查后修复两处调色板问题：专辑选中态元数据使用 HighlightedText，已打开的专辑占位封面随调色板刷新而不重置状态。审查范围内无未解决的产品问题。
- `uv run pyinstaller --clean --noconfirm packaging/classic-drop.spec` 退出码 0，生成 `dist/Classic Drop.app`（arm64）。`codesign --verify --deep --strict --verbose=2` 通过；这是本地 ad-hoc 签名，未进行 Developer ID 签名或公证。
- 三语 × 浅深色 × 两种尺寸 × 三个工作区的 36 张布局渲染保存在忽略目录 `.scratch/classic-drop-ui-verification/`。原生 GUI 检查工具因本机运行时配置错误不可用；不以 offscreen 图片替代原生窗口、辅助功能或硬件验收。

### 2026-10-29 删除安全与最终复核修复

- 删除已提交但本地恢复索引写入失败时，待恢复事务现在阻止导入、再次删除和设备重选，避免覆盖恢复所依赖的曲库。恢复完成后才解除限制。恢复与清理已完成、仅重新加载失败的明确终态会移除旧恢复路径，保留警告并允许重新选择设备；仍有其他待恢复事务时保留其新路径。已索引恢复在清理完成后收到最终刷盘警告时，注销该恢复记录并撤销旧曲库会话，保留安全弹出提示。
- 删除流程改为后台只读准备 Library Review，再展示最终确认。确认后仅提交原先展示的 Review，不重新准备；过期或替换的 Review、变化的删除包或来源不能直接提交。准备期间禁止编辑删除包。
- 最终窗口显示完整可滚动的曲目清单、加入来源、受影响播放列表及独立恢复媒体大小。播放列表数量较多时单独滚动；提示明确说明从整个曲库及所有播放列表移除、原件保留在 iPod、不会立即释放空间。默认操作为取消，普通 Return 不授权删除；中日英目录已更新并编译。
- 新增回归先验证失败再修复，覆盖本地索引失败后的写入阻塞、恢复后继续导入、只读准备、提交已审阅 Review、过期 Review、确认取消、来源变化、长清单、三语提示和恢复完成后的重新加载或刷盘警告。最终代码的 Classic Drop、相关 Library 服务及 Sync 恢复检测定向回归共 179 项通过。
- 全仓 Ruff 格式、lint、锁文件和差异空白检查通过；源码及两份修改/新增测试的定向 Mypy 检查 20 个文件通过，使用 `--follow-imports=silent` 隔离既有测试问题。全仓 Mypy 仍有六份未修改的 Classic Drop 测试中的 120 个错误；全仓 Rumdl 仍有两条既有缺失私有文件链接。全仓 Pytest 运行得到 7125 passed、32 failed、128 skipped、63 errors，失败标识均位于本轮未修改的 iOpenPod 或 Storage 测试；该运行早于最后一轮审查修复，最终代码另由上述 179 项定向回归验证，不宣称全仓通过。完整失败标识及检查范围保存在忽略目录 `.scratch/removal-fixes-validation.md`。
- 独立审查提出的恢复终态阻塞和播放列表溢出问题均补充失败回归并修复。三语与播放列表溢出的实际 Qt 控件渲染位于忽略目录 `.scratch/removal-review-layouts/`；没有执行真实 iPod 写入或原生 macOS 实机验收，也未进行发布。
