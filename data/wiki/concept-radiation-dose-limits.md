---
related:
- professional-exposure
- public-exposure
- concept-radiation-protection-law.md
sources:
- StrlSchG.md [Teil 6/13]
- StrlSchG.md
- StrlSchV.md
title: Radiation Dose Limits
type: concept
updated: '2026-05-17'
---

# Radiation Dose Limits

Radiation Dose Limits are legally established maximum permissible levels of radiation energy absorbed by the body or specific organs, designed to minimize health risks from ionizing radiation. These limits differ significantly based on whether the exposure is professional or public.

## Key Limits (Per Calendar Year)
| Exposure Type | Dose Type | Limit | Notes |
| :--- | :--- | :--- | :--- |
| **Professional** | Effective Dose (General) | 20 mSv | Competent authority may permit 50 mSv in one year, provided 100 mSv is not exceeded over five years [StrlSchG.md [Teil 6/13].md]. |
| **Professional** | Eye Lens (Organ) | 20 mSv | [StrlSchG.md [Teil 6/13].md]. |
| **Professional** | Local Skin Dose (Organ) | 500 mSv | [StrlSchG.md [Teil 6/13].md]. |
| **Professional** | Extremities (Organ) | 500 mSv | Applies individually to hands, forearms, feet, and ankles [StrlSchG.md [Teil 6/13].md]. |
| **Public** | Effective Dose (Sum) | 1 mSv | For individuals in the general population [StrlSchG.md [Teil 6/13].md]. |
| **Public** | Eye Lens (Organ) | 15 mSv | For individuals in the general population [StrlSchG.md [Teil 6/13].md]. |
| **Public** | Local Skin Dose (Organ) | 50 mSv | For individuals in the general population [StrlSchG.md [Teil 6/13].md]. |

*Note: Limits for minors and pregnant women are also specified in the law [StrlSchG.md [Teil 6/13].md].*

## Detailed Measurement and Calculation (StrlSchV)
The *Strahlenschutzverordnung* (StrlSchV) specifies highly detailed methodologies for measuring and calculating doses:

### Measurement Quantities for External Radiation (Anlage 18)
For external radiation, specific person doses are defined:
*   **Depth-person dose $H_p(10)$:** Equivalent dose in 10 millimeters depth at the location of the dosimeter [StrlSchV.md [Teil 14/15].md].
*   **Eye lens-person dose $H_p(3)$:** Equivalent dose in 3 millimeters depth at the location of the dosimeter [StrlSchV.md [Teil 14/15].md].
*   **Surface-person dose $H_p(0.07)$:** Equivalent dose in 0.07 millimeters depth at the location of the dosimeter [StrlSchV.md [Teil 14/15].md].
For site doses, measurements include Ambient equivalent dose $H^*(10)$, directional equivalent dose in 3 mm depth $H'(3,\Omega)$, and directional equivalent dose in 0.07 mm depth $H'(0,07,\Omega)$ [StrlSchV.md [Teil 14/15].md].

### Calculation of Body Dose
1. **Organ Equivalent Dose $H_T$:** Calculated as the product of the mean energy dose $D_{T,R}$ in the tissue or organ $T$ and the radiation weighting factor $w_R$: $H_{T,R} = w_R D_{T,R}$ [StrlSchV.md [Teil 14/15].md].
2. **Effective Dose $E$:** This is the weighted mean of organ equivalent doses, considering the radiation sensitivity of various organs or tissues via weighting factors $w_T$ [StrlSchV.md [Teil 14/15].md].

## Significance Criteria (StrlSchV)
The *Verordnung* establishes criteria for determining when an exposure situation is significant, covering:
*   **Planned Exposure:** Criteria include exceeding dose limits for professionals or the general population, or exceeding permissible derivation limits for radioactive substances in air or water [StrlSchV.md [Teil 14/15].md].
*   **Interventions:** Specific dose-area product thresholds (e.g., 20,000 Centigray-cm² for investigation, 50,000 Centigray-cm² for treatment) are defined [StrlSchV.md [Teil 14/15].md].
