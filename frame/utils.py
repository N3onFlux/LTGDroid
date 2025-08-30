import hashlib
import json
import os
import random
import string
import time
from typing import TYPE_CHECKING, Any

from PIL import ImageDraw, ImageFont, Image
from loguru import logger

if TYPE_CHECKING:
    from frame.scene import Scene
    from frame.transition import Transition
    from frame.widget import Widget


def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def timestamp():
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime())


def generate_random_char_list(length: int) -> list[str]:
    characters = string.ascii_lowercase
    random_char_list = [random.choice(characters) for _ in range(length)]
    return random_char_list


def ensure_dir(path_str: str):
    if not os.path.exists(path_str):
        os.makedirs(path_str)


def hash_hex(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def unique_file_with_id_path(dir_path: str, base_name: str, file_ext: str):
    if not os.path.exists(dir_path):
        raise FileNotFoundError(f"{os.path.abspath(dir_path)} does not exist")
    cur_id = 1
    while True:
        cur_path = os.path.join(dir_path, f"{base_name}-{cur_id:02}.{file_ext}")
        if not os.path.exists(cur_path):
            return os.path.abspath(cur_path)
        cur_id += 1


class GraphPersistence:
    result_dir: str

    @classmethod
    def init(cls, result_dir: str):
        cls.result_dir = result_dir

    @classmethod
    def save_scene(cls, scene: "Scene"):
        file_path = f"{cls.result_dir}/scenes/{scene.scene_id}.json"
        data = {
            "scene_id": scene.scene_id,
            "widget_tree": scene.widget_tree.to_dict(),
            "app_info": scene.app_info.to_dict(),
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    @classmethod
    def save_transition(cls, transition: "Transition"):
        file_path = f"{cls.result_dir}/transitions/{transition.transition_id}.json"
        data = {
            "transition_id": transition.transition_id,
            "one_sentence_summary": transition.one_sentence_summary,
            "start_scene_id": transition.start_scene_id,
            "end_scene_id": transition.end_scene_id,
            "ui_transition": transition.ui_transition,
            "action": transition.action.to_dict(),
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)


class ImageUtils:
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont
    result_dir: str

    @classmethod
    def init(cls, result_dir: str):
        cls.font = ImageFont.load_default(50)
        cls.result_dir = result_dir

    @classmethod
    def get_scene_image(cls, scene_id: str):
        image_path = f"{cls.result_dir}/scenes/{scene_id}.png"
        return Image.open(image_path)

    @classmethod
    def get_transition_image(cls, transition_id: str):
        image_path = f"{cls.result_dir}/transitions/{transition_id}.png"
        return Image.open(image_path)

    @classmethod
    def save_cur_scene_image(cls, scene: "Scene", cur_scene_image: Image.Image):
        file_path = f"{cls.result_dir}/scenes/{scene.scene_id}.png"
        if os.path.exists(file_path):
            logger.warning(
                f"[ImageUtils] Scene image already exists, overwrite it: {file_path}"
            )
        cur_scene_image.save(file_path)

    @classmethod
    def save_transition_image(
        cls, transition: "Transition", first_scene_image: Image.Image
    ):
        action = transition.action
        if action.widget is not None:
            cls.draw_widget_bounds([action.widget], first_scene_image)
        cls.draw_title(action.action_type.name, first_scene_image)
        file_path = f"{cls.result_dir}/transitions/{transition.transition_id}.png"
        if os.path.exists(file_path):
            logger.warning(
                f"[ImageUtils] Transition image already exists, overwrite it: {file_path}"
            )
        first_scene_image.save(file_path)

    @classmethod
    def draw_widget_bounds(
        cls,
        widgets: list["Widget"],
        image: Image.Image,
        box_color: str = "red",
        draw_index: bool = False,
    ):
        draw = ImageDraw.Draw(image)
        for index, w in enumerate(widgets, 1):
            xy = (w.bounds.left, w.bounds.top), (w.bounds.right, w.bounds.bottom)
            draw.rectangle(xy, outline=box_color, width=5)
            if draw_index:
                draw.text(
                    (w.bounds.left + 5, w.bounds.top + 5),
                    str(index),
                    fill="red",
                    font=cls.font,
                )

        return image

    @classmethod
    def draw_title(cls, title: str, image: Image.Image) -> Image.Image:
        draw = ImageDraw.Draw(image)
        draw.text((0, 0), title, fill="red", font=cls.font)
        return image

    @classmethod
    def concat_images(cls, images: list[Image.Image]) -> Image.Image:
        width = sum([img.width for img in images])
        height = max([img.height for img in images])
        result = Image.new("RGB", (width, height))
        x = 0
        for img in images:
            result.paste(img, (x, 0))
            x += img.width
        return result
