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


def is_xal(data):
    """判断文件内容是否为 x-anylabeling 格式（imagePath + shapes 列表）。"""
    return (isinstance(data, dict) and 'imagePath' in data
            and isinstance(data.get('shapes'), list))


def shape_to_bbox(shape):
    """把 XAL 的 points 转成 [x, y, w, h]，四舍五入取整（与框架 read_from_json 一致）。"""
    pts = shape['points']  # 多边形/矩形顶点列表。
    xs = [p[0] for p in pts]  # 所有顶点 x。
    ys = [p[1] for p in pts]  # 所有顶点 y。
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)  # 最小外接框。
    return round(x1), round(y1), round(x2 - x1), round(y2 - y1)  # 取整的 x, y, w, h。


def build_xal_coco(src_dir):
    """扫描 src_dir 下所有有标注的 XAL，构造未压缩的 COCO（image 一条对应一个 XAL 截图）。

    跳过非 XAL 或 shapes 为空的 JSON（如 ok_templates/coco_annotations.json、huodong_01/02 等）。
    """
    categories = []  # 类别表。
    cat_id_by_name = {}  # label -> category_id 映射。
    images = []  # 图片表（每条对应一个 XAL 截图）。
    annotations = []  # 标注表。
    ann_id = 1  # 标注自增 id。
    img_id = 1  # 图片自增 id。
    for f in sorted(glob.glob(os.path.join(src_dir, '*.json'))):  # 遍历 XAL 目录 JSON。
        with open(f, encoding='utf-8') as fh:  # 读取标注文件。
            data = json.load(fh)
        if not is_xal(data) or not data.get('shapes'):  # 跳过非 XAL 或无标注的 JSON。
            continue
        images.append({  # 每个 XAL 对应一张原始截图。
            'id': img_id,
            'file_name': os.path.basename(data['imagePath']),  # 压缩前先统一为 basename，避免 XAL 用子目录时拼图失败。
            'width': data['imageWidth'],  # 截图宽（通常 2560）。
            'height': data['imageHeight'],  # 截图高（通常 1440）。
        })
        for shape in data['shapes']:  # 逐个标注框。
            label = shape['label']  # 特征名。
            if label not in cat_id_by_name:  # 新标签登记为类别。
                cat_id_by_name[label] = len(categories) + 1
                categories.append({'id': cat_id_by_name[label], 'name': label, 'supercategory': ''})
            x, y, w, h = shape_to_bbox(shape)  # 转 bbox。
            annotations.append({  # 追加标注。
                'id': ann_id,
                'image_id': img_id,
                'category_id': cat_id_by_name[label],
                'bbox': [x, y, w, h],
                'area': w * h,
                'iscrowd': 0,
            })
            ann_id += 1
        img_id += 1
    return {'images': images, 'annotations': annotations, 'categories': categories}


def import_xal(target_dir='assets'):
    """主流程：解析 XAL → 临时 COCO → 框架 compress_copy_coco 打包到 target_dir。"""
    src_dir = os.path.abspath(SRC)  # XAL 目录绝对路径。
    target_dir = os.path.abspath(target_dir)  # 输出目录绝对路径。
    # 临时 COCO 写在 ok_templates 下：compress_copy_coco 要求 coco_json 与 image_folder 同级，
    # 内部会按 coco_folder 解析 file_name；放其它目录会找不到 XAL 截图。
    tmp_coco = os.path.join(src_dir, TMP_COCO_NAME)
    coco = build_xal_coco(src_dir)  # 解析 XAL 构造未压缩 COCO。
    if not coco['images']:  # 没有任何有标注的 XAL。
        raise RuntimeError(f'no x-anylabeling annotations found in {src_dir}')
    with open(tmp_coco, 'w', encoding='utf-8') as f:  # 落盘临时 COCO。
        json.dump(coco, f, ensure_ascii=False, indent=2)
    try:
        # 复用框架 compress_copy_coco：复制图到 target_dir/images/、重写 file_name 为 images/<base>，
        # 再链式调 compress_coco 按 bbox 冲突贪心分页拼图，输出 0.png/1.png/... 并改写 file_name。
        compress_copy_coco(tmp_coco, target_dir, src_dir)
        print(f'packed {len(coco["images"])} source images, {len(coco["annotations"])} annotations, '
              f'{len(coco["categories"])} categories -> {target_dir}')
    finally:
        if os.path.exists(tmp_coco):  # 清理临时 COCO（写在 ok_templates 下，不污染 assets）。
            os.remove(tmp_coco)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])  # 命令行入口。
    parser.add_argument('--target', default='assets',  # 输出目录，默认覆盖 assets/。
                        help='output directory (default: assets)')
    args = parser.parse_args()
    import_xal(args.target)


if __name__ == '__main__':  # 脚本入口。
    main()
