import base64
import json
from typing import cast
from json_repair import repair_json
from enum import Enum
from io import BytesIO

from PIL.Image import Image, Resampling
from loguru import logger
from openai import OpenAI as Client


class Model(Enum):
    # openai
    GPT_4O = "gpt-4o"
    GPT_4O_MINI = "gpt-4o-mini"
    GPT_4_1 = "gpt-4.1"
    GPT_4_1_MINI = "gpt-4.1-mini"

    # zhipu
    GLM_4_PLUS = "glm-4-plus"
    GLM_4V_PLUS = "glm-4v-plus"


class LLM:
    name: str
    client: Client
    text_model: Model
    image_model: Model
    format_model: Model
    temperature: float
    tokenDict: dict

    @classmethod
    def init(
        cls,
        name: str,
        api_key: str,
        base_url: str,
        temperature: float,
        text_model: Model,
        image_model: Model,
        format_model: Model,
    ) -> None:
        cls.name = name
        cls.temperature = temperature
        cls.client = Client(api_key=api_key, base_url=base_url)
        cls.text_model = text_model
        cls.image_model = image_model
        cls.format_model = format_model
        cls.tokenDict = {
            model.name: {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
            for model in [text_model, image_model, format_model]
        }

    @staticmethod
    def _image_to_base64(image: Image, max_height: int = 512) -> str:
        old_width, old_height = image.size
        if old_height > max_height:
            new_width = int(max_height / old_height * old_width)
            image = image.resize((new_width, max_height), Resampling.LANCZOS)

        buffer = BytesIO()
        image = image.convert("RGB")
        image.save(buffer, format="JPEG", quality=80, optimize=True)

        image_bytes = buffer.getvalue()
        base64_str = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:image/jpeg;base64,{base64_str}"

    @classmethod
    def record_token_usage(cls, result_dir: str):
        with open(f"{result_dir}/token_usage.json", "w") as f:
            json.dump(cls.tokenDict, f, indent=4)
        logger.debug("[LLM] token consumption:\n{}", LLM.tokenDict)

    @classmethod
    def chat(cls, prompt: str, **kwargs) -> str:
        params = {
            "model": cls.text_model.value,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": cls.temperature,
            **kwargs,
        }

        logger.debug(
            f"[LLM] Requesting {cls.name}'s {cls.text_model.value}, T:{params['temperature']}, Prompt:\n{prompt}"
        )
        try:
            completion = cls.client.chat.completions.create(**params)
        except Exception as e:
            raise Exception(f"LLM request failed: {e}")
        if not completion.choices:
            raise Exception("LLM response nothing")
        res = completion.choices[0].message.content

        usage = completion.usage
        cls.tokenDict[cls.text_model.name]["prompt_tokens"] += usage.prompt_tokens
        cls.tokenDict[cls.text_model.name]["completion_tokens"] += usage.completion_tokens
        cls.tokenDict[cls.text_model.name]["total_tokens"] += usage.total_tokens

        logger.debug(
            f"[LLM] Response from {cls.name}'s {cls.text_model.value} (prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}, total_tokens={usage.total_tokens}):\n{res}"
        )
        return res

    @classmethod
    def chat_with_image(cls, prompt: str, image: Image, **kwargs) -> str:
        image_base64 = LLM._image_to_base64(image)
        params = {
            "model": cls.image_model.value,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_base64}},
                    ],
                },
            ],
            "temperature": cls.temperature,
            **kwargs,
        }

        logger.debug(
            f"[LLM] Requesting {cls.name}'s {cls.image_model.value} with image, T:{params['temperature']}, Prompt:\n{prompt}"
        )
        try:
            completion = cls.client.chat.completions.create(**params)
        except Exception as e:
            raise Exception(f"LLM request failed: {e}")

        if not completion.choices:
            raise Exception("LLM response nothing")
        res = completion.choices[0].message.content

        usage = completion.usage
        cls.tokenDict[cls.image_model.name]["prompt_tokens"] += usage.prompt_tokens
        cls.tokenDict[cls.image_model.name]["completion_tokens"] += usage.completion_tokens
        cls.tokenDict[cls.image_model.name]["total_tokens"] += usage.total_tokens

        logger.debug(
            f"[LLM] Response from {cls.name}'s {cls.image_model.value} (prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}, total_tokens={usage.total_tokens}):\n{res}"
        )
        return res

    @classmethod
    def chat_with_image_list(cls, prompt: str, image_list: list[Image], **kwargs) -> str:
        image_base64_list = [LLM._image_to_base64(image) for image in image_list]
        params = {
            "model": cls.image_model.value,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        *[
                            {"type": "image_url", "image_url": {"url": image_base64}}
                            for image_base64 in image_base64_list
                        ],
                    ],
                },
            ],
            "temperature": cls.temperature,
            **kwargs,
        }
        logger.debug(
            f"[LLM] Requesting {cls.name}'s {cls.image_model.value} with {len(image_list)} image, T:{params['temperature']}, Prompt:\n{prompt}"
        )
        try:
            completion = cls.client.chat.completions.create(**params)
        except Exception as e:
            raise Exception(f"LLM request failed: {e}")
        if not completion.choices:
            raise Exception("LLM response nothing")

        usage = completion.usage
        cls.tokenDict[cls.image_model.name]["prompt_tokens"] += usage.prompt_tokens
        cls.tokenDict[cls.image_model.name]["completion_tokens"] += usage.completion_tokens
        cls.tokenDict[cls.image_model.name]["total_tokens"] += usage.total_tokens

        res = completion.choices[0].message.content
        logger.debug(
            f"[LLM] Response from {cls.name}'s {cls.image_model.value} (prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}, total_tokens={usage.total_tokens}):\n{res}"
        )
        return res

    @classmethod
    def format_to_json(cls, res: str, type_definition: str, format_model: Model | None = None) -> dict:
        if format_model is None:
            format_model = cls.format_model

        prompt = f"""
{res}

---

Given the LLM response above, please extract the relevant information and present it in the following 'TypeScript definition' format:
{type_definition}
Please review the raw content thoroughly and provide a comprehensive answer.
Only output the JSON object that exactly matches the specified 'TypeScript definition' description.
        """.strip()

        try:
            completion = cls.client.chat.completions.create(
                model=format_model.value,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
            )
        except Exception as e:
            raise Exception(f"LLM request failed: {e}")

        if not completion.choices:
            raise Exception("LLM response nothing")

        usage = completion.usage
        if usage is None:
            raise Exception("LLM usage is none")

        cls.tokenDict[cls.format_model.name]["prompt_tokens"] += usage.prompt_tokens
        cls.tokenDict[cls.format_model.name]["completion_tokens"] += usage.completion_tokens
        cls.tokenDict[cls.format_model.name]["total_tokens"] += usage.total_tokens

        formatted_res = completion.choices[0].message.content
        if formatted_res is None:
            raise Exception("LLM response nothing")
        logger.debug(
            f"[LLM] Formated response from {cls.name}'s {format_model.value} (prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}, total_tokens={usage.total_tokens}):\n{formatted_res}"
        )
        try:
            return cast(
                dict,
                repair_json(formatted_res, return_objects=True, ensure_ascii=False),
            )
        except:
            raise Exception("Formatting llm response failed")
