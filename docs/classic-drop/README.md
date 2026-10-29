# Classic Drop 公开开发交接

本目录是从 `.scratch/classic-drop-roadmap/` 迁移出来的公开规划与 UI 设计资料，供其他电脑继续开发。`.scratch` 仍是本机工作记录，不纳入版本库。

## 入口

- [产品路线图](roadmap.md)：批量删除、导入查重、多语言、容量与发布验证的范围、顺序和验收目标。
- [macOS UI 设计](ui-design.md)：窗口信息架构、交互规则、无障碍、三语布局和视觉验收要求。
- [开发清单](development.md)：当前开发顺序、已完成的本机验证、未完成门禁和后续任务。
- [静态视觉稿](ui-concept.svg) / [PNG 预览](ui-concept.png)：设计示意，不是运行截图。

## 异地接续

多语言实现已随 `96e9b13` 合入 `main`，不再需要从原电脑找回未提交代码。新电脑可从公开主分支接续：

```powershell
git switch main
git pull --ff-only
```

2026-10-29 的 macOS UI 外壳实现仍在当前开发工作区，是否可在新克隆取得应以 Git 提交为准；已完成项、实际验证范围与平台验收缺口见开发清单。

## 建议顺序

1. 先阅读路线图的产品边界、删除恢复约束和 ADR 要求。
2. 阅读开发清单，确认多语言本机实现的提交状态与未完成验证。
3. 获取多语言代码提交后，运行其定向测试，再进入 macOS UI 阶段。
4. 按路线图顺序推进导入查重、删除包、可恢复删除和发布验证；每个行为变更补测试和必要 ADR。

仓库要求的常用检查命令见根目录 `AGENTS.md` 与项目说明；文档变更可先运行：

```powershell
uv run rumdl check docs/README.md docs/classic-drop
git diff --check
```
