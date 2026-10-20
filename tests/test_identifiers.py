# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for identifier validation and resolution utilities."""

import pytest

from ocrs import load_schema
from ocrs.identifiers import (
    CANONICAL_WORK_ID_PATTERN,
    IDENTIFIER_PRIORITY,
    RESOLVERS,
    build_content_hash,
    build_resolver_url,
    build_work_identifiers,
    compute_content_hash,
    generate_canonical_work_id,
    normalize_orcid,
    parse_canonical_work_id,
    resolve_primary_identifier,
    validate_ark,
    validate_arxiv,
    validate_doi,
    validate_ecli,
    validate_google_scholar,
    validate_handle,
    validate_isbn,
    validate_issn,
    validate_openalex_author,
    validate_openalex_work,
    validate_orcid,
    validate_orcid_checksum,
    validate_pmcid,
    validate_scopus_author,
    validate_uuid,
    validate_valency_author,
    validate_valency_work,
)
from ocrs.util import migrate_work_id_to_identifiers, source_work_id


class TestOrcidValidation:
    """Tests for ORCID validation and normalization."""

    def test_valid_orcid_with_numeric_checksum(self):
        """Test valid ORCID with numeric checksum digit."""
        # 0000-0001-5000-0007 has checksum 7 (verified)
        assert validate_orcid("0000-0001-5000-0007")

    def test_valid_orcid_with_x_checksum(self):
        """Test valid ORCID with X checksum digit."""
        # 0000-0000-0000-001X is a valid ORCID with checksum X
        assert validate_orcid("0000-0000-0000-001X")

    def test_invalid_checksum_rejected(self):
        """Test that invalid checksums are rejected."""
        # Wrong checksum (should be 7, not 8)
        assert not validate_orcid("0000-0001-5000-0008")

    def test_invalid_format_rejected(self):
        """Test that invalid formats are rejected."""
        assert not validate_orcid("0000-0001-5000")  # Too short
        assert not validate_orcid("0000-0001-5000-00007")  # Too long
        assert not validate_orcid("000000015000007")  # No hyphens
        assert not validate_orcid("0000-0001-5000-000Z")  # Invalid char

    def test_checksum_algorithm(self):
        """Test the checksum algorithm directly."""
        # Valid ORCIDs with their correct checksums (verified)
        assert validate_orcid_checksum("0000-0000-0000-001X")  # X checksum
        assert validate_orcid_checksum("0000-0001-5000-0007")  # 7 checksum
        assert not validate_orcid_checksum("0000-0001-5000-0008")  # Wrong checksum

    def test_normalize_standard_format(self):
        """Test normalization of standard ORCID format."""
        assert normalize_orcid("0000-0001-5000-0007") == "0000-0001-5000-0007"

    def test_normalize_url_format(self):
        """Test normalization from URL format."""
        assert normalize_orcid("https://orcid.org/0000-0001-5000-0007") == "0000-0001-5000-0007"
        assert normalize_orcid("http://orcid.org/0000-0001-5000-0007") == "0000-0001-5000-0007"

    def test_normalize_no_hyphens(self):
        """Test normalization from format without hyphens."""
        # 0000-0001-5000-0007 without hyphens
        assert normalize_orcid("0000000150000007") == "0000-0001-5000-0007"

    def test_normalize_lowercase_x(self):
        """Test normalization handles lowercase X."""
        # 0000-0000-0000-001X with lowercase x
        assert normalize_orcid("0000-0000-0000-001x") == "0000-0000-0000-001X"

    def test_normalize_invalid_returns_none(self):
        """Test normalization of invalid ORCID returns None."""
        assert normalize_orcid("invalid") is None
        assert normalize_orcid("0000-0001-5000-0008") is None  # Invalid checksum


class TestDoiValidation:
    """Tests for DOI validation."""

    def test_valid_doi(self):
        """Test valid DOI patterns."""
        assert validate_doi("10.1234/example.2024")
        assert validate_doi("10.12345/foo-bar.123")
        assert validate_doi("10.1000/xyz-123")

    def test_invalid_doi_wrong_prefix(self):
        """Test DOI with wrong prefix is rejected."""
        assert not validate_doi("9.1234/wrong")
        assert not validate_doi("11.1234/wrong")

    def test_invalid_doi_no_suffix(self):
        """Test DOI without suffix is rejected."""
        assert not validate_doi("10.1234/")
        assert not validate_doi("10.1234")


class TestArxivValidation:
    """Tests for arXiv identifier validation."""

    def test_modern_format(self):
        """Test modern arXiv format (YYMM.NNNNN)."""
        assert validate_arxiv("2401.12345")
        assert validate_arxiv("2312.01234")

    def test_modern_format_with_version(self):
        """Test modern format with version number."""
        assert validate_arxiv("2401.12345v2")
        assert validate_arxiv("2401.12345v10")

    def test_legacy_format(self):
        """Test legacy arXiv format (category/YYMMNNN)."""
        assert validate_arxiv("hep-th/9901001")
        assert validate_arxiv("astro-ph/0001001")

    def test_invalid_arxiv(self):
        """Test invalid arXiv identifiers."""
        assert not validate_arxiv("2401.123")  # Too few digits (only 3)
        assert not validate_arxiv("240.12345")  # Wrong year format
        assert not validate_arxiv("invalid")
        assert not validate_arxiv("2401.123456")  # Too many digits (6)


class TestPmcidValidation:
    """Tests for PubMed Central ID validation."""

    def test_valid_pmcid(self):
        """Test valid PMCID formats."""
        assert validate_pmcid("PMC5555555")
        assert validate_pmcid("PMC123456789")

    def test_invalid_pmcid(self):
        """Test invalid PMCID formats."""
        assert not validate_pmcid("pmc5555555")  # Lowercase
        assert not validate_pmcid("5555555")  # No prefix
        assert not validate_pmcid("PMCABC")  # Non-numeric


class TestOpenalexValidation:
    """Tests for OpenAlex identifier validation."""

    def test_valid_work_id(self):
        """Test valid OpenAlex Work IDs."""
        assert validate_openalex_work("W2741809807")
        assert validate_openalex_work("W123")

    def test_valid_author_id(self):
        """Test valid OpenAlex Author IDs."""
        assert validate_openalex_author("A5023888391")
        assert validate_openalex_author("A123")

    def test_invalid_openalex(self):
        """Test invalid OpenAlex IDs."""
        assert not validate_openalex_work("A123")  # Wrong prefix for work
        assert not validate_openalex_author("W123")  # Wrong prefix for author
        assert not validate_openalex_work("W")  # No number


VALENCY_WORK_IDS = ["W_6r533gdt", "W_6r533gdt_v1", "W_6r533gdt_v12", "W_k7pm3xn2ab"]
NOT_VALENCY_WORK_IDS = [
    "W_6r533gd",  # 7 characters
    "W_6r533gdi",  # i is not in the alphabet
    "W_6r533gd0",  # nor is 0
    "W_6R533GDT",  # upper case
    "W_6r533gdt_v0",  # versions start at 1
    "A_7zdytxzb",  # an author
    "W2741809807",  # an OpenAlex work
]


class TestValencyValidation:
    """Tests for Valency Hub identifier validation."""

    @pytest.mark.parametrize("value", VALENCY_WORK_IDS)
    def test_valid_work_id(self, value):
        assert validate_valency_work(value)

    @pytest.mark.parametrize("value", NOT_VALENCY_WORK_IDS)
    def test_invalid_work_id(self, value):
        assert not validate_valency_work(value)

    def test_author_id(self):
        assert validate_valency_author("A_7zdytxzb")
        assert not validate_valency_author("A_7zdytxzb_v1")  # authors have no versions
        assert not validate_valency_author("W_6r533gdt")
        assert not validate_valency_author("A5023888391")

    @pytest.mark.parametrize("value", VALENCY_WORK_IDS + NOT_VALENCY_WORK_IDS)
    def test_schema_work_pattern_matches_python(self, value):
        import re

        identifiers = load_schema()["$defs"]["workIdentifiers"]["properties"]
        schema_pattern = identifiers["valency_id"]["properties"]["value"]["pattern"]
        assert bool(re.match(schema_pattern, value)) == validate_valency_work(value)

    @pytest.mark.parametrize("value", ["A_7zdytxzb", "A_7zdytxz", "A_7zdytxzl", "W_6r533gdt"])
    def test_schema_author_pattern_matches_python(self, value):
        import re

        human_referee = load_schema()["$defs"]["humanReferee"]["properties"]
        schema_pattern = human_referee["valency_id"]["pattern"]
        assert bool(re.match(schema_pattern, value)) == validate_valency_author(value)

    def test_review_of_a_hub_work_validates(self):
        from ocrs import validate_canonical

        validate_canonical(
            {
                "review_id": "review-1",
                "version": "1.0.0",
                "created_at": "2026-10-17T12:00:00Z",
                "provenance": {"source_system": "valency-hub"},
                "referees": [
                    {
                        "referee_type": "human",
                        "identity_mode": "open",
                        "human_referee": {"valency_id": "A_7zdytxzb"},
                    }
                ],
                "target": {
                    "work_id": "valency_id:W_6r533gdt_v1",
                    "work_type": "preprint",
                    "identifiers": build_work_identifiers(valency_id="W_6r533gdt_v1"),
                },
                "opinion": {"summary": "A sound paper."},
            }
        )


class TestScopusValidation:
    """Tests for Scopus Author ID validation."""

    def test_valid_scopus_id(self):
        """Test valid Scopus Author IDs (10-12 digits)."""
        assert validate_scopus_author("1234567890")  # 10 digits
        assert validate_scopus_author("12345678901")  # 11 digits
        assert validate_scopus_author("123456789012")  # 12 digits

    def test_invalid_scopus_id(self):
        """Test invalid Scopus Author IDs."""
        assert not validate_scopus_author("123456789")  # 9 digits
        assert not validate_scopus_author("0123456789")  # Leading zero
        assert not validate_scopus_author("1234567890123")  # 13 digits


class TestGoogleScholarValidation:
    """Tests for Google Scholar ID validation."""

    def test_valid_gs_id(self):
        """Test valid Google Scholar IDs (12 chars)."""
        assert validate_google_scholar("aB3_cD4-eF5g")
        assert validate_google_scholar("123456789012")

    def test_invalid_gs_id(self):
        """Test invalid Google Scholar IDs."""
        assert not validate_google_scholar("too_short")
        assert not validate_google_scholar("this_is_too_long")


class TestCrossrefIdentifierValidation:
    """Tests for the identifier types added to match Crossref's."""

    def test_valid_handle(self):
        """Test valid Handles, including derived prefixes."""
        assert validate_handle("1721.1/12345")
        assert validate_handle("20.500.12345/abc-def")

    def test_invalid_handle(self):
        """Test invalid Handles."""
        assert not validate_handle("hdl:1721.1/12345")
        assert not validate_handle("1721.1")
        assert not validate_handle("abc/123")

    def test_valid_ark(self):
        """Test ARKs with and without the slash after the label."""
        assert validate_ark("ark:/13030/tf5p30086k")
        assert validate_ark("ark:13030/tf5p30086k")

    def test_invalid_ark(self):
        """Test invalid ARKs."""
        assert not validate_ark("13030/tf5p30086k")
        assert not validate_ark("https://n2t.net/ark:/13030/tf5p30086k")
        assert not validate_ark("ark:/13030")

    def test_valid_isbn(self):
        """Test ISBN-13 and ISBN-10 with correct check digits."""
        assert validate_isbn("9780262035613")
        assert validate_isbn("0262035618")
        assert validate_isbn("080442957X")

    def test_invalid_isbn(self):
        """Test ISBNs with hyphens, wrong check digits or wrong length."""
        assert not validate_isbn("978-0-262-03561-3")
        assert not validate_isbn("9780262035614")
        assert not validate_isbn("0262035619")
        assert not validate_isbn("12345")

    def test_valid_issn(self):
        """Test ISSNs, including an X check character."""
        assert validate_issn("2050-084X")
        assert validate_issn("0028-0836")

    def test_invalid_issn(self):
        """Test ISSNs with a wrong check character or no hyphen."""
        assert not validate_issn("2050-0841")
        assert not validate_issn("2050084X")

    def test_valid_ecli(self):
        """Test valid ECLIs."""
        assert validate_ecli("ECLI:EU:C:2014:317")
        assert validate_ecli("ECLI:NL:HR:2009:BH1234")

    def test_invalid_ecli(self):
        """Test invalid ECLIs."""
        assert not validate_ecli("EU:C:2014:317")
        assert not validate_ecli("ECLI:EU:C:14:317")
        assert not validate_ecli("ecli:eu:c:2014:317")

    def test_valid_uuid(self):
        """Test valid UUIDs in either case."""
        assert validate_uuid("123e4567-e89b-12d3-a456-426614174000")
        assert validate_uuid("123E4567-E89B-12D3-A456-426614174000")

    def test_invalid_uuid(self):
        """Test UUIDs without hyphens or with non-hex characters."""
        assert not validate_uuid("123e4567e89b12d3a456426614174000")
        assert not validate_uuid("123e4567-e89b-12d3-a456-42661417400g")


class TestResolutionPriority:
    """Tests for identifier resolution priority."""

    def test_doi_takes_precedence(self):
        """Test that DOI has highest priority."""
        ids = {
            "doi": {"value": "10.1234/x"},
            "arxiv_id": {"value": "2401.00001"},
            "internal_id": {"field_name": "x", "value": "123"},
        }
        id_type, value = resolve_primary_identifier(ids)
        assert id_type == "doi"
        assert value == "10.1234/x"

    def test_arxiv_before_internal(self):
        """Test that arXiv has priority over internal_id."""
        ids = {
            "arxiv_id": {"value": "2401.00001"},
            "internal_id": {"field_name": "x", "value": "123"},
        }
        id_type, value = resolve_primary_identifier(ids)
        assert id_type == "arxiv_id"
        assert value == "2401.00001"

    def test_internal_id_fallback(self):
        """Test internal_id used as fallback."""
        ids = {"internal_id": {"field_name": "hotcrp_pid", "value": "42"}}
        id_type, value = resolve_primary_identifier(ids)
        assert id_type == "internal_id"
        assert value == "42"

    def test_permalink_resolution(self):
        """Test permalink (string value) resolution."""
        ids = {"permalink": "https://example.com/paper/123"}
        id_type, value = resolve_primary_identifier(ids)
        assert id_type == "permalink"
        assert value == "https://example.com/paper/123"

    def test_empty_identifiers(self):
        """Test empty identifiers returns unknown."""
        id_type, value = resolve_primary_identifier({})
        assert id_type == "unknown"
        assert value is None

    def test_priority_order_complete(self):
        """Test the complete priority order list."""
        expected = [
            "doi",
            "arxiv_id",
            "s2cid",
            "pubmed_id",
            "pmcid",
            "openalex_id",
            "valency_id",
            "handle",
            "ark",
            "isbn",
            "ecli",
            "accession",
            "purl",
            "permalink",
            "uuid",
            "internal_id",
        ]
        assert IDENTIFIER_PRIORITY == expected

    def test_purl_resolution(self):
        """Test purl (string value) resolution, ahead of permalink."""
        ids = {"purl": "https://purl.org/example/1", "permalink": "https://example.com/1"}
        assert resolve_primary_identifier(ids) == ("purl", "https://purl.org/example/1")

    def test_handle_before_uuid(self):
        """Test that a resolvable Handle outranks an opaque UUID."""
        ids = {
            "uuid": {"value": "123e4567-e89b-12d3-a456-426614174000"},
            "handle": {"value": "1721.1/12345"},
        }
        assert resolve_primary_identifier(ids) == ("handle", "1721.1/12345")

    def test_issn_is_never_primary(self):
        """Test that an ISSN alone does not identify the work."""
        ids = {"issn": {"value": "2050-084X"}}
        assert resolve_primary_identifier(ids) == ("unknown", None)


class TestCanonicalWorkId:
    """Tests for canonical work ID generation."""

    def test_doi_canonical_id(self):
        """Test canonical ID from DOI."""
        ids = {"doi": {"value": "10.1234/example"}}
        assert generate_canonical_work_id(ids) == "doi:10.1234/example"

    def test_arxiv_canonical_id(self):
        """Test canonical ID from arXiv."""
        ids = {"arxiv_id": {"value": "2401.12345"}}
        assert generate_canonical_work_id(ids) == "arxiv_id:2401.12345"

    def test_internal_canonical_id(self):
        """Test canonical ID from internal_id keeps the field name."""
        ids = {"internal_id": {"field_name": "pid", "value": "42"}}
        assert generate_canonical_work_id(ids) == "internal_id:pid:42"

    def test_empty_returns_unknown(self):
        """Test empty identifiers returns unknown."""
        assert generate_canonical_work_id({}) == "unknown"

    def test_parse_canonical_work_id(self):
        """Test splitting canonical IDs into type, field name and value."""
        assert parse_canonical_work_id("doi:10.1234/a:b") == ("doi", None, "10.1234/a:b")
        assert parse_canonical_work_id("internal_id:pid:42") == ("internal_id", "pid", "42")
        assert parse_canonical_work_id("unknown") is None
        assert parse_canonical_work_id("paper-1") is None
        assert parse_canonical_work_id("issn:2050-084X") is None

    def test_canonical_ids_round_trip_through_parse(self):
        """Test that every generated ID parses back to its identifier."""
        for ids, expected in [
            ({"doi": {"value": "10.1234/x"}}, ("doi", None, "10.1234/x")),
            ({"purl": "https://purl.org/x"}, ("purl", None, "https://purl.org/x")),
            ({"internal_id": {"field_name": "pid", "value": "4:2"}}, ("internal_id", "pid", "4:2")),
        ]:
            assert parse_canonical_work_id(generate_canonical_work_id(ids)) == expected

    @pytest.mark.parametrize(
        "work_id",
        [
            "doi:10.1234/x",
            "internal_id:paperId:42",
            "uuid:123e4567-e89b-12d3-a456-426614174000",
            "valency_id:W_6r533gdt",
            "valency_id:W_6r533gdt_v2",
            "unknown",
            "paper-1",
            "internal_id:42",
            "issn:2050-084X",
            "doi:",
            "doi: 10.1234/x",
        ],
    )
    def test_schema_pattern_matches_python_pattern(self, work_id):
        """Test that the schema's work_id pattern agrees with CANONICAL_WORK_ID_PATTERN."""
        import re

        schema_pattern = load_schema()["properties"]["target"]["properties"]["work_id"]["pattern"]
        in_python = work_id == "unknown" or bool(CANONICAL_WORK_ID_PATTERN.match(work_id))
        assert bool(re.match(schema_pattern, work_id)) == in_python


class TestResolverUrl:
    """Tests for resolver URL generation."""

    def test_doi_resolver(self):
        """Test DOI resolver URL."""
        url = build_resolver_url("doi", "10.1234/example")
        assert url == "https://doi.org/10.1234/example"

    def test_arxiv_resolver(self):
        """Test arXiv resolver URL."""
        url = build_resolver_url("arxiv_id", "2401.12345")
        assert url == "https://arxiv.org/abs/2401.12345"

    def test_pubmed_resolver(self):
        """Test PubMed resolver URL."""
        url = build_resolver_url("pubmed_id", "12345678")
        assert url == "https://pubmed.ncbi.nlm.nih.gov/12345678"

    def test_pmcid_resolver(self):
        """Test PMCID resolver URL."""
        url = build_resolver_url("pmcid", "PMC5555555")
        assert url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC5555555"

    def test_openalex_resolver(self):
        """Test OpenAlex resolver URL."""
        url = build_resolver_url("openalex_id", "W12345")
        assert url == "https://openalex.org/W12345"

    def test_s2cid_resolver(self):
        """Test Semantic Scholar resolver URL."""
        url = build_resolver_url("s2cid", "12345678")
        assert url == "https://api.semanticscholar.org/CorpusID:12345678"

    def test_orcid_resolver(self):
        """Test ORCID resolver URL."""
        url = build_resolver_url("orcid", "0000-0001-5000-0007")
        assert url == "https://orcid.org/0000-0001-5000-0007"

    def test_unknown_type_returns_none(self):
        """Test unknown identifier type returns None."""
        assert build_resolver_url("unknown_type", "value") is None


class TestBuildWorkIdentifiers:
    """Tests for work identifiers construction."""

    def test_build_doi_only(self):
        """Test building identifiers with DOI only."""
        ids = build_work_identifiers(doi="10.1234/example")
        assert ids["doi"]["value"] == "10.1234/example"
        assert ids["doi"]["hyperlink"] == "https://doi.org/10.1234/example"

    def test_build_multiple_identifiers(self):
        """Test building with multiple identifiers."""
        ids = build_work_identifiers(
            doi="10.1234/example",
            arxiv_id="2401.12345",
            pubmed_id="12345678",
        )
        assert "doi" in ids
        assert "arxiv_id" in ids
        assert "pubmed_id" in ids
        assert ids["arxiv_id"]["hyperlink"] == "https://arxiv.org/abs/2401.12345"

    def test_build_with_internal_id(self):
        """Test building with internal_id."""
        ids = build_work_identifiers(internal_field_name="hotcrp_pid", internal_value="42")
        assert ids["internal_id"]["field_name"] == "hotcrp_pid"
        assert ids["internal_id"]["value"] == "42"

    def test_build_with_permalink(self):
        """Test building with permalink."""
        ids = build_work_identifiers(permalink="https://example.com/paper/123")
        assert ids["permalink"] == "https://example.com/paper/123"

    def test_build_with_crossref_identifier_types(self):
        """Test building with the identifier types added to match Crossref's."""
        ids = build_work_identifiers(
            handle="1721.1/12345",
            ark="ark:/13030/tf5p30086k",
            isbn="9780262035613",
            issn="2050-084X",
            ecli="ECLI:EU:C:2014:317",
            accession="MN908947",
            accession_database="GenBank",
            purl="https://purl.org/example/1",
            uuid="123e4567-e89b-12d3-a456-426614174000",
        )
        assert ids["handle"]["hyperlink"] == "https://hdl.handle.net/1721.1/12345"
        assert ids["ark"]["hyperlink"] == "https://n2t.net/ark:/13030/tf5p30086k"
        assert ids["issn"]["hyperlink"] == "https://portal.issn.org/resource/ISSN/2050-084X"
        assert ids["isbn"] == {"value": "9780262035613"}
        assert ids["ecli"] == {"value": "ECLI:EU:C:2014:317"}
        assert ids["accession"] == {"value": "MN908947", "database": "GenBank"}
        assert ids["purl"] == "https://purl.org/example/1"
        assert ids["uuid"] == {"value": "123e4567-e89b-12d3-a456-426614174000"}

    def test_build_with_valency_id(self):
        ids = build_work_identifiers(arxiv_id="2401.12345", valency_id="W_6r533gdt_v2")
        assert ids["valency_id"] == {
            "value": "W_6r533gdt_v2",
            "hyperlink": "https://hub.valency.io/works/W_6r533gdt_v2",
        }
        assert generate_canonical_work_id(ids) == "arxiv_id:2401.12345"
        del ids["arxiv_id"]
        assert generate_canonical_work_id(ids) == "valency_id:W_6r533gdt_v2"

    def test_build_empty_raises(self):
        """Test that building with no identifiers raises."""
        with pytest.raises(ValueError, match="At least one identifier"):
            build_work_identifiers()


class TestContentHashing:
    """Tests for content hash computation."""

    def test_sha256_hash(self):
        """Test SHA-256 hash computation."""
        content = b"Hello, World!"
        result = compute_content_hash(content, "sha256")
        assert len(result) == 64  # SHA-256 produces 64 hex chars
        # Known hash for "Hello, World!"
        assert result == "dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f"

    def test_sha512_hash(self):
        """Test SHA-512 hash computation."""
        content = b"Hello, World!"
        result = compute_content_hash(content, "sha512")
        assert len(result) == 128  # SHA-512 produces 128 hex chars

    def test_unsupported_algorithm_raises(self):
        """Test that unsupported algorithm raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported hash algorithm"):
            compute_content_hash(b"test", "sha1")

    def test_md5_unsupported(self):
        """Test that MD5 is no longer supported (security concern)."""
        with pytest.raises(ValueError, match="Unsupported hash algorithm"):
            compute_content_hash(b"test", "md5")

    def test_build_content_hash_object(self):
        """Test building content_hash object for schema."""
        content = b"test content"
        result = build_content_hash(content, "sha256")
        assert result["algorithm"] == "sha256"
        assert "value" in result
        assert len(result["value"]) == 64


class TestResolversDict:
    """Tests for resolver URL dictionary."""

    def test_all_expected_resolvers_present(self):
        """Test that all expected resolvers are defined."""
        expected_keys = {
            "doi",
            "arxiv_id",
            "pubmed_id",
            "pmcid",
            "openalex_id",
            "valency_id",
            "valency_author_id",
            "s2cid",
            "orcid",
            "handle",
            "ark",
            "issn",
        }
        assert expected_keys.issubset(set(RESOLVERS.keys()))

    def test_resolver_urls_are_valid(self):
        """Test that resolver URLs have valid format."""
        for key, url in RESOLVERS.items():
            assert url.startswith("https://") or url.startswith("http://"), (
                f"Resolver {key} URL should be HTTPS/HTTP"
            )


class TestWorkIdHelpers:
    """Tests for reading identifiers back out of a work ID."""

    def test_migrate_reads_canonical_ids(self):
        """Test that a canonical work ID becomes that identifier, not an internal_id."""
        assert migrate_work_id_to_identifiers("doi:10.1234/x") == {
            "doi": {"value": "10.1234/x", "hyperlink": "https://doi.org/10.1234/x"}
        }
        assert migrate_work_id_to_identifiers("internal_id:pid:42") == {
            "internal_id": {"field_name": "pid", "value": "42"}
        }
        assert migrate_work_id_to_identifiers("purl:https://purl.org/x") == {
            "purl": "https://purl.org/x"
        }

    def test_migrate_reads_hub_work_pages(self):
        """Test that a Hub work page or citation becomes a Valency ID, and other Hub URLs stay
        permalinks."""
        for url, value in [
            ("https://hub.valency.io/works/W_6r533gdt", "W_6r533gdt"),
            ("https://hub.valency.io/works/W_6r533gdt_v2/", "W_6r533gdt_v2"),
            ("https://hub.valency.io/works/W_6r533gdt?utm_source=share", "W_6r533gdt"),
            ("https://hub.valency.io/works/W_6r533gdt#abstract", "W_6r533gdt"),
            ("https://hub.valency.io/works/W_6r533gdt_v2/?tab=details#refs", "W_6r533gdt_v2"),
        ]:
            assert migrate_work_id_to_identifiers(url) == {
                "valency_id": {"value": value, "hyperlink": url}
            }
        for url in [
            "https://hub.valency.io/works/W_6r533gdt/figures",
            "https://hub.valency.io/authors/A_7zdytxzb",
        ]:
            assert migrate_work_id_to_identifiers(url) == {"permalink": url}
        assert migrate_work_id_to_identifiers("vlnc:W_6r533gdt_v2") == {
            "valency_id": {
                "value": "W_6r533gdt_v2",
                "hyperlink": "https://hub.valency.io/works/W_6r533gdt_v2",
            }
        }
        # A citation of another kind of Hub entity is not a work
        assert migrate_work_id_to_identifiers("vlnc:A_7zdytxzb", "hub") == {
            "internal_id": {"field_name": "hub", "value": "vlnc:A_7zdytxzb"}
        }
        assert migrate_work_id_to_identifiers("valency_id:W_6r533gdt") == {
            "valency_id": {
                "value": "W_6r533gdt",
                "hyperlink": "https://hub.valency.io/works/W_6r533gdt",
            }
        }

    def test_migrate_still_reads_bare_ids(self):
        """Test the existing DOI, URL and fallback detection."""
        assert "doi" in migrate_work_id_to_identifiers("10.1234/x")
        assert migrate_work_id_to_identifiers("paper-1", "example-platform") == {
            "internal_id": {"field_name": "example-platform", "value": "paper-1"}
        }

    def test_source_work_id_prefers_internal_id(self):
        """Test that the source system's own ID comes from identifiers.internal_id."""
        target = {
            "work_id": "doi:10.1234/x",
            "identifiers": {
                "doi": {"value": "10.1234/x"},
                "internal_id": {"field_name": "paperId", "value": "42"},
            },
        }
        assert source_work_id(target) == "42"

    def test_source_work_id_from_work_id(self):
        """Test falling back to the value in work_id, or a pre-0.5 free-form work_id."""
        assert source_work_id({"work_id": "internal_id:pid:42"}) == "42"
        assert source_work_id({"work_id": "doi:10.1234/x"}) == "10.1234/x"
        assert source_work_id({"work_id": "paper-1"}) == "paper-1"
        assert source_work_id({"work_id": "unknown"}) is None
