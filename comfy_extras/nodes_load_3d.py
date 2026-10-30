import nodes
import folder_paths
import json
import os
import re
import struct
import uuid
from dataclasses import dataclass, field
from io import BytesIO

import numpy as np
from typing_extensions import override
from comfy_api.latest import IO, UI, ComfyExtension, InputImpl, Types

from pathlib import Path


def normalize_path(path):
    return path.replace('\\', '/')

class Load3D(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        input_dir = os.path.join(folder_paths.get_input_directory(), "3d")

        os.makedirs(input_dir, exist_ok=True)

        input_path = Path(input_dir)
        base_path = Path(folder_paths.get_input_directory())

        files = [
            normalize_path(str(file_path.relative_to(base_path)))
            for file_path in input_path.rglob("*")
            if file_path.suffix.lower() in {'.gltf', '.glb', '.obj', '.fbx', '.stl', '.spz', '.splat', '.ply', '.ksplat'}
        ]
        return IO.Schema(
            node_id="Load3D",
            display_name="Load 3D & Animation",
            category="3d",
            essentials_category="Basics",
            is_experimental=True,
            inputs=[
                IO.Combo.Input("model_file", options=["none"] + sorted(files), upload=IO.UploadType.model),
                IO.Load3D.Input("image"),
                IO.Int.Input("width", default=1024, min=1, max=4096, step=1),
                IO.Int.Input("height", default=1024, min=1, max=4096, step=1),
            ],
            outputs=[
                IO.Image.Output(display_name="image"),
                IO.Mask.Output(display_name="mask"),
                IO.String.Output(display_name="mesh_path"),
                IO.Image.Output(display_name="normal"),
                IO.Load3DCamera.Output(display_name="camera_info"),
                IO.Video.Output(display_name="recording_video"),
                IO.File3DAny.Output(display_name="model_3d"),
                IO.Load3DModelInfo.Output(display_name="model_3d_info"),
            ],
        )

    @classmethod
    def validate_inputs(cls, model_file, **kwargs) -> bool | str:
        if not model_file or model_file == "none":
            return True
        if not folder_paths.exists_annotated_filepath(model_file):
            return f"Invalid 3D model file: {model_file}"
        return True

    @classmethod
    def execute(cls, model_file, image, **kwargs) -> IO.NodeOutput:
        load_image_node = nodes.LoadImage()
        output_image, ignore_mask = load_image_node.load_image(image=image['image'])
        ignore_image, output_mask = load_image_node.load_image(image=image['mask'])
        normal_image, ignore_mask2 = load_image_node.load_image(image=image['normal'])

        video = None

        if image['recording'] != "":
            recording_video_path = folder_paths.get_annotated_filepath(image['recording'])

            video = InputImpl.VideoFromFile(recording_video_path)

        file_3d = None
        mesh_path = ""
        if model_file and model_file != "none":
            file_3d = Types.File3D(folder_paths.get_annotated_filepath(model_file))
            mesh_path = model_file
        model_3d_info = image.get('model_3d_info', [])
        return IO.NodeOutput(output_image, output_mask, mesh_path, normal_image, image['camera_info'], video, file_3d, model_3d_info)

    process = execute  # TODO: remove


class Preview3D(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="Preview3D",
            display_name="Preview 3D & Animation (DEPRECATED)",
            category="3d",
            description="Preview a 3D model file without saving it to the ComfyUI output directory.",
            is_experimental=True,
            is_output_node=True,
            is_deprecated=True, # This node is superseded by the Preview 3D (Advanced) node
            inputs=[
                IO.MultiType.Input(
                    IO.String.Input("model_file", default="", multiline=False),
                    types=[
                        IO.File3DGLB,
                        IO.File3DGLTF,
                        IO.File3DFBX,
                        IO.File3DOBJ,
                        IO.File3DSTL,
                        IO.File3DUSDZ,
                        IO.File3DAny,
                    ],
                    tooltip="3D model file or path string",
                ),
                IO.Load3DCamera.Input("camera_info", optional=True, advanced=True),
                IO.Image.Input("bg_image", optional=True, advanced=True),
            ],
            outputs=[],
        )

    @classmethod
    def execute(cls, model_file: str | Types.File3D, **kwargs) -> IO.NodeOutput:
        if isinstance(model_file, Types.File3D):
            filename = f"preview3d_{uuid.uuid4().hex}.{model_file.format}"
            model_file.save_to(os.path.join(folder_paths.get_output_directory(), filename))
        else:
            filename = model_file
        camera_info = kwargs.get("camera_info", None)
        bg_image = kwargs.get("bg_image", None)
        return IO.NodeOutput(ui=UI.PreviewUI3D(filename, camera_info, bg_image=bg_image))

    process = execute  # TODO: remove


class Preview3DAdvanced(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="Preview3DAdvanced",
            display_name="Preview 3D (Advanced)",
            search_aliases=["preview", "preview 3d", "3d viewer", "view mesh", "frame 3d", "3d camera output"],
            category="3d",
            description="Preview a 3D model file without saving it to the ComfyUI output directory.",
            is_experimental=True,
            is_output_node=True,
            inputs=[
                IO.MultiType.Input(
                    "model_3d",
                    types=[
                        IO.File3DGLB,
                        IO.File3DGLTF,
                        IO.File3DFBX,
                        IO.File3DOBJ,
                        IO.File3DSTL,
                        IO.File3DUSDZ,
                        IO.File3DAny,
                    ],
                    tooltip="3D model file from an upstream 3D node.",
                ),
                IO.Load3DModelInfo.Input("model_3d_info", optional=True, advanced=True),
                IO.Load3D.Input("viewport_state"),
                IO.Load3DCamera.Input("camera_info", optional=True, advanced=True, tooltip="Viewport camera information: position, look-at target, zoom, and type."),
                IO.Int.Input("width", default=1024, min=1, max=4096, step=1, tooltip="Render width of the viewport in pixels."),
                IO.Int.Input("height", default=1024, min=1, max=4096, step=1, tooltip="Render height of the viewport in pixels."),
            ],
            outputs=[
                IO.File3DAny.Output(display_name="model_3d", tooltip="3D model file (glb/obj/stl/etc.) from an upstream 3D node."),
                IO.Load3DModelInfo.Output(display_name="model_3d_info", tooltip="Placement of each model in the scene: position, rotation, and scale (Y-up world space)."),
                IO.Load3DCamera.Output(display_name="camera_info", tooltip="Viewport camera information: position, look-at target, zoom, and type."),
                IO.Int.Output(display_name="width", tooltip="Render width of the viewport in pixels."),
                IO.Int.Output(display_name="height", tooltip="Render height of the viewport in pixels."),
            ],
        )

    @classmethod
    def execute(cls, model_3d: Types.File3D, viewport_state, width: int, height: int, **kwargs) -> IO.NodeOutput:
        filename = f"preview3d_advanced_{uuid.uuid4().hex}.{model_3d.format}"
        model_3d.save_to(os.path.join(folder_paths.get_temp_directory(), filename))

        viewport_state = viewport_state if isinstance(viewport_state, dict) else {}
        camera_info_input = kwargs.get("camera_info", None)
        camera_info = camera_info_input if camera_info_input is not None else viewport_state.get('camera_info')
        model_3d_info_input = kwargs.get("model_3d_info", None)
        model_3d_info = model_3d_info_input if model_3d_info_input is not None else viewport_state.get('model_3d_info', [])
        return IO.NodeOutput(
            model_3d,
            model_3d_info,
            camera_info,
            width,
            height,
            ui=UI.Saved3DModels([UI.SavedResult(filename, "", IO.FolderType.temp)], camera_info, model_3d_info),
        )


class PreviewGaussianSplat(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="PreviewGaussianSplat",
            display_name="Preview Splat",
            category="3d",
            description="Preview a gaussian splat 3D file without saving it to the ComfyUI output directory.",
            is_experimental=True,
            is_output_node=True,
            search_aliases=[
                "preview",
                "preview splat",
                "preview gaussian",
                "preview gaussian splat",
                "preview 3dgs",
                "preview ply",
                "preview spz",
                "preview ksplat",
                "view splat",
                "view gaussian",
                "view gaussian splat",
                "view 3dgs",
            ],
            inputs=[
                IO.MultiType.Input(
                    "model_3d",
                    types=[
                        IO.File3DSplatAny,
                        IO.File3DPLY,
                        IO.File3DSPLAT,
                        IO.File3DSPZ,
                        IO.File3DKSPLAT,
                    ],
                    tooltip="A gaussian splat 3D file.",
                ),
                IO.Load3DModelInfo.Input("model_3d_info", optional=True, advanced=True),
                IO.Load3D.Input("viewport_state"),
                IO.Load3DCamera.Input("camera_info", optional=True, advanced=True),
                IO.Int.Input("width", default=1024, min=1, max=4096, step=1),
                IO.Int.Input("height", default=1024, min=1, max=4096, step=1),
            ],
            outputs=[
                IO.File3DSplatAny.Output(display_name="model_3d"),
                IO.Load3DModelInfo.Output(display_name="model_3d_info"),
                IO.Load3DCamera.Output(display_name="camera_info"),
                IO.Int.Output(display_name="width"),
                IO.Int.Output(display_name="height"),
            ],
        )

    @classmethod
    def execute(cls, model_3d: Types.File3D, viewport_state, width: int, height: int, **kwargs) -> IO.NodeOutput:
        filename = f"preview_splat_{uuid.uuid4().hex}.{model_3d.format}"
        model_3d.save_to(os.path.join(folder_paths.get_temp_directory(), filename))

        viewport_state = viewport_state if isinstance(viewport_state, dict) else {}
        camera_info_input = kwargs.get("camera_info", None)
        camera_info = camera_info_input if camera_info_input is not None else viewport_state.get('camera_info')
        model_3d_info_input = kwargs.get("model_3d_info", None)
        model_3d_info = model_3d_info_input if model_3d_info_input is not None else viewport_state.get('model_3d_info', [])
        return IO.NodeOutput(
            model_3d,
            model_3d_info,
            camera_info,
            width,
            height,
            ui=UI.Saved3DModels([UI.SavedResult(filename, "", IO.FolderType.temp)], camera_info, model_3d_info),
        )


class PreviewPointCloud(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        return IO.Schema(
            node_id="PreviewPointCloud",
            display_name="Preview Point Cloud",
            category="3d",
            description="Preview a point cloud 3D file without saving it to the ComfyUI output directory.",
            is_experimental=True,
            is_output_node=True,
            search_aliases=[
                "preview",
                "preview point cloud",
                "preview pointcloud",
                "preview ply",
                "view point cloud",
                "view pointcloud",
            ],
            inputs=[
                IO.MultiType.Input(
                    "model_3d",
                    types=[
                        IO.File3DPointCloudAny,
                        IO.File3DPLY,
                    ],
                    tooltip="Point cloud file (.ply)",
                ),
                IO.Load3DModelInfo.Input("model_3d_info", optional=True, advanced=True),
                IO.Load3D.Input("viewport_state"),
                IO.Load3DCamera.Input("camera_info", optional=True, advanced=True),
                IO.Int.Input("width", default=1024, min=1, max=4096, step=1),
                IO.Int.Input("height", default=1024, min=1, max=4096, step=1),
            ],
            outputs=[
                IO.File3DPointCloudAny.Output(display_name="model_3d"),
                IO.Load3DModelInfo.Output(display_name="model_3d_info"),
                IO.Load3DCamera.Output(display_name="camera_info"),
                IO.Int.Output(display_name="width"),
                IO.Int.Output(display_name="height"),
            ],
        )

    @classmethod
    def execute(cls, model_3d: Types.File3D, viewport_state, width: int, height: int, **kwargs) -> IO.NodeOutput:
        filename = f"preview_pointcloud_{uuid.uuid4().hex}.{model_3d.format}"
        model_3d.save_to(os.path.join(folder_paths.get_temp_directory(), filename))

        viewport_state = viewport_state if isinstance(viewport_state, dict) else {}
        camera_info_input = kwargs.get("camera_info", None)
        camera_info = camera_info_input if camera_info_input is not None else viewport_state.get('camera_info')
        model_3d_info_input = kwargs.get("model_3d_info", None)
        model_3d_info = model_3d_info_input if model_3d_info_input is not None else viewport_state.get('model_3d_info', [])
        return IO.NodeOutput(
            model_3d,
            model_3d_info,
            camera_info,
            width,
            height,
            ui=UI.Saved3DModels([UI.SavedResult(filename, "", IO.FolderType.temp)], camera_info, model_3d_info),
        )


MESH_EXTENSIONS = {'.gltf', '.glb', '.obj', '.fbx', '.stl'}


class Load3DAdvanced(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        input_dir = os.path.join(folder_paths.get_input_directory(), "3d")
        os.makedirs(input_dir, exist_ok=True)

        input_path = Path(input_dir)
        base_path = Path(folder_paths.get_input_directory())

        files = [
            normalize_path(str(file_path.relative_to(base_path)))
            for file_path in input_path.rglob("*")
            if file_path.suffix.lower() in MESH_EXTENSIONS
        ]
        return IO.Schema(
            node_id="Load3DAdvanced",
            display_name="Load 3D (Advanced)",
            category="3d",
            search_aliases=[
                "load mesh",
                "load gltf",
                "load glb",
                "load obj",
                "load fbx",
                "load stl",
            ],
            is_experimental=True,
            inputs=[
                IO.Combo.Input("model_file", options=["none"] + sorted(files), upload=IO.UploadType.model),
                IO.Load3D.Input("viewport_state"),
                IO.Int.Input("width", default=1024, min=1, max=4096, step=1, tooltip="Render width of the viewport in pixels."),
                IO.Int.Input("height", default=1024, min=1, max=4096, step=1, tooltip="Render height of the viewport in pixels."),
            ],
            outputs=[
                IO.File3DAny.Output(display_name="model_3d", tooltip="Loaded 3D model file (glb/obj/stl/etc.)."),
                IO.Load3DModelInfo.Output(display_name="model_3d_info", tooltip="Placement of each model in the scene: position, rotation, and scale (Y-up world space)."),
                IO.Load3DCamera.Output(display_name="camera_info", tooltip="Viewport camera information: position, look-at target, zoom, and type."),
                IO.Int.Output(display_name="width", tooltip="Render width of the viewport in pixels."),
                IO.Int.Output(display_name="height", tooltip="Render height of the viewport in pixels."),
            ],
        )

    @classmethod
    def validate_inputs(cls, model_file, **kwargs) -> bool | str:
        if not model_file or model_file == "none":
            return True
        if not folder_paths.exists_annotated_filepath(model_file):
            return f"Invalid 3D model file: {model_file}"
        return True

    @classmethod
    def execute(cls, model_file, viewport_state, width: int, height: int, **kwargs) -> IO.NodeOutput:
        file_3d = None
        if model_file and model_file != "none":
            file_3d = Types.File3D(folder_paths.get_annotated_filepath(model_file))
        viewport_state = viewport_state if isinstance(viewport_state, dict) else {}
        model_3d_info = viewport_state.get('model_3d_info', [])
        return IO.NodeOutput(file_3d, model_3d_info, viewport_state.get('camera_info'), width, height)


# Local BVH mocap import: single-root, Y-up BVH from input/3d -> animated,
# bones-only GLB (no body model needed). Offsets and positions are converted
# from the user-selected source unit to glTF metres; End Sites become leaf
# nodes so terminal bone lengths survive; channels are consumed in the exact
# order each joint declares them; keyframe times come from Frame Time.

class BVHParseError(ValueError):
    pass


@dataclass
class BVHJoint:
    name: str
    parent: int                         # -1 = root
    offset: np.ndarray                  # (3,) source units, parent-relative
    # (0 = position / 1 = rotation, axis 0/1/2 = x/y/z), in declared order
    channels: list[tuple[int, int]]
    channel_start: int                  # first motion column of this joint
    children: list[int] = field(default_factory=list)
    end_site: bool = False


@dataclass
class BVHClip:
    joints: list[BVHJoint]
    frame_count: int
    frame_time: float
    motion: np.ndarray                  # (frame_count, total_channels); source units / degrees


_TOKEN_SPLIT = re.compile(r"[\s:]+")
_AXES = "xyz"


def parse_bvh(text: str) -> BVHClip:
    """Parse a BVH document. Raises BVHParseError on structural damage or on
    motion data that does not match the declared Frames/CHANNELS layout."""
    tokens: list[tuple[str, int]] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for token in _TOKEN_SPLIT.split(line.strip()):
            if token:
                tokens.append((token, lineno))

    parser = _BVHParser(tokens)
    return parser.parse()


class _BVHParser:
    def __init__(self, tokens: list[tuple[str, int]]):
        self.tokens = tokens
        self.pos = 0
        self.joints: list[BVHJoint] = []
        self.total_channels = 0
        self.root_count = 0

    def _take(self) -> tuple[str, int]:
        if self.pos >= len(self.tokens):
            raise BVHParseError("BVH parse error: unexpected end of file")
        token, lineno = self.tokens[self.pos]
        self.pos += 1
        return token, lineno

    def _expect(self, expected: str) -> None:
        token, lineno = self._take()
        if token != expected:
            raise BVHParseError(
                f"BVH parse error on line {lineno}: expected {expected!r}, got {token!r}"
            )

    def _number(self) -> float:
        token, lineno = self._take()
        try:
            value = float(token)
        except ValueError:
            raise BVHParseError(
                f"BVH parse error on line {lineno}: expected a number, got {token!r}"
            )
        if not np.isfinite(value):
            raise BVHParseError(
                f"BVH parse error on line {lineno}: non-finite number {token!r}"
            )
        return value

    def _integer(self, what: str) -> int:
        token, lineno = self._take()
        try:
            value = int(token)
        except ValueError:
            raise BVHParseError(
                f"BVH parse error on line {lineno}: {what} must be an integer, got {token!r}"
            )
        return value

    def parse(self) -> BVHClip:
        self._expect("HIERARCHY")
        self._parse_joint(-1)
        if self.root_count != 1:
            raise BVHParseError("BVH parse error: hierarchy must contain exactly one ROOT joint")

        token, lineno = self._take()
        if token != "MOTION":
            raise BVHParseError(
                f"BVH parse error on line {lineno}: expected 'MOTION', got {token!r}"
            )
        self._expect("Frames")
        frame_count = self._integer("Frames")
        if frame_count <= 0:
            raise BVHParseError(f"BVH parse error: Frames must be >= 1, got {frame_count}")
        self._expect("Frame")
        self._expect("Time")
        frame_time = self._number()
        if frame_time <= 0.0:
            raise BVHParseError(f"BVH parse error: Frame Time must be > 0, got {frame_time}")

        remaining = self.tokens[self.pos:]
        needed = frame_count * self.total_channels
        if len(remaining) != needed:
            raise BVHParseError(
                f"BVH motion data mismatch: Frames: {frame_count} x {self.total_channels} "
                f"declared channels = {needed} values, file contains {len(remaining)}"
            )
        try:
            values = np.asarray([token for token, _ in remaining], dtype=np.float64)
        except ValueError:
            raise BVHParseError("BVH motion data contains a non-numeric value")
        if not np.isfinite(values).all():
            raise BVHParseError("BVH motion data contains a non-finite value")
        motion = values.reshape(frame_count, self.total_channels)

        return BVHClip(self.joints, frame_count, frame_time, motion)

    def _parse_joint(self, parent: int, keyword: str | None = None) -> int:
        is_root = parent < 0
        if keyword is None:
            keyword, lineno = self._take()
        else:
            lineno = self.tokens[self.pos - 1][1]
        expected_keyword = "ROOT" if is_root else "JOINT"
        if keyword != expected_keyword:
            raise BVHParseError(
                f"BVH parse error on line {lineno}: expected {expected_keyword!r}, got {keyword!r}"
            )
        if is_root:
            self.root_count += 1
            if self.root_count > 1:
                raise BVHParseError("BVH parse error: multiple ROOT joints; only a single root is supported")

        name, _ = self._take()
        self._expect("{")

        index = len(self.joints)
        joint = BVHJoint(name=name, parent=parent, offset=np.zeros(3),
                         channels=[], channel_start=self.total_channels)
        self.joints.append(joint)

        have_offset = False
        have_channels = False
        have_end_site = False
        while True:
            token, token_line = self._take()
            if token == "}":
                if not have_offset:
                    raise BVHParseError(f"BVH parse error: joint {name!r} is missing OFFSET")
                if not have_channels:
                    raise BVHParseError(f"BVH parse error: joint {name!r} is missing CHANNELS")
                break
            if have_end_site:
                raise BVHParseError(
                    f"BVH parse error on line {token_line}: End Site must be the last "
                    f"child of joint {name!r}, got {token!r}"
                )
            if token == "OFFSET":
                if have_offset:
                    raise BVHParseError(f"BVH parse error: duplicate OFFSET in joint {name!r}")
                offset = np.array([self._number(), self._number(), self._number()], dtype=np.float64)
                joint.offset = offset
                have_offset = True
            elif token == "CHANNELS":
                if have_channels:
                    raise BVHParseError(f"BVH parse error: duplicate CHANNELS in joint {name!r}")
                count = self._integer("CHANNELS count")
                if not 0 <= count <= 6:
                    raise BVHParseError(
                        f"BVH parse error in joint {name!r}: CHANNELS count must be 0-6, got {count}"
                    )
                channels: list[tuple[int, int]] = []
                for _ in range(count):
                    channel_token, channel_line = self._take()
                    lowered = channel_token.lower()
                    axis_char, kind = lowered[:1], lowered[1:]
                    if axis_char not in _AXES or kind not in ("position", "rotation"):
                        raise BVHParseError(
                            f"BVH parse error on line {channel_line}: invalid channel "
                            f"{channel_token!r} in joint {name!r}"
                        )
                    channels.append((0 if kind == "position" else 1, _AXES.index(axis_char)))
                for channel_kind in (0, 1):
                    axes = [axis for kind, axis in channels if kind == channel_kind]
                    if len(axes) != len(set(axes)):
                        kind_name = "position" if channel_kind == 0 else "rotation"
                        raise BVHParseError(
                            f"BVH parse error in joint {name!r}: duplicate {kind_name} axis in CHANNELS"
                        )
                joint.channels = channels
                joint.channel_start = self.total_channels
                self.total_channels += count
                have_channels = True
            elif token == "JOINT":
                child = self._parse_joint(index, keyword="JOINT")
                joint.children.append(child)
            elif token == "End":
                self._expect("Site")
                self._expect("{")
                token2, line2 = self._take()
                if token2 != "OFFSET":
                    raise BVHParseError(
                        f"BVH parse error on line {line2}: expected 'OFFSET' in End Site, got {token2!r}"
                    )
                end_offset = np.array([self._number(), self._number(), self._number()], dtype=np.float64)
                self._expect("}")
                end = BVHJoint(name=f"{name}_End", parent=index, offset=end_offset,
                               channels=[], channel_start=-1, end_site=True)
                end_index = len(self.joints)
                self.joints.append(end)
                joint.children.append(end_index)
                have_end_site = True
            else:
                raise BVHParseError(
                    f"BVH parse error on line {token_line}: unexpected token {token!r} in joint {name!r}"
                )

        return index


# glTF binary builder (bones-only subset; mirrors the layout used by the
# sam3d_body GLB exporter without taking on its rig dependencies).

_GL_FLOAT = 5126
_GL_UINT = 5125
_GL_USHORT = 5123
_GL_ARRAY_BUFFER = 34962
_GL_ELEMENT_ARRAY_BUFFER = 34963


def _glb_pad4(data: bytes, fill: bytes = b"\x00") -> bytes:
    return data + fill * ((4 - len(data) % 4) % 4)


class _GLBBuilder:
    def __init__(self):
        self.buffer = bytearray()
        self.buffer_views: list[dict] = []
        self.accessors: list[dict] = []

    def _view(self, data: bytes, target: int | None = None) -> int:
        offset = len(self.buffer)
        self.buffer += data
        pad = (4 - (offset + len(data)) % 4) % 4
        if pad:
            self.buffer += b"\x00" * pad
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        self.buffer_views.append(view)
        return len(self.buffer_views) - 1

    def _accessor(self, array: np.ndarray, component_type: int, type_name: str,
                  target: int | None = None, minmax: bool = False) -> int:
        view_index = self._view(array.tobytes(), target)
        accessor = {
            "bufferView": view_index, "componentType": component_type,
            "count": int(array.shape[0]), "type": type_name,
        }
        if minmax:
            flat = array.reshape(array.shape[0], -1)
            accessor["min"] = flat.min(axis=0).tolist()
            accessor["max"] = flat.max(axis=0).tolist()
        self.accessors.append(accessor)
        return len(self.accessors) - 1

    def vec3(self, array: np.ndarray, *, target: int | None = _GL_ARRAY_BUFFER,
             minmax: bool = False) -> int:
        return self._accessor(np.ascontiguousarray(array, dtype=np.float32),
                              _GL_FLOAT, "VEC3", target, minmax)

    def vec4(self, array: np.ndarray, *, target: int | None = None) -> int:
        return self._accessor(np.ascontiguousarray(array, dtype=np.float32),
                              _GL_FLOAT, "VEC4", target)

    def mat4(self, array: np.ndarray) -> int:
        return self._accessor(np.ascontiguousarray(array, dtype=np.float32),
                              _GL_FLOAT, "MAT4")

    def scalar(self, array: np.ndarray) -> int:
        return self._accessor(np.ascontiguousarray(array, dtype=np.float32).reshape(-1),
                              _GL_FLOAT, "SCALAR")

    def indices_u32(self, array: np.ndarray) -> int:
        return self._accessor(np.ascontiguousarray(array, dtype=np.uint32).reshape(-1),
                              _GL_UINT, "SCALAR", _GL_ELEMENT_ARRAY_BUFFER)

    def joints_u16(self, array: np.ndarray) -> int:
        return self._accessor(np.ascontiguousarray(array, dtype=np.uint16),
                              _GL_USHORT, "VEC4", _GL_ARRAY_BUFFER)

    def finish(self, gltf: dict) -> bytes:
        gltf["buffers"] = [{"byteLength": len(self.buffer)}]
        gltf["bufferViews"] = self.buffer_views
        gltf["accessors"] = self.accessors
        json_bytes = _glb_pad4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
        bin_bytes = _glb_pad4(bytes(self.buffer))
        total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
        return (
            struct.pack("<4sII", b"glTF", 2, total)
            + struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
            + struct.pack("<II", len(bin_bytes), 0x004E4942) + bin_bytes
        )


def _quat_multiply(q: np.ndarray, r: np.ndarray) -> np.ndarray:
    """xyzw quaternion product, broadcast over leading dims."""
    qx, qy, qz, qw = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    rx, ry, rz, rw = r[..., 0], r[..., 1], r[..., 2], r[..., 3]
    return np.stack([
        qw * rx + qx * rw + qy * rz - qz * ry,
        qw * ry - qx * rz + qy * rw + qz * rx,
        qw * rz + qx * ry - qy * rx + qz * rw,
        qw * rw - qx * rx - qy * ry - qz * rz,
    ], axis=-1)


def _rotation_align(from_vec: np.ndarray, to_vec: np.ndarray) -> np.ndarray:
    """3x3 rotation mapping unit from_vec onto unit to_vec (Rodrigues)."""
    cos_t = float(np.dot(from_vec, to_vec))
    cross = np.cross(from_vec, to_vec)
    sin_t = float(np.linalg.norm(cross))
    if sin_t < 1e-8:
        if cos_t > 0:
            return np.eye(3, dtype=np.float64)
        return np.diag([1.0, -1.0, -1.0]).astype(np.float64)
    axis = cross / sin_t
    k = np.array([
        [0.0, -axis[2], axis[1]],
        [axis[2], 0.0, -axis[0]],
        [-axis[1], axis[0], 0.0],
    ], dtype=np.float64)
    return np.eye(3, dtype=np.float64) + sin_t * k + (1.0 - cos_t) * (k @ k)


# Blender-style bone octahedron: head at origin, tail at +Y, unit length.
_OCT_VERTS = np.array([
    [0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [1.0, 0.1, 0.0],
    [-1.0, 0.1, 0.0],
    [0.0, 0.1, 1.0],
    [0.0, 0.1, -1.0],
], dtype=np.float64)
_OCT_FACES = np.array([
    [0, 2, 4], [0, 5, 2], [0, 3, 5], [0, 4, 3],
    [1, 4, 2], [1, 3, 4], [1, 5, 3], [1, 2, 5],
], dtype=np.uint32)
_OCT_NORMALS = np.array([
    [0.0, -1.0, 0.0],
    [0.0, 1.0, 0.0],
    [1.0, 0.0, 0.0],
    [-1.0, 0.0, 0.0],
    [0.0, 0.0, 1.0],
    [0.0, 0.0, -1.0],
], dtype=np.float64)

_BONE_HALF_WIDTH_CAP_M = 0.02
_BONE_WIDTH_RATIO = 0.1
_BONE_MIN_HALF_WIDTH_M = 0.001


def _build_bone_octahedrons(rest_m: np.ndarray, joints: list[BVHJoint]):
    """One skinned octahedron per parent->child edge (End Site leaves included)."""
    verts: list[np.ndarray] = []
    normals: list[np.ndarray] = []
    faces: list[np.ndarray] = []
    skin_joints: list[list[int]] = []
    skin_weights: list[list[float]] = []
    canonical_y = np.array([0.0, 1.0, 0.0], dtype=np.float64)

    for child_index in range(1, len(joints)):
        parent_index = joints[child_index].parent
        head = rest_m[parent_index]
        tail = rest_m[child_index]
        direction = tail - head
        length = float(np.linalg.norm(direction))
        if length < 1e-6:
            continue
        align = _rotation_align(canonical_y, direction / length)
        half_width = max(_BONE_MIN_HALF_WIDTH_M,
                         min(length * _BONE_WIDTH_RATIO, _BONE_HALF_WIDTH_CAP_M))
        local_scale = np.array([half_width, length, half_width], dtype=np.float64)

        vertex_offset = len(verts)
        verts.extend((_OCT_VERTS * local_scale) @ align.T + head)
        normals.extend(_OCT_NORMALS @ align.T)
        faces.extend(_OCT_FACES + vertex_offset)
        for k in range(_OCT_VERTS.shape[0]):
            # Head pole follows the parent, tail pole follows the child; ridges
            # blend by canonical Y so the bone stretches between the two joints.
            w_child = float(min(max(_OCT_VERTS[k, 1], 0.0), 1.0))
            w_parent = 1.0 - w_child
            skin_joints.append([parent_index, child_index, 0, 0])
            skin_weights.append([w_parent, w_child, 0.0, 0.0])

    if not verts:
        return None
    return (
        np.asarray(verts, dtype=np.float32),
        np.asarray(normals, dtype=np.float32),
        np.asarray(faces, dtype=np.uint32),
        np.asarray(skin_joints, dtype=np.uint16),
        np.asarray(skin_weights, dtype=np.float32),
    )


def build_bvh_glb(clip: BVHClip, unit_scale: float) -> bytes:
    """Convert a parsed BVH clip to a self-contained animated, bones-only GLB.

    unit_scale converts source units to glTF metres (0.01 for cm, 1.0 for m).
    The bind pose is the OFFSET chain with identity rotations. Rest local
    rotations are identity; each joint's rotation channels compose in the
    intrinsic order the CHANNELS line declares.
    """
    joints = clip.joints
    joint_count = len(joints)
    if joint_count > 65535:
        raise BVHParseError(f"BVH has {joint_count} joints; the skeleton GLB supports at most 65535")

    offsets_m = (np.stack([joint.offset for joint in joints]).astype(np.float64)
                 * float(unit_scale)).astype(np.float32)
    rest_m = np.zeros_like(offsets_m)
    for index, joint in enumerate(joints):
        if joint.parent < 0:
            rest_m[index] = offsets_m[index]
        else:
            rest_m[index] = rest_m[joint.parent] + offsets_m[index]

    glb = _GLBBuilder()

    nodes: list[dict] = []
    for index, joint in enumerate(joints):
        node = {"name": joint.name, "translation": offsets_m[index].tolist()}
        if joint.children:
            node["children"] = list(joint.children)
        nodes.append(node)

    samplers: list[dict] = []
    animation_channels: list[dict] = []
    frame_count = clip.frame_count
    time_accessor = glb.scalar(np.arange(frame_count, dtype=np.float64) * clip.frame_time)
    motion = clip.motion

    for index, joint in enumerate(joints):
        if joint.end_site or not joint.channels:
            continue
        position_specs = [
            (axis, joint.channel_start + k)
            for k, (kind, axis) in enumerate(joint.channels) if kind == 0
        ]
        rotation_specs = [
            (axis, joint.channel_start + k)
            for k, (kind, axis) in enumerate(joint.channels) if kind == 1
        ]

        if position_specs:
            translations = np.broadcast_to(offsets_m[index], (frame_count, 3)).copy()
            for axis, column in position_specs:
                translations[:, axis] = motion[:, column] * float(unit_scale)
            if float(np.ptp(translations, axis=0).max()) < 1e-7:
                nodes[index]["translation"] = translations[0].tolist()
            else:
                accessor = glb.vec3(translations, target=None)
                samplers.append({"input": time_accessor, "output": accessor, "interpolation": "LINEAR"})
                animation_channels.append({
                    "sampler": len(samplers) - 1,
                    "target": {"node": index, "path": "translation"},
                })

        if rotation_specs:
            quaternion = None
            for axis, column in rotation_specs:
                half_angles = np.deg2rad(motion[:, column]) * 0.5
                rotation = np.zeros((frame_count, 4), dtype=np.float64)
                rotation[:, axis] = np.sin(half_angles)
                rotation[:, 3] = np.cos(half_angles)
                quaternion = rotation if quaternion is None else _quat_multiply(quaternion, rotation)
            quaternion = quaternion / np.maximum(np.linalg.norm(quaternion, axis=-1, keepdims=True), 1e-12)
            quaternion = quaternion.astype(np.float32)
            if float(np.ptp(quaternion, axis=0).max()) < 1e-7:
                nodes[index]["rotation"] = quaternion[0].tolist()
            else:
                accessor = glb.vec4(quaternion)
                samplers.append({"input": time_accessor, "output": accessor, "interpolation": "LINEAR"})
                animation_channels.append({
                    "sampler": len(samplers) - 1,
                    "target": {"node": index, "path": "rotation"},
                })

    scene_nodes = [0]
    meshes: list[dict] = []
    skins: list[dict] = []
    materials: list[dict] = []

    bone_geometry = _build_bone_octahedrons(rest_m, joints)
    if bone_geometry is not None:
        positions, normals, faces, skin_joints, skin_weights = bone_geometry
        position_accessor = glb.vec3(positions, minmax=True)
        normal_accessor = glb.vec3(normals)
        index_accessor = glb.indices_u32(faces)
        joints_accessor = glb.joints_u16(skin_joints)
        weights_accessor = glb.vec4(skin_weights)

        # Bind pose is pure offset translations; inverse bind = T(-rest).
        inverse_bind = np.zeros((joint_count, 4, 4), dtype=np.float32)
        inverse_bind[:, 0, 0] = 1.0
        inverse_bind[:, 1, 1] = 1.0
        inverse_bind[:, 2, 2] = 1.0
        inverse_bind[:, 3, 3] = 1.0
        inverse_bind[:, :3, 3] = -rest_m
        inverse_bind = inverse_bind.transpose(0, 2, 1)  # glTF MAT4 is column-major
        ibm_accessor = glb.mat4(inverse_bind)

        materials.append({
            "pbrMetallicRoughness": {
                "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.85,
            },
        })
        meshes.append({"primitives": [{
            "attributes": {
                "POSITION": position_accessor,
                "NORMAL": normal_accessor,
                "JOINTS_0": joints_accessor,
                "WEIGHTS_0": weights_accessor,
            },
            "indices": index_accessor,
            "material": 0,
            "mode": 4,
        }]})
        skins.append({
            "joints": list(range(joint_count)),
            "inverseBindMatrices": ibm_accessor,
            "skeleton": 0,
        })
        nodes.append({"name": "bvh_skeleton", "mesh": 0, "skin": 0})
        scene_nodes.append(len(nodes) - 1)

    gltf = {
        "asset": {"version": "2.0", "generator": "ComfyUI"},
        "scene": 0,
        "scenes": [{"nodes": scene_nodes}],
        "nodes": nodes,
    }
    if meshes:
        gltf["meshes"] = meshes
        gltf["skins"] = skins
        gltf["materials"] = materials
    if samplers:
        gltf["animations"] = [{
            "name": "bvh_animation",
            "samplers": samplers,
            "channels": animation_channels,
        }]

    return glb.finish(gltf)


def resolve_bvh_path(bvh_file: str) -> str:
    """Resolve a combo value against the input directory (same convention as
    the other file-upload combos) and require it to stay inside input/3d."""
    input_3d = os.path.join(folder_paths.get_input_directory(), "3d")
    try:
        path = folder_paths.get_annotated_filepath(bvh_file)
    except ValueError:
        path = None
    if path is None or not folder_paths.is_within_directory(input_3d, path):
        raise ValueError(f"Load BVH Animation: {bvh_file!r} resolves outside input/3d")
    return path


class LoadBVHAnimation(IO.ComfyNode):
    @classmethod
    def define_schema(cls):
        input_dir = os.path.join(folder_paths.get_input_directory(), "3d")
        os.makedirs(input_dir, exist_ok=True)

        files = [
            normalize_path(str(file_path.relative_to(folder_paths.get_input_directory())))
            for file_path in Path(input_dir).rglob("*")
            if file_path.is_file() and file_path.suffix.lower() == ".bvh"
        ]
        return IO.Schema(
            node_id="LoadBVHAnimation",
            display_name="Load BVH Animation",
            category="3d",
            search_aliases=["bvh", "mocap", "motion capture", "load bvh", "skeleton animation"],
            description="Load a BVH mocap clip from input/3d as an animated skeleton GLB.",
            is_experimental=True,
            inputs=[
                IO.Combo.Input(
                    "bvh_file",
                    options=["none"] + sorted(files),
                    upload=IO.UploadType.model,
                    tooltip="BVH file from input/3d. Must have a single ROOT joint and be Y-up.",
                ),
                IO.Combo.Input(
                    "units",
                    options=["cm", "m"],
                    default="cm",
                    tooltip="Units the BVH OFFSET/position values were authored in. "
                            "The GLB is always written in metres. 'cm' is the mocap standard.",
                ),
            ],
            outputs=[
                IO.File3DGLB.Output(
                    display_name="model_3d",
                    tooltip="Animated GLB with visible skeleton bones. Connect to Preview 3D or Save 3D Model.",
                ),
            ],
        )

    @classmethod
    def validate_inputs(cls, bvh_file, **kwargs) -> bool | str:
        if not bvh_file or bvh_file == "none":
            return True
        try:
            path = resolve_bvh_path(bvh_file)
        except ValueError:
            return f"Invalid BVH file: {bvh_file}"
        if not os.path.isfile(path):
            return f"Invalid BVH file: {bvh_file}"
        return True

    @classmethod
    def execute(cls, bvh_file, units: str = "cm", **kwargs) -> IO.NodeOutput:
        if not bvh_file or bvh_file == "none":
            return IO.NodeOutput(None)
        if units not in ("cm", "m"):
            raise ValueError(f"Load BVH Animation: units must be 'cm' or 'm', got {units!r}")

        path = resolve_bvh_path(bvh_file)
        if not os.path.isfile(path):
            raise ValueError(f"Load BVH Animation: BVH file not found: {bvh_file!r}")

        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as e:
            raise ValueError(f"Load BVH Animation: {bvh_file!r} is not valid UTF-8 text") from e

        clip = parse_bvh(text)
        glb_bytes = build_bvh_glb(clip, 0.01 if units == "cm" else 1.0)
        return IO.NodeOutput(Types.File3D(BytesIO(glb_bytes), file_format="glb"))

    process = execute  # TODO: remove


class Load3DExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[IO.ComfyNode]]:
        return [
            Load3D,
            Load3DAdvanced,
            LoadBVHAnimation,
            Preview3D,
            Preview3DAdvanced,
            PreviewGaussianSplat,
            PreviewPointCloud,
        ]


async def comfy_entrypoint() -> Load3DExtension:
    return Load3DExtension()
