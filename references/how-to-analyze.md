# How to Analyze a Skill's Dependencies

Use this when producing a manifest.json for a new (unknown) skill. Goal: read the skill's source, classify its dependencies into the five manifest categories, and produce a manifest the user confirms.

This is methodology (you read + reason), NOT a script. Scripts can't reliably distinguish "this import is real" from "this import is example code", and can't judge whether an exe download URL is stable. You can.

---

## Step 1: Find dependency declarations, in priority order

Read these sources in order; later ones fill gaps the earlier miss:

1. **`setup.sh` / `setup.py`** — official skills' canonical declaration (e.g. docx/pdf skills). Highest authority.
2. **`requirements.txt` / `pyproject.toml`** — common in open-source skills.
3. **`SKILL.md` "Dependencies" section** — documentation-level declaration.
4. **`scripts/*.py` imports** — ground truth: what code actually uses.
5. **`references/*.md` require/import statements** — **ZCODE-SPECIFIC, do not skip.** These markdown files contain example code the model will reproduce when generating documents. Their imports ARE real dependencies (e.g. docx skill's `references/chart-templates.md` has `import matplotlib` — matplotlib must be in the manifest).

## Step 2: Classify into the five manifest categories

- **`pip`**: Python `import X` where X is a third-party package (not stdlib). Map import name to pip name when they differ (`PIL` → `Pillow`, `fitz` → `PyMuPDF`, `docx` → `python-docx`).
- **`npm`**: JS `require('X')` where X is not a Node builtin (`fs`, `path`, `child_process`, `module`, `os`, `crypto`, `stream`, `util`, `events`, `http`, `https`...).
  **只列顶层包名**——npm 包的传递依赖由 pack.py 用 `npm install` 整树解析（落盘到 `node_modules/`），
  你**不要**手动展开传递依赖。例如 docx skill 的 npm 只列 `docx`、`image-size`，
  docx 的依赖（hash.js/jszip/nanoid/xml/xml-js 等）pack.py 自动拉。内网用拷贝 + NODE_PATH，零 npm。
- **`playwright`**: present if `setup.sh` runs `playwright install`, OR `require('playwright')` / `require('playwright-core')` appears. List browsers (usually `["chromium"]`) and the playwright version if pinned.
- **`tools.auto`**: external executables with a stable download URL (GitHub Releases pattern: `https://github.com/.../releases/download/{version}/...`). You must be able to write a `url_template` with `{version}` that resolves.
- **`tools.manual`**: large installers or unstable sources (see Step 3).

## Step 3: Decide `manual` vs `auto` — three rules

Mark a tool `manual` if ANY of:
- **Size > ~200MB or requires an MSI installer** (LibreOffice, large suites). The bundle shouldn't auto-download these.
- **Download needs login/redirect/manual version selection** (some vendor sites).
- **You're unsure the URL is stable.** When in doubt, manual. A manual tool that fails is a soft warning; a broken auto URL is a hard failure.

Otherwise `auto`, with `url_template` + `version` + `extract_root`.

## Step 4: Decide pip version pinning

- **Default: omit `version`** — let pip's resolver pick one that installs on the target. Skill code usually just does `import X`; pinning risks an untested version.
- **Pin with `==`** ONLY when the skill's setup.sh/requirements explicitly require a version.
- **Range (`>=1.0`)** when you want a floor but not a ceiling.
- Unsure → omit.

## Step 5: Produce the manifest and confirm with the user

1. Copy `templates/manifest.template.json`.
2. Fill `skill_name`, `skill_source` (path to the skill dir on THIS machine), `target` (win/amd64/node 20 是固定的，但 **python 版本必须问清内网实际版本**——3.12 和 3.13 的 wheel 互不兼容，写错版本打包出来的 bundle 内网装不上), and the `deps` you classified.
3. Show the draft to the user. Ask them to confirm, especially:
   - **`target.python` 是否等于内网 Python 版本？**（必问。`python --version` 或 `sys.version` 确认。
     cp312 wheel 装不进 3.13，cp313 wheel 装不进 3.12。版本不符 = 全部失败。）
   - Are all real dependencies caught? (show them your Step-1 source list)
   - Are the manual tools acceptable as manual?
4. On confirmation, run `python pack.py add <skill-dir> --manifest <the-manifest>`.

---

## Analyzing an MCP server (pack.py mcp)

MCP server 走独立的 manifest（`templates/mcp.template.json`）和 `pack.py mcp` 子命令。
分析一个新 MCP server 时按此分类：

**Step M1: 判 transport——服务在内网跑着吗？**

- **目标服务自带 MCP**（如 NocoDB ≥0.265.0 内置）或内网已部署 HTTP MCP 服务
  → `transport: "http"`。**零文件打包**，只登记 url + headers。
- **独立 npm 包、stdio 启动**（`npx -y xxx` 形态）→ `transport: "stdio-npm"`，
  pack.py 会整树下载到 `bundle/mcp/<name>/`（独立子树，非共享池——ESM 不走 NODE_PATH，
  见 gotchas E1）。
- Python 版 MCP server（uvx/pip 形态）目前**未支持**（可先 `pip download` 进 wheelhouse
  手动处理，后续再扩展 stdio-pip transport）。

**Step M2: 查包的可用性（联网机可查）**

- npm 上有正式包？`registry.npmjs.org/<name>/latest` 看 `bin`（入口）、`dependencies`
  （越少越好打包）、`engines.node`（对照内网 node 版本）、`type`（module=ESM）。
- `bin` 有多个入口（如 `nocodb-mcp` + `nocodb-mcp-http`）时，用 server 级 `"bin"` 字段选。

**Step M3: 区分"打包机可知"与"内网才知"的值**

- 打包机可知：npm 包名、公有 url、非敏感默认值 → 直接写进 manifest。
- **内网才知：主机地址、端口、token、tokenId → 一律写 `ask:VAR_NAME` 占位符**
  （可嵌在 url 子串里），安装时 `_merge_mcp.py` 提示填入（gotchas E3/E4）。
  判断标准：这个值在内网 GUI 里创建/取决于内网拓扑 → ask:。

**Step M4: 版本兼容性问清用户**

- server 对**后端服务版本**的要求（如 nocodb-mcp 要 NocoDB ≥2026.04 的 v3 API）；
- engines.node 对照内网 Node 大版本。

**Step M5: 产出 MCP manifest 并确认**

复制 `templates/mcp.template.json`，按上面分类填 servers；向用户展示并确认 ask: 清单和
版本要求后跑 `python pack.py mcp --manifest <file>`。

## Anti-patterns

- **Don't** run a regex over imports and dump them all into pip. Classify by hand — stdlib modules and example-only imports need judgment.
- **Don't** invent a `url_template` you haven't seen resolve. If unsure, mark manual.
- **Don't** pin pip versions speculatively. Omit unless required.
- **Don't** forget `references/*.md`. This is the #1 way zcode skills leak un-declared deps.
- **Don't** guess `target.python`. 必须向用户确认内网 Python 版本——cp312/cp313 wheel 互斥，
  版本不符打包出的 bundle 内网一个 C 扩展包都装不上（numpy/matplotlib/lxml 全废）。
- **Don't** manually expand npm transitive deps into `deps.npm`. 只列顶层包名，传递依赖
  pack.py 用 `npm install` 整树解析。手动列既易漏又会让 install 逻辑混乱。
- **Don't** write `npx -y <pkg>` into any generated MCP config——离线内网没有 registry，
  npx 会当场联网失败。stdio 一律 `command: "node"` + 绝对路径入口（pack.py 已如此渲染）。
- **Don't** bake 内网才有的值（token、内网主机地址）进 manifest——用 `ask:VAR` 占位符。
