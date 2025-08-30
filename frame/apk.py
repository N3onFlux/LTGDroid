import os
import apkutils

from frame.utils import ensure_dir


class Apk:
    apk_path: str
    package_name: str
    main_activities: list[str]

    def __init__(
            self, apk_name: str):
        ensure_dir("working/apk")
        apk_path = os.path.abspath(f"working/apk/{apk_name}")
        self.apk_path = apk_path

        if not os.path.exists(apk_path):
            raise Exception(f"Apk file not found: {apk_path}")

        with apkutils.APK.from_file(apk_path) as apk:
            self.package_name = apk.get_package_name()
            self.main_activities = apk.get_main_activities()

    def __str__(self) -> str:
        return f"Apk(apk_path={self.apk_path}, package_name={self.package_name}, main_activities={self.main_activities})"
