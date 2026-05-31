# ─────────────────────────────────────────────────────────────────────────────
#  BB MultiLevel Focus
#  Location : 3D View  (F = View Selected · Ctrl+F = Isolate)
# ─────────────────────────────────────────────────────────────────────────────

bl_info = {
    "name":        "BB MultiLevel Focus",
    "author":      "Blender Bob + Claude.ai",
    "version":     (1, 0, 0),
    "blender":     (4, 2, 0),
    "location":    "View3D: F / Ctrl+F",
    "description": "Multi-level viewport focus and object isolation",
    "category":    "3D View",
}

import bpy
import bmesh
import gpu
import blf
import json
from gpu_extras.batch import batch_for_shader
from bpy.props import BoolProperty, EnumProperty, StringProperty, PointerProperty
from bpy.app.handlers import persistent


# ═══════════════════════════════════════════════════════════════════════════════
#  PREFERENCES
# ═══════════════════════════════════════════════════════════════════════════════

class BBFocusPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    tween: BoolProperty(
        name="Viewport Tweening",
        description="Animate the viewport when zooming to selection",
        default=True)

    def draw(self, context):
        self.layout.prop(self, "tween")


def _prefs():
    return bpy.context.preferences.addons[__name__].preferences


# ═══════════════════════════════════════════════════════════════════════════════
#  ISOLATION STACK
#
#  Stored as a JSON string on the scene — no PointerProperty, no CollectionProperty.
#  Each level: {"hidden": ["ObjName", ...], "mirrors": ["ObjName::ModName", ...]}
#  Using names instead of pointers means deleted objects are skipped gracefully.
# ═══════════════════════════════════════════════════════════════════════════════

class BBFocusSceneProps(bpy.types.PropertyGroup):
    stack: StringProperty(default="[]")


def _stack_read(scene):
    try:
        return json.loads(scene.bb_focus.stack)
    except Exception:
        return []


def _stack_write(scene, data):
    scene.bb_focus.stack = json.dumps(data)


def _stack_depth(scene):
    return len(_stack_read(scene))


def _stack_push(scene, hidden_names, disabled_mirrors):
    data = _stack_read(scene)
    data.append({"hidden": hidden_names, "mirrors": disabled_mirrors})
    _stack_write(scene, data)


def _stack_pop(scene):
    data = _stack_read(scene)
    if not data:
        return None
    level = data.pop()
    _stack_write(scene, data)
    return level


# ═══════════════════════════════════════════════════════════════════════════════
#  HUD
#  Border colour shifts white → orange as isolation depth increases.
# ═══════════════════════════════════════════════════════════════════════════════

_hud_handle = None


def _draw_hud():
    ctx = bpy.context
    if not ctx or not ctx.scene:
        return
    depth = _stack_depth(ctx.scene)
    if not depth:
        return
    if not ctx.space_data or not ctx.space_data.overlay.show_overlays:
        return

    region = ctx.region
    w, h   = region.width, region.height
    lw     = 2

    # White at depth 1, orange at depth 3+
    green  = max(0.0, 1.0 - (depth - 1) * 0.5)
    color  = (1.0, green, 0.0, 0.30)

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    shader.bind()
    shader.uniform_float("color", color)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(lw)

    corners = [(lw, lw), (w - lw, lw), (w - lw, h - lw), (lw, h - lw)]
    edges   = [(0, 1), (1, 2), (2, 3), (3, 0)]
    batch_for_shader(shader, 'LINES', {"pos": corners}, indices=edges).draw(shader)

    gpu.state.blend_set('NONE')
    gpu.state.line_width_set(1.0)

    # Label
    scale    = ctx.preferences.view.ui_scale
    fontsize = max(10, int(12 * scale))
    label    = "Isolation  %d" % depth

    blf.size(0, fontsize)
    blf.color(0, 1.0, green, 0.0, 0.9)
    tw = blf.dimensions(0, label)[0]
    blf.position(0, (w - tw) * 0.5, h - fontsize - 6, 0)
    blf.draw(0, label)


@persistent
def _hud_sync(scene):
    global _hud_handle

    if _hud_handle and "RNA_HANDLE_REMOVED" in str(_hud_handle):
        _hud_handle = None

    active = _stack_depth(scene) > 0

    if active and _hud_handle is None:
        _hud_handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_hud, (), 'WINDOW', 'POST_PIXEL')
    elif not active and _hud_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_hud_handle, 'WINDOW')
        _hud_handle = None


# ═══════════════════════════════════════════════════════════════════════════════
#  OPERATOR
# ═══════════════════════════════════════════════════════════════════════════════

class BB_OT_MultiLevelFocus(bpy.types.Operator):
    bl_idname  = "bb.multi_level_focus"
    bl_label   = "BB Multi-Level Focus"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=[('VIEW_SELECTED', "View Selected", "Zoom viewport to selection"),
               ('ISOLATE',       "Isolate",       "Enter or deepen object isolation")],
        default='VIEW_SELECTED')

    suppress_mirrors: BoolProperty(
        name="Suppress Mirrors",
        description="Disable Mirror modifiers on isolated objects to reduce visual noise",
        default=True)

    ignore_mirrors: BoolProperty(
        name="Ignore Mirrors for Framing",
        description="Temporarily hide Mirror modifiers before zooming so they don't skew the framing",
        default=True)

    invert: BoolProperty(
        name="Invert",
        description="Isolate everything except the selection",
        default=False)

    @classmethod
    def poll(cls, context):
        return (context.space_data and
                context.space_data.type == 'VIEW_3D' and
                context.region and
                context.region.type == 'WINDOW')

    def draw(self, context):
        col = self.layout.column(align=True)
        if self.mode == 'VIEW_SELECTED':
            col.prop(self, "ignore_mirrors", toggle=True)
        else:
            col.prop(self, "suppress_mirrors", toggle=True)
            col.prop(self, "invert",           toggle=True)

    def execute(self, context):
        if self.mode == 'VIEW_SELECTED':
            return self._view_selected(context)
        return self._isolate(context)

    # ── View Selected ─────────────────────────────────────────────────────────

    def _view_selected(self, context):
        mode          = context.mode
        hidden_mods   = []
        had_selection = True

        if mode == 'OBJECT':
            sel = context.selected_objects
            if not sel:
                op = bpy.ops.view3d.view_all
                op('INVOKE_DEFAULT') if _prefs().tween else op()
                return {'FINISHED'}

            if self.ignore_mirrors:
                for obj in sel:
                    for mod in obj.modifiers:
                        if mod.type == 'MIRROR' and mod.show_viewport:
                            mod.show_viewport = False
                            hidden_mods.append(mod)

        elif mode == 'EDIT_MESH':
            bm = bmesh.from_edit_mesh(context.active_object.data)
            bm.normal_update()
            had_selection = any(v.select for v in bm.verts)
            if not had_selection:
                for v in bm.verts:
                    v.select_set(True)
                bm.select_flush(True)

        op = bpy.ops.view3d.view_selected
        op('INVOKE_DEFAULT') if _prefs().tween else op()

        for mod in hidden_mods:
            mod.show_viewport = True

        if mode == 'EDIT_MESH' and not had_selection:
            bm = bmesh.from_edit_mesh(context.active_object.data)
            for f in bm.faces:
                f.select_set(False)
            bm.select_flush(False)

        return {'FINISHED'}

    # ── Isolate ───────────────────────────────────────────────────────────────

    def _isolate(self, context):
        space   = context.space_data
        scene   = context.scene
        visible = list(context.visible_objects)

        if self.invert:
            for obj in visible:
                obj.select_set(not obj.select_get())

        selection = list(context.selected_objects)

        if space.local_view:
            if selection and set(selection) != set(visible):
                self._enter(space, scene, selection, visible)
            else:
                self._exit(space, scene)
        else:
            if not selection:
                return {'CANCELLED'}
            _stack_write(scene, "[]")
            self._enter(space, scene, selection, visible, first=True)

        return {'FINISHED'}

    def _enter(self, space, scene, selection, visible, first=False):
        to_hide = [obj for obj in visible if obj not in selection]

        # On the very first level, even with nothing to hide we still
        # enter local view so subsequent levels can go deeper.
        if not to_hide and not first:
            return

        if first:
            bpy.ops.view3d.localview(frame_selected=False)
        else:
            for obj in to_hide:
                obj.local_view_set(space, False)

        hidden_names = [obj.name for obj in to_hide]

        disabled_mirrors = []
        if self.suppress_mirrors:
            for obj in selection:
                for mod in obj.modifiers:
                    if mod.type == 'MIRROR' and mod.show_viewport:
                        mod.show_viewport = False
                        disabled_mirrors.append("%s::%s" % (obj.name, mod.name))

        _stack_push(scene, hidden_names, disabled_mirrors)

        if self.invert:
            for obj in selection:
                obj.select_set(False)
        elif selection:
            selection[0].select_set(True)

    def _exit(self, space, scene):
        level = _stack_pop(scene)
        if level is None:
            bpy.ops.view3d.localview(frame_selected=False)
            return

        # Last level — exit local view entirely (Blender restores visibility)
        if _stack_depth(scene) == 0:
            bpy.ops.view3d.localview(frame_selected=False)
        else:
            # Intermediate level — manually restore objects into local view
            for name in level["hidden"]:
                obj = bpy.data.objects.get(name)
                if obj:
                    obj.local_view_set(space, True)

        # Re-enable any suppressed Mirror modifiers
        for entry in level["mirrors"]:
            obj_name, mod_name = entry.split("::", 1)
            obj = bpy.data.objects.get(obj_name)
            if obj:
                mod = obj.modifiers.get(mod_name)
                if mod:
                    mod.show_viewport = True


# ═══════════════════════════════════════════════════════════════════════════════
#  REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════

_classes = (
    BBFocusPreferences,
    BBFocusSceneProps,
    BB_OT_MultiLevelFocus,
)

_keymaps = []


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.bb_focus = PointerProperty(type=BBFocusSceneProps)

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        km  = kc.keymaps.new(name='3D View Generic', space_type='VIEW_3D')
        kmi = km.keymap_items.new('bb.multi_level_focus', 'F', 'PRESS')
        kmi.properties.mode = 'VIEW_SELECTED'
        _keymaps.append((km, kmi))

        km  = kc.keymaps.new(name='Object Mode')
        kmi = km.keymap_items.new('bb.multi_level_focus', 'F', 'PRESS', ctrl=True)
        kmi.properties.mode   = 'ISOLATE'
        kmi.properties.invert = False
        _keymaps.append((km, kmi))

        km  = kc.keymaps.new(name='Object Mode')
        kmi = km.keymap_items.new('bb.multi_level_focus', 'F', 'PRESS', ctrl=True, alt=True)
        kmi.properties.mode   = 'ISOLATE'
        kmi.properties.invert = True
        _keymaps.append((km, kmi))

    if _hud_sync not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_hud_sync)


def unregister():
    global _hud_handle

    if _hud_sync in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_hud_sync)

    if _hud_handle and "RNA_HANDLE_REMOVED" not in str(_hud_handle):
        bpy.types.SpaceView3D.draw_handler_remove(_hud_handle, 'WINDOW')
        _hud_handle = None

    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()

    try:
        del bpy.types.Scene.bb_focus
    except Exception:
        pass

    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


if __name__ == "__main__":
    register()
