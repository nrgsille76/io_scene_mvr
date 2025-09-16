# SPDX-FileCopyrightText: 2024 Sebastian Schrand
#
# SPDX-License-Identifier: GPL-2.0-or-later

__author__ = "Sebastian Sille <nrgsille@gmail.com>"
__version__ = "1.4.4"
__date__ = "2 Aug 2024"


import os
import bpy
from . import export_mvr
from . import import_mvr
from . import import_gdtf
from bpy_extras.io_utils import (
    ImportHelper,
    ExportHelper,
    orientation_helper,
    axis_conversion,
    poll_file_object_drop,
)
from bpy.props import (
    IntProperty,
    BoolProperty,
    EnumProperty,
    FloatProperty,
    StringProperty,
    PointerProperty,
    CollectionProperty,
    FloatVectorProperty,
)
from bpy.types import (
    Operator,
    FileHandler,
    AddonPreferences,
)

'''
bl_info = {
    "name": "Import MVR & GDTF",
    "author": "Sebastian Sille",
    "version": (1, 4, 4),
    "blender": (4, 0, 0),
    "location": "File > Import",
    "description": "Import My Virtual Rig and General Device Type Format",
    "warning": "",
    "filepath_url": "",
    "category": "Import-Export",
}
'''

if "bpy" in locals():
    import importlib
    if "ExportMVR" in locals():
        importlib.reload(export_mvr)
    if "ImportMVR" in locals():
        importlib.reload(import_mvr)
    if "ImportGDTF" in locals():
        importlib.reload(import_gdtf)


class MVR_AddonPreferences(AddonPreferences):
    bl_idname = __package__

    profile_path: StringProperty(
        name="GDTF File Path",
        description="Directory of GDTF profiles",
        default="",
        subtype='DIR_PATH',
    )

    def draw(self, context):
        layout = self.layout
        line = layout.row(align=True)
        line.prop(self, "profile_path", text="Path to GDTF Files", icon='FOLDER_REDIRECT', placeholder="//gdtf/")


@orientation_helper(axis_forward='Y', axis_up='Z')
class ImportMVR(Operator, ImportHelper):
    """Import My Virtual Rig"""
    bl_idname = "import_scene.mvr"
    bl_label = "Import MVR (.mvr)"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".mvr"
    filter_glob: StringProperty(default="*.mvr", options={'HIDDEN'})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH')

    scale_objects: FloatProperty(
        name="Scale",
        description="Scale factor for all objects",
        min=0.0001, max=10000.0,
        soft_min=0.001, soft_max=1000.0,
        default=1.0,
        subtype='FACTOR',
    )
    use_collection: BoolProperty(
        name="Collection",
        description="Create a new collection",
        default=False,
    )
    use_apply_transform: BoolProperty(
        name="Apply Transform",
        description="Apply matrix transform",
        default=False,
    )
    use_fixtures: BoolProperty(
        name="Fixtures",
        description="Import fixtures of the scene",
        default=True,
    )
    use_targets: BoolProperty(
        name="Targets",
        description="Use targets for constraints",
        default=True,
    )
    fixture_path: StringProperty(
        name="GDTF File Path",
        description="Import GDTF profiles from this directory",
        default="",
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        import_mvr_include(layout, self, context)
        import_mvr_transform(layout, self)

    def execute(self, context):
        if os.path.lexists(context.preferences.addons[__package__].preferences.profile_path):
            self.fixture_path = context.preferences.addons[__package__].preferences.profile_path
        keywords = self.as_keywords(ignore=("axis_forward", "axis_up", "filter_glob"))
        global_matrix = axis_conversion(from_forward=self.axis_forward, from_up=self.axis_up).to_4x4()
        keywords["global_matrix"] = global_matrix
        return import_mvr.load(self, context, **keywords)

    def invoke(self, context, event):
        return self.invoke_popup(context)


def import_mvr_include(layout, operator, context):
    header, body = layout.panel("MVR_import_include", default_closed=False)
    prefs = context.preferences.addons[__package__].preferences
    header.label(text="Include")
    if body:
        line = body.row(align=True)
        line.prop(operator, "use_collection")
        line.label(text="", icon='OUTLINER_COLLECTION' if operator.use_collection else 'GROUP')
        line = body.row(align=True)
        line.prop(operator, "use_fixtures")
        line.label(text="", icon='OUTLINER_OB_LIGHT' if operator.use_fixtures else 'LIGHT')
        line = body.row(align=True)
        line.enabled = (operator.use_fixtures == True)
        line.prop(operator, "fixture_path", text="GDTF Path", icon='FILE_FOLDER', placeholder=prefs.profile_path)


def import_mvr_transform(layout, operator):
    header, body = layout.panel("MVR_import_transform", default_closed=False)
    header.label(text="Transform")
    if body:
        body.prop(operator, "scale_objects")
        line = body.row(align=True)
        line.enabled = (operator.use_fixtures == True)
        line.prop(operator, "use_targets")
        line.label(text="", icon='CON_STRETCHTO' if operator.use_targets else 'CON_TRACKTO')
        line = body.row(align=True)
        line.prop(operator, "use_apply_transform")
        line.label(text="", icon='MESH_CUBE' if operator.use_apply_transform else 'MOD_SOLIDIFY')
        body.prop(operator, "axis_forward")
        body.prop(operator, "axis_up")


@orientation_helper(axis_forward='Y', axis_up='Z')
class ExportMVR(Operator, ExportHelper):
    """Export My Virtual Rig"""

    bl_idname = "export_scene.mvr"
    bl_label = "Export MVR (.mvr)"
    bl_options = {"PRESET", "UNDO"}

    filename_ext = ".mvr"
    filter_glob: StringProperty(default="*.mvr", options={'HIDDEN'})

    collection: StringProperty(
        name="Source Collection",
        description="Export objects from this collection",
        default="",
    )
    scale_factor: FloatProperty(
        name="Scale",
        description="Scale factor for all objects",
        min=0.0001, max=10000.0,
        soft_min=0.001, soft_max=1000.0,
        default=1.0,
        subtype='FACTOR',
    )
    use_selection: BoolProperty(
        name="Selection",
        description="Export selected objects only",
        default=False,
    )
    use_apply_transform: BoolProperty(
        name="Apply Transform",
        description="Apply matrix transform",
        default=False,
    )
    use_images: BoolProperty(
        name="Images",
        description="Export material texture images",
        default=True,
    )
    use_collection: BoolProperty(
        name="Collection",
        description="Export active collection only",
        default=False,
    )
    use_fixtures: BoolProperty(
        name="Fixtures",
        description="Export fixtures of the scene",
        default=True,
    )
    use_targets: BoolProperty(
        name="Targets",
        description="Export target positions",
        default=True,
    )
    fixture_path: StringProperty(
        name="GDTF File Path",
        description="Export GDTF profiles from this directory",
        default="",
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        export_mvr_include(layout, self, context)
        export_mvr_transform(layout, self)

    def execute(self, context):
        if os.path.lexists(context.preferences.addons[__package__].preferences.profile_path):
            self.fixture_path = context.preferences.addons[__package__].preferences.profile_path
        keywords = self.as_keywords(ignore=("axis_forward", "axis_up", "filter_glob", "check_existing"))
        global_matrix = axis_conversion(to_forward=self.axis_forward, to_up=self.axis_up).to_4x4()
        keywords["global_matrix"] = global_matrix
        keywords["version"] = __version__

        return export_mvr.save(self, context, **keywords)


def export_mvr_include(layout, operator, context):
    header, body = layout.panel("MVR_export_include", default_closed=False)
    prefs = context.preferences.addons[__package__].preferences
    header.label(text="Include")
    if body:
        line = body.row(align=True)
        line.prop(operator, "use_images")
        line.label(text="", icon='OUTLINER_OB_IMAGE' if operator.use_images else 'IMAGE_DATA')
        line = body.row(align=True)
        line.prop(operator, "use_fixtures")
        line.label(text="", icon='OUTLINER_OB_LIGHT' if operator.use_fixtures else 'LIGHT')
        line = body.row(align=True)
        line.prop(operator, "use_selection")
        line.label(text="", icon='RESTRICT_SELECT_OFF' if operator.use_selection else 'RESTRICT_SELECT_ON')
        if context.space_data.type == 'FILE_BROWSER':
            line = body.row(align=True)
            line.prop(operator, "use_collection")
            line.label(text="", icon='OUTLINER_COLLECTION' if operator.use_collection else 'GROUP')
            line = body.row(align=True)
            line.enabled = (operator.use_fixtures == True)
            line.prop(operator, "fixture_path", text="GDTF Path", icon='FILE_FOLDER', placeholder=prefs.profile_path)
        else:
            line = body.row(align=True)
            line.enabled = (operator.use_fixtures == True)
            line.prop(prefs, "profile_path", text="GDTF Path", icon='FOLDER_REDIRECT', placeholder="//gdtf/")


def export_mvr_transform(layout, operator):
    header, body = layout.panel("MVR_export_transform", default_closed=False)
    header.label(text="Transform")
    if body:
        body.prop(operator, "scale_factor")
        line = body.row(align=True)
        line.enabled = (operator.use_fixtures == True)
        line.prop(operator, "use_targets")
        line.label(text="", icon='CON_STRETCHTO' if operator.use_targets else 'CON_TRACKTO')
        line = body.row(align=True)
        line.prop(operator, "use_apply_transform")
        line.label(text="", icon='MESH_CUBE' if operator.use_apply_transform else 'MOD_SOLIDIFY')
        body.prop(operator, "axis_forward")
        body.prop(operator, "axis_up")


class IO_FH_mvr(FileHandler):
    bl_idname = "IO_FH_MVR"
    bl_label = "MVR"
    bl_import_operator = "import_scene.mvr"
    bl_export_operator = "export_scene.mvr"
    bl_file_extensions = ".mvr"

    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


@orientation_helper(axis_forward='Y', axis_up='Z')
class ImportGDTF(Operator, ImportHelper):
    """Import General Device Type Format"""
    bl_idname = "import_scene.gdtf"
    bl_label = "Import GDTF (.gdtf)"
    bl_options = {'PRESET', 'UNDO'}

    filename_ext = ".gdtf"
    filter_glob: StringProperty(default="*.gdtf", options={'HIDDEN'})
    files: CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    directory: StringProperty(subtype='DIR_PATH')

    fixture_index: IntProperty(
        name="Index",
        description="Fixture start index",
        min=0, max=100000,
        soft_min=0, soft_max=100000,
        default=0,
    )
    fixture_count: IntProperty(
        name="Quantity",
        description="Fixture count",
        min=0, max=10000,
        soft_min=0, soft_max=10000,
        default=1,
    )
    fixture_mode: IntProperty(
        name="Mode",
        description="Fixture mode",
        min=1, max=1024,
        soft_min=1, soft_max=512,
        default=1,
    )
    gel_color: FloatVectorProperty(
        name="Color",
        description="Fixture gel color",
        min=0.0, max=1.0,
        soft_min=0.0, soft_max=1.0,
        default=[1.0, 1.0, 1.0],
        subtype='COLOR',
    )
    fixture_position: FloatVectorProperty(
        name="Position",
        description="Fixture position",
        min=-10000.0, max=10000.0,
        soft_min=-10000.0, soft_max=10000.0,
        default=[0.0, 0.0, 0.0],
        subtype='TRANSLATION',
    )
    align_objects: FloatProperty(
        name="Align",
        description="Align distance between objects",
        min=0.0, max=1000.0,
        soft_min=0.0, soft_max=1000.0,
        default=1.0,
        subtype='DISTANCE',
        unit='LENGTH'
    )
    align_axis: EnumProperty(
        name="Axis",
        items=(('X', "X Align", "Align to Axis X"),
               ('Y', "Y Align", "Align to Axis Y"),
               ('Z', "Z Align", "Align to Axis Z"),
               ),
        description="Axis for align objects",
        default='X',
    )
    scale_objects: FloatProperty(
        name="Scale",
        description="Scale factor for all objects",
        min=0.0, max=10000.0,
        soft_min=0.0, soft_max=10000.0,
        default=1.0,
        subtype='FACTOR'
    )
    use_collection: BoolProperty(
        name="Collection",
        description="Create a new collection",
        default=False,
    )
    use_targets: BoolProperty(
        name="Targets",
        description="Use constraints for targets",
        default=True,
    )
    use_beams: BoolProperty(
        name="Beams",
        description="Display Beams",
        default=True,
    )
    use_show_cone: BoolProperty(
        name="Show Cone",
        description="Show Beam Cones",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        import_gdtf_include(layout, self)
        import_gdtf_transform(layout, self)

    def execute(self, context):
        keywords = self.as_keywords(ignore=("fixture_position", "axis_forward", "axis_up", "filter_glob"))
        global_matrix = axis_conversion(from_forward=self.axis_forward, from_up=self.axis_up,).to_4x4()
        device_position = self.fixture_position if any(self.fixture_position) else None
        keywords["device_position"] = device_position
        keywords["global_matrix"] = global_matrix
        return import_gdtf.load(self, context, **keywords)

    def invoke(self, context, event):
        return self.invoke_popup(context)


def import_gdtf_include(layout, operator):
    header, body = layout.panel("GDTF_import_include", default_closed=False)
    header.label(text="Include")
    if body:
        line = body.row(align=True)
        line.prop(operator, "use_collection")
        line.label(text="", icon='OUTLINER_COLLECTION' if operator.use_collection else 'GROUP')
        body.prop(operator, "fixture_index")
        body.prop(operator, "fixture_count")
        body.prop(operator, "fixture_mode")
        body.prop(operator, "gel_color")
        line = layout.row(align=True)
        line.prop(operator, "use_beams")
        line.label(text="", icon='OUTLINER_OB_LIGHT' if operator.use_beams else 'LIGHT')
        line = layout.row(align=True)
        line.enabled = (operator.use_beams == True)
        line.prop(operator, "use_show_cone")
        line.label(text="", icon='LIGHT_SPOT' if operator.use_show_cone else 'LIGHT_HEMI')


def import_gdtf_transform(layout, operator):
    header, body = layout.panel("GDTF_import_transform", default_closed=False)
    header.label(text="Transform")
    if body:
        body.prop(operator, "fixture_position")
        body.prop(operator, "align_objects")
        body.prop(operator, "align_axis")
        body.prop(operator, "scale_objects")
        line = layout.row(align=True)
        line.prop(operator, "use_targets")
        line.label(text="", icon='CON_STRETCHTO' if operator.use_targets else 'CON_TRACKTO')
        body.prop(operator, "axis_forward")
        body.prop(operator, "axis_up")


class IO_FH_gdtf(FileHandler):
    bl_idname = "IO_FH_GDTF"
    bl_label = "GDTF"
    bl_import_operator = "import_scene.gdtf"
    bl_file_extensions = ".gdtf"

    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


def menu_func_import(self, context):
    self.layout.operator(ImportMVR.bl_idname, text="My Virtual Rig (.mvr)")
    self.layout.operator(ImportGDTF.bl_idname, text="General Device Type Format (.gdtf)")


def menu_func_export(self, context):
    self.layout.operator(ExportMVR.bl_idname, text="My Virtual Rig (.mvr)")


def register():
    bpy.utils.register_class(MVR_AddonPreferences)
    bpy.utils.register_class(ImportGDTF)
    bpy.utils.register_class(ImportMVR)
    bpy.utils.register_class(ExportMVR)
    bpy.utils.register_class(IO_FH_mvr)
    bpy.utils.register_class(IO_FH_gdtf)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.utils.unregister_class(IO_FH_mvr)
    bpy.utils.unregister_class(IO_FH_gdtf)
    bpy.utils.unregister_class(ExportMVR)
    bpy.utils.unregister_class(ImportMVR)
    bpy.utils.unregister_class(ImportGDTF)
    bpy.utils.unregister_class(MVR_AddonPreferences)


if __name__ == "__main__":
    register()
