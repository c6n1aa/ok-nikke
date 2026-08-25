# P1.3 coco 标注完整性静态校验测试

> 上游依据：`docs/screen-recovery-evolution-plan.md` §5.3 子项 3、§6 Phase 1.3
> 工作分支：`feature/screen-recovery-evolution`；依赖：P1.1（需 `src/screens.py` 就位）。
> 预计改动面：`tests/TestScreenRegistryIntegrity.py`（新增）。

## 目标

把「注册表引用了 coco 中不存在的特征」从运行时 warning（`NikkeBaseTask.py:591-593`）前移到测试期/CI 失败。

## 实施步骤

1. 新建 `tests/TestScreenRegistryIntegrity.py`（纯 `unittest`，不需要 `TaskTestCase`——本测试不触碰游戏帧，只做静态比对）。
2. 用例：
   - 读取 `assets/coco_annotations.json` 的 `categories` 名称集合。
   - 导入 `src.screens.SCREENS`，收集每个界面条目的：`features` 列表元素、`ocr_box`（若为字符串形式的 coco 特征名）。
   - 断言引用集合 ⊆ coco categories；失败时按界面分组打印缺失特征清单（提供可读 diff）。
3. 二次断言「无空判定」：每个界面至少配置了 `features` 或 `keywords` 之一（防止误注册空 spec）。

## 修改文件

- 新增：`tests/TestScreenRegistryIntegrity.py`。

## 测试与验收

- `.\venv\Scripts\python.exe -m unittest tests.TestScreenRegistryIntegrity` 通过。
- 破坏性验证：在临时副本上把某个界面条目的 features 改成一个不存在的名字，应导致该用例失败（验证完成后还原；禁止提交破坏性改动）。

## 提交

`test(screens): validate screen registry against coco annotations`

## 超范围禁止

不引入几何/模态覆盖区检查（该扩展项依赖 P1.4 的「参与全局判定标记」，见 Backlog）；不改任何产品代码。
