---
name: offline-bundle-skill
description: 当用户提到"离线准备/离线打包/内网部署 zcode skill 的依赖"，或要把某个 skill 的依赖弄到无网络环境使用，或需要在不联网的机器上安装 skill 及其依赖时使用本 skill。覆盖场景：为 docx/pdf/Excel/PPT 等文档 skill 或任何开源 zcode skill 准备离线安装包；在内网机离线安装这些 skill。
---

# offline-bundle-skill

为 zcode skill 离线准备依赖 + skill 本体。清单（manifest）是产品，pack.py/install.bat 是执行器，AI 分析方法是产线。

## 何时使用

- 用户要把某个 skill 部署到无网络的内网
- 用户要"离线打包 / 离线准备依赖"
- 新接入一个开源 skill，需要它的依赖清单

## 整体流程

```
联网机                          内网机
  │                               │
  ├─ AI 分析 skill → manifest     │
  ├─ python pack.py add ...        │
  │     ↓ 产出 offline-bundle/    │
  │           含 wheelhouse/       │ ──拷贝──►
  │           skills/ install.bat  │           install.bat → ~/.agents/skills/
```

## 命令速查

**打包（联网机）：**
```cmd
python "%~dp0scripts\pack.py" add <skill-dir> --manifest <manifest.json> [--target "py:3.12,os:win,arch:amd64,node:20"] [--bundle <bundle-dir>]
```

**安装（内网机）：**
```cmd
install.bat --bundle <bundle-dir> [--dry-run] [--skill <name>]
```

## 工作流（详见 references/）

1. **接入新 skill**：AI 读 `references/how-to-analyze.md` 分析依赖 → 产出 manifest → 你确认 → 跑 pack.py add
2. **追加新 skill（增量）**：pack.py 累加进同一个 bundle → 内网 robocopy /MIR → install.bat
3. **补缺包**：改 manifest → 重跑 pack.py（去重只补缺）→ robocopy → install.bat 重跑

## 关键概念

- **manifest.json**：一 skill 一清单，唯一输入。schema 见 `templates/manifest.template.json`。
- **target 环境**：manifest 强制记录，pack.py 据此交叉下载。优先级：`--target` > manifest.target > 探测本机。
- **wheelhouse 池**：跨 skill 共享 pip/npm 文件池。
  - pip：`.whl` 文件名天然去重。
  - npm：**整棵依赖树**落盘到 `wheelhouse/npm/node_modules/`（不是裸 tgz）。
    npm 包有传递依赖，裸 tgz 内网 `npm install -g` 会联网失败，所以必须整树安装，
    内网靠"拷 node_modules + NODE_PATH"使用，零 npm 零网络。
- **manual 项**：体大/不稳的 exe（libreoffice），只 warn 不阻断。

详见 `references/how-to-analyze.md`（分析方法）、`references/known-recipes.md`（docx/pdf 现成清单）、
`references/gotchas.md`（**实现陷阱库——修改脚本前必读**）。

## 给维护者：修改脚本前

如果你要改 `pack.py` / `install.bat` / `_check_install.py`，或给本 skill 加功能，
**先读 `references/gotchas.md`**。它记录了开发中真实踩过的 batch 引号/括号陷阱、
pip dry-run 跨版本误判、URL 注释误删等问题。重蹈这些覆辙会浪费大量调试时间。

## 验收状态（开发机）

以下在联网开发机（Python 3.14，为目标 cp313/win_amd64 交叉下载）验证通过：
- `pack.py add docx/pdf` 端到端打包（pip/npm/playwright/tools/skill 本体）
- **npm 整树方案**：docx/image-size/pdf-lib/playwright 连传递依赖落盘到共享
  `node_modules/`（28 包），内网靠"拷贝 + NODE_PATH"使用，不调 npm install
- wheelhouse 跨 skill 去重（reportlab 只 1 份）
- manifest-index 累加（docx + pdf 共存，target=3.13）
- playwright chromium 下载到 pw-browser/
- `install.bat` 真实安装：pip 装、npm node_modules 拷全局、skill 落盘 `~/.agents/skills/`、
  **重装备份用 `move /Y`（ren 会在同名备份已存在时卡死）**
- **内网实跑通过**（Python 3.13.9 + Anaconda）：install.bat 全流程完成，skill 装入

**内网部署要点（target 必须匹配内网 Python 版本）**：
- bundle 的 pip wheel 按 target.python 的 cp 标签下载（cp312 ≠ cp313，装不上就换版本重打）
- 内网跑 `install.bat --dry-run` 先自检；npm 装完**新开终端**让 NODE_PATH 生效
