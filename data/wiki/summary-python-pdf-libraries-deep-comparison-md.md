---
confidence: high
created: '2026-05-18'
description: Python PDF Libraries Deep Comparison vom 07.05.2026
effective as of: 07.05.2026
fullname: Python PDF Libraries Deep Comparison
name: Python PDF Libraries
related:
- software-licensing.md
sources:
- Python PDF Libraries Deep Comparison.md
title: Python PDF Libraries Deep Comparison
type: source-summary
updated: '2026-05-18'
---

# Python PDF Libraries: Deep Comparison — PyMuPDF vs. pypdfium2 vs. pdfplumber vs. pdfminer.six vs. pypdf

This report compares five major Python libraries used for PDF processing: PyMuPDF, pypdfium2, pdfplumber, pdfminer.six, and pypdf. The comparison covers licensing, performance benchmarks, feature sets, and deployment considerations for production use [Python PDF Libraries Deep Comparison.md].

## Overview

The five libraries analyzed each possess distinct strengths, licensing terms, and performance profiles. A primary focus of the comparison is on licensing constraints, particularly noting that **PyMuPDF's AGPL-3.0** is a key factor driving developers to seek alternatives [Python PDF Libraries Deep Comparison.md].

## 1. License & Commercial Use

The licensing terms are highlighted as the most critical dimension for many projects.

| Library | License | Commercial Use | Server-Side Use | Source Disclosure Required |
| :--- | :--- | :--- | :--- | :--- |
| **PyMuPDF** | AGPL-3.0 | ❌ Requires paid license from Artifex [Python PDF Libraries Deep Comparison.md] | ❌ Must open-source or buy commercial license [Python PDF Libraries Deep Comparison.md] | ✅ Yes, under AGPL [Python PDF Libraries Deep Comparison.md] |
| **pypdfium2** | Apache-2.0 or BSD-3-Clause | ✅ Free [Python PDF Libraries Deep Comparison.md] | ✅ Free [Python PDF Libraries Deep Comparison.md] | ❌ No |
| **pdfplumber** | MIT | ✅ Free [Python PDF Libraries Deep Comparison.md] | ✅ Free [Python PDF Libraries Deep Comparison.md] | ❌ No |
| **pdfminer.six** | MIT/X | ✅ Free [Python PDF Libraries Deep Comparison.md] | ✅ Free [Python PDF Libraries Deep Comparison.md] | ❌ No |
| **pypdf** | BSD-3-Clause | ✅ Free [Python PDF Libraries Deep Comparison.md] | ✅ Free [Python PDF Libraries Deep Comparison.md] | ❌ No |

**Key AGPL implication**: Any software using PyMuPDF must either be released as free, open-source software (AGPL-compliant), or acquire a commercial license from Artifex. This obligation applies transitively, meaning if an application depends on a library that depends on PyMuPDF, the application may still be subject to AGPL obligations [Python PDF Libraries Deep Comparison.md].

## 2. Performance Benchmarks

Benchmarks were conducted using the `py-pdf/benchmarks` repository across 14 real-world PDFs on an Intel Core i7-6700HQ [Python PDF Libraries Deep Comparison.md].

### Text Extraction Speed (average across 14 docs)

*   **PyMuPDF**: 0.1s [Python PDF Libraries Deep Comparison.md] (baseline)
*   **pypdfium2**: 0.1s [Python PDF Libraries Deep Comparison.md] (~on par)
*   **pypdf**: 3.5s [Python PDF Libraries Deep Comparison.md] (~35× slower)
*   **pdfminer.six**: 5.8s [Python PDF Libraries Deep Comparison.md] (~58× slower)
*   **pdfplumber**: 9.5s [Python PDF Libraries Deep Comparison.md] (~95× slower)

**pypdfium2** is noted as being essentially tied with PyMuPDF for text extraction speed [Python PDF Libraries Deep Comparison.md].

### Text Extraction Quality (accuracy %, average)

*   **pypdfium2**: 97% [Python PDF Libraries Deep Comparison.md]
*   **pypdf**: 96% [Python PDF Libraries Deep Comparison.md]
*   **PyMuPDF**: 96% [Python PDF Libraries Deep Comparison.md]
*   **pdfminer.six**: 89% [Python PDF Libraries Deep Comparison.md]
*   **pdfplumber**: 75% [Python PDF Libraries Deep Comparison.md]

Notably, **pypdfium2** achieves slightly higher text extraction accuracy than PyMuPDF (97% vs. 96%) while maintaining comparable speed and using a permissive license [Python PDF Libraries Deep Comparison.md].

## 3. Feature Matrix

The comparison details various features:

*   **Text extraction**: PyMuPDF, pypdfium2, pdfplumber, pdfminer.six, and pypdf all offer text extraction, with pdfplumber noted for its "Best-in-class" table extraction [Python PDF Libraries Deep Comparison.md].
*   **Table extraction**: Only **pdfplumber** is listed as having "Best-in-class" table extraction [Python PDF Libraries Deep Comparison.md].
*   **Page rendering (to image)**: PyMuPDF is listed as having the "Best" capability [Python PDF Libraries Deep Comparison.md].
*   **Bounding box / layout data**: PyMuPDF, pypdfium2, pdfplumber, pdfminer.six, and pypdf can all provide this data [Python PDF Libraries Deep Comparison.md].

## 4. Dependencies & Deployment

| Library | Pure Python | C / Native Bindings | System Dependencies | Binary Size |
| :--- | :--- | :--- | :--- | :--- |
| **PyMuPDF** | ❌ | C (MuPDF) [Python PDF Libraries Deep Comparison.md] | None extra | Large (~40 MB wheel) [Python PDF Libraries Deep Comparison.md] |
| **pypdfium2** | ❌ | C (PDFium/Chromium) [Python PDF Libraries Deep Comparison.md] | None extra; prebuilt wheels | Large (~40 MB wheel) [Python PDF Libraries Deep Comparison.md] |
| **pdfplumber** | ✅ | None [Python PDF Libraries Deep Comparison.md] | None | Small [Python PDF Libraries Deep Comparison.md] |
| **pdfminer.six** | ✅ | None [Python PDF Libraries Deep Comparison.md] | None | Small [Python PDF Libraries Deep Comparison.md] |
| **pypdf** | ✅ | None [Python PDF Libraries Deep Comparison.md] | None (crypto optional) | Small [Python PDF Libraries Deep Comparison.md] |

Pure-Python alternatives (pdfplumber, pdfminer.six, pypdf) deploy anywhere without build tools, including serverless environments [Python PDF Libraries Deep Comparison.md].

## 5. Community & Maintenance (as of May 2026)

PyMuPDF has the largest community by far. pypdfium2 has a smaller but active maintainer team. pypdf had a DoS vulnerability fixed in v6.7.2 (CVE-2026-27628) [Python PDF Libraries Deep Comparison.md].

## Conclusion

For commercial or proprietary projects seeking a PyMuPDF replacement, **pypdfium2 is identified as the strongest alternative** because it matches PyMuPDF's speed, slightly exceeds it in text accuracy, and is licensed under Apache 2.0 / BSD-3-Clause [Python PDF Libraries Deep Comparison.md].

For specialized needs, the combination of **pypdfium2 + pdfplumber** is recommended for covering most use cases (fast text + rendering + table extraction) without AGPL exposure [Python PDF Libraries Deep Comparison.md].
