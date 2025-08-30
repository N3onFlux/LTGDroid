import json
import os.path
import time
from typing import TextIO, TYPE_CHECKING

from PIL.Image import Image
from loguru import logger
import atexit

from frame.transition import Transition
from frame.utils import timestamp

if TYPE_CHECKING:
    from explore import ExploringNode, GraphNode


class ExploreRecorder:
    data_f: TextIO
    index: int
    result_dir: str
    state: str

    @classmethod
    def init(cls, result_dir):
        cls.result_dir = result_dir
        cls.data_f = open(os.path.join(result_dir, "data"), "a", encoding="utf-8")
        cls.index = 0
        cls._state_update(0, "exploring")

        def on_exit():
            cls.data_f.close()

        atexit.register(on_exit)

    @classmethod
    def append_data(cls, type_name: str, data: dict, state="exploring"):
        ts = int(time.time())
        data["id"] = cls.index
        cls.index += 1
        data["ts"] = ts
        data["type"] = type_name
        cls.data_f.write(f"{json.dumps(data, ensure_ascii=False)}\n")
        cls.data_f.flush()
        cls._state_update(ts, state)
        logger.debug("[ExplorePersistence] Save data {}: {}", type_name, ts)

    @classmethod
    def _state_update(cls, ts: float, state: str):
        cls.state = state
        tmp_path = os.path.join(cls.result_dir, "state.tmp")
        final_path = os.path.join(cls.result_dir, "state")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(f"{ts} {state}")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, final_path)

    @classmethod
    def record_add_graph_node(cls, node: "GraphNode"):
        cls.append_data("AddGraphNode", {"scene_id": node.scene_id, "total_action_num": node.total_action_num})

    @classmethod
    def record_add_graph_transition(cls, transition: "Transition", level: int, reused: bool = False):
        cls.append_data(
            "AddGraphTransition",
            {
                "transition_id": transition.transition_id,
                "start_scene_id": transition.start_scene_id,
                "end_scene_id": transition.end_scene_id,
                "level": level,
                "reused": reused,
            },
        )

    @classmethod
    def record_update_current_scene(cls, scene_id: str):
        cls.append_data("UpdateCurrentScene", {"scene_id": scene_id})

    @classmethod
    def record_explore_success(cls, file_list: list[str]):
        cls.append_data("ExploreSuccess", {"paths": file_list}, "success")

    @classmethod
    def record_explore_fail(cls, reason: str):
        cls.append_data("ExploreFail", {"reason": reason}, "fail")

    @classmethod
    def record_explore_error(cls, reason: str):
        cls.append_data("ExploreError", {"reason": reason}, "error")

    @classmethod
    def record_disable_transition(cls, transition_id: str):
        cls.append_data("DisableTransition", {"transition_id": transition_id})

    @classmethod
    def record_remove_exploring_transition(cls, transition_id_list: list[str]):
        cls.append_data("PruneExploringTransition", {"transition_id_list": transition_id_list})

    @classmethod
    def record_summary_s2r(cls, prompt: str, s2r: str):
        cls.append_data("SummaryS2R", {"prompt": prompt, "s2r": s2r})

    @classmethod
    def record_prune_exploring_nodes(
        cls,
        prompt: str,
        res: str,
        format_res: dict,
        total: list["ExploringNode"],
        achieved: list["ExploringNode"],
        removed: list["ExploringNode"],
        total_index: list[int],
        achieved_index: list[int],
        removed_index: list[int],
    ):
        total_paths = [
            {
                "scene_id": node.scene_id,
                "exploring_path": [t.transition_id for t in node.exploring_path],
                "no": total_index[i],
            }
            for i, node in enumerate(total)
        ]
        achieved_paths = [
            {
                "scene_id": node.scene_id,
                "exploring_path": [t.transition_id for t in node.exploring_path],
                "no": achieved_index[i],
            }
            for i, node in enumerate(achieved)
        ]
        removed_paths = [
            {
                "scene_id": node.scene_id,
                "exploring_path": [t.transition_id for t in node.exploring_path],
                "no": removed_index[i],
            }
            for i, node in enumerate(removed)
        ]

        cls.append_data(
            "FilterExploringNodes",
            {
                "llm": {
                    "prompt": prompt,
                    "res": res,
                    "format_res": format_res,
                },
                "total_paths": total_paths,
                "achieved_paths": achieved_paths,
                "removed_paths": removed_paths,
            },
        )

    @classmethod
    def record_validate_exploring_complete(
        cls, prompt: str, res: str, format_res: list[dict], achieved: list["ExploringNode"], achieved_index: list[int]
    ):
        achieved_paths = [
            {
                "scene_id": node.scene_id,
                "exploring_path": [t.transition_id for t in node.exploring_path],
                "no": achieved_index[i],
            }
            for i, node in enumerate(achieved)
        ]

        cls.append_data(
            "ValidateExploringComplete",
            {
                "llm": {
                    "prompt": prompt,
                    "res": res,
                    "format_res": format_res,
                },
                "achieved_paths": achieved_paths,
            },
        )

    @classmethod
    def record_track_crash_completion(cls, node: "ExploringNode"):
        cls.append_data(
            "TrackCrashCompletion",
            {
                "scene_id": node.scene_id,
                "crash_path": [t.transition_id for t in node.exploring_path],
            },
        )

    @classmethod
    def record_refine_action_widgets(
        cls,
        prompt: str,
        res: str,
        format_res: dict,
        scene_id: str,
        before_refine_image: Image,
        after_refine_image: Image,
        predict_flag: bool,
    ):
        ts = timestamp()
        before_image_name = f"RefineActionWidgets_{ts}_0"
        after_image_name = f"RefineActionWidgets_{ts}_1"
        before_image_path = os.path.abspath(os.path.join(cls.result_dir, "details", f"{before_image_name}.png"))
        after_image_path = os.path.abspath(os.path.join(cls.result_dir, "details", f"{after_image_name}.png"))
        before_refine_image.save(before_image_path)
        after_refine_image.save(after_image_path)

        cls.append_data(
            "RefineActionWidgets",
            {
                "llm": {
                    "prompt": prompt,
                    "res": res,
                    "format_res": format_res,
                },
                "scene_id": scene_id,
                "before_image_name": before_image_name,
                "after_image_name": after_image_name,
                "predict_flag": predict_flag,
            },
        )
