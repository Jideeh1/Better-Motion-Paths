bl_info = {
    "name": "Better Motion Path",
    "author": "Jideeh",
    "version": (1, 4, 0),
    "blender": (3, 3, 0),
    "location": "View3D > Sidebar > Animation > Motion Path",
    "description": "Blender 3.3+ add-on: edit an object's location motion path as a thick colored Bezier curve, bake fresh keyframes, and manage motion paths.",
    "category": "Animation",
}

import bpy
from mathutils import Vector

CURVE_PROP_NAME = "_motion_path_edit_curve_for"
CURVE_FRAME_PROP = "_motion_path_edit_curve_frames"
MATERIAL_NAME = "MPE Helper Curve Material"


def ensure_object_mode():
    """Commit edit-mode curve edits before reading spline data."""
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


def get_location_fcurves(obj):
    if not obj or not obj.animation_data or not obj.animation_data.action:
        return []
    return [
        fc for fc in obj.animation_data.action.fcurves
        if fc.data_path == "location" and fc.array_index in {0, 1, 2}
    ]


def get_location_key_frames(obj):
    return sorted({
        int(round(kp.co.x))
        for fc in get_location_fcurves(obj)
        for kp in fc.keyframe_points
    })


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


def frames_from_curve_or_object(curve_obj, target_obj):
    if curve_obj:
        stored = curve_obj.get(CURVE_FRAME_PROP, "")
        try:
            frames = sorted({int(x) for x in stored.split(',') if x.strip()})
            if len(frames) >= 2:
                return frames
        except Exception:
            pass
    return get_location_key_frames(target_obj)


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


def sample_bezier_curve_world(curve_obj, samples_per_segment=64):
    """Sample edited Bezier splines in world space."""
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
    action = obj.animation_data.action
    for fc in list(action.fcurves):
        if fc.data_path == "location" and fc.array_index in {0, 1, 2}:
            action.fcurves.remove(fc)


def set_key_interpolation(obj, interpolation):
    for fc in get_location_fcurves(obj):
        for kp in fc.keyframe_points:
            kp.interpolation = interpolation
        fc.update()


def find_view3d_override(context):
    """Return a 3D View context override when possible, useful for motion path operators in 3.3+."""
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
    """Clear selected object's motion path with context fallbacks for Blender 3.3+."""
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
    """Automatically recalculate object motion paths after baking.

    Blender's motion-path operator API has changed a little across versions, so this
    function tries several compatible calls. If one works, it returns True. If all
    fail, the baked keyframes are still valid and the user gets a warning.
    """
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
            bpy.data.objects.remove(existing, do_unlink=True)

        curve_data = bpy.data.curves.new(obj.name + " Motion Path Edit Curve", type='CURVE')
        curve_data.dimensions = '3D'
        curve_data.resolution_u = 32
        curve_data.bevel_depth = scene.mpe_curve_thickness
        curve_data.bevel_resolution = 4
        curve_data.twist_smooth = 8

        spl = curve_data.splines.new('BEZIER')
        spl.bezier_points.add(len(frames) - 1)

        for bp, frame in zip(spl.bezier_points, frames):
            loc = evaluate_location_at_frame(obj, frame)
            bp.co = world_from_location_value(obj, loc)
            bp.handle_left_type = scene.mpe_handle_mode
            bp.handle_right_type = scene.mpe_handle_mode

        curve_obj = bpy.data.objects.new(curve_data.name, curve_data)
        context.collection.objects.link(curve_obj)
        curve_obj[CURVE_PROP_NAME] = obj.name
        curve_obj[CURVE_FRAME_PROP] = ",".join(str(f) for f in frames)
        curve_obj.show_in_front = True
        curve_obj.display_type = 'TEXTURED'
        apply_curve_color(curve_obj, scene.mpe_curve_color)

        obj.select_set(False)
        curve_obj.select_set(True)
        context.view_layer.objects.active = curve_obj

        self.report({'INFO'}, "Editable colored curve created. Edit it, then press Bake Keyframes To Curve.")
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
    bl_description = "Bake fresh location keyframes to the edited curve, delete old location keys, delete the curve, and auto-calculate motion paths"
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

        if target_obj is None or curve_obj is None:
            self.report({'ERROR'}, "Select the generated edit curve, or select the target object while its edit curve exists.")
            return {'CANCELLED'}

        frames = frames_from_curve_or_object(curve_obj, target_obj)
        if len(frames) < 2:
            self.report({'ERROR'}, "Could not determine the original keyframe range.")
            return {'CANCELLED'}

        points = sample_bezier_curve_world(curve_obj, scene.mpe_curve_accuracy)
        if len(points) < 2:
            self.report({'ERROR'}, "The edit curve has no usable Bezier segments.")
            return {'CANCELLED'}

        lengths, total_len = cumulative_lengths(points)
        if total_len <= 0.000001:
            self.report({'ERROR'}, "The edit curve has no measurable length.")
            return {'CANCELLED'}

        first_frame = min(frames)
        last_frame = max(frames)
        frame_span = max(1.0, float(last_frame - first_frame))

        step = max(1, int(scene.mpe_bake_every_n_frames))
        bake_frames = list(range(first_frame, last_frame + 1, step))
        if bake_frames[-1] != last_frame:
            bake_frames.append(last_frame)

        baked = []
        for frame in bake_frames:
            ratio = (float(frame) - first_frame) / frame_span
            world_pos = point_at_distance(points, lengths, total_len * ratio)
            baked.append((frame, location_value_from_world(target_obj, world_pos)))

        original_scene_frame = scene.frame_current

        delete_location_fcurves(target_obj)
        for frame, loc in baked:
            scene.frame_set(frame)
            target_obj.location = loc
            target_obj.keyframe_insert(data_path="location", frame=frame)

        set_key_interpolation(target_obj, scene.mpe_key_interpolation)

        bpy.data.objects.remove(curve_obj, do_unlink=True)

        bpy.ops.object.select_all(action='DESELECT')
        target_obj.select_set(True)
        context.view_layer.objects.active = target_obj
        context.view_layer.update()

        motion_path_ok = calculate_motion_path(context, target_obj, first_frame, last_frame)

        if first_frame <= original_scene_frame <= last_frame:
            scene.frame_set(original_scene_frame)
        else:
            scene.frame_set(first_frame)
        context.view_layer.update()

        if motion_path_ok:
            self.report({'INFO'}, "Baked new keys, deleted the curve, and recalculated motion paths.")
        else:
            self.report({'WARNING'}, "Baked new keys and deleted the curve, but Blender did not allow automatic motion-path calculation in this context.")

        return {'FINISHED'}


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
        layout.prop(scene, "mpe_curve_thickness")
        layout.prop(scene, "mpe_curve_color")
        layout.operator(MPE_OT_apply_curve_color.bl_idname, icon='COLOR')
        layout.prop(scene, "mpe_handle_mode")
        layout.operator(MPE_OT_create_curve.bl_idname, icon='CURVE_BEZCURVE')

        layout.separator()
        layout.label(text="Bake")
        layout.prop(scene, "mpe_bake_every_n_frames")
        layout.prop(scene, "mpe_curve_accuracy")
        layout.prop(scene, "mpe_key_interpolation")
        layout.prop(scene, "mpe_set_scene_range_for_motion_path")
        layout.operator(MPE_OT_bake_keys_to_curve.bl_idname, icon='KEY_HLT')

        layout.separator()
        layout.label(text="Motion Path")
        row = layout.row(align=True)
        row.operator(MPE_OT_recalculate_motion_path.bl_idname, icon='IPO_BEZIER')
        row.operator(MPE_OT_clear_motion_path.bl_idname, icon='X')

        layout.separator()
        box = layout.box()
        box.label(text="How to curve a motion path:")
        box.label(text="1. Create editable motion path")
        box.label(text="2. Adjust the bezier curve in Edit Mode")
        box.label(text="3. Adjust the value of Bake every N Frames.")
        box.label(text="(Bake evert N Frames sets the space between every keyframes.)")

classes = (
    MPE_OT_create_curve,
    MPE_OT_apply_curve_color,
    MPE_OT_bake_keys_to_curve,
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
    bpy.types.Scene.mpe_bake_every_n_frames = bpy.props.IntProperty(
        name="Bake Every N Frames",
        default=1,
        min=1,
        max=100,
        description="Bake one new key every N frames over the original range",
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


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.mpe_curve_thickness
    del bpy.types.Scene.mpe_curve_color
    del bpy.types.Scene.mpe_handle_mode
    del bpy.types.Scene.mpe_bake_every_n_frames
    del bpy.types.Scene.mpe_curve_accuracy
    del bpy.types.Scene.mpe_key_interpolation
    del bpy.types.Scene.mpe_set_scene_range_for_motion_path


if __name__ == "__main__":
    register()
