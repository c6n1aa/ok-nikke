import argparse
import ast
import os
from collections import Counter

import polib


TASK_DICT_ATTRS = {"default_config", "config_description", "config_type"}
TASK_STRING_ATTRS = {"name", "description"}
CONFIG_TYPE_META = {
    "type",
    "options",
    "buttons",
    "drop_down",
    "multi_selection",
    "global",
    "text_edit",
    "button",
}


class TaskStringVisitor(ast.NodeVisitor):
    def __init__(self):
        self.strings = []

    def visit_Assign(self, node):
        for target in node.targets:
            self._collect_assignment(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        self._collect_assignment(node.target, node.value)
        self.generic_visit(node)

    def visit_Call(self, node):
        attr = node.func
        if isinstance(attr, ast.Attribute) and attr.attr == "update":
            if self._is_self_attr_in(attr.value, {"default_config", "config_description"}):
                for arg in node.args:
                    self._collect_dict_strings(arg)
            elif self._is_self_attr_in(attr.value, {"config_type"}):
                for arg in node.args:
                    self._collect_config_type_strings(arg)
        self.generic_visit(node)

    def _collect_assignment(self, target, value):
        if self._is_self_attr_in(target, TASK_STRING_ATTRS):
            self._add_string(value)
        elif self._is_self_attr_in(target, {"default_config", "config_description"}):
            self._collect_dict_strings(value)
        elif self._is_self_attr_in(target, {"config_type"}):
            self._collect_config_type_strings(value)

    def _is_self_attr_in(self, node, attrs):
        return (
            isinstance(node, ast.Attribute)
            and node.attr in attrs
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        )

    def _add_string(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if value:
                self.strings.append(value)

    def _collect_dict_strings(self, node):
        if not isinstance(node, ast.Dict):
            return
        for key, value in zip(node.keys, node.values):
            self._add_string(key)
            self._collect_value_strings(value)

    def _collect_value_strings(self, node):
        self._add_string(node)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for item in node.elts:
                self._collect_value_strings(item)
        elif isinstance(node, ast.Dict):
            self._collect_dict_strings(node)

    def _collect_config_type_strings(self, node):
        if not isinstance(node, ast.Dict):
            return
        for key, value in zip(node.keys, node.values):
            self._add_string(key)
            self._collect_config_type_value(value)

    def _collect_config_type_value(self, node):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value in {"options", "buttons"}:
                    self._collect_value_strings(value)
        elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            for item in node.elts:
                self._collect_config_type_value(item)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value not in CONFIG_TYPE_META:
            self._add_string(node)


def scan_task(path):
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    visitor = TaskStringVisitor()
    visitor.visit(tree)
    for value in dict.fromkeys(visitor.strings):
        print(value)


def iter_po_paths(i18n_dir):
    """列出目录下的全部 .po，顺序稳定。

    除了 ok.po（应用 UI），项目里还可能有 ocr.po（游戏画面文字，域为 "ocr"），
    两者都要编译，因此按后缀遍历而不是只认 ok.po。
    """
    for root, dirnames, files in os.walk(i18n_dir):
        dirnames.sort()
        for name in sorted(files):
            if name.endswith(".po"):
                yield os.path.join(root, name)


def find_duplicate_msgids(po):
    ids = [entry.msgid for entry in po if entry.msgid]
    return sorted(msgid for msgid, count in Counter(ids).items() if count > 1)


def needs_space_stripped_entries(po_path):
    """英文词条需要额外一份去掉空格的 msgid。

    OCR 结果经常丢掉词间空格，框架匹配时会先查原串、再查一次去空格串，
    因此只有空格有意义（英文）的词条需要这份变体。与框架
    ok.core.translation 里 duplicate_spaced_msgids 的做法一致。
    """
    return any(part.startswith("en") for part in os.path.normpath(po_path).split(os.sep))


def add_space_stripped_entries(po):
    existing = {entry.msgid for entry in po}
    added = []
    for entry in po:
        if not entry.msgid or " " not in entry.msgid or not entry.msgstr:
            continue
        stripped = entry.msgid.replace(" ", "")
        if stripped in existing:
            continue
        existing.add(stripped)
        added.append(polib.POEntry(msgid=stripped, msgstr=entry.msgstr))
    po.extend(added)
    return len(added)


def compile_i18n(i18n_dir):
    for po_path in iter_po_paths(i18n_dir):
        po = polib.pofile(str(po_path))
        duplicates = find_duplicate_msgids(po)
        if duplicates:
            raise SystemExit(f"duplicate msgid entries in {po_path}: {duplicates}")
        added = add_space_stripped_entries(po) if needs_space_stripped_entries(po_path) else 0
        mo_path = os.path.splitext(po_path)[0] + ".mo"
        po.save_as_mofile(mo_path)
        extra = f" (+{added} space-stripped entries)" if added else ""
        print(f"compiled {po_path} -> {mo_path}{extra}")


def check_i18n(i18n_dir):
    failed = False
    for po_path in iter_po_paths(i18n_dir):
        po = polib.pofile(str(po_path))
        duplicates = find_duplicate_msgids(po)
        if duplicates:
            failed = True
            print(f"duplicate msgid entries in {po_path}:")
            for msgid in duplicates:
                print(msgid)
        else:
            print(f"ok {po_path}")
    if failed:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan")
    scan.add_argument("--task", required=True)

    compile_cmd = subparsers.add_parser("compile")
    compile_cmd.add_argument("--i18n", default="i18n")

    check_cmd = subparsers.add_parser("check")
    check_cmd.add_argument("--i18n", default="i18n")

    args = parser.parse_args()

    if args.command == "scan":
        scan_task(args.task)
    elif args.command == "compile":
        compile_i18n(args.i18n)
    elif args.command == "check":
        check_i18n(args.i18n)


if __name__ == "__main__":
    main()
