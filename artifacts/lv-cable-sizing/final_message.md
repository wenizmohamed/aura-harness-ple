The low-voltage wire schedule and supporting engineering package for **Building 4210, Consolidated Support Facility (Project P-4210)** at Naval Support Activity Whitmore Ridge have been completed and packaged in `/filesystem/electrical__lv_cable_sizing__blind/output/submission.zip`.

### Delivered Files (Top-Level in `/filesystem/electrical__lv_cable_sizing__blind/output/submission.zip`)
1. `wire_schedule.csv` (`/filesystem/electrical__lv_cable_sizing__blind/output/wire_schedule.csv`) — 32-circuit schedule (`B-01` through `B-18`, `F-01` through `F-13`, and `SE-1`) with all 27 required columns.
2. `E-621_wire_schedule.dxf` (`/filesystem/electrical__lv_cable_sizing__blind/output/E-621_wire_schedule.dxf`) — Contract drawing Sheet E-621 with project title block (`P-4210`), abbreviation legend, and `TEXT` entities for all 32 circuits matching `wire_schedule.csv`.
3. `calc_book.xlsx` (`/filesystem/electrical__lv_cable_sizing__blind/output/calc_book.xlsx`) — Calculation workbook containing `front_sheet`, `duct_assignment`, and `cost_ledger` with stored numerical values.
4. `design_basis.md` (`/filesystem/electrical__lv_cable_sizing__blind/output/design_basis.md`) — Engineering Basis of Design opening with the required structured `json` block followed by the narrative.
5. `constraint_register.xlsx` (`/filesystem/electrical__lv_cable_sizing__blind/output/constraint_register.xlsx`) — Code-compliance matrix registering 54 atomic requirements traced to governing clauses and explicitly documenting non-governing/superseded documents.

---

### Key Engineering Results
- **Codes of Record & Precedence:** **NFPA 70 (NEC) 2023 Edition** and **IBC 2024 Edition**, adopted by **UFC 1-200-01** (Change 4, 17 December 2024) as fixed at design start (14 July 2025), alongside **UFC 3-501-01** (27 November 2024), **UFC 3-520-01** (16 January 2025), and **NSA-WR EDS-26 Rev 4** (12 June 2026). Where criteria differ, the **most restrictive requirement governs** (`EDS-26 Rev 4` §1.1); superseded documents (`EDS-26 Rev 2`, `E-601 Rev A`), non-governing vendor data (`Meridian Cable`), and power-limited fire alarm circuits (`Sheet E-401`) do not govern.
- **Environmental & Thermal Parameters (`NFPA 70` §310.14(B) Neher-McGrath):**
  - Outdoor design dry-bulb: **`42 °C`** (`NOAA USW00003145` maximum `DLY-TMAX-NORMAL = 106.8 °F = 41.56 °C` rounded up per `EDS-26 Rev 4` §5.4).
  - Unshaded roof cable tray `CT-R1`: **`46 °C`** ambient (`42 °C + 4 K`), solar irradiance **`1030 W/m²`** (`absorptivity = 0.6`, `h = 14.0 W/(m²·K)`, `Delta_T_s = 14.05 K`), `18` current-carrying conductors (`k_t = 1.90`), total cable OD sum **`12.206 in <= 16.20 in`** (`90%` of `18 in` usable width).
  - Undisturbed earth ambient: **`27.45 °C`** (annual mean `DLY-TAVG-NORMAL = 76.00 °F = 24.45 °C + 3 K`; spot logger `22.1–28.4 °C` rejected per `EDS-26 Rev 4` §5.3.2).
  - Thermal resistivities: **`0.60 K·m/W`** fluidised thermal backfill (full trench width/depth; native sandy clay `0.95 K·m/W` rejected per `EDS-26 Rev 4` §5.3.3) and **`0.55 K·m/W`** concrete encasement at **`LF = 1.0`**.
  - Interior raceways: **`45 °C`** in Mechanical Room 104 (`F-01`, `B-11`..`B-15`) and Fire Pump Room 108 (`F-03`); **`40 °C`** in all other interior spaces (`M-501-C`).
- **Duct-Bank Assignment & Mutual Heating:**
  - `DB-1` (`10` ducts `D1..D10` available; `D11` owner spare and `D12` existing site lighting reserved per `E-619`): `SE-1` (`6 sets of 500 kcmil CU`, `4/0 CU` EGC) occupies **`D1, D2, D5, D6, D9, D10`** (`worst-case Delta_T_m = 31.09 K` at `D5`, `348.11 A/set`, `2088.66 A >= 2000 A` `MSB-1` bus rating); `F-10` (`2 sets of 500 kcmil AL`, `#1 CU` EGC) occupies **`D4, D8`** (`Delta_T_m = 23.53 K` at `D8`, `302.25 A/set`, `604.50 A >= 600 A`).
  - `DB-2` (`3` ducts `E1..E3` available; `E4` reserved for communications): `F-05` (`3 sets of 600 kcmil AL`, `250 kcmil CU` EGC) occupies **`E1, E2, E3`** (`Delta_T_m = 1.54 K`, capped at `336.00 A/set` by `75 °C` termination limit).
- **Voltage-Drop Allocation:** Starts at **`T-1` secondary lugs** (`WRPU-2026-0412`) and does **not** reset at low-voltage transformer `K-13` (`UFC 3-501-01` §3-2.7.4.5.3). Feeder-chain cumulative drops are **`1.04%`** at `MSB-1`, **`1.41%`** at `DP-2`, **`1.57%`** at `K-13`, **`2.58%`** at `MCC-1`, **`2.58%`** at `DP-3`, **`2.77%`** at `LP-1`, and **`2.78%`** at `ATS-1` (all `<= 3.0%`). All 18 branch/motor circuits satisfy `<= 3.0%` individual drop and `<= 5.0%` cumulative drop (maximum **`4.93%`** on `B-17`), and special equipment limits on `F-03` (`1.34%` running, `2.05%` locked rotor), `F-09` (`1.25x` reactance, `2.41%` cumulative), and `F-11` (`1.16% <= 2.0%` feeder) are met.
- **Standardisation & Installed Cost:** Uses exactly **5 distinct phase-conductor sizes larger than `#1 AWG`** (`4/0`, `300 kcmil`, `400 kcmil`, `500 kcmil`, `600 kcmil`). Total conductor length is **`40,888 ft`** (`>= 38,000 ft`), qualifying for the `-6%` campus quantity break:
  - **Conductors (net of `-6%` break):** `$70,387.43` material + `$22,996.99` labour = **`$93,384.42`**
  - **Terminations (`90 set-ends`):** `$5,105.26` material + `$4,504.06` labour = **`$9,609.32`**
  - **Interior Raceway (`4,257 ft` RMC):** `$21,406.08` material + `$26,183.52` labour = **`$47,589.60`**
  - **Total Installed Package Cost (`total_usd`):** `$96,898.77` material + `$53,684.57` labour = **`$150,583.34`**