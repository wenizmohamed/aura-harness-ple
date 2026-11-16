The structural roof deck design for **Building A of the DC-2 Helena Data Centre** has been completed and packaged at:

- **Deliverable archive**: `/filesystem/final_batch4__structural_task7_roof_deck_design__blind/output/submission.zip`
  1. `deck_design.xlsx` — Roof deck design workbook (`Zones`, `DesignBasis`, `Drifts`, `CalcSummary`, `Diaphragm`, `BOM`).
  2. `roof_deck_plan.dxf` — Roof framing and deck zoning plan in feet (`S-DECK-ZONE`, `S-DECK-TEXT`, `S-FRAMING`, `S-OPENING`).
  3. `constraint_register.xlsx` — Governing requirement register (`Register`, 100 rows).
  4. `design_basis.md` — Engineering design basis narrative covering governing document resolution, load derivations, 2D semi-rigid diaphragm FEA and stiffness tuning, zoning optimization, and BOM/cost breakdown.

---

### Key Engineering Results

1. **Governing Document & Hazard Basis (`DesignBasis`)**:
   - **Snow (`SNOW-2026-014` & `EOR-DC-RD-01 Rev 2` Clause 5)**: $p_g = 63.0\text{ psf}$ (at $4,880\text{ ft}$ elevation), $C_e = 0.90$, $C_t = 1.0$, $I_s = 1.10$, balanced flat-roof snow load $p_f = 43.66\text{ psf}$, snow density $\gamma = 22.19\text{ pcf}$, balanced snow depth $h_b = 1.968\text{ ft}$.
   - **Live Load (`EOR-DC-RD-01 Rev 2` Clause 4 & `UFC 3-301-01` Table E-1 Item 51)**: $L_r = 20.0\text{ psf}$ unreduced ($R_1 = R_2 = 1.0$).
   - **Wind (`EOR-DC-RD-01 Rev 2` Clause 6 & `LAT-2026-003 Rev 1` Table 4-1)**: $V = 115\text{ mph}$, Exposure C, $h = 32.0\text{ ft}$, $q_h = 29.93\text{ psf}$, C&C edge strip width $a = 12.8\text{ ft}$ ($2a = 25.6\text{ ft}$), C&C net uplift pressures $-32.3\text{ psf}$ (Zone 1'), $-47.3\text{ psf}$ (Zone 1), $-74.2\text{ psf}$ (Zone 2), $-101.2\text{ psf}$ (Zone 3); roof diaphragm forces $\text{WIND\_X} = 118.0\text{ kip}$, $\text{WIND\_Y} = 152.0\text{ kip}$.
   - **Seismic (`USGS ASCE 7-22 JSON`, `EOR-DC-RD-01 Rev 2` Clause 7, & `LAT-2026-003 Rev 1` Section 5)**: $S_{DS} = 0.44\text{ g}$, $S_{D1} = 0.24\text{ g}$, $I_e = 1.25$, $R = 3.25$, $\Omega_0 = 2.0$, effective seismic weight $w_{\text{seismic}} = 18.0 + 0.20(43.66) = 26.73\text{ psf}$ ($W = 1,154.82\text{ kip}$), diaphragm design force $F_{px} = 195.43\text{ kip}$, diaphragm classification `SEMI-RIGID`.

2. **Governing Snow Drift Surcharges (`Drifts`)**:
   - `MEP-PH-1` face `W`: peak surcharge $104.28\text{ psf}$, band from $60.0\text{ ft}$ to $41.20\text{ ft}$ (leeward of $120\text{ ft}$ enclosure).
   - `SCR-N` face `S`: peak surcharge $89.48\text{ psf}$, band from $164.0\text{ ft}$ to $147.75\text{ ft}$ (windward of $164\text{ ft}$ south fetch, truncated at $h_c = 4.032\text{ ft}$).
   - `PARAPET` face `N`: peak surcharge $34.01\text{ psf}$, band from $180.0\text{ ft}$ to $167.74\text{ ft}$ (windward of $180\text{ ft}$ fetch, truncated at $h_c = 1.532\text{ ft}$, width $8 h_c = 12.26\text{ ft}$).
   - `RTU-1` face `E`: peak surcharge $98.17\text{ psf}$, band from $36.0\text{ ft}$ to $53.70\text{ ft}$ (windward of $204\text{ ft}$ east fetch).

3. **Optimized Roof Deck Zoning (`Zones` & `CalcSummary`)**:
   - **3 zones, 14 rectangles, 2 gages (`18 ga`, `22 ga`), 3 attachment patterns** covering all $1,172$ decked `6 ft × 6 ft` cells ($42,192\text{ sf}$) and excluding all $28$ framed opening cells (`RO-1`, `RO-2`, `RO-3`, $1,008\text{ sf}$):
     - **`Z1`** (`18 ga`, `36/9`, `SCREW-10`, `5`/span — $8,640\text{ sf}$, 2 rectangles): shear $912.90 / 1,225.70\text{ plf}$, gravity $157.14 / 177.00\text{ psf}$, net uplift $94.90 / 119.75\text{ psf}$, governing scenario **`S04`** (D/C $= 0.888$).
     - **`Z2`** (`22 ga`, `36/9`, `BP`, `4`/span — $15,768\text{ sf}$, 5 rectangles): shear $476.21 / 521.50\text{ plf}$, gravity $103.51 / 106.00\text{ psf}$, net uplift $68.71 / 74.50\text{ psf}$, governing scenario **`S04`** (D/C $= 0.976$).
     - **`Z3`** (`18 ga`, `36/7`, `SCREW-10`, `3`/span — $17,784\text{ sf}$, 7 rectangles): shear $600.53 / 742.70\text{ plf}$, gravity $160.94 / 177.00\text{ psf}$, net uplift $67.90 / 93.14\text{ psf}$, governing scenario **`S02`** (D/C $= 0.909$).

4. **In-Plane Diaphragm Performance (`Diaphragm`)**:
   - `S05` (Wind X): max shear $399.76\text{ plf}$, max deflection $0.502\text{ in}$, chord force $11.58\text{ kip}$, collector force $15.70\text{ kip}$, `SEMI-RIGID`.
   - `S06` (Wind Y): max shear $699.07\text{ plf}$, max deflection $1.036\text{ in}$, chord force $23.00\text{ kip}$, collector force $16.54\text{ kip}$, `SEMI-RIGID`.
   - `S07` (Seismic X): max shear $669.88\text{ plf}$, max deflection $0.806\text{ in}$, chord force $19.28\text{ kip}$, collector force $28.23\text{ kip}$, `SEMI-RIGID`.
   - `S08` (Seismic Y): max shear $912.90\text{ plf}$, max deflection $1.322\text{ in}$ ($\le 1.60\text{ in}$), chord force $29.69\text{ kip}$ ($\le 38.0\text{ kip}$), collector force $21.85\text{ kip}$, `SEMI-RIGID`.
   - `S10` (Seismic X + $\Omega_0 = 2.0$): max shear $669.88\text{ plf}$, max deflection $0.806\text{ in}$, chord force $19.28\text{ kip}$, amplified collector force $56.45\text{ kip}$ ($\le 58.0\text{ kip}$), `SEMI-RIGID`.

5. **Bill of Materials & Total Installed Cost (`BOM`)**:
   - `deck area 22 gage`: $15,768\text{ sf}$
   - `deck area 18 gage`: $26,424\text{ sf}$
   - `support fasteners`: $19,120\text{ ea}$
   - `sidelap connectors`: $8,868\text{ ea}$ ($5,364\text{ ea}$ `SCREW-10` + $3,504\text{ ea}$ `BP`)
   - **Total Installed Cost (`CP-RD-2026 Rev 0`)**: **`$218,128.36`**