import time

import uiautomator2 as u2
from loguru import logger


class DeviceHelper:
    device: u2.Device

    def __init__(self, d: u2.Device):
        self.device = d

    @staticmethod
    def wait_time(wait_time: float = 1):
        logger.debug(f"[PreCondition] Wait time: {wait_time}")
        time.sleep(wait_time)

    def swipe(self, direction: str, scale: float = 0.9):
        logger.debug(f"[PreCondition] Swipe {direction} (scale={scale})")
        self.device.swipe_ext(direction, scale=scale)

    def wait_activity(self, activity: str, timeout: float = 5):
        logger.debug(f"[PreCondition] Wait activity (timeout={timeout}): {activity}")
        deadline = time.time() + timeout
        current_activity = ""
        while time.time() < deadline:
            cur_app_info = self.device.app_current()
            current_activity: str = cur_app_info["activity"]
            if current_activity.startswith("."):
                current_activity = cur_app_info["package"] + current_activity
            if activity == current_activity:
                return
            time.sleep(1)
        raise TimeoutError(
            f"Wait activity {activity} timeout, current activity: {current_activity}"
        )

    def try_click_xpath(self, xpath: str, timeout: float = 3, wait_time: float = 1):
        try:
            self.device.xpath(xpath).click(timeout=timeout)
            self.wait_time(wait_time)
            return True
        except:
            logger.warning(f"[PreCondition] Try to click xpath failed: {xpath}")
            return False

    def click_xpath(self, xpath: str, timeout: float = 3, wait_time: float = 1):
        logger.debug(f"[PreCondition] Click xpath (timeout={timeout}): {xpath}")
        self.device.xpath(xpath).click(timeout=timeout)
        self.wait_time(wait_time)

    def input_text_xpath(
            self, xpath: str, text: str, timeout: float = 3, wait_time: float = 1
    ):
        logger.debug(
            f"[PreCondition] Input text xpath (timeout={timeout}, text={text}): {xpath}"
        )
        ele = self.device.xpath(xpath).get(timeout=timeout)
        ele.click()
        time.sleep(0.3)
        self.device.clear_text()
        self.device.send_keys(text)
        self.wait_time(wait_time)

    def long_click_xpath(
            self,
            xpath: str,
            duration: float = 0.8,
            timeout: float = 3,
            wait_time: float = 1,
    ):
        logger.debug(
            f"[PreCondition] Long click xpath (timeout={timeout}, duration={duration}): {xpath}"
        )
        x, y = self.device.xpath(xpath).get(timeout=timeout).center()
        self.device.long_click(x, y, duration=duration)
        self.wait_time(wait_time)

    def back(self, wait_time: float = 1):
        logger.debug("[PreCondition] Back")
        self.device.press("back")
        self.wait_time(wait_time)

    def install_app(self, apk_path: str, uninstall: bool = True):
        self.device.adb_device.install(apk_path, uninstall=uninstall)

    def clear_app(self, package_name: str):
        self.device.app_clear(package_name)

    def start_app(self, package_name: str):
        self.device.app_start(package_name, wait=True, use_monkey=True)


class BaseTask:
    device: DeviceHelper
    task_description: str
    action_delay = 2

    def __init__(self, d: u2.Device):
        self.device = DeviceHelper(d)

    def precondition(self):
        pass
