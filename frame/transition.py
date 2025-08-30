from typing import TYPE_CHECKING

from PIL.Image import Image

from frame.device import AppInfo
from frame.llm import LLM
from frame.recorder import Recorder
from frame.utils import ImageUtils, hash_hex

if TYPE_CHECKING:
    from frame.action import Action


class Transition:
    transition_id: str
    action: 'Action'
    start_scene_id: str
    end_scene_id: str
    ui_transition: str
    one_sentence_summary: str
    start_app_info: AppInfo
    end_app_info: AppInfo

    @staticmethod
    def gen_ui_transition(action: 'Action', before_scene_image: Image, after_scene_image: Image,
                          start_app_info: AppInfo,
                          end_app_info: AppInfo):
        if action.widget is not None:
            ImageUtils.draw_widget_bounds([action.widget], before_scene_image)

        action_prompt = action.to_prompt()
        red_box_prmpt = " and key interactive element highlighted in red box" if action.widget is not None else ''

        prompt = f'''
Evaluate and analyze the UI transitions and functional changes in Android applications after specific user actions.

## Context
- Action: {action_prompt}
- Initial State:
  - App: {start_app_info.package}
  - Activity: {start_app_info.activity}
  - Image: First image shows the state of the screen before the action was performed.
- Final State: 
  - App: {end_app_info.package}
  - Activity: {end_app_info.activity}
  - Image: Second image shows the state of the screen after the action was performed.

## Workflows
- Goal: Evaluate the transition caused by the action on the Android app based on the context.
- Steps:
    1. Review the initial state of the app before the action, noting the layout{red_box_prmpt}.
    2. Analyze the transition state of the app after the action has been executed, identifying any changes or effects.
    3. Compare both states to identify and describe all observable UI and state changes resulting from the action.
- Expected Result:
    1. A detailed description of what the action does and the resulting changes in the app’s UI and state, including:
        - Widget additions or removals
        - Visibility updates
        - Content modifications
        - Layout shifts
        - Screen navigation or App/Activity switch
    2. A concise one-sentence summary that captures the primary effect or purpose of the action.
        '''.strip()

        res = LLM.chat_with_image_list(prompt, [before_scene_image, after_scene_image])

        formatted_res = LLM.format_to_json(
            res, '''
{
    detailed_description: string; // A detailed description of what the action does and the resulting changes in the app’s UI and state
    one_sentence_summary: string; // A concise one-sentence summary that captures the primary effect or purpose of the action
}
                    '''.strip())
        Recorder.record_gen_ui_transition(prompt, res, formatted_res, before_scene_image, after_scene_image, action)
        return formatted_res["detailed_description"], formatted_res["one_sentence_summary"]

    @staticmethod
    def get_transition_id(start_scene_id: str, end_scene_id: str, action_id: str):
        return hash_hex(f"{start_scene_id},{action_id},{end_scene_id}")

    def __init__(self, action: 'Action', start_scene_id: str, end_scene_id: str, start_app_info: AppInfo,
                 end_app_info: AppInfo, ui_transition: str, one_sentence_summary: str):
        self.transition_id = self.get_transition_id(start_scene_id, end_scene_id, action.action_id)
        self.action = action
        self.start_scene_id = start_scene_id
        self.end_scene_id = end_scene_id
        self.start_app_info = start_app_info
        self.end_app_info = end_app_info
        self.ui_transition = ui_transition
        self.one_sentence_summary = one_sentence_summary

    def to_prompt(self, one_sentence=False):
        if one_sentence:
            return self.one_sentence_summary
        return self.ui_transition
