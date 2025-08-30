import os.path
import re
import shlex
import subprocess
import time
from typing import TYPE_CHECKING

import uiautomator2 as u2
from PIL.Image import Image
import lxml.etree as etree
from anytree import PreOrderIter

if TYPE_CHECKING:
    from .scene import Scene
    from .widget import Widget


class AppInfo:
    package: str
    activity: str

    def __init__(self, package: str, activity: str):
        self.package = package
        self.activity = activity

    def to_dict(self):
        return {"package": self.package, "activity": self.activity}


class Device:
    device: u2.Device
    device_serial: str
    connected: bool = False
    INPUT_TEXT_SUPPORTED_CHARS = re.compile(r"^[A-Za-z0-9@_\-\+,\./: ]*$")

    @classmethod
    def connect(cls, device_serial: str | None = None):
        if device_serial is not None:
            cls.device = u2.connect(device_serial)
        else:
            cls.device = u2.connect()
        cls.device_serial = cls.device.serial
        cls.connected = True

    @classmethod
    def set_proxy(cls, proxy: str = "10.0.2.2:7890"):
        cls.device.shell(f"settings put global http_proxy {proxy}")
        cls.device.shell(f"settings put global https_proxy {proxy}")

    @classmethod
    def set_immersive(cls):
        cls.device.shell("settings put global policy_control immersive.full=*")

    @classmethod
    def u2_ime_set(cls, enable: bool):
        if not enable:
            cls.device.shell("pm enable com.android.inputmethod.latin")
            cls.device.set_input_ime(False)
        else:
            cls.device.shell("pm disable-user com.android.inputmethod.latin")
            cls.device.set_input_ime(True)

    @classmethod
    def hide_keyboard(cls):
        cls.device.hide_keyboard()

    @classmethod
    def set_orientation(cls, orientation: str):
        cls.device.set_orientation(orientation)

    @classmethod
    def install_app(cls, apk_path: str, uninstall: bool = True):
        apk_path = os.path.abspath(apk_path)
        cls.device.adb_device.install(apk_path, uninstall=uninstall, nolaunch=True)

    @classmethod
    def uninstall_app(cls, package_name: str):
        cls.device.app_uninstall(package_name)

    @classmethod
    def clear_app(cls, package_name: str):
        cls.device.app_clear(package_name)

    @classmethod
    def start_app(
        cls,
        package_name: str,
        activity: str | None = None,
        stop: bool = False,
        wait_timeout: int = 10,
    ):
        cls.device.app_start(package_name, wait=False, activity=activity, stop=stop)
        if cls.device.app_wait(package_name, wait_timeout) == 0:
            raise TimeoutError(f"start app {package_name} timeout")

    @classmethod
    def start_app_session(cls, package_name: str, activity: str, attach: bool = False):
        cls.start_app(package_name, activity, stop=not attach)
        return u2.Session(cls.device.adb_device, package_name)

    @classmethod
    def logcat_crash(cls):
        return subprocess.check_output(
            ["adb", "-s", cls.device_serial, "logcat", "-d", "AndroidRuntime:E", "*:S"], encoding="utf-8"
        )

    @classmethod
    def logcat_clear(cls):
        subprocess.run(["adb", "-s", cls.device_serial, "logcat", "-c"])

    @classmethod
    def active_app_info(cls) -> AppInfo:
        info = cls.device.app_current()
        package: str = info["package"]
        activity: str = info["activity"]
        if activity.startswith("."):
            activity = package + activity
        return AppInfo(package, activity)

    @classmethod
    def screenshot(cls) -> Image:
        res = cls.device.screenshot()
        assert res is not None
        return res

    @classmethod
    def click(cls, x: int, y: int):
        cls.device.click(x, y)

    @classmethod
    def long_click(cls, x: int, y: int, duration: float = 0.8):
        cls.device.long_click(x, y, duration)

    @classmethod
    def input_text(cls, widget: "Widget", text: str):
        x, y = widget.bounds.center()
        cls.click(x, y)
        time.sleep(0.1)
        cls.device.clear_text()

        if len(text) <= 20 and cls.INPUT_TEXT_SUPPORTED_CHARS.match(text):
            safe_text = text.replace(" ", "%s")
            cls.device.shell(f"input text {shlex.quote(safe_text)}")
        else:
            cls.device.send_keys(text)

    @classmethod
    def press_back(cls):
        cls.device.press("back")

    @classmethod
    def press_home(cls):
        cls.device.press("home")

    @classmethod
    def press_enter(cls):
        cls.device.press("enter")

    @classmethod
    def press_delete(cls):
        cls.device.press("delete")

    @classmethod
    def current_scene(cls, only_filter: str | None = None, remove_package: set[str] | None = None) -> "Scene":
        from .widget import Widget
        from .scene import Scene

        # construct widget tree

        if remove_package is None:
            remove_package = set()

        xml_hierarchy = cls.device.dump_hierarchy(max_depth=100)
        root = etree.fromstring(xml_hierarchy.encode())
        if only_filter is not None:
            top_layer_nodes = [
                child
                for child in root
                if child.attrib["package"] == only_filter and child.attrib["package"] not in remove_package
            ]
        else:
            top_layer_nodes = [child for child in root if child.attrib["package"] not in remove_package]

        if len(top_layer_nodes) == 1:
            root_widget = Widget(top_layer_nodes[0], None)
        else:
            root_widget = Widget(None, None)

        def _traverse_node(node: etree.Element, parent: Widget | None):
            cur_widget = Widget(node, parent)
            for child in node:
                if child.attrib["package"] in remove_package:
                    continue
                if only_filter is None or child.attrib["package"] == only_filter:
                    _traverse_node(child, cur_widget)

        for c in root:
            if c.attrib["package"] in remove_package:
                continue
            if only_filter is None or c.attrib["package"] == only_filter:
                _traverse_node(c, root_widget)

        def _travel(the_root: Widget):
            for index, child in enumerate(the_root.children):
                # path like /0:ClassA/1:ClassB
                child.name = f"{index}:{child.tag}"
                _travel(child)

        root_widget.name = ""
        _travel(root_widget)

        app_info = Device.active_app_info()
        scene = Scene(root_widget, app_info)

        for w in PreOrderIter(root_widget):
            w.path_str = "/".join([t.name for t in w.path])
            w.scene_id = scene.scene_id

        return scene
