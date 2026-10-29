# Classic Drop 开发清单与首阶段实施计划

Status: active-handoff

日期：2026-10-28。用户已要求从规划进入开发。执行范围为 Classic Drop；原 PRD 中“仅规划”的历史记录保留，本文件记录后续授权和实际进度。

> 执行方式：使用 writing-plans 和 executing-plans，在当前会话按任务串行推进；完成主要功能后使用 requesting-code-review 做独立审查。本文件与路线图属于公开开发文档，随代码一起维护。

**Goal:** 整理全部待开发内容，并交付第一个可验证的中日英多语言增量，为后续 macOS UI、查重与删除工作区提供基础。

**Architecture:** 保留现有 Classic Drop → iOpenPod / iPodDB / Storage 依赖方向；语言属于表示层，工作流使用语言无关的消息模板。采用 Qt QTranslator 和独立 Classic Drop catalogs；重译不重建导入状态、不重新发起设备操作。

**Tech Stack:** Python 3.12、UV 锁定环境、PySide6、Qt Linguist、Ruff、Mypy、Pytest、Rumdl。

**Spec:** [路线图](roadmap.md) 与 [UI 设计](ui-design.md)（尤其多语言章节）。

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
| 1 | 中日英多语言 | 独立翻译目录、系统默认/手动选择、运行时重译、状态保留、离线打包 | 本机已实现；待独立审查、提交和 macOS 验证 |
| 2 | macOS UI 与窗口职责拆分 | 侧栏/统一工具栏/检查器、语义配色、原生平台样式、浅深色/辅助功能、旧系统回退 | 待开发 |
| 3 | 导入查重增强 | 队列内/曲库匹配、精确/历史/疑似分层、匹配依据、人工覆盖、复核及选择保留 | 待开发 |
| 4 | 六维筛选和删除包 | AND/OR 条件、多选/全匹配加入、去重、移出/清空、设备/快照绑定、最终复核 | 待开发 |
| 5 | 可恢复删除与恢复入口 | 新 ADR、设备端保留、事务验证、中断/重连、共享媒体、末次写入顺序 | 待开发；先验证恢复策略 |
| 6 | 容量预估与故障反馈 | 媒体/转码/数据库/临时空间估算，状态未知/需恢复反馈 | 待开发 |
| 7 | Classic Drop 发布与实机验证 | 产品文档边界、独立安装包、资源、签名/公证、机型/架构验证表 | 待开发；CI/发布前单独确认 |

在线封面和音频指纹未确认，不纳入执行范围。现有导入保留 Host Recovery；删除所需设备端保留策略不得由 UI 假装已经满足。

## 首阶段任务清单

- [x] 阅读当前规格、启动入口、窗口、上游翻译维护规范和测试；确认工作区基线与分支。
- [ ] 准备锁定环境，运行现有 Classic Drop 定向基线。
- [ ] 先增加语言选择、catalog、占位符和热切换保留队列的失败测试。
- [ ] 实现独立语言管理、两份翻译源/编译目录，接入菜单选择与窗口重译。
- [ ] 迁移可见静态/动态提示与应用错误模板，保留诊断参数原文；打包目录资源。
- [ ] 完成定向测试、静态检查、独立代码审查与必要修复，并记录证据。
- [ ] 汇报首阶段结果及仍待开发项，不把多语言交付等同于整条路线完成。

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
