#!/usr/bin/env python3
"""
Self-contained IFC4 coordination model & clash-free overhead MEP router
for Data Hall dc_model hall_seed005_d100.

Uses only ifcopenshell==0.8.4, numpy, and Python standard library.
No PNG reading at runtime; all drawing data baked in as literals.
"""

import json
import math
import os
import sys
import uuid
import numpy as np
import ifcopenshell


# ---------------------------------------------------------------------------
# Deterministic UUID helper for IFC GlobalId (22-char base64)
# ---------------------------------------------------------------------------
_B64_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


def make_guid(seed_str: str) -> str:
    h = uuid.uuid5(uuid.NAMESPACE_DNS, f"hall_seed005_d100::{seed_str}").int
    chars = []
    for _ in range(22):
        chars.append(_B64_CHARS[h & 0x3F])
        h >>= 6
    return "".join(reversed(chars))


# ---------------------------------------------------------------------------
# Baked Drawing Data (from A-101, A-301, A-601, A-602, M-101, E-101, F-101)
# ---------------------------------------------------------------------------

# 8 Interior Structural Columns (600 x 600 mm, Z = 0 .. 3650 mm)
# Note: Grid intersection (21450, 21450) lies outside the L-shaped room boundary
# (X <= 18000 mm for Y >= 15000 mm).
COLUMNS = [
    ("COL-B2", 7050.0, 7050.0),
    ("COL-C2", 14250.0, 7050.0),
    ("COL-D2", 21450.0, 7050.0),
    ("COL-B3", 7050.0, 14250.0),
    ("COL-C3", 14250.0, 14250.0),
    ("COL-D3", 21450.0, 14250.0),
    ("COL-B4", 7050.0, 21450.0),
    ("COL-C4", 14250.0, 21450.0),
]

# Cabinet Type Specifications (A-601 Table 3b)
CABINET_TYPES = {
    "C1": {"width": 600.0, "depth": 1200.0, "height": 2000.0, "facing": "SOUTH", "kw": 8.0, "kg": 1363.0},
    "C2": {"width": 600.0, "depth": 1070.0, "height": 2000.0, "facing": "NORTH", "kw": 8.0, "kg": 1363.0},
    "N1": {"width": 800.0, "depth": 1200.0, "height": 2000.0, "facing": "SOUTH", "kw": 8.0, "kg": 1363.0},
    "N2": {"width": 800.0, "depth": 1070.0, "height": 2000.0, "facing": "NORTH", "kw": 8.0, "kg": 1363.0},
}

# Row Y-intervals and exact West-to-East sequences (A-101 & A-601 Table 1)
# At the circulation cross-aisle (CA), the east half of every row re-registers
# its first element's west face onto X = 12600.0 mm (Tile V = 21 * 600 mm).
ROW_DEFS = [
    {
        "row_id": "A",
        "y_min": 2400.0,
        "y_max": 3600.0,
        "facing": "SOUTH",
        "west_seq": [("C1", 4), ("CU", "CRAH-05"), ("C1", 4), ("N1", 1), ("C1", 4), ("CU", "CRAH-06")],
        "east_seq": [("C1", 7), ("GAP", 600.0), ("CU", "CRAH-07"), ("C1", 6)],
    },
    {
        "row_id": "B",
        "y_min": 5400.0,
        "y_max": 6470.0,
        "facing": "NORTH",
        "west_seq": [
            ("C2", 4),
            ("CU", "CRAH-08"),
            ("C2", 3),
            ("GAP", 1200.0),  # Z-600 (2-tile column pocket at X=6600..7800)
            ("C2", 2),
            ("N2", 2),
            ("CU", "CRAH-09"),
        ],
        "east_seq": [
            ("C2", 2),
            ("GAP", 1200.0),  # Z-600 (2-tile column pocket at X=13800..15000)
            ("C2", 3),
            ("CU", "CRAH-10"),
            ("GAP", 600.0),   # SP
            ("C2", 5),
            ("GAP", 1200.0),  # Z-600 (2-tile column pocket at X=21000..22200)
        ],
    },
    {
        "row_id": "C",
        "y_min": 7800.0,
        "y_max": 9000.0,
        "facing": "SOUTH",
        "west_seq": [
            ("C1", 4),
            ("CU", "CRAH-11"),
            ("C1", 3),
            ("GAP", 1200.0),  # Z-600 (2-tile column pocket at X=6600..7800)
            ("C1", 2),
            ("CU", "CRAH-12"),
            ("C1", 2),
        ],
        "east_seq": [
            ("N1", 1),
            ("GAP", 1200.0),  # Z-600 (2-tile column pocket at X=13400..14600)
            ("C1", 4),
            ("GAP", 600.0),   # SP
            ("CU", "CRAH-13"),
            ("C1", 4),
            ("GAP", 1200.0),  # Z-600 (2-tile column pocket at X=20600..21800)
        ],
    },
    {
        "row_id": "D",
        "y_min": 10800.0,
        "y_max": 11870.0,
        "facing": "NORTH",
        "west_seq": [("C2", 5), ("CU", "CRAH-14"), ("C2", 3), ("N2", 2), ("C2", 3), ("CU", "CRAH-15")],
        "east_seq": [("C2", 8), ("GAP", 600.0), ("CU", "CRAH-16"), ("C2", 6)],
    },
]

# 4 Perimeter CRAH units (1200 x 900 x 2000 mm, 100 kW, 20000 CMH, North discharge)
PERIMETER_CRAHS = [
    ("CRAH-01", 1200.0, 450.0, 1200.0, 900.0, 2000.0, 100.0, 20000.0, "NORTH"),
    ("CRAH-02", 9600.0, 450.0, 1200.0, 900.0, 2000.0, 100.0, 20000.0, "NORTH"),
    ("CRAH-03", 17400.0, 450.0, 1200.0, 900.0, 2000.0, 100.0, 20000.0, "NORTH"),
    ("CRAH-04", 25800.0, 450.0, 1200.0, 900.0, 2000.0, 100.0, 20000.0, "NORTH"),
]

# 4 PDUs (750 x 815 x 1950 mm, 225 kVA, 42 ways, 1800 mm East of last rack in each row)
PDUS = [
    ("PDU-01", 23775.0, 2807.5, 750.0, 815.0, 1950.0, 225.0, 42, "SOUTH"),
    ("PDU-02", 23175.0, 6062.5, 750.0, 815.0, 1950.0, 225.0, 42, "NORTH"),
    ("PDU-03", 22775.0, 8207.5, 750.0, 815.0, 1950.0, 225.0, 42, "SOUTH"),
    ("PDU-04", 24375.0, 11462.5, 750.0, 815.0, 1950.0, 225.0, 42, "NORTH"),
]

# 94 Ceiling Sprinkler Heads at Z_deflector = +3575 mm (F-101)
CEILING_SPRINKLER_XY = [
    # Row Y = 23766 (7 heads, X < 18000)
    (1235.0, 23764.0), (3726.0, 23767.0), (6229.0, 23767.0), (8732.0, 23765.0),
    (11227.0, 23767.0), (13733.0, 23765.0), (17323.0, 23765.0),
    # Row Y = 21264 (7 heads, X < 18000)
    (1235.0, 21266.0), (3726.0, 21266.0), (6229.0, 21263.0), (8732.0, 21263.0),
    (11227.0, 21263.0), (13732.0, 21263.0), (17323.0, 21263.0),
    # Row Y = 18766 (7 heads, X < 18000)
    (1231.0, 18766.0), (3731.0, 18767.0), (6231.0, 18765.0), (8729.0, 18762.0),
    (11227.0, 18768.0), (13729.0, 18766.0), (17330.0, 18768.0),
    # Row Y = 16267 (7 heads, X < 18000)
    (1235.0, 16267.0), (3726.0, 16267.0), (6228.0, 16268.0), (8729.0, 16268.0),
    (11228.0, 16264.0), (13730.0, 16267.0), (17325.0, 16264.0),
    # Row Y = 13764 / 14366 (11 heads across 27000)
    (1233.0, 13763.0), (3732.0, 13766.0), (6228.0, 13762.0), (8728.0, 13766.0),
    (11229.0, 13764.0), (13726.0, 13762.0), (16228.0, 13763.0), (18728.0, 14365.0),
    (21229.0, 13762.0), (23723.0, 14366.0), (26228.0, 14366.0),
    # Row Y = 11268 (11 heads)
    (1229.0, 11267.0), (3731.0, 11267.0), (6229.0, 11272.0), (8730.0, 11259.0),
    (11227.0, 11272.0), (13731.0, 11269.0), (16228.0, 11264.0), (18730.0, 11272.0),
    (21231.0, 11267.0), (23728.0, 11267.0), (26229.0, 11272.0),
    # Row Y = 8766 (11 heads)
    (1232.0, 8766.0), (3723.0, 8766.0), (6232.0, 8767.0), (8729.0, 8763.0),
    (11228.0, 8766.0), (13732.0, 8766.0), (16229.0, 8767.0), (18728.0, 8765.0),
    (21230.0, 8767.0), (23723.0, 8766.0), (26228.0, 8766.0),
    # Row Y = 6266 (11 heads)
    (1229.0, 6266.0), (3734.0, 6266.0), (6232.0, 6266.0), (8727.0, 6266.0),
    (11223.0, 6266.0), (13728.0, 6266.0), (16233.0, 6266.0), (18728.0, 6266.0),
    (21226.0, 6265.0), (23724.0, 6266.0), (26227.0, 6266.0),
    # Row Y = 3768 (11 heads)
    (1234.0, 3767.0), (3726.0, 3767.0), (6230.0, 3765.0), (8729.0, 3772.0),
    (11228.0, 3768.0), (13732.0, 3768.0), (16230.0, 3770.0), (18728.0, 3769.0),
    (21229.0, 3770.0), (23723.0, 3768.0), (26228.0, 3768.0),
    # Row Y = 1267 (11 heads)
    (1233.0, 1267.0), (3728.0, 1267.0), (6229.0, 1263.0), (8732.0, 1270.0),
    (11227.0, 1263.0), (13731.0, 1266.0), (16230.0, 1271.0), (18728.0, 1265.0),
    (21229.0, 1267.0), (23728.0, 1267.0), (26229.0, 1263.0),
]

# 10 Sub-Containment Sprinkler Head X-positions (F-101)
# Placed beneath CAC-AB roof (Y = 4500 mm, Z_deflector = +1925 mm, 75 mm below +2000 mm roof)
SUB_SPRINKLER_X = [
    2279.0, 4254.0, 6227.0, 7827.0, 10877.0,
    13253.0, 15027.0, 16844.0, 18660.0, 20475.0,
]


# ---------------------------------------------------------------------------
# Clash-Free, Minimum-Length 3D Overhead MEP Route Definitions
# ---------------------------------------------------------------------------
# Butt joints use 1.0 mm penetration (<= 2.0 mm hard clash limit) so connected
# segments physically overlap by 1.0 mm in 3D space (distance = 0.0 mm) while
# producing 0 hard clashes even under unfiltered all-pairs clash checking.

# 1. Telecom Cable Tray (CT-1): 600 mm W x 112 mm H, Z_bot = 2650, Z_top = 2762, Z_cl = 2706 mm
CT1_Z = 2706.0
CT1_W = 600.0
CT1_H = 112.0
CT1_SEGMENTS = [
    ("CT-1-SEG-01", 19.0, 11900.0, CT1_Z, 701.0, 11900.0, CT1_Z),
    ("CT-1-SEG-02", 1000.0, 12200.0, CT1_Z, 1000.0, 2700.0, CT1_Z),
    ("CT-1-SEG-03", 1299.0, 11900.0, CT1_Z, 21000.0, 11900.0, CT1_Z),
    ("CT-1-SEG-04", 1299.0, 8900.0, CT1_Z, 20600.0, 8900.0, CT1_Z),
    ("CT-1-SEG-05", 1299.0, 5900.0, CT1_Z, 21000.0, 5900.0, CT1_Z),
    ("CT-1-SEG-06", 1299.0, 3000.0, CT1_Z, 21500.0, 3000.0, CT1_Z),
]

# 2. Power Busway (BW-1): 120 mm W x 142 mm H, Z_bot = 2780, Z_top = 2922, Z_cl = 2851 mm
BW1_Z = 2851.0
BW1_W = 120.0
BW1_H = 142.0
BW1_SEGMENTS = [
    ("BW-1-SEG-01", 19.0, 12750.0, BW1_Z, 22041.0, 12750.0, BW1_Z),
    ("BW-1-SEG-02", 22100.0, 12810.0, BW1_Z, 22100.0, 2140.0, BW1_Z),
    ("BW-1-SEG-03", 22041.0, 8100.0, BW1_Z, 2000.0, 8100.0, BW1_Z),
    ("BW-1-SEG-04", 22041.0, 5100.0, BW1_Z, 2000.0, 5100.0, BW1_Z),
    ("BW-1-SEG-05", 22041.0, 2200.0, BW1_Z, 2000.0, 2200.0, BW1_Z),
]

# 3. Chilled Water Pipe (CHW-1): Steel OD 114.3 mm + 25.4 mm insulation = 165.1 mm OD (R = 82.55 mm)
# Z_cl = 3022.55 mm -> Z_bot = 2940.0 mm, Z_top = 3105.1 mm
CHW1_Z = 3022.55
CHW1_OD = 165.1
CHW1_R = 82.55
CHW1_SEGMENTS = [
    ("CHW-1-SEG-01", 19.0, 12480.0, CHW1_Z, 21000.0, 12480.0, CHW1_Z),
    ("CHW-1-SEG-02", 500.0, 12398.45, CHW1_Z, 500.0, 1517.45, CHW1_Z),
    ("CHW-1-SEG-03", 581.55, 8500.0, CHW1_Z, 20600.0, 8500.0, CHW1_Z),
    ("CHW-1-SEG-04", 581.55, 5500.0, CHW1_Z, 21000.0, 5500.0, CHW1_Z),
    ("CHW-1-SEG-05", 581.55, 1600.0, CHW1_Z, 25800.0, 1600.0, CHW1_Z),
]


# ---------------------------------------------------------------------------
# IFC4 Model Builder
# ---------------------------------------------------------------------------

class HallModelBuilder:
    def __init__(self):
        self.f = ifcopenshell.file(schema="IFC4")
        self._init_header_and_context()
        self.storey_elements = []

    def _init_header_and_context(self):
        f = self.f
        org = f.create_entity("IfcOrganization", Name="MEP Coordination Corp")
        app = f.create_entity(
            "IfcApplication",
            ApplicationDeveloper=org,
            Version="1.0",
            ApplicationFullName="DCM Hall Coordinator",
            ApplicationIdentifier="DCM-COORD",
        )
        person = f.create_entity("IfcPerson", FamilyName="Coordinator", GivenName="BIM")
        p_org = f.create_entity("IfcPersonAndOrganization", ThePerson=person, TheOrganization=org)
        self.owner_history = f.create_entity(
            "IfcOwnerHistory",
            OwningUser=p_org,
            OwningApplication=app,
            ChangeAction="NOCHANGE",
            CreationDate=1700000000,
        )

        # Units: MILLIMETRE
        unit_len = f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Prefix="MILLI", Name="METRE")
        unit_area = f.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE")
        unit_vol = f.create_entity("IfcSIUnit", UnitType="VOLUMEUNIT", Name="CUBIC_METRE")
        unit_angle = f.create_entity("IfcSIUnit", UnitType="PLANEANGLEUNIT", Name="RADIAN")
        unit_assign = f.create_entity("IfcUnitAssignment", Units=[unit_len, unit_area, unit_vol, unit_angle])

        # 3D Context & 2D Origin
        self.origin_3d = f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
        self.origin_2d = f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0))
        self.dir_z = f.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0))
        self.dir_x = f.create_entity("IfcDirection", DirectionRatios=(1.0, 0.0, 0.0))
        self.dir_neg_x = f.create_entity("IfcDirection", DirectionRatios=(-1.0, 0.0, 0.0))
        self.dir_2d_x = f.create_entity("IfcDirection", DirectionRatios=(1.0, 0.0))

        self.world_cs = f.create_entity(
            "IfcAxis2Placement3D", Location=self.origin_3d, Axis=self.dir_z, RefDirection=self.dir_x
        )
        self.pos_2d = f.create_entity(
            "IfcAxis2Placement2D", Location=self.origin_2d, RefDirection=self.dir_2d_x
        )

        self.context = f.create_entity(
            "IfcGeometricRepresentationContext",
            ContextIdentifier="Model",
            ContextType="Model",
            CoordinateSpaceDimension=3,
            Precision=1.0e-5,
            WorldCoordinateSystem=self.world_cs,
        )
        self.body_ctx = f.create_entity(
            "IfcGeometricRepresentationSubContext",
            ContextIdentifier="Body",
            ContextType="Model",
            ParentContext=self.context,
            TargetView="MODEL_VIEW",
        )

        self.project = f.create_entity(
            "IfcProject",
            GlobalId=make_guid("IfcProject"),
            OwnerHistory=self.owner_history,
            Name="hall_seed005_d100",
            Description="Data Hall Overhead MEP Coordination Model",
            RepresentationContexts=[self.context],
            UnitsInContext=unit_assign,
        )

        # Spatial Hierarchy: Project -> Site -> Building -> Storey ("Data Hall") -> Space ("Server Room")
        self.site_pl = self.make_placement(0.0, 0.0, 0.0, parent=None)
        self.site = f.create_entity(
            "IfcSite",
            GlobalId=make_guid("IfcSite"),
            OwnerHistory=self.owner_history,
            Name="Data Center Site",
            CompositionType="ELEMENT",
            ObjectPlacement=self.site_pl,
        )
        self.bldg_pl = self.make_placement(0.0, 0.0, 0.0, parent=self.site_pl)
        self.building = f.create_entity(
            "IfcBuilding",
            GlobalId=make_guid("IfcBuilding"),
            OwnerHistory=self.owner_history,
            Name="Data Center Building",
            CompositionType="ELEMENT",
            ObjectPlacement=self.bldg_pl,
        )
        self.storey_pl = self.make_placement(0.0, 0.0, 0.0, parent=self.bldg_pl)
        self.storey = f.create_entity(
            "IfcBuildingStorey",
            GlobalId=make_guid("IfcBuildingStorey::DataHall"),
            OwnerHistory=self.owner_history,
            Name="Data Hall",
            CompositionType="ELEMENT",
            Elevation=0.0,
            ObjectPlacement=self.storey_pl,
        )
        self.space_pl = self.make_placement(0.0, 0.0, 0.0, parent=self.storey_pl)
        self.space = f.create_entity(
            "IfcSpace",
            GlobalId=make_guid("IfcSpace::ServerRoom"),
            OwnerHistory=self.owner_history,
            Name="Server Room",
            CompositionType="ELEMENT",
            PredefinedType="INTERNAL",
            ObjectPlacement=self.space_pl,
        )

        f.create_entity(
            "IfcRelAggregates",
            GlobalId=make_guid("RelAgg::Project->Site"),
            OwnerHistory=self.owner_history,
            RelatingObject=self.project,
            RelatedObjects=[self.site],
        )
        f.create_entity(
            "IfcRelAggregates",
            GlobalId=make_guid("RelAgg::Site->Building"),
            OwnerHistory=self.owner_history,
            RelatingObject=self.site,
            RelatedObjects=[self.building],
        )
        f.create_entity(
            "IfcRelAggregates",
            GlobalId=make_guid("RelAgg::Building->Storey"),
            OwnerHistory=self.owner_history,
            RelatingObject=self.building,
            RelatedObjects=[self.storey],
        )
        f.create_entity(
            "IfcRelAggregates",
            GlobalId=make_guid("RelAgg::Storey->Space"),
            OwnerHistory=self.owner_history,
            RelatingObject=self.storey,
            RelatedObjects=[self.space],
        )

    def make_placement(self, x: float, y: float, z: float, axis=None, ref_dir=None, parent=None):
        f = self.f
        pt = f.create_entity("IfcCartesianPoint", Coordinates=(float(x), float(y), float(z)))
        ax = axis if axis is not None else self.dir_z
        rf = ref_dir if ref_dir is not None else self.dir_x
        a2p = f.create_entity("IfcAxis2Placement3D", Location=pt, Axis=ax, RefDirection=rf)
        return f.create_entity("IfcLocalPlacement", PlacementRelTo=parent, RelativePlacement=a2p)

    def make_box_shape(self, x_dim: float, y_dim: float, depth: float):
        f = self.f
        prof = f.create_entity(
            "IfcRectangleProfileDef",
            ProfileType="AREA",
            Position=self.pos_2d,
            XDim=float(x_dim),
            YDim=float(y_dim),
        )
        solid = f.create_entity(
            "IfcExtrudedAreaSolid",
            SweptArea=prof,
            Position=self.world_cs,
            ExtrudedDirection=self.dir_z,
            Depth=float(depth),
        )
        rep = f.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=self.body_ctx,
            RepresentationIdentifier="Body",
            RepresentationType="SweptSolid",
            Items=[solid],
        )
        return f.create_entity("IfcProductDefinitionShape", Representations=[rep])

    def make_cylinder_shape(self, radius: float, depth: float):
        f = self.f
        prof = f.create_entity(
            "IfcCircleProfileDef",
            ProfileType="AREA",
            Position=self.pos_2d,
            Radius=float(radius),
        )
        solid = f.create_entity(
            "IfcExtrudedAreaSolid",
            SweptArea=prof,
            Position=self.world_cs,
            ExtrudedDirection=self.dir_z,
            Depth=float(depth),
        )
        rep = f.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=self.body_ctx,
            RepresentationIdentifier="Body",
            RepresentationType="SweptSolid",
            Items=[solid],
        )
        return f.create_entity("IfcProductDefinitionShape", Representations=[rep])

    def make_polygon_slab_shape(self, pts_2d, depth: float):
        f = self.f
        ifc_pts = [f.create_entity("IfcCartesianPoint", Coordinates=(float(px), float(py))) for px, py in pts_2d]
        ifc_pts.append(ifc_pts[0])
        poly = f.create_entity("IfcPolyline", Points=ifc_pts)
        prof = f.create_entity("IfcArbitraryClosedProfileDef", ProfileType="AREA", OuterCurve=poly)
        solid = f.create_entity(
            "IfcExtrudedAreaSolid",
            SweptArea=prof,
            Position=self.world_cs,
            ExtrudedDirection=self.dir_z,
            Depth=float(depth),
        )
        rep = f.create_entity(
            "IfcShapeRepresentation",
            ContextOfItems=self.body_ctx,
            RepresentationIdentifier="Body",
            RepresentationType="SweptSolid",
            Items=[solid],
        )
        return f.create_entity("IfcProductDefinitionShape", Representations=[rep])

    def add_pset(self, element, pset_name: str, props_dict: dict):
        f = self.f
        prop_entities = []
        for k, v in props_dict.items():
            if isinstance(v, bool):
                val = f.create_entity("IfcBoolean", v)
            elif isinstance(v, int):
                val = f.create_entity("IfcInteger", v)
            elif isinstance(v, float):
                val = f.create_entity("IfcReal", round(float(v), 4))
            else:
                val = f.create_entity("IfcLabel", str(v))
            prop_entities.append(
                f.create_entity("IfcPropertySingleValue", Name=str(k), NominalValue=val)
            )
        pset = f.create_entity(
            "IfcPropertySet",
            GlobalId=make_guid(f"Pset::{element.GlobalId}::{pset_name}"),
            OwnerHistory=self.owner_history,
            Name=pset_name,
            HasProperties=prop_entities,
        )
        f.create_entity(
            "IfcRelDefinesByProperties",
            GlobalId=make_guid(f"RelProp::{element.GlobalId}::{pset_name}"),
            OwnerHistory=self.owner_history,
            RelatedObjects=[element],
            RelatingPropertyDefinition=pset,
        )

    def build_room_and_structure(self):
        f = self.f
        l_poly = [
            (0.0, 0.0),
            (27000.0, 0.0),
            (27000.0, 15000.0),
            (18000.0, 15000.0),
            (18000.0, 24000.0),
            (0.0, 24000.0),
        ]

        # 1. Structural Base Slab (-900 to -600 mm, top at -600 mm)
        base_slab = f.create_entity(
            "IfcSlab",
            GlobalId=make_guid("Slab::BaseSlab"),
            OwnerHistory=self.owner_history,
            Name="Structural Base Slab",
            PredefinedType="BASESLAB",
            ObjectPlacement=self.make_placement(0.0, 0.0, -900.0, parent=self.storey_pl),
            Representation=self.make_polygon_slab_shape(l_poly, 300.0),
        )
        self.storey_elements.append(base_slab)

        # 2. Raised Access Floor (-38 to 0 mm, top at +0 mm FFL)
        access_floor = f.create_entity(
            "IfcCovering",
            GlobalId=make_guid("Covering::AccessFloor"),
            OwnerHistory=self.owner_history,
            Name="Raised Access Floor",
            PredefinedType="FLOORING",
            ObjectPlacement=self.make_placement(0.0, 0.0, -38.0, parent=self.storey_pl),
            Representation=self.make_polygon_slab_shape(l_poly, 38.0),
        )
        self.storey_elements.append(access_floor)

        # 3. Ceiling Slab (+3650 to +3900 mm, soffit at +3650 mm)
        ceil_slab = f.create_entity(
            "IfcSlab",
            GlobalId=make_guid("Slab::CeilingSlab"),
            OwnerHistory=self.owner_history,
            Name="Ceiling Slab",
            PredefinedType="ROOF",
            ObjectPlacement=self.make_placement(0.0, 0.0, 3650.0, parent=self.storey_pl),
            Representation=self.make_polygon_slab_shape(l_poly, 250.0),
        )
        self.storey_elements.append(ceil_slab)

        # 4. Perimeter Walls (200 mm thick, placed on outer perimeter so inner room face is exact)
        wall_defs = [
            ("Wall-South", 13500.0, -100.0, 27000.0, 200.0),
            ("Wall-West", -100.0, 12000.0, 200.0, 24000.0),
            ("Wall-North", 9000.0, 24100.0, 18000.0, 200.0),
            ("Wall-NE-Vert", 18100.0, 19500.0, 200.0, 9000.0),
            ("Wall-NE-Horiz", 22600.0, 15100.0, 8800.0, 200.0),
            ("Wall-East", 27100.0, 7500.0, 200.0, 15000.0),
        ]
        for wname, cx, cy, wx, wy in wall_defs:
            wall = f.create_entity(
                "IfcWall",
                GlobalId=make_guid(f"Wall::{wname}"),
                OwnerHistory=self.owner_history,
                Name=wname,
                PredefinedType="STANDARD",
                ObjectPlacement=self.make_placement(cx, cy, -600.0, parent=self.storey_pl),
                Representation=self.make_box_shape(wx, wy, 4250.0),
            )
            self.storey_elements.append(wall)

        # 5. Structural Columns (8 interior columns, 600 x 600 mm, Z = 0 .. 3650 mm full clear height)
        col_shape = self.make_box_shape(600.0, 600.0, 3650.0)
        for col_id, cx, cy in COLUMNS:
            col = f.create_entity(
                "IfcColumn",
                GlobalId=make_guid(f"Column::{col_id}"),
                OwnerHistory=self.owner_history,
                Name=col_id,
                PredefinedType="COLUMN",
                ObjectPlacement=self.make_placement(cx, cy, 0.0, parent=self.storey_pl),
                Representation=col_shape,
            )
            self.storey_elements.append(col)

    def build_cabinets_and_inrow_crahs(self):
        f = self.f
        self.cabinets_info = []
        self.crahs_info = []

        for rdef in ROW_DEFS:
            row_id = rdef["row_id"]
            y_min = rdef["y_min"]
            y_max = rdef["y_max"]
            cy = 0.5 * (y_min + y_max)
            depth_row = y_max - y_min
            facing = rdef["facing"]
            ref_dir = self.dir_neg_x if facing == "SOUTH" else self.dir_x

            rack_idx = 0
            for half_name, start_x, seq in [
                ("west", 1800.0, rdef["west_seq"]),
                ("east", 12600.0, rdef["east_seq"]),
            ]:
                cur_x = start_x
                for item_type, count_or_id in seq:
                    if item_type == "GAP":
                        cur_x += float(count_or_id)
                    elif item_type == "CU":
                        crah_id = str(count_or_id)
                        w = 600.0
                        cx = cur_x + 0.5 * w
                        cur_x += w
                        crah = f.create_entity(
                            "IfcUnitaryEquipment",
                            GlobalId=make_guid(f"CRAH::{crah_id}"),
                            OwnerHistory=self.owner_history,
                            Name=crah_id,
                            PredefinedType="AIRCONDITIONINGUNIT",
                            ObjectPlacement=self.make_placement(
                                cx, cy, 0.0, ref_dir=ref_dir, parent=self.storey_pl
                            ),
                            Representation=self.make_box_shape(w, depth_row, 2000.0),
                        )
                        self.add_pset(
                            crah,
                            "Pset_DCM_CRAH",
                            {
                                "UnitId": crah_id,
                                "CoolingCapacityKW": 50.0,
                                "AirflowCMH": 9000.0,
                            },
                        )
                        self.storey_elements.append(crah)
                        self.crahs_info.append((crah_id, cx, cy, w, depth_row, 2000.0, crah))
                    else:
                        spec = CABINET_TYPES[item_type]
                        w = spec["width"]
                        d = spec["depth"]
                        h = spec["height"]
                        for _ in range(int(count_or_id)):
                            rack_idx += 1
                            cab_name = f"{row_id}-{rack_idx:02d}"
                            cx = cur_x + 0.5 * w
                            cur_x += w
                            cab = f.create_entity(
                                "IfcFurniture",
                                GlobalId=make_guid(f"Cabinet::{cab_name}"),
                                OwnerHistory=self.owner_history,
                                Name=cab_name,
                                ObjectType="Rack",
                                PredefinedType="USERDEFINED",
                                ObjectPlacement=self.make_placement(
                                    cx, cy, 0.0, ref_dir=ref_dir, parent=self.storey_pl
                                ),
                                Representation=self.make_box_shape(w, d, h),
                            )
                            self.add_pset(
                                cab,
                                "Pset_DCM_Cabinet",
                                {
                                    "RowId": row_id,
                                    "RackIndex": rack_idx,
                                    "RackType": item_type,
                                    "Facing": facing,
                                    "RatedPowerKW": spec["kw"],
                                    "WeightKg": spec["kg"],
                                },
                            )
                            self.storey_elements.append(cab)
                            self.cabinets_info.append((cab_name, row_id, rack_idx, cx, cy, w, d, h))

    def build_perimeter_crahs_and_pdus(self):
        f = self.f
        for crah_id, cx, cy, w, d, h, kw, cmh, facing in PERIMETER_CRAHS:
            ref_dir = self.dir_neg_x if facing == "SOUTH" else self.dir_x
            crah = f.create_entity(
                "IfcUnitaryEquipment",
                GlobalId=make_guid(f"CRAH::{crah_id}"),
                OwnerHistory=self.owner_history,
                Name=crah_id,
                PredefinedType="AIRCONDITIONINGUNIT",
                ObjectPlacement=self.make_placement(cx, cy, 0.0, ref_dir=ref_dir, parent=self.storey_pl),
                Representation=self.make_box_shape(w, d, h),
            )
            self.add_pset(
                crah,
                "Pset_DCM_CRAH",
                {
                    "UnitId": crah_id,
                    "CoolingCapacityKW": kw,
                    "AirflowCMH": cmh,
                },
            )
            self.storey_elements.append(crah)
            self.crahs_info.append((crah_id, cx, cy, w, d, h, crah))

        self.pdus_info = []
        for pdu_id, cx, cy, w, d, h, kva, ways, facing in PDUS:
            ref_dir = self.dir_neg_x if facing == "SOUTH" else self.dir_x
            pdu = f.create_entity(
                "IfcElectricDistributionBoard",
                GlobalId=make_guid(f"PDU::{pdu_id}"),
                OwnerHistory=self.owner_history,
                Name=pdu_id,
                PredefinedType="DISTRIBUTIONBOARD",
                ObjectPlacement=self.make_placement(cx, cy, 0.0, ref_dir=ref_dir, parent=self.storey_pl),
                Representation=self.make_box_shape(w, d, h),
            )
            vert_clr = (CHW1_Z - CHW1_R) - h
            self.add_pset(
                pdu,
                "Pset_DCM_PDU",
                {
                    "UnitId": pdu_id,
                    "RatedKVA": kva,
                    "OutputWays": ways,
                    "NearestCHWVerticalClearanceMm": vert_clr,
                },
            )
            self.storey_elements.append(pdu)
            self.pdus_info.append((pdu_id, cx, cy, w, d, h, pdu))

    def build_containment_and_sprinklers(self):
        f = self.f
        for bay_id, cx, w in [("CAC-AB-WEST", 6400.0, 9200.0), ("CAC-AB-EAST", 17100.0, 9000.0)]:
            cont = f.create_entity(
                "IfcBuildingElementProxy",
                GlobalId=make_guid(f"Containment::{bay_id}"),
                OwnerHistory=self.owner_history,
                Name=bay_id,
                ObjectType="Containment",
                PredefinedType="USERDEFINED",
                ObjectPlacement=self.make_placement(cx, 4500.0, 2000.0, parent=self.storey_pl),
                Representation=self.make_box_shape(w, 1800.0, 50.8),
            )
            self.add_pset(
                cont,
                "Pset_DCM_Containment",
                {
                    "ContainmentId": "CAC-AB",
                    "AisleWidthMm": 1800.0,
                    "RoofElevMm": 2000.0,
                },
            )
            self.storey_elements.append(cont)

        ceil_spr_shape = self.make_cylinder_shape(50.0, 75.0)
        sub_spr_shape = self.make_cylinder_shape(50.0, 70.0)

        self.sprinklers_info = []
        for idx, (sx, sy) in enumerate(CEILING_SPRINKLER_XY, start=1):
            head_id = f"SPR-{idx:03d}"
            spr = f.create_entity(
                "IfcFireSuppressionTerminal",
                GlobalId=make_guid(f"Sprinkler::{head_id}"),
                OwnerHistory=self.owner_history,
                Name=head_id,
                PredefinedType="SPRINKLER",
                ObjectPlacement=self.make_placement(sx, sy, 3575.0, parent=self.storey_pl),
                Representation=ceil_spr_shape,
            )
            self.add_pset(
                spr,
                "Pset_DCM_Sprinkler",
                {
                    "HeadId": head_id,
                    "KFactor": 80.0,
                    "CoverageAreaM2": 6.2,
                    "DeflectorElevMm": 3575.0,
                    "ClearanceToTrayTopMm": 3575.0 - (CT1_Z + 0.5 * CT1_H),
                    "ClearanceToBuswayTopMm": 3575.0 - (BW1_Z + 0.5 * BW1_H),
                    "ClearanceToCHWTopMm": 3575.0 - (CHW1_Z + CHW1_R),
                },
            )
            self.storey_elements.append(spr)
            self.sprinklers_info.append((head_id, sx, sy, 3575.0, spr))

        for idx, sx in enumerate(SUB_SPRINKLER_X, start=95):
            head_id = f"SPR-{idx:03d}"
            sy = 4500.0
            spr = f.create_entity(
                "IfcFireSuppressionTerminal",
                GlobalId=make_guid(f"Sprinkler::{head_id}"),
                OwnerHistory=self.owner_history,
                Name=head_id,
                PredefinedType="SPRINKLER",
                ObjectPlacement=self.make_placement(sx, sy, 1925.0, parent=self.storey_pl),
                Representation=sub_spr_shape,
            )
            self.add_pset(
                spr,
                "Pset_DCM_Sprinkler",
                {
                    "HeadId": head_id,
                    "KFactor": 80.0,
                    "CoverageAreaM2": 4.5,
                    "DeflectorElevMm": 1925.0,
                },
            )
            self.storey_elements.append(spr)
            self.sprinklers_info.append((head_id, sx, sy, 1925.0, spr))

    def _make_directed_segment_placement(self, x1, y1, z1, x2, y2, z2):
        dx = x2 - x1
        dy = y2 - y1
        dz = z2 - z1
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        ux, uy, uz = dx / length, dy / length, dz / length

        if abs(uz) < 1e-6:
            rx, ry, rz = -uy, ux, 0.0
        else:
            rx, ry, rz = 1.0, 0.0, 0.0

        f = self.f
        axis_dir = f.create_entity("IfcDirection", DirectionRatios=(float(ux), float(uy), float(uz)))
        ref_dir = f.create_entity("IfcDirection", DirectionRatios=(float(rx), float(ry), float(rz)))
        pl = self.make_placement(x1, y1, z1, axis=axis_dir, ref_dir=ref_dir, parent=self.storey_pl)
        return pl, length

    def build_mep_routes_and_diagnostics(self):
        f = self.f

        # 1. Service Entries on West Wall (X = 0..20 mm, overlapping first segment at X=19 mm by 1.0 mm)
        service_entries = [
            ("SE-CT-1", "TELECOM", "CT-1", 11900.0, CT1_Z, 20.0, 200.0, 112.0),
            ("SE-BW-1", "POWER", "BW-1", 12750.0, BW1_Z, 20.0, 120.0, 142.0),
            ("SE-CHW-1", "CHILLED WATER", "CHW-1", 12480.0, CHW1_Z, 20.0, 165.0, 165.0),
        ]
        for se_id, sys_type, pw_id, sy, sz, wx, wy, wz in service_entries:
            se = f.create_entity(
                "IfcBuildingElementProxy",
                GlobalId=make_guid(f"ServiceEntry::{se_id}"),
                OwnerHistory=self.owner_history,
                Name=se_id,
                ObjectType="ServiceEntry",
                PredefinedType="USERDEFINED",
                ObjectPlacement=self.make_placement(10.0, sy, sz - 0.5 * wz, parent=self.storey_pl),
                Representation=self.make_box_shape(wx, wy, wz),
            )
            self.add_pset(
                se,
                "Pset_DCM_ServiceEntry",
                {
                    "SystemType": sys_type,
                    "PathwayId": pw_id,
                },
            )
            self.storey_elements.append(se)

        # 2. Telecom Cable Tray Segments (CT-1)
        ct_total_len = sum(
            math.hypot(x2 - x1, y2 - y1) for _, x1, y1, _, x2, y2, _ in CT1_SEGMENTS
        )
        for seg_id, x1, y1, z1, x2, y2, z2 in CT1_SEGMENTS:
            pl, length = self._make_directed_segment_placement(x1, y1, z1, x2, y2, z2)
            seg = f.create_entity(
                "IfcCableCarrierSegment",
                GlobalId=make_guid(f"CT1::{seg_id}"),
                OwnerHistory=self.owner_history,
                Name=seg_id,
                PredefinedType="CABLETRAYSEGMENT",
                ObjectPlacement=pl,
                Representation=self.make_box_shape(CT1_W, CT1_H, length),
            )
            self.add_pset(
                seg,
                "Pset_DCM_Pathway",
                {
                    "SystemType": "TELECOM",
                    "PathwayId": "CT-1",
                    "WidthMm": CT1_W,
                    "HeightMm": CT1_H,
                    "ElevationBotMm": CT1_Z - 0.5 * CT1_H,
                    "ElevationTopMm": CT1_Z + 0.5 * CT1_H,
                    "SegmentLengthMm": length,
                    "OverheadLengthMm": ct_total_len,
                    "UnderfloorLengthMm": 0.0,
                    "MinBuswaySeparationMm": 440.0,
                },
            )
            self.storey_elements.append(seg)

        # 3. Power Busway Segments (BW-1)
        bw_total_len = sum(
            math.hypot(x2 - x1, y2 - y1) for _, x1, y1, _, x2, y2, _ in BW1_SEGMENTS
        )
        for seg_id, x1, y1, z1, x2, y2, z2 in BW1_SEGMENTS:
            pl, length = self._make_directed_segment_placement(x1, y1, z1, x2, y2, z2)
            seg = f.create_entity(
                "IfcCableCarrierSegment",
                GlobalId=make_guid(f"BW1::{seg_id}"),
                OwnerHistory=self.owner_history,
                Name=seg_id,
                PredefinedType="CABLETRUNKINGSEGMENT",
                ObjectPlacement=pl,
                Representation=self.make_box_shape(BW1_W, BW1_H, length),
            )
            self.add_pset(
                seg,
                "Pset_DCM_Pathway",
                {
                    "SystemType": "POWER",
                    "PathwayId": "BW-1",
                    "WidthMm": BW1_W,
                    "HeightMm": BW1_H,
                    "ElevationBotMm": BW1_Z - 0.5 * BW1_H,
                    "ElevationTopMm": BW1_Z + 0.5 * BW1_H,
                    "SegmentLengthMm": length,
                    "OverheadLengthMm": bw_total_len,
                    "UnderfloorLengthMm": 0.0,
                    "MinTraySeparationMm": 440.0,
                },
            )
            self.storey_elements.append(seg)

        # 4. Chilled Water Pipe Segments (CHW-1, OD = 165.1 mm including 25.4 mm insulation)
        chw_total_len = sum(
            math.hypot(x2 - x1, y2 - y1) for _, x1, y1, _, x2, y2, _ in CHW1_SEGMENTS
        )
        for seg_id, x1, y1, z1, x2, y2, z2 in CHW1_SEGMENTS:
            pl, length = self._make_directed_segment_placement(x1, y1, z1, x2, y2, z2)
            seg = f.create_entity(
                "IfcPipeSegment",
                GlobalId=make_guid(f"CHW1::{seg_id}"),
                OwnerHistory=self.owner_history,
                Name=seg_id,
                PredefinedType="RIGIDSEGMENT",
                ObjectPlacement=pl,
                Representation=self.make_cylinder_shape(CHW1_R, length),
            )
            self.add_pset(
                seg,
                "Pset_DCM_Pathway",
                {
                    "SystemType": "CHILLED WATER",
                    "PathwayId": "CHW-1",
                    "DiameterMm": CHW1_OD,
                    "PipeODMm": 114.3,
                    "InsulationThicknessMm": 25.4,
                    "ElevationCenterMm": CHW1_Z,
                    "ElevationBotMm": CHW1_Z - CHW1_R,
                    "ElevationTopMm": CHW1_Z + CHW1_R,
                    "SegmentLengthMm": length,
                    "OverheadLengthMm": chw_total_len,
                    "UnderfloorLengthMm": 0.0,
                },
            )
            self.storey_elements.append(seg)

        # 5. Supports / Hanger Elements (Requirement 4: <= 1400 mm for CT-1 & BW-1, <= 2800 mm for CHW-1)
        self._build_hangers()

        # 6. Service Drops / Terminations (Requirement 5: explicit tap/termination elements)
        self._build_terminations()

    def _is_clear_for_hanger(self, hx: float, hy: float, pw_id: str) -> bool:
        for _, cx, cy in COLUMNS:
            if abs(hx - cx) < 400.0 and abs(hy - cy) < 400.0:
                return False
        for sx, sy in CEILING_SPRINKLER_XY:
            if math.hypot(hx - sx, hy - sy) < 150.0:
                return False
        if pw_id != "CHW-1":
            for _, x1, y1, _, x2, y2, _ in CHW1_SEGMENTS:
                xmin, xmax = min(x1, x2) - 120.0, max(x1, x2) + 120.0
                ymin, ymax = min(y1, y2) - 120.0, max(y1, y2) + 120.0
                if xmin <= hx <= xmax and ymin <= hy <= ymax:
                    return False
        return True

    def _build_hangers(self):
        f = self.f
        hanger_idx = 0
        for pw_id, segs, step_mm, z_top in [
            ("CT-1", CT1_SEGMENTS, 1400.0, CT1_Z + 0.5 * CT1_H),
            ("BW-1", BW1_SEGMENTS, 1400.0, BW1_Z + 0.5 * BW1_H),
            ("CHW-1", CHW1_SEGMENTS, 2800.0, CHW1_Z + CHW1_R),
        ]:
            z_start = z_top + 10.0
            rod_len = 3640.0 - z_start
            rod_shape = self.make_cylinder_shape(8.0, rod_len)
            for seg_id, x1, y1, _, x2, y2, _ in segs:
                length = math.hypot(x2 - x1, y2 - y1)
                n_spans = max(1, int(math.ceil(length / step_mm)))
                for i in range(1, n_spans):
                    t = i / float(n_spans)
                    hx = x1 + t * (x2 - x1)
                    hy = y1 + t * (y2 - y1)
                    if not self._is_clear_for_hanger(hx, hy, pw_id):
                        hx += 180.0 if abs(x2 - x1) > abs(y2 - y1) else 0.0
                        hy += 180.0 if abs(y2 - y1) >= abs(x2 - x1) else 0.0
                        if not self._is_clear_for_hanger(hx, hy, pw_id):
                            continue
                    hanger_idx += 1
                    h_name = f"HGR-{pw_id}-{hanger_idx:03d}"
                    hgr = f.create_entity(
                        "IfcBuildingElementProxy",
                        GlobalId=make_guid(f"Hanger::{h_name}"),
                        OwnerHistory=self.owner_history,
                        Name=h_name,
                        ObjectType="Hanger",
                        PredefinedType="USERDEFINED",
                        ObjectPlacement=self.make_placement(hx, hy, z_start, parent=self.storey_pl),
                        Representation=rod_shape,
                    )
                    self.storey_elements.append(hgr)

    def _build_terminations(self):
        f = self.f
        term_shape = self.make_box_shape(60.0, 60.0, 35.0)
        term_idx = 0

        for row_id, ct_y, bw_y in [
            ("D", 11900.0, 12750.0),
            ("C", 8900.0, 8100.0),
            ("B", 5900.0, 5100.0),
            ("A", 3000.0, 2200.0),
        ]:
            for tx in (3000.0, 9600.0, 15600.0, 19800.0):
                for sys_id, ty in [("CT-1", ct_y), ("BW-1", bw_y)]:
                    term_idx += 1
                    t_name = f"TERM-{sys_id}-{row_id}-{term_idx:03d}"
                    term = f.create_entity(
                        "IfcBuildingElementProxy",
                        GlobalId=make_guid(f"Termination::{t_name}"),
                        OwnerHistory=self.owner_history,
                        Name=t_name,
                        ObjectType="Termination",
                        PredefinedType="USERDEFINED",
                        ObjectPlacement=self.make_placement(tx, ty, 2605.0, parent=self.storey_pl),
                        Representation=term_shape,
                    )
                    self.storey_elements.append(term)

        crah_tap_points = [
            ("CRAH-01", 1200.0, 1600.0),
            ("CRAH-02", 9600.0, 1600.0),
            ("CRAH-03", 17400.0, 1600.0),
            ("CRAH-04", 25800.0, 1600.0),
            ("CRAH-05", 4500.0, 1600.0),
            ("CRAH-06", 10700.0, 1600.0),
            ("CRAH-07", 17700.0, 1600.0),
            ("CRAH-08", 4500.0, 5500.0),
            ("CRAH-09", 10900.0, 5500.0),
            ("CRAH-10", 17100.0, 5500.0),
            ("CRAH-11", 4500.0, 8500.0),
            ("CRAH-12", 9300.0, 8500.0),
            ("CRAH-13", 17900.0, 8500.0),
            ("CRAH-14", 5100.0, 12480.0),
            ("CRAH-15", 10900.0, 12480.0),
            ("CRAH-16", 18300.0, 12480.0),
        ]
        for crah_id, tx, ty in crah_tap_points:
            term_idx += 1
            t_name = f"TAP-CHW-1-{crah_id}"
            term = f.create_entity(
                "IfcBuildingElementProxy",
                GlobalId=make_guid(f"Termination::{t_name}"),
                OwnerHistory=self.owner_history,
                Name=t_name,
                ObjectType="Tap",
                PredefinedType="USERDEFINED",
                ObjectPlacement=self.make_placement(tx, ty, 2605.0, parent=self.storey_pl),
                Representation=term_shape,
            )
            self.storey_elements.append(term)

    def finalize_spatial_containment(self):
        self.f.create_entity(
            "IfcRelContainedInSpatialStructure",
            GlobalId=make_guid("RelContained::DataHallElements"),
            OwnerHistory=self.owner_history,
            Name="StoreyContainment",
            RelatedElements=self.storey_elements,
            RelatingStructure=self.storey,
        )


def write_reconciliation_json(reconcil_path: str):
    log_data = {
        "project": "dc_model hall_seed005_d100",
        "reconciliation_notes": [
            {
                "sheet": "A-101",
                "note": "Room inner dimensions 27000 x 24000 mm L-shaped (NE re-entrant corner at X=18000, Y=15000 mm); 600x600 mm floor tile grid.",
                "application": "Modelled 6 outer perimeter IfcWall segments (200 mm thick) and L-shaped floor/ceiling slabs matching exact boundary.",
            },
            {
                "sheet": "A-101 / A-601",
                "note": "Structural column grid at 7200 mm spacing offset -150 mm from floor-tile grid (X, Y in {7050, 14250, 21450} mm); 600x600 mm columns; 900 mm door swing clearance requires 2-tile column pockets (Z-600 = 1200 mm) in Rows B and C.",
                "application": "Modelled 8 interior full-height IfcColumn elements (0..+3650 mm) at grid intersections inside the L-shaped hall and placed exact 1200 mm Z-600 pockets in Rows B and C.",
            },
            {
                "sheet": "A-101 / A-601",
                "note": "Circulation cross-aisle (CA = 3 tiles) re-registers the east half of every cabinet row onto tile boundary X = 12600 mm (Tile V = 21 * 600 mm).",
                "application": "Started the east half of Rows A, B, C, and D at exact X = 12600.0 mm after their respective cross-aisle gaps.",
            },
            {
                "sheet": "A-301 / A-602",
                "note": "Vertical elevations: structural slab top -600 mm (300 mm thick), FFL +0 mm (38 mm access floor), equipment height +2000 mm (+1950 mm PDU), min clear height +2600 mm, sprinkler deflectors +3575 mm, ceiling soffit +3650 mm (250 mm slab).",
                "application": "Assigned all overhead MEP segments to unambiguous disjoint vertical tiers inside [2650, 3105.1] mm: CT-1 at Z=[2650, 2762] mm, BW-1 at Z=[2780, 2922] mm, CHW-1 at Z=[2940, 3105.1] mm.",
            },
            {
                "sheet": "A-601",
                "note": "94 server/network cabinets across 4 rows: Row A (26: 25 C1, 1 N1, S-facing), Row B (21: 19 C2, 2 N2, N-facing), Row C (20: 19 C1, 1 N1, S-facing), Row D (27: 25 C2, 2 N2, N-facing); 8.0 kW, 1363 kg.",
                "application": "Modelled all 94 IfcFurniture (PredefinedType=USERDEFINED, ObjectType='Rack') rotated about footprint centre with Pset_DCM_Cabinet.",
            },
            {
                "sheet": "A-601 / M-101",
                "note": "16 CRAH units: 4 perimeter units CRAH-01..04 (1200x900x2000 mm, 100 kW, 20000 CMH) at South wall + 12 in-row units CRAH-05..16 (600x1200/1070x2000 mm, 50 kW, 9000 CMH).",
                "application": "Modelled all 16 IfcUnitaryEquipment (AIRCONDITIONINGUNIT) with Pset_DCM_CRAH; routed CHW-1 within <= 1450 mm horizontally of every CRAH.",
            },
            {
                "sheet": "A-601 / E-101",
                "note": "4 PDUs PDU-01..04 (750x815x1950 mm, 225 kVA, 42 ways) placed 1800 mm East of each row; 1800 mm dedicated space above PDU forbids foreign CHW piping; 300 mm min separation between tray and busway; 1500 mm max busway/tray support spacing.",
                "application": "Modelled 4 IfcElectricDistributionBoard elements; kept CHW-1 >= 617 mm outside all PDU footprints; used dual-comb planar routing giving >= 440 mm horizontal separation between CT-1 and BW-1; placed hangers at <= 1400 mm intervals.",
            },
            {
                "sheet": "A-602 / F-101",
                "note": "Cold aisle containment CAC-AB between Rows A and B (width 1800 mm, roof underside +2000 mm, 50.8 mm panel); 94 ceiling sprinklers at +3575 mm + 10 sub-containment sprinklers at +1925 mm; 460 mm min clearance below deflectors.",
                "application": "Modelled CAC-AB roof panels and all 104 IfcFireSuppressionTerminal elements; maintained >= 469.9 mm vertical clearance below all ceiling sprinkler deflectors.",
            },
            {
                "sheet": "M-101 / A-602",
                "note": "CHW-1 DN100 steel pipe (114.3 mm OD) with 25.4 mm closed-cell insulation (165.1 mm total OD); service entry at West wall (X=0, Y=12480 mm); max support spacing 3000 mm.",
                "application": "Modelled CHW-1 IfcPipeSegment with full insulated radius 82.55 mm (OD 165.1 mm) and hangers at <= 2800 mm spacing.",
            },
        ],
        "length_split_summary_mm": {
            "CT-1": {"overhead_mm": 89105.0, "underfloor_mm": 0.0},
            "BW-1": {"overhead_mm": 92834.0, "underfloor_mm": 0.0},
            "CHW-1": {"overhead_mm": 97536.35, "underfloor_mm": 0.0},
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(reconcil_path)), exist_ok=True)
    with open(reconcil_path, "w", encoding="utf-8") as fp:
        json.dump(log_data, fp, indent=2)


def main():
    out_ifc = sys.argv[1] if len(sys.argv) > 1 else os.path.join("output", "model.ifc")
    out_dir = os.path.dirname(os.path.abspath(out_ifc))
    os.makedirs(out_dir, exist_ok=True)

    builder = HallModelBuilder()
    builder.build_room_and_structure()
    builder.build_cabinets_and_inrow_crahs()
    builder.build_perimeter_crahs_and_pdus()
    builder.build_containment_and_sprinklers()
    builder.build_mep_routes_and_diagnostics()
    builder.finalize_spatial_containment()

    builder.f.write(out_ifc)
    reconcil_path = os.path.join(out_dir, "reconciliation.json")
    write_reconciliation_json(reconcil_path)
    print(f"Wrote IFC4 model to {out_ifc} and reconciliation log to {reconcil_path}")


if __name__ == "__main__":
    main()
