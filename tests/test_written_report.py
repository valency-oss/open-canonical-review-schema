# Copyright (c) 2026 Valency Systems Inc.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the written_report schema field."""

import pytest
from jsonschema import ValidationError

from ocrs import validate_canonical


def _minimal_review(**overrides):
    """Create a minimal valid review with optional overrides."""
    review = {
        "review_id": "test_001",
        "version": "1.0.0",
        "created_at": "2025-01-15T14:30:00Z",
        "provenance": {"source_system": "test"},
        "referees": [
            {
                "referee_type": "human",
                "identity_mode": "double_blind",
                "human_referee": {},
            }
        ],
        "target": {"work_id": "internal_id:manuscript_id:paper_123", "work_type": "article"},
        "opinion": {"summary": "Test review."},
    }
    review.update(overrides)
    return review


class TestWrittenReportSchema:
    """Tests for written_report field validation."""

    def test_review_without_written_report_is_valid(self):
        """Test that reviews without written_report are still valid."""
        review = _minimal_review()
        validate_canonical(review)  # Should not raise

    def test_minimal_written_report(self):
        """Test minimal written_report with only required content_type."""
        review = _minimal_review(written_report={"content_type": "pdf"})
        validate_canonical(review)  # Should not raise

    def test_written_report_pdf_type(self):
        """Test written_report with PDF content type."""
        review = _minimal_review(
            written_report={
                "filename": "review.pdf",
                "content_type": "pdf",
                "url": "https://example.com/reviews/review.pdf",
            }
        )
        validate_canonical(review)

    def test_written_report_docx_type(self):
        """Test written_report with Word document content type."""
        review = _minimal_review(
            written_report={
                "filename": "review.docx",
                "content_type": "docx",
                "url": "https://example.com/reviews/review.docx",
            }
        )
        validate_canonical(review)

    def test_written_report_markdown_type(self):
        """Test written_report with Markdown content type."""
        review = _minimal_review(
            written_report={
                "filename": "review.md",
                "content_type": "markdown",
                "url": "https://example.com/reviews/review.md",
            }
        )
        validate_canonical(review)

    def test_written_report_txt_type(self):
        """Test written_report with plain text content type."""
        review = _minimal_review(
            written_report={
                "filename": "review.txt",
                "content_type": "txt",
                "url": "https://example.com/reviews/review.txt",
            }
        )
        validate_canonical(review)

    def test_written_report_all_fields(self):
        """Test written_report with all optional fields populated."""
        review = _minimal_review(
            written_report={
                "filename": "detailed_review.pdf",
                "content_type": "pdf",
                "url": "https://example.com/reviews/detailed_review.pdf",
                "content_hash": {
                    "algorithm": "sha256",
                    "value": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
                },
                "size_bytes": 245678,
                "uploaded_at": "2025-01-15T14:30:00Z",
                "description": "Detailed technical review with annotated figures",
            }
        )
        validate_canonical(review)

    def test_written_report_sha512_hash(self):
        """Test written_report with SHA-512 content hash."""
        review = _minimal_review(
            written_report={
                "content_type": "pdf",
                "content_hash": {
                    "algorithm": "sha512",
                    "value": "a" * 128,  # SHA-512 is 128 hex chars
                },
            }
        )
        validate_canonical(review)


class TestWrittenReportValidationErrors:
    """Tests for written_report validation error cases."""

    def test_written_report_missing_content_type_fails(self):
        """Test that written_report without content_type fails validation."""
        review = _minimal_review(written_report={"filename": "review.pdf"})
        with pytest.raises(ValidationError):
            validate_canonical(review)

    def test_written_report_invalid_content_type_fails(self):
        """Test that invalid content_type fails validation."""
        review = _minimal_review(
            written_report={"content_type": "html"}  # Not in enum
        )
        with pytest.raises(ValidationError):
            validate_canonical(review)

    def test_written_report_invalid_hash_algorithm_fails(self):
        """Test that invalid hash algorithm fails validation."""
        review = _minimal_review(
            written_report={
                "content_type": "pdf",
                "content_hash": {
                    "algorithm": "md5",  # Not allowed
                    "value": "abc123",
                },
            }
        )
        with pytest.raises(ValidationError):
            validate_canonical(review)

    def test_written_report_negative_size_fails(self):
        """Test that negative size_bytes fails validation."""
        review = _minimal_review(
            written_report={
                "content_type": "pdf",
                "size_bytes": -100,
            }
        )
        with pytest.raises(ValidationError):
            validate_canonical(review)

    def test_written_report_with_url_string(self):
        """Test that URL is accepted as a string (format is advisory in JSON Schema)."""
        # Note: JSON Schema 'format' keyword is advisory by default,
        # so invalid URLs are accepted as strings
        review = _minimal_review(
            written_report={
                "content_type": "pdf",
                "url": "https://example.com/valid.pdf",
            }
        )
        validate_canonical(review)

    def test_written_report_with_timestamp_string(self):
        """Test that date-time is accepted as a string (format is advisory in JSON Schema)."""
        # Note: JSON Schema 'format' keyword is advisory by default,
        # so the date-time format is not strictly enforced by jsonschema
        review = _minimal_review(
            written_report={
                "content_type": "pdf",
                "uploaded_at": "2025-01-15T14:30:00Z",
            }
        )
        validate_canonical(review)

    def test_written_report_extra_properties_fails(self):
        """Test that extra properties fail validation (additionalProperties: false)."""
        review = _minimal_review(
            written_report={
                "content_type": "pdf",
                "extra_field": "not allowed",
            }
        )
        with pytest.raises(ValidationError):
            validate_canonical(review)

    def test_written_report_empty_hash_value_fails(self):
        """Test that empty hash value fails validation."""
        review = _minimal_review(
            written_report={
                "content_type": "pdf",
                "content_hash": {
                    "algorithm": "sha256",
                    "value": "",  # minLength: 1
                },
            }
        )
        with pytest.raises(ValidationError):
            validate_canonical(review)
