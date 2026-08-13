# 打包与发布

## 发布相关文件

- `.github/workflows/build.yml`：监听 `v*` tag，运行测试、打包并创建 GitHub Release。
- `pyappify.yml`：定义应用名称、入口、图标、Python 版本和更新仓库。
- `deploy.txt`：定义同步到独立更新仓库的文件（当前使用源码仓库更新，未启用）。

## 修改构建工作流

首次发布前，根据自己的项目修改 `.github/workflows/build.yml`：

- 更新 Git 用户信息。
- 更新源码库和更新库地址。
- 更新安装包名称和 Release 下载链接。
- 配置工作流需要的 GitHub Actions Secrets。

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

GitHub Actions 会运行测试、打包 EXE，并创建对应的 GitHub Release。发布前再次搜索 `.github/workflows`，确认没有遗留的模板仓库地址、项目名或未配置的 Secrets。
