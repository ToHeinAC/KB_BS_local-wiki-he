---
related:
- concept-radiation-protection.md
- concept-professional-exposure.md
- concept-radiation-dose-limits.md
sources:
- summary-din-25425-3-2019-12-md.md
- summary-din-25425-4-2019-12-md-teil-2-2.md
title: Radionuclide Laboratories
type: concept
updated: '2026-05-27'
---

# Radionuclide Laboratories

A radionuclide laboratory is a highly specialized facility designed for the safe handling of open radioactive substances. The design, construction, and operation must adhere to stringent guidelines, notably detailed in DIN 25425-1 [summary-din-25425-1-2021-05-md-teil-1-2.md].

## Purpose and Scope
The laboratory is an area or set of rooms dedicated to processes involving open radioactive substances above the release limit [summary-din-25425-1-2021-05-md-teil-1-2.md].

## Risk Assessment and Room Classification
The primary determinant for required protective measures is the risk assessment, which leads to the assignment of a Room Category ($R_K$) [summary-din-25425-1-2021-05-md-teil-1-2.md].

### Assessment Factor (K)
The assessment factor $K$ quantifies the potential hazard and is calculated using formulas that incorporate the handling method and activity levels [summary-din-25425-1-2021-05-md-teil-1-2.md].

The Room Category ($R_K$) is determined by $K$:
*   $K \le 10^{-4}$: RK0
*   $10^{-4} < K \le 10^{-2}$: RK1
*   $10^{-2} < K \le 100$: RK2
*   $100 < K \le 10^2$: RK3

### Handling Method
The handling method dictates the Incorporation Factor ($a_k$):
*   **Low Release Probability:** $a_k = 10^{-4}$ (e.g., dilution, measurement).
*   **Increased Release Probability:** $a_k = 10^{-3}$ (e.g., handling of powders, drying).

## Technical Design Requirements
The facility must integrate multiple technical systems to ensure protection against external exposure, internal contamination, and environmental release [summary-din-25425-1-2021-05-md-teil-1-2.md].

### Ventilation and Airflow
*   **Flow Direction:** A constant airflow must be maintained from low contamination risk areas to high contamination risk areas [summary-din-25425-1-2021-05-md-teil-1-2.md].
*   **Exhaust System:** For RK2 and RK3, the exhaust system must be dedicated and cannot connect to other exhaust systems. Filtration retrofitting must be planned [summary-din-25425-1-2021-05-md-teil-1-2.md].

### Utilities Management
*   **Wastewater:** Wastewater must be classified as either largely contamination-free or radioactively contaminated. If both occur, the systems must be physically separated. Radioactively contaminated wastewater must be collected for determining the disposal route [summary-din-25425-1-2021-05-md-teil-1-2.md].
*   **Waste:** Residual material (*Reststoff*) must be managed according to waste regulations [summary-din-25425-1-2021-05-md-teil-1-2.md].

### Facility Layout
The layout must ensure that specialized rooms are physically separated and that traffic paths are controlled [summary-din-25425-1-2021-05-md-teil-1-2.md].

## Fire Protection Requirements (DIN 25425-3)
The design must incorporate measures for preventive fire protection, as detailed in DIN 25425-3 [summary-din-25425-3-2019-12-md.md].

### Hazard Assessment for Fire
The required fire resistance of building components is determined by the Hazard Level (GS) of the room or room group, which measures the necessary protection against radiation risk in case of fire (external irradiation, contamination, incorporation) [summary-din-25425-3-2019-12-md.md].

**Hazard Level Determination:**
The Hazard Level is determined according to Table 1 [summary-din-25425-3-2019-12-md.md]:
| Hazard Level | Range (X) |
| :--- | :--- |
| GS 1 | $1 < X \leq 10^4$ |
| GS 2 | $10^4 < X \leq 10^7$ |
| GS 3 | $10^7 < X \leq 10^{10}$ |
| GS 4 | $X > 10^{10}$ |

The calculation for the classification uses the formula:
$$
\sum (A_{o,i} + A_{u,i}/1000)
$$
$$
F_i = X \quad (1)
$$
Where $A_{o,i}$ is the activity of the individual radionuclide $i$, open and not fireproofly enclosed; $A_{u,i}$ is the activity of the individual radionuclide $i$, fireproofly enclosed; and $F_i$ is the release limit of the radionuclide $i$ according to Annex 4, Table 1, Column 2 StrlSchV [summary-din-25425-3-2019-12-md.md].

### Structural and Material Requirements
*   **Materials:** Non-combustible building materials should be used in rooms or room groups of GS 2 to GS 4 [summary-din-25425-3-2019-12-md.md].
*   **Compartmentalization:** Fire-resistant building components (walls, ceilings, doors) must be selected according to Table 2 [summary-din-25425-3-2019-12-md.md].
*   **Doors and Passages:** Doors in walls closing the radionuclide laboratory must be smoke-tight. For GS 3 and GS 4, rooms or room groups may only be connected via a airlock (*Schleuse*) [summary-din-25425-3-2019-12-md.md].

### Utilities and Waste Management
*   **Residual Waste:** Radioactive residual materials (*Reststoffe*) exceeding 10⁴ times the release limit must be stored in non-combustible, tightly sealed storage facilities during interim storage until handover to the regional collection point or third parties [summary-din-25425-3-2019-12-md.md]. The required fire resistance for the residual material room must be determined according to Table 2 and referencing DIN 25422 [summary-din-25425-3-2019-12-md.md].
*   **Utilities:** Necessary passages for cables, pipelines, residual material shafts, or ventilation ducts must be executed in a fire-resistant manner according to Table 2 [summary-din-25425-3-2019-12-md.md].

## Personal Protection Rules (DIN 25425-4)
In addition to structural and fire safety, the standard mandates specific rules for the protection of personnel (*Personenschutz*) [summary-din-25425-4-2019-12-md-teil-2-2.md]. These rules focus on minimizing occupational exposure:

*   **Exposure Minimization:** Procedures must be designed to minimize the time spent near sources and maximize the distance between personnel and radioactive materials [summary-din-25425-4-2019-12-md-teil-2-2.md].
*   **Containment:** Handling procedures must utilize appropriate containment measures (e.g., fume hoods, glove boxes) to prevent the spread of contamination and limit inhalation/ingestion risks [summary-din-25425-4-2019-12-md-teil-2-2.md].
*   **Monitoring:** Personnel must be subject to regular monitoring. This includes:
    *   **Dosimetry:** Implementation of personal dosimetry systems to track cumulative radiation doses received by individuals [summary-din-25425-4-2019-12-md-teil-2-2.md].
    *   **Contamination Checks:** Regular monitoring of personnel and equipment for radioactive contamination is required [summary-din-25425-4-2019-12-md-teil-2-2.md].