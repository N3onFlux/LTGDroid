import math
import time
from collections import deque
from itertools import islice
from typing import TYPE_CHECKING, Type

from PIL.Image import Image
from loguru import logger

from frame.avd_controller import AvdController
from frame.device import Device, AppInfo
from frame.llm import LLM
from frame.limiter import Limiter
from frame.transition import Transition
from networkx import MultiDiGraph

from frame.utils import ImageUtils, unique_file_with_id_path, GraphPersistence
from explore_recorder import ExploreRecorder
from tasks.utils import BaseTask

if TYPE_CHECKING:
    from frame.action import Action
    from frame.apk import Apk
    from frame.scene import Scene
    from frame.widget import Widget


class GraphNode:
    scene_id: str
    total_action_num: int

    def __init__(self, scene_id: str, total_action_num: int):
        self.scene_id = scene_id
        self.total_action_num = total_action_num


class ExploringNode:
    scene: "Scene"
    scene_id: str
    app_info: AppInfo
    scene_image: Image
    exploring_path: list[Transition]
    available_actions: list["Action"]
    parent_scene_id: str | None

    def __init__(
        self,
        scene: "Scene",
        app_info: AppInfo,
        scene_image: Image,
        available_actions: list["Action"],
        exploring_path: list[Transition],
        parent_scene_id: str | None,
    ):
        self.scene = scene
        self.app_info = app_info
        self.scene_image = scene_image
        self.available_actions = available_actions
        self.exploring_path = exploring_path
        self.parent_scene_id = parent_scene_id

        self.scene_id = scene.scene_id

    def to_prompt(self) -> str:
        transition_lines = []

        length = len(self.exploring_path)
        for index, transition in enumerate(self.exploring_path):
            short = (length - index) > 3  # only the last three transitions are fully displayed
            transition_lines.append(f"- {transition.to_prompt(short)}")

        return "\n".join(transition_lines)


class Explore:
    task: Type[BaseTask] | None
    STG: MultiDiGraph
    stg_node_dict: dict[str, GraphNode]
    apk: "Apk"
    result_dir: str
    task_description: str
    max_step: int
    action_delay: int
    llm_second_branch_limit: int
    llm_first_branch_limit: int

    @classmethod
    def restore_node_from_empty(cls, node: ExploringNode):
        AvdController.start_avd(
            AvdController.avd_name, AvdController.avd_serial, kill_old=True, wipe_data=False, snapshot="empty"
        )
        time.sleep(3)
        import main

        if not main.init_app(cls.apk, cls.task):
            raise Exception("Restore node state from empty snapshot failed: init app failed")

        time.sleep(3)
        try:
            for transition in node.exploring_path:
                transition.action.execute(wait_time=cls.action_delay)
        except Exception as e:
            raise Exception(f"Restore node state from empty snapshot failed: {e}")

    @classmethod
    def scene_available_actions(cls, scene: "Scene") -> list["Action"]:
        from frame.action import Action

        out = []

        def _post_order(widget: "Widget"):
            for w in widget.children:
                _post_order(w)
            # flag_list = [_post_order(widget) for widget in widget.children]
            # if any(flag_list):
            #     return True  # stop

            actions = widget.available_actions()
            if actions:
                out.extend(actions)
                # return True  # stop
            # return False  # continue

        _post_order(scene.widget_tree)

        out.extend(
            [
                Action.press_action(scene.scene_id, "back"),
                Action.press_action(scene.scene_id, "enter"),
                Action.press_action(scene.scene_id, "delete"),
                Action.press_action(scene.scene_id, "home"),
                Action.swipe_action(scene.scene_id, "up"),
                Action.swipe_action(scene.scene_id, "down"),
                Action.swipe_action(scene.scene_id, "left"),
                Action.swipe_action(scene.scene_id, "right"),
                Action.rotate_action(scene.scene_id, "landscape"),
                Action.rotate_action(scene.scene_id, "portrait"),
            ]
        )
        return out

    @classmethod
    def record_current_scene(cls):
        cur_app_info = Device.active_app_info()
        cur_scene_image = Device.screenshot()

        # if cur_app_info.package != cls.apk.package_name:
        cur_scene = Device.current_scene(None, {"com.android.systemui", "com.github.uiautomator"})
        # else:
        #     cur_scene = Device.current_scene(cls.apk.package_name)

        available_actions = cls.scene_available_actions(cur_scene)

        # new scene
        new_scene_flag = False
        if cur_scene.scene_id not in cls.stg_node_dict:
            new_stg_node = GraphNode(cur_scene.scene_id, len(available_actions))
            cls.stg_node_dict[cur_scene.scene_id] = new_stg_node
            Explore.STG.add_node(new_stg_node)
            ExploreRecorder.record_add_graph_node(new_stg_node)
            ImageUtils.save_cur_scene_image(cur_scene, cur_scene_image)
            GraphPersistence.save_scene(cur_scene)
            new_scene_flag = True

        return (
            cur_scene,
            cur_app_info,
            cur_scene_image,
            available_actions,
            new_scene_flag,
        )

    @classmethod
    def clear_snapshots(cls, not_clear=None):
        if not_clear is None:
            not_clear = []
        not_clear.extend(["default_boot", "empty"])
        not_clear = set(not_clear)
        logger.info("[Explore] Clear snapshots")
        tags = AvdController.snapshot_list()
        clear = [tag for tag in tags if tag not in not_clear]
        for tag in clear:
            AvdController.snapshot_delete(tag)
        logger.success("[Explore] Clear {} snapshots", len(clear))

    @classmethod
    def prune_exploring_nodes_by_llm(
        cls, queue: deque[ExploringNode]
    ) -> tuple[list[ExploringNode], list[ExploringNode], list[ExploringNode]]:
        queue_lines = []
        for index, node in enumerate(queue, 1):
            queue_lines.append(f"**Path ID:** {index}\n**Path detail of ID {index}**:\n{node.to_prompt()}")

        prompt = f'''
We are exploring the correct paths to reproduce the following bug by given Steps to Reproduce in the Android app:

Package Name: {cls.apk.package_name}  
Steps to Reproduce the Bug:
{cls.task_description}  

Current Status:  
- There are {len(queue)} exploration paths in progress, each with a unique ID.

Exploration Paths with IDs:  

{'\n\n---\n\n'.join(queue_lines)}

---

Extra Guidance:
1. App installation and first app launch are not reflected in the Exploration Path descriptions.
2. Some initialization steps are necessary before reproducing the bug, such as granting permissions, closing update dialogs, progressing through or skipping onboarding screens, or consenting to data collection prompts.
3. After a fresh installation, the app usually contains no data, so creating the necessary data specified in the Steps to Reproduce the Bug is essential.
4. If certain exploration paths fall into a loop, such paths are not worth continuing to explore.

Request:  
1. For each exploration path, evaluate its progress:  
    - Determine whether the path should be continued, based on its potential to successfully complete the Steps to Reproduce the Bug.
    - Identify whether the path has already successfully completed the Steps to Reproduce the Bug.
2. After evaluating all exploration paths, summarize the results:
    - Provide two separate lists of path IDs:
        1. One list for paths that are worth continuing due to promising potential.
            - If multiple paths exhibit identical behavior or outcomes, retain only the one that appears most promising to complete the reproduction steps.
            - If there are more than {cls.llm_second_branch_limit} such paths, include only the top {cls.llm_second_branch_limit} most promising ones.
            - If there are {cls.llm_second_branch_limit} or fewer such paths, include all of them.
            - If no paths have successfully completed the Steps to Reproduce the Bug **and** you also determine that no paths are worth continuing, then provide at least one path that appears most likely to complete the reproduction steps, rather than excluding all paths.
        2. Another list for paths that have already successfully completed the Steps to Reproduce the Bug.
                '''.strip()

        res = LLM.chat(prompt)
        formatted_res = LLM.format_to_json(
            res,
            f"""
{{
    path_id_array_with_potential: number[]; // An array of path IDs with promising potential to complete the Steps to Reproduce the Bug. If there are more than {cls.llm_second_branch_limit}, only the top {cls.llm_second_branch_limit} most promising ones are included.
    path_id_array_completed: number[]; // An array of number containing the exploration path IDs that have successfully completed the Steps to Reproduce the Bug.
}}
            """.strip(),
        )
        with_potential = formatted_res["path_id_array_with_potential"]
        task_achieved = formatted_res["path_id_array_completed"]

        total = set(int(num) for num in task_achieved + with_potential)
        achieved = set(int(num) for num in task_achieved)
        removed = set(num for num in range(1, len(queue) + 1) if num not in total)

        total, total_index = [queue[i - 1] for i in total], [i for i in total]
        achieved, achieved_index = [queue[i - 1] for i in achieved], [i for i in achieved]
        removed, removed_index = [queue[i - 1] for i in removed], [i for i in removed]
        ExploreRecorder.record_prune_exploring_nodes(
            prompt,
            res,
            formatted_res,
            total,
            achieved,
            removed,
            total_index,
            achieved_index,
            removed_index,
        )
        return total, achieved, removed

    @classmethod
    def check_log_crash(cls):
        log = Device.logcat_crash()
        if "FATAL EXCEPTION" in log:
            return True
        Device.logcat_clear()
        return False

    # @classmethod
    # def check_permission(cls):
    #     cur_app_info = Device.active_app_info()
    #     if (
    #         cur_app_info.package == "com.android.packageinstaller"
    #         or cur_app_info.package == "com.google.android.packageinstaller"
    #     ):
    #         stop = False
    #         while stop != True:
    #             try:
    #                 Device.device.xpath(
    #                     '//*[@resource-id="com.android.packageinstaller:id/permission_allow_button"]'
    #                 ).click(timeout=0.5)
    #                 logger.success("[Explore] Permission granted")
    #                 time.sleep(cls.action_delay)
    #             except:
    #                 stop = True

    @classmethod
    def check_input_action(cls, action: "Action", cur_node: ExploringNode) -> "Action":
        if action.action_type.name == "InputText" and action.addition == "::random::":
            action.addition = action.gen_text_about_task(cls.apk.package_name, cls.task_description, cur_node)
        return action

    @classmethod
    def validate_exploring_complete_by_llm(cls, achieved_nodes: list[ExploringNode]) -> list[ExploringNode]:
        achieved, achieved_index = [], []
        final_prompt, final_res, final_formatted_res = [], [], []

        for index, node in enumerate(achieved_nodes, 1):
            prompt = f"""
You are required to determine if the provided exploring path within the {cls.apk.package_name} Android app has definitively completed the the Steps to Reproduce the Bug.

Steps to Reproduce the Bug:
{cls.task_description}

Exploring Path: 
{node.to_prompt()}

Current App UI State: The attached image represents the visual state reached after executing the exploring path.

Instructions:
- Carefully analyze the exploring path steps and the current UI state shown in the image.
- Compare the UI state and any observed on-screen feedback, indicators, or confirmation messages with the explicit criteria defined by the Steps to Reproduce the Bug.
- Confirm the completion of the Steps to Reproduce the Bug only if all conditions in the Steps to Reproduce the Bug have been satisfied based on the sequence of actions in the exploring path and visible evidence in the image.
        """.strip()

            res = LLM.chat_with_image(prompt, node.scene_image)
            formatted_res = LLM.format_to_json(
                res,
                """
{
    task_achieved: boolean; // Whether the exploring path has definitively completed the the Steps to Reproduce the Bug.
}
                """.strip(),
            )
            task_achieved = str(formatted_res["task_achieved"]).lower()
            task_achieved = task_achieved == "yes" or task_achieved == "true"
            if task_achieved:
                achieved.append(node)
                achieved_index.append(index)

            final_prompt.append(prompt)
            final_res.append(res)
            final_formatted_res.append(formatted_res)

        ExploreRecorder.record_validate_exploring_complete(
            "\n\n---\n\n".join(final_prompt),
            "\n\n---\n\n".join(final_res),
            final_formatted_res,
            achieved,
            achieved_index,
        )
        return achieved

    @classmethod
    def store_complete_path(cls, achieved_node: ExploringNode):
        file_path = unique_file_with_id_path(cls.result_dir, "achieved-path", "md")
        steps = []
        for index, transition in enumerate(achieved_node.exploring_path, 1):
            step = f"""
### Step {index}

- **Action:** {transition.action.to_prompt()}
- **Transition:** {transition.to_prompt()}

<img src="transitions/{transition.transition_id}.png" alt="step_{index}" style="display: block; margin: 0 auto; height: 512px">
            """.strip()
            steps.append(step)

        content = f'''
## Task Overview

### App Package

{cls.apk.package_name}  

### Steps to Reproduce the Bug

{cls.task_description}

## Explored Path

The length of the explored path is {len(achieved_node.exploring_path)}.

{"\n\n".join(steps)}

## Final Scene

<img src="scenes/{achieved_node.scene_id}.png" alt="final_scene" style="display: block; margin: 0 auto; height: 512px">

        '''.strip()

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.success("[Explore] Store complete path to {}", file_path)
        return file_path

    @classmethod
    def refine_action_widgets_by_llm(cls, available_actions: list["Action"], current_node: ExploringNode):
        from frame.action import ActionType

        out_available_actions: list["Action"] = []

        action_widgets: list[Widget] = []
        widgets_id_set: set[str] = set()
        potential_widget_id_set: set[str] = set()

        potential_operations_flags = {
            "press back": False,
            "press enter": False,
            "press delete": False,
            "press home": False,
            "swipe down": False,
            "swipe up": False,
            "swipe left": False,
            "swipe right": False,
            "rotate landscape": False,
            "rotate portrait": False,
        }

        for action in available_actions:
            if action.widget is not None:
                if action.widget.widget_id not in widgets_id_set:
                    action_widgets.append(action.widget)
                    widgets_id_set.add(action.widget.widget_id)

        if LLM.image_model.value.startswith("glm"):
            group_size = 20
        else:
            group_size = 100

        num_groups = max(math.ceil(len(action_widgets) / group_size), 1)
        record = {
            "prompt": [],
            "res": [],
            "formatted_res": [],
            "before_image": [],
            "after_image": [],
        }

        for group_index in range(num_groups):
            group_action_widgets = list(
                islice(
                    action_widgets,
                    group_index * group_size,
                    (group_index + 1) * group_size,
                )
            )
            group_action_widgets_image = current_node.scene_image.copy()
            ImageUtils.draw_widget_bounds(group_action_widgets, group_action_widgets_image, draw_index=True)

            if len(current_node.exploring_path):
                exploring_status_prompt = f"""
    - We have previously assessed {len(current_node.exploring_path)} steps to advance towards the completion of Steps to Reproduce the Bug, outlined as follows:
    {current_node.to_prompt()}
    - We are preparing to analyze the next steps for interaction with specific interactive widgets listed below, all of which are marked in red box in the provided image along with their respective IDs.
                """.strip()
            else:
                exploring_status_prompt = f"- We are focusing on the first step of exploring interactions with the specific interactive widgets listed below, all of which are marked in red box in the provided image along with their respective IDs."

            lines = []
            for index, widget in enumerate(group_action_widgets, 1):
                lines.append(f"ID: {index}\n{widget.to_prompt_xml_tree()}")

            prompt = f'''
We are exploring the correct paths to reproduce the following bug based on the given Steps to Reproduce in the Android app:

Package Name: {cls.apk.package_name}
Steps to Reproduce the Bug:
{cls.task_description}  

Current Exploration Status:  
{exploring_status_prompt}

Details of Interactive Widgets:
{'\n\n---\n\n'.join(lines)}

Extra Guidance:
1. App installation and first app launch are not reflected in the Exploration Path descriptions.
2. Some initialization steps are necessary before reproducing the bug, such as granting permissions, closing update dialogs, progressing through or skipping onboarding screens, or consenting to data collection prompts.
3. After a fresh installation, the app usually contains no data, so creating the necessary data specified in the Steps to Reproduce the Bug is essential.
4. If completing the final reproduction step doesn't trigger the bug behavior, a press back operation might be required.

---

Request:  
Carry out the following precise steps：
1. For each interactive widget detailed in the 'Details of Interactive Widgets' section, assess whether interaction with this widget could reasonably serve as a next step toward advancing progress in completing the given Steps to Reproduce the Bug.
2. Evaluate the likelihood that the following global operations could plausibly serve as next actions that help move the app state closer to bug reproduction, given the current screen state (as shown in the provided image).
    - global operations: press back, press home, press enter, press delete, swipe up, swipe down, swipe left, swipe right, rotate landscape, rotate portrait
3. Summarize the final results:
    - Summarize the widget IDs from step 1 that are likely to contribute to complete the Steps to Reproduce the Bug, titled **Summary of Most Promising Widgets**.
    - Summarize the global operations from step 2 that are likely to contribute to completing the Steps to Reproduce the Bug, titled **Summary of Most Promising Operations**.
    - If there are more than {cls.llm_first_branch_limit} such widgets or operations, include only the top {cls.llm_first_branch_limit} most promising ones.
    - If there is no such widget or operation, then provide at least one widget or operation that appears most likely to contribute, rather than excluding all of them.
            '''.strip()

            res = LLM.chat_with_image(prompt, group_action_widgets_image)

            formatted_res = LLM.format_to_json(
                res,
                """
{
    most_promising_widget_id_array: number[]; // An array of number containing the 'widget IDs' in **Summary of Most Promising Widgets**.
    most_promising_operation_array: string[]; // An array of string containing the 'global operations' in **Summary of Most Promising Operations**.
}
                    """.strip(),
            )
            potential_widget_index = formatted_res["most_promising_widget_id_array"]
            potential_widget_index = [int(num) for num in potential_widget_index]

            potential_operations: list[str] = formatted_res["most_promising_operation_array"]
            potential_operations = [op.strip('"').lower() for op in potential_operations]

            for i in potential_widget_index:
                w = group_action_widgets[i - 1]
                potential_widget_id_set.add(w.widget_id)
            for op in potential_operations:
                if op in potential_operations_flags:
                    potential_operations_flags[op] = True

            from PIL import ImageDraw

            # draw potential widgets image
            group_potential_action_widgets_image = current_node.scene_image.copy()
            draw = ImageDraw.Draw(group_potential_action_widgets_image)
            for i in potential_widget_index:
                w = group_action_widgets[i - 1]
                xy = (w.bounds.left, w.bounds.top), (w.bounds.right, w.bounds.bottom)
                draw.rectangle(xy, outline="green", width=5)
                draw.text(
                    (w.bounds.left + 5, w.bounds.top + 5),
                    str(i),
                    fill="green",
                    font=ImageUtils.font,
                )

            record["prompt"].append(prompt)
            record["res"].append(res)
            record["formatted_res"].append(formatted_res)
            record["before_image"].append(group_action_widgets_image)
            record["after_image"].append(group_potential_action_widgets_image)

        for action in available_actions:
            if action.action_type == ActionType.Swipe:
                if potential_operations_flags[f"swipe {action.addition}"]:
                    out_available_actions.append(action)
            elif action.action_type == ActionType.Press:
                if potential_operations_flags[f"press {action.addition}"]:
                    out_available_actions.append(action)
            elif action.action_type == ActionType.Rotate:
                if potential_operations_flags[f"rotate {action.addition}"]:
                    out_available_actions.append(action)
            else:
                w = action.widget
                if w is not None and w.widget_id in potential_widget_id_set:
                    out_available_actions.append(action)

        prompt = "\n===================\n".join(record["prompt"])
        res = "\n===================\n".join(record["res"])
        formatted_res = {index: f for index, f in enumerate(record["formatted_res"], 1)}
        before_image = ImageUtils.concat_images(record["before_image"])
        after_image = ImageUtils.concat_images(record["after_image"])
        ExploreRecorder.record_refine_action_widgets(
            prompt,
            res,
            formatted_res,
            current_node.scene_id,
            before_image,
            after_image,
            False,
        )

        return out_available_actions

    @classmethod
    def explore(
        cls,
        apk: "Apk",
        result_dir: str,
        task_description: str,
        max_step: int,
        llm_second_branch_limit: int,
        llm_first_branch_limit: int,
        action_delay: int,
        task: Type[BaseTask] | None = None,
    ):
        cls.task = task
        cls.apk = apk
        cls.result_dir = result_dir
        cls.action_delay = action_delay
        cls.task_description = task_description
        cls.llm_second_branch_limit = llm_second_branch_limit
        cls.llm_first_branch_limit = llm_first_branch_limit
        cls.STG = MultiDiGraph()
        cls.stg_node_dict = dict()

        logger.debug("Apk: {}", apk.apk_path)
        logger.debug("Task description: {}", task_description)
        logger.debug("Result dir: {}", result_dir)
        logger.debug("Max step: {}", max_step)
        logger.debug("Action delay: {}", action_delay)
        logger.debug("LLM branch limit: {}", llm_second_branch_limit)
        logger.debug("Max explore time: {}", Limiter.format_duration(Limiter.max_minutes * 60))

        cls.clear_snapshots()

        logger.info("[Explore] Start exploring {}...", apk.package_name)

        (
            cur_scene,
            cur_app_info,
            cur_scene_image,
            cur_available_actions,
            new_scene_flag,
        ) = cls.record_current_scene()
        queue: deque[ExploringNode] = deque(
            [
                ExploringNode(
                    scene=cur_scene,
                    app_info=cur_app_info,
                    scene_image=cur_scene_image,
                    available_actions=cur_available_actions,
                    exploring_path=[],
                    parent_scene_id=None,
                )
            ]
        )
        AvdController.snapshot_save(cur_scene.scene_id)

        level_index = 0
        while queue:
            level_index += 1
            level_size = len(queue)

            if level_index > max_step:
                logger.error(
                    "[Explore] Failed to accomplish task, max steps reached: {}",
                    max_step,
                )
                ExploreRecorder.record_explore_fail(f"max steps reached: {max_step}")
                return None

            logger.info("[Explore] Exploring step {} with {} scene", level_index, level_size)

            for _ in range(level_size):
                node = queue.popleft()
                # enter target scene
                logger.info("[Explore] Entering target scene: {}", node.scene.scene_id)

                # If root node, no need to re-enter
                if node.parent_scene_id is not None:
                    try:
                        AvdController.try_snapshot_load(node.scene_id, try_times=2)
                    except Exception as e:
                        logger.warning("[Explore] {}", e)
                        cls.restore_node_from_empty(node)

                ExploreRecorder.record_update_current_scene(node.scene_id)

                cur_scene, cur_app_info, cur_scene_image, cur_available_actions = (
                    node.scene,
                    node.app_info,
                    node.scene_image,
                    node.available_actions,
                )

                cur_available_actions = cls.refine_action_widgets_by_llm(cur_available_actions, node)

                for action_index, action in enumerate(cur_available_actions):
                    action = cls.check_input_action(action, node)

                    action.try_execute(wait_time=cls.action_delay)
                    # no skip when execute failed

                    # cls.check_permission()

                    (
                        next_scene,
                        next_app_info,
                        next_scene_image,
                        next_available_actions,
                        new_scene_flag,
                    ) = cls.record_current_scene()
                    ExploreRecorder.record_update_current_scene(next_scene.scene_id)

                    # record transition
                    if not new_scene_flag:
                        if next_scene.scene_id == cur_scene.scene_id:
                            # when scene not change
                            logger.warning("[Explore] Scene not change: {}", next_scene.scene_id)
                            ui_transition = "Scene not change"
                        else:
                            # when scene already explored
                            logger.warning(
                                "[Explore] Scene already explored: {}",
                                next_scene.scene_id,
                            )
                            ui_transition = "Enter already explored scene"

                        transition = Transition(
                            action,
                            cur_scene.scene_id,
                            next_scene.scene_id,
                            cur_app_info,
                            next_app_info,
                            ui_transition,
                            ui_transition,
                        )
                        ImageUtils.save_transition_image(transition, cur_scene_image.copy())
                        GraphPersistence.save_transition(transition)
                        Explore.STG.add_edge(
                            cls.stg_node_dict[cur_scene.scene_id],
                            cls.stg_node_dict[next_scene.scene_id],
                            transition=transition,
                            level=level_index,
                        )
                        ExploreRecorder.record_add_graph_transition(transition, level_index)
                        ExploreRecorder.record_disable_transition(transition.transition_id)
                        Limiter.transitions_count += 1
                    else:
                        # when normal case
                        # add transition edge

                        ui_transition, one_sentence_summary = Transition.gen_ui_transition(
                            action,
                            cur_scene_image.copy(),
                            next_scene_image.copy(),
                            cur_app_info,
                            next_app_info,
                        )

                        transition = Transition(
                            action,
                            cur_scene.scene_id,
                            next_scene.scene_id,
                            cur_app_info,
                            next_app_info,
                            ui_transition,
                            one_sentence_summary,
                        )
                        ImageUtils.save_transition_image(transition, cur_scene_image.copy())
                        GraphPersistence.save_transition(transition)
                        Explore.STG.add_edge(
                            cls.stg_node_dict[cur_scene.scene_id],
                            cls.stg_node_dict[next_scene.scene_id],
                            transition=transition,
                            level=level_index,
                        )
                        ExploreRecorder.record_add_graph_transition(transition, level_index, False)
                        Limiter.transitions_count += 1

                        # add node to queue
                        new_exploring_path = [*node.exploring_path, transition]
                        new_exploring_node = ExploringNode(
                            scene=next_scene,
                            app_info=next_app_info,
                            scene_image=next_scene_image,
                            available_actions=next_available_actions,
                            exploring_path=new_exploring_path,
                            parent_scene_id=node.scene_id,
                        )
                        queue.append(new_exploring_node)

                        # check app crash
                        is_crashed = cls.check_log_crash()
                        if is_crashed:
                            logger.success("[Explore] Successfully completed bug reproduction with app crashed")
                            ExploreRecorder.record_track_crash_completion(new_exploring_node)
                            file_list = [cls.store_complete_path(new_exploring_node)]
                            ExploreRecorder.record_explore_success(file_list)
                            return True

                        AvdController.snapshot_save(new_exploring_node.scene_id)

                    if action_index != len(node.available_actions) - 1:
                        try:
                            AvdController.try_snapshot_load(node.scene_id, try_times=2)
                        except Exception as e:
                            logger.warning("[Explore] {}", e)
                            cls.restore_node_from_empty(node)

                        ExploreRecorder.record_update_current_scene(node.scene_id)

                    if Limiter.check_max_time():
                        ExploreRecorder.record_explore_fail(f"Max explore time reached: {Limiter.time_consumption()}")
                        return None

                    if Limiter.check_max_transitions():
                        ExploreRecorder.record_explore_fail(
                            f"Max explore transitions reached: {Limiter.transitions_count}"
                        )
                        return None

            if len(queue) == 0:
                logger.error(
                    "[Explore] Failed to accomplish task, no more exploring nodes at step {}",
                    level_index,
                )
                ExploreRecorder.record_explore_fail(f"no more exploring nodes at step {level_index}")
                return None
            # prune exploring nodes by llm
            total_nodes, achieved_nodes, removed_nodes = cls.prune_exploring_nodes_by_llm(queue)

            # record transition id being removed
            removed_ids = [node.exploring_path[-1].transition_id for node in removed_nodes]
            ExploreRecorder.record_remove_exploring_transition(removed_ids)

            if not total_nodes:
                logger.error(
                    "[Explore] Failed to accomplish task, no potential exploring path that LLM agree with at step {}",
                    level_index,
                )
                ExploreRecorder.record_explore_fail(
                    f"no potential exploring path that LLM agree with at step {level_index}"
                )
                return None

            if achieved_nodes:
                # validate complete again
                achieved = cls.validate_exploring_complete_by_llm(achieved_nodes)
                if achieved:
                    file_list = [cls.store_complete_path(node) for node in achieved]
                    ExploreRecorder.record_explore_success(file_list)
                    return True

            queue.clear()
            queue.extend(total_nodes)

            not_clear = [node.scene_id for node in queue]
            cls.clear_snapshots(not_clear)
