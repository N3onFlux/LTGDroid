import json
from enum import Enum
from typing import TYPE_CHECKING

from PIL.Image import Image

from frame.utils import ensure_dir, ImageUtils

if TYPE_CHECKING:
    from frame.action import Action


class RecordType(Enum):
    GenerateText = 1
    ExecuteAction = 2
    ExtractTransition = 3


class Recorder:
    out_dir: str
    index: int

    @classmethod
    def init(cls, result_dir: str):
        cls.out_dir = f"{result_dir}/details"
        cls.index = 0
        ensure_dir(cls.out_dir)

    @classmethod
    def save_record(
        cls, record_type: RecordType, record: dict, image: Image | None = None
    ):
        with open(
            f"{cls.out_dir}/{cls.index:04}-{record_type.name}.json",
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(record, f, ensure_ascii=False, indent=4)
        if image is not None:
            image.save(f"{cls.out_dir}/{cls.index:04}-{record_type.name}.png")
        cls.index += 1

    @classmethod
    def record_gen_text(cls, prompt: str, res: str, format_res: dict, image: Image):
        cls.save_record(
            RecordType.GenerateText,
            {"prompt": prompt, "res": res, "format_res": format_res},
            image,
        )

    @classmethod
    def record_execute_action(
        cls, action: "Action", description: str, start_image: Image, end_image: Image
    ):
        action_type = action.action_type

        if action.widget is not None:
            ImageUtils.draw_widget_bounds([action.widget], start_image)
        ImageUtils.draw_title(action_type.name, start_image)

        ImageUtils.draw_title("result", end_image)

        image = ImageUtils.concat_images([start_image, end_image])
        cls.save_record(
            RecordType.ExecuteAction,
            {"action_type": action_type.name, "description": description},
            image,
        )

    @classmethod
    def record_gen_ui_transition(
        cls,
        prompt: str,
        res: str,
        format_res: dict,
        start_image: Image,
        end_image: Image,
        action: "Action",
    ):
        image = ImageUtils.concat_images([start_image, end_image])
        cls.save_record(
            RecordType.ExtractTransition,
            {
                "action_id": action.action_id,
                "prompt": prompt,
                "res": res,
                "format_res": format_res,
            },
            image,
        )
