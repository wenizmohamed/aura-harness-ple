The delegated lateral design package for **Building A2 at the Northern Divide Data Campus** (Lewis and Clark County, Montana) has been completed and bundled into:

- **`/filesystem/final_batch4__structural_task5_wind_diaphragm_shear__blind/output/submission.zip`**

### Delivered Files Inside `output/submission.zip`
1. **`lateral_schedule.xlsx`** — Nine-worksheet schedule workbook (`DeckZones`, `ChordSchedule`, `Piers`, `ShearWalls`, `Diaphragm`, `Chords`, `Drift`, `Convergence`, `Cost`) populated with positive Allowable Stress Design (`0.6W` ASD) magnitudes at mesh refinement level `L2` ($H = 5.0\text{ ft}$).
2. **`diaphragm_plan.dxf`** — Plan view drawing on the building grid in feet (origin `(0, 0)` at the south-west corner) carrying all required layers (`S-DIAP-SHEAR`, `S-DIAP-ZONE`, `S-WALL-REAC`, `S-CHRD`, `S-COLL`, `S-ANNO-TEXT`, `S-GRID`), explicitly annotated for `TRANSVERSE` (North–South wind) and `LONGITUDINAL` (East–West wind) directions and `ASD` (`0.6W`).
3. **`constraint_register.xlsx`** — Worksheet `Register` (`document, clause, requirement, value, units, items`) documenting 124 governing requirements across all active corpus documents, strictly excluding superseded 2024 revisions and the Building A1 study.
4. **`calculations.pdf`** — 5-page $8.5 \times 11\text{ in.}$ portrait calculation package explicitly stating `ASD` (`0.6W` for strength/drift; `0.6D + 0.6W` for overturning stability) and covering wind velocity pressures, parapet cantilever transfer and roof-level wall line loads, `DIAPH-MT 1.0` benchmark verification (`VE-1`) and mesh convergence (`L1`, `L2`, `L3`), deck zones and quarter-point unit shears, chords and collectors, diaphragm drift, precast pier stiffnesses, overturning stability, connections, and installed cost.
5. **`design_basis.md`** — Design basis narrative containing the required 9-parameter basis table, the 6-line governing scenario table, and prose documenting the resolution of all eight conflicts between the issued documents.

---

### Key Engineering Results (`0.6W` ASD Basis)
- **Wind Parameters (`EOR-NDDC-A2-S01` Rev 2 §4, `NDDC-AHJ-014`, `TS-2026-02`, `ALTA-2025-77`, `WT-2026-07`):**
  - Risk Category III, $V = 115\text{ mph}$, Exposure C, $K_d = 0.85$, $K_{zt} = 1.19$, $z_g = 3940.0\text{ ft}$ NAVD 88 $\Rightarrow K_e = e^{-0.0000362(3940.0)} = 0.8671$.
  - Velocity pressures: $q_h(28.0\text{ ft}) = 28.75\text{ psf}$, $q_p(31.0\text{ ft}) = 29.37\text{ psf}$ (typical parapet), $q_p(36.0\text{ ft}) = 30.31\text{ psf}$ (as-built north mechanical screen wall on panels `N108–N111`).
- **As-Built Geometry & Precast Shear Wall Piers (`EOR-NDDC-A2-S01` Rev 2 §5, `SR-2026-118`, 2026 IFC Model):**
  - Net roof diaphragm area = $39,600\text{ sf}$ (accounting for the $60\text{ ft} \times 40\text{ ft}$ NE generator yard re-entrant notch and the $40\text{ ft} \times 30\text{ ft}$ mechanical well opening).
  - 63 precast panels segmented into **73 active piers** ($\text{width} \ge 2.0\text{ ft}$; the $1.5\text{ ft}$ east leg of panel `S14` adjacent to the as-built $8\text{ ft} \times 12\text{ ft}$ field-cut opening at $x = 194.5\text{–}202.5\text{ ft}$ is neglected per §5.4).
- **DIAPH-MT 1.0 Solver Verification & Mesh Convergence (§9):**
  - Exact reproduction of benchmark `VE-1` (240 elements, 273 nodes, $F_y = 20.00\text{ kips}$, $R = 10.00\text{ kips}$, $v_{\max} = 185.2\text{ plf}$, $T_{\max} = 2.57\text{ kips}$, $d_y = 0.1669\text{ in}$).
  - Building A2 mesh convergence on scenario `W01` wall line `W` reaction: `L1` ($10\text{ ft}$, 396 elements) = $47.62\text{ kips}$, `L2` ($5\text{ ft}$, 1,584 elements) = $47.85\text{ kips}$, `L3` ($2.5\text{ ft}$, 6,336 elements) = $47.96\text{ kips}$ ($0.23\%$ change between `L2` and `L3`, well within the $5.0\%$ limit).
- **Roof Deck, Chords/Collectors, Drift & Connections Summary:**
  - **4 deck types** across the 12 zones ($\le 4$ limit): `D22-36/4-2` (`Z21`, `Z22` with $1.15 G' = 20.47\text{ kip/in}$ for the $4\text{ ft}$ span), `D22-36/4-4` (`Z11`, `Z41`, `Z42`), `D22-36/7-2` (`Z13`, `Z23`, `Z31`, `Z33`, `Z43`), and `D22-36/7-4` (`Z12`, `Z32`), with peak zone shear utilization $\le 0.812$.
  - **Chords & Collectors:** `C-E2 = PL12x1`, `C-N1 = PL5x1/2`, `C-N2 = PL5x1/2`, and all other chord and collector lines `PL3x3/8`.
  - **Diaphragm Drift:** Peak in-plane ASD deflection = $0.5401\text{ in}$ (`W01`, `Y` axis) $\le 0.55\text{ in}$ limit (`0.2816 in` max in `X`).
  - **Panel Connections:** All 63 panels satisfy $V_{\text{panel,ASD}} \le 1.40 L$ (`B1` base shear capacity; max utilization $0.986$ on `E201` at $13.80\text{ kips} \le 14.00\text{ kips}$); **140 `E1` roof-to-panel embeds** and **10 `T1` panel base tie-downs** required.
  - **Total Installed Package Cost:** **`$210,647.01`** (Roof Deck: `$138,648.00`; Chords/Collectors: `$21,599.01`; `E1` Embeds: `$25,900.00`; `T1` Tie-Downs: `$24,500.00`), $32.0\%$ below the `$310,000.00` cost cap.