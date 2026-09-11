# 打包与发布

面向开发者。普通用户从 [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) 下载便携包即可，见[快速开始](getting-started.md)。

## 发布形态

**单包**：`ok-nikke-win32-portable.zip`，解压即用。

包内结构：

```
ok-nikke/
├── ok-nikke.exe            # 入口 shim：自身提权(UAC) + 以包根为 cwd 拉起 python\pythonw.exe main.py
├── python/                 # python-build-standalone（可重定位，自带 pip），依赖装在其 Lib/site-packages
├── git/                    # MinGit（cmd/git.exe），供应用内更新 fetch/checkout
├── src/ assets/ icons/ i18n/ main.py main_debug.py update.py
├── version.txt             # 版本号（build 写、update.py 维护；不入 git）
└── configs/update.json     # 更新源（channel: auto|github|cnb）
```

- 依赖来源是 `requirements.txt`（**保留 `ok-script`/`pyappify`**）。
- 更新源出厂为 `auto`（按系统语言：中文 → CNB 镜像，其它 → GitHub），用户可在「关于 → 应用更新」切换。

## 发布相关文件

- `.github/workflows/build.yml`：监听 `v*` tag，按顺序执行——装 runner 依赖 → 逐文件跑测试 → 下载 python-build-standalone 到 `python/` → 下载 MinGit 到 `git/` → 往包内解释器装 `requirements.txt`（`--no-deps`）→ 写 `version.txt` 与默认 `configs/update.json` → 用 MSVC 编入口 exe（`launcher/build.py`，链接后校验 UAC manifest）→ 同步 CNB 镜像并断言 tag 存在 → 打单个便携 zip → 生成 Release 正文（`.github/scripts/release_notes.py`）→ 创建 GitHub Release。不使用 NSIS 安装器。
- `deploy.txt`：同步到 CNB 国内镜像仓库的文件清单（`src`、`main.py`、`update.py`、`launcher`、`assets` 等）。镜像仓库与 GitHub 同 tag，供 CN 用户应用内更新。
- `launcher/`：入口 shim 源码（`launcher.c` / `launcher.manifest` / `launcher.rc`）与构建脚本 `build.py`（MinGW 或 MSVC 自动探测）。改图标/提权行为后需重新发版——**入口 exe 与 `python/`、`git/` 都无法通过 git 更新**（见方案文档 §10）。
- `update.py`：应用内更新 bootstrap（零第三方依赖），负责 fetch tag → checkout → 必要时 pip → 写版本号 → 重启应用。
- `.github/scripts/release_notes.py`：Release 正文生成（纯标准库；手写覆盖 + Conventional Commits 自动分节，见下节）。
- `changelog/`：可选的用户向更新日志（`changelog/<tag>.md`）——`deploy` 时只有明确要求生成才会写，随 tag 提交后优先于自动生成（见下节）。

## 更新日志（Release 正文）

GitHub Release 的正文不再写死：CI 在创建 Release 前用 `.github/scripts/release_notes.py` 生成 `release_notes.md`，再以 `body_path` 交给 `softprops/action-gh-release`。规则：

- **手写覆盖优先**：`changelog/<tag>.md` 存在时，其正文直接作为「更新日志」内容（文件里不要再写 `### 更新日志` 标题，分组用 `####` 子标题；对应 GitHub issue 的修复可在条目末尾写 `（#12）`，GitHub 会自动变成链接），并且**必须随 tag 一起提交**，CI 才能读到。`deploy` 技能默认**不**生成它，只有发版时明确要求「生成更新日志」才会写这份用户向中文说明；手动发版也可自己写。省略即走自动生成。
- **自动生成回退**：否则解析 `<上一个 tag>..<tag>` 的非 merge 提交并分节——`feat` 新功能、`fix` 问题修复、`perf` 性能优化、`revert`/`refactor` 等其他改动；`docs`/`chore`/`ci`/`test`/`build`/`style` 不单列（全部被过滤时兜底进「其他改动」）；标题带 `!` 或正文含 `BREAKING CHANGE` 的条目进「不兼容变更」节。上一个 tag 按仓库内的 `v*` tag 计算，首个版本写「首个版本发布。」。
- 两种模式都会附加：预发布说明（tag 含 `-`）、`下载说明`（便携 zip 链接）与「完整变更记录」compare 链接；自动模式在区间内 `launcher/` 有改动时额外提示重新下载完整包（入口 exe 无法通过应用内 git 更新交付）。
- 本地预览（不发版、不改远端；`release_notes.md` 已 gitignore，可放心写到仓库根）：

  ```powershell
  .\.venv\Scripts\python.exe .github\scripts\release_notes.py --tag v0.2.0 --out release_notes.md
  ```

## 发布产物

每个 tag 发布一个文件：

- `ok-nikke-win32-portable.zip`：完整便携包。解压到任意目录后运行其中的 `ok-nikke.exe`（需管理员权限；UAC 弹窗未签名时会显示「未知发布者」）。

## 更新机制

应用内更新完全由 `update.py` 完成（git tag 语义，支持升级与降级）：

1. 应用内「检查更新」= `update.py --list-tags` 列出远端 tag；「更新/降级」= `update.py --target <tag> --wait-pid <本进程>`。
2. `update.py` 等旧进程退出 → `git init`/seed（首次）→ `git fetch --depth=1 origin tag <tag>` → 依赖指纹变化时先 pip 再 `checkout -f` → 写 `version.txt`。
3. 任一步失败都以旧版本拉起应用，绝不留下起不来的包；日志见包内 `logs/update.log`。
4. **只对正式版提示**：含 `-` 的预发布（如 `v0.2.0-beta.1`）不亮导航徽标、不进版本下拉（判定见 `src/update_config.py` 的 `is_prerelease`，与 `update.py` 的 `version_key` 同源）；需要试预发布的用户到 Release 页手动下载。版本下拉只列最近 5 个正式版（`update_config.selectable_versions` / `MAX_VERSION_OPTIONS`），排除当前版本，选中更旧的版本按钮变「降级」。

**发布时务必注意（方案 C 的约定）**：框架升级必须同时 bump `pyproject.toml` 并重新 `pip-compile` 生成 `requirements.txt`，与 tag 一起提交；否则 tag 里的 lock 仍是旧版本，用户界面上显示已更新、框架却没升级。`version.txt` 与 `version.txt.prev` 不要提交、不要加进 `deploy.txt`。

## 调整构建配置

如需调整发布配置，修改 `.github/workflows/build.yml`：

- 独立解释器版本线（`STANDALONE_PYTHON`）、Git 用户信息、仓库地址。
- 便携包名称与 Release 下载链接。

工作流已声明 `permissions: contents: write`，无需额外配置 Secrets（CNB 同步用仓库 secret `CNB_DEPLOY_TOKEN`）。

## 发布新版本

推荐使用仓库内置的 `deploy` 技能（`.agents/skills/deploy/`）：提交、创建下一个注释 tag 并推送；发版时明确要求「生成更新日志」还会写 `changelog/<tag>.md`（用户向中文说明）。也可手动创建：

```bash
git tag v0.x.0
git push origin v0.x.0
```

`v*` tag 推送后，GitHub Actions 会运行测试、打包便携 zip 并创建 GitHub Release；tag 名含 `-`（如 `v0.2.0-beta.1`）会被标记为 prerelease，**并且不会被应用内「检查更新」提示**——预发布只能从 Release 页手动下载。

