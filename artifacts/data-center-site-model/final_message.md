I have designed and verified the phased 3D BIM model for the data-center campus (`p6_002`) and written the final deliverable to **`submission/model.ifc`**.

### Delivered File
- **`submission/model.ifc`**: An ISO-10303-21 STEP physical file (schema `IFC4`, SI metres) containing one `IfcProject`, one `IfcSite` with the `DCD_Networks` property set, and seven `IfcBuilding` extruded-solid entities (`DH_P1`, `DH_P2`, `SUB`, `GEN`, `CTP`, `BRM`, and `RET`) with their `IfcBuildingStorey` aggregations and `DCD_Layout` property sets.

### Key Engineering & Verification Results
1. **3D Building Massing & Program Compliance (Sec. 1, Addenda A.1, A.3–A.5)**:
   - **`DH_P1`** (`data_hall`, Phase 1, southern developable area): `[93.8, 19.0]–[184.0, 69.0]` (`90.2 m × 50.0 m = 4,510.0 m² >= 4,500 m²`, aspect ratio `1.80 <= 2.5`), 2 storeys (`0.0 m`, `4.5 m`), height `9.0 m <= 13.8 m` (floor-to-floor `4.5 m` in `[3.2, 5.5] m`), `GFA = 9,020.0 m² >= 7,200 m²`.
   - **`DH_P2`** (`data_hall`, Phase 2, northern developable area): `[89.8, 192.0]–[180.0, 242.0]` (`90.2 m × 50.0 m = 4,510.0 m² >= 4,500 m²`, aspect ratio `1.80 <= 2.5`), 2 storeys (`0.0 m`, `4.5 m`), height `9.0 m <= 13.8 m`, `GFA = 9,020.0 m² >= 7,200 m²`.
   - **`SUB`** (`substation`, Phase 1): `[188.0, 170.5]–[220.0, 202.0]` (`32.0 m × 31.5 m = 1,008.0 m² >= 1,000 m²`), 1 storey, height `6.5 m`.
   - **`GEN`** (`generator_yard`, Phase 1): `[210.0, 237.0]–[235.5, 257.0]` (`25.5 m × 20.0 m = 510.0 m² >= 500 m²`), 1 storey, height `2.5 m`.
   - **`CTP`** (`cooling_plant`, Phase 1): `[224.0, 182.0]–[256.5, 207.0]` (`32.5 m × 25.0 m = 812.5 m² >= 800 m²`), 1 storey, height `3.5 m`.
   - **`BRM`** (`berm`, Phase 1): `[192.0, 221.0]–[206.5, 256.0]` (`14.5 m × 35.0 m = 507.5 m² >= 300 m²`), 1 storey, height `8.0 m`.
   - **`RET`** (`stormwater_retention`, Phase 1): `[195.0, 18.5]–[255.0, 45.25]` (`60.0 m × 26.75 m = 1,605.0 m² >= 100 m²`), extruded from `z = -0.3 m` with depth `0.3 m` (`max Z = 0.0 m`).

2. **Setbacks, Coverage, Wetlands, Stormwater & Hazard Separation (Sec. 2.3, 2.5, 3.2, 4.1, 4.2, 4.4)**:
   - **Setbacks**: All 7 structures are set back `>= 18.5 m` (`>= 18.0 m` required) from all four parcel boundaries.
   - **Lot Coverage**: Non-exempt building footprints total `11,350.5 m²` (`12.67% <= 15.1%` of the `89,600 m²` parcel; even including `BRM` and `RET`, total area is `13,463.0 m² = 15.03% <= 15.1%`).
   - **Wetland Buffers**: All structures and buffered roadways maintain `>= 9.0 m` clearance (`>= 8.0 m` required) from both `WET1` and `WET2`.
   - **Stormwater Retention**: `RET` area (`1,605.0 m²`) exceeds `11.8%` of total impervious roof and road area (`1,539.0 m²` at full buildout; `998.0 m²` at Phase 1).
   - **Hazard Separation**: `GEN` is separated by `>= 30.0 m` (`>= 28.0 m` required) from every occupied structure (`DH_P1`, `DH_P2`, `SUB`, and `CTP`).

3. **3D Acoustics & Visual Screening (Sec. 5.1, 5.2, Addenda A.2, A.6)**:
   - **Visual Screening**: `GEN` is 100% screened in 3D across its entire footprint from `R1 (-25, 140, 1.7)` by `BRM` (`8.0 m`) and from `R2 (160, -30, 1.7)` by `DH_P1` (`9.0 m`) and `SUB` (`6.5 m`) in both Phase 1 and Full Buildout.
   - **Noise**: With 3D barrier insertion loss credited where lines of sight are broken (`BRM` and `SUB` for `R1`; `DH_P1` and `SUB` for `R2`), cumulative sound pressure levels are **`37.72 dB(A)`** at `R1` and **`39.04 dB(A)`** at `R2` in Phase 1, and **`38.12 dB(A)`** at `R1` and **`39.05 dB(A)`** at `R2` at Full Buildout (all well below the **`42.35 dB(A)`** limit).

4. **Road Access, MV Continuity & Phased Utility Cost Caps (Sec. 3.1, 3.3, 6.2–6.5, 7.1–7.5, 8.1–8.4)**:
   - **Road Network**: Enters at single south-frontage gate `(188.0, 0.0)`, threads the upland corridor (`x = 184.0`) between `WET1` and `WET2`, and passes within `4.0 m` (`<= 18.0 m` required) of `DH_P1`, `DH_P2`, `SUB`, `CTP`, and `GEN` without intersecting any building footprint (`road_p1 = 274.94 m`, `road_p2 = 7.00 m`, total road length = `281.94 m`).
   - **MV Power Network**: Routes continuously from `POI (320.0, 195.0)` to `SUB (220.0, 170.5)` (`mv_p1_util = 102.96 m`) and from `SUB` to `DH_P1 (184.0, 69.0)` (`mv_p1_dh1 = 107.70 m`, Phase 1 MV = `210.66 m`) and `DH_P2 (180.0, 195.0)` (`mv_p2_dh2 = 59.71 m`, Total MV = `270.37 m`) with zero cross-phase building footprint crossings.
   - **Weighted Utility Costs**:
     - **Phase 1**: `1.0 × 210.66 + 0.3 × 274.94 = 293.14 <= 314.0`
     - **Full Buildout**: `1.0 × 270.37 + 0.3 × 281.94 = 354.95 <= 473.0` (vs. `454.7` reference cost)