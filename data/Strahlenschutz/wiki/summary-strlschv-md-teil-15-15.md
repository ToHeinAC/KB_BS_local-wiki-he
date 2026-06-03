---
confidence: high
created: '2026-05-17'
related:
- concept-effective-dose-calculation.md
- concept-radiation-weighting-factor.md
- concept-tissue-weighting-factor.md
- concept-quality-factor.md
- concept-röntgeneinrichtung.md
- concept-medizinphysik-experte.md
sources:
- StrlSchV.md [Teil 15/15]
- StrlSchV.md
title: Strahlenschutzverordnung - StrlSchV (Teil 15/15)
type: source-summary
updated: '2026-05-17'
---

This document provides highly detailed technical annexes and guidelines derived from the *Strahlenschutzverordnung* (StrlSchV), covering advanced dosimetry calculations, weighting factors, and the specific qualification requirements for radiation safety experts.

## Dosimetry Calculations
The source details the calculation of effective dose, particularly considering the follow-up dose ($E(\tau)$) resulting from radionuclides remaining in the body after the reference point [StrlSchV.md [Teil 15/15].md].

*   **Effective Follow-up Dose ($E(\tau)$):** This is the sum of the follow-up organ equivalent doses ($H_T(\tau)$) multiplied by the corresponding tissue weighting factor ($w_T$) [StrlSchV.md [Teil 15/15].md].
*   **Time Period ($\tau$):** For adults, the integration period is set at 50 years; for children, it is from the respective age until age 70, unless another value is specified [StrlSchV.md [Teil 15/15].md].
*   **Dose Calculation Methods:**
    *   **Inhalation of Radon at Workplaces:** An effective dose of 1 millisievert is assumed from:
        a) A Radon-222 exposure of 0.32 Megabecquerel per cubic meter per hour, using a balance factor of 0.4 between Radon-222 and its short-lived decay products, OR
        b) A potential Alpha energy exposure of 0.71 millijoule per cubic meter per hour [StrlSchV.md [Teil 15/15].md].
    *   **Incorporation, Submersion, or Soil Contamination:** Dose coefficients and guidelines must be drawn from specific publications in the *Bundesanzeiger* (e.g., No. 160 a and b from August 28, 2001, Part I and Part II, and the *Bundesanzeiger* of May 10, 2023) [StrlSchV.md [Teil 15/15].md].
    *   **Unborn Child:** Specific dose coefficients are required for external exposure (using the *Bundesanzeiger* announcement of April 17, 2023, BAnz AT 10. Mai 2023 B6) and for internal exposure due to radionuclide incorporation [StrlSchV.md [Teil 15/15].md].

## Weighting Factors
The source defines three critical weighting factors used in dosimetry:

### 1. Radiation Weighting Factor ($w_R$)
These values depend on the type and quality of the external radiation field or the radiation emitted by an incorporated radionuclide [StrlSchV.md [Teil 15/15].md]:
| Radiation Type | Radiation Weighting Factor ($w_R$) |
| :--- | :--- |
| Photons | 1 |
| Electrons and Muons | 1 |
| Protons and Charged Pions | 2 |
| Alpha particles, Fragment particles, Heavy Ions | 20 |
| Neutrons, Energy $E_n < 1$ | |
| Neutrons, $1 \le \text{Energy } E_n \le 50$ | |
| Neutrons, Energy $E_n > 50$ | |

### 2. Tissue Weighting Factor ($w_T$)
These factors are used for calculating the effective dose [StrlSchV.md [Teil 15/15].md]:
| Tissue or Organ | Tissue Weighting Factor ($w_T$) |
| :--- | :--- |
| 1. Red Bone Marrow | 0.12 |
| 2. Large Intestine | 0.12 |
| 3. Lungs | 0.12 |
| 4. Stomach | 0.12 |
| 5. Breast | 0.12 |
| 6. Gonads | 0.08 |
| 7. Bladder | 0.04 |
| 8. Esophagus | 0.04 |
| 9. Liver | 0.04 |
| 10. Thyroid | 0.04 |
| 11. Skin | 0.01 |
| 12. Bone Surface | 0.01 |
| 13. Brain | 0.01 |
| 14. Salivary Glands | 0.01 |
| 15. Other Organs or Tissues | 0.12 |

### 3. Quality Factor ($Q$)
The values for the Quality Factor $Q$ (according to ICRP 2007) depend on the unconstrained linear energy transfer potential $L$ in water [StrlSchV.md [Teil 15/15].md]:
| $L$ | $Q(L)$ |
| :--- | :--- |
| $< 10$ | 1 |
| $10 \le L \le 100$ | $0.32 \cdot L^{-2.2}$ |
| $L > 100$ | $300/\sqrt{L}$ |

## Qualification for Experts (Sachverständige)
The source provides detailed tables outlining the required number of examinations for acquiring and maintaining the professional qualification for radiation safety experts ($\text{Sachverständige}$) according to $\S 172$ of the Radiation Protection Act (StrlSchG) [StrlSchV.md [Teil 15/15].md].

**Table 1: Examinations for Qualification under $\S 172$ Paragraph 1 Sentence 1 Number 1, 3, and 4 StrlSchG**
*   **A Medical and Dental X-ray Equipment:**
    *   *Acquisition:* Requires examination of 1 fixed and 1 mobile X-ray device.
    *   *Maintenance:* Requires examination of 1.1 and 1.2 devices.
*   **A 2 Fluoroscopy Equipment:**
    *   *Acquisition:* 30 systems; *Maintenance:* 15 systems.
*   **A 3 CT Equipment:**
    *   *Acquisition:* 10 systems; *Maintenance:* 5 systems.
*   **B Non-Medical X-ray Equipment and Scatter Sources:**
    *   *B 1 Fine and Coarse Structure Examination Equipment:* *Acquisition:* 20 systems; *Maintenance:* 10 systems.
    *   *B 2 High-, Full-Protection, and Basic Protection Equipment and School X-ray Equipment:* *Acquisition:* 5 systems; *Maintenance:* 2 systems.

**Table 2: Examinations for Qualification under $\S 172$ Paragraph 1 Sentence 1 Number 2 StrlSchG**
*   This table details requirements for various systems (D, E, F), including medical systems (D 1, D 2) and non-medical systems (E 1, E 2, E 2a, E 3, E 4), specifying the required number of examinations for acquisition and maintenance.
