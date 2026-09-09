# 打包与发布

面向开发者。普通用户从 [GitHub Releases](https://github.com/c6n1aa/ok-nikke/releases) 下载便携包即可，见[快速开始](getting-started.md)。

## 发布相关文件

- `.github/workflows/build.yml`：监听 `v*` tag，运行测试（逐文件独立进程）、把 ok-script 内联进源码包（`inline_ok_requirements`，从 requirements 删除以加速应用内更新），再用 pyappify-action 只编译启动器 exe（`build_exe_only`），执行 `ok-nikke.exe -c setup -p Release` 生成 `data/`（内嵌 Python + venv + 按 tag 克隆的代码），压缩成便携 zip 并创建 GitHub Release。不使用 NSIS 安装器。
- `pyappify.yml`：定义应用名称、入口、图标、Python 版本和更新仓库。单一 `Release` profile；profile 名与 workflow 中 `setup` 步骤的 `-p` 参数保持一致。
- `pyappify-cn.yml` / `pyappify-global.yml`：随便携包一起放到包根目录的更新源配置。当前两者 `git_url` 都指向 GitHub（国内镜像未建），用户首次运行前把其一重命名为 `pyappify.yml` 即可选择更新源。
- `deploy.txt`：定义同步到独立更新仓库的文件（当前使用源码仓库更新，未启用）。

## 发布产物

每个 tag 只发布一个文件：

- `ok-nikke-win32-portable.zip`：完整便携包（启动器 exe + `data/` 全部依赖），解压到任意目录后运行其中的 `ok-nikke.exe`（需管理员权限）。

便携包根目录会附带 `pyappify-cn.yml` 与 `pyappify-global.yml`。首次运行前，按网络环境把其中一个重命名为 `pyappify.yml`（与 `ok-nikke.exe` 同目录），启动器会读取它作为更新源配置；当前两者均指向 GitHub，国内镜像仓库建好后 `pyappify-cn.yml` 会改为镜像地址。

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

启动器 exe 只在图标或 pyappify 配置变化时才需要重新编译。日常发版可在 `Build launcher with PyAppify Action` 步骤增加 `use_release` 输入，复用上一个 Release 中的启动器以大幅缩短构建时间：

```yaml
- name: Build launcher with PyAppify Action
  id: build-app
  uses: ok-oldking/pyappify-action@master
  with:
    use_release: https://api.github.com/repos/c6n1aa/ok-nikke/releases/tags/v0.1.0
```

注意 `use_release` 复用的是旧 Release 中的 `ok-nikke-win32.zip` 启动器包，而本项目的 Release 已改为只发布便携 zip；若要用此加速方式，需同时让工作流保留发布该启动器包，或改从指定 Release 资产中获取 exe。
