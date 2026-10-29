# Classic Drop 公开开发交接

本目录是从 `.scratch/classic-drop-roadmap/` 迁移出来的公开规划与 UI 设计资料，供其他电脑继续开发。`.scratch` 仍是本机工作记录，不纳入版本库。

## 入口

- [产品路线图](roadmap.md)：批量删除、导入查重、多语言、容量与发布验证的范围、顺序和验收目标。
- [macOS UI 设计](ui-design.md)：窗口信息架构、交互规则、无障碍、三语布局和视觉验收要求。
- [开发清单](development.md)：当前开发顺序、已完成的本机验证、未完成门禁和后续任务。
- [静态视觉稿](ui-concept.svg) / [PNG 预览](ui-concept.png)：设计示意，不是运行截图。

## 异地接续

当前公开文档提交基于分支 `codex/classic-drop-development` 的 `e359c16`（多语言需求测试草案）。在新电脑上执行：

```powershell
git switch codex/classic-drop-development
git pull --ff-only
```

本次交接提交只包含 `docs/` 下的规划、设计和视觉资产。多语言实现已经在原电脑工作区完成一版，但仍未提交，因此新克隆不会包含 `src/classic_drop/i18n.py`、翻译目录及相关代码改动；要继续该实现，应从原电脑另行提交/推送代码，或按开发清单重新实现。

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
