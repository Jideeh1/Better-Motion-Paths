# Better-Motion-Paths [Blender 3.3+]

A Blender add-on that lets you adjust object-level motion paths inside the 3D viewport.
<p align="center">
  <img src="BMP.gif">
</p>
This add-on adds a **Motion Path** panel to Blender's 3D View sidebar.

`3D Viewport > Sidebar/N Panel > Animation > Motion Path`

Better Motion Path creates an editable Bezier curve from an object's Location keyframes. The curve is adjusted using object-mode handles, so you can reshape the path directly in the viewport without entering curve Edit Mode.

# Recommended Workflow

```
1. Select an animated object or armature
2. Open the Motion Path panel
3. Set Curve Thickness, Curve Color, Handle Mode, and Control Handles
4. Click Create Editable Motion Path
5. Move the object-mode handles in the viewport
6. Optional: enable Auto Bake
7. Choose Bake Every N Frames, Curve Accuracy, and New Key Interpolation
8. Click Bake Keyframes To Curve
9. Review the recalculated motion path
```

## Quick Reference

| UI Item | Type | Purpose |
|---|---|---|
| `Handle Mode` | Dropdown | Sets the initial Bezier handle type when creating the editable curve. Options: `Auto`, `Vector`, `Free`. |
| `Control Handles` | Value | Controls how many object-mode control points are created for the editable motion path. |
| `Reset Motion Path` | Button | Resets the editable helper curve to the target object's current Location keyframes, or restores the saved original path after baking. |
| `Remove Editable Motion Paths` | Button | Removes generated editable curves and their object-mode handles without changing the target object's keyframes. |
| `Curve Thickness` | Value | Controls the thickness of the helper Bezier curve and the size of the object-mode handles. |
| `Curve Color` | Color Picker | Chooses the color of the generated helper Bezier curve. |
| `Create Editable Motion Path` | Button | Creates a temporary Bezier curve from the selected object's or armature's Location keyframes and adds object-mode handles. |
| `Auto Bake` | Checkbox | Bakes keyframes after the editable curve handles are changed without deleting the curve. |
| `Bake Every N Frames` | Value | Controls how often new Location keyframes are inserted during baking. `1` gives the most accurate result. |
| `Curve Accuracy` | Value | Controls how accurately the edited Bezier curve is sampled. Higher values follow tighter bends more accurately. |
| `New Key Interpolation` | Dropdown | Sets the interpolation type for newly baked Location keyframes. Options: `Bezier`, `Linear`, `Constant`. |
| `Use Baked Range For Motion Path` | Checkbox | Sets the scene frame range to the baked keyframe range before calculating motion paths. |
| `Bake Keyframes To Curve` | Button | Bakes new Location keyframes along the edited curve. If Auto Bake is off, it deletes the helper curve and handles after baking. |
| `Calculate Motion Path` | Button | Calculates the selected object's or armature's motion path over its current Location keyframe range. |
| `Recalculate Motion Path` | Button | Recalculates the selected object's or armature's motion path if one already exists. |
| `Clear Motion Path` | Button | Clears the selected object's or armature's calculated motion path from the viewport. |

# Instructions

### 1. Install the add-on

Download the add-on `.zip` file.

In Blender, go to:

`Edit > Preferences > Add-ons > Install`

Select the add-on file, then enable it in the add-ons list.

---

### 2. Open the add-on panel

In the 3D Viewport, open the sidebar by pressing:

`N`

Then go to:

`Animation > Motion Path`

---

### 3. Select an animated object or armature

Select the object or armature whose object-level Location keyframes you want to edit.

The selected object or armature should have at least two Location keyframes.

If nothing is selected, the panel will show:

`No selected object or armature yet`

---

### 4. Set up the editable curve

In the **Create Curve** section, adjust the curve options if needed:

- `Handle Mode` controls the initial Bezier handle type.
- `Control Handles` controls how many editable object-mode control points are created.
- `Curve Thickness` controls the helper curve thickness and handle size.
- `Curve Color` controls the color of the helper Bezier curve.

---

### 5. Create the editable motion path

Click:

`Create Editable Motion Path`

The add-on creates a temporary Bezier curve based on the selected object's or armature's Location keyframes.

It also clears the current motion path display so the generated handles are easier to see.

The add-on creates object-mode controls for the curve:

- yellow handles are Bezier control points
- blue handles are left tangent handles
- green handles are right tangent handles
- connector lines show which tangent handles belong to each control point

---

### 6. Edit the curve in Object Mode

Move the generated object-mode handles directly in the viewport.

You do not need to enter curve Edit Mode.

Move the yellow point handles to reposition the path.

Move the blue and green tangent handles to curve the path.

---

### 7. Optional: enable Auto Bake

Enable:

`Auto Bake`

When this is enabled, moving the object-mode handles will bake the target object's Location keyframes after the curve changes.

Auto Bake keeps the editable curve and handles in the scene.

---

### 8. Set the bake options

In the **Bake** section, adjust the bake settings if needed:

- `Bake Every N Frames` controls how often new Location keyframes are inserted.
- `Curve Accuracy` controls how accurately the Bezier curve is sampled.
- `New Key Interpolation` controls the interpolation type of the new baked keyframes.
- `Use Baked Range For Motion Path` sets the scene frame range to the baked animation range before calculating motion paths.

For the most accurate result, keep:

`Bake Every N Frames = 1`

---

### 9. Bake the keyframes to the curve

Click:

`Bake Keyframes To Curve`

If `Auto Bake` is off, the add-on will:

1. Read the edited Bezier curve from the object-mode handles.
2. Delete the original Location keyframes.
3. Bake new Location keyframes along the edited curve.
4. Delete the temporary helper curve.
5. Delete the object-mode handles and connector lines.
6. Recalculate the motion path.

If `Auto Bake` is on, the add-on will bake the keyframes but keep the editable curve and handles.

---

### 10. Review the new animation

After baking with Auto Bake off, the original object or armature remains selected.

Scrub the timeline to preview the new animation.

The motion path should update automatically after baking.

---

### 11. Reset the editable motion path

Click:

`Reset Motion Path`

If an editable curve exists, this resets the editable curve to the target object's current Location keyframes.

If the motion path was already baked and reset data is available, this restores the saved original path.

---

### 12. Remove editable motion paths

Click:

`Remove Editable Motion Paths`

This removes the generated helper curve, object-mode handles, and connector lines without changing the target object's keyframes.

---

### 13. Calculate or recalculate the motion path manually

Click:

`Calculate Motion Path`

or:

`Recalculate Motion Path`

This calculates the selected object's or armature's visible motion path over its current Location keyframe range.

---

### 14. Clear the motion path

Click:

`Clear Motion Path`

This clears the selected object's or armature's calculated motion path from the viewport.

# Notes

Better Motion Path works on object-level Location keyframes.

It is intended for objects or armatures animated through their object Location channels.

The editable curve and object-mode handles are helper objects. They are safe to remove using `Remove Editable Motion Paths`.
