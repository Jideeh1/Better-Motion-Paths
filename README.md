# Better-Motion-Paths [Blender 3.3+]
![views](https://img.shields.io/badge/views-tracked-blue)

A blender add-on that allows motion path adjustment inside the 3D viewport.
<p align="center">
  <img src="Better Motion Paths.png">
</p>

This add-on adds a **Motion Path** panel to Blender's 3D View sidebar.
`3D Viewport > Sidebar/N Panel > Motion Path`
This lets you create a visible Bezier curve from an object's motion path that is adjustable in **Edit Mode.**

# Recommended Workflow
```
1. Select an animated object or armature
2. Choose Curve Thickness
3. Choose Curve Color
4. Choose Handle Mode
5. Click Create Editable Motion Path Curve
6. Edit the Bezier curve in the viewport
7. Choose Bake Every N Frames
8. Choose Curve Accuracy
9. Choose New Key Interpolation
10. Keep Use Baked Range For Motion Path enabled unless you need your scene range unchanged
11. Click Bake Keyframes To Curve
12. Review the automatically recalculated motion path
```
## Quick Reference
| UI Item | Type | Purpose |
|---|---|---|
| `Curve Thickness` | Value | Controls the thickness of the generated helper Bezier curve. |
| `Curve Color` | Color Picker | Chooses the color of the generated helper Bezier curve. |
| `Apply Color To Edit Curve` | Button | Applies the selected `Curve Color` to an already existing helper curve. |
| `Handle Mode` | Dropdown | Sets the initial Bezier handle type when creating the helper curve. Options: `Auto`, `Vector`, `Free`. |
| `Create Editable Motion Path Curve` | Button | Creates a temporary editable Bezier curve from the selected object's or armature's Location keyframes. |
| `Bake Every N Frames` | Value | Controls how often new Location keyframes are inserted during baking. For example: `1` = every frame, `2` = every 2 frames, `5` = every 5 frames. |
| `Curve Accuracy` | Value | Controls how accurately the edited Bezier curve is sampled. Higher values follow tighter bends more accurately. |
| `New Key Interpolation` | Dropdown | Sets the interpolation type for the newly baked Location keyframes. Options: `Bezier`, `Linear`, `Constant`. |
| `Use Baked Range For Motion Path` | Checkbox | Sets the scene frame range to the baked keyframe range before calculating motion paths. |
| `Bake Keyframes To Curve` | Button | Reads the edited curve, deletes the original Location keyframes, bakes new Location keyframes, deletes the helper curve, and recalculates the motion path. |
| `Recalculate Motion Path` | Button | Manually recalculates the selected object's or armature's motion path. |
| `Clear Motion Path` | Button | Clears the selected object's or armature's calculated motion path from the viewport. |
# Instructions

<p align="center">
  <img src="BMP Lite.gif">
</p>

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
`Animation > Motion Path Curve`
---
### 3. Select an animated object or armature
Select the object or armature whose object-level Location keyframes you want to edit.
The selected object or armature should have at least two Location keyframes.
If nothing is selected, the panel will show:
`No selected object or armature yet`
---
### 4. Set up the helper curve
In the **Create Curve** section, adjust the curve options if needed:
- `Curve Thickness` controls how thick the helper Bezier curve appears in the viewport.
- `Curve Color` controls the color of the helper Bezier curve.
- `Handle Mode` controls the initial Bezier handle type.
---
### 5. Create the editable motion path curve
Click:
`Create Editable Motion Path Curve`
The add-on creates a temporary Bezier curve based on the selected object's or armature's existing Location keyframes.
The generated curve is selected automatically so you can edit it right away.
---
### 6. Edit the Bezier curve
Edit the generated Bezier curve in the viewport.
You can move the curve points, adjust handles, reshape arcs, or change the path however you like.
The helper curve is temporary and will be deleted after baking.
---
### 7. Optional: change the curve color
If the helper curve already exists and you want to change its color:
1. Choose a new color using `Curve Color`.
2. Click `Apply Color To Edit Curve`.
This updates the existing helper curve without recreating it.
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
The add-on will:
1. Read the edited Bezier curve.
2. Delete the original Location keyframes.
3. Bake new Location keyframes along the edited curve.
4. Delete the temporary helper curve.
5. Automatically recalculate the motion path.
---
### 10. Review the new animation
After baking, the original object or armature remains selected.
Scrub the timeline to preview the new animation.
The motion path should update automatically after baking.
---
### 11. Recalculate the motion path manually
If the motion path does not visually update, click:
`Recalculate Motion Path`
This manually recalculates the selected object's or armature's motion path.
---
### 12. Clear the motion path
If you want to remove the visible motion path from the viewport, click:
`Clear Motion Path`
This clears the selected object's or armature's calculated motion path.
