# ─────────────────────────────────────────────────────────────────────────────
#  BB MultiLevel Focus
#  Location : 3D View  (F = View Selected · Ctrl+F = Local View isolation)
# ─────────────────────────────────────────────────────────────────────────────

bl_info = {
    "name":        "BB MultiLevel Focus",
    "author":      "Blender Bob",
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
from gpu_extras.batch import batch_for_shader
from bpy.props import (BoolProperty, EnumProperty, StringProperty,
                       PointerProperty, CollectionProperty)
from bpy.app.handlers import persistent


# ═══════════════════════════════════════════════════════════════════════════════
#  PROPERTY GROUPS
# ═══════════════════════════════════════════════════════════════════════════════

class BBFocus_ObjectEntry(bpy.types.PropertyGroup):
    obj: PointerProperty(name="Object", type=bpy.types.Object)


class BBFocus_Epoch(bpy.types.PropertyGroup):
    objects:    CollectionProperty(type=BBFocus_ObjectEntry)
    unmirrored: CollectionProperty(type=BBFocus_ObjectEntry)


class BBFocus_SceneProps(bpy.types.PropertyGroup):
    focus_history: CollectionProperty(type=BBFocus_Epoch)


# ═══════════════════════════════════════════════════════════════════════════════
#  PREFERENCES
# ═══════════════════════════════════════════════════════════════════════════════

class BBFocusPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    focus_view_transition: BoolProperty(
        name="Viewport Tweening",
        description="Animate the viewport when zooming to selection",
        default=True)

    def draw(self, context):
        self.layout.prop(self, "focus_view_transition")


# ═══════════════════════════════════════════════════════════════════════════════
#  HUD  (Focus-level border + label)
# ═══════════════════════════════════════════════════════════════════════════════

_hud_handler = None


def _draw_hud():
    context = bpy.context
    if not context or not context.scene:
        return
    try:
        history = context.scene.bb_focus.focus_history
    except Exception:
        return
    if not history:
        return
    if not context.space_data or not context.space_data.overlay.show_overlays:
        return

    region = context.region
    w, h   = region.width, region.height
    lw     = 2

    # Border
    coords  = [(lw, lw), (w - lw, lw), (w - lw, h - lw), (lw, h - lw)]
    indices = [(0, 1), (1, 2), (2, 3), (3, 0)]

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    shader.bind()
    shader.uniform_float("color", (1.0, 1.0, 1.0, 0.25))

    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('ALPHA')
    gpu.state.line_width_set(lw)
    batch_for_shader(shader, 'LINES', {"pos": coords}, indices=indices).draw(shader)
    gpu.state.blend_set('NONE')
    gpu.state.line_width_set(1.0)

    # Label
    scale    = context.preferences.view.ui_scale
    font     = 1
    fontsize = int(12 * scale)
    blf.size(font, fontsize)
    blf.color(font, 1.0, 1.0, 1.0, 1.0)
    blf.position(font, w / 2 - int(60 * scale), h - 4 - fontsize, 0)
    blf.draw(font, "Focus Level: %d" % len(history))


@persistent
def _hud_update(scene):
    global _hud_handler

    if _hud_handler and "RNA_HANDLE_REMOVED" in str(_hud_handler):
        _hud_handler = None

    has_history = bool(scene.bb_focus.focus_history)

    if has_history and not _hud_handler:
        _hud_handler = bpy.types.SpaceView3D.draw_handler_add(
            _draw_hud, (), 'WINDOW', 'POST_PIXEL')
    elif not has_history and _hud_handler:
        bpy.types.SpaceView3D.draw_handler_remove(_hud_handler, 'WINDOW')
        _hud_handler = None


# ═══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _prefs():
    return bpy.context.preferences.addons[__name__].preferences


def _local_view_set(space, states):
    if space.local_view:
        for obj, local in states:
            obj.local_view_set(space, local)


# ═══════════════════════════════════════════════════════════════════════════════
#  OPERATOR
# ═══════════════════════════════════════════════════════════════════════════════

class BB_OT_Focus(bpy.types.Operator):
    bl_idname  = "bb.focus"
    bl_label   = "BB Focus"
    bl_options = {'REGISTER', 'UNDO'}

    method: EnumProperty(
        name="Method",
        items=[('VIEW_SELECTED', 'View Selected', 'Zoom viewport to selection'),
               ('LOCAL_VIEW',   'Local View',    'Multi-level object isolation')],
        default='VIEW_SELECTED')

    unmirror:       BoolProperty(name="Un-Mirror",      default=True,
                                 description="Temporarily hide Mirror modifiers on focused objects")
    ignore_mirrors: BoolProperty(name="Ignore Mirrors", default=True,
                                 description="Hide Mirror modifiers before zooming so they don't skew the framing")
    invert:         BoolProperty(name="Invert Selection", default=False,
                                 description="Isolate everything EXCEPT the selection")

    @classmethod
    def poll(cls, context):
        return (context.space_data and
                context.space_data.type == 'VIEW_3D' and
                context.region.type == 'WINDOW')

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        if self.method == 'VIEW_SELECTED':
            box.label(text="View Selected")
            box.prop(self, "ignore_mirrors", toggle=True)
        else:
            box.label(text="Local View")
            box.prop(self, "unmirror",       toggle=True)
            box.prop(self, "invert",         toggle=True)

    def execute(self, context):
        if self.method == 'VIEW_SELECTED':
            self._view_selected(context)
        else:
            self._local_view(context)
        return {'FINISHED'}

    # ── View Selected ─────────────────────────────────────────────────────────

    def _view_selected(self, context):
        mirrors          = []
        nothing_selected = False
        mode             = context.mode

        if mode == 'OBJECT':
            sel = context.selected_objects
            if not sel:
                op = bpy.ops.view3d.view_all
                op('INVOKE_DEFAULT') if _prefs().focus_view_transition else op()
                return
            if self.ignore_mirrors:
                mirrors = [mod for obj in sel for mod in obj.modifiers
                           if mod.type == 'MIRROR' and mod.show_viewport]
                for mod in mirrors:
                    mod.show_viewport = False

        elif mode == 'EDIT_MESH':
            bm = bmesh.from_edit_mesh(context.active_object.data)
            bm.normal_update()
            nothing_selected = not any(v.select for v in bm.verts)
            if nothing_selected:
                for v in bm.verts:
                    v.select_set(True)
                bm.select_flush(True)

        op = bpy.ops.view3d.view_selected
        op('INVOKE_DEFAULT') if _prefs().focus_view_transition else op()

        for mod in mirrors:
            mod.show_viewport = True

        if nothing_selected and mode == 'EDIT_MESH':
            bm = bmesh.from_edit_mesh(context.active_object.data)
            for f in bm.faces:
                f.select_set(False)
            bm.select_flush(False)

    # ── Local View (multi-level) ───────────────────────────────────────────────

    def _local_view(self, context):
        view    = context.space_data
        vis     = context.visible_objects
        history = context.scene.bb_focus.focus_history

        if self.invert:
            for obj in vis:
                obj.select_set(not obj.select_get())

        sel = context.selected_objects

        if view.local_view:
            if sel and set(vis) != set(sel):
                self._enter_focus(context, view, sel, history)
            else:
                if history:
                    self._exit_focus(context, view, history)
                else:
                    bpy.ops.view3d.localview(frame_selected=False)
        elif sel:
            if history:
                history.clear()
            self._enter_focus(context, view, sel, history, init=True)

    def _enter_focus(self, context, view, sel, history, init=False):
        vis    = context.visible_objects
        hidden = [obj for obj in vis if obj not in sel]
        if not hidden:
            return

        if init:
            bpy.ops.view3d.localview(frame_selected=False)
        else:
            _local_view_set(view, [(obj, False) for obj in hidden])

        epoch      = history.add()
        epoch.name = "Epoch_%d" % (len(history) - 1)

        for obj in hidden:
            e = epoch.objects.add()
            e.obj  = obj
            e.name = obj.name

        if self.unmirror:
            for obj in sel:
                for mod in obj.modifiers:
                    if mod.type == 'MIRROR' and mod.show_viewport:
                        mod.show_viewport = False
                        u = epoch.unmirrored.add()
                        u.obj  = obj
                        u.name = obj.name

        if self.invert:
            for obj in sel:
                obj.select_set(False)
        elif sel:
            sel[0].select_set(True)

    def _exit_focus(self, context, view, history):
        last = history[-1]

        if len(history) == 1:
            bpy.ops.view3d.localview(frame_selected=False)
        else:
            _local_view_set(view, [(e.obj, True) for e in last.objects])

        for u in last.unmirrored:
            for mod in u.obj.modifiers:
                if mod.type == 'MIRROR':
                    mod.show_viewport = True

        idx = list(history.keys()).index(last.name)
        history.remove(idx)


# ═══════════════════════════════════════════════════════════════════════════════
#  REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════

_classes = (
    BBFocus_ObjectEntry,
    BBFocus_Epoch,
    BBFocus_SceneProps,
    BBFocusPreferences,
    BB_OT_Focus,
)

_keymaps = []


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.bb_focus = PointerProperty(type=BBFocus_SceneProps)

    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if kc:
        # F  →  View Selected  (works in any 3D View context)
        km  = kc.keymaps.new(name='3D View Generic', space_type='VIEW_3D')
        kmi = km.keymap_items.new('bb.focus', 'F', 'PRESS')
        kmi.properties.method = 'VIEW_SELECTED'
        _keymaps.append((km, kmi))

        # Ctrl+F  →  Local View isolate
        km  = kc.keymaps.new(name='Object Mode')
        kmi = km.keymap_items.new('bb.focus', 'F', 'PRESS', ctrl=True)
        kmi.properties.method  = 'LOCAL_VIEW'
        kmi.properties.invert  = False
        _keymaps.append((km, kmi))

        # Ctrl+Alt+F  →  Local View isolate (inverted)
        km  = kc.keymaps.new(name='Object Mode')
        kmi = km.keymap_items.new('bb.focus', 'F', 'PRESS', ctrl=True, alt=True)
        kmi.properties.method  = 'LOCAL_VIEW'
        kmi.properties.invert  = True
        _keymaps.append((km, kmi))

    if _hud_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_hud_update)


def unregister():
    global _hud_handler

    if _hud_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_hud_update)

    if _hud_handler and "RNA_HANDLE_REMOVED" not in str(_hud_handler):
        bpy.types.SpaceView3D.draw_handler_remove(_hud_handler, 'WINDOW')
        _hud_handler = None

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
