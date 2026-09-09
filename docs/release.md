# 打包与发布

面向开发者。普通用户从 [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) 下载便携包即可，见[快速开始](getting-started.md)。

## 发布相关文件

- `.github/workflows/build.yml`：监听 `v*` tag，运行测试（逐文件独立进程）、把 ok-script 内联进源码包（`inline_ok_requirements`，从 requirements 删除以加速应用内更新），再用 pyappify-action 只编译启动器 exe（`build_exe_only`），对每个 profile 执行 `ok-nikke.exe -c setup -p <profile>` 生成 `data/`（内嵌 Python + venv + 按 tag 克隆的代码），压缩成便携 zip 并创建 GitHub Release。不使用 NSIS 安装器。
- `pyappify.yml`：定义应用名称、入口、图标、Python 版本和更新仓库。两个 profile：`Release`（GitHub）与 `Release-CN`（CNB 镜像）；profile 名与 workflow 中 `setup` 步骤的 `-p` 参数对应。
- `deploy.txt`：定义同步到 CNB 国内镜像仓库的文件（`src`、`ok`、`main.py`、`assets`、`pyappify.yml` 等）。

## 发布产物

每个 tag 发布以下文件：

- `ok-nikke-win32-portable.zip`：全球版完整便携包（启动器 exe + `data/` 全部依赖），更新源为 GitHub。解压到任意目录后运行其中的 `ok-nikke.exe`（需管理员权限）。
- `ok-nikke-win32-portable-cn.zip`：国内版完整便携包，更新源为 CNB 镜像（`https://cnb.cool/c6n1aa/ok-nikke`）。解压到任意目录后运行其中的 `ok-nikke.exe`（需管理员权限）。
- `ok-nikke-win32.zip`：仅含启动器 exe，供 CI 复用加速后续构建（见下文「复用启动器加速构建」），普通用户无需下载。

两个包的 exe 相同，区别只在打包时 `setup` 用的 profile（Global 用 `Release`，CN 用 `Release-CN`），因此各自 `data/` 里固化的更新源（当前 profile）不同。

应用内更新由启动器通过 git tag 完成（fetch `git_url` → checkout → 依赖变化时重跑 pip），与发布产物形态无关；`git_url` 由仓库中的 `pyappify.yml` 驱动，修改后随下一版生效，无需重编启动器。

## 调整构建配置

如需调整发布配置，修改 `.github/workflows/build.yml`：

- Git 用户信息、源码库与更新库地址。
- 便携包名称与 Release 下载链接。

工作流已声明 `permissions: contents: write`，无需额外配置 Secrets。

本项目未集成 Mirror酱、CNB 或网盘渠道，如需接入请参考 ok-script 框架文档相应小节。

## 发布新版本

推荐使用仓库内置的 `deploy` 技能（`.agents/skills/deploy/`）：自动提交、创建下一个注释 tag 并推送。也可手动创建：

```bash
git tag v0.x.0
git push origin v0.x.0
```

`v*` tag 推送后，GitHub Actions 会运行测试、打包便携 zip 并创建 GitHub Release；tag 名含 `-`（如 `v0.2.0-beta.1`）会被标记为 prerelease。

## 复用启动器加速构建

启动器 exe 的 Tauri 编译约占构建耗时的 70%（约 12 分钟）。图标（`icons/`）与 `pyappify.yml` 都内嵌在 exe 中，因此只要二者自某个已发布版本起都未变化，后续版本即可复用该版本的启动器：

1. 每个 Release 都附带 `ok-nikke-win32.zip` 启动器包资产（顶层目录 `ok-nikke/ok-nikke.exe`，与 pyappify 基础包格式一致）。
2. 把 `.github/workflows/build.yml` 中的 `USE_RELEASE` 环境变量改为某个 Release 的 API URL（如 `https://api.github.com/repos/c6n1aa/ok-nikke/releases/tags/v0.1.1`），构建即跳过编译、直接从该 Release 下载 exe；平时保持为空。

注意 pyappify-action 自带的 `use_release` 输入与 `build_exe_only` 互斥且会连带打包 NSIS 安装器，本工作流不用它，而是在 `Reuse launcher from previous release` 步骤中做等价实现。修改图标或 `pyappify.yml` 的版本必须留空全量编译，否则会产出含旧配置的旧启动器。
