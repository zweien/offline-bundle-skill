# Known Recipes — Ready-Made Manifests

Verified manifests for skills already analyzed. Copy/adapt when adding a similar skill.

---

## docx skill

Source analysis: `setup.sh` declares docx-js + defusedxml + python-docx; `scripts/document.py` imports `defusedxml`; `references/chart-templates.md` imports matplotlib/numpy/PIL/reportlab; `references/*.md` require `docx`, `image-size`.

```json
{
  "skill_name": "docx",
  "skill_source": { "type": "local", "path": "<path-to>/skills/docx" },
  "target": { "python": "3.13", "os": "win", "arch": "amd64", "node": "20" },
  "deps": {
    "pip": [
      { "name": "defusedxml" },
      { "name": "python-docx" },
      { "name": "matplotlib" },
      { "name": "numpy" },
      { "name": "Pillow" },
      { "name": "reportlab" }
    ],
    "npm": [
      { "name": "docx" },
      { "name": "image-size" }
    ],
    "tools": [
      {
        "name": "pandoc",
        "kind": "auto",
        "version": "3.5",
        "url_template": "https://github.com/jgm/pandoc/releases/download/{version}/pandoc-{version}-windows-x86_64.zip",
        "extract_root": "pandoc-{version}"
      },
      {
        "name": "libreoffice",
        "kind": "manual",
        "note": "Download LibreOffice 24.x msi, place in bundle/tools/manual/, install on intranet. Needed for .doc support and docx→PDF."
      }
    ]
  }
}
```

**Notes:**
- pandoc URL verified pattern; adjust `{version}` (e.g. 3.5) to a released tag.
- poppler (pdftoppm) is optional for docx; add as auto-tool if PDF-from-images needed:
  `"url_template": "https://github.com/oschwartz10612/poppler-windows/releases/download/v{version}-0/Release-{version}-0.zip"`

---

## pdf skill

Source analysis: `setup.sh` declares pikepdf/pdfplumber/pypdf/reportlab/PyMuPDF + playwright + Chromium; `scripts/*.js` require playwright/playwright-core/pdf-lib.

```json
{
  "skill_name": "pdf",
  "skill_source": { "type": "local", "path": "<path-to>/skills/pdf" },
  "target": { "python": "3.13", "os": "win", "arch": "amd64", "node": "20" },
  "deps": {
    "pip": [
      { "name": "pikepdf" },
      { "name": "pdfplumber" },
      { "name": "pypdf" },
      { "name": "reportlab" },
      { "name": "PyMuPDF" }
    ],
    "npm": [
      { "name": "playwright" },
      { "name": "pdf-lib" }
    ],
    "playwright": {
      "browsers": ["chromium"],
      "version": "1.48"
    },
    "tools": [
      {
        "name": "libreoffice",
        "kind": "manual",
        "note": "Download LibreOffice msi, place in bundle/tools/manual/. Needed for xlsx/pptx/docx→PDF conversion."
      }
    ]
  }
}
```

**Notes:**
- pdf and docx both depend on reportlab → wheelhouse auto-dedups (Task 12 verifies this).
- playwright npm package + chromium browser go to separate locations (npm/ and pw-browser/).

---

## ppt-master skill

Source analysis: `skills/ppt-master/requirements.txt` declares deps by feature group.
**关键决策**：requirements.txt 含联网类依赖（google-genai 调 AI API、requests/curl_cffi/beautifulsoup4
抓网页、edge-tts 联网 TTS、flask 本地 web 服务），这些**内网无意义，manifest 不收录**。
只收"离线可运行"的核心：PPT 生成 + 文档转换。

```json
{
  "skill_name": "ppt-master",
  "skill_source": { "type": "local", "path": "<path-to>/skills/ppt-master" },
  "target": { "python": "3.13", "os": "win", "arch": "amd64", "node": "20" },
  "deps": {
    "pip": [
      { "name": "python-pptx" },
      { "name": "Pillow" },
      { "name": "numpy" },
      { "name": "svglib" },
      { "name": "reportlab" },
      { "name": "PyMuPDF" },
      { "name": "openpyxl" },
      { "name": "mammoth" },
      { "name": "markdownify" },
      { "name": "ebooklib" },
      { "name": "nbconvert" }
    ],
    "npm": [],
    "tools": []
  }
}
```

**Notes:**
- `reportlab`/`PyMuPDF`/`Pillow`/`numpy` 与 docx/pdf skill 重叠 → wheelhouse 自动去重。
- **已排除的联网类依赖**（内网装上也用不了）：`google-genai`（AI 图片生成）、`requests`/`curl_cffi`/`beautifulsoup4`（网页抓取）、`edge-tts`（联网 TTS）、`flask`（SVG 编辑器，可选）。若未来内网有 AI 大模型可调，再单独补 `google-genai`。
- 这个 skill 体积大（83MB，含 templates 11841 个 SVG 模板 + references 调色板 PNG），是离线部署最重的 skill。

---

## 评估过但暂不接入：minimax-docx（.NET 技术栈）

来自 `github.com/MiniMax-AI/skills`。**决策：暂不接入内网**，原因记录于此，避免重复评估。

**为何是 .NET 而非 Python/Node**：`scripts/dotnet/` 是完整 C# 工程，目标框架 `net8.0`，
NuGet 依赖 `DocumentFormat.OpenXml 3.5.1` + `System.CommandLine 2.0.5`。运行方式是
`dotnet run --project ...Cli -- <command>`（每次编译，需 SDK，非 Runtime），
还有 `run-script task.csx` 模式让 AI 动态写 C# 执行——两者都依赖 SDK 在场。

**离线方案（可行但成本高）**：
1. 联网机 `dotnet restore --packages <nuget-cache>` 抓全 NuGet 包
2. 拷 skill + nuget-cache + **.NET 8 SDK 安装包**（~250MB）进内网
3. 内网装 SDK + `setx NUGET_PACKAGES <nuget-cache>` + `dotnet restore`（命中缓存不联网）

**为何暂不接入**：
- 已有 **docx skill**（Node.js docx-js，已在 bundle 内网可用）覆盖绝大多数 Word 场景
- minimax-docx 的增量价值（OpenXML 级精细排版：复杂模板合并/多节页眉页脚）对当前需求非必需
- .NET SDK 离线成本（装 SDK + NuGet 缓存机制）远高于 pip/npm

**何时回头接入**：真遇到 docx skill 搞不定的复杂 Word 排版需求时，按上面三步方案做。
（顺带：同源的 minimax-pdf / minimax-xlsx 大概率也是 .NET 技术栈，一并按此评估。）

---

## NocoDB MCP（两条路线，二选一或并存）

目标：让内网 zcode 通过 MCP 读写内网 NocoDB。**先调研再选路线**（2026-11 调研结论）：

| | 路线 A：官方内置 | 路线 B：社区 stdio server |
|---|---|---|
| server | NocoDB 本体内置（≥0.265.0，2025-10 发布；账号级 token 需 2026.09.1+） | `nocodb-mcp`（zoyak-tech，v3 API，92 工具） |
| 离线打包 | **零文件**，只生成配置片段 | npm 整树 ~几 MB（仅 2 个运行时依赖） |
| 要求 | 内网 NocoDB 版本 ≥0.265.0（旧 fork 需同步上游） | NocoDB ≥2026.04（v3 API）+ API token |
| 认证 | `x-api-key` header（GUI 创建 MCP token） | `NOCODB_API_TOKEN` env（GUI → Account → Tokens） |
| 功能 | NocoDB 官方决定 | Community 自托管约 40-50/92 工具可用（见下） |
| 客户端配置 | `type: http` + url + headers | `type: stdio` + node 入口 + env |

**路线 A manifest**（`pack.py mcp` 的输入，零下载）：

```json
{
  "servers": [
    {
      "name": "nocodb",
      "transport": "http",
      "url": "http://<内网nocodb主机>:8080/api/v2/mcp/ask:NOCODB_MCP_TOKEN_ID",
      "headers": { "x-api-key": "ask:NOCODB_MCP_TOKEN" },
      "note": "NocoDB >= 0.265.0; token + tokenId 均在内网 GUI 创建 (Base/Account settings -> MCP)"
    }
  ]
}
```

**Notes（路线 A）:**
- 端点 `POST /api/v2/mcp/<mcpTokenId>`，无状态 streamable HTTP，**GET 返回 405 是正常的**。
- 认证 header 用 `x-api-key`（官方为"只能设一个自定义 header 的 MCP 客户端"特意兼容）。
- 自有 fork 若停在 2026-07 之前（如 zweien/nocodb @2026-07-15），mcp 模块是 3 文件旧形态，
  需先同步上游 ≥0.265.0（最好 2026.09.1+）才能用此路线——不想动 fork 就走路线 B。

**路线 B manifest**（`pack.py mcp` 会 npm 整树下载 `nocodb-mcp`）：

```json
{
  "servers": [
    {
      "name": "nocodb-mcp",
      "transport": "stdio-npm",
      "package": { "name": "nocodb-mcp" },
      "env": {
        "NOCODB_BASE_URL": "ask:NOCODB_BASE_URL",
        "NOCODB_API_TOKEN": "ask:NOCODB_API_TOKEN"
      },
      "note": "zoyak-tech/nocodb-mcp, NocoDB v3 API (>= 2026.04); token: GUI -> Account -> Tokens"
    }
  ]
}
```

**Notes（路线 B）:**
- `nocodb-mcp` 是 ESM 包（`"type": "module"`）——正因如此走**独立子树**而非共享
  wheelhouse/NODE_PATH（gotchas E1）。`pack.py mcp` 自动处理。
- 双 bin：默认 `nocodb-mcp`（stdio）。想在**内网服务器上跑成共享 HTTP 服务**，给 server
  加 `"bin": "nocodb-mcp-http"`，安装后 `set NOCODB_BASE_URL=... && node <入口>` 起服务
  （PORT 默认 3000，`/health` 健康检查，`/mcp` 接客户端），各客户端改用 http 配置连它。
- ⚠️ **NocoDB 社区版把 v3 Meta API 大部分锁在企业许可后**：Community 自托管可用的约
  40-50/92 工具（连接/工作区/表/字段 CRUD/记录 CRUD+批量+全局搜索/导入导出/关联/附件）；
  视图/webhook/仪表盘/工作流/脚本/NocoDocs/评论调用会返回 `ERR_LICENSE_REQUIRED`（402），
  server 本身不受影响、其余工具照常。
- 旧 NocoDB（v2 API）备选：`edwinbernadus/nocodb-mcp-server`（npm 同名包，记录 CRUD 为主，
  `NOCODB_URL` + `NOCODB_API_TOKEN`）——功能窄但社区版无许可限制，package 段换成
  `{"name": "nocodb-mcp-server"}`、env 键名对应改即可。

---

## Adding a new skill

1. Read `how-to-analyze.md` for the methodology.
2. Copy the closest recipe above as a starting point.
3. Adjust `skill_source.path`, `skill_name`, and deps.
4. Validate mentally: pip = python third-party imports, npm = JS require of external packages, playwright = if setup.sh mentions it, tools = external exes.

**关键提醒（踩坑总结）：**
- **target.python 必须匹配内网 Python 版本**。bundle 的 pip wheel 按 cp 标签下载
  （cp312 的 wheel 装不进 3.13），版本不符会全部失败。内网若是 3.13，manifest 写 `3.13`。
- **npm 依赖由 pack.py 整树安装**（落盘到 `node_modules/`），你只需在 manifest 的 `deps.npm`
  列顶层包名（如 `docx`），传递依赖 pack.py 自动解析。**不要**手动列传递依赖。
- 导入名 ≠ 包名：`python-docx`(pip) 导入是 `import docx`；`Pillow`(pip) 是 `import PIL`；
  `PyMuPDF`(pip) 是 `import fitz`。分析时按"包名→导入名"映射，别混淆。
