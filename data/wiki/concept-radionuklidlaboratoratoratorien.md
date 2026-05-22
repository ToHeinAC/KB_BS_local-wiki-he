---
confidence: high
created: '2026-05-21'
related:
- concept-radiation-protection-law.md
- concept-strahlenschutzverordnung-strlschv.md
- concept-kontaminierte-abfaelle.md
- concept-radioactive-stoffe.md
- concept-radiation-protection.md
- concept-professional-exposure.md
- concept-radiation-dose-limits.md
sources:
- DIN 25425-1_2021-05 .md [Teil 1/2]
- DIN 25425-1_2021-05 .md
- summary-din-25425-3-2019-12-md.md
- DIN 25425-3_2019-12.md
- summary-din-25425-4-2019-12-md-teil-1-2.md
- DIN 25425-4_2019-12.md [Teil 1/2]
- DIN 25425-4_2019-12.md
- DIN 25425-5_2024-12.md
title: Radionuclide Laboratories
type: concept
updated: '2026-05-21'
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

## Personal Protection (DIN 25425-4)
The standard DIN 25425-4 provides detailed rules for personal protection in radionuclide laboratories, supplementing the structural requirements of DIN 25425-1 and fire protection of DIN 25425-3.

### Operational Safety and Monitoring
*   **Legal Basis:** The foundation for handling radioactive substances is the *Strahlenschutzgesetz* (StrlSchG) and the *Strahlenschutzverordnung* (StrlSchV) [summary-din-25425-4-2019-12-md-teil-1-2.md].
*   **Exposure Monitoring:** For external exposure, the body dose is generally measured using official personal dosimeters [summary-din-25425-4-2019-12-md-teil-1-2.md].
*   **Personnel Classification:** Personnel are classified into Category A or Category B based on expected exposure. Category A personnel require annual medical monitoring [summary-din-25425-4-2019-12-md-teil-1-2.md].
*   **Pregnancy:** Handling open radioactive substances is prohibited for pregnant or breastfeeding women, as internal incorporation cannot be ruled out [summary-din-25425-4-2019-12-md-teil-1-2.md].

### Contamination Control
*   During activities with open radioactive substances, the possibility of checking clothing, body, and work materials for contamination must exist [summary-din-25425-4-2019-12-md-teil-1-2.md].
*   If contamination is suspected on accessible traffic areas, an immediate contamination check must be performed [summary-din-25425-4-2019-12-md-teil-1-2.md].
*   The documentation of personal contamination incidents is required for 30 years (for significant contamination without limit exceedance) [summary-din-25425-4-2019-12-md-teil-1-2.md].

### Documentation Requirements
The documentation of radiation protection must adhere to the StrlSchG and StrlSchV. The required records include:
*   Personal dosimetry measurements (75 years after birth, but min. 30 years after employment end) [summary-din-25425-4-2019-12-md-teil-1-2.md].
*   Incorporated activity (75 years after birth, but min. 30 years after employment end) [summary-din-25425-4-2019-12-md-teil-1-2.md].
*   Radioactive waste/residues (30 years) [summary-din-25425-4-2019-12-md-teil-1-2.md].

## Decontamination of Surfaces (DIN 25425-5)
The management of surface contamination is governed by DIN 25425-5, which provides detailed rules for decontamination procedures.

### Scope and Principles
This standard sets general rules for decontamination measures for both adherent and non-adherent surface contaminations, aiming to allow the reuse of rooms, work surfaces, and objects [summary-din-25425-5-2024-12.md]. The principles of contamination behavior are detailed, distinguishing between mechanical adhesion, adsorption, ion exchange, and diffusion [summary-din-25425-5-2024-12.md].

### Decontamination Procedures
The procedures are categorized based on whether material removal is necessary:

**1. Procedures without Material Removal:**
These are suitable for contamination that is mechanically adhered, embedded in dirt layers, or physically/chemically adsorbed [summary-din-25425-5-2024-12.md].
*   **Dry Mechanical:** Vacuuming with exhaust filtration (minimum H13 efficiency per DIN EN 1822-1:2019-10) is used for dust/particles. Adhesive films can be used for weak contamination [summary-din-25425-5-2024-12.md].
*   **Wet Mechanical:** Water with additives like tensides is used. Mechanical support can involve soft plastic brushes or floor polishing machines with vacuuming [summary-din-25425-5-2024-12.md]. Ultrasound can improve cleaning, especially on rough surfaces, using a shaking bath or encapsulated sonotrode [summary-din-25425-5-2024-12.md].
*   **Wet Chemical:** Use aqueous solutions of surfactant mixtures, alcohols, complexing agents, or organic acids. These must be supplemented with mechanical support [summary-din-25425-5-2024-12.md].

**2. Procedures with Material Removal:**
These are required if contamination is deeply embedded in pores, cracks, or gaps, embedded in corrosion layers, or diffused in surfaces [summary-din-25425-5-2024-12.md].
*   **Mechanical:** Includes cutting, milling, planing, or grinding. These must be equipped with a vacuum system. The removal depth is limited to 1 mm [summary-din-25425-5-2024-12.md].
*   **Chemical:** Use solutions of alkalis, acids, redox chemicals, or complexing agents. The surface must be carefully rinsed, neutralized, and possibly passivated after treatment [summary-din-25425-5-2024-12.md].
*   **Electrochemical:** Applicable only to metal objects. Electro-polishing uses dilute acids or mixtures thereof (usually phosphoric and sulfuric acid) to achieve a polished surface. Electro-decontaminating uses dilute acids or salt solutions, which is generally preferred due to less material removal [summary-din-25425-5-2024-12.md].

### Selection and Measurement
The selection of procedures must consider personnel exposure, risks from hazardous substances (GefStoffV), waste disposal, decontamination effect, minimal surface damage, and time required [summary-din-25425-5-2024-12.md].

Measurement of surface contamination can be done by direct and indirect methods. Indirect methods (like wipe tests) are associated with uncertainties and can only allow for a conservative estimate. For compliance outside radiation protection areas, adherent contamination can be disregarded [summary-din-25425-5-2024-12.md].

## Literature References
The standard references several other DIN documents, including:
*   DIN 25425-1 (Rules for the Design);
*   DIN 25425-3 (Rules for Preventive Fire Protection);
*   DIN 25425-4 (Rules for Personal Protection);
*   DIN 25430 (Safety Marking in Radiation Protection);
*   DIN ISO 7503-1, DIN ISO 7503-2, DIN ISO 7503-3 (Measurement and Evaluation of Surface Contamination).