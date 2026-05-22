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
title: 'DIN 25425-1 Radionuklidlaboratorien – Teil 1: Regeln für die Auslegung'
type: source-summary
updated: '2026-05-21'
---

The DIN 25425-1:2021-05 standard, titled *Radionuklidlaboratorien – Teil 1: Regeln für die Auslegung* (Rules for the design of radionuclide laboratories), provides guidelines for the architectural and technical planning of laboratories handling open radioactive substances. It serves as a guide for planners, builders, operators, assessors, and authorities [DIN 25425-1_2021-05 .md [Teil 1/2].md].

## Scope and Applicability
This document applies to the design of radionuclide laboratories where open radioactive substances are handled, and for the design of functionally required special rooms [DIN 25425-1_2021-05 .md [Teil 1/2].md].
*   **Exclusion:** Requirements for radionuclides handled in closed systems are not covered by this document.
*   **Exemption:** The document is not applicable if the release limits according to StrlSchV, Annex 4, Table 1, Column 2, are undercut when considering open radioactive substances, taking into account the sum formula [DIN 25425-1_2021-05 .md [Teil 1/2].md].
*   **Related Standards:** Specific requirements for storage are governed by DIN 25422. For hot cells, DIN 25420-1/2 and DIN 25422 are required.

## Key Definitions
The standard defines several critical terms for facility planning:
*   **Radionuklidlaboratorium:** An area, consisting of one or more rooms, used for handling open radioactive substances above the release limit [DIN 25425-1_2021-05 .md [Teil 1/2].md].
*   **Reststoff (Residual Material):** Radioactive substances, dismantled or decommissioned components, building debris, and collected soil, as well as movable objects that are contaminated or activated, for which the recycling or disposal route has not yet been decided, until it is determined that they belong to radioactive waste [DIN 25425-1_2021-05 .md [Teil 1/2].md].

## Technical Radiation Protection Requirements
The standard mandates protection measures against external exposure, internal exposure, and contamination [DIN 25425-1_2021-05 .md [Teil 1/2].md].

### 1. Protection Against External Exposure
Protection against external exposure must generally be ensured by shielding, distance from the radiation source, and limitation of stay time in the radiation field. Since the distance to the radiating substance is small during manual handling, shielding is generally required [DIN 25425-1_2021-05 .md [Teil 1/2].md].

### 2. Protection Against Internal Exposure and Contamination
This requires specialized ventilation, fume hoods, and closed working cells, such as glove boxes or process cells (referencing DIN 25412-1 or DIN 25481) [DIN 25425-1_2021-05 .md [Teil 1/2].md]. Environmental protection requires controlled exhaust and wastewater management, and contamination prevention via airlocks [DIN 25425-1_2021-05 .md [Teil 1/2].md].

## Room Classification (Raumkategorie)
The risk of internal exposure and contamination determines the Room Category ($R_K$) [DIN 25425-1_2021-05 .md [Teil 1/2].md]. The classification depends on the simultaneously handled activity and the handling method.

The Assessment Factor ($K$) is calculated using:
$$
K = \frac{a_{k}A}{R} \cdot JAZ \quad (1)
$$
or for multiple radionuclides:
$$
K = \sum_{i=1}^{n} \frac{a_{ki}}{A_i} \cdot R \cdot JAZ_i \quad (2)
$$
Where:
*   $a_{ki}$ is the proportion of the handled activity of the i-th radionuclide that can be maximally incorporated during the most unfavorable work process without considering technical protective measures (Incorporation Factor).
*   $A_i$ is the planned maximum handled activity of the i-th radionuclide in a room.
*   $R \cdot JAZ$ refers to the Reference Value for Annual Activity Supply (RJAZ).

The Room Category is assigned based on $K$:
| Bewertungsfaktor K | Raumkategorie |
| :--- | :--- |
| $K \le 10^{-4}$ | RK0 |
| $10^{-4} < K \le 10^{-2}$ | RK1 |
| $10^{-2} < K \le 100$ | RK2 |
| $100 < K \le 10^2$ | RK3 |

## Facility Planning and Utilities
### Ventilation (Luftführung)
*   **General:** Ventilation design must consider the potential hazard associated with the inhalation of radioactive substances. Applicable standards include DIN EN 12792, DIN EN 16798-3, DIN 1946-4, DIN 1946-6, DIN 1946-7, and DIN ISO 2889 [DIN 25425-1_2021-05 .md [Teil 1/2].md].
*   **Flow Direction:** A constant airflow must be maintained from areas of low contamination risk to those of higher risk.
*   **Exhaust/Supply:** For RK2 and RK3, the exhaust flow must be directed to a dedicated exhaust system, which cannot be connected to other exhaust systems.
*   **Filtration:** For RK2 and RK3, the possibility of retrofitting exhaust filtration must be provided during the structural design. Filters must meet standards like DIN EN ISO 16890-1 (Vorfilter $\ge$ ISO ePM2,5) and DIN EN 1822-1 (Schwebstofffilter $\ge$ H13).

### Wastewater (Abwasserführung)
*   **Classification:** Wastewater is classified as either largely contamination-free or radioactively contaminated [DIN 25425-1_2021-05 .md [Teil 1/2].md].
*   **Separation:** If both types of wastewater occur, the systems must be separated.
*   **Contaminated Water:** Radioactively contaminated wastewater must be collected to determine the further procedure (e.g., disposal route, decay storage, balancing) [DIN 25425-1_2021-05 .md [Teil 1/2].md].
*   **System Requirements:** The network for radioactively contaminated wastewater must be accessible for visual and tightness tests and must be marked clearly [DIN 25425-1_2021-05 .md [Teil 1/2].md].
