import pytest

from app.services.validation import (
    DUPLICATE_EMAIL,
    NAME_MAX_LENGTH,
    validate_recipient,
    validate_recipients,
)


def test_valid_recipient_is_trimmed_and_lowercased():
    result = validate_recipient({"name": "  Asha Rao  ", "email": "Asha.Rao@Example.COM"})

    assert result.is_valid
    assert result.name == "Asha Rao"
    assert result.email == "asha.rao@example.com"
    assert result.error is None


@pytest.mark.parametrize("name", ["", "   ", None])
def test_blank_or_missing_name_is_invalid(name):
    result = validate_recipient({"name": name, "email": "asha@example.com"})

    assert not result.is_valid
    assert result.error == "name is required"


def test_name_over_max_length_is_invalid():
    result = validate_recipient({"name": "a" * (NAME_MAX_LENGTH + 1), "email": "a@example.com"})

    assert result.error == f"name must be at most {NAME_MAX_LENGTH} characters"


def test_name_at_max_length_is_valid():
    assert validate_recipient({"name": "a" * NAME_MAX_LENGTH, "email": "a@example.com"}).is_valid


@pytest.mark.parametrize("email", ["not-an-email", "a@", "@example.com", "a b@example.com"])
def test_bad_email_is_invalid(email):
    result = validate_recipient({"name": "Asha", "email": email})

    assert result.error == "email is not valid"


def test_missing_email_is_invalid():
    assert validate_recipient({"name": "Asha"}).error == "email is required"


def test_wrong_types_are_invalid():
    result = validate_recipient({"name": 42, "email": ["a@example.com"]})

    assert result.errors == ["name must be a string", "email must be a string"]
    assert result.name is None


def test_non_object_recipient_is_invalid():
    assert validate_recipient("Asha Rao").error == "recipient must be an object"


def test_all_problems_are_collected():
    result = validate_recipient({"name": "", "email": "not-an-email"})

    assert result.error == "name is required; email is not valid"


def test_invalid_row_keeps_values_as_received():
    result = validate_recipient({"name": "", "email": "Not-An-Email"})

    assert result.name == ""
    assert result.email == "Not-An-Email"


def test_duplicate_email_keeps_first_occurrence():
    results = validate_recipients(
        [
            {"name": "Asha", "email": "asha@example.com"},
            {"name": "Ravi", "email": "ravi@example.com"},
            {"name": "Asha Again", "email": "ASHA@example.com"},
        ]
    )

    assert [r.is_valid for r in results] == [True, True, False]
    assert results[2].error == DUPLICATE_EMAIL


def test_invalid_row_does_not_claim_its_email():
    results = validate_recipients(
        [
            {"name": "", "email": "asha@example.com"},
            {"name": "Asha", "email": "asha@example.com"},
        ]
    )

    assert results[0].error == "name is required"
    assert results[1].is_valid


def test_duplicate_is_reported_alongside_other_problems():
    results = validate_recipients(
        [
            {"name": "Asha", "email": "asha@example.com"},
            {"name": " ", "email": "asha@example.com"},
        ]
    )

    assert results[1].error == f"name is required; {DUPLICATE_EMAIL}"
