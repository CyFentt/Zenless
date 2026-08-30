from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, cast

Vec3 = tuple[float, float, float]
Face = tuple[int, int, int]
Matrix4 = tuple[float, ...]

JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
MAX_GLB_BYTES = 512 * 1024 * 1024


class GLBError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MeshData:
    name: str
    vertices: tuple[Vec3, ...]
    faces: tuple[Face, ...]
    minimum: Vec3
    maximum: Vec3

    @property
    def center(self) -> Vec3:
        return cast(Vec3, tuple((low + high) * 0.5 for low, high in zip(self.minimum, self.maximum)))

    @property
    def radius(self) -> float:
        cx, cy, cz = self.center
        return max(
            math.dist((cx, cy, cz), self.minimum),
            math.dist((cx, cy, cz), self.maximum),
            1e-6,
        )


_COMPONENTS: dict[int, tuple[str, int]] = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
_ARITY = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
_IDENTITY: Matrix4 = (
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
)


def load_glb(path: Path | str, *, max_vertices: int = 250_000, max_faces: int = 250_000) -> MeshData:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise GLBError(f"GLB file not found: {source}")
    size = source.stat().st_size
    if size < 20 or size > MAX_GLB_BYTES:
        raise GLBError("The GLB is empty, truncated, or larger than 512 MiB.")
    raw = source.read_bytes()
    magic, version, declared_length = struct.unpack_from("<4sII", raw, 0)
    if magic != b"glTF" or version != 2 or declared_length != len(raw):
        raise GLBError("Invalid GLB 2.0 header.")

    document: dict[str, Any] | None = None
    binary = b""
    offset = 12
    while offset + 8 <= len(raw):
        chunk_length, chunk_type = struct.unpack_from("<II", raw, offset)
        offset += 8
        end = offset + chunk_length
        if chunk_length < 0 or end > len(raw):
            raise GLBError("Truncated GLB chunk.")
        payload = raw[offset:end]
        offset = end
        if chunk_type == JSON_CHUNK and document is None:
            try:
                value = json.loads(payload.rstrip(b" \t\r\n\0").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GLBError("Invalid GLB JSON chunk.") from exc
            if not isinstance(value, dict):
                raise GLBError("The glTF document must be a JSON object.")
            document = value
        elif chunk_type == BIN_CHUNK and not binary:
            binary = payload
    if document is None or not binary:
        raise GLBError("GLB is missing required JSON or BIN chunks.")

    vertices: list[Vec3] = []
    faces: list[Face] = []
    meshes = document.get("meshes") or []
    nodes = document.get("nodes") or []
    if not isinstance(meshes, list) or not meshes:
        raise GLBError("GLB contains no meshes.")

    def emit_mesh(mesh_index: int, transform: Matrix4) -> None:
        if not 0 <= mesh_index < len(meshes) or not isinstance(meshes[mesh_index], dict):
            raise GLBError("A node references a missing mesh.")
        primitives = meshes[mesh_index].get("primitives") or []
        for primitive in primitives:
            if not isinstance(primitive, dict):
                continue
            attributes = primitive.get("attributes") or {}
            position_index = attributes.get("POSITION") if isinstance(attributes, dict) else None
            if not isinstance(position_index, int):
                continue
            positions = _read_accessor(document, binary, position_index)
            if len(vertices) + len(positions) > max_vertices:
                raise GLBError(f"GLB exceeds the {max_vertices:,} vertex limit.")
            base = len(vertices)
            for value in positions:
                if not isinstance(value, tuple) or len(value) < 3:
                    raise GLBError("POSITION accessor is not VEC3.")
                vertices.append(_transform_point(transform, (float(value[0]), float(value[1]), float(value[2]))))

            index_accessor = primitive.get("indices")
            if isinstance(index_accessor, int):
                raw_indices = _read_accessor(document, binary, index_accessor)
                indices = [int(item if not isinstance(item, tuple) else item[0]) for item in raw_indices]
            else:
                indices = list(range(len(positions)))
            mode = int(primitive.get("mode", 4))
            for a, b, c in _triangles(indices, mode):
                if min(a, b, c) < 0 or max(a, b, c) >= len(positions):
                    raise GLBError("Triangle index is outside the POSITION accessor.")
                if len(faces) >= max_faces:
                    raise GLBError(f"GLB exceeds the {max_faces:,} face limit.")
                if a != b and b != c and a != c:
                    faces.append((base + a, base + b, base + c))

    if isinstance(nodes, list) and nodes:
        scenes = document.get("scenes") or []
        scene_index = int(document.get("scene", 0) or 0)
        roots: list[int] = []
        if isinstance(scenes, list) and 0 <= scene_index < len(scenes) and isinstance(scenes[scene_index], dict):
            roots = [int(item) for item in scenes[scene_index].get("nodes", []) if isinstance(item, int)]
        if not roots:
            children = {
                int(child)
                for node in nodes
                if isinstance(node, dict)
                for child in node.get("children", [])
                if isinstance(child, int)
            }
            roots = [index for index in range(len(nodes)) if index not in children]

        def visit(node_index: int, parent: Matrix4, chain: frozenset[int]) -> None:
            if node_index in chain:
                raise GLBError("Cycle detected in the node hierarchy.")
            if not 0 <= node_index < len(nodes) or not isinstance(nodes[node_index], dict):
                raise GLBError("The scene references a missing node.")
            node = nodes[node_index]
            transform = _matrix_multiply(parent, _node_matrix(node))
            mesh_index = node.get("mesh")
            if isinstance(mesh_index, int):
                emit_mesh(mesh_index, transform)
            next_chain = chain | {node_index}
            for child in node.get("children", []):
                if isinstance(child, int):
                    visit(child, transform, next_chain)

        for root in roots:
            visit(root, _IDENTITY, frozenset())
    else:
        for index in range(len(meshes)):
            emit_mesh(index, _IDENTITY)

    if not vertices or not faces:
        raise GLBError("No renderable triangle geometry was found.")
    minimum = cast(Vec3, tuple(min(vertex[axis] for vertex in vertices) for axis in range(3)))
    maximum = cast(Vec3, tuple(max(vertex[axis] for vertex in vertices) for axis in range(3)))
    return MeshData(source.name, tuple(vertices), tuple(faces), minimum, maximum)


def project_triangles(
    mesh: MeshData,
    angle: float,
    width: int,
    height: int,
    *,
    max_draw_faces: int = 2_400,
) -> list[tuple[float, tuple[float, float, float, float, float, float], float]]:
    if width < 10 or height < 10:
        return []
    step = max(1, math.ceil(len(mesh.faces) / max(1, max_draw_faces)))
    selected = mesh.faces[::step]
    used = {index for face in selected for index in face}
    cx, cy, cz = mesh.center
    radius = mesh.radius
    sin_y, cos_y = math.sin(angle), math.cos(angle)
    sin_x, cos_x = math.sin(-0.32), math.cos(-0.32)
    transformed: dict[int, Vec3] = {}
    projected: dict[int, tuple[float, float]] = {}
    scale = min(width, height) * 0.68
    for index in used:
        vx, vy, vz = mesh.vertices[index]
        x, y, z = (vx - cx) / radius, (vy - cy) / radius, (vz - cz) / radius
        rx = x * cos_y - z * sin_y
        rz = x * sin_y + z * cos_y
        ry = y * cos_x - rz * sin_x
        rz2 = y * sin_x + rz * cos_x
        transformed[index] = (rx, ry, rz2)
        perspective = 3.2 / max(0.35, 3.2 - rz2)
        projected[index] = (width * 0.5 + rx * scale * perspective, height * 0.52 - ry * scale * perspective)

    output: list[tuple[float, tuple[float, float, float, float, float, float], float]] = []
    light = (0.25, -0.35, 0.9)
    for face in selected:
        a, b, c = (transformed[index] for index in face)
        ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        normal = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        magnitude = max(1e-9, math.sqrt(sum(value * value for value in normal)))
        intensity = max(0.12, min(1.0, 0.34 + 0.66 * abs(sum(normal[i] * light[i] for i in range(3))) / magnitude))
        pa, pb, pc = (projected[index] for index in face)
        coords = (pa[0], pa[1], pb[0], pb[1], pc[0], pc[1])
        output.append(((a[2] + b[2] + c[2]) / 3.0, coords, intensity))
    output.sort(key=lambda item: item[0])
    return output


def _read_accessor(document: dict[str, Any], binary: bytes, index: int) -> list[Any]:
    accessors = document.get("accessors") or []
    views = document.get("bufferViews") or []
    if not isinstance(accessors, list) or not 0 <= index < len(accessors) or not isinstance(accessors[index], dict):
        raise GLBError("Accessor does not exist.")
    accessor = accessors[index]
    if accessor.get("sparse"):
        raise GLBError("Sparse accessors are not supported by the local preview.")
    view_index = accessor.get("bufferView")
    if not isinstance(view_index, int) or not isinstance(views, list) or not 0 <= view_index < len(views):
        raise GLBError("Accessor has no valid bufferView.")
    view = views[view_index]
    if not isinstance(view, dict) or int(view.get("buffer", 0)) != 0:
        raise GLBError("GLB preview supports only the embedded binary buffer.")
    component = int(accessor.get("componentType", 0))
    kind = str(accessor.get("type", ""))
    if component not in _COMPONENTS or kind not in _ARITY:
        raise GLBError("Unsupported accessor format.")
    fmt, component_size = _COMPONENTS[component]
    arity = _ARITY[kind]
    count = int(accessor.get("count", 0))
    if count < 0:
        raise GLBError("Accessor count is invalid.")
    unpacker = struct.Struct("<" + fmt * arity)
    stride = int(view.get("byteStride", unpacker.size))
    if stride < unpacker.size:
        raise GLBError("byteStride is smaller than the accessor item.")
    start = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    view_end = int(view.get("byteOffset", 0)) + int(view.get("byteLength", len(binary)))
    last_end = start if count == 0 else start + (count - 1) * stride + unpacker.size
    if start < 0 or last_end > len(binary) or last_end > view_end:
        raise GLBError("Accessor exceeds the binary buffer.")
    values: list[Any] = []
    for item in range(count):
        decoded = unpacker.unpack_from(binary, start + item * stride)
        values.append(decoded[0] if arity == 1 else decoded)
    return values


def _triangles(indices: list[int], mode: int) -> Iterable[Face]:
    if mode == 4:
        for offset in range(0, len(indices) - 2, 3):
            yield indices[offset], indices[offset + 1], indices[offset + 2]
    elif mode == 5:
        for offset in range(len(indices) - 2):
            a, b, c = indices[offset : offset + 3]
            yield (b, a, c) if offset % 2 else (a, b, c)
    elif mode == 6 and indices:
        for offset in range(1, len(indices) - 1):
            yield indices[0], indices[offset], indices[offset + 1]


def _node_matrix(node: dict[str, Any]) -> Matrix4:
    matrix = node.get("matrix")
    if isinstance(matrix, list) and len(matrix) == 16:
        values = [float(item) for item in matrix]
        return tuple(values[column * 4 + row] for row in range(4) for column in range(4))
    raw_translation = node.get("translation")
    raw_scale = node.get("scale")
    raw_rotation = node.get("rotation")
    translation = (
        raw_translation if isinstance(raw_translation, list) and len(raw_translation) >= 3 else [0.0, 0.0, 0.0]
    )
    scale = raw_scale if isinstance(raw_scale, list) and len(raw_scale) >= 3 else [1.0, 1.0, 1.0]
    rotation = raw_rotation if isinstance(raw_rotation, list) and len(raw_rotation) >= 4 else [0.0, 0.0, 0.0, 1.0]
    x, y, z, w = (float(rotation[index]) for index in range(4))
    length = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / length, y / length, z / length, w / length
    sx, sy, sz = (float(scale[index]) for index in range(3))
    tx, ty, tz = (float(translation[index]) for index in range(3))
    return (
        (1 - 2 * y * y - 2 * z * z) * sx,
        (2 * x * y - 2 * z * w) * sy,
        (2 * x * z + 2 * y * w) * sz,
        tx,
        (2 * x * y + 2 * z * w) * sx,
        (1 - 2 * x * x - 2 * z * z) * sy,
        (2 * y * z - 2 * x * w) * sz,
        ty,
        (2 * x * z - 2 * y * w) * sx,
        (2 * y * z + 2 * x * w) * sy,
        (1 - 2 * x * x - 2 * y * y) * sz,
        tz,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def _matrix_multiply(left: Matrix4, right: Matrix4) -> Matrix4:
    return tuple(
        sum(left[row * 4 + inner] * right[inner * 4 + column] for inner in range(4))
        for row in range(4)
        for column in range(4)
    )


def _transform_point(matrix: Matrix4, point: Vec3) -> Vec3:
    x, y, z = point
    result = (
        matrix[0] * x + matrix[1] * y + matrix[2] * z + matrix[3],
        matrix[4] * x + matrix[5] * y + matrix[6] * z + matrix[7],
        matrix[8] * x + matrix[9] * y + matrix[10] * z + matrix[11],
    )
    return result
