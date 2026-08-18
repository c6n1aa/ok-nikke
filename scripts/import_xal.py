"""从 ok_templates 下的 XAL（x-anylabeling）标注生成 assets/images 与 coco_annotations.json。

用途：在 XAL 中完成 coco 特征标注（每个特征一个矩形框，标注写在 2560x1440 截图上）后，用本脚本
把全部有标注的 JSON 转换为压缩图集：140 个特征被框架按 (width,height) 分组、按 bbox 冲突贪心分
到 N 张白底大图（默认 2560x1440），输出 0.png/1.png/... 与改写 file_name 后的 COCO。

这条流水线与 GUI「模板 tab → 保存压缩」走的是同一路径：
    xal -> 未压缩 coco -> ok.feature.FeatureSet.compress_copy_coco
        -> 复制/重命名 image -> 内部链式调用 compress_coco 拼图 + 改写 file_name
不依赖外部 xanylabeling CLI，不重复实现拼图算法。

用法（必须在仓库根目录运行，使 ok_templates/ 与 assets/ 路径生效）：
    python scripts/import_xal.py                 # 生成到 ./assets（覆盖 images/ 与 coco_annotations.json）
    python scripts/import_xal.py --target 临时目录  # 生成到指定目录（用于 diff/验证，不动正式 assets）
"""
import argparse
import glob
import json
import os

from ok.feature.FeatureSet import compress_copy_coco  # 框架自带：复制图 + 内部 compress_coco 拼图。

SRC = 'ok_templates'  # XAL 标注与截图所在目录。
TMP_COCO_NAME = 'coco_annotations.json'  # 临时 COCO 文件名；compress_copy_coco 以 basename 落盘为同名。
