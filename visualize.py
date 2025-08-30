import json
import os.path
from contextlib import asynccontextmanager

from loguru import logger

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from frame.utils import load_json


# class Share:
#     init_flag: bool = False
#     graph_dir: str
#     graph_path: str

#     @classmethod
#     def reset(cls, graph_dir: str):
#         cls.graph_dir = graph_dir
#         cls.graph_path = os.path.join(cls.graph_dir, "graph.txt")
#         cls.init_flag = True

#     @classmethod
#     def check_init_flag(cls):
#         if not cls.init_flag:
#             raise HTTPException(status_code=400, detail="Graph folder path not set")

#     @classmethod
#     def reload(cls):
#         if not os.path.exists(cls.graph_path):
#             return ""

#         with open(cls.graph_path, "r", encoding="utf-8") as f:
#             return f.read().strip().split("\n")

#     @classmethod
#     def edge_detail(cls, transition_id: str):
#         edge_path = os.path.join(cls.graph_dir, "transitions", f"{transition_id}.json")
#         if not os.path.exists(edge_path):
#             raise HTTPException(status_code=400, detail=f"Transition not found: {edge_path}")
#         with open(edge_path, "r", encoding="utf-8") as f:
#             return json.load(f)

#     @classmethod
#     def node_detail(cls, scene_id: str):
#         node_path = os.path.join(cls.graph_dir, "scenes", f"{scene_id}.json")
#         if not os.path.exists(node_path):
#             raise HTTPException(status_code=400, detail=f"Scene not found: {node_path}")
#         with open(node_path, "r", encoding="utf-8") as f:
#             return json.load(f)


class State:
    init_flag: bool = False
    current_ts: int
    current_state: str
    result_dir: str
    data_cursor = -1
    events: list[dict]

    @classmethod
    def reset(cls, result_dir: str):
        cls.current_ts = 0
        cls.current_state = "exploring"
        cls.result_dir = os.path.abspath(result_dir)
        cls.data_cursor = 0
        cls.events = []
        cls.init_flag = True

    @classmethod
    def check_init_flag(cls):
        if not cls.init_flag:
            raise HTTPException(status_code=400, detail="Folder path not set")

    @classmethod
    def read_scene(cls, scene_id: str) -> dict:
        file_path = os.path.join(cls.result_dir, "scenes", f"{scene_id}.json")
        return load_json(file_path)

    @classmethod
    def read_transition(cls, transition_id: str) -> dict:
        file_path = os.path.join(cls.result_dir, "transitions", f"{transition_id}.json")
        return load_json(file_path)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("Visualize app start")
    yield
    logger.info("Visualize app stop")


app = FastAPI(lifespan=lifespan)
app.mount("/assets", StaticFiles(directory="resource/web/assets"), name="assets")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PostDataSetConfig(BaseModel):
    path: str


# @app.get("/share")
# async def serve_share():
#     return FileResponse("resource/web/share.html")


# @app.post("/api/share/set_config")
# async def set_share_config(item: PostDataSetConfig):
#     if os.path.exists(item.path) and os.path.isdir(item.path):
#         Share.reset(item.path)
#         logger.success(f"Folder path set successfully: {item.path}")
#         return {"msg": f"Folder path set successfully: {item.path}"}
#     else:
#         raise HTTPException(status_code=400, detail=f"Folder path not exists: {item.path}")


# @app.get("/share/image/transitions/{transition_id}")
# def get_share_transitions_image(transition_id: str):
#     Share.check_init_flag()
#     return FileResponse(os.path.join(Share.graph_dir, "transitions", f"{transition_id}.png"))


# @app.get("/share/image/scenes/{scene_id}")
# def get_share_scenes_image(scene_id: str):
#     Share.check_init_flag()
#     return FileResponse(os.path.join(Share.graph_dir, "scenes", f"{scene_id}.png"))


# @app.get("/api/share/reload")
# def load_share_data():
#     Share.check_init_flag()
#     raw_data = Share.reload()
#     return {
#         "msg": "success",
#         "data": {
#             "raw_data": raw_data,
#             "resultDirectory": Share.graph_dir,
#         }
#     }


# @app.get("/api/share/scene/{scene_id}")
# def get_share_scenes_detail(scene_id: str):
#     Share.check_init_flag()
#     return {
#         "msg": "success",
#         "data": Share.node_detail(scene_id)
#     }


# @app.get("/api/share/transition/{transition_id}")
# def get_share_transitions_detail(transition_id: str):
#     Share.check_init_flag()

#     return {
#         "msg": "success",
#         "data": Share.edge_detail(transition_id)
#     }


@app.get("/")
async def serve_home():
    return FileResponse("resource/web/index.html")


@app.get("/image/scenes/{scene_id}")
def get_scenes_image(scene_id: str):
    State.check_init_flag()
    return FileResponse(os.path.join(State.result_dir, "scenes", f"{scene_id}.png"))


@app.get("/image/transitions/{transition_id}")
def get_transitions_image(transition_id: str):
    State.check_init_flag()
    return FileResponse(os.path.join(State.result_dir, "transitions", f"{transition_id}.png"))


@app.get("/image/details/{image_name}")
def get_detail_image(image_name: str):
    State.check_init_flag()
    return FileResponse(os.path.join(State.result_dir, "details", f"{image_name}.png"))


@app.post("/api/set_config")
async def set_config(item: PostDataSetConfig):
    if os.path.exists(item.path) and os.path.isdir(item.path):
        State.reset(item.path)
        logger.success(f"Folder path set successfully: {item.path}")
        return {"msg": f"Folder path set successfully: {item.path}"}
    else:
        raise HTTPException(status_code=400, detail=f"Folder path not exists: {item.path}")


@app.get("/api/get_events/{start_id}/{end_id}")
def get_events(start_id: int, end_id: int):
    output = []

    for event in State.events:
        if event["id"] > end_id:
            break
        if event["id"] >= start_id:
            output.append(event)

    return {"msg": "success", "data": {"idRange": [output[0]["id"], output[-1]["id"]], "events": output}}


@app.get("/api/refresh")
def refresh():
    State.check_init_flag()

    if not os.path.exists(os.path.join(State.result_dir, "state")):
        raise HTTPException(status_code=400, detail="Exploring state not initialized")

    if State.data_cursor == -1:
        return {
            "msg": "success",
            "data": {
                "idRange": [State.events[0]["id"], State.events[-1]["id"]],
                "tsRange": [State.events[0]["ts"], State.events[-1]["ts"]],
                "state": State.current_state,
                "resultDirectory": State.result_dir,
            },
        }

    with open(os.path.join(State.result_dir, "state"), "r", encoding="utf-8") as f:
        ts, state = f.read().strip().split()
        State.current_state = state
    ts = int(ts)
    if ts == 0:
        raise HTTPException(status_code=400, detail="Exploring state not initialized")

    if State.current_ts <= ts:
        State.current_ts = ts

        with open(os.path.join(State.result_dir, "data"), "r", encoding="utf-8") as data_f:
            data_f.seek(State.data_cursor)
            content = data_f.read().strip()
            if content:
                lines = content.split("\n")
                State.data_cursor = data_f.tell()
                for line in lines:
                    event: dict = json.loads(line.strip())
                    event_type = event["type"]
                    if event_type == "AddGraphNode":
                        scene = State.read_scene(event["scene_id"])
                        event.update(scene)
                        State.events.append(event)
                    elif event_type == "AddGraphTransition":
                        transition = State.read_transition(event["transition_id"])
                        event.update(transition)
                        State.events.append(event)
                    else:
                        # UpdateCurrentScene
                        # ExploreSuccess
                        # ExploreFail
                        # DisableTransition
                        # PruneExploringTransition
                        # FilterExploringNodes
                        # ValidateExploringComplete
                        # TrackCrashCompletion
                        State.events.append(event)

            if state == "fail":
                logger.info("Exploring state update: fail")
            elif state == "success":
                logger.success("Exploring state update: success")

    return {
        "msg": "success",
        "data": {
            "idRange": [State.events[0]["id"], State.events[-1]["id"]],
            "tsRange": [State.events[0]["ts"], State.events[-1]["ts"]],
            "state": state,
            "resultDirectory": State.result_dir,
        },
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=13126)
