import os
import platform
import subprocess
import time
from typing import Any

from loguru import logger

from frame.device import Device
from PIL import Image


class AvdController:
    avd_serial: str
    avd_name: str

    @staticmethod
    def start_avd(
        avd_name: str,
        avd_serial: str,
        kill_old: bool = True,
        wipe_data: bool = False,
        wait_timeout: int = 120,
        emulator_path: str = "emulator",
        snapshot: str | None = None,
    ):
        start_time = time.time()

        if kill_old:
            # adb -s emulator-5554 emu kill
            logger.info(f"Killing old AVD {avd_serial}")
            subprocess.run(["adb", "-s", avd_serial, "emu", "kill"])
            time.sleep(3)
        port = avd_serial.split("-")[-1]
        args = [emulator_path, "-avd", avd_name, "-port", str(port), "-noaudio"]
        if wipe_data:
            args.append("-wipe-data")
        if snapshot is not None:
            args.append("-snapshot")
            args.append(snapshot)

        system = platform.system()
        if system == "Windows":
            command = f"start cmd /c {' '.join(args)}"
            subprocess.Popen(command, shell=True, env=os.environ)
        else:
            command = " ".join(args)
            subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=os.environ,
            )

        if wait_timeout > 0:
            logger.debug("Wait 7.5s before check AVD ready...")
            time.sleep(7.5)

            def is_device_ready():
                for i in range(5):
                    res = subprocess.run(
                        [
                            "adb",
                            "-s",
                            avd_serial,
                            "shell",
                            "getprop",
                            "sys.boot_completed",
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    boot_completed = res.stdout.strip()
                    boot_error = res.stderr.strip()
                    if boot_error:
                        logger.warning(f"[AvdController] AVD {avd_name} emulator:{port} error({i+1}): {boot_error}")
                        time.sleep(5)
                    else:
                        break

                if boot_error:
                    raise Exception(f"AVD {avd_name} emulator:{port} start failed: {boot_error}")

                boot_anim = subprocess.run(
                    [
                        "adb",
                        "-s",
                        avd_serial,
                        "shell",
                        "getprop",
                        "init.svc.bootanim",
                    ],
                    stdout=subprocess.PIPE,
                    text=True,
                ).stdout.strip()

                return boot_completed == "1" and boot_anim == "stopped"

            check_interval = 2
            log_interval = 20
            last_log_time = 0
            logger.debug(f"Waiting for AVD {avd_name} emulator:{port} to be ready...")
            while not is_device_ready():
                now = time.time()
                if time.time() - start_time > wait_timeout:
                    logger.error(
                        "[AvdController] AVD {} emulator:{} start timeout",
                        avd_name,
                        port,
                    )
                    raise Exception(f"AVD {avd_name} emulator:{port} start timeout")

                if now - last_log_time >= log_interval:
                    logger.debug(f"Waiting for AVD {avd_name} emulator:{port} to be ready...")
                    last_log_time = now
                time.sleep(check_interval)

            logger.success("AVD started successfully in {}s", round(time.time() - start_time, 2))

    @classmethod
    def init(cls, avd_name: str, avd_serial: str):
        cls.avd_serial = avd_serial
        cls.avd_name = avd_name
        success, res = cls.exec(["avd", "status"])
        if success:
            logger.success("[AvdController] Avd status: {}", res.strip().split("\n")[0])
        else:
            raise Exception(res)

    @classmethod
    def exec(cls, command: list[str]):
        procress = subprocess.run(
            ["adb", "-s", cls.avd_serial, "emu", *command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )

        res = f"{procress.stdout}\n{procress.stderr}".strip()

        success = res.split("\n")[-1].startswith("OK")
        return success, res

    @classmethod
    def snapshot_list(cls) -> list[str]:
        success, snapshot_res = cls.exec(["avd", "snapshot", "list"])
        if not success:
            logger.error("[AvdController] Snapshot list failed: {}", snapshot_res)
            return []
        tags = []
        lines = snapshot_res.split("\n")
        if not lines[0].startswith("List of snapshots"):
            return []
        lines = lines[3:-1]
        for line in lines:
            if not line:
                continue
            line = line.strip()
            parts = line.split()
            tags.append(parts[1])
        return tags

    @classmethod
    def snapshot_save(cls, name: str, wait_time: int = 4):
        try:
            time.sleep(wait_time / 2)
            success, snapshot_res = cls.exec(["avd", "snapshot", "save", name])
            if not success:
                logger.error("[AvdController] Snapshot {} save failed: {}", name, snapshot_res)
                raise Exception(snapshot_res)
            else:
                logger.success("[AvdController] Snapshot {} save success", name)
                logger.info("[AvdController] Wait {} seconds", wait_time)
                time.sleep(wait_time)
            return success
        except Exception as e:
            raise Exception(f"Unable to save snapshot {name}: {e}")

    @classmethod
    def try_snapshot_load(cls, name: str, wait_time: int = 5, try_times: int = 3):
        error_messages = []
        for try_time in range(try_times):
            try:
                cls.snapshot_load(name, wait_time)
                return
            except Exception as e:
                logger.warning(
                    f"[AvdController] Attempt {try_time + 1}/{try_times} to load snapshot '{name}' failed: {e}"
                )
                error_messages.append(str(e))
                cls.start_avd(cls.avd_name, cls.avd_serial, kill_old=True, wipe_data=False, snapshot="empty")
        msg = "; ".join(error_messages)
        raise Exception(f"Failed to load snapshot '{name}' after {try_times} attempts : {msg}")

    @staticmethod
    def is_sampled_pixels_all_black(image: Image.Image, step: int = 50) -> bool:
        image = image.convert("RGB")
        width, height = image.size
        pixels: Any = image.load()

        for y in range(0, height, step):
            for x in range(0, width, step):
                r, g, b = pixels[x, y]
                if (r, g, b) != (0, 0, 0):
                    return False
        return True

    @classmethod
    def snapshot_load(cls, name: str, wait_time: int = 5):
        try:
            time.sleep(wait_time / 2)
            success, snapshot_res = cls.exec(["avd", "snapshot", "load", name])
            if not success:
                if not snapshot_res:
                    snapshot_res = "Avd crashed"
                logger.error("[AvdController] Snapshot {} load failed: {}", name, snapshot_res)
                raise Exception(snapshot_res)
            else:
                logger.info("[AvdController] Wait {} seconds", wait_time)
                time.sleep(wait_time)

            logger.debug("[AvdController] Validate snapshot loading state...")
            if not Device.connected:
                Device.connect(cls.avd_serial)

            image = Device.screenshot()
            image = image.convert("RGB")
            if cls.is_sampled_pixels_all_black(image):
                raise Exception(f"Unable to load snapshot {name}: fully black screen")

            logger.success("[AvdController] Snapshot {} load success", name)

        except Exception as e:
            raise Exception(f"Unable to load snapshot {name}: {e}")

    @classmethod
    def snapshot_delete(cls, name: str):
        success, snapshot_res = cls.exec(["avd", "snapshot", "delete", name])
        if not success:
            logger.error("[AvdController] Snapshot {} delete failed: {}", name, snapshot_res)
        else:
            logger.success("[AvdController] Snapshot {} delete success", name)
        return success
