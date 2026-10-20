# Real reviews

Published reviews, used by `tests/test_real_reviews.py` to check the round trips on what systems
actually produce. `sources.json` lists every file with its source, URL, license and the date it
was fetched; `scripts/fetch_real_reviews.py` fetches them all again, byte for byte.

Every review here is **real** (published by its venue or its reviewer) except the HotCRP,
ScholarOne and Editorial Manager ones, which are **documented samples**: synthetic values in the
structure each system's API documents. No real HotCRP, CMT, Editorial Manager or ScholarOne
export is public.

## OpenReview (API v2 notes)

OpenReview's API asks scripts to pass a browser check, so the notes come from the forum queries
openreview.net makes, as the Internet Archive saved them. Each note is as the API returned it,
without the `details` the query asked for. In each forum's folder, `submission.json` is the
`submission` argument (from the forum's submission note) and `scale_bounds.json` the
`scale_bounds` of each kind of note, from the field definitions of the note's invitation, which
the query's `details` held. ICLR 2026's query asked for no details, so its forms' scales are
unknown and its scores are read without bounds.

All notes are licensed CC BY 4.0 (each note's own `license`), retrieved 2026-10-20.

| Forum | Venue | Notes | Archived query |
|---|---|---|---|
| [45rvZkJbuX](https://openreview.net/forum?id=45rvZkJbuX) | ICLR 2025 Poster | 1 decision, 1 meta review, 4 official reviews | [capture](https://web.archive.org/web/20250703023727id_/https://api2.openreview.net/notes?details=writable%2Csignatures%2Cinvitation%2Cpresentation%2Ctags&domain=ICLR.cc%2F2025%2FConference&forum=45rvZkJbuX&limit=1000&trash=true) |
| [SJTSvRtGsN](https://openreview.net/forum?id=SJTSvRtGsN) | ICLR 2024 Conference Withdrawn Submission | 3 official reviews | [capture](https://web.archive.org/web/20251014140351id_/https://api2.openreview.net/notes?details=writable%2Csignatures%2Cinvitation%2Cpresentation%2Ctags&domain=ICLR.cc%2F2024%2FConference&forum=SJTSvRtGsN&limit=1000&trash=true) |
| [Ti67584b98](https://openreview.net/forum?id=Ti67584b98) | COLM | 1 decision, 4 official reviews | [capture](https://web.archive.org/web/20241206132449id_/https://api2.openreview.net/notes?details=writable%2Csignatures%2Cinvitation%2Cpresentation%2Ctags&domain=colmweb.org%2FCOLM%2F2024%2FConference&forum=Ti67584b98&limit=1000&trash=true) |
| [rNsAQisgOo](https://openreview.net/forum?id=rNsAQisgOo) | Rejected by TMLR | 1 decision, 3 reviews | [capture](https://web.archive.org/web/20250113174837id_/https://api2.openreview.net/notes?details=writable%2Csignatures%2Cinvitation%2Cpresentation%2Ctags&domain=TMLR&forum=rNsAQisgOo&limit=1000&trash=true) |
| [u7m2CG84BQ](https://openreview.net/forum?id=u7m2CG84BQ) | NeurIPS 2024 Track Datasets and Benchmarks Spotlight | 1 decision, 3 official reviews | [capture](https://web.archive.org/web/20250116203208id_/https://api2.openreview.net/notes?details=writable%2Csignatures%2Cinvitation%2Cpresentation%2Ctags&domain=NeurIPS.cc%2F2024%2FDatasets_and_Benchmarks_Track&forum=u7m2CG84BQ&limit=1000&trash=true) |
| [y3oHMcoItR](https://openreview.net/forum?id=y3oHMcoItR) | ICLR 2026 Oral | 1 decision, 1 meta review, 4 official reviews | [capture](https://web.archive.org/web/20260419040827id_/https://api2.openreview.net/notes?forum=y3oHMcoItR) |
| [y8Rm4VNRPH](https://openreview.net/forum?id=y8Rm4VNRPH) | NeurIPS 2024 poster | 1 decision, 3 official reviews | [capture](https://web.archive.org/web/20250116203216id_/https://api2.openreview.net/notes?details=writable%2Csignatures%2Cinvitation%2Cpresentation%2Ctags&domain=NeurIPS.cc%2F2024%2FConference&forum=y8Rm4VNRPH&limit=1000&trash=true) |

## Journal narratives

A journal narrative is OCRS's own minimal format, not the publisher's. The review's text is the
publisher's, its paragraphs joined with a blank line (list items one to a line); the DOI of the
version reviewed, the journal, the review's own DOI (as `review_id`), the reviewer's number when
the review gives one, and the date the review was published come from the publisher's record
(for eLife, the date Crossref gives the review's DOI). What else the publisher records, such as
an eLife Assessment's significance and strength terms, an F1000 report's recommendation and
referee, has no place in the format and is not included.

| File | Review | License | Retrieved from |
|---|---|---|---|
| `journal/elife_100443_sa0.json` | [10.7554/eLife.100443.2.sa0](https://doi.org/10.7554/eLife.100443.2.sa0) (eLife) | CC BY 4.0 | [api.elifesciences.org](https://api.elifesciences.org/articles/100443) |
| `journal/elife_100443_sa1.json` | [10.7554/eLife.100443.2.sa1](https://doi.org/10.7554/eLife.100443.2.sa1) (eLife) | CC BY 4.0 | [api.elifesciences.org](https://api.elifesciences.org/articles/100443) |
| `journal/elife_100443_sa2.json` | [10.7554/eLife.100443.2.sa2](https://doi.org/10.7554/eLife.100443.2.sa2) (eLife) | CC BY 4.0 | [api.elifesciences.org](https://api.elifesciences.org/articles/100443) |
| `journal/elife_110030_sa1.json` | [10.7554/eLife.110030.3.sa1](https://doi.org/10.7554/eLife.110030.3.sa1) (eLife) | CC BY 4.0 | [api.elifesciences.org](https://api.elifesciences.org/articles/110030) |
| `journal/f1000_r367849.json` | [10.5256/f1000research.178206.r367849](https://doi.org/10.5256/f1000research.178206.r367849) (F1000Research) | CC BY 4.0 | [f1000research.com](https://f1000research.com/articles/13-970/v2/xml) |
| `journal/f1000_r413354.json` | [10.5256/f1000research.180054.r413354](https://doi.org/10.5256/f1000research.180054.r413354) (F1000Research) | CC BY 4.0 | [f1000research.com](https://f1000research.com/articles/12-1170/v3/xml) |
| `journal/f1000_r477634.json` | [10.5256/f1000research.194339.r477634](https://doi.org/10.5256/f1000research.194339.r477634) (F1000Research) | CC BY 4.0 | [f1000research.com](https://f1000research.com/articles/15-562/v1/xml) |

## OpenAIReview

`paper.json` outputs from the [ChicagoHAI/OpenAIReview](https://github.com/ChicagoHAI/OpenAIReview)
repository (MIT), at commit `436a42f`, without `paragraphs`, the paper's own text, which the
mapper does not read. Each holds two reviews, by `claude-opus-4-6` and `gemini-3.1-pro-preview`;
the tests read each. The reviews are MIT, but the papers they review are not known to be
openly licensed, so the passages the reviews quote from them are obscured (letters as x, digits
as 0, spacing and punctuation kept): each comment's `quote`, and what its title, its
explanation and the overall feedback put in quotation marks.

| File | Source |
|---|---|
| `openaireview/apep-0001-pdf.json` | [apep-0001-pdf.json](https://raw.githubusercontent.com/ChicagoHAI/OpenAIReview/436a42f0a7222ae87b5008729f0cc5b521d7e160/examples/review_results/apep-0001-pdf.json) |
| `openaireview/smoothing-shifts-pdf.json` | [smoothing-shifts-pdf.json](https://raw.githubusercontent.com/ChicagoHAI/OpenAIReview/436a42f0a7222ae87b5008729f0cc5b521d7e160/examples/review_results/smoothing-shifts-pdf.json) |

## HotCRP (documented sample)

`hotcrp/documented_api_review.json` is a review object as HotCRP's API returns it
([devel/apidoc/reviews.md](https://github.com/kohler/hotcrp/blob/3a579b7479790cd523b3cb539002eb996ed1976d/devel/apidoc/reviews.md),
`devel/openapi.json`), with the default form's fields under the UIDs HotCRP's own tests use
(`OveMer`, `RevExp`, `PapSum`, `ComAut`, `ComPC`). The values are written for OCRS.

## ScholarOne and Editorial Manager (documented samples)

`scholarone/documented_api_reviewer.json` and `editorialmanager/documented_api_reviewer.json`
are each one `result` of the `getReviewerInfoFull` web service: one reviewer's review of one
revision, with the fields of its response table. ScholarOne's are those of its
[API documentation](https://developer.scholarone.com/docs/getreviewerinfofull-copy) and
[sample call](https://developer.scholarone.com/docs/getreviewerinfofull-sample-api-call-copy);
Editorial Manager's those of Aries Systems'
[Web Services instructions](https://www.ariessys.com/wp-content/uploads/Customer-Instructions-Web-Services-and-Notification-Services.pdf)
(pp. 71–86), which differ in a few fields (`documentId` is a string; it adds `revision`,
`journalName`, `scopusId` and `reviewerRank`; it has no `commentsToEditor`, and a score sheet
answer's `numericValue` is always null). The values are written for OCRS.

Both services document their responses in XML only, though both say they return JSON. So the
JSON shape is **unverified**: whether `Response` wraps the results, whether a repeated element
(`scoreSheetCustomQuestions`, `departments`) becomes an array, and whether a question's answer
is one object or a list (the readers accept either). Unanswered questions, which ScholarOne's
sample lists without an answer, are left out. `reviewerRatingCustomQuestions` and `reviewRScore`
are the editor's rating of the reviewer, not part of the review, and the readers do not take
them.

## JATS

eLife's and F1000Research's `<sub-article>`s, as `from_jats` takes them: each article's JATS XML,
split by `ocrs.mappers.jats.sub_articles` into the sub-article (as Python's XML library writes it
back, so attribute order and namespace declarations can differ from the publisher's file) and
what the article says of itself (its version DOI, title and journal). All are licensed CC BY
4.0 (the article's license, or the report's own `<license>`), retrieved 2026-10-20.

| File | What it is | Source |
|---|---|---|
| `jats/elife_100443_sa0.json` | eLife Assessment, with its significance and strength terms | [100443.xml](https://elifesciences.org/articles/100443.xml) |
| `jats/elife_100443_sa1.json`, `jats/elife_100443_sa2.json` | Anonymous public reviews | the same |
| `jats/elife_100443_sa3.json` | The authors' response, by 13 authors, quoting the reviews | the same |
| `jats/f1000_176295_report477634.json` | Referee report, approved with reservations, with the authors' response nested in it | [15-562/v1/xml](https://f1000research.com/articles/15-562/v1/xml) |
| `jats/f1000_154672_report367849.json` | Referee report on version 2, approved | [13-970/v2/xml](https://f1000research.com/articles/13-970/v2/xml) |
| `jats/f1000_138153_report413354.json` | Referee report, not approved, with two licenses | [12-1170/v3/xml](https://f1000research.com/articles/12-1170/v3/xml) |

