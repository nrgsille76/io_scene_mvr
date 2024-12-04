# SPDX-FileCopyrightText: 2024 Sebastian Schrand
#
# SPDX-License-Identifier: GPL-2.0-or-later

__author__ = "Sebastian Sille <nrgsille@gmail.com>"
__version__ = "1.1.3"
__date__ = "2 Aug 2024"


import bpy
from bpy_extras.io_utils import (
    ImportHelper,
    orientation_helper,
    axis_conversion,
)
from bpy.props import (
    IntProperty,
    BoolProperty,
    EnumProperty,
    FloatProperty,
    StringProperty,
    CollectionProperty,
    FloatVectorProperty,
)

bl_info = {
    "name": "Import MVR & GDTF",
    "author": "Sebastian Sille",
    "version": (1, 1, 2),
    "blender": (4, 0, 0),
    "location": "File > Import",
    "description": "Import My Virtual Rig and General Device Type Format",
    "warning": "",
    "filepath_url": "",
    "category": "Import-Export",
}

if "bpy" in locals():
    import importlib
    if "ImportMVR" in locals():
        importlib.reload(import_max)
    if "ImportGDTF" in locals():
        importlib.reload(import_gdtf)


@orientation_helper(axis_forward='Y', axis_up='Z')
class ImportMVR(bpy.types.Operator, ImportHelper):
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
        min=0.0, max=10000.0,
        soft_min=0.0, soft_max=10000.0,
        default=1.0,
        subtype='FACTOR',
    )
    use_collection: BoolProperty(
        name="Collection",
        description="Create a new collection",
        default=False,
    )
    use_fixtures: BoolProperty(
        name="Fixtures",
        description="Import fixtures of the scene",
        default=True,
    )
    use_targets: BoolProperty(
        name="Targets",
        description="Use constraints for targets",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        import_mvr_include(layout, self)
        import_mvr_transform(layout, self)

    def execute(self, context):
        from . import import_mvr
        keywords = self.as_keywords(ignore=("axis_forward", "axis_up", "filter_glob"))
        global_matrix = axis_conversion(from_forward=self.axis_forward, from_up=self.axis_up,).to_4x4()
        keywords["global_matrix"] = global_matrix

        return import_mvr.load(self, context, **keywords)


def import_mvr_include(layout, operator):
    header, body = layout.panel("MVR_import_include", default_closed=False)
    header.label(text="Include")
    if body:
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_collection")
        layrow.label(text="", icon='OUTLINER_COLLECTION' if operator.use_collection else 'GROUP')
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_fixtures")
        layrow.label(text="", icon='OUTLINER_OB_LIGHT' if operator.use_fixtures else 'LIGHT')


def import_mvr_transform(layout, operator):
    header, body = layout.panel("MVR_import_transform", default_closed=False)
    header.label(text="Transform")
    if body:
        layout.prop(operator, "scale_objects")
        layrow = layout.row(align=True)
        layrow.enabled = (operator.use_fixtures == True)
        layrow.prop(operator, "use_targets")
        layrow.label(text="", icon='CON_STRETCHTO' if operator.use_targets else 'CON_TRACKTO')
        layout.prop(operator, "axis_forward")
        layout.prop(operator, "axis_up")


class IO_FH_mvr(bpy.types.FileHandler):
    bl_idname = "IO_FH_mvr"
    bl_label = "MVR"
    bl_import_operator = "import_scene.mvr"
    #bl_export_operator = "export_scene.mvr"
    bl_file_extensions = ".mvr"

    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


@orientation_helper(axis_forward='Y', axis_up='Z')
class ImportGDTF(bpy.types.Operator, ImportHelper):
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
        from . import import_gdtf
        keywords = self.as_keywords(ignore=("fixture_position", "axis_forward", "axis_up", "filter_glob"))
        global_matrix = axis_conversion(from_forward=self.axis_forward, from_up=self.axis_up,).to_4x4()
        device_position = self.fixture_position if any(self.fixture_position) else None
        keywords["device_position"] = device_position
        keywords["global_matrix"] = global_matrix

        return import_gdtf.load(self, context, **keywords)


def import_gdtf_include(layout, operator):
    header, body = layout.panel("GDTF_import_include", default_closed=False)
    header.label(text="Include")
    if body:
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_collection")
        layrow.label(text="", icon='OUTLINER_COLLECTION' if operator.use_collection else 'GROUP')
        layout.prop(operator, "fixture_index")
        layout.prop(operator, "fixture_count")
        layout.prop(operator, "gel_color")
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_beams")
        layrow.label(text="", icon='OUTLINER_OB_LIGHT' if operator.use_beams else 'LIGHT')
        layrow = layout.row(align=True)
        layrow.enabled = (operator.use_beams == True)
        layrow.prop(operator, "use_show_cone")
        layrow.label(text="", icon='LIGHT_SPOT' if operator.use_show_cone else 'LIGHT_HEMI')


def import_gdtf_transform(layout, operator):
    header, body = layout.panel("GDTF_import_transform", default_closed=False)
    header.label(text="Transform")
    if body:
        layout.prop(operator, "fixture_position")
        layout.prop(operator, "align_objects")
        layout.prop(operator, "align_axis")
        layout.prop(operator, "scale_objects")
        layrow = layout.row(align=True)
        layrow.prop(operator, "use_targets")
        layrow.label(text="", icon='CON_STRETCHTO' if operator.use_targets else 'CON_TRACKTO')
        layout.prop(operator, "axis_forward")
        layout.prop(operator, "axis_up")


class IO_FH_gdtf(bpy.types.FileHandler):
    bl_idname = "IO_FH_gdtf"
    bl_label = "GDTF"
    bl_import_operator = "import_scene.gdtf"
    bl_file_extensions = ".gdtf"

    @classmethod
    def poll_drop(cls, context):
        return poll_file_object_drop(context)


def menu_func(self, context):
    self.layout.operator(ImportMVR.bl_idname, text="My Virtual Rig (.mvr)")
    self.layout.operator(ImportGDTF.bl_idname, text="General Device Type Format (.gdtf)")


def register():
    bpy.utils.register_class(ImportMVR)
    bpy.utils.register_class(ImportGDTF)
    bpy.utils.register_class(IO_FH_mvr)
    bpy.utils.register_class(IO_FH_gdtf)
    bpy.types.TOPBAR_MT_file_import.append(menu_func)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func)
    bpy.utils.unregister_class(IO_FH_mvr)
    bpy.utils.unregister_class(IO_FH_gdtf)
    bpy.utils.unregister_class(ImportMVR)
    bpy.utils.unregister_class(ImportGDTF)


if __name__ == "__main__":
    register()
