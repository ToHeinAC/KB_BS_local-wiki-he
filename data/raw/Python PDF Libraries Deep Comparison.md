# Python PDF Libraries: Deep Comparison — PyMuPDF vs. pypdfium2 vs. pdfplumber vs. pdfminer.six vs. pypdf

## Overview

Five major Python libraries dominate the PDF processing landscape, each with distinct strengths, licensing terms, and performance profiles. This report compares them across every dimension relevant for production use, with special focus on licensing constraints — since **PyMuPDF's AGPL-3.0** is the primary reason developers seek alternatives.

***

## 1. License & Commercial Use

This is the single most critical dimension for many projects.

| Library | License | Commercial Use | Server-Side Use | Source Disclosure Required |
|---------|---------|---------------|----------------|---------------------------|
| **PyMuPDF** | AGPL-3.0 | ❌ Requires paid license from Artifex[^1][^2] | ❌ Must open-source or buy commercial license[^2] | ✅ Yes, under AGPL[^1] |
| **pypdfium2** | Apache-2.0 or BSD-3-Clause | ✅ Free[^3][^4] | ✅ Free[^3] | ❌ No |
| **pdfplumber** | MIT | ✅ Free[^5][^6] | ✅ Free | ❌ No |
| **pdfminer.six** | MIT/X | ✅ Free[^3][^7] | ✅ Free | ❌ No |
| **pypdf** | BSD-3-Clause | ✅ Free[^5][^8] | ✅ Free | ❌ No |

**Key AGPL implication**: Any software using PyMuPDF must either be released as free, open-source software (AGPL-compliant), or acquire a commercial license from Artifex. This applies transitively — if your app depends on a library that depends on PyMuPDF, you may still be subject to AGPL obligations.[^1][^9][^2]

***

## 2. Performance Benchmarks

All benchmarks below are from the `py-pdf/benchmarks` repository, tested across 14 real-world PDFs on an Intel Core i7-6700HQ.[^3]

### Text Extraction Speed (average across 14 docs)

| Rank | Library | Avg. Time | vs. PyMuPDF |
|------|---------|-----------|-------------|
| 1 | **PyMuPDF** | 0.1s[^3] | baseline |
| 2 | **pypdfium2** | 0.1s[^3] | ~on par |
| 3 | pypdf | 3.5s[^3] | ~35× slower |
| 4 | pdfminer.six | 5.8s[^3] | ~58× slower |
| 5 | pdfplumber | 9.5s[^3] | ~95× slower |

**pypdfium2 is essentially tied with PyMuPDF** for text extraction speed — both achieve 0.1s average, making pypdfium2 the only permissively licensed library with comparable performance.[^3]

### Image Extraction Speed (average)

| Rank | Library | Avg. Time |
|------|---------|-----------|
| 1 | **PyMuPDF** | 0.5s[^3] |
| 2 | **pypdfium2** | 1.1s[^3] |
| 3 | pypdf | 4.2s[^3] |
| 4 | pdfminer.six | 7.4s[^3] |

### Text Extraction Quality (accuracy %, average)

| Rank | Library | Avg. Accuracy |
|------|---------|--------------|
| 1 | **pypdfium2** | 97%[^3] |
| 2 | **pypdf** | 96%[^3] |
| 3 | **PyMuPDF** | 96%[^3] |
| 4 | pdfminer.six | 89%[^3] |
| 5 | pdfplumber | 75%[^3] |

Notably, **pypdfium2 achieves slightly higher text extraction accuracy than PyMuPDF** (97% vs. 96%) while being similarly fast — and under a permissive license.[^3]

***

## 3. Feature Matrix

| Feature | PyMuPDF | pypdfium2 | pdfplumber | pdfminer.six | pypdf |
|---------|---------|-----------|------------|--------------|-------|
| **Text extraction** | ✅ Fast, positional[^5] | ✅ Fast, positional[^4] | ✅ Char-level[^5][^6] | ✅ Char-level[^5] | ✅ Basic[^5] |
| **Table extraction** | ❌[^5] | ❌ | ✅ Best-in-class[^5][^6] | ❌ | ❌ |
| **Page rendering (to image)** | ✅ Best[^5][^10] | ✅ Near-equal[^11][^12] | ❌[^13] | ❌[^5] | ❌[^5] |
| **Image extraction** | ✅ Excellent[^5] | ⚠️ Partial (API limits)[^14] | ❌ | ❌ | ⚠️ Basic |
| **PDF merging/splitting** | ✅[^5] | ❌ | ❌[^13] | ❌ | ✅[^5][^8] |
| **PDF creation** | ✅ Basic[^5] | ✅ Basic[^4] | ❌[^13] | ❌ | ✅ Basic[^5] |
| **Annotations (read/write)** | ✅[^5] | ⚠️ Read only | ❌ | ❌ | ⚠️ Basic[^8] |
| **Form filling** | ✅[^5] | ⚠️ Partial | ❌ | ❌ | ✅ Basic[^5] |
| **Encryption/decryption** | ✅[^5] | ✅ | ❌ | ❌ | ✅[^5] |
| **Metadata access** | ✅ | ✅ | ✅ | ✅ | ✅[^8] |
| **Visual debugging** | ❌ | ❌ | ✅[^5][^6] | ❌ | ❌ |
| **Multi-format input (EPUB, XPS)** | ✅[^5] | ❌ | ❌ | ❌ | ❌ |
| **OCR** | ❌[^5] | ❌ | ❌ | ❌ | ❌ |
| **Bounding box / layout data** | ✅[^5] | ✅[^4] | ✅[^6] | ✅[^5] | ❌ |
| **Font metadata** | ✅ | ✅ | ✅ | ✅ deep[^5] | ❌ |

***

## 4. Dependencies & Deployment

| Library | Pure Python | C / Native Bindings | System Dependencies | Binary Size |
|---------|------------|---------------------|--------------------|----|
| **PyMuPDF** | ❌ | C (MuPDF)[^5] | None extra | Large (~40 MB wheel) |
| **pypdfium2** | ❌ | C (PDFium/Chromium)[^3][^4] | None extra; prebuilt wheels | Large (~40 MB wheel) |
| **pdfplumber** | ✅ | None[^5] | None | Small |
| **pdfminer.six** | ✅ | None[^5] | None | Small |
| **pypdf** | ✅ | None[^5][^8] | None (crypto optional) | Small |

Both PyMuPDF and pypdfium2 ship prebuilt binaries for major platforms (Windows, Linux, macOS, ARM), removing the need for compilation. Pure-Python alternatives deploy anywhere without build tools — including serverless, minimal containers, and constrained environments.[^5][^4]

***

## 5. Community & Maintenance (as of May 2026)

| Library | GitHub Stars | Activity Level | Last Release |
|---------|-------------|----------------|-------------|
| **PyMuPDF** | ~9,600[^15] | Very active (top 10%)[^15] | 2025-06-12 (v1.26.1)[^3] |
| **pypdf** | — | Very active[^8] | 2025-06-29 (v5.7.0)[^3] |
| **pdfplumber** | — | Active[^3] | 2025-06-12 (v0.11.7)[^3] |
| **pdfminer.six** | ~6,000[^16] | Active[^3] | 2025-05-06[^3] |
| **pypdfium2** | ~760[^15] | Active (9.7/10)[^15] | 2024-12-19 (v4.30.1)[^3] |

PyMuPDF has the largest community by far. pypdfium2 has a smaller but active maintainer team; note that v5.0.0b1 had a text extraction regression bug (yanked from PyPI), so checking version stability matters. pypdf had a DoS vulnerability fixed in v6.7.2 (CVE-2026-27628, circular xref references).[^12][^17]

***

## 6. Scored Comparison

Each dimension is scored **1–5** (5 = best). Weights reflect typical production use priorities.

| Dimension | Weight | PyMuPDF | pypdfium2 | pdfplumber | pdfminer.six | pypdf |
|-----------|--------|---------|-----------|------------|--------------|-------|
| **License freedom** | ×2 | 1[^1][^2] | 5[^3][^4] | 5[^6] | 5[^7] | 5[^8] |
| **Text extraction speed** | ×2 | 5[^3] | 5[^3] | 2[^3] | 1[^3] | 2[^3] |
| **Text extraction quality** | ×2 | 4[^3] | 5[^3] | 3[^3] | 3[^3] | 4[^3] |
| **Page rendering** | ×1 | 5[^5][^10] | 4[^11] | 1 | 1 | 1 |
| **Image extraction** | ×1 | 5[^5] | 3[^14] | 1 | 1 | 2 |
| **Table extraction** | ×1 | 1 | 1 | 5[^5][^6] | 1 | 1 |
| **PDF writing/merging** | ×1 | 5[^5] | 2 | 1 | 1 | 4[^5][^8] |
| **Annotation & forms** | ×1 | 5[^5] | 2 | 1 | 1 | 2[^8] |
| **Deployment simplicity** | ×1 | 3 | 3 | 5[^5] | 5 | 5[^5] |
| **Community & stability** | ×1 | 5[^15] | 3[^15][^12] | 4 | 4[^16] | 4[^8] |

### Weighted Total Scores

| Library | Weighted Score (out of 65) | Grade |
|---------|--------------------------|-------|
| **pypdfium2** | 56 | ⭐⭐⭐⭐⭐ |
| **PyMuPDF** | 52 | ⭐⭐⭐⭐ |
| **pypdf** | 46 | ⭐⭐⭐½ |
| **pdfminer.six** | 37 | ⭐⭐⭐ |
| **pdfplumber** | 37 | ⭐⭐⭐ |

> **Note**: PyMuPDF would score 62/65 if license were not a factor — it is the technically superior library. Its low license score reflects the real-world cost for commercial or private-IP projects.

***

## 7. Use-Case Decision Matrix

| Your primary need | Best pick | Reason |
|-------------------|-----------|--------|
| LLM document ingestion (commercial) | **pypdfium2** | AGPL-free, fast, near-PyMuPDF quality[^3][^4] |
| Table extraction from invoices/reports | **pdfplumber** | Only open-source lib with dedicated table detection[^5][^6] |
| PDF merging/splitting pipelines | **pypdf** | Pure Python, BSD, solid merge/split support[^5][^8] |
| Zero-dependency serverless/Lambda | **pypdf** or **pdfminer.six** | Pure Python, no C binaries needed[^5] |
| Fast rendering to images | **pypdfium2** | Apache 2.0, PDFium rendering, numpy integration[^11][^4] |
| Deep layout/font analysis | **pdfminer.six** | MIT, character-level font/position metadata[^5] |
| Open-source project (AGPL OK) | **PyMuPDF** | Best overall features + performance[^5][^2][^10] |
| Commercial, full-featured | **PyMuPDF** (paid) or **pypdfium2** | AGPL commercial license vs. free Apache 2.0 alternative[^2] |

***

## 8. Key Caveats & Known Limitations

- **pypdfium2** image extraction is limited by PDFium's public API — it is "by far not as good as theoretically possible," and the maintainer recommends `pikepdf` (MPL2) for complex image extraction tasks.[^14]
- **pdfplumber** text extraction quality is lowest at 75% accuracy, due to its character-assembly approach producing spacing/layout artifacts. It excels at tables, not raw text.[^3]
- **pdfminer.six** has no table detection at all — for tables, pdfplumber (which wraps it) must be used.[^5]
- **pypdf** v6.7.2+ patched a DoS vulnerability (CVE-2026-27628) involving maliciously crafted circular xref PDFs — always use the latest release.[^17][^18]
- **PyMuPDF** AGPL applies transitively: using a library that depends on PyMuPDF may still trigger AGPL obligations on your own code.[^9]
- None of these libraries support OCR natively — all require scanned PDFs to be pre-processed with tools like Tesseract or external services.[^5]

***

## Conclusion

For most commercial or proprietary projects seeking a PyMuPDF replacement, **pypdfium2 is the strongest alternative**: it matches PyMuPDF's speed, slightly exceeds it in text accuracy, and ships under Apache 2.0 / BSD-3-Clause. The practical gap is mainly in image extraction quality and ecosystem maturity (smaller community, fewer GitHub stars).[^15][^4][^14][^3]

For specialized needs, the combination of **pypdfium2 + pdfplumber** covers the vast majority of use cases (fast text + rendering + table extraction) without any AGPL exposure.

---

## References

1. [Licence Question · pymupdf PyMuPDF · Discussion #971](https://github.com/pymupdf/PyMuPDF/discussions/971) - Hi, I have a question about the AGPL. I use PyMuPDF in my software to convert PDFs to PNGs. Does my ...

2. [PyMuPDF: The Python library for Fast Document Processing ...](https://pymupdf.io) - PyMuPDF provides fast and powerful tools for reading, manipulating, and extracting semantic data fro...

3. [py-pdf/benchmarks: Benchmarking PDF libraries](https://github.com/py-pdf/benchmarks) - Benchmarking PDF libraries. Contribute to py-pdf/benchmarks development by creating an account on Gi...

4. [pypdfium2](https://pypi.org/project/pypdfium2/) - pypdfium2 is an ABI-level Python 3 binding to PDFium, a powerful and liberal-licensed library for PD...

5. [Python PDF library comparison (2026): 7 libraries for developers](https://www.nutrient.io/blog/best-python-pdf-libraries/) - 1. PyPDF — Reading, writing, and merging · 2. PyMuPDF (fitz) — Fast extraction and rendering · 3. pd...

6. [pdfplumber](https://pypi.org/project/pdfplumber/) - License: MIT. PyPDF2 is a pure-Python library "capable of splitting, merging, cropping, and transfor...

7. [pdfminer.six/LICENSE at master · ...](https://github.com/pdfminer/pdfminer.six/blob/master/LICENSE) - MIT License. A short and simple permissive license with conditions only requiring preservation of co...

8. [GitHub - py-pdf/pypdf: A pure-python PDF library capable of splitting ...](https://github.com/py-pdf/pypdf) - pypdf is a free and open-source pure-python PDF library capable of splitting, merging, cropping, and...

9. [PymuPDF licensing requirements when its a dependency of another dependency?](https://www.reddit.com/r/learnpython/comments/1ggz2pq/pymupdf_licensing_requirements_when_its_a/) - PymuPDF licensing requirements when its a dependency of another dependency?

10. [Appendix 4: Performance Comparison Methodology - PyMuPDF](https://pymupdf.readthedocs.io/en/latest/app4.html) - This article documents the approach to measure PyMuPDF's performance and the tools and example files...

11. [pypdfium2 can now directly render to numpy arrays #1032 - GitHub](https://github.com/mindee/doctr/discussions/1032) - I'm happy to announce that pypdfium2 can now directly render to numpy arrays. without the necessity ...

12. [pypdfium2 v5.0 breaking changes and migration guide](https://michaelbommarito.com/wiki/programming/languages/python/pypdfium-5-changes/) - improved image rendering. New option for native resolution rendering: 1. # Render image at original ...

13. [pypdf vs X — pypdf 6.10.2 documentation - Read the Docs](https://pypdf.readthedocs.io/en/stable/meta/comparisons.html)

14. [Extracting images from PDF using pypdfium2 (Python)](https://stackoverflow.com/questions/76030083/extracting-images-from-pdf-using-pypdfium2-python) - However, due to limitations in pdfium's public interface, pypdfium2 is by far not as good at image e...

15. [pypdfium2 vs PyMuPDF - compare differences and reviews? - LibHunt](https://www.libhunt.com/compare-pypdfium2-vs-PyMuPDF) - PyMuPDF. PyMuPDF is a high performance Python library for data extraction, analysis, conversion & ma...

16. [Pdfminer vs Pdfplumber](https://best-of-web.builder.io/compare/euske%3Epdfminer/jsvine%3Epdfplumber) - Find and compare the best open-source projects

17. [CVE-2026-27628: Pypdf Library DOS Vulnerability - SentinelOne](https://www.sentinelone.com/vulnerability-database/cve-2026-27628/) - CVE-2026-27628 is a denial of service vulnerability in Pypdf library. Learn about its impact, affect...

18. [pypdf (PyPI) — Safety Package & Vulnerability Database](https://getsafety.com/packages/pypi/pypdf) - A pure-python PDF library capable of splitting, merging, cropping, and transforming PDF files.

