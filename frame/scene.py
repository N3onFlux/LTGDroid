import random
from anytree import PreOrderIter

from .device import AppInfo
from .utils import hash_hex
from .widget import Widget


class Scene:
    scene_id: str
    widget_tree: Widget
    app_info: AppInfo

    def __init__(self, widget_tree: Widget, app_info: AppInfo):
        self.widget_tree = widget_tree
        self.scene_id = hash_hex(
            ",".join(f"({w.widget_id}:{len(w.children)})" for w in PreOrderIter(self.widget_tree))
        ) + f"-{random.randint(1000, 9999)}"
        self.app_info = app_info
