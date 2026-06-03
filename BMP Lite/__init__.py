bl_info = {
    "name": "Better Motion Path",
    "author": "Jideeh",
    "version": (1, 5, 5),
    "blender": (3, 3, 0),
    "location": "View3D > Sidebar > Animation > Motion Path",
    "description": "Blender 3.3+ add-on: edit an object's location motion path as a thick colored Bezier curve, bake fresh keyframes, and manage motion paths.",
    "category": "Animation",
}

import bpy
import json
from mathutils import Vector
from bpy.app.handlers import persistent

try:
    from bpy_extras import anim_utils
except Exception:
    anim_utils = None

CURVE_PROP_NAME = "_motion_path_edit_curve_for"
CURVE_FRAME_PROP = "_motion_path_edit_curve_frames"
ORIGINAL_PATH_PROP = "_motion_path_edit_original_path_json"
MATERIAL_NAME = "MPE Helper Curve Material"
HANDLE_PROP_NAME = "_motion_path_edit_handle_for"
HANDLE_INDEX_PROP = "_motion_path_edit_handle_index"
HANDLE_ROLE_PROP = "_motion_path_edit_handle_role"
HANDLE_LINE_PROP_NAME = "_motion_path_edit_handle_line_for"
HANDLE_LINE_INDEX_PROP = "_motion_path_edit_handle_line_index"
HANDLE_LINE_ROLE_PROP = "_motion_path_edit_handle_line_role"
HANDLE_SYNC_BUSY = False
AUTO_BAKE_BUSY = False
AUTO_BAKE_PENDING = set()
AUTO_BAKE_TIMER_ACTIVE = False
AUTO_BAKE_STATE = {}


def ensure_object_mode():
    try:
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass


def get_active_anim_object(context):
    obj = context.object
    if obj is None:
        return None
    if obj.type == 'CURVE' and CURVE_PROP_NAME in obj:
        return bpy.data.objects.get(obj.get(CURVE_PROP_NAME))
    return obj


def get_action_slot(obj):
    ad = getattr(obj, "animation_data", None)
    if ad is None:
        return None
    slot = getattr(ad, "action_slot", None)
    if slot is not None:
        return slot
    action = getattr(ad, "action", None)
    slots = getattr(action, "slots", None)
    if slots:
        try:
            return slots[0]
        except Exception:
            return None
    return None


def _channelbag_from_anim_utils(action, slot, ensure=False):
    if anim_utils is None or action is None or slot is None:
        return None

    helper_names = (
        "action_get_channelbag_for_slot",
        "action_ensure_channelbag_for_slot",
    )

    for helper_name in helper_names:
        helper = getattr(anim_utils, helper_name, None)
        if helper is None:
            continue
        try:
            if helper_name == "action_ensure_channelbag_for_slot" or ensure:
                return helper(action, slot)
            return helper(action, slot)
        except Exception:
            continue

    return None


def _channelbag_from_layers(action, slot, ensure=False):
    if action is None or slot is None:
        return None

    layers = getattr(action, "layers", None)
    if layers is None:
        return None

    if ensure:
        try:
            if len(layers) == 0:
                layer = layers.new("Layer")
            else:
                layer = layers[0]
            if len(layer.strips) == 0:
                layer.strips.new(type='KEYFRAME')
        except Exception:
            pass

    for layer in layers:
        strips = getattr(layer, "strips", [])
        for strip in strips:
            channelbag_method = getattr(strip, "channelbag", None)
            if channelbag_method:
                try:
                    return channelbag_method(slot, ensure=ensure)
                except TypeError:
                    try:
                        return channelbag_method(slot)
                    except Exception:
                        pass
                except Exception:
                    pass

            for channelbag in getattr(strip, "channelbags", []):
                try:
                    if getattr(channelbag, "slot", None) == slot:
                        return channelbag
                except Exception:
                    pass
                try:
                    if getattr(channelbag, "slot_handle", None) == getattr(slot, "handle", None):
                        return channelbag
                except Exception:
                    pass

    return None


def get_fcurve_collections(obj, ensure=False):
    if not obj or not obj.animation_data or not obj.animation_data.action:
        return []

    action = obj.animation_data.action

    legacy_fcurves = getattr(action, "fcurves", None)
    if legacy_fcurves is not None:
        return [legacy_fcurves]

    slot = get_action_slot(obj)
    channelbag = _channelbag_from_anim_utils(action, slot, ensure=ensure)
    if channelbag is None:
        channelbag = _channelbag_from_layers(action, slot, ensure=ensure)

    if channelbag is not None and getattr(channelbag, "fcurves", None) is not None:
        return [channelbag.fcurves]

    return []


def get_location_fcurves(obj):
    fcurves = []
    for collection in get_fcurve_collections(obj, ensure=False):
        fcurves.extend([
            fc for fc in collection
            if fc.data_path == "location" and fc.array_index in {0, 1, 2}
        ])
    return fcurves


def get_location_key_frames(obj):
    return sorted({
        int(round(kp.co.x))
        for fc in get_location_fcurves(obj)
        for kp in fc.keyframe_points
    })
def get_editable_control_frames(frames, handle_count):
    frames = sorted({int(frame) for frame in frames})
    if len(frames) <= 2:
        return frames
    count = max(2, min(int(handle_count), len(frames)))
    if count >= len(frames):
        return frames
    indexes = sorted({int(round(i * (len(frames) - 1) / float(count - 1))) for i in range(count)})
    indexes[0] = 0
    indexes[-1] = len(frames) - 1
    return [frames[index] for index in indexes]



def evaluate_location_at_frame(obj, frame):
    loc = obj.location.copy()
    for fc in get_location_fcurves(obj):
        loc[fc.array_index] = fc.evaluate(frame)
    return loc


def world_from_location_value(obj, loc):
    if obj.parent:
        return obj.parent.matrix_world @ loc
    return loc.copy()


def location_value_from_world(obj, world_pos):
    if obj.parent:
        return obj.parent.matrix_world.inverted() @ world_pos
    return world_pos.copy()


def find_existing_curve_for(obj):
    if obj is None:
        return None
    for item in bpy.context.scene.objects:
        if item.type == 'CURVE' and item.get(CURVE_PROP_NAME) == obj.name:
            return item
    return None


def stored_frames_from_curve(curve_obj):
    if not curve_obj:
        return []
    stored = curve_obj.get(CURVE_FRAME_PROP, "")
    try:
        return sorted({int(x) for x in stored.split(',') if x.strip()})
    except Exception:
        return []


def frames_from_curve_or_object(curve_obj, target_obj):
    current = get_location_key_frames(target_obj)
    if len(current) >= 2:
        return current

    stored = stored_frames_from_curve(curve_obj)
    if len(stored) >= 2:
        return stored

    return current


def capture_original_location_path(obj):
    frames = get_location_key_frames(obj)
    data = []
    for frame in frames:
        loc = evaluate_location_at_frame(obj, frame)
        data.append({
            "frame": int(frame),
            "location": [float(loc.x), float(loc.y), float(loc.z)],
        })
    return data


def store_original_location_path(owner, data):
    try:
        owner[ORIGINAL_PATH_PROP] = json.dumps(data)
    except Exception:
        pass


def load_original_location_path(owner):
    if owner is None or ORIGINAL_PATH_PROP not in owner:
        return []
    try:
        raw = owner.get(ORIGINAL_PATH_PROP, "[]")
        data = json.loads(raw)
        result = []
        for item in data:
            frame = int(item.get("frame"))
            loc = item.get("location")
            if isinstance(loc, list) and len(loc) == 3:
                result.append((frame, Vector((float(loc[0]), float(loc[1]), float(loc[2])))))
        return sorted(result, key=lambda x: x[0])
    except Exception:
        return []


def restore_original_location_path(context, obj):
    saved = load_original_location_path(obj)
    if len(saved) < 2:
        return []

    scene = context.scene
    original_scene_frame = scene.frame_current
    delete_location_fcurves(obj)

    for frame, loc in saved:
        scene.frame_set(frame)
        obj.location = loc
        obj.keyframe_insert(data_path="location", frame=frame)

    set_key_interpolation(obj, scene.mpe_key_interpolation)
    first_frame = min(frame for frame, _loc in saved)
    last_frame = max(frame for frame, _loc in saved)
    calculate_motion_path(context, obj, first_frame, last_frame)

    if first_frame <= original_scene_frame <= last_frame:
        scene.frame_set(original_scene_frame)
    else:
        scene.frame_set(first_frame)
    context.view_layer.update()
    return [frame for frame, _loc in saved]


def get_or_create_curve_material(color):
    mat = bpy.data.materials.get(MATERIAL_NAME)
    if mat is None:
        mat = bpy.data.materials.new(MATERIAL_NAME)
    mat.diffuse_color = color
    try:
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            if "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = color
            if "Alpha" in bsdf.inputs:
                bsdf.inputs["Alpha"].default_value = color[3]
    except Exception:
        pass
    return mat


def apply_curve_color(curve_obj, color):
    curve_obj.color = color
    mat = get_or_create_curve_material(color)
    curve_obj.data.materials.clear()
    curve_obj.data.materials.append(mat)


def update_curve_color(self, context):
    try:
        for obj in context.scene.objects:
            if obj.type == 'CURVE' and CURVE_PROP_NAME in obj:
                apply_curve_color(obj, context.scene.mpe_curve_color)
    except Exception:
        pass


def object_has_motion_path(obj):
    try:
        return bool(obj and obj.motion_path)
    except Exception:
        return False


def reset_curve_to_target_keyframes(curve_obj, target_obj, scene):
    if curve_obj is None or target_obj is None:
        return []

    frames = get_location_key_frames(target_obj)
    if len(frames) < 2:
        return []

    curve_data = curve_obj.data
    curve_data.splines.clear()
    curve_data.dimensions = '3D'
    curve_data.resolution_u = 32
    curve_data.bevel_depth = scene.mpe_curve_thickness
    curve_data.bevel_resolution = 4
    curve_data.twist_smooth = 8

    control_frames = get_editable_control_frames(frames, scene.mpe_control_handle_count)
    spl = curve_data.splines.new('BEZIER')
    spl.bezier_points.add(len(control_frames) - 1)

    inv = curve_obj.matrix_world.inverted()
    for bp, frame in zip(spl.bezier_points, control_frames):
        loc = evaluate_location_at_frame(target_obj, frame)
        world_pos = world_from_location_value(target_obj, loc)
        bp.co = inv @ world_pos
        bp.handle_left_type = scene.mpe_handle_mode
        bp.handle_right_type = scene.mpe_handle_mode

    curve_obj[CURVE_PROP_NAME] = target_obj.name
    curve_obj[CURVE_FRAME_PROP] = ",".join(str(f) for f in frames)
    if ORIGINAL_PATH_PROP not in curve_obj:
        original_data = capture_original_location_path(target_obj)
        store_original_location_path(curve_obj, original_data)
    curve_obj.show_in_front = True
    curve_obj.display_type = 'TEXTURED'
    apply_curve_color(curve_obj, scene.mpe_curve_color)
    return frames


def sample_bezier_curve_world(curve_obj, samples_per_segment=64):
    points = []
    mw = curve_obj.matrix_world.copy()

    for spl in curve_obj.data.splines:
        if spl.type != 'BEZIER' or len(spl.bezier_points) < 2:
            continue

        bps = spl.bezier_points
        seg_count = len(bps) if spl.use_cyclic_u else len(bps) - 1

        for i in range(seg_count):
            p0 = bps[i]
            p1 = bps[(i + 1) % len(bps)]
            P0 = p0.co.copy()
            P1 = p0.handle_right.copy()
            P2 = p1.handle_left.copy()
            P3 = p1.co.copy()

            for s in range(samples_per_segment):
                t = s / float(samples_per_segment)
                u = 1.0 - t
                p = (
                    (u ** 3) * P0 +
                    3.0 * (u ** 2) * t * P1 +
                    3.0 * u * (t ** 2) * P2 +
                    (t ** 3) * P3
                )
                points.append(mw @ p)

        if not spl.use_cyclic_u:
            points.append(mw @ bps[-1].co.copy())

    return points


def cumulative_lengths(points):
    lengths = [0.0]
    total = 0.0
    for a, b in zip(points, points[1:]):
        total += (b - a).length
        lengths.append(total)
    return lengths, total


def point_at_distance(points, lengths, distance):
    if distance <= 0.0:
        return points[0].copy()
    if distance >= lengths[-1]:
        return points[-1].copy()

    for i in range(1, len(points)):
        if lengths[i] >= distance:
            previous = lengths[i - 1]
            seg_len = lengths[i] - previous
            if seg_len <= 0.000001:
                return points[i].copy()
            t = (distance - previous) / seg_len
            return points[i - 1].lerp(points[i], t)

    return points[-1].copy()


def delete_location_fcurves(obj):
    if not obj.animation_data or not obj.animation_data.action:
        return
    for fcurve_collection in get_fcurve_collections(obj, ensure=False):
        for fc in list(fcurve_collection):
            if fc.data_path == "location" and fc.array_index in {0, 1, 2}:
                try:
                    fcurve_collection.remove(fc)
                except Exception:
                    pass


def capture_location_key_settings(obj):
    settings = {}
    for fc in get_location_fcurves(obj):
        axis_settings = {}
        for kp in fc.keyframe_points:
            frame = int(round(kp.co.x))
            axis_settings[frame] = {
                "interpolation": getattr(kp, "interpolation", 'BEZIER'),
                "easing": getattr(kp, "easing", 'AUTO'),
                "handle_left_type": getattr(kp, "handle_left_type", 'AUTO'),
                "handle_right_type": getattr(kp, "handle_right_type", 'AUTO'),
                "amplitude": getattr(kp, "amplitude", 0.0),
                "back": getattr(kp, "back", 0.0),
                "period": getattr(kp, "period", 0.0),
            }
        settings[fc.array_index] = axis_settings
    return settings


def apply_location_key_settings(obj, settings, fallback_interpolation='LINEAR'):
    for fc in get_location_fcurves(obj):
        axis_settings = settings.get(fc.array_index, {}) if settings else {}
        for kp in fc.keyframe_points:
            frame = int(round(kp.co.x))
            data = axis_settings.get(frame)
            if data:
                try:
                    kp.interpolation = data.get("interpolation", fallback_interpolation)
                except Exception:
                    pass
                for attr in ("easing", "handle_left_type", "handle_right_type", "amplitude", "back", "period"):
                    if attr in data:
                        try:
                            setattr(kp, attr, data[attr])
                        except Exception:
                            pass
            else:
                try:
                    kp.interpolation = fallback_interpolation
                except Exception:
                    pass
        fc.update()


def build_original_motion_progress_ratios(obj, bake_frames):
    if not bake_frames:
        return {}

    frames = sorted({int(f) for f in bake_frames})
    original_positions = [evaluate_location_at_frame(obj, frame) for frame in frames]

    distances = [0.0]
    total = 0.0
    for prev, current in zip(original_positions, original_positions[1:]):
        total += (current - prev).length
        distances.append(total)

    if total <= 0.000001:
        first = frames[0]
        last = frames[-1]
        span = max(1.0, float(last - first))
        return {frame: (float(frame) - first) / span for frame in frames}

    return {frame: distance / total for frame, distance in zip(frames, distances)}


def set_key_interpolation(obj, interpolation):
    for fc in get_location_fcurves(obj):
        for kp in fc.keyframe_points:
            kp.interpolation = interpolation
        fc.update()


def find_view3d_override(context):
    window = context.window
    screen = context.screen
    if not window or not screen:
        return None

    for area in screen.areas:
        if area.type == 'VIEW_3D':
            region = None
            space = None
            for r in area.regions:
                if r.type == 'WINDOW':
                    region = r
                    break
            for s in area.spaces:
                if s.type == 'VIEW_3D':
                    space = s
                    break
            if region and space:
                return {
                    'window': window,
                    'screen': screen,
                    'area': area,
                    'region': region,
                    'space_data': space,
                    'scene': context.scene,
                    'view_layer': context.view_layer,
                }
    return None


def clear_motion_path(context, obj):
    ensure_object_mode()
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj
    context.view_layer.update()

    override = find_view3d_override(context)
    attempts = [lambda: bpy.ops.object.paths_clear()]

    if override:
        attempts.append(lambda: bpy.ops.object.paths_clear(override))

        def temp_override_clear():
            with context.temp_override(**override):
                return bpy.ops.object.paths_clear()

        attempts.append(temp_override_clear)

    for attempt in attempts:
        try:
            result = attempt()
            if result and 'FINISHED' in result:
                return True
        except Exception:
            continue

    return False


def calculate_motion_path(context, obj, first_frame, last_frame):
    scene = context.scene

    ensure_object_mode()
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    context.view_layer.objects.active = obj
    context.view_layer.update()

    if scene.mpe_set_scene_range_for_motion_path:
        scene.frame_start = first_frame
        scene.frame_end = last_frame

    clear_motion_path(context, obj)

    override = find_view3d_override(context)
    attempts = []
    attempts.append(lambda: bpy.ops.object.paths_calculate(start_frame=first_frame, end_frame=last_frame))
    attempts.append(lambda: bpy.ops.object.paths_calculate())

    if override:
        attempts.append(lambda: bpy.ops.object.paths_calculate(override, start_frame=first_frame, end_frame=last_frame))
        attempts.append(lambda: bpy.ops.object.paths_calculate(override))

        def temp_override_explicit():
            with context.temp_override(**override):
                return bpy.ops.object.paths_calculate(start_frame=first_frame, end_frame=last_frame)

        def temp_override_plain():
            with context.temp_override(**override):
                return bpy.ops.object.paths_calculate()

        attempts.append(temp_override_explicit)
        attempts.append(temp_override_plain)

    for attempt in attempts:
        try:
            result = attempt()
            if result and 'FINISHED' in result:
                return True
        except Exception:
            continue

    return False




def make_material(name, color):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def is_motion_path_handle(obj):
    return bool(obj and HANDLE_PROP_NAME in obj and HANDLE_INDEX_PROP in obj and HANDLE_ROLE_PROP in obj)


def is_motion_path_handle_line(obj):
    return bool(obj and HANDLE_LINE_PROP_NAME in obj and HANDLE_LINE_INDEX_PROP in obj and HANDLE_LINE_ROLE_PROP in obj)


def find_handles_for_curve(curve_obj):
    if curve_obj is None:
        return []
    return [obj for obj in bpy.context.scene.objects if is_motion_path_handle(obj) and obj.get(HANDLE_PROP_NAME) == curve_obj.name]


def find_handle_lines_for_curve(curve_obj):
    if curve_obj is None:
        return []
    return [obj for obj in bpy.context.scene.objects if is_motion_path_handle_line(obj) and obj.get(HANDLE_LINE_PROP_NAME) == curve_obj.name]


def remove_handles_for_curve(curve_obj):
    for obj in list(find_handles_for_curve(curve_obj)) + list(find_handle_lines_for_curve(curve_obj)):
        if obj.name in bpy.data.objects:
            bpy.data.objects.remove(obj, do_unlink=True)


def make_handle_object(context, curve_obj, index, role, world_pos, size):
    mesh = bpy.data.meshes.new(curve_obj.name + " " + role + " Mesh " + str(index))
    radius = size if role == 'Point' else size * 0.55
    verts = [(-radius, 0, 0), (radius, 0, 0), (0, -radius, 0), (0, radius, 0), (0, 0, -radius), (0, 0, radius)]
    faces = [(0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4), (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(curve_obj.name + " " + role + " " + str(index), mesh)
    obj.location = world_pos
    obj.show_in_front = True
    obj[HANDLE_PROP_NAME] = curve_obj.name
    obj[HANDLE_INDEX_PROP] = int(index)
    obj[HANDLE_ROLE_PROP] = role
    if role == 'Point':
        color = (1.0, 0.85, 0.05, 1.0)
    elif role == 'Left':
        color = (0.1, 0.45, 1.0, 1.0)
    else:
        color = (0.1, 1.0, 0.35, 1.0)
    obj.color = color
    obj.data.materials.append(make_material("BMP " + role + " Handle", color))
    context.collection.objects.link(obj)
    return obj


def make_handle_line(context, curve_obj, index, role, start, end, size):
    data = bpy.data.curves.new(curve_obj.name + " " + role + " Line " + str(index), type='CURVE')
    data.dimensions = '3D'
    data.resolution_u = 1
    data.bevel_depth = max(0.005, size * 0.08)
    data.bevel_resolution = 1
    spl = data.splines.new('POLY')
    spl.points.add(1)
    spl.points[0].co = (start.x, start.y, start.z, 1.0)
    spl.points[1].co = (end.x, end.y, end.z, 1.0)
    obj = bpy.data.objects.new(curve_obj.name + " " + role + " Line " + str(index), data)
    obj.show_in_front = True
    obj.hide_select = True
    obj[HANDLE_LINE_PROP_NAME] = curve_obj.name
    obj[HANDLE_LINE_INDEX_PROP] = int(index)
    obj[HANDLE_LINE_ROLE_PROP] = role
    color = (0.35, 0.65, 1.0, 1.0) if role == 'Left' else (0.35, 1.0, 0.55, 1.0)
    obj.color = color
    obj.data.materials.append(make_material("BMP " + role + " Handle Line", color))
    context.collection.objects.link(obj)
    return obj


def update_handle_lines(curve_obj):
    handles = find_handles_for_curve(curve_obj)
    lines = find_handle_lines_for_curve(curve_obj)
    handle_by_key = {}
    line_by_key = {}
    for obj in handles:
        handle_by_key[(int(obj.get(HANDLE_INDEX_PROP)), obj.get(HANDLE_ROLE_PROP))] = obj
    for obj in lines:
        line_by_key[(int(obj.get(HANDLE_LINE_INDEX_PROP)), obj.get(HANDLE_LINE_ROLE_PROP))] = obj
    for key, line in line_by_key.items():
        index, role = key
        point = handle_by_key.get((index, 'Point'))
        handle = handle_by_key.get((index, role))
        if not point or not handle:
            continue
        spl = line.data.splines[0]
        start = point.matrix_world.translation
        end = handle.matrix_world.translation
        spl.points[0].co = (start.x, start.y, start.z, 1.0)
        spl.points[1].co = (end.x, end.y, end.z, 1.0)
        line.data.update_tag()


def make_initial_free_handles(curve_obj):
    for spl in curve_obj.data.splines:
        if spl.type != 'BEZIER':
            continue
        count = len(spl.bezier_points)
        for index, bp in enumerate(spl.bezier_points):
            previous_bp = spl.bezier_points[index - 1] if index > 0 else None
            next_bp = spl.bezier_points[index + 1] if index < count - 1 else None
            if previous_bp and next_bp:
                direction = next_bp.co - previous_bp.co
                length = min((bp.co - previous_bp.co).length, (next_bp.co - bp.co).length) / 3.0
            elif next_bp:
                direction = next_bp.co - bp.co
                length = direction.length / 3.0
            elif previous_bp:
                direction = bp.co - previous_bp.co
                length = direction.length / 3.0
            else:
                direction = Vector((1.0, 0.0, 0.0))
                length = 1.0
            if direction.length <= 0.000001:
                direction = Vector((1.0, 0.0, 0.0))
            direction.normalize()
            bp.handle_left_type = 'FREE'
            bp.handle_right_type = 'FREE'
            bp.handle_left = bp.co - direction * length
            bp.handle_right = bp.co + direction * length


def create_object_mode_handles(context, curve_obj):
    remove_handles_for_curve(curve_obj)
    make_initial_free_handles(curve_obj)
    handles = []
    size = max(0.08, float(context.scene.mpe_curve_thickness) * 3.0)
    mw = curve_obj.matrix_world
    for spl in curve_obj.data.splines:
        if spl.type != 'BEZIER':
            continue
        for index, bp in enumerate(spl.bezier_points):
            point = make_handle_object(context, curve_obj, index, 'Point', mw @ bp.co, size)
            left = make_handle_object(context, curve_obj, index, 'Left', mw @ bp.handle_left, size)
            right = make_handle_object(context, curve_obj, index, 'Right', mw @ bp.handle_right, size)
            make_handle_line(context, curve_obj, index, 'Left', point.location, left.location, size)
            make_handle_line(context, curve_obj, index, 'Right', point.location, right.location, size)
            handles.extend([point, left, right])
    bpy.ops.object.select_all(action='DESELECT')
    for obj in handles:
        obj.select_set(True)
    if handles:
        context.view_layer.objects.active = handles[0]
    update_handle_lines(curve_obj)
    return handles


def sync_curve_from_object_mode_handles(curve_obj):
    if curve_obj is None or curve_obj.name not in bpy.data.objects:
        return False
    handles = find_handles_for_curve(curve_obj)
    if not handles:
        return False
    by_key = {}
    for obj in handles:
        by_key[(int(obj.get(HANDLE_INDEX_PROP)), obj.get(HANDLE_ROLE_PROP))] = obj
    inv = curve_obj.matrix_world.inverted()
    changed = False
    for spl in curve_obj.data.splines:
        if spl.type != 'BEZIER':
            continue
        for index, bp in enumerate(spl.bezier_points):
            point = by_key.get((index, 'Point'))
            left = by_key.get((index, 'Left'))
            right = by_key.get((index, 'Right'))
            if point:
                bp.co = inv @ point.matrix_world.translation
                changed = True
            if left:
                bp.handle_left = inv @ left.matrix_world.translation
                bp.handle_left_type = 'FREE'
                changed = True
            if right:
                bp.handle_right = inv @ right.matrix_world.translation
                bp.handle_right_type = 'FREE'
                changed = True
    if changed:
        curve_obj.data.update_tag()
        update_handle_lines(curve_obj)
    return changed


@persistent
def motion_path_handle_sync_handler(scene, depsgraph):
    global HANDLE_SYNC_BUSY
    if HANDLE_SYNC_BUSY:
        return
    curves = set()
    for update in depsgraph.updates:
        item = update.id
        if isinstance(item, bpy.types.Object) and is_motion_path_handle(item):
            curve_obj = bpy.data.objects.get(item.get(HANDLE_PROP_NAME))
            if curve_obj:
                curves.add(curve_obj)
                if getattr(scene, "mpe_auto_bake", False) and not AUTO_BAKE_BUSY:
                    queue_auto_bake_curve(curve_obj)
    if not curves:
        return
    HANDLE_SYNC_BUSY = True
    try:
        for curve_obj in curves:
            sync_curve_from_object_mode_handles(curve_obj)
    finally:
        HANDLE_SYNC_BUSY = False
AUTO_BAKE_BUSY = False
AUTO_BAKE_PENDING = set()
AUTO_BAKE_TIMER_ACTIVE = False
AUTO_BAKE_STATE = {}


def editable_curve_signature(curve_obj):
    if curve_obj is None or curve_obj.name not in bpy.data.objects:
        return None
    sync_curve_from_object_mode_handles(curve_obj)
    data = []
    for spl in curve_obj.data.splines:
        if spl.type != 'BEZIER':
            continue
        points = []
        for bp in spl.bezier_points:
            points.append((round(bp.co.x, 5), round(bp.co.y, 5), round(bp.co.z, 5), round(bp.handle_left.x, 5), round(bp.handle_left.y, 5), round(bp.handle_left.z, 5), round(bp.handle_right.x, 5), round(bp.handle_right.y, 5), round(bp.handle_right.z, 5)))
        data.append(tuple(points))
    return tuple(data)


def bake_editable_curve(context, curve_obj, target_obj, keep_editable):
    scene = context.scene
    if target_obj is None or curve_obj is None:
        return False, "Select the generated edit curve, or select the target object while its edit curve exists."
    frames = frames_from_curve_or_object(curve_obj, target_obj)
    if len(frames) < 2:
        return False, "Could not determine the current keyframe range."
    sync_curve_from_object_mode_handles(curve_obj)
    points = sample_bezier_curve_world(curve_obj, scene.mpe_curve_accuracy)
    if len(points) < 2:
        return False, "The edit curve has no usable Bezier segments."
    lengths, total_len = cumulative_lengths(points)
    if total_len <= 0.000001:
        return False, "The edit curve has no measurable length."
    first_frame = min(frames)
    last_frame = max(frames)
    step = max(1, int(scene.mpe_bake_every_n_frames))
    bake_frames = list(range(first_frame, last_frame + 1, step))
    if bake_frames[-1] != last_frame:
        bake_frames.append(last_frame)
    progress_by_frame = build_original_motion_progress_ratios(target_obj, bake_frames)
    baked = []
    for frame in bake_frames:
        ratio = progress_by_frame.get(frame, 0.0)
        world_pos = point_at_distance(points, lengths, total_len * ratio)
        baked.append((frame, location_value_from_world(target_obj, world_pos)))
    original_scene_frame = scene.frame_current
    original_key_settings = capture_location_key_settings(target_obj)
    original_selected = list(context.selected_objects)
    original_active = context.view_layer.objects.active
    delete_location_fcurves(target_obj)
    for frame, loc in baked:
        scene.frame_set(frame)
        target_obj.location = loc
        target_obj.keyframe_insert(data_path="location", frame=frame)
    apply_location_key_settings(target_obj, original_key_settings, scene.mpe_key_interpolation)
    original_path = load_original_location_path(curve_obj)
    if original_path:
        store_original_location_path(target_obj, [
            {"frame": frame, "location": [float(loc.x), float(loc.y), float(loc.z)]}
            for frame, loc in original_path
        ])
    if keep_editable:
        sync_curve_from_object_mode_handles(curve_obj)
        update_handle_lines(curve_obj)
    else:
        remove_handles_for_curve(curve_obj)
        bpy.data.objects.remove(curve_obj, do_unlink=True)
    bpy.ops.object.select_all(action='DESELECT')
    if keep_editable:
        for obj in original_selected:
            if obj and obj.name in bpy.data.objects:
                obj.select_set(True)
        if original_active and original_active.name in bpy.data.objects:
            context.view_layer.objects.active = original_active
    else:
        target_obj.select_set(True)
        context.view_layer.objects.active = target_obj
    context.view_layer.update()
    motion_path_ok = calculate_motion_path(context, target_obj, first_frame, last_frame) if not keep_editable else True
    if first_frame <= original_scene_frame <= last_frame:
        scene.frame_set(original_scene_frame)
    else:
        scene.frame_set(first_frame)
    context.view_layer.update()
    if not motion_path_ok:
        return True, "Baked new keys, but Blender did not allow automatic motion-path calculation in this context."
    return True, "Baked new keys to the edited curve."


def queue_auto_bake_curve(curve_obj):
    global AUTO_BAKE_TIMER_ACTIVE
    if curve_obj is None or curve_obj.name not in bpy.data.objects:
        return
    signature = editable_curve_signature(curve_obj)
    state = AUTO_BAKE_STATE.get(curve_obj.name, {})
    state["pending_signature"] = signature
    state["stable_count"] = 0
    AUTO_BAKE_STATE[curve_obj.name] = state
    AUTO_BAKE_PENDING.add(curve_obj.name)
    if not AUTO_BAKE_TIMER_ACTIVE:
        AUTO_BAKE_TIMER_ACTIVE = True
        bpy.app.timers.register(run_auto_bake_timer, first_interval=0.25)


def run_auto_bake_timer():
    global AUTO_BAKE_BUSY, AUTO_BAKE_TIMER_ACTIVE
    scene = bpy.context.scene
    if scene is None or not getattr(scene, "mpe_auto_bake", False):
        AUTO_BAKE_TIMER_ACTIVE = False
        return None
    if not AUTO_BAKE_PENDING:
        AUTO_BAKE_TIMER_ACTIVE = False
        return None
    ready = []
    for name in list(AUTO_BAKE_PENDING):
        curve_obj = bpy.data.objects.get(name)
        if curve_obj is None or curve_obj.type != 'CURVE' or CURVE_PROP_NAME not in curve_obj:
            AUTO_BAKE_PENDING.discard(name)
            AUTO_BAKE_STATE.pop(name, None)
            continue
        signature = editable_curve_signature(curve_obj)
        state = AUTO_BAKE_STATE.get(name, {})
        if signature == state.get("pending_signature"):
            state["stable_count"] = state.get("stable_count", 0) + 1
        else:
            state["pending_signature"] = signature
            state["stable_count"] = 0
        AUTO_BAKE_STATE[name] = state
        if state.get("stable_count", 0) >= 2 and signature != state.get("baked_signature"):
            ready.append(name)
    if not ready:
        return 0.25
    AUTO_BAKE_BUSY = True
    try:
        for name in ready:
            curve_obj = bpy.data.objects.get(name)
            if curve_obj is None or curve_obj.type != 'CURVE' or CURVE_PROP_NAME not in curve_obj:
                AUTO_BAKE_PENDING.discard(name)
                AUTO_BAKE_STATE.pop(name, None)
                continue
            target_obj = bpy.data.objects.get(curve_obj.get(CURVE_PROP_NAME))
            if target_obj is None:
                AUTO_BAKE_PENDING.discard(name)
                AUTO_BAKE_STATE.pop(name, None)
                continue
            ok, message = bake_editable_curve(bpy.context, curve_obj, target_obj, True)
            state = AUTO_BAKE_STATE.get(name, {})
            if ok:
                state["baked_signature"] = editable_curve_signature(curve_obj)
                state["pending_signature"] = state["baked_signature"]
                state["stable_count"] = 0
                AUTO_BAKE_PENDING.discard(name)
            AUTO_BAKE_STATE[name] = state
    finally:
        AUTO_BAKE_BUSY = False
    if AUTO_BAKE_PENDING:
        return 0.25
    AUTO_BAKE_TIMER_ACTIVE = False
    return None


def update_auto_bake(self, context):
    if getattr(context.scene, "mpe_auto_bake", False):
        curve_obj = context.object if context.object and context.object.type == 'CURVE' and CURVE_PROP_NAME in context.object else None
        if curve_obj is None:
            target = get_active_anim_object(context)
            curve_obj = find_existing_curve_for(target)
        if curve_obj:
            queue_auto_bake_curve(curve_obj)

class MPE_OT_create_curve(bpy.types.Operator):
    bl_idname = "mpe.create_edit_curve"
    bl_label = "Create Editable Motion Path"
    bl_description = "Create a thick colored Bezier curve through the object's location keyframes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ensure_object_mode()
        scene = context.scene
        obj = get_active_anim_object(context)

        if obj is None or obj.type == 'CURVE':
            self.report({'ERROR'}, "No selected object or armature yet.")
            return {'CANCELLED'}

        frames = get_location_key_frames(obj)
        if len(frames) < 2:
            self.report({'ERROR'}, "The selected object or armature needs at least two location keyframes.")
            return {'CANCELLED'}

        existing = find_existing_curve_for(obj)
        if existing:
            remove_handles_for_curve(existing)
            bpy.data.objects.remove(existing, do_unlink=True)

        curve_data = bpy.data.curves.new(obj.name + " Motion Path Edit Curve", type='CURVE')
        curve_data.dimensions = '3D'
        curve_data.resolution_u = 32
        curve_data.bevel_depth = scene.mpe_curve_thickness
        curve_data.bevel_resolution = 4
        curve_data.twist_smooth = 8

        control_frames = get_editable_control_frames(frames, scene.mpe_control_handle_count)
        spl = curve_data.splines.new('BEZIER')
        spl.bezier_points.add(len(control_frames) - 1)

        for bp, frame in zip(spl.bezier_points, control_frames):
            loc = evaluate_location_at_frame(obj, frame)
            bp.co = world_from_location_value(obj, loc)
            bp.handle_left_type = scene.mpe_handle_mode
            bp.handle_right_type = scene.mpe_handle_mode

        curve_obj = bpy.data.objects.new(curve_data.name, curve_data)
        context.collection.objects.link(curve_obj)
        curve_obj[CURVE_PROP_NAME] = obj.name
        curve_obj[CURVE_FRAME_PROP] = ",".join(str(f) for f in frames)
        store_original_location_path(curve_obj, capture_original_location_path(obj))
        curve_obj.show_in_front = True
        curve_obj.display_type = 'TEXTURED'
        apply_curve_color(curve_obj, scene.mpe_curve_color)
        clear_motion_path(context, obj)
        create_object_mode_handles(context, curve_obj)
        obj.select_set(False)

        self.report({'INFO'}, "Editable colored curve created. Move the object mode handles, then press Bake Keyframes To Curve.")
        return {'FINISHED'}


class MPE_OT_apply_curve_color(bpy.types.Operator):
    bl_idname = "mpe.apply_curve_color"
    bl_label = "Apply Color To Edit Curve"
    bl_description = "Apply the selected UI color to the existing helper Bezier curve"
    bl_options = {'UNDO'}

    def execute(self, context):
        obj = context.object
        target = get_active_anim_object(context)
        curve_obj = obj if obj and obj.type == 'CURVE' and CURVE_PROP_NAME in obj else find_existing_curve_for(target)

        if curve_obj is None:
            self.report({'ERROR'}, "No edit curve found to color.")
            return {'CANCELLED'}

        apply_curve_color(curve_obj, context.scene.mpe_curve_color)
        context.view_layer.update()
        self.report({'INFO'}, "Edit curve color updated.")
        return {'FINISHED'}


class MPE_OT_bake_keys_to_curve(bpy.types.Operator):
    bl_idname = "mpe.bake_keys_to_curve"
    bl_label = "Bake Keyframes To Curve"
    bl_description = "Bake fresh location keyframes to the edited curve using the target object's current keyframe range"
    bl_options = {'UNDO'}

    def execute(self, context):
        ensure_object_mode()
        scene = context.scene
        curve_obj = context.object if context.object and context.object.type == 'CURVE' else None
        if curve_obj and CURVE_PROP_NAME in curve_obj:
            target_obj = bpy.data.objects.get(curve_obj.get(CURVE_PROP_NAME))
        else:
            target_obj = get_active_anim_object(context)
            curve_obj = find_existing_curve_for(target_obj)
        keep_editable = bool(getattr(scene, "mpe_auto_bake", False))
        ok, message = bake_editable_curve(context, curve_obj, target_obj, keep_editable)
        if not ok:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}
        if keep_editable:
            self.report({'INFO'}, "Baked new keys and kept the editable curve.")
        elif "did not allow" in message:
            self.report({'WARNING'}, message)
        else:
            self.report({'INFO'}, "Baked new keys, deleted the curve, and recalculated motion paths.")
        return {'FINISHED'}

class MPE_OT_remove_editable_motion_paths(bpy.types.Operator):
    bl_idname = "mpe.remove_editable_motion_paths"
    bl_label = "Remove Editable Motion Paths"
    bl_description = "Delete generated editable helper curves without changing the target object's keyframes"
    bl_options = {'UNDO'}

    remove_all: bpy.props.BoolProperty(
        name="Remove All",
        default=False,
        description="Remove all generated editable motion path curves in the scene instead of only the selected target's curve",
    )

    def execute(self, context):
        ensure_object_mode()
        selected = context.object
        target = get_active_anim_object(context)
        curves_to_remove = []

        if self.remove_all:
            curves_to_remove = [obj for obj in context.scene.objects if obj.type == 'CURVE' and CURVE_PROP_NAME in obj]
        else:
            if selected and selected.type == 'CURVE' and CURVE_PROP_NAME in selected:
                curves_to_remove = [selected]
            elif target:
                found = find_existing_curve_for(target)
                if found:
                    curves_to_remove = [found]

        if not curves_to_remove:
            self.report({'ERROR'}, "No editable motion path curve found to remove.")
            return {'CANCELLED'}

        target_to_select = target if target and target.name in bpy.data.objects else None
        if target_to_select is None and curves_to_remove:
            target_to_select = bpy.data.objects.get(curves_to_remove[0].get(CURVE_PROP_NAME))

        removed_count = 0
        for curve_obj in curves_to_remove:
            if curve_obj and curve_obj.name in bpy.data.objects:
                remove_handles_for_curve(curve_obj)
                bpy.data.objects.remove(curve_obj, do_unlink=True)
                removed_count += 1

        bpy.ops.object.select_all(action='DESELECT')
        if target_to_select and target_to_select.name in bpy.data.objects:
            target_to_select.select_set(True)
            context.view_layer.objects.active = target_to_select
        context.view_layer.update()

        self.report({'INFO'}, f"Removed {removed_count} editable motion path curve(s).")
        return {'FINISHED'}


class MPE_OT_reset_motion_path(bpy.types.Operator):
    bl_idname = "mpe.reset_motion_path"
    bl_label = "Reset Motion Path"
    bl_description = "Reset the editable helper curve, or restore baked keyframes to the saved original path after baking"
    bl_options = {'UNDO'}

    def execute(self, context):
        ensure_object_mode()
        scene = context.scene
        selected = context.object

        if selected and selected.type == 'CURVE' and CURVE_PROP_NAME in selected:
            curve_obj = selected
            target_obj = bpy.data.objects.get(curve_obj.get(CURVE_PROP_NAME))
        else:
            target_obj = get_active_anim_object(context)
            curve_obj = find_existing_curve_for(target_obj)

        if target_obj is not None and curve_obj is not None:
            frames = reset_curve_to_target_keyframes(curve_obj, target_obj, scene)
            if len(frames) < 2:
                self.report({'ERROR'}, "Target object needs at least two current location keyframes to reset the edit curve.")
                return {'CANCELLED'}
            bpy.ops.object.select_all(action='DESELECT')
            curve_obj.select_set(True)
            context.view_layer.objects.active = curve_obj
            context.view_layer.update()
            self.report({'INFO'}, f"Editable motion path reset to current keys over frames {min(frames)}-{max(frames)}.")
            return {'FINISHED'}

        if target_obj is not None:
            frames = restore_original_location_path(context, target_obj)
            if len(frames) >= 2:
                bpy.ops.object.select_all(action='DESELECT')
                target_obj.select_set(True)
                context.view_layer.objects.active = target_obj
                context.view_layer.update()
                self.report({'INFO'}, f"Baked motion path reset to saved original keys over frames {min(frames)}-{max(frames)}.")
                return {'FINISHED'}

        self.report({'ERROR'}, "No editable curve or saved baked reset data found. Create an editable motion path first, then bake it.")
        return {'CANCELLED'}


class MPE_OT_calculate_motion_path(bpy.types.Operator):
    bl_idname = "mpe.calculate_motion_path"
    bl_label = "Calculate Motion Path"
    bl_description = "Calculate or recalculate the selected object's or armature's motion path over its current location-keyframe range"
    bl_options = {'UNDO'}

    def execute(self, context):
        ensure_object_mode()
        obj = get_active_anim_object(context)

        if obj is None or obj.type == 'CURVE':
            self.report({'ERROR'}, "No selected object or armature yet.")
            return {'CANCELLED'}

        frames = get_location_key_frames(obj)
        if len(frames) < 2:
            self.report({'ERROR'}, "Selected object or armature needs at least two location keyframes.")
            return {'CANCELLED'}

        first_frame = min(frames)
        last_frame = max(frames)
        was_recalc = object_has_motion_path(obj)
        ok = calculate_motion_path(context, obj, first_frame, last_frame)
        if ok:
            verb = "recalculated" if was_recalc else "calculated"
            self.report({'INFO'}, f"Motion path {verb} over frames {first_frame}-{last_frame}.")
            return {'FINISHED'}

        self.report({'WARNING'}, "Blender did not allow automatic motion-path calculation in this context.")
        return {'CANCELLED'}

class MPE_OT_recalculate_motion_path(bpy.types.Operator):
    bl_idname = "mpe.recalculate_motion_path"
    bl_label = "Recalculate Motion Path"
    bl_description = "Recalculate the selected object's or armature's motion path over its location-keyframe range"
    bl_options = {'UNDO'}

    def execute(self, context):
        ensure_object_mode()
        obj = get_active_anim_object(context)
        if obj is None or obj.type == 'CURVE':
            self.report({'ERROR'}, "No selected object or armature yet.")
            return {'CANCELLED'}

        frames = get_location_key_frames(obj)
        if len(frames) < 2:
            self.report({'ERROR'}, "Selected object or armature needs at least two location keyframes.")
            return {'CANCELLED'}

        ok = calculate_motion_path(context, obj, min(frames), max(frames))
        if ok:
            self.report({'INFO'}, "Motion path recalculated.")
            return {'FINISHED'}
        self.report({'WARNING'}, "Blender did not allow automatic motion-path calculation in this context.")
        return {'CANCELLED'}


class MPE_OT_clear_motion_path(bpy.types.Operator):
    bl_idname = "mpe.clear_motion_path"
    bl_label = "Clear Motion Path"
    bl_description = "Clear the selected object's or armature's calculated motion path"
    bl_options = {'UNDO'}

    def execute(self, context):
        ensure_object_mode()
        obj = get_active_anim_object(context)
        if obj is None or obj.type == 'CURVE':
            self.report({'ERROR'}, "No selected object or armature yet.")
            return {'CANCELLED'}

        ok = clear_motion_path(context, obj)
        if ok:
            self.report({'INFO'}, "Motion path cleared.")
            return {'FINISHED'}
        self.report({'WARNING'}, "Blender did not allow clearing motion paths in this context.")
        return {'CANCELLED'}


class MPE_PT_panel(bpy.types.Panel):
    bl_label = "Motion Path"
    bl_idname = "MPE_PT_motion_path_curve"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Animation"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        selected = context.object
        target = get_active_anim_object(context)

        if selected is None:
            layout.label(text="No selected object or armature yet", icon='INFO')
        elif target:
            layout.label(text="Target: " + target.name)
        else:
            layout.label(text="No selected object or armature yet", icon='INFO')

        layout.separator()
        layout.label(text="Create Curve")
        layout.prop(scene, "mpe_handle_mode")
        layout.prop(scene, "mpe_control_handle_count")
        row = layout.row(align=True)
        row.operator(MPE_OT_reset_motion_path.bl_idname, icon='FILE_REFRESH')
        row.operator(MPE_OT_remove_editable_motion_paths.bl_idname, icon='TRASH')
        layout.prop(scene, "mpe_curve_thickness")
        layout.prop(scene, "mpe_curve_color")
        layout.operator(MPE_OT_create_curve.bl_idname, icon='CURVE_BEZCURVE')

        layout.separator()
        layout.label(text="Bake")
        layout.prop(scene, "mpe_auto_bake")
        layout.prop(scene, "mpe_bake_every_n_frames")
        layout.label(text="Timing: Preserve Original Ease", icon='TIME')
        layout.prop(scene, "mpe_curve_accuracy")
        layout.prop(scene, "mpe_key_interpolation")
        layout.prop(scene, "mpe_set_scene_range_for_motion_path")
        layout.operator(MPE_OT_bake_keys_to_curve.bl_idname, icon='KEY_HLT')

        layout.separator()
        layout.label(text="Motion Path")
        row = layout.row(align=True)
        motion_label = "Recalculate Motion Path" if object_has_motion_path(target) else "Calculate Motion Path"
        row.operator(MPE_OT_calculate_motion_path.bl_idname, text=motion_label, icon='IPO_BEZIER')
        row.operator(MPE_OT_clear_motion_path.bl_idname, icon='X')

        layout.separator()
        box = layout.box()
        box.label(text="How to curve a motion path:")
        box.label(text="1. Create editable motion path")
        box.label(text="2. Move the object mode handles")
        box.label(text="3. Reset works before and after baking")
        box.label(text="4. Retiming is supported: move target keyframes")
        box.label(text="5. Bake Keyframes To Curve")
        box.label(text="Remove deletes helper curves only.")

classes = (
    MPE_OT_create_curve,
    MPE_OT_apply_curve_color,
    MPE_OT_bake_keys_to_curve,
    MPE_OT_remove_editable_motion_paths,
    MPE_OT_reset_motion_path,
    MPE_OT_calculate_motion_path,
    MPE_OT_recalculate_motion_path,
    MPE_OT_clear_motion_path,
    MPE_PT_panel,
)


def register():
    bpy.types.Scene.mpe_curve_thickness = bpy.props.FloatProperty(
        name="Curve Thickness",
        default=0.15,
        min=0.001,
        max=10.0,
        description="Thickness of the generated helper curve",
    )
    bpy.types.Scene.mpe_curve_color = bpy.props.FloatVectorProperty(
        name="Curve Color",
        subtype='COLOR',
        size=4,
        min=0.0,
        max=1.0,
        default=(1.0, 0.25, 0.05, 1.0),
        description="Color of the generated helper Bezier curve",
        update=update_curve_color,
    )
    bpy.types.Scene.mpe_handle_mode = bpy.props.EnumProperty(
        name="Handle Mode",
        items=[
            ('AUTO', "Auto", "Smooth automatic handles"),
            ('VECTOR', "Vector", "Straight segments"),
            ('FREE', "Free", "Free handles"),
        ],
        default='AUTO',
    )
    bpy.types.Scene.mpe_auto_bake = bpy.props.BoolProperty(
        name="Auto Bake",
        default=False,
        description="Bake keyframes after the editable curve handles are changed without deleting the curve",
        update=update_auto_bake,
    )
    bpy.types.Scene.mpe_control_handle_count = bpy.props.IntProperty(
        name="Control Handles",
        default=4,
        min=2,
        max=100,
        description="Number of editable object-mode control points created for the motion path",
    )
    bpy.types.Scene.mpe_bake_every_n_frames = bpy.props.IntProperty(
        name="Bake Every N Frames",
        default=1,
        min=1,
        max=100,
        description="Bake one new key every N frames while preserving the original motion timing/ease",
    )
    bpy.types.Scene.mpe_curve_accuracy = bpy.props.IntProperty(
        name="Curve Accuracy",
        default=96,
        min=4,
        max=512,
        description="Sampling accuracy for following the edited curve",
    )
    bpy.types.Scene.mpe_key_interpolation = bpy.props.EnumProperty(
        name="New Key Interpolation",
        items=[
            ('BEZIER', "Bezier", "Smooth interpolation"),
            ('LINEAR', "Linear", "Linear interpolation"),
            ('CONSTANT', "Constant", "Stepped interpolation"),
        ],
        default='LINEAR',
    )
    bpy.types.Scene.mpe_set_scene_range_for_motion_path = bpy.props.BoolProperty(
        name="Use Baked Range For Motion Path",
        default=True,
        description="Set the scene frame range to the baked keyframe range before calculating motion paths",
    )

    for cls in classes:
        bpy.utils.register_class(cls)
    if motion_path_handle_sync_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(motion_path_handle_sync_handler)


def unregister():
    if motion_path_handle_sync_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(motion_path_handle_sync_handler)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.mpe_curve_thickness
    del bpy.types.Scene.mpe_curve_color
    del bpy.types.Scene.mpe_handle_mode
    del bpy.types.Scene.mpe_auto_bake
    del bpy.types.Scene.mpe_control_handle_count
    del bpy.types.Scene.mpe_bake_every_n_frames
    del bpy.types.Scene.mpe_curve_accuracy
    del bpy.types.Scene.mpe_key_interpolation
    del bpy.types.Scene.mpe_set_scene_range_for_motion_path


if __name__ == "__main__":
    register()
