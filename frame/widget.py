from anytree import NodeMixin, findall, RenderTree

from typing import TYPE_CHECKING

from frame.action import Action, ActionType
from frame.utils import hash_hex

if TYPE_CHECKING:
    from frame.scene import Scene


class WidgetMatch:
    path: list[str]
    attributes: dict[str, str]

    @staticmethod
    def from_json(json: dict):
        return WidgetMatch(**json)

    def __init__(self, path: list[str], attributes: dict[str, str]):
        self.path = path
        self.attributes = attributes

    def to_json(self):
        return {"path": "/".join(self.path), "attributes": self.attributes}

    def match_in_scene(self, scene: "Scene") -> "Widget | None":
        found_by_attribute = findall(scene.widget_tree, lambda w: w.attributes == self.attributes)
        if len(found_by_attribute) == 1:
            return found_by_attribute[0]

        for i in range(len(self.path) - 3):
            cur_path_str = "/".join(self.path[i:])

            def find_by_cur_path(w):
                return w.path_str.endwith(cur_path_str)

            found_by_path = findall(scene.widget_tree, find_by_cur_path)
            if len(found_by_path) == 0:
                continue

            if len(found_by_attribute) == 0:
                return found_by_path[0]

            for ww in found_by_path:
                if ww in found_by_attribute:
                    return ww  # the first widget found both in found_by_attribute and found_by_path

        return None  # not found


class WidgetBounds:
    left: int
    top: int
    right: int
    bottom: int
    bounds: str

    def __init__(self, bounds: str):
        self.bounds = bounds
        parts = bounds.strip("[]").split("][")
        [x1, y1] = parts[0].split(",")
        [x2, y2] = parts[1].split(",")
        self.left = int(x1)
        self.top = int(y1)
        self.right = int(x2)
        self.bottom = int(y2)

    def center(self) -> tuple[int, int]:
        x = round((self.left + self.right) / 2)
        y = round((self.top + self.bottom) / 2)
        return x, y

    def __str__(self):
        return self.bounds


class Widget(NodeMixin):
    widget_id: str
    scene_id: str

    virtual: bool
    name: str
    path_str: str

    attributes: dict[str, str]
    tag: str
    bounds: WidgetBounds
    package: str
    text: str
    content_desc: str
    resource_id: str
    clickable: bool
    long_clickable: bool

    def __init__(self, node, parent: "Widget | None"):
        if node is None:
            self.virtual = True
            self.widget_id = "0"
            self.attributes = {}
        else:
            self.virtual = False
            self.parent = parent
            self.attributes = dict(node.attrib)

            # state attributes
            self.bounds = WidgetBounds(self.attributes["bounds"])
            self.tag = self.attributes["class"].split(".")[-1]
            self.package = self.attributes.get("package", "")
            self.text = self.attributes.get("text", "").strip()
            self.content_desc = self.attributes.get("content-desc", "").strip()
            self.hint = self.attributes.get("hint", "").strip()
            self.resource_id = self.attributes.get("resource-id", "").split("/")[-1].strip()
            self.checked = self.attributes.get("checked", "false") == "true"
            self.selected = self.attributes.get("selected", "false") == "true"
            self.enabled = self.attributes.get("enabled", "true") == "true"
            self.activated = self.attributes.get("activated", "false") == "true"

            self.clickable = self.attributes.get("clickable", "false") == "true"
            self.long_clickable = self.attributes.get("long-clickable", "false") == "true"

            self.widget_id = hash_hex(
                ",".join(
                    map(
                        str,
                        [
                            self.package,
                            self.tag,
                            self.resource_id,
                            self.bounds,
                            self.text,
                            self.content_desc,
                            self.hint,
                            self.checked,
                            self.selected,
                            self.enabled,
                            self.activated,
                        ],
                    )
                )
            )

    def __str__(self):
        if self.virtual:
            return f"Virtual"
        if not self.name:
            return f"ROOT"
        return f"Name({self.name})::ResourceId({self.resource_id})::Text({self.text[:10]})::ContentDesc({self.content_desc[:10]})"

    def available_actions(self) -> list[Action]:
        if self.virtual:
            return []

        actions = []
        if self.tag == "EditText":
            actions.append(Action(self.scene_id, self, ActionType.InputText, "::random::"))
            actions.append(Action(self.scene_id, self, ActionType.LongClick))
        else:
            if self.clickable:
                actions.append(Action(self.scene_id, self, ActionType.Click))
            if self.long_clickable:
                actions.append(Action(self.scene_id, self, ActionType.LongClick))

        return actions

    def to_widget_match(self):
        return WidgetMatch(self.path_str.split("/"), self.attributes)

    def is_empty_content(self):
        return not self.text and not self.content_desc and not self.resource_id and not self.hint

    def is_empty_content_tree(self):
        def recur(w: Widget):
            if not w.is_empty_content():
                return False
            if w.children:
                for c in w.children:
                    if not recur(c):
                        return False
            return True

        return recur(self)

    def to_prompt_content(self):
        # only this widget
        out = []
        if self.checked:
            out.append("checked")
        if self.text:
            out.append(self.text)
        if self.content_desc:
            out.append(self.content_desc)
        if self.resource_id:
            out.append(self.resource_id)
        if self.hint:
            out.append(self.hint)
        return ";".join(out)

    def to_prompt_xml_single(self):
        # only this widget
        return f'<{self.tag} content="{self.to_prompt_content()}"/>'

    def to_prompt_xml_tree(self, addition: str = ""):
        # the widget tree with content in xml

        def recur(widget: Widget, indent: int):
            pad = " " * (indent * 4)
            content = widget.to_prompt_content()
            cur_addition = f" {addition}" if indent == 0 else ""
            if not widget.children:
                return f'{pad}<{widget.tag} content="{content}"{cur_addition}/>\n'
            else:
                result = f'{pad}<{widget.tag} content="{content}"{cur_addition}>\n'
                for child in widget.children:
                    result += recur(child, indent + 1)
                result += f"{pad}</{widget.tag}>\n"
                return result.strip("\n")

        return recur(self, 0)

    def render_tree(self) -> str:
        out = []
        for pre, fill, node in RenderTree(self):
            if node.virtual or not node.name:
                out.append("ROOT")
            else:
                out.append(f"{pre}{node}")
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {"widget_id": self.widget_id, "attributes": self.attributes, "render": self.render_tree()}
