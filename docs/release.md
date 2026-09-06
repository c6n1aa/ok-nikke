# 打包与发布

## 发布相关文件

- `.github/workflows/build.yml`：监听 `v*` tag，运行测试、用 pyappify-action 只编译启动器 exe（`build_exe_only`），再执行 `ok-nikke.exe -c setup -p Release` 生成 `data/`（内嵌 Python + venv + 按 tag 克隆的代码），压缩成便携 zip 并创建 GitHub Release。不使用 NSIS 安装器。
- `pyappify.yml`：定义应用名称、入口、图标、Python 版本和更新仓库。单一 `Release` profile，不再区分 China/Global；profile 名与 workflow 中 `setup` 步骤的 `-p` 参数保持一致。
- `deploy.txt`：定义同步到独立更新仓库的文件（当前使用源码仓库更新，未启用）。

## 发布产物

每个 tag 只发布一个文件：

- `ok-nikke-win32-portable.zip`：完整便携包（启动器 exe + `data/` 全部依赖），解压到任意目录后运行其中的 `ok-nikke.exe`（需管理员权限）。

应用内更新由启动器通过 git tag 完成（fetch `git_url` → checkout → 依赖变化时重跑 pip），与发布产物形态无关；`git_url` 由仓库中的 `pyappify.yml` 驱动，修改后随下一版生效，无需重编启动器。

## 修改构建工作流

首次发布前，根据自己的项目修改 `.github/workflows/build.yml`：

- 更新 Git 用户信息。
- 更新源码库和更新库地址。
- 更新便携包名称和 Release 下载链接。
- 工作流已声明 `permissions: contents: write`，无需额外配置 Secrets。

本项目未集成 Mirror酱、CNB 或网盘渠道，如需接入请参考本文相应小节。

## 推送版本 tag

提交并推送初始化结果，再创建符合 `v*` 规则的 tag：

```bash
git add .
git commit -m "Initialize project"
git push origin HEAD
git tag v0.1.0
git push origin v0.1.0
```

GitHub Actions 会运行测试、打包便携 zip，并创建对应的 GitHub Release。发布前再次搜索 `.github/workflows`，确认没有遗留的模板仓库地址、项目名或未配置的 Secrets。

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
