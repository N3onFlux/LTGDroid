import json
import time
from enum import Enum
from typing import TYPE_CHECKING, Any

from loguru import logger

from frame.device import Device
from frame.llm import LLM
from frame.recorder import Recorder
from frame.utils import ImageUtils, generate_random_char_list, hash_hex

if TYPE_CHECKING:
    from frame.widget import Widget
    from explore import ExploringNode


class ActionType(Enum):
    Click = 0
    LongClick = 1
    InputText = 2
    Press = 3
    Swipe = 4
    Rotate = 5


class Action:
    scene_id: str
    action_id: str

    widget: "Widget|None"
    action_type: ActionType
    addition: Any

    @staticmethod
    def press_action(scene_id: str, key: str):
        key = key.strip().lower()
        if key in ["enter", "back", "home", "delete"]:
            return Action(scene_id, widget=None, action_type=ActionType.Press, addition=key)
        return Action(scene_id, widget=None, action_type=ActionType.Press, addition="back")

    @staticmethod
    def swipe_action(scene_id: str, direction: str):
        direction = direction.strip().lower()
        if direction not in ["up", "down", "left", "right"]:
            direction = "up"

        return Action(
            scene_id,
            widget=None,
            action_type=ActionType.Swipe,
            addition=direction,
        )

    @staticmethod
    def rotate_action(scene_id: str, direction: str):
        direction = direction.strip().lower()
        if direction not in ["landscape", "portrait"]:
            direction = "landscape"

        return Action(
            scene_id,
            widget=None,
            action_type=ActionType.Rotate,
            addition=direction,
        )

    def __init__(
        self,
        scene_id: str,
        widget: "Widget|None",
        action_type: ActionType,
        addition: Any = None,
    ):
        self.scene_id = scene_id
        self.widget = widget
        self.action_type = action_type
        self.addition = addition

        hash_widget_id = widget.widget_id if widget is not None else "None"
        hash_addition = self.addition if action_type == ActionType.Swipe else "None"

        # widget_id contains enough information to uniquely identify the action target
        self.action_id = hash_hex(",".join([self.scene_id, hash_widget_id, self.action_type.name, hash_addition]))

    def _gen_text(self):
        if self.action_type != ActionType.InputText:
            raise Exception("Only InputText action can generate random text.")

        assert self.widget is not None

        image = ImageUtils.get_scene_image(self.scene_id)
        ImageUtils.draw_widget_bounds([self.widget], image)

        edittext_info = []
        if self.widget.resource_id:
            edittext_info.append(f"\n\tresource-id='{self.widget.resource_id}'")
        if self.widget.hint:
            edittext_info.append(f"\n\thint='{self.widget.hint}'")
        if self.widget.text:
            edittext_info.append(f"\n\told-text='{self.widget.text}'")
        if edittext_info:
            edittext_info = f"EditText widget:\n<EditText{''.join(edittext_info)}\n/>\n"
        else:
            edittext_info = ""

        return image, edittext_info

    def gen_text_about_task(self, package_name: str, task_description: str, current_node: "ExploringNode"):
        image, edittext_info = self._gen_text()
        if len(current_node.exploring_path):
            exploring_status_prompt = f"""
- We have previously assessed {len(current_node.exploring_path)} steps to advance towards the completion of Steps to Reproduce the Bug, outlined as follows:
{current_node.to_prompt()}
- We are preparing to analyze the next steps for interaction with specific interactive widgets listed below, all of which are marked in red box in the provided image along with their respective IDs.
            """.strip()
        else:
            exploring_status_prompt = f"- We are focusing on the first step of exploring interactions with the specific interactive widgets listed below, all of which are marked in red box in the provided image along with their respective IDs."

        prompt = f'''
We are exploring the correct path to reproduce the following bug based on the given Steps to Reproduce in the Android app:
- Package Name: {package_name}
- Steps to Reproduce the Bug:
{task_description}  

Current Progress:
- Exploration Status: {exploring_status_prompt}

Next Objective:
- Our immediate goal is to generate an appropriate input for an EditText widget to advance to the next step in the bug reproduction process.

Additional Information:
- An image is provided that shows the app screen, with the target EditText widget clearly highlighted in a red box.
{f"- {edittext_info}\n" if edittext_info else ""}

Request:
- Please provide a suitable input value for the highlighted EditText widget that will help bring the app state closer to successfully reproducing the reported bug.
            '''.strip()

        res = LLM.chat_with_image(prompt=prompt, image=image)
        formatted_res = LLM.format_to_json(
            res,
            """
{
    input: string; // the suitable input for this EditText widget
}
            """.strip(),
        )

        Recorder.record_gen_text(prompt, res, formatted_res, image)
        return formatted_res["input"]

    def gen_random_text(self):
        image, edittext_info = self._gen_text()
        random_char_list = json.dumps(generate_random_char_list(5))

        prompt = f"""
The image shows the screen of android app, with the target EditText widget highlighted in a red box.
{edittext_info}
Generate a random input for the EditText widget:
Use characters {random_char_list} as a starting point, and then expand or transform it into a meaningful input that fits the context.
What's the new meaningful input for this EditText widget?
        """.strip()

        res = LLM.chat_with_image(prompt=prompt, image=image)
        formatted_res = LLM.format_to_json(
            res,
            """
{
    input: string; // the new meaningful input for this EditText widget
}
                    """.strip(),
        )
        Recorder.record_gen_text(prompt, res, formatted_res, image)
        return formatted_res["input"]

    def try_execute(self, wait_time: int = 2):
        try:
            self.execute(wait_time)
            return True
        except Exception as e:
            logger.error("[Action] Failed to execute action '{}': {}", self.to_prompt(), e)
            return False

    def execute(self, wait_time: int = 2):
        start_image = Device.screenshot()
        if self.action_type == ActionType.Press:
            if self.addition == "enter":
                Device.press_enter()
            elif self.addition == "home":
                Device.press_home()
            elif self.addition == "delete":
                Device.press_delete()
            else:
                Device.press_back()
        elif self.action_type == ActionType.Swipe:
            Device.device.swipe_ext(self.addition, scale=0.9)
        elif self.action_type == ActionType.Rotate:
            if self.addition == "landscape":
                Device.set_orientation("l")
            else:
                Device.set_orientation("n")
        else:
            assert self.widget is not None
            x, y = self.widget.bounds.center()
            if self.action_type == ActionType.Click:
                Device.click(x, y)
            elif self.action_type == ActionType.LongClick:
                if self.addition is not None:
                    Device.long_click(x, y, duration=self.addition)
                else:
                    Device.long_click(x, y)
            elif self.action_type == ActionType.InputText:
                if self.addition == "::random::":
                    self.addition = self.gen_random_text()
                    Device.input_text(self.widget, self.addition)
                else:
                    Device.input_text(self.widget, self.addition)
            else:
                logger.warning(f"Unknown action type: {self.action_type}")

        Device.hide_keyboard()

        logger.info("[Action] {} ({})", self.to_prompt(), self.action_id)
        logger.info(f"[Action] Wait {wait_time} seconds")
        time.sleep(wait_time)
        end_image = Device.screenshot()
        Recorder.record_execute_action(self, self.to_prompt(), start_image, end_image)

    def to_prompt(self):
        if self.action_type == ActionType.Press:
            return f"press '{self.addition}' key"
        elif self.action_type == ActionType.Swipe:
            return f"swipe {self.addition}"
        elif self.action_type == ActionType.Rotate:
            return f"rotate {self.addition}"
        else:
            assert self.widget is not None
            if self.action_type == ActionType.InputText:
                return f"input '{self.addition}' in widget `{self.widget.to_prompt_xml_single()}`"
            else:
                return f"{self.action_type.name.lower()} widget `{self.widget.to_prompt_xml_single()}`"

    def to_dict(self):
        return {
            "action_id": self.action_id,
            "scene_id": self.scene_id,
            "action_type": self.action_type.name,
            "target_widget": self.widget.to_dict() if self.widget is not None else None,
            "addition": self.addition,
            "action_desc": self.to_prompt(),
        }
