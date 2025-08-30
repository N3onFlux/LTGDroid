import argparse
import os.path
import sys
import time
from typing import Type

from explore import Explore
from frame.avd_controller import AvdController
from frame.apk import Apk
from frame.device import Device
from frame.llm import LLM, Model
from frame.recorder import Recorder
from frame.limiter import Limiter
from frame.utils import ensure_dir, timestamp, load_json, ImageUtils, GraphPersistence
from loguru import logger

from explore_recorder import ExploreRecorder
from tasks.utils import BaseTask


def init(
    apk: Apk,
    max_minutes: int,
    max_transitions: int,
    task: Type[BaseTask] | None,
    output: str | None,
):
    if output is None:
        if task is not None:
            result_dir = f"working/result/{apk.package_name}/{task.__name__}-{timestamp()}"
        else:
            result_dir = f"working/result/{apk.package_name}/{timestamp()}"
    else:
        result_dir = output

    result_dir = os.path.abspath(result_dir)

    logger.remove()
    logger.add(
        sink=sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | <level>{message}</level>",
    )
    logger.add(
        sink=f"{result_dir}/log.txt",
        format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | <level>{message}</level>",
    )

    ensure_dir(f"{result_dir}/scenes")
    ensure_dir(f"{result_dir}/transitions")

    Recorder.init(result_dir)
    ImageUtils.init(result_dir)
    GraphPersistence.init(result_dir)
    ExploreRecorder.init(result_dir)
    Limiter.init(max_minutes, max_transitions)

    return result_dir


def main():
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-avd_name", type=str, required=True)
    parser.add_argument("-avd_port", type=int, required=False, default=5554)
    parser.add_argument("-apk_name", type=str, required=True)
    parser.add_argument("-task_name", type=str, required=False, default=None)
    parser.add_argument("-task_description", type=str, required=False, default=None)
    parser.add_argument("-bug_name", type=str, required=False, default=None)
    parser.add_argument(
        "-max_minute",
        type=int,
        required=False,
        default=120,
        help="Maximum exploring time in minutes",
    )
    parser.add_argument(
        "-max_transition",
        type=int,
        required=False,
        default=100,
        help="Maximum exploring events",
    )
    parser.add_argument(
        "-max_step",
        type=int,
        required=False,
        default=20,
        help="Maximum exploring steps",
    )
    parser.add_argument(
        "-action_delay",
        type=int,
        required=False,
        default=2,
        help="Delay after action execution",
    )
    parser.add_argument(
        "-llm_first_branch_limit",
        type=int,
        required=False,
        default=6,
        help="Maximum number of widget branches after first stage pruning",
    )
    parser.add_argument(
        "-llm_second_branch_limit",
        type=int,
        required=False,
        default=3,
        help="Maximum number of action branches after second stage pruning",
    )
    parser.add_argument(
        "-output",
        type=str,
        required=False,
        default=None,
        help="Output directory, default to working/result/{package_name}/{task_name}-{timestamp}",
    )

    args = parser.parse_args()

    avd_name = args.avd_name
    avd_port = args.avd_port
    apk_name = args.apk_name
    task_name = args.task_name
    bug_name = args.bug_name
    task_description = args.task_description
    max_step = args.max_step
    action_delay = args.action_delay
    max_minutes = args.max_minute
    max_transitions = args.max_transition
    output = args.output

    llm_second_branch_limit = args.llm_second_branch_limit
    llm_first_branch_limit = args.llm_first_branch_limit

    if bug_name is not None:
        task = None
        task_description = ""
    else:
        if task_name is not None:
            from tasks import get_task_class_by_task_name

            task, _ = get_task_class_by_task_name(task_name)
            task_description = task.task_description
        else:
            task = None

        if task is None and task_description is None:
            raise Exception("task_description is required when task is not specified")
        elif task_description is None and task is not None:
            task_description = task.task_description

    start(
        avd_name=avd_name,
        avd_port=avd_port,
        max_step=max_step,
        action_delay=action_delay,
        llm_second_branch_limit=llm_second_branch_limit,
        llm_first_branch_limit=llm_first_branch_limit,
        max_minutes=max_minutes,
        max_transitions=max_transitions,
        apk_name=apk_name,
        task_description=task_description,
        task=task,
        bug_name=bug_name,
        output=output,
    )


def summary_bug_s2r_by_llm(bug_name: str):
    logger.info(f"Summary steps to reproduce bug: {bug_name}")
    bug_config = load_json(f"bugs/{bug_name}.json")
    repo: str = bug_config["repo"]
    title: str = bug_config["title"]
    body: str = bug_config["body"]
    comments: list[str] = bug_config["comments"]

    comments_content = []
    for index, comment in enumerate(comments, 1):
        comments_content.append(f"=======Issue comment {index}=======")
        comments_content.append(comment)

    prompt = f"""
=======Issue title=======
{repo} - {title}
=======Issue body=======
{body}
{"\n".join(comments_content)}

---

Analyze the provided GitHub issue content, which includes the repository name, issue title, issue body, and any related comments. Based on this information, extract a clear, step-by-step workflow that an LLM agent should follow to manually reproduce the reported bug in the specified Android app. For each step, detail the exact user actions and specify any input values or parameters mentioned in the issue.
Present your findings as a concise, well-structured ordered list of steps that accurately reflect the bug reproduction process, using only information from the provided issue content. Avoid adding assumptions or additional details beyond what is documented.
Finally, summarize the specific and observable error in the app’s user interface (such as a crash, freeze, or missing UI element) that serves as clear evidence the bug has been successfully reproduced.
    """.strip()

    s2r = LLM.chat(prompt)
    ExploreRecorder.record_summary_s2r(prompt, s2r)
    return s2r


def init_app(apk: Apk, task: Type[BaseTask] | None):
    try:
        Device.set_proxy()
        Device.set_immersive()
        Device.install_app(apk.apk_path)
        Device.clear_app(apk.package_name)
        Device.start_app(apk.package_name)
        time.sleep(1)

        if task is not None:
            logger.info("[Task] run precondition...")
            task(Device.device).precondition()
    except Exception as e:
        logger.exception(e)
        ExploreRecorder.record_explore_error(str(e))
        return False

    return True


def start(
    max_step: int,
    llm_second_branch_limit: int,
    llm_first_branch_limit: int,
    max_minutes: int,
    max_transitions: int,
    action_delay: int,
    apk_name: str,
    avd_name: str,
    avd_port: int,
    task_description: str,
    task: Type[BaseTask] | None,
    bug_name: str | None,
    output: str | None = None,
):

    apk = Apk(apk_name=apk_name)
    result_dir = init(apk, max_minutes, max_transitions, task, output)

    env = load_json("env.json")
    llm_service = env["llm_service"]
    llm_config = env[llm_service]

    LLM.init(
        name=llm_service,
        api_key=llm_config["api_key"],
        base_url=llm_config["base_url"],
        temperature=0.0,
        text_model=Model(llm_config["text_model"]),
        image_model=Model(llm_config["image_model"]),
        format_model=Model(llm_config["format_model"]),
    )

    if bug_name is not None:
        task_description = summary_bug_s2r_by_llm(bug_name)
    if task is not None:
        action_delay = task.action_delay

    device_serial = f"emulator-{avd_port}"

    try:
        logger.info(f"Connecting to device {device_serial}")
        Device.connect(device_serial)
        AvdController.init(avd_name, device_serial)
        AvdController.snapshot_load("empty")
        Device.u2_ime_set(True)
    except:
        AvdController.start_avd(
            avd_name,
            device_serial,
            kill_old=True,
            wipe_data=True,
            wait_timeout=120,
        )
        Device.connect(device_serial)
        Device.u2_ime_set(True)

        AvdController.init(avd_name, device_serial)
        AvdController.snapshot_save("empty")

    if not init_app(apk, task):
        logger.info("[Limiter] {}", Limiter.time_consumption())
        LLM.record_token_usage(result_dir)
        return

    logger.info("[Explore] wait 3s before exploring...")
    time.sleep(3)

    try:
        Explore.explore(
            apk,
            result_dir,
            task_description,
            max_step,
            llm_second_branch_limit,
            llm_first_branch_limit,
            action_delay,
        )
        Explore.clear_snapshots()
    except KeyboardInterrupt:
        logger.error("[Explore] KeyboardInterrupt")
        ExploreRecorder.record_explore_error(f"run time error: KeyboardInterrupt")
    except Exception as e:
        logger.exception(e)
        ExploreRecorder.record_explore_error(str(e))

    LLM.record_token_usage(result_dir)
    logger.info("[Limiter] {}", Limiter.time_consumption())


if __name__ == "__main__":
    main()
